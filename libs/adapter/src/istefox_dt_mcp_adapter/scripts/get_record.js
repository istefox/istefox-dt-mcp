// Fetch a single record by UUID.
// argv: [uuid]
// stdout: JSON object matching schemas.common.Record, or {error: "RECORD_NOT_FOUND"}
//
// Defensive: every property access is wrapped in safe() because DT
// can throw -1700 errAECoercionFail on records of unusual kind, and
// getRecordWithUuid raises on UUIDs that don't resolve. Without
// these guards the script crashes and the caller sees an opaque
// JXA_ERROR instead of a structured RECORD_NOT_FOUND.

function run(argv) {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  function safe(fn, def) {
    try {
      var v = fn();
      return v === undefined || v === null ? def : v;
    } catch (e) {
      return def;
    }
  }
  function safeStr(fn) { return String(safe(fn, "") || ""); }

  var uuid = argv[0];
  var record = safe(function() { return DT.getRecordWithUuid(uuid); }, null);

  if (!record) {
    return JSON.stringify({error: "RECORD_NOT_FOUND"});
  }

  function iso(fn) {
    var d = safe(fn, null);
    return d ? d.toISOString() : null;
  }

  // referenceUrl() may return empty for special record types (smart
  // group, feed item, missing file placeholder). Fall back to the
  // canonical x-devonthink-item:// constructed from uuid so callers
  // always get a usable deep link. Same pattern as search_bm25.js
  // and find_related.js — keep them consistent or get_record vs
  // search round-trips will mismatch (see test_get_record_round_trip).
  var uuidStr = safeStr(function() { return record.uuid(); });
  var refUrl = safeStr(function() { return record.referenceUrl(); });
  if (!refUrl && uuidStr) refUrl = "x-devonthink-item://" + uuidStr;

  return JSON.stringify({
    uuid: uuidStr,
    name: safeStr(function() { return record.name(); }),
    kind: safeStr(function() { return record.type(); }),
    location: safeStr(function() { return record.location(); }),
    path: safe(function() { return record.path(); }, null),
    reference_url: refUrl,
    creation_date: iso(function() { return record.creationDate(); }),
    modification_date: iso(function() { return record.modificationDate(); }),
    tags: safe(function() { return record.tags(); }, []),
    size_bytes: safe(function() { return record.size(); }, null),
    word_count: safe(function() { return record.wordCount(); }, null)
  });
}
