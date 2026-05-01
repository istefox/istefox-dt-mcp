"""Local HTTP webhook receiver for DT4 smart-rule events.

DT4 smart rules can run AppleScript on record create / modify /
delete. The accompanying script POSTs a JSON payload to this
listener; we put it on an asyncio.Queue and the consumer task
pushes it through the RAG provider.

Stdlib only — `http.server` in a daemon thread, queue bridges to
the main asyncio loop. No new deps. Intentional simplicity:
loopback only, optional Bearer token for the smart-rule script.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue as queuelib
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

log = structlog.get_logger(__name__)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 27205  # picked to avoid clashing with other Stefano-stack services
DEFAULT_PATH = "/sync-event"


class _Handler(BaseHTTPRequestHandler):
    """One request handler instance per connection."""

    server_version = "istefox-webhook/0.0.6"

    # Injected by WebhookListener.start()
    events_queue: queuelib.Queue[dict[str, Any]]
    auth_token: str | None
    accept_path: str

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Silence the noisy default access log; structlog covers it
        return

    def _reply(self, status: HTTPStatus, body: dict[str, Any] | None = None) -> None:
        payload = json.dumps(body or {"status": status.phrase}).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        if self.path != self.accept_path:
            self._reply(HTTPStatus.NOT_FOUND, {"error": "unknown_path"})
            return

        if self.auth_token:
            header = self.headers.get("Authorization") or ""
            if header != f"Bearer {self.auth_token}":
                self._reply(HTTPStatus.UNAUTHORIZED, {"error": "auth"})
                return

        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > 16 * 1024:
            self._reply(HTTPStatus.BAD_REQUEST, {"error": "empty_or_too_large"})
            return

        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._reply(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return

        action = str(payload.get("action") or "")
        uuid = str(payload.get("uuid") or "")
        database = str(payload.get("database") or "")
        if action not in {"created", "modified", "deleted"} or not uuid:
            self._reply(HTTPStatus.BAD_REQUEST, {"error": "schema"})
            return

        try:
            self.events_queue.put_nowait(
                {"action": action, "uuid": uuid, "database": database}
            )
        except queuelib.Full:
            self._reply(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "queue_full"})
            return

        log.debug("webhook_event_received", action=action, uuid=uuid)
        self._reply(HTTPStatus.ACCEPTED, {"status": "queued"})


class WebhookListener:
    """Wraps a ThreadingHTTPServer + bounded queue."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        path: str = DEFAULT_PATH,
        auth_token: str | None = None,
        max_queue: int = 1024,
    ) -> None:
        self._host = host
        self._port = port
        self._path = path
        self._auth_token = auth_token or os.environ.get("ISTEFOX_WEBHOOK_TOKEN")
        self.events: queuelib.Queue[dict[str, Any]] = queuelib.Queue(maxsize=max_queue)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("WebhookListener already started")

        # Inject context into the handler class via a subclass per instance
        listener = self
        accept_path = self._path
        token = self._auth_token

        class BoundHandler(_Handler):
            pass

        BoundHandler.events_queue = listener.events
        BoundHandler.auth_token = token
        BoundHandler.accept_path = accept_path

        self._server = ThreadingHTTPServer((self._host, self._port), BoundHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="istefox-webhook", daemon=True
        )
        self._thread.start()
        log.info(
            "webhook_listening",
            host=self._host,
            port=self._port,
            path=self._path,
            auth_required=bool(token),
        )

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._server = None
        self._thread = None
        log.info("webhook_stopped")


async def consume_events(
    listener: WebhookListener,
    process_event: Callable[[dict[str, Any]], Awaitable[None]],
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Drain the listener queue and dispatch to `process_event(event)`.

    `process_event` is an async callable. The consumer runs until
    `stop_event` is set (or forever if None).
    """
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            event = await asyncio.to_thread(listener.events.get, True, 1.0)
        except queuelib.Empty:
            continue
        try:
            await process_event(event)
        except Exception as e:
            log.warning("webhook_event_failed", event=event, error=str(e))
