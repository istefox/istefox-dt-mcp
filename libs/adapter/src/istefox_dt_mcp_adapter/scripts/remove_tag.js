// Remove a tag from a record.
// argv: [uuid, tag]
// stdout: JSON {uuid, tags_after} or {error: ...}
//
// Defensive: getRecordWithUuid throws on UUIDs that don't resolve;
// without safe() the script crashes and the caller gets opaque
// JXA_ERROR instead of structured RECORD_NOT_FOUND.

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

  var uuid = argv[0];
  var tag = argv[1];

  var record = safe(function() { return DT.getRecordWithUuid(uuid); }, null);
  if (!record) {
    return JSON.stringify({error: "RECORD_NOT_FOUND"});
  }

  var current = safe(function() { return record.tags(); }, []);
  var idx = current.indexOf(tag);
  if (idx === -1) {
    return JSON.stringify({uuid: uuid, tags_after: current, noop: true});
  }
  var updated = [];
  for (var i = 0; i < current.length; i++) {
    if (i !== idx) updated.push(current[i]);
  }
  try {
    record.tags = updated;
  } catch (e) {
    return JSON.stringify({error: "JXA_ERROR", message: "tags assign failed: " + String(e)});
  }
  return JSON.stringify({uuid: uuid, tags_after: updated});
}
