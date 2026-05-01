// Find records related to the given UUID via DEVONthink Compare.
// argv: [uuid, k]
// stdout: JSON array of {uuid, name, similarity, location, reference_url}
//
// Defensive: same as search_bm25.js — records that fail to serialize
// individually are skipped instead of aborting the whole call.

function run(argv) {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  var uuid = argv[0];
  var k = parseInt(argv[1], 10) || 10;

  function safe(fn, def) {
    try {
      var v = fn();
      return v === undefined || v === null ? def : v;
    } catch (e) {
      return def;
    }
  }
  function safeStr(fn) { return String(safe(fn, "") || ""); }

  var record = safe(function() { return DT.getRecordWithUuid(uuid); }, null);
  if (!record) {
    return JSON.stringify({error: "RECORD_NOT_FOUND"});
  }

  var related;
  try {
    related = DT.compare({record: record});
  } catch (e) {
    return JSON.stringify({
      error: "JXA_ERROR",
      message: "DT.compare failed: " + String(e)
    });
  }

  var relCount = safe(function() { return related.length; }, 0);
  var iterCap = Math.min(relCount, k * 2);

  var result = [];
  for (var i = 0; i < iterCap && result.length < k; i++) {
    var r = related[i];
    if (!r) continue;
    var ru = safeStr(function() { return r.uuid(); });
    if (!ru) continue;
    result.push({
      uuid: ru,
      name: safeStr(function() { return r.name(); }),
      similarity: null,
      location: safeStr(function() { return r.location(); }),
      reference_url: safeStr(function() { return r.referenceUrl(); })
    });
  }
  return JSON.stringify(result);
}
