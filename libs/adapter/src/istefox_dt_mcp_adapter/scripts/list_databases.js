// List all open DEVONthink databases.
// argv: none
// stdout: JSON array of {uuid, name, path, is_open, record_count}
//
// Defensive: skip databases whose properties throw -1700 instead of
// aborting the whole call.

function run() {
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

  var dbs = DT.databases();
  var result = [];
  var n = safe(function() { return dbs.length; }, 0);
  for (var i = 0; i < n; i++) {
    var d = dbs[i];
    if (!d) continue;
    var u = safeStr(function() { return d.uuid(); });
    if (!u) continue;
    result.push({
      uuid: u,
      name: safeStr(function() { return d.name(); }),
      path: safeStr(function() { return d.path(); }),
      is_open: true,
      // DT exposes the full content set via d.contents(); .length
      // is the recursive record count. Wrapped in safe() so a slow
      // or unsupported call falls back to null instead of aborting
      // the whole listing.
      record_count: safe(function() { return d.contents().length; }, null)
    });
  }
  return JSON.stringify(result);
}
