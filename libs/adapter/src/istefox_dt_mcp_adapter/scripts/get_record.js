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

  return JSON.stringify({
    uuid: safeStr(function() { return record.uuid(); }),
    name: safeStr(function() { return record.name(); }),
    kind: safeStr(function() { return record.type(); }),
    location: safeStr(function() { return record.location(); }),
    path: safe(function() { return record.path(); }, null),
    reference_url: safeStr(function() { return record.referenceUrl(); }),
    creation_date: iso(function() { return record.creationDate(); }),
    modification_date: iso(function() { return record.modificationDate(); }),
    tags: safe(function() { return record.tags(); }, []),
    size_bytes: safe(function() { return record.size(); }, null),
    word_count: safe(function() { return record.wordCount(); }, null)
  });
}
