/* Spacing review viewer. Reads window.SPACING_DATA (scripts/build_spacing_review.py).
 * Answers live in this browser's localStorage; Export TSV is the durable record.
 * The v1.1 and v1.2 strings are only ever displayed, never trimmed or rewritten. */
(function () {
  "use strict";
  var data = window.SPACING_DATA, core = window.SpacingCore;
  var detail = document.getElementById("detail");
  if (!data || !core) {
    detail.textContent = "spacing_data.js is missing. Run: py -3.14 scripts/build_spacing_review.py";
    return;
  }
  var STORE_KEY = "nko-spacing-review:" + data.source.spacing_sample_sha256;
  var PREF_KEY = "nko-spacing-review-prefs";
  var KEYS = { q1: ["1", "2", "3"], q2: ["4", "5", "6"], q3: ["7", "8", "9"], q4: ["z", "x", "c"] };
  var HELP = {
    q1: "Compare the numbered changes on the printed line with the v1.2 text. Yes if every word break in v1.2 matches a visible break in print.",
    q2: "Yes if any green (inserted) space splits what is printed as one word.",
    q3: "Yes if any red (removed) space separated two words in print. Removed spaces should only be indents or line-end space.",
    q4: "Yes if the print is unclear, the entry is hard to read, or you could not decide."
  };
  var RULES = {
    positioned_space_inserted: function (c) { return "Gap in the print with no glyph, " + c.gap_pt + " pt wide (one space ≈ 2.5 pt): " + c.count + " space(s) inserted"; },
    leading_layout_space_removed: function () { return "Space glyph before the first visible glyph of the line (indent): removed"; },
    trailing_layout_space_removed: function () { return "Space glyph after the last visible glyph of the line: removed"; },
    wa_tail_gap_not_a_space: function (c) { return "Gap of " + c.gap_pt + " pt after ߥ is the slot its tail is drawn into: left joined (no change)"; },
    narrow_gap_not_spaced: function (c) { return "Gap of " + c.gap_pt + " pt is narrower than a space: left joined (no change)"; },
    wide_gap_not_spaced: function (c) { return "Gap of " + c.gap_pt + " pt separates a stray fragment: not spaced (no change)"; }
  };

  function load(key, fallback) {
    try { var v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
  }
  var reviews = load(STORE_KEY, {});
  var prefs = load(PREF_KEY, { showSpaces: true, showCodepoints: false, markers: true, reviewer: "" });
  var state = { index: 0, visible: [] }, lastSave = "";

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
  function toast(msg) {
    var t = document.getElementById("toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(function () { t.hidden = true; }, 4000);
  }
  function kindsOf(rec) {
    var k = {};
    rec.changes.forEach(function (c) { k[c.kind] = (k[c.kind] || 0) + (c.kind === "kept" ? 1 : c.count); });
    return k;
  }

  // --- exact text --------------------------------------------------------------
  function nkoText(s) {
    var el = h("span", { class: "nko", dir: "rtl", lang: "nqo" });
    if (!prefs.showSpaces) { el.textContent = s; return el; }
    var re = /( +)|(⟨U\+[0-9A-F]{4,5}⟩)|([^ ⟨]+|⟨)/g, m;
    while ((m = re.exec(s))) {
      if (m[1]) el.appendChild(h("span", { class: "ws", title: m[1].length + " space(s)" }, m[1].replace(/ /g, "·")));
      else if (m[2]) el.appendChild(placeholder(m[2]));
      else el.appendChild(document.createTextNode(m[3]));
    }
    return el;
  }
  function placeholder(s) {
    return h("span", { class: "ph", dir: "ltr", title: "candidate/unknown legacy code, shown as a placeholder" }, s);
  }
  // Text without spaces, with placeholders kept left-to-right so their brackets do not mirror.
  function appendText(el, s) {
    s.split(/(⟨U\+[0-9A-F]{4,5}⟩)/).forEach(function (part, i) {
      if (part) el.appendChild(i % 2 ? placeholder(part) : document.createTextNode(part));
    });
  }
  function codepoints(s) {
    return h("div", { class: "cps" }, Array.from(s).map(function (ch) {
      return "U+" + ch.codePointAt(0).toString(16).toUpperCase().padStart(4, "0");
    }).join(" "));
  }

  // The v1.2 line with every change as a numbered badge at its place in the text.
  function diffText(line, li, rec) {
    var at = {};
    rec.changes.forEach(function (c) {
      if (c.line !== li) return;
      var key = c.kind + ":" + c.offset;
      (at[key] = at[key] || []).push(c);
    });
    var el = h("span", { class: "nko", dir: "rtl", lang: "nqo" }), k = 0, keptDone = {};
    function badge(kind, list, n) {
      var sym = kind === "ins" ? "+" + "␣".repeat(n) : kind === "del" ? "−" + "␣".repeat(n) : "∥";
      var tip = list.map(function (c) { return "#" + c.id + " " + RULES[c.rule](c); }).join("\n");
      return h("span", { class: kind, title: tip, dir: "ltr" }, sym + " " + list.map(function (c) { return c.id; }).join(","));
    }
    function kept(off) {
      if (keptDone[off] || !at["kept:" + off]) return;
      keptDone[off] = true;
      el.appendChild(badge("kept", at["kept:" + off]));
    }
    line.segments.forEach(function (seg) {
      if (seg.t === "text") {
        var chars = Array.from(seg.s), buf = "";
        chars.forEach(function (ch, j) {
          if (at["kept:" + (k + j)] && !keptDone[k + j]) {
            if (buf) { appendText(el, buf); buf = ""; }
            kept(k + j);
          }
          buf += ch;
        });
        if (buf) appendText(el, buf);
        k += chars.length;
      } else if (seg.t === "space") {
        el.appendChild(h("span", { class: "same", title: seg.n + " unchanged space(s)" }, "·".repeat(seg.n)));
      } else {
        var kind = seg.t === "ins" ? "inserted" : "removed";
        el.appendChild(badge(seg.t, at[kind + ":" + seg.offset] || [], seg.n));
      }
    });
    kept(k);
    return el;
  }

  // --- crops ---------------------------------------------------------------------
  function cropView(ctx, alt) {
    var wrap = h("div", { class: "crop" }, h("img", { src: ctx.img, alt: alt, width: ctx.px && ctx.px[0], height: ctx.px && ctx.px[1] }));
    ctx.boxes.forEach(function (b) {
      var box = h("span", { class: "box k-" + b.kind });
      box.style.left = (b.l * 100) + "%"; box.style.top = (b.t * 100) + "%";
      box.style.width = (b.w * 100) + "%"; box.style.height = (b.h * 100) + "%";
      if (b.kind === "nko") box.appendChild(h("b", null, String(b.line + 1)));
      wrap.appendChild(box);
    });
    return wrap;
  }
  function lineCrop(line, li) {
    var wrap = h("div", { class: "crop" + (prefs.markers ? "" : " nomk") },
      h("img", { src: line.img, alt: "Printed N'Ko line " + (li + 1), width: line.px && line.px[0], height: line.px && line.px[1] }));
    line.markers.forEach(function (m) {
      var mk = h("span", { class: "mk " + (m.kind === "inserted" ? "ins" : m.kind === "removed" ? "del" : "kept") }, h("i", null, String(m.id)));
      mk.style.left = (m.l * 100) + "%"; mk.style.width = (m.w * 100) + "%";
      wrap.appendChild(mk);
    });
    return wrap;
  }
  function legend() {
    return h("div", { class: "legend" },
      h("span", null, h("i", { class: "sw ins" }), "inserted space (green)"),
      h("span", null, h("i", { class: "sw del" }), "removed space (red)"),
      h("span", null, h("i", { class: "sw kept" }), "gap measured, left joined"),
      h("span", null, "Numbers match the table below and the markers on the printed line."));
  }

  // --- list ------------------------------------------------------------------------
  function statusOf(rec) { return core.status(reviews[rec.spacing_id]); }
  function matches(rec) {
    var st = document.getElementById("f-stratum").value, fs = document.getElementById("f-status").value;
    var fc = document.getElementById("f-change").value, q = document.getElementById("f-search").value.trim().toLowerCase();
    if (st !== "all" && rec.row.stratum !== st) return false;
    if (fs === "problem" && !core.problems(reviews[rec.spacing_id]).length) return false;
    if (["unreviewed", "partial", "complete"].indexOf(fs) >= 0 && statusOf(rec) !== fs) return false;
    if (fc !== "all" && !kindsOf(rec)[fc]) return false;
    if (q && [rec.spacing_id, rec.row.sample_id, rec.row.headword, rec.row.entry_ref].join(" ").toLowerCase().indexOf(q) < 0) return false;
    return true;
  }
  function renderList() {
    var list = document.getElementById("record-list"), current = data.records[state.index];
    state.visible = []; list.textContent = "";
    data.records.forEach(function (rec, i) {
      if (!matches(rec)) return;
      state.visible.push(i);
      var st = statusOf(rec), k = kindsOf(rec);
      var dot = core.problems(reviews[rec.spacing_id]).length ? "problem" : st;
      list.appendChild(h("li", { class: rec === current ? "current" : "", title: rec.row.entry_ref, onclick: function () { go(i); } },
        h("span", { class: "dot " + dot, title: st }),
        h("span", { class: "sid", text: rec.spacing_id }),
        h("span", { class: "hw", text: rec.row.headword || "(" + rec.row.entry_kind + ")" }),
        h("span", { class: "tag", text: "+" + (k.inserted || 0) + " −" + (k.removed || 0) + (k.kept ? " ∥" + k.kept : "") })));
    });
    document.getElementById("list-count").textContent = state.visible.length + " of " + data.records.length + " shown";
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

  // --- answers ---------------------------------------------------------------------
  function touch(r) {
    r.reviewer = prefs.reviewer || r.reviewer || "";
    r.updated_at = new Date().toISOString();
    lastSave = save(STORE_KEY, reviews) ? "Saved in this browser " + new Date().toLocaleTimeString()
      : "Browser storage unavailable: export before closing";
  }
  function setAnswer(key, value) {
    var rec = data.records[state.index], r = reviews[rec.spacing_id] || (reviews[rec.spacing_id] = {});
    r[key] = r[key] === value ? "" : value;
    touch(r);
    renderDetail(); renderList(); renderProgress();
  }

  // --- detail ----------------------------------------------------------------------
  function renderDetail() {
    var rec = data.records[state.index], row = rec.row, r = reviews[rec.spacing_id] || {}, k = kindsOf(rec);
    detail.textContent = "";
    detail.appendChild(h("div", { class: "meta" },
      h("h2", { text: rec.spacing_id + " · " + (row.headword || "(no headword: " + row.entry_kind + ")") }),
      h("span", { class: "chip ins", text: "+" + (k.inserted || 0) + " inserted" }),
      h("span", { class: "chip del", text: "−" + (k.removed || 0) + " removed" }),
      k.kept ? h("span", { class: "chip kept", text: k.kept + " left joined" }) : null));
    var facts = [
      ["Original sample", row.sample_id + " · " + row.stratum],
      ["Entry", row.entry_ref + " (" + row.entry_kind + ")"],
      ["Location", "PDF page " + row.page_number + " (not the printed page number), " + (row.column_index === "1" ? "right" : "left") + " column"]
    ];
    if (rec.flags.length) facts.push(["Flags", rec.flags.join(", ")]);
    detail.appendChild(h("dl", { class: "facts" }, facts.map(function (f) { return [h("dt", { text: f[0] }), h("dd", { text: f[1] })]; })));

    detail.appendChild(h("section", { class: "card" },
      h("h3", null, "Printed entry ", h("span", { class: "muted", text: "· N'Ko lines numbered, French headword dashed" })),
      cropView(rec.context, "Printed entry " + row.entry_ref)));

    var toggles = h("div", { class: "toggles" },
      toggle("showSpaces", "Show spaces as ·"), toggle("markers", "Change markers on print"), toggle("showCodepoints", "Show code points"));
    detail.appendChild(h("section", { class: "card" },
      h("h3", null, "Line by line ", h("span", { class: "muted", text: "· printed line, then v1.1, v1.2 and the changes between them" })),
      legend(), toggles,
      rec.lines.map(function (ln, li) {
        return h("div", { class: "line" },
          h("h4", { text: "Line " + (li + 1) + " · baseline y=" + ln.y }),
          lineCrop(ln, li),
          h("div", { class: "vrow" }, h("span", { class: "lab", text: "v1.1" }), nkoText(ln.old)),
          prefs.showCodepoints ? codepoints(ln.old) : null,
          h("div", { class: "vrow" }, h("span", { class: "lab", text: "v1.2" }), nkoText(ln.new)),
          prefs.showCodepoints ? codepoints(ln.new) : null,
          h("div", { class: "vrow" }, h("span", { class: "lab", text: "Changes" }), diffText(ln, li, rec)));
      })));

    detail.appendChild(h("section", { class: "card" },
      h("h3", null, "Evidence ", h("span", { class: "muted", text: "· from the v1.2 build, re-measured in the PDF for this kit" })),
      h("table", { class: "changes" },
        h("thead", null, h("tr", null, ["#", "Line", "Change", "Reason", "Gap (pt)"].map(function (t) { return h("th", { text: t }); }))),
        h("tbody", null, rec.changes.map(function (c) {
          return h("tr", null, h("td", { class: "num", text: String(c.id) }), h("td", { class: "num", text: String(c.line + 1) }),
            h("td", { class: "kind " + c.kind, text: c.kind === "kept" ? "left joined" : c.kind }),
            h("td", { text: RULES[c.rule](c) }), h("td", { class: "num", text: c.gap_pt == null ? "–" : String(c.gap_pt) }));
        })))));

    detail.appendChild(questionsCard(rec, r));
  }

  function questionsCard(rec, r) {
    var notes = h("textarea", { id: "notes", placeholder: "e.g. #3 splits one word; line 2 print unclear" });
    notes.value = r.notes || "";
    notes.addEventListener("input", function () {
      var rv = reviews[rec.spacing_id] || (reviews[rec.spacing_id] = {});
      rv.notes = notes.value; touch(rv);
      document.getElementById("saved").textContent = lastSave;
      renderProgress();
    });
    notes.addEventListener("change", renderList);
    return h("section", { class: "card" },
      h("h3", null, "Review ", h("span", { class: "muted", text: "· status: " + statusOf(rec) })),
      h("div", { class: "questions" },
        core.QUESTIONS.map(function (q) {
          return h("div", { class: "q" }, h("h4", { text: q.title }), h("p", { text: HELP[q.key] }),
            h("div", { class: "answers", role: "group", "aria-label": q.title }, data.answers.map(function (a, i) {
              return h("button", { type: "button", "aria-pressed": r[q.key] === a ? "true" : "false",
                class: a === q.problem || a === "uncertain" ? "bad" : "", onclick: function () { setAnswer(q.key, a); } },
                a, h("kbd", { text: KEYS[q.key][i] }));
            })));
        }),
        h("label", null, h("div", { class: "label", text: "Notes" }), notes)),
      h("div", { class: "nav" },
        h("button", { type: "button", onclick: function () { step(-1); } }, "← Previous"),
        h("button", { type: "button", onclick: function () { step(1); } }, "Next →"),
        h("button", { type: "button", onclick: nextOpen }, "Next unfinished"),
        h("span", { class: "hint", text: "Keys: 1–3 · 4–6 · 7–9 · z/x/c answer questions 1–4 (yes/no/uncertain) · j/k next/previous · u next unfinished" }),
        h("span", { id: "saved", class: "saved", text: lastSave })));
  }

  function toggle(pref, label) {
    var cb = h("input", { type: "checkbox", onchange: function () { prefs[pref] = cb.checked; save(PREF_KEY, prefs); renderDetail(); } });
    cb.checked = !!prefs[pref];
    return h("label", null, cb, " " + label);
  }

  // --- navigation ------------------------------------------------------------------
  function go(i) {
    state.index = i;
    renderDetail(); renderList();
    window.scrollTo(0, 0);
    try { history.replaceState(null, "", "#" + data.records[i].spacing_id); } catch (e) { /* file:// may refuse */ }
  }
  function step(d) {
    var vis = state.visible.length ? state.visible : data.records.map(function (_r, i) { return i; });
    var pos = vis.indexOf(state.index);
    var next = pos < 0 ? vis[0] : vis[Math.min(vis.length - 1, Math.max(0, pos + d))];
    if (next !== undefined) go(next);
  }
  function nextOpen() {
    for (var n = 1; n <= data.records.length; n++) {
      var i = (state.index + n) % data.records.length;
      if (statusOf(data.records[i]) !== "complete") return go(i);
    }
    toast("Every record is complete.");
  }
  document.addEventListener("keydown", function (ev) {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    var t = ev.target.tagName;
    if (t === "INPUT" || t === "TEXTAREA" || t === "SELECT" || document.querySelector("dialog[open]")) return;
    var hit = null;
    Object.keys(KEYS).forEach(function (q) { var i = KEYS[q].indexOf(ev.key); if (i >= 0) hit = [q, data.answers[i]]; });
    if (hit) { setAnswer(hit[0], hit[1]); ev.preventDefault(); return; }
    if (ev.key === "j" || ev.key === "ArrowDown") { step(1); ev.preventDefault(); }
    else if (ev.key === "k" || ev.key === "ArrowUp") { step(-1); ev.preventDefault(); }
    else if (ev.key === "u") nextOpen();
  });

  // --- header tools ------------------------------------------------------------------
  var fStratum = document.getElementById("f-stratum");
  fStratum.appendChild(h("option", { value: "all", text: "All original strata" }));
  Array.from(new Set(data.records.map(function (r) { return r.row.stratum; }))).forEach(function (s) {
    fStratum.appendChild(h("option", { value: s, text: s }));
  });
  ["f-stratum", "f-status", "f-change", "f-search"].forEach(function (id) {
    document.getElementById(id).addEventListener("input", renderList);
  });
  var reviewer = document.getElementById("reviewer");
  reviewer.value = prefs.reviewer || "";
  reviewer.addEventListener("input", function () { prefs.reviewer = reviewer.value.trim(); save(PREF_KEY, prefs); });

  document.getElementById("btn-export").addEventListener("click", function () {
    var blob = new Blob([core.exportTsv(data, reviews)], { type: "text/tab-separated-values;charset=utf-8" });
    var a = h("a", { href: URL.createObjectURL(blob), download: "spacing_sample.v1.review.tsv" });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    toast("Exported spacing_sample.v1.review.tsv to your browser's download folder.\nMove it into data/spacing_review/ and keep it local.");
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
      toast("Imported " + n + " reviews" + (res.errors.length ? "; " + res.errors.length + " row(s) skipped:\n" + res.errors.slice(0, 5).join("\n") : "."));
    });
    ev.target.value = "";
  });
  document.getElementById("btn-reset").addEventListener("click", function () {
    if (!confirm("Clear every spacing review stored in this browser? Export first if you need them.")) return;
    reviews = {}; save(STORE_KEY, reviews);
    renderDetail(); renderList(); renderProgress();
  });
  document.getElementById("btn-summary").addEventListener("click", function () {
    var sum = core.summarize(data, reviews), body = document.getElementById("summary-body");
    body.textContent = "";
    var cols = data.answers.concat(["unanswered"]);
    core.QUESTIONS.forEach(function (q) {
      body.appendChild(h("h3", { text: q.title }));
      body.appendChild(h("table", { class: "sum" },
        h("thead", null, h("tr", null, h("th", { text: "Group" }), cols.map(function (c) { return h("th", { text: c }); }))),
        h("tbody", null, Object.keys(sum).map(function (s) {
          return h("tr", null, h("td", { text: s === "all" ? "All " + sum[s].total : s + " (" + sum[s].total + ")" }),
            cols.map(function (c) { return h("td", { text: String((sum[s][q.key] || {})[c] || 0) }); }));
        }))));
    });
    document.getElementById("summary-dialog").showModal();
  });

  var start = 0, hash = location.hash.slice(1);
  data.records.forEach(function (r, i) { if (r.spacing_id === hash) start = i; });
  renderProgress();
  go(start);
})();
