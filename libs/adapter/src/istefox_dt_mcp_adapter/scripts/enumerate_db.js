// Enumerate records inside a database (descend into all groups).
// argv: [database_name, limit, offset]
// stdout: JSON array of {uuid, name, kind, location}
//
// Recursive walk via DT4 native `children` property. We skip groups
// and smart groups in the output (they are containers, not content).
// Defensive — bad records are skipped, not aborted.

function run(argv) {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  var dbName = argv[0];
  var limit = parseInt(argv[1], 10) || 1000;
  var offset = parseInt(argv[2], 10) || 0;

  function safe(fn, def) {
    try {
      var v = fn();
      return v === undefined || v === null ? def : v;
    } catch (e) {
      return def;
    }
  }
  function safeStr(fn) { return String(safe(fn, "") || ""); }

  var allDbs = DT.databases();
  var targetDb = null;
  for (var i = 0; i < allDbs.length; i++) {
    if (safeStr(function() { return allDbs[i].name(); }) === dbName) {
      targetDb = allDbs[i];
      break;
    }
  }
  if (!targetDb) {
    return JSON.stringify({error: "DATABASE_NOT_FOUND", name: dbName});
  }

  var SKIP_KINDS = {"group": 1, "smart group": 1};
  var collected = [];
  var seen = 0;

  // Iterative DFS — JXA recursion is fragile.
  var stack = [safe(function() { return targetDb.root(); }, null)];
  while (stack.length > 0 && collected.length < limit) {
    var node = stack.pop();
    if (!node) continue;

    var children = safe(function() { return node.children(); }, []);
    var n = safe(function() { return children.length; }, 0);
    for (var j = 0; j < n; j++) {
      var c = children[j];
      if (!c) continue;
      var kind = safeStr(function() { return c.type(); });
      if (SKIP_KINDS[kind]) {
        stack.push(c);
        continue;
      }
      var uuid = safeStr(function() { return c.uuid(); });
      if (!uuid) continue;
      seen++;
      if (seen <= offset) continue;
      collected.push({
        uuid: uuid,
        name: safeStr(function() { return c.name(); }),
        kind: kind,
        location: safeStr(function() { return c.location(); }),
      });
      if (collected.length >= limit) break;
    }
  }

  return JSON.stringify({records: collected, total_seen: seen});
}
