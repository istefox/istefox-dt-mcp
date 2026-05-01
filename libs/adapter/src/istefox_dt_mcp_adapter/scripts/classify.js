// DT4 native classifier — suggested destination groups for a record.
// argv: [uuid, top_n]
// stdout: JSON array [{location, score, database}], or {error: "RECORD_NOT_FOUND"}
//
// Wraps `DT.classify({record: r})` which returns a list of groups
// sorted by relevance descending. We expose location strings and
// scores; the calling tool decides which to apply.

function run(argv) {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  var uuid = argv[0];
  var topN = parseInt(argv[1], 10) || 3;

  function safe(fn, def) {
    try {
      var v = fn();
      return v === undefined || v === null ? def : v;
    } catch (e) {
      return def;
    }
  }
  function safeStr(fn) { return String(safe(fn, "") || ""); }
  function safeNum(fn) { var v = safe(fn, null); return v === null ? null : Number(v); }

  var record = safe(function() { return DT.getRecordWithUuid(uuid); }, null);
  if (!record) {
    return JSON.stringify({error: "RECORD_NOT_FOUND"});
  }

  var suggestions;
  try {
    suggestions = DT.classify({record: record});
  } catch (e) {
    return JSON.stringify({
      error: "JXA_ERROR",
      message: "DT.classify failed: " + String(e),
    });
  }

  var n = safe(function() { return suggestions.length; }, 0);
  var out = [];
  var cap = Math.min(n, topN);
  for (var i = 0; i < cap; i++) {
    var s = suggestions[i];
    if (!s) continue;
    out.push({
      location: safeStr(function() { return s.location(); }),
      score: safeNum(function() { return s.score(); }),
      database: safeStr(function() { return s.database().name(); }),
    });
  }
  return JSON.stringify(out);
}
