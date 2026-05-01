// BM25 search via DEVONthink native engine.
// argv: [query, max_results, databases_json, kinds_json]
// stdout: JSON array of {uuid, name, location, reference_url, score, snippet}

function run(argv) {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  var query = argv[0];
  var maxResults = parseInt(argv[1], 10) || 10;
  var dbNames = JSON.parse(argv[2] || "[]");
  var kinds = JSON.parse(argv[3] || "[]");

  var searchOpts = { in: undefined };
  if (dbNames.length === 1) {
    var allDbs = DT.databases();
    for (var i = 0; i < allDbs.length; i++) {
      if (allDbs[i].name() === dbNames[0]) {
        searchOpts.in = allDbs[i].root();
        break;
      }
    }
  }

  var hits;
  try {
    hits = searchOpts.in
      ? DT.search(query, { in: searchOpts.in })
      : DT.search(query);
  } catch (e) {
    return JSON.stringify({error: "JXA_ERROR", message: String(e)});
  }

  var result = [];
  var count = Math.min(hits.length, maxResults);
  for (var j = 0; j < count; j++) {
    var r = hits[j];
    var kind = String(r.type());
    if (kinds.length > 0 && kinds.indexOf(kind) === -1) continue;
    var text = "";
    try { text = (r.plainText() || "").substring(0, 300); } catch (e) {}
    result.push({
      uuid: r.uuid(),
      name: r.name(),
      location: r.location(),
      reference_url: r.referenceUrl(),
      score: null,
      snippet: text
    });
  }
  return JSON.stringify(result);
}
