/* Pure logic for the spacing review: answers, status, export, import, summary.
 * TSV quoting comes from review_core.js (shared with the first review kit), so
 * an unreviewed export reproduces every spacing_sample line byte for byte as a
 * prefix. No DOM access; loaded by the viewer and by the Node tests. */
(function (root) {
  "use strict";
  var RC = typeof module !== "undefined" && module.exports ? require("./review_core.js") : root.ReviewCore;

  var QUESTIONS = [
    { key: "q1", column: "q1_separation_matches_pdf", problem: "no",
      title: "1. Does the v1.2 word separation match the printed PDF?" },
    { key: "q2", column: "q2_space_inserted_inside_word", problem: "yes",
      title: "2. Were any spaces inserted inside a word?" },
    { key: "q3", column: "q3_meaningful_space_removed", problem: "yes",
      title: "3. Were any meaningful spaces removed?" },
    { key: "q4", column: "q4_uncertain_or_difficult", problem: "yes",
      title: "4. Is the result uncertain or difficult to judge?" }
  ];

  function status(review) {
    var r = review || {};
    var done = QUESTIONS.filter(function (q) { return !!r[q.key]; }).length;
    if (!done && !r.notes) return "unreviewed";
    return done === QUESTIONS.length ? "complete" : "partial";
  }

  // An answer that points at a spacing error, or at doubt.
  function problems(review) {
    var r = review || {};
    return QUESTIONS.filter(function (q) { return r[q.key] === q.problem || r[q.key] === "uncertain"; })
      .map(function (q) { return q.key; });
  }

  function exportTsv(data, reviews) {
    var lines = [data.columns.concat(data.answer_columns).map(RC.tsvField).join("\t")];
    data.records.forEach(function (rec) {
      var r = reviews[rec.spacing_id] || {};
      var row = data.columns.map(function (c) { return rec.row[c]; });
      var extra = { review_notes: r.notes || "", reviewer: r.reviewer || "", reviewed_at: r.updated_at || "" };
      QUESTIONS.forEach(function (q) { extra[q.column] = r[q.key] || ""; });
      data.answer_columns.forEach(function (c) { row.push(extra[c]); });
      lines.push(row.map(RC.tsvField).join("\t"));
    });
    return lines.join("\n") + "\n";
  }

  // Read an exported file back. Every sample cell must be identical to the
  // kit's, otherwise the row is rejected.
  function importTsv(data, text) {
    var rows = RC.parseTsv(text), errors = [], reviews = {}, byId = {};
    data.records.forEach(function (rec) { byId[rec.spacing_id] = rec; });
    var header = rows.shift() || [];
    for (var c = 0; c < data.columns.length; c++) {
      if (header[c] !== data.columns[c]) return { reviews: {}, errors: ["header does not start with the spacing-sample columns"] };
    }
    var at = {};
    header.forEach(function (h, i) { at[h] = i; });
    rows.forEach(function (row, n) {
      if (row.length === 1 && row[0] === "") return;
      var rec = byId[row[0]];
      if (!rec) { errors.push("line " + (n + 2) + ": unknown spacing_id " + row[0]); return; }
      for (var i = 0; i < data.columns.length; i++) {
        if (row[i] !== rec.row[data.columns[i]]) {
          errors.push(rec.spacing_id + ": column " + data.columns[i] + " differs from the sample; row skipped");
          return;
        }
      }
      var get = function (name) { return at[name] === undefined ? "" : (row[at[name]] || ""); };
      var r = { notes: get("review_notes"), reviewer: get("reviewer"), updated_at: get("reviewed_at") };
      var bad = [];
      QUESTIONS.forEach(function (q) {
        r[q.key] = get(q.column);
        if (r[q.key] && data.answers.indexOf(r[q.key]) < 0) bad.push(q.column);
      });
      if (bad.length) { errors.push(rec.spacing_id + ": invalid answer in " + bad.join(", ") + "; row skipped"); return; }
      if (status(r) !== "unreviewed") reviews[rec.spacing_id] = r;
    });
    return { reviews: reviews, errors: errors };
  }

  // Tallies per question, overall and per original stratum.
  function summarize(data, reviews) {
    var out = { all: { total: 0, complete: 0 } };
    data.records.forEach(function (rec) {
      var r = reviews[rec.spacing_id] || {};
      [out.all, out[rec.row.stratum] || (out[rec.row.stratum] = { total: 0, complete: 0 })].forEach(function (t) {
        t.total++;
        if (status(r) === "complete") t.complete++;
        QUESTIONS.forEach(function (q) {
          var a = r[q.key] || "unanswered";
          t[q.key] = t[q.key] || {};
          t[q.key][a] = (t[q.key][a] || 0) + 1;
        });
      });
    });
    return out;
  }

  var api = { QUESTIONS: QUESTIONS, status: status, problems: problems, exportTsv: exportTsv,
              importTsv: importTsv, summarize: summarize };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SpacingCore = api;
})(this);
