"""WebhookListener — POST handling, auth, schema, queue."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

import pytest
from istefox_dt_mcp_server.webhook import WebhookListener


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _post(url: str, body: dict, headers: dict | None = None) -> tuple[int, bytes]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture
def listener():
    port = _free_port()
    li = WebhookListener(port=port)
    li.start()
    try:
        yield li, port
    finally:
        li.stop()


def test_valid_event_returns_202_and_queued(listener) -> None:
    li, port = listener
    status, _ = _post(
        f"http://127.0.0.1:{port}/sync-event",
        {"action": "created", "uuid": "abc", "database": "Business"},
    )
    assert status == 202
    event = li.events.get(timeout=1)
    assert event["uuid"] == "abc"
    assert event["action"] == "created"


def test_invalid_action_rejected(listener) -> None:
    _li, port = listener
    status, _ = _post(
        f"http://127.0.0.1:{port}/sync-event",
        {"action": "wrong", "uuid": "abc"},
    )
    assert status == 400


def test_missing_uuid_rejected(listener) -> None:
    _li, port = listener
    status, _ = _post(
        f"http://127.0.0.1:{port}/sync-event",
        {"action": "modified"},
    )
    assert status == 400


def test_unknown_path_404(listener) -> None:
    _li, port = listener
    status, _ = _post(
        f"http://127.0.0.1:{port}/other",
        {"action": "created", "uuid": "u"},
    )
    assert status == 404


def test_invalid_json_rejected(listener) -> None:
    _li, port = listener
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/sync-event",
        data=b"not json",
        method="POST",
        headers={"Content-Type": "application/json", "Content-Length": "8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 400


def test_auth_required_when_token_set() -> None:
    port = _free_port()
    li = WebhookListener(port=port, auth_token="secret")
    li.start()
    try:
        # without token
        status, _ = _post(
            f"http://127.0.0.1:{port}/sync-event",
            {"action": "created", "uuid": "u"},
        )
        assert status == 401

        # with wrong token
        status, _ = _post(
            f"http://127.0.0.1:{port}/sync-event",
            {"action": "created", "uuid": "u"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert status == 401

        # with correct token
        status, _ = _post(
            f"http://127.0.0.1:{port}/sync-event",
            {"action": "created", "uuid": "u"},
            headers={"Authorization": "Bearer secret"},
        )
        assert status == 202
    finally:
        li.stop()
