// BM25 search via DEVONthink native engine.
// argv: [query, max_results, databases_json, kinds_json]
// stdout: JSON array of {uuid, name, location, reference_url, score, snippet}
//
// Defensive: every property access is wrapped in safe() because DT
// records of unusual kind (smart group, feed item, missing files)
// can fail with -1700 errAECoercionFail when serialized naively.
// Records that fail entirely are skipped, not aborted.

function run(argv) {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  var query = argv[0];
  var maxResults = parseInt(argv[1], 10) || 10;
  var dbNames = JSON.parse(argv[2] || "[]");
  var kinds = JSON.parse(argv[3] || "[]");

  function safe(fn, def) {
    try {
      var v = fn();
      return v === undefined || v === null ? def : v;
    } catch (e) {
      return def;
    }
  }

  function safeStr(fn) { return String(safe(fn, "") || ""); }

  // Resolve database scope (single-db filter only for now).
  var scopeRoot = null;
  if (dbNames.length === 1) {
    var allDbs = DT.databases();
    for (var i = 0; i < allDbs.length; i++) {
      if (safeStr(function() { return allDbs[i].name(); }) === dbNames[0]) {
        scopeRoot = safe(function() { return allDbs[i].root(); }, null);
        break;
      }
    }
  }

  var hits;
  try {
    hits = scopeRoot
      ? DT.search(query, { in: scopeRoot })
      : DT.search(query);
  } catch (e) {
    return JSON.stringify({
      error: "JXA_ERROR",
      message: "DT.search failed: " + String(e)
    });
  }

  var result = [];
  var hitCount = safe(function() { return hits.length; }, 0);
  var iterCap = Math.min(hitCount, maxResults * 4);  // over-fetch for kind filter

  for (var j = 0; j < iterCap && result.length < maxResults; j++) {
    var r = hits[j];
    if (!r) continue;

    var uuid = safeStr(function() { return r.uuid(); });
    if (!uuid) continue;  // unserializable record

    var kind = safeStr(function() { return r.type(); });
    if (kinds.length > 0 && kinds.indexOf(kind) === -1) continue;

    // DT4's referenceUrl() is the canonical x-devonthink-item:// link.
    // For some special records (smart group, feed item, missing file
    // placeholder) the property may return empty/null even though the
    // uuid is valid. Fall back to constructing the URL from uuid so
    // callers always get a usable deep link.
    var refUrl = safeStr(function() { return r.referenceUrl(); });
    if (!refUrl) refUrl = "x-devonthink-item://" + uuid;

    result.push({
      uuid: uuid,
      name: safeStr(function() { return r.name(); }),
      location: safeStr(function() { return r.location(); }),
      reference_url: refUrl,
      // DT4 may expose .score() on search results (relevance 0..1).
      // Falls back to null if the property isn't accessible.
      score: safe(function() { return r.score(); }, null),
      // Snippet stays null by design: r.plainText() is slow on big
      // PDFs, and tool callers can pull text on demand via
      // get_record_text. Avoid blocking search on per-result I/O.
      snippet: null
    });
  }
  return JSON.stringify(result);
}
