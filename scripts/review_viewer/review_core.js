/* Pure review logic shared by the viewer and the Node tests. No DOM access.
 *
 * Export keeps the 19 sample columns exactly as read (whitespace included),
 * fills the three original review_* columns, and appends EXTRA columns.
 * Quoting matches Python's csv module (QUOTE_MINIMAL, tab, "\n") so an
 * unreviewed export reproduces every original line byte for byte as a prefix.
 */
(function (root) {
  "use strict";

  function tsvField(value) {
    var v = value == null ? "" : String(value);
    return /[\t"\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }

  // Inverse of tsvField over a whole file. Returns an array of rows of strings.
  function parseTsv(text) {
    var rows = [], row = [], field = "", i = 0, quoted = false, n = text.length;
    if (text.charCodeAt(0) === 0xfeff) i = 1;
    for (; i < n; i++) {
      var ch = text[i];
      if (quoted) {
        if (ch === '"') {
          if (text[i + 1] === '"') { field += '"'; i++; } else quoted = false;
        } else field += ch;
      } else if (ch === '"' && field === "") quoted = true;
      else if (ch === "\t") { row.push(field); field = ""; }
      else if (ch === "\n" || ch === "\r") {
        if (ch === "\r" && text[i + 1] === "\n") i++;
        row.push(field); rows.push(row); row = []; field = "";
      } else field += ch;
    }
    if (field !== "" || row.length) { row.push(field); rows.push(row); }
    return rows;
  }

  var REVIEW_KEYS = ["script", "segmentation", "continuation"];

  function needsContinuation(rec) { return !!rec.continuation; }

  function recordStatus(rec, review) {
    var r = review || {};
    var keys = needsContinuation(rec) ? REVIEW_KEYS : REVIEW_KEYS.slice(0, 2);
    var done = keys.filter(function (k) { return !!r[k]; }).length;
    if (done === 0 && !r.notes) return "unreviewed";
    return done === keys.length ? "complete" : "partial";
  }

  function exportTsv(data, reviews) {
    var cols = data.columns, idx = {};
    cols.forEach(function (c, i) { idx[c] = i; });
    var lines = [cols.concat(data.extra_columns).map(tsvField).join("\t")];
    data.records.forEach(function (rec) {
      var r = reviews[rec.sample_id] || {};
      var row = rec.original.slice();
      row[idx.review_script_ok] = r.script || "";
      row[idx.review_segmentation_ok] = r.segmentation || "";
      row[idx.review_notes] = r.notes || "";
      var extra = {
        review_continuation_ok: needsContinuation(rec) ? (r.continuation || "") : "n/a",
        auto_flags: rec.auto_flags.map(function (f) { return f.code; }).join(" "),
        reviewer: r.reviewer || "",
        reviewed_at: r.updated_at || ""
      };
      data.extra_columns.forEach(function (c) { row.push(extra[c]); });
      lines.push(row.map(tsvField).join("\t"));
    });
    return lines.join("\n") + "\n";
  }

  // Read an exported review file back. Every sample cell other than the review
  // columns must be identical to the kit's source, otherwise the row is rejected.
  function importTsv(data, text) {
    var rows = parseTsv(text), errors = [], reviews = {}, byId = {};
    data.records.forEach(function (rec) { byId[rec.sample_id] = rec; });
    var header = rows.shift() || [];
    var cols = data.columns;
    for (var c = 0; c < cols.length; c++) {
      if (header[c] !== cols[c]) return { reviews: {}, errors: ["header does not start with the 19 sample columns"] };
    }
    var at = {};
    header.forEach(function (h, i) { at[h] = i; });
    var reviewCols = { review_script_ok: 1, review_segmentation_ok: 1, review_notes: 1 };
    rows.forEach(function (row, n) {
      if (row.length === 1 && row[0] === "") return;
      var rec = byId[row[0]];
      if (!rec) { errors.push("line " + (n + 2) + ": unknown sample_id " + row[0]); return; }
      for (var i = 0; i < cols.length; i++) {
        if (!reviewCols[cols[i]] && row[i] !== rec.original[i]) {
          errors.push(rec.sample_id + ": column " + cols[i] + " differs from the sample; row skipped");
          return;
        }
      }
      var get = function (name) { return at[name] === undefined ? "" : (row[at[name]] || ""); };
      var r = {
        script: get("review_script_ok"),
        segmentation: get("review_segmentation_ok"),
        continuation: get("review_continuation_ok") === "n/a" ? "" : get("review_continuation_ok"),
        notes: get("review_notes"),
        reviewer: get("reviewer"),
        updated_at: get("reviewed_at")
      };
      var bad = REVIEW_KEYS.filter(function (k) { return r[k] && data.answers.indexOf(r[k]) < 0; });
      if (bad.length) { errors.push(rec.sample_id + ": invalid answer in " + bad.join(", ") + "; row skipped"); return; }
      if (r.continuation && !needsContinuation(rec)) {
        errors.push(rec.sample_id + ": continuation answer on a row without a continuation link; row skipped");
        return;
      }
      if (r.script || r.segmentation || r.continuation || r.notes) reviews[rec.sample_id] = r;
    });
    return { reviews: reviews, errors: errors };
  }

  // Per-stratum tallies of each question, for reporting results per stratum.
  function summarize(data, reviews) {
    var out = {};
    data.records.forEach(function (rec) {
      var s = rec.original[data.columns.indexOf("stratum")];
      var t = out[s] || (out[s] = { total: 0, complete: 0, script: {}, segmentation: {}, continuation: {} });
      var r = reviews[rec.sample_id] || {};
      t.total++;
      if (recordStatus(rec, r) === "complete") t.complete++;
      REVIEW_KEYS.forEach(function (k) {
        if (k === "continuation" && !needsContinuation(rec)) return;
        var a = r[k] || "unanswered";
        t[k][a] = (t[k][a] || 0) + 1;
      });
    });
    return out;
  }

  var api = {
    tsvField: tsvField, parseTsv: parseTsv, recordStatus: recordStatus, needsContinuation: needsContinuation,
    exportTsv: exportTsv, importTsv: importTsv, summarize: summarize, REVIEW_KEYS: REVIEW_KEYS
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReviewCore = api;
})(this);
