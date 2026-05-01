// Extract plain text from a record, safely truncated.
// argv: [uuid, max_chars]
// stdout: JSON {uuid, text} or {error: "RECORD_NOT_FOUND"} or {error: "NO_TEXT"}
//
// `r.plainText()` is the most common -1700 culprit because it does
// not exist on every record kind (smart group, feed, image without
// OCR). We swallow those failures and return text="" so the caller
// can still cite the record by UUID/name without breaking the batch.

function run(argv) {
  var DT = Application("DEVONthink");

  if (!DT.running()) {
    return JSON.stringify({error: "DT_NOT_RUNNING"});
  }

  var uuid = argv[0];
  var maxChars = parseInt(argv[1], 10) || 2000;

  function safe(fn, def) {
    try {
      var v = fn();
      return v === undefined || v === null ? def : v;
    } catch (e) {
      return def;
    }
  }

  var record = safe(function() { return DT.getRecordWithUuid(uuid); }, null);
  if (!record) {
    return JSON.stringify({error: "RECORD_NOT_FOUND"});
  }

  var text = safe(function() {
    var pt = record.plainText();
    return pt ? String(pt) : "";
  }, "");

  if (text.length > maxChars) {
    text = text.substring(0, maxChars);
  }

  return JSON.stringify({uuid: uuid, text: text});
}
