// Find records related to the given UUID via DEVONthink Compare.
// argv: [uuid, k]
// stdout: JSON array of {uuid, name, similarity, location, reference_url}

function run(argv) {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  var uuid = argv[0];
  var k = parseInt(argv[1], 10) || 10;

  var record = DT.getRecordWithUuid(uuid);
  if (!record) {
    return JSON.stringify({error: "RECORD_NOT_FOUND"});
  }

  var related;
  try {
    related = DT.compare({record: record});
  } catch (e) {
    return JSON.stringify({error: "JXA_ERROR", message: String(e)});
  }

  var result = [];
  var count = Math.min(related.length, k);
  for (var i = 0; i < count; i++) {
    var r = related[i];
    result.push({
      uuid: r.uuid(),
      name: r.name(),
      similarity: null,
      location: r.location(),
      reference_url: r.referenceUrl()
    });
  }
  return JSON.stringify(result);
}
