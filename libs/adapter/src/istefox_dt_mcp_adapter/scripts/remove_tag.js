// Remove a tag from a record.
// argv: [uuid, tag]
// stdout: JSON {uuid, tags_after} or {error: ...}

function run(argv) {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  var uuid = argv[0];
  var tag = argv[1];

  var record = DT.getRecordWithUuid(uuid);
  if (!record) {
    return JSON.stringify({error: "RECORD_NOT_FOUND"});
  }

  var current = record.tags() || [];
  var idx = current.indexOf(tag);
  if (idx === -1) {
    return JSON.stringify({uuid: uuid, tags_after: current, noop: true});
  }
  var updated = [];
  for (var i = 0; i < current.length; i++) {
    if (i !== idx) updated.push(current[i]);
  }
  record.tags = updated;
  return JSON.stringify({uuid: uuid, tags_after: updated});
}
