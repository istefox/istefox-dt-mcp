// Move a record to a destination group path.
// argv: [uuid, dest_group_path]
//   dest_group_path: "Database/Group/Subgroup" — first segment is database name
// stdout: JSON {uuid, location} or {error: ...}

function run(argv) {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  var uuid = argv[0];
  var destPath = argv[1];

  var record = DT.getRecordWithUuid(uuid);
  if (!record) {
    return JSON.stringify({error: "RECORD_NOT_FOUND"});
  }

  var parts = destPath.split("/").filter(function(p) { return p.length > 0; });
  if (parts.length === 0) {
    return JSON.stringify({error: "VALIDATION_ERROR", message: "empty destination path"});
  }

  var dbName = parts[0];
  var groupPath = parts.slice(1).join("/");

  var allDbs = DT.databases();
  var targetDb = null;
  for (var i = 0; i < allDbs.length; i++) {
    if (allDbs[i].name() === dbName) {
      targetDb = allDbs[i];
      break;
    }
  }
  if (!targetDb) {
    return JSON.stringify({error: "DATABASE_NOT_FOUND", name: dbName});
  }

  var destGroup;
  if (groupPath) {
    destGroup = DT.createLocation(groupPath, {in: targetDb});
  } else {
    destGroup = targetDb.root();
  }

  try {
    DT.move({record: record, to: destGroup});
  } catch (e) {
    return JSON.stringify({error: "JXA_ERROR", message: String(e)});
  }

  return JSON.stringify({uuid: uuid, location: destGroup.location()});
}
