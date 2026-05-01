// List all open DEVONthink databases.
// argv: none
// stdout: JSON array of {uuid, name, path, is_open, record_count}

function run() {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  var dbs = DT.databases();
  var result = [];
  for (var i = 0; i < dbs.length; i++) {
    try {
      result.push({
        uuid: dbs[i].uuid(),
        name: dbs[i].name(),
        path: dbs[i].path(),
        is_open: true,
        record_count: null
      });
    } catch (e) {
      // skip databases that throw on property access
    }
  }
  return JSON.stringify(result);
}
