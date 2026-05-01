// Fetch a single record by UUID.
// argv: [uuid]
// stdout: JSON object matching schemas.common.Record, or {error: "RECORD_NOT_FOUND"}

function run(argv) {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  var uuid = argv[0];
  var record = DT.getRecordWithUuid(uuid);

  if (!record) {
    return JSON.stringify({error: "RECORD_NOT_FOUND"});
  }

  function iso(d) {
    return d ? d.toISOString() : null;
  }

  return JSON.stringify({
    uuid: record.uuid(),
    name: record.name(),
    kind: String(record.type()),
    location: record.location(),
    path: record.path() || null,
    reference_url: record.referenceUrl(),
    creation_date: iso(record.creationDate()),
    modification_date: iso(record.modificationDate()),
    tags: record.tags() || [],
    size_bytes: record.size ? record.size() : null,
    word_count: record.wordCount ? record.wordCount() : null
  });
}
