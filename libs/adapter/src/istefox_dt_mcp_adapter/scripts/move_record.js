// Move a record to a destination group path.
// argv: [uuid, dest_group_path]
//   dest_group_path: "Database/Group/Subgroup" — first segment is database name
// stdout: JSON {uuid, location} or {error: ...}
//
// Defensive: getRecordWithUuid and database iteration throw on
// edge cases (UUID not resolving, database not opened); safe()
// guards turn those into structured errors instead of opaque
// JXA_ERROR script crashes.

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
  function safeStr(fn) { return String(safe(fn, "") || ""); }

  var uuid = argv[0];
  var destPath = argv[1];

  var record = safe(function() { return DT.getRecordWithUuid(uuid); }, null);
  if (!record) {
    return JSON.stringify({error: "RECORD_NOT_FOUND"});
  }

  var parts = destPath.split("/").filter(function(p) { return p.length > 0; });
  if (parts.length === 0) {
    return JSON.stringify({error: "VALIDATION_ERROR", message: "empty destination path"});
  }

  var dbName = parts[0];
  var groupPath = parts.slice(1).join("/");

  var allDbs = safe(function() { return DT.databases(); }, []);
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

  var destGroup;
  try {
    destGroup = groupPath
      ? DT.createLocation(groupPath, {in: targetDb})
      : targetDb.root();
  } catch (e) {
    return JSON.stringify({
      error: "JXA_ERROR",
      message: "createLocation failed: " + String(e)
    });
  }

  try {
    DT.move({record: record, to: destGroup});
  } catch (e) {
    return JSON.stringify({error: "JXA_ERROR", message: "move failed: " + String(e)});
  }

  return JSON.stringify({
    uuid: uuid,
    location: safeStr(function() { return destGroup.location(); })
  });
}
