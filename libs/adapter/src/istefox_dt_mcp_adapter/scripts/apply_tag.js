// Add a tag to a record.
// argv: [uuid, tag]
// stdout: JSON {uuid, tags_after} or {error: "RECORD_NOT_FOUND"}

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
  if (current.indexOf(tag) !== -1) {
    return JSON.stringify({uuid: uuid, tags_after: current, noop: true});
  }
  var updated = current.concat([tag]);
  record.tags = updated;
  return JSON.stringify({uuid: uuid, tags_after: updated});
}
