// List all open DEVONthink databases.
// argv:
//   $1 (optional): "0" to skip record_count (returns null) for users
//                  with very large databases where d.contents().length
//                  is slow. Any other value (or absent) computes it.
// stdout: JSON array of {uuid, name, path, is_open, record_count}
//
// Defensive: skip databases whose properties throw -1700 instead of
// aborting the whole call.

function run(argv) {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  // Default: compute record_count. Caller passes "0" to skip.
  var includeCount = !(argv && argv.length > 0 && String(argv[0]) === "0");

  function safe(fn, def) {
    try {
      var v = fn();
      return v === undefined || v === null ? def : v;
    } catch (e) {
      return def;
    }
  }
  function safeStr(fn) { return String(safe(fn, "") || ""); }

  var dbs = DT.databases();
  var result = [];
  var n = safe(function() { return dbs.length; }, 0);
  for (var i = 0; i < n; i++) {
    var d = dbs[i];
    if (!d) continue;
    var u = safeStr(function() { return d.uuid(); });
    if (!u) continue;
    // DT exposes the full content set via d.contents(); .length is
    // the recursive record count. On databases with tens of thousands
    // of records this materializes the full list and can take several
    // seconds. The 5-min adapter cache amortizes most of the cost,
    // but users who want to avoid the first-call latency can pass
    // "0" as argv to skip the count entirely.
    // Wrapped in safe() so a slow/failing call returns null instead
    // of aborting the whole listing.
    var count = includeCount
      ? safe(function() { return d.contents().length; }, null)
      : null;
    result.push({
      uuid: u,
      name: safeStr(function() { return d.name(); }),
      path: safeStr(function() { return d.path(); }),
      is_open: true,
      record_count: count
    });
  }
  return JSON.stringify(result);
}
