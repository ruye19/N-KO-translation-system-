/* Review viewer. Reads window.REVIEW_DATA (written by scripts/build_review_kit.py)
 * and keeps answers in this browser's localStorage; Export TSV is the durable
 * record. Decoded strings are only ever displayed, never trimmed or rewritten. */
(function () {
  "use strict";
  var data = window.REVIEW_DATA, core = window.ReviewCore;
  var detail = document.getElementById("detail");
  if (!data || !core) {
    detail.textContent = "review_data.js is missing. Run: py -3.14 scripts/build_review_kit.py";
    return;
  }

  var COL = {};
  data.columns.forEach(function (c, i) { COL[c] = i; });
  var STORE_KEY = "nko-review:" + data.source.sample_tsv_sha256;
  var PREF_KEY = "nko-review-prefs";
  var QUESTIONS = [
    { key: "script", title: "Script fidelity",
      text: "Does the decoded Unicode match the printed N'Ko, line by line: letters, tone marks, nasalisation, punctuation and spacing?",
      keys: ["1", "2", "3"] },
    { key: "segmentation", title: "Segmentation",
      text: "Do the French headword line(s) and the N'Ko line(s) highlighted here belong together as one entry, with no line missing, extra or taken from a neighbour?",
      keys: ["4", "5", "6"] },
    { key: "continuation", title: "Continuation",
      text: "", keys: ["7", "8", "9"] }
  ];

  function load(key, fallback) {
    try { var v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
  }

  var reviews = load(STORE_KEY, {});
  var prefs = load(PREF_KEY, { showSpaces: true, showCodepoints: false, highlights: true, reviewer: "" });
  var state = { index: 0, visible: [] };
  var lastSave = "";

  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v == null || v === false) return;
      if (k === "text") el.textContent = v;
      else if (k === "class") el.className = v;
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    });
    (function add(items) {
      items.forEach(function (x) {
        if (x == null || x === false) return;
        if (Array.isArray(x)) add(x);
        else el.appendChild(typeof x === "string" ? document.createTextNode(x) : x);
      });
    })(Array.prototype.slice.call(arguments, 2));
    return el;
  }
  function field(rec, name) { return rec.original[COL[name]]; }
  function toast(msg) {
    var t = document.getElementById("toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(function () { t.hidden = true; }, 4000);
  }

  // --- decoded text, shown exactly ---------------------------------------
  function edgeCounts(s) {
    var lead = s.length - s.replace(/^\s+/, "").length;
    var trail = lead === s.length ? 0 : s.length - s.replace(/\s+$/, "").length;
    return { lead: lead, trail: trail };
  }
  function nkoText(s, small) {
    var el = h("span", { class: "nko" + (small ? " small" : ""), dir: "rtl", lang: "nqo" });
    if (!prefs.showSpaces) {
      el.textContent = s;
      return el;
    }
    var re = /(\s+)|(⟨U\+[0-9A-F]{4,5}⟩)|([^\s⟨]+|⟨)/g, m;
    while ((m = re.exec(s))) {
      if (m[1]) {
        var edge = m.index === 0 || m.index + m[1].length === s.length;
        el.appendChild(h("span", { class: "ws" + (edge ? " edge" : ""), title: m[1].length + " whitespace char(s)" },
          m[1].replace(/ /g, "·").replace(/\t/g, "→").replace(/ /g, "°")));
      } else if (m[2]) el.appendChild(h("span", { class: "ph", title: "candidate/unknown legacy code, not decoded" }, m[2]));
      else el.appendChild(document.createTextNode(m[3]));
    }
    return el;
  }
  function wsNote(s) {
    var c = edgeCounts(s);
    if (!c.lead && !c.trail) return h("div", { class: "wsnote", text: "No leading or trailing whitespace." });
    return h("div", { class: "wsnote edge",
      text: "Whitespace kept as decoded: " + c.lead + " leading, " + c.trail + " trailing (logical order; leading is at the right)." });
  }
  function codepoints(s) {
    return h("div", { class: "cps" }, Array.from(s).map(function (ch) {
      return "U+" + ch.codePointAt(0).toString(16).toUpperCase().padStart(4, "0");
    }).join(" "));
  }

  // --- page crops ----------------------------------------------------------
  function cropView(ctx, alt) {
    var wrap = h("div", { class: "crop" + (prefs.highlights ? "" : " nohl") },
      h("img", { src: ctx.img, alt: alt, width: ctx.px && ctx.px[0], height: ctx.px && ctx.px[1], loading: "lazy" }));
    ctx.boxes.forEach(function (b) {
      var box = h("span", { class: "box k-" + b.kind });
      box.style.left = (b.l * 100) + "%"; box.style.top = (b.t * 100) + "%";
      box.style.width = (b.w * 100) + "%"; box.style.height = (b.h * 100) + "%";
      if (b.kind === "nko") box.appendChild(h("b", null, String(b.line + 1)));
      wrap.appendChild(box);
    });
    return wrap;
  }
  function legend() {
    return h("p", { class: "legend" }, h("i"), "decoded N'Ko line (numbered)", h("i", { class: "fr" }), "French headword line");
  }

  // --- list ------------------------------------------------------------------
  function statusOf(rec) { return core.recordStatus(rec, reviews[rec.sample_id]); }
  function hasAnswer(rec, a) {
    var r = reviews[rec.sample_id] || {};
    return core.REVIEW_KEYS.some(function (k) { return r[k] === a; });
  }
  function matches(rec) {
    var st = document.getElementById("f-stratum").value;
    var fs = document.getElementById("f-status").value;
    var q = document.getElementById("f-search").value.trim().toLowerCase();
    if (st !== "all" && field(rec, "stratum") !== st) return false;
    if (fs === "flagged" && !rec.auto_flags.length) return false;
    if (fs === "continuation" && !rec.continuation) return false;
    if ((fs === "no" || fs === "uncertain") && !hasAnswer(rec, fs)) return false;
    if (["unreviewed", "partial", "complete"].indexOf(fs) >= 0 && statusOf(rec) !== fs) return false;
    if (q && [rec.sample_id, field(rec, "headword"), field(rec, "entry_ref")].join(" ").toLowerCase().indexOf(q) < 0) return false;
    return true;
  }
  function renderList() {
    var list = document.getElementById("record-list");
    var current = data.records[state.index];
    state.visible = [];
    list.textContent = "";
    data.records.forEach(function (rec, i) {
      if (!matches(rec)) return;
      state.visible.push(i);
      var st = statusOf(rec);
      var dot = "dot " + (hasAnswer(rec, "no") ? "has-no" : st);
      list.appendChild(h("li", {
        class: rec === current ? "current" : "", "data-i": i, title: field(rec, "entry_ref"),
        onclick: function () { go(i); }
      },
        h("span", { class: dot, title: st }),
        h("span", { class: "sid", text: rec.sample_id }),
        h("span", { class: "hw", text: field(rec, "headword") || "(" + field(rec, "entry_kind") + ")" }),
        h("span", { class: "tag" }, rec.auto_flags.length ? h("span", { class: "flag-mark", title: "auto-flagged" }, "⚠ ") : null,
          field(rec, "stratum").charAt(0))
      ));
    });
    document.getElementById("list-count").textContent = state.visible.length + " of " + data.records.length + " shown";
    // Scroll only the list itself; scrollIntoView would also move the window.
    var cur = list.querySelector("li.current");
    if (cur && (cur.offsetTop < list.scrollTop || cur.offsetTop + cur.offsetHeight > list.scrollTop + list.clientHeight)) {
      list.scrollTop = cur.offsetTop - list.clientHeight / 2;
    }
  }
  function renderProgress() {
    var done = data.records.filter(function (r) { return statusOf(r) === "complete"; }).length;
    document.getElementById("progress-fill").style.width = (100 * done / data.records.length) + "%";
    document.getElementById("progress-text").textContent = done + " / " + data.records.length + " complete";
  }

  // --- answers ---------------------------------------------------------------
  function setAnswer(key, value) {
    var rec = data.records[state.index];
    if (key === "continuation" && !rec.continuation) return;
    var r = reviews[rec.sample_id] || (reviews[rec.sample_id] = {});
    r[key] = r[key] === value ? "" : value;
    touch(r);
    renderDetail(); renderList(); renderProgress();
  }
  function touch(r) {
    r.reviewer = prefs.reviewer || r.reviewer || "";
    r.updated_at = new Date().toISOString();
    lastSave = save(STORE_KEY, reviews) ? "Saved in this browser " + new Date().toLocaleTimeString()
      : "Browser storage unavailable: export before closing";
  }

  // --- detail ----------------------------------------------------------------
  function renderDetail() {
    var rec = data.records[state.index], e = rec.entry, r = reviews[rec.sample_id] || {};
    detail.textContent = "";

    detail.appendChild(h("div", { class: "meta" },
      h("h2", { text: rec.sample_id + " · " + (e.headword || "(no headword: " + e.kind + ")") }),
      h("span", { class: "chip", text: field(rec, "stratum") }),
      h("span", { class: "chip tier-" + field(rec, "weakest_tier"), text: field(rec, "weakest_tier") }),
      h("span", { class: "chip", text: e.kind })));

    rec.auto_flags.forEach(function (f) {
      detail.appendChild(h("div", { class: "banner", role: "note" },
        h("strong", { text: "⚠ " + f.code.replace(/_/g, " ") }), f.message));
    });

    var facts = [
      ["Why sampled", field(rec, "reason")],
      ["Entry", e.entry_ref],
      ["Location", "PDF page " + e.page + " (not the printed page number), " + (e.column ? "right" : "left") + " column"],
      ["Rules applied", field(rec, "rules_applied") || "none"],
      ["Candidate codes", field(rec, "candidate_codes") || "none"],
      ["Link to old table", e.link_status + (e.flags.length ? " · flags: " + e.flags.join(", ") : "")]
    ];
    if (rec.structural_parent) facts.push(["Sub-entry of", rec.structural_parent.entry_ref + " " + (rec.structural_parent.headword || "")]);
    if (e.continued_by.length) facts.push(["Continued by", e.continued_by.join(", ")]);
    detail.appendChild(h("dl", { class: "facts" }, facts.map(function (f) { return [h("dt", { text: f[0] }), h("dd", { text: f[1] })]; })));

    detail.appendChild(h("section", { class: "card" },
      h("h3", null, "Printed entry ", h("span", { class: "muted", text: "· exact line boxes from line_positions, with one line of context" })),
      cropView(rec.context, "Printed entry " + e.entry_ref), legend()));

    detail.appendChild(h("section", { class: "card" },
      h("h3", null, "French"),
      h("div", { class: "french" },
        e.headword_lines.length ? e.headword_lines.map(function (l) { return h("div", { class: "hl", text: l.text }); })
          : h("div", { class: "muted", text: "No French headword line: this row is " + e.kind + "." }))));

    var toggles = h("div", { class: "toggles" },
      toggle("showSpaces", "Show whitespace (· = space)"),
      toggle("showCodepoints", "Show code points"),
      toggle("highlights", "Highlight boxes on crops"));
    detail.appendChild(h("section", { class: "card" },
      h("h3", null, "N'Ko, line by line ", h("span", { class: "muted", text: "· printed (top) vs decoded Unicode (below)" })),
      toggles,
      h("div", { class: "lines" }, rec.lines.map(function (ln, i) {
        var s = e.decoded_lines[i];
        return h("div", { class: "line" },
          h("div", { class: "n", text: String(i + 1) }),
          h("div", null,
            h("div", { class: "label", text: "Printed · baseline y=" + ln.y + ", x " + ln.x0 + "–" + ln.x1 }),
            h("div", { class: "print" }, h("img", { src: ln.img, alt: "Printed N'Ko line " + (i + 1), loading: "lazy",
              width: ln.px && ln.px[0], height: ln.px && ln.px[1] })),
            h("div", { class: "label", text: "Decoded" }),
            nkoText(s), wsNote(s), prefs.showCodepoints ? codepoints(s) : null));
      }))));

    if (rec.continuation) detail.appendChild(continuationCard(rec));
    if (rec.structural_parent) {
      detail.appendChild(h("section", { class: "card" },
        h("h3", null, "Parent headword of this sub-entry ", h("span", { class: "muted", text: "· " + rec.structural_parent.entry_ref })),
        h("div", { class: "french", text: rec.structural_parent.headword || "(none)" }),
        rec.structural_parent.decoded_lines.map(function (s) { return nkoText(s, true); })));
    }

    detail.appendChild(questionsCard(rec, r));
  }

  function continuationCard(rec) {
    var c = rec.continuation, p = c.parent;
    return h("section", { class: "card" },
      h("h3", null, "Continuation link ", h("span", { class: "muted", text: "· made by the decoder, not verified" })),
      h("dl", { class: "facts" },
        h("dt", { text: "Linked to" }), h("dd", { text: p.entry_ref + " · " + (p.headword || "(no headword)") }),
        h("dt", { text: "Where" }), h("dd", { text: "PDF page " + p.page + ", " + (p.column ? "right" : "left") + " column" }),
        h("dt", { text: "Evidence" }), h("dd", { text: evidenceText(c.evidence) })),
      cropView(c.context, "Linked previous entry " + p.entry_ref), legend(),
      h("div", { class: "label", text: "Decoded N'Ko of the linked entry" }),
      p.decoded_lines.map(function (s) { return nkoText(s, true); }));
  }
  function evidenceText(ev) {
    var known = {
      bracket_balance: "bracket_balance: the previous entry leaves a bracket open and this row closes it",
      reading_order: "reading_order: only position (it is the entry directly before this column-top text); nothing in the text confirms it"
    };
    return known[ev] || ev || "none recorded";
  }

  function questionsCard(rec, r) {
    var qs = QUESTIONS.map(function (q) {
      var na = q.key === "continuation" && !rec.continuation;
      var text = q.text;
      if (q.key === "continuation") {
        text = na ? "Not applicable: the decoder made no continuation link for this row (exported as n/a)."
          : "Is this column-top text correctly attached to " + rec.continuation.parent.entry_ref + " (" +
            (rec.continuation.parent.headword || "no headword") + ")? Answer “no” if it belongs elsewhere; do not guess where.";
      }
      return h("div", { class: "q" + (na ? " na" : "") },
        h("h4", { text: q.title }), h("p", { text: text }),
        na ? null : h("div", { class: "answers", role: "group", "aria-label": q.title },
          data.answers.map(function (a, i) {
            return h("button", { type: "button", class: "a-" + a, "aria-pressed": r[q.key] === a ? "true" : "false",
              onclick: function () { setAnswer(q.key, a); } }, a, h("kbd", { text: q.keys[i] }));
          })));
    });
    var notes = h("textarea", { id: "notes", placeholder: "What differs? e.g. line 2: printed tone mark missing on 3rd vowel" });
    notes.value = r.notes || "";
    notes.addEventListener("input", function () {
      var rv = reviews[rec.sample_id] || (reviews[rec.sample_id] = {});
      rv.notes = notes.value;
      touch(rv);
      document.getElementById("saved").textContent = lastSave;
      renderProgress();
    });
    notes.addEventListener("change", renderList);
    return h("section", { class: "card" },
      h("h3", null, "Review ", h("span", { class: "muted", text: "· status: " + statusOf(rec) })),
      h("div", { class: "questions" }, qs,
        h("label", null, h("div", { class: "label", text: "Notes" }), notes)),
      h("div", { class: "nav" },
        h("button", { type: "button", onclick: function () { step(-1); } }, "← Previous"),
        h("button", { type: "button", onclick: function () { step(1); } }, "Next →"),
        h("button", { type: "button", onclick: nextOpen }, "Next unfinished"),
        h("span", { class: "hint", text: "Keys: 1–3 script · 4–6 segmentation · 7–9 continuation · j/k next/previous · u next unfinished" }),
        h("span", { id: "saved", class: "saved", text: lastSave })));
  }

  function toggle(pref, label) {
    var cb = h("input", { type: "checkbox", onchange: function () {
      prefs[pref] = cb.checked; save(PREF_KEY, prefs); renderDetail();
    } });
    cb.checked = !!prefs[pref];
    return h("label", null, cb, " " + label);
  }

  // --- navigation --------------------------------------------------------------
  function go(i) {
    state.index = i;
    renderDetail(); renderList();
    detail.scrollTop = 0; window.scrollTo(0, 0);
    try { history.replaceState(null, "", "#" + data.records[i].sample_id); } catch (e) { /* file:// may refuse */ }
  }
  function step(d) {
    var vis = state.visible.length ? state.visible : data.records.map(function (_r, i) { return i; });
    var pos = vis.indexOf(state.index);
    var next = pos < 0 ? vis[0] : vis[Math.min(vis.length - 1, Math.max(0, pos + d))];
    if (next !== undefined) go(next);
  }
  function nextOpen() {
    for (var k = 1; k <= data.records.length; k++) {
      var i = (state.index + k) % data.records.length;
      if (statusOf(data.records[i]) !== "complete") return go(i);
    }
    toast("Every record is complete.");
  }

  document.addEventListener("keydown", function (ev) {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    var t = ev.target.tagName;
    if (t === "INPUT" || t === "TEXTAREA" || t === "SELECT" || document.querySelector("dialog[open]")) return;
    var hit = null;
    QUESTIONS.forEach(function (q) { var i = q.keys.indexOf(ev.key); if (i >= 0) hit = [q.key, data.answers[i]]; });
    if (hit) { setAnswer(hit[0], hit[1]); ev.preventDefault(); return; }
    if (ev.key === "j" || ev.key === "ArrowDown") { step(1); ev.preventDefault(); }
    else if (ev.key === "k" || ev.key === "ArrowUp") { step(-1); ev.preventDefault(); }
    else if (ev.key === "u") nextOpen();
  });

  // --- header tools --------------------------------------------------------------
  var strata = Array.from(new Set(data.records.map(function (r) { return field(r, "stratum"); })));
  var fStratum = document.getElementById("f-stratum");
  fStratum.appendChild(h("option", { value: "all", text: "All strata" }));
  strata.forEach(function (s) { fStratum.appendChild(h("option", { value: s, text: s })); });
  ["f-stratum", "f-status", "f-search"].forEach(function (id) {
    document.getElementById(id).addEventListener("input", renderList);
  });

  var reviewer = document.getElementById("reviewer");
  reviewer.value = prefs.reviewer || "";
  reviewer.addEventListener("input", function () { prefs.reviewer = reviewer.value.trim(); save(PREF_KEY, prefs); });

  document.getElementById("btn-export").addEventListener("click", function () {
    var blob = new Blob([core.exportTsv(data, reviews)], { type: "text/tab-separated-values;charset=utf-8" });
    var a = h("a", { href: URL.createObjectURL(blob), download: data.source.sample_tsv.replace(/\.tsv$/, "") + ".review.tsv" });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    toast("Exported. Keep the file local (e.g. in data/); it contains copyrighted excerpts.");
  });

  document.getElementById("file-import").addEventListener("change", function (ev) {
    var file = ev.target.files[0];
    if (!file) return;
    file.text().then(function (text) {
      var res = core.importTsv(data, text), n = Object.keys(res.reviews).length;
      if (!n && res.errors.length) { toast("Import failed:\n" + res.errors.slice(0, 5).join("\n")); return; }
      if (Object.keys(reviews).length && !confirm("Replace the " + Object.keys(reviews).length +
        " reviews in this browser with the " + n + " in the file?")) return;
      reviews = res.reviews; save(STORE_KEY, reviews);
      renderDetail(); renderList(); renderProgress();
      toast("Imported " + n + " reviews" + (res.errors.length ? "; " + res.errors.length + " row(s) skipped:\n" +
        res.errors.slice(0, 5).join("\n") : "."));
    });
    ev.target.value = "";
  });

  document.getElementById("btn-reset").addEventListener("click", function () {
    if (!confirm("Clear every review stored in this browser? Export first if you need them.")) return;
    reviews = {}; save(STORE_KEY, reviews);
    renderDetail(); renderList(); renderProgress();
  });

  document.getElementById("btn-summary").addEventListener("click", function () {
    var sum = core.summarize(data, reviews), body = document.getElementById("summary-body");
    body.textContent = "";
    var cols = data.answers.concat(["unanswered"]);
    ["script", "segmentation", "continuation"].forEach(function (k) {
      var rows = Object.keys(sum).filter(function (s) { return Object.keys(sum[s][k]).length; });
      if (!rows.length) return;
      body.appendChild(h("h3", { text: QUESTIONS.filter(function (q) { return q.key === k; })[0].title }));
      body.appendChild(h("table", { class: "sum" },
        h("thead", null, h("tr", null, h("th", { text: "Stratum" }), cols.map(function (c) { return h("th", { text: c }); }))),
        h("tbody", null, rows.map(function (s) {
          return h("tr", null, h("td", { text: s }), cols.map(function (c) { return h("td", { text: String(sum[s][k][c] || 0) }); }));
        }))));
    });
    document.getElementById("summary-dialog").showModal();
  });

  var start = 0, hash = location.hash.slice(1);
  data.records.forEach(function (r, i) { if (r.sample_id === hash) start = i; });
  renderProgress();
  go(start);
})();
