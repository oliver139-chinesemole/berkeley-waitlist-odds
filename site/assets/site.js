// Berkeley Waitlist Odds: code shared by every page (docs/DESIGN_A6.md).
// Static site, no build step, no dependencies. Loaded before each page's own
// script; exposes BWO. Every number shown comes from site/data/*.json written by
// analysis/export.py; this file reads curves, it never computes a statistic.
const BWO = (function () {
  "use strict";
  const SITE = "Berkeley Waitlist Odds";
  const REPO = "https://github.com/oliver139-chinesemole/berkeley-waitlist-odds";
  const BUCKETS = [[1, 5, "1-5"], [6, 15, "6-15"], [16, 40, "16-40"], [41, 1e9, "41+"]];
  const BUCKET_ORDER = ["1-5", "6-15", "16-40", "41+"];
  const DAY = 86400000;
  // Verdict thresholds (docs/dev/SITE_V3_PLAN.md decision 2); printed on the page wherever a verdict appears.
  const VERDICT = { likely: 0.75, unlikely: 0.40, wide: 0.30 };
  // Common shorthand for subjects, mapped to the spelling classes.berkeley.edu uses.
  const SUBJECT_ALIASES = {
    CS: "COMPSCI", COMPSCI: "COMPSCI", "COMP SCI": "COMPSCI", EE: "ELENG", "EL ENG": "ELENG", MCB: "MCELLBI", IB: "INTEGBI", BIO: "BIOLOGY",
    PE: "PHYSED", "PHYS ED": "PHYSED", NST: "NUSCTX", NUTRITION: "NUSCTX", STATS: "STAT", DS: "DATA", "DATA SCIENCE": "DATA", PS: "POLSCI", POLISCI: "POLSCI",
    "POLI SCI": "POLSCI", "POL SCI": "POLSCI", BA: "UGBA", HAAS: "UGBA", ME: "MECENG", "MEC ENG": "MECENG", CE: "CIVENG", "CIV ENG": "CIVENG",
    CHEME: "CHMENG", "CHM ENG": "CHMENG", IEOR: "INDENG", "IND ENG": "INDENG", MSE: "MATSCI", "MAT SCI": "MATSCI", NE: "NUCENG", "NUC ENG": "NUCENG",
    BIOE: "BIOENG", "BIO ENG": "BIOENG", ASTRO: "ASTRON", PHYS: "PHYSICS", ANTH: "ANTHRO", SOC: "SOCIOL", HIST: "HISTORY", PHIL: "PHILOS",
    LING: "LINGUIS", RHET: "RHETOR", PH: "PBHLTH", "PB HLTH": "PBHLTH", "PUB HLTH": "PBHLTH", "PUBLIC HEALTH": "PBHLTH", ENGL: "ENGLISH", ED: "EDUC",
    NEURO: "NEU", NEUROSCI: "NEU", THEATRE: "THEATER", SPAN: "SPANISH", FREN: "FRENCH", GERM: "GERMAN", CHIN: "CHINESE", JAPN: "JAPAN",
    JAPANESE: "JAPAN", KOR: "KOREAN", ITAL: "ITALIAN", "COG SCI": "COGSCI", "ENV ECON": "ENVECON", "ENE RES": "ENERES", "ART HIST": "HISTART",
    "HIST ART": "HISTART", "PUB POL": "PUBPOL", "ETH STD": "ETHSTD", ASAM: "ASAMST", "COL WRIT": "COLWRIT", "L&S": "LS", "L S": "LS",
    "CY PLAN": "CYPLAN", "LD ARCH": "LDARCH", "ENV DES": "ENVDES", "DES INV": "DESINV", "AERO ENG": "AEROENG", "LEGAL ST": "LEGALST",
    "MEDIA ST": "MEDIAST", MEDIA: "MEDIAST", "MIL SCI": "MILSCI", "NAV SCI": "NAVSCI", "PLANT BI": "PLANTBI", "SOC WEL": "SOCWEL",
  };

  // ------------------------------------------------------------------ helpers
  const $ = (id) => document.getElementById(id);
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function pct(p) { return Math.round(p * 100) + "%"; }
  function num(n) { return Number(n).toLocaleString("en-US"); }
  function fmtDate(iso) { try { return new Date(iso).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" }); } catch (e) { return iso; } }
  function fmtDay(iso) { try { return new Date(iso + "T12:00:00Z").toLocaleDateString("en-US", { dateStyle: "medium", timeZone: "UTC" }); } catch (e) { return iso; } }
  function fmtShort(d) { try { return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }); } catch (e) { return d.toISOString().slice(0, 10); } }
  function days(n) { const r = Math.round(n); return r === 1 ? "1 day" : r + " days"; }
  function plural(n, one, many) { return n === 1 ? `1 ${one}` : `${num(n)} ${many || one + "s"}`; }
  function bucketOf(pos) { for (const [lo, hi, label] of BUCKETS) if (pos >= lo && pos <= hi) return label; return "41+"; }
  function bucketText(b) { return b === "41+" ? "positions 41 and up" : "positions " + b.replace("-", " to "); }
  function addDays(date, n) { return new Date(date.getTime() + n * DAY); }
  function params() { return new URLSearchParams(typeof location !== "undefined" ? location.search : ""); }
  function today() {
    const t = params().get("today");
    const d = t ? new Date(t + "T12:00:00Z") : new Date();
    return isNaN(d.getTime()) ? new Date() : d;
  }
  function pinned() { const t = params().get("today"); return t && !isNaN(new Date(t + "T12:00:00Z").getTime()) ? t : null; }
  // Keep ?today= on internal links so a pinned date follows the reader around the site.
  function withToday(href) { const t = pinned(); return t ? href + (href.includes("?") ? "&" : "?") + "today=" + t : href; }

  // --------------------------------------------------------------- data files
  const cache = {};
  const loaded = {}; // what load() fetched, for the page and for the tests
  async function fetchJson(url) {
    if (cache[url]) return cache[url];
    let out;
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (r.ok) out = { ok: true, data: await r.json() };
      else out = { ok: false, status: r.status, missing: r.status === 404 };
    } catch (e) {
      out = { ok: false, status: 0, missing: false, error: e };
    }
    if (out.ok || out.missing) cache[url] = out;
    return out;
  }
  function dataReady(meta) { return !!(meta && meta.events && meta.events >= 10 && meta.deadline && meta.instruction_start); }
  // Loads meta plus the named files ("index", "pooled", "insights", "backtest").
  // state: loading -> ready | empty (no estimates yet) | failed (could not fetch).
  async function load(names) {
    const m = await fetchJson("data/meta.json");
    if (!m.ok && !m.missing) return { state: "failed", error: m };
    const meta = m.ok ? m.data : null;
    loaded.meta = meta;
    if (!dataReady(meta)) return { state: "empty", meta };
    const files = meta.files || { index: "index.json", pooled: "pooled.json", insights: "insights.json" };
    const data = {};
    const results = await Promise.all((names || []).map((n) => fetchJson("data/" + (files[n] || n + ".json"))));
    for (let i = 0; i < (names || []).length; i++) {
      const r = results[i];
      if (r.ok) data[names[i]] = r.data;
      else if (r.missing) data[names[i]] = null;
      else return { state: "failed", error: r, meta };
      loaded[names[i]] = data[names[i]];
    }
    return { state: "ready", meta, data };
  }
  async function loadSubject(meta, subject) {
    const rel = meta.subject_files && meta.subject_files[subject];
    if (!rel) return null;
    const r = await fetchJson("data/" + rel);
    return r.ok ? r.data : null;
  }

  // ----------------------------------------------------------- state markup
  function emptyHtml(meta) {
    const counts = meta ? ` Snapshots so far: ${esc(meta.sections)} sections, ${esc(meta.cohort_rows)} hypothetical joiners, ${esc(meta.events)} clearings.` : "";
    return `<p><strong>No estimates yet.</strong> Snapshots for Spring 2027 enrollment start with Phase 1 on Oct 26, 2026; the first curves appear once enough waitlists have cleared (planned for mid-November).${counts}</p>`;
  }
  function failedHtml() {
    return `<p class="error"><strong>Could not load the estimates.</strong> The data files did not download; check your connection and try again. <button type="button" class="quiet" onclick="location.reload()">Reload</button></p>`;
  }
  function skeletonHtml() { return `<p class="muted">Loading data…</p><div class="skeleton" style="width:70%"></div><div class="skeleton" style="width:45%"></div>`; }
  function sourceHtml(meta) {
    const counts = `${esc(num(meta.courses))} courses with estimates from ${esc(num(meta.sections))} sections and ${esc(num(meta.cohort_rows))} hypothetical joiners, ${esc(num(meta.events))} of whom cleared`;
    if (meta.data_source === "berkeleytime_history") {
      return `<p><strong>${esc(meta.term_name)}</strong>, from Berkeleytime's public 15-minute enrollment history: ${counts}. Live Spring 2027 collection by this project starts Oct 26, 2026; the estimates switch to its own snapshots once Spring waitlists start clearing.</p>`;
    }
    return `<p><strong>${esc(meta.term_name)}</strong>: ${counts}.</p>`;
  }
  function sourceLabel(meta) {
    return meta.data_source === "berkeleytime_history" ? `${esc(meta.term_name)}, from Berkeleytime's public history` : `${esc(meta.term_name)}, this project's own snapshots`;
  }
  function stamp(meta, t) {
    const h = horizons(meta, t);
    const pin = pinned();
    const when = pin ? ` Horizons computed for ${esc(pin)}.` : "";
    return "Data through " + fmtDate(meta.join_window ? meta.join_window[1] : meta.generated_at) + "; page generated " + fmtDate(meta.generated_at) + "." + when + (h.deadline > 0 ? ` Last automatic waitlist run ${fmtDay(meta.deadline)} (${days(h.deadline)} away).` : "");
  }
  function setStamp(meta, t) { const el = $("stamp"); if (el) el.textContent = meta ? stamp(meta, t) : ""; }

  // ------------------------------------------------------------- horizons
  // Days from "today" to the end of the last automatic waitlist run's day and to
  // 00:00 UTC on the first day of instruction, for the forecast term in meta.
  function horizons(meta, t) {
    const d = meta.deadline.split("-").map(Number), i = meta.instruction_start.split("-").map(Number);
    const deadlineEnd = Date.UTC(d[0], d[1] - 1, d[2] + 1);
    const instruction = Date.UTC(i[0], i[1] - 1, i[2]);
    return { deadline: (deadlineEnd - t.getTime()) / DAY, instruction: (instruction - t.getTime()) / DAY };
  }
  // The strip of key dates: what is next, from the forecast term's calendar.
  function keyDates(meta, t) {
    const dates = meta.dates || {};
    const rows = [
      ["phase1_start", "Phase 1 opens"], ["phase2_start", "Phase 2 opens"], ["adjustment_start", "Adjustment period"],
      ["instruction_start", "First day of class"], ["last_auto_waitlist", "Last automatic waitlist run"], ["add_drop_deadline", "Add/drop deadline"],
    ];
    const out = [];
    for (const [key, label] of rows) {
      const iso = dates[key] || (key === "instruction_start" ? meta.instruction_start : key === "last_auto_waitlist" ? meta.deadline : null);
      if (!iso) continue;
      const p = iso.split("-").map(Number);
      const left = (Date.UTC(p[0], p[1] - 1, p[2]) - t.getTime()) / DAY;
      out.push({ key, label, iso, left, past: left < -1 });
    }
    return out;
  }
  function keyDatesHtml(meta, t) {
    const all = keyDates(meta, t);
    const upcoming = all.filter((d) => !d.past).slice(0, 3);
    const items = (upcoming.length ? upcoming : all.slice(-2)).map((d) => {
      const rel = d.left >= 1 ? `in ${days(d.left)}` : d.left > -1 ? "today" : `${days(-d.left)} ago`;
      const you = d.key === "instruction_start" || d.key === "last_auto_waitlist" ? " you" : "";
      return `<li class="${you.trim()}"><strong>${esc(fmtDay(d.iso))}</strong> ${esc(d.label)} <span class="muted">(${rel})</span></li>`;
    }).join("");
    return `<ul class="dates" aria-label="Key dates for ${esc(meta.forecast_term_name || meta.term_name)}"><li><strong>${esc(meta.forecast_term_name || meta.term_name)}</strong></li>${items}</ul>`;
  }

  // ----------------------------------------------------------------- curves
  // A curve is a step function: the last grid point at or before h days is
  // P(got in within h days); past the reach the last point stands, as a floor.
  function readCurve(curve, h) {
    let pt = null;
    for (const c of curve) { if (c[0] <= h) pt = c; else break; }
    if (!pt) return { p: 0, lo: null, hi: null, day: 0, capped: false };
    const reach = curve[curve.length - 1][0];
    return { p: pt[1], lo: pt[2], hi: pt[3], day: pt[0], capped: h > reach + 1e-9 };
  }
  function interval(r) { return r.lo == null || r.hi == null ? "" : ` <small>(95% interval ${pct(r.lo)} to ${pct(r.hi)})</small>`; }
  // Resolve a course's bucket cell to a curve cell: its own, or the pool it points at.
  function resolveCell(entry, bucket, pooled) {
    const cell = entry && entry.buckets && entry.buckets[bucket];
    if (!cell) return null;
    if (cell.pooled === false) return { cell, pooled: false, own: null, source: "course" };
    if (!pooled) return { cell: null, pooled: cell.pooled, own: cell, source: "pending" };
    const pool = cell.pooled === "all" ? pooled.all[bucket] : (pooled.dept[cell.pooled] || {})[bucket];
    return pool ? { cell: pool, pooled: cell.pooled, own: cell, source: cell.pooled === "all" ? "all" : "dept" } : null;
  }
  // Fallback for a course with no cell: department, then level, then all courses.
  function fallbackCell(pooled, bucket, dept, level) {
    if (!pooled) return null;
    if (dept && pooled.dept[dept] && pooled.dept[dept][bucket]) return { cell: pooled.dept[dept][bucket], pooled: dept, source: "dept" };
    if (level && pooled.level[level] && pooled.level[level][bucket]) return { cell: pooled.level[level][bucket], pooled: level, source: "level" };
    if (pooled.all[bucket]) return { cell: pooled.all[bucket], pooled: "all", source: "all" };
    return null;
  }
  // What a course's estimate is: meta.estimate_level "dept" (the department's curve for the
  // bucket stands in for every course; the course's own cases are counts) or "course".
  function estimateLevel(meta) { return meta && meta.estimate_level === "course" ? "course" : "dept"; }
  function pooledTag(pooled, source, meta) {
    if (pooled === false || pooled == null) return "";
    if (source === "dept" && estimateLevel(meta) === "dept") return "";  // the department curve is the estimate, not a fallback
    const what = source === "all" ? "all courses" : source === "level" ? `all ${esc(pooled)}-division courses` : `the whole ${esc(pooled)} department`;
    return `<span class="tag pooled" title="Too few cases for this course alone; estimate uses ${what}">pooled</span>`;
  }
  function pooledSentence(pooled, source, meta) {
    if (pooled === false || pooled == null) return "";
    if (source === "all") return "Pooled over all courses at these positions.";
    if (source === "level") return `Pooled over all ${esc(pooled)}-division courses at these positions.`;
    if (estimateLevel(meta) === "dept") return `Department estimate: the whole ${esc(pooled)} department at these positions.`;
    return `Pooled over the whole ${esc(pooled)} department at these positions.`;
  }
  // One sentence on the rule, for the pages' small print.
  function levelNote(meta) {
    if (estimateLevel(meta) === "dept") return `Estimates are by department and position, not by course: in the ${esc(meta.term_name)} backtest, course-level curves did not beat the position-only baseline, so a course's own cases are shown as counts next to its department's curve (<a href="accuracy.html">how accurate it was</a>).`;
    return `Estimates are by course and position when a course has at least ${esc(meta.min_n || 30)} cases, otherwise by department (labelled pooled): across whole cycles, a course's own curve predicted better than its position alone (<a href="accuracy.html">how accurate it was</a>).`;
  }
  function levelOf(number) { const m = String(number || "").match(/(\d+)/); if (!m) return null; const n = parseInt(m[1], 10); return n < 100 ? "lower" : n < 200 ? "upper" : "grad"; }

  // ----------------------------------------------------------------- search
  // "cs61a", "CS 61A", "data 8", "Compsci C100" all resolve. Returns null when nothing parses.
  function parseQuery(text) {
    const t = String(text || "").toUpperCase().replace(/[^A-Z0-9&\s]/g, " ").replace(/\s+/g, " ").trim();
    if (!t) return null;
    const m = t.match(/^([A-Z&][A-Z&\s]*?)\s*(\d+[A-Z]*)$/);
    if (!m) return { subjects: subjectCandidates(t), numbers: [], raw: t };
    let subject = m[1].trim();
    let number = m[2];
    const subjects = [];
    const numbers = [number];
    for (const s of subjectCandidates(subject)) subjects.push({ subject: s, number });
    // "DATA C8", "MATH H53", "COMPSCI W182": a trailing C, H, N or W before the digits belongs to the number
    const cross = subject.match(/^(.*?)\s?([CHNW])$/);
    if (cross && cross[1]) {
      subjects.push(...subjectCandidates(cross[1].trim()).map((s) => ({ subject: s, number: cross[2] + number })));
    }
    if (!/^[A-Z]/.test(number)) numbers.push("C" + number);
    else if (/^C\d/.test(number)) numbers.push(number.slice(1));
    return { subjects: subjects.map((x) => x.subject), pairs: subjects, numbers, raw: t };
  }
  function subjectCandidates(subject) {
    const out = [];
    const push = (s) => { if (s && !out.includes(s)) out.push(s); };
    push(SUBJECT_ALIASES[subject]);
    push(subject);
    const squashed = subject.replace(/[\s&]+/g, "");
    push(SUBJECT_ALIASES[squashed]);
    push(squashed);
    return out;
  }
  function indexMap(index) {
    if (!index.__map) { const map = {}; for (const r of index.courses) map[r.key] = r; index.__map = map; }
    return index.__map;
  }
  function findCourse(index, text) {
    const q = parseQuery(text);
    if (!q || !q.pairs) return null;
    const map = indexMap(index);
    for (const pair of q.pairs) {
      for (const n of [pair.number, ...(q.numbers.filter((x) => x !== pair.number))]) {
        const hit = map[pair.subject + " " + n];
        if (hit) return hit;
      }
    }
    return null;
  }
  // Ranked suggestions for the combobox: prefix matches on the subject (aliases
  // expanded) and the number, most-joined first.
  function searchCourses(index, text, limit) {
    const q = parseQuery(text);
    if (!q) return [];
    const exact = findCourse(index, text);
    const subjects = q.subjects.length ? q.subjects : [q.raw];
    const numPrefixes = q.numbers.length ? q.numbers : [""];
    const rows = [];
    for (const r of index.courses) {
      let score = 0;
      for (const s of subjects) {
        if (r.subject === s) { score = 2; break; }
        if (r.subject.startsWith(s)) score = Math.max(score, 1);
      }
      if (!score && !q.numbers.length && r.key.replace(/\s+/g, "").startsWith(q.raw.replace(/[\s&]+/g, ""))) score = 1;
      if (!score) continue;
      if (q.numbers.length) {
        let ok = false;
        for (const n of numPrefixes) if (r.number.startsWith(n) || (n.startsWith("C") && r.number.startsWith(n.slice(1)))) ok = true;
        if (!ok) continue;
      }
      rows.push({ r, score: score + (exact && exact.key === r.key ? 10 : 0), joins: r.joins || 0 });
    }
    rows.sort((a, b) => b.score - a.score || b.joins - a.joins || a.r.key.localeCompare(b.r.key));
    return rows.slice(0, limit || 8).map((x) => x.r);
  }
  // Courses with their own cell at the given bucket, most-joined first (example chips).
  function topCourses(index, n, bucket) {
    const b = bucket || "6-15";
    const byJoins = (x, y) => (y.joins || 0) - (x.joins || 0) || x.key.localeCompare(y.key);
    const standing = (r) => r.buckets[b] && (r.buckets[b].pooled === false || (r.buckets[b].pooled !== "all" && (r.buckets[b].n_course || 0) >= 30));
    const own = index.courses.filter(standing).sort(byJoins);
    if (own.length >= (n || 3)) return own.slice(0, n || 3);
    // too few courses stand on their own at that bucket: any own cell, then any course
    const anyOwn = index.courses.filter((r) => !own.includes(r) && Object.values(r.buckets).some((c) => c.pooled === false)).sort(byJoins);
    const rest = index.courses.filter((r) => !own.includes(r) && !anyOwn.includes(r)).sort(byJoins);
    return own.concat(anyOwn, rest).slice(0, n || 3);
  }
  function relatedCourses(index, row, bucket, n) {
    const b = bucket || "6-15";
    const same = index.courses.filter((r) => r.key !== row.key && r.subject === row.subject && r.buckets[b] && r.buckets[b].pooled !== "all");
    same.sort((x, y) => (y.joins || 0) - (x.joins || 0) || x.key.localeCompare(y.key));
    return same.slice(0, n || 5);
  }

  // ----------------------------------------------------------- the result
  function verdict(r, pooled) {
    if (pooled === "all" || r.lo == null || r.hi == null || (r.hi - r.lo) > VERDICT.wide) return { label: "Too little data to call", why: pooled === "all" ? "the estimate is pooled over all courses" : r.lo == null ? "one section only, no interval" : "the interval is wider than 30 points" };
    if (r.p >= VERDICT.likely) return { label: "Likely", why: `${pct(VERDICT.likely)} or more` };
    if (r.p >= VERDICT.unlikely) return { label: "Could go either way", why: `${pct(VERDICT.unlikely)} to ${pct(VERDICT.likely - 0.01)}` };
    return { label: "Unlikely", why: `below ${pct(VERDICT.unlikely)}` };
  }
  const VERDICT_NOTE = `Verdicts: Likely at ${pct(VERDICT.likely)} or more, Could go either way from ${pct(VERDICT.unlikely)} to ${pct(VERDICT.likely - 0.01)}, Unlikely below ${pct(VERDICT.unlikely)}; Too little data to call when the interval is wider than ${Math.round(VERDICT.wide * 100)} points, the estimate rests on one section, or it is pooled over all courses.`;
  function frequency(p) { const k = Math.round(p * 20); return k === 0 ? "Almost no one" : k === 20 ? "Almost everyone" : `About ${k} in 20`; }
  function dots(p, opts) {
    const k = Math.round(p * 20);
    let s = "";
    for (let i = 0; i < 20; i++) s += `<i class="${i < k ? "on" : ""}"></i>`;
    return `<span class="dots${opts && opts.dim ? " dim" : ""}" role="img" aria-label="${k} of 20 dots filled: ${pct(p)}">${s}</span>`;
  }
  // The headline block shared by the lookup and the course page (same words, same code).
  function headlineHtml(cell, pooled, source, meta, t) {
    const h = horizons(meta, t);
    let html = "";
    const marks = [];
    if (h.deadline <= 0) {
      const last = readCurve(cell.curve, 1e9);
      const v = verdict(last, pooled);
      html += `<p class="lead">${frequency(last.p)} got in within ${days(last.day)} of joining</p>${dots(last.p)}
        <div class="big">${pct(last.p)}${interval(last)}</div>
        <p>The last automatic waitlist run for ${esc(meta.forecast_term_name || meta.term_name)} was on ${esc(fmtDay(meta.deadline))}; waitlists are no longer processed automatically, so this is a look back, not a forecast.</p>
        <p><span class="verdict">${esc(v.label)}</span> <span class="muted small">(${esc(v.why)})</span></p>`;
      return { html, marks, h };
    }
    const atDeadline = readCurve(cell.curve, h.deadline);
    const v = verdict(atDeadline, pooled);
    html += `<p class="lead">${frequency(atDeadline.p)} got in by ${esc(fmtDay(meta.deadline))}</p>${dots(atDeadline.p)}
      <div class="big">${pct(atDeadline.p)}${interval(atDeadline)}</div>
      <p>of comparable students had cleared within ${days(h.deadline)} of joining, the time left before the last automatic waitlist run (${esc(fmtDay(meta.deadline))}).</p>
      <p><span class="verdict">${esc(v.label)}</span> <span class="muted small">(${esc(v.why)})</span></p>`;
    marks.push({ day: h.deadline, label: "last waitlist run" });
    if (atDeadline.capped) html += `<p class="note muted">The data follow joiners for ${days(atDeadline.day)}; treat this as a floor.</p>`;
    if (h.instruction > 0) {
      const atInstruction = readCurve(cell.curve, h.instruction);
      html += `<p><strong>${pct(atInstruction.p)}</strong> by the first day of instruction (${esc(fmtDay(meta.instruction_start))}, ${days(h.instruction)} from now).</p>`;
      marks.push({ day: h.instruction, label: "instruction" });
    } else {
      html += `<p class="note muted">Instruction has begun; most clearing happens after the first day of class.</p>`;
    }
    return { html, marks, h, atDeadline };
  }
  // "By when": fixed horizons plus the two calendar dates, each with its date from today.
  function byWhenHtml(cell, meta, t) {
    const h = horizons(meta, t);
    const rows = [];
    for (const d of [7, 14]) if (h.deadline <= 0 || d < h.deadline) rows.push({ label: `${d} days from now`, day: d, date: addDays(t, d) });
    if (h.instruction > 0) rows.push({ label: "First day of class", day: h.instruction, date: new Date(meta.instruction_start + "T00:00:00Z") });
    if (h.deadline > 0) rows.push({ label: "Last waitlist run", day: h.deadline, date: new Date(meta.deadline + "T00:00:00Z") });
    if (!rows.length) return "";
    const tr = rows.map((r) => { const v = readCurve(cell.curve, r.day); return `<tr><td>${esc(r.label)} <span class="muted">(${esc(fmtShort(r.date))})</span></td><td class="num"><strong>${pct(v.p)}</strong>${v.capped ? ' <span class="muted small">floor</span>' : ""}</td><td class="num muted small">${v.lo == null ? "" : pct(v.lo) + " to " + pct(v.hi)}</td></tr>`; }).join("");
    return `<table class="bywhen" aria-label="Share who got in, by when"><thead><tr><th>By when</th><th class="num">Share who got in</th><th class="num">95% interval</th></tr></thead><tbody>${tr}</tbody></table>`;
  }
  function casesHtml(cell, own) {
    return `${plural(cell.sections, "section")}, ${num(cell.n)} hypothetical joiners, ${num(cell.events)} cleared${own ? ` (this course alone: ${num(own.n_course)} joiners in ${plural(own.sections_course, "section")})` : ""}`;
  }
  function medianText(cell) {
    if (cell.median_days == null) return "more than half never cleared in the data";
    return cell.median_days < 1 ? Math.round(cell.median_days * 24) + " hours" : cell.median_days.toFixed(1) + " days";
  }
  function copyText(text) {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) return navigator.clipboard.writeText(text);
    } catch (e) { /* fall through */ }
    return Promise.reject(new Error("clipboard unavailable"));
  }

  // ------------------------------------------------------------------ charts
  // Step-drawn clearing curves. series: [{label, curve, cls: "s1".."s4", you, band}];
  // marks: [{day, label}] (gold); t: today's date for the calendar axis; id for the readout.
  let chartSeq = 0;
  function curveChart(opts) {
    const series = (opts.series || []).filter((s) => s.curve && s.curve.length);
    if (!series.length) return "";
    const id = opts.id || ("chart" + (++chartSeq));
    const W = 640, H = opts.height || 260, L = 44, R = series.length > 1 ? 88 : 52, T = 18, B = opts.t ? 46 : 32;
    const reach = Math.max(...series.map((s) => s.curve[s.curve.length - 1][0]));
    const marks = (opts.marks || []).filter((m) => m.day > 0);
    const maxDay = Math.max(opts.maxDay || 0, reach, ...marks.map((m) => m.day), 7);
    const x = (d) => L + (Math.min(d, maxDay) / maxDay) * (W - L - R);
    const y = (p) => T + (1 - p) * (H - T - B);
    const stepPath = (curve, col) => {
      let d = `M ${x(0).toFixed(1)} ${y(0).toFixed(1)}`;
      let prev = 0;
      for (const c of curve) { d += ` H ${x(c[0]).toFixed(1)} V ${y(c[col]).toFixed(1)}`; prev = c[col]; }
      if (curve[curve.length - 1][0] < maxDay) d += ` H ${x(maxDay).toFixed(1)}`;
      return d;
    };
    let svg = `<defs><pattern id="hatch-${id}" patternUnits="userSpaceOnUse" width="8" height="8" patternTransform="rotate(45)"><line class="hatch-line" x1="0" y1="0" x2="0" y2="8"/></pattern></defs>`;
    // gridlines: solid hairlines, 0 to 100%
    for (const p of [0, .25, .5, .75, 1]) svg += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(p).toFixed(1)}" y2="${y(p).toFixed(1)}"/><text class="lbl" x="${L - 6}" y="${(y(p) + 4).toFixed(1)}" text-anchor="end">${Math.round(p * 100)}%</text>`;
    svg += `<line class="axis" x1="${L}" x2="${W - R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}"/>`;
    // beyond the data's reach
    if (reach < maxDay) svg += `<rect class="beyond" x="${x(reach).toFixed(1)}" y="${T}" width="${(x(maxDay) - x(reach)).toFixed(1)}" height="${(H - T - B)}" fill="url(#hatch-${id})"><title>Beyond ${days(reach)}, the longest the data follow anyone; the last value stands as a floor</title></rect>`;
    // x ticks: days, and the calendar date under each when "today" is known
    const step = maxDay > 120 ? 28 : maxDay > 60 ? 14 : maxDay > 21 ? 7 : maxDay > 10 ? 2 : 1;
    for (let dd = 0; dd <= maxDay + 1e-9; dd += step) {
      svg += `<text class="lbl" x="${x(dd).toFixed(1)}" y="${H - B + 14}" text-anchor="middle">${dd}d</text>`;
      if (opts.t) svg += `<text class="lbl date" x="${x(dd).toFixed(1)}" y="${H - B + 27}" text-anchor="middle">${esc(fmtShort(addDays(opts.t, dd)))}</text>`;
    }
    svg += `<text class="lbl" x="${W - R}" y="${H - 4}" text-anchor="end">days since joining the waitlist</text>`;
    // bands first, then curves, then marks and labels
    for (const s of series) {
      if (s.band === false || !s.curve.every((c) => c[2] != null && c[3] != null)) continue;
      const upper = stepPath(s.curve, 3);
      let lower = "";
      const rev = s.curve.slice().reverse();
      for (let i = 0; i < rev.length; i++) {
        const c = rev[i];
        const next = rev[i + 1];
        lower += ` V ${y(c[2]).toFixed(1)} H ${x(next ? next[0] : 0).toFixed(1)}`;
      }
      svg += `<path class="band" d="${upper}${lower} Z"/>`;
    }
    const ends = [];
    series.forEach((s, i) => {
      svg += `<path class="curve ${esc(s.cls || "s" + ((i % 4) + 1))}${s.you ? " you" : ""}" d="${stepPath(s.curve, 1)}"><title>${esc(s.label)}</title></path>`;
      const last = s.curve[s.curve.length - 1];
      ends.push({ s, i, x: x(last[0]), y: y(last[1]), p: last[1] });
    });
    // end markers with a surface ring, and direct labels nudged apart
    ends.sort((a, b) => a.y - b.y);
    let lastY = -Infinity;
    for (const e of ends) {
      e.ly = Math.max(e.y, lastY + 13);
      lastY = e.ly;
    }
    for (const e of ends) {
      svg += `<circle class="${esc(e.s.cls || "s" + ((e.i % 4) + 1))} fill end" r="4.5" cx="${e.x.toFixed(1)}" cy="${e.y.toFixed(1)}"><title>${esc(e.s.label)}: ${pct(e.p)}</title></circle>`;
      if (series.length > 1) svg += `<text class="lbl${e.s.you ? " ink" : ""}" x="${(W - R + 8)}" y="${(e.ly + 4).toFixed(1)}">${esc(e.s.short || e.s.label)} ${pct(e.p)}</text>`;
      else if (opts.labelEnd) svg += `<text class="lbl ink" x="${(W - R + 8)}" y="${(e.ly + 4).toFixed(1)}">${pct(e.p)}</text>`;
    }
    // date markers in gold; labels staggered so two close dates stay legible
    marks.forEach((m, i) => {
      const mx = x(m.day).toFixed(1);
      const near = marks.some((o, j) => j !== i && Math.abs(x(o.day) - x(m.day)) < 90);
      svg += `<line class="mark" x1="${mx}" x2="${mx}" y1="${T}" y2="${y(0).toFixed(1)}"/><text class="lbl ink" x="${mx}" y="${near ? T + 10 + 13 * (i % 2) : T - 6}" text-anchor="${m.day / maxDay > 0.8 ? "end" : "middle"}" dx="${m.day / maxDay > 0.8 ? -4 : 0}">${esc(m.label)}</text>`;
      for (const s of series) { const v = readCurve(s.curve, m.day); svg += `<circle class="markdot" r="4.5" cx="${mx}" cy="${y(v.p).toFixed(1)}"><title>${esc(s.label)} at ${esc(m.label)}: ${pct(v.p)}</title></circle>`; }
    });
    svg += `<line id="${id}-cross" class="cross" x1="0" x2="0" y1="${T}" y2="${y(0).toFixed(1)}" style="display:none"/>`;
    svg += `<rect class="hit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}"/>`;
    const label = opts.ariaLabel || `Share who got in, by days since joining the waitlist${series.length > 1 ? ", one curve per position bucket" : ""}, with a 95% band`;
    const out = `<figure class="chart" id="${id}"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}" tabindex="0" data-maxday="${maxDay}" data-left="${L}" data-width="${W - L - R}">${svg}</svg>
      <div class="readout" id="${id}-readout" aria-live="polite">${esc(opts.hint || "Hover, tap or use the arrow keys to read the curve at a day.")}</div>
      ${series.length > 1 ? `<ul class="legend">${series.map((s, i) => `<li class="k${(i % 4) + 1}">${esc(s.label)}${s.you ? " (you)" : ""}</li>`).join("")}${marks.length ? `<li class="kgold">${marks.map((m) => esc(m.label)).join(", ")}</li>` : ""}</ul>` : ""}
      ${tableHtml(series, opts.t)}</figure>`;
    pendingCharts.push({ id, series, maxDay, L, W: W - L - R, t: opts.t });
    return out;
  }
  function tableHtml(series, t) {
    const daysSet = new Set();
    for (const s of series) for (const c of s.curve) daysSet.add(c[0]);
    const grid = Array.from(daysSet).sort((a, b) => a - b);
    const head = series.map((s) => `<th class="num">${esc(s.label)}</th>`).join("");
    const rows = grid.map((d) => `<tr><td class="num">${d}${t ? ` <span class="muted">(${esc(fmtShort(addDays(t, d)))})</span>` : ""}</td>${series.map((s) => { const v = readCurve(s.curve, d); return `<td class="num">${pct(v.p)}${v.lo == null ? "" : ` <span class="muted">(${pct(v.lo)} to ${pct(v.hi)})</span>`}</td>`; }).join("")}</tr>`).join("");
    return `<details class="table"><summary>Show as table</summary><div class="scroll" tabindex="0"><table><thead><tr><th class="num">Days since joining</th>${head}</tr></thead><tbody>${rows}</tbody></table></div></details>`;
  }
  // Wire the hover, tap and keyboard readout of every chart rendered since the last call.
  const pendingCharts = [];
  function activateCharts() {
    while (pendingCharts.length) {
      const ch = pendingCharts.pop();
      const fig = $(ch.id);
      if (!fig || typeof fig.querySelector !== "function") continue;
      const svg = fig.querySelector("svg"), cross = $(ch.id + "-cross"), readout = $(ch.id + "-readout");
      let day = null;
      const show = (d) => {
        day = Math.max(0, Math.min(ch.maxDay, d));
        const px = ch.L + (day / ch.maxDay) * ch.W;
        cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.style.display = "";
        readout.innerHTML = `<b>${days(day)}</b>${ch.t ? ` (${esc(fmtShort(addDays(ch.t, day)))})` : ""}: ` + ch.series.map((s) => { const v = readCurve(s.curve, day); return `${esc(s.label)} <b>${pct(v.p)}</b>${v.lo == null ? "" : ` <span class="muted">(${pct(v.lo)} to ${pct(v.hi)})</span>`}`; }).join(" · ");
      };
      const fromEvent = (ev) => {
        const rect = svg.getBoundingClientRect();
        const vx = (ev.clientX - rect.left) / rect.width * (ch.L + ch.W + 72);
        show(((vx - ch.L) / ch.W) * ch.maxDay);
      };
      svg.addEventListener("pointermove", fromEvent);
      svg.addEventListener("pointerdown", fromEvent);
      svg.addEventListener("keydown", (ev) => {
        const stepK = ev.shiftKey ? 7 : 1;
        if (ev.key === "ArrowRight") { ev.preventDefault(); show((day == null ? 0 : day) + stepK); }
        else if (ev.key === "ArrowLeft") { ev.preventDefault(); show((day == null ? 0 : day) - stepK); }
        else if (ev.key === "Home") { ev.preventDefault(); show(0); }
        else if (ev.key === "End") { ev.preventDefault(); show(ch.maxDay); }
      });
    }
  }

  // ------------------------------------------------------------- combobox
  // ARIA combobox on an <input> with a <ul role="listbox">; onPick(row) when a course is chosen.
  function combobox(input, list, index, onPick) {
    let rows = [], active = -1, open = false;
    const render = () => {
      if (!rows.length) { list.innerHTML = ""; list.hidden = true; open = false; input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant"); return; }
      list.innerHTML = rows.map((r, i) => `<li role="option" id="${list.id}-${i}" aria-selected="${i === active}" data-key="${esc(r.key)}"><span>${esc(r.key)}</span><span class="sub">${esc(r.level ? r.level + " division" : "")}${r.joins ? ` · ${num(r.joins)} joins` : ""}</span></li>`).join("");
      list.hidden = false; open = true;
      input.setAttribute("aria-expanded", "true");
      if (active >= 0) input.setAttribute("aria-activedescendant", `${list.id}-${active}`); else input.removeAttribute("aria-activedescendant");
    };
    const close = () => { rows = []; active = -1; render(); };
    const pick = (r) => { input.value = r.key; close(); if (onPick) onPick(r); };
    input.addEventListener("input", () => { rows = searchCourses(index, input.value, 8); active = -1; render(); });
    input.addEventListener("focus", () => { if (input.value && !open) { rows = searchCourses(index, input.value, 8); render(); } });
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown") { ev.preventDefault(); if (!open) { rows = searchCourses(index, input.value, 8); } active = Math.min(rows.length - 1, active + 1); render(); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); active = Math.max(-1, active - 1); render(); }
      else if (ev.key === "Escape") { close(); }
      else if (ev.key === "Enter" && open && active >= 0) { ev.preventDefault(); pick(rows[active]); }
      else if (ev.key === "Tab") { close(); }
    });
    input.addEventListener("blur", () => { setTimeout(close, 150); });
    list.addEventListener("pointerdown", (ev) => { ev.preventDefault(); });
    list.addEventListener("click", (ev) => {
      let el = ev.target;
      while (el && el !== list && !(el.getAttribute && el.getAttribute("data-key"))) el = el.parentNode;
      if (el && el !== list) { const key = el.getAttribute("data-key"); const r = indexMap(index)[key]; if (r) pick(r); }
    });
    return { close, suggest: (text) => { rows = searchCourses(index, text, 8); active = -1; render(); return rows; } };
  }

  return {
    SITE, REPO, BUCKETS, BUCKET_ORDER, VERDICT, VERDICT_NOTE, SUBJECT_ALIASES, DAY,
    $, esc, pct, num, fmtDate, fmtDay, fmtShort, days, plural, bucketOf, bucketText, addDays, params, today, pinned, withToday,
    fetchJson, load, loaded, loadSubject, dataReady, emptyHtml, failedHtml, skeletonHtml, sourceHtml, sourceLabel, stamp, setStamp,
    horizons, keyDates, keyDatesHtml, readCurve, interval, resolveCell, fallbackCell, estimateLevel, pooledTag, pooledSentence, levelNote, levelOf,
    parseQuery, findCourse, searchCourses, topCourses, relatedCourses, indexMap,
    verdict, frequency, dots, headlineHtml, byWhenHtml, casesHtml, medianText, copyText,
    curveChart, activateCharts, combobox,
  };
})();
if (typeof window !== "undefined") window.BWO = BWO;

// ------------------------------------------------------ department pages (C5)
// dept.html?subject=CODE. Kept in one block at the end so parallel branches merge.
// A subject's display name: the generated map when it is on the branch (BWO.SUBJECT_NAMES), else the code.
BWO.subjectName = function (code) { return (BWO.SUBJECT_NAMES && BWO.SUBJECT_NAMES[code]) || code; };
// The subject a ?subject= value names, as the index spells it ("cs", "Comp Sci" and "compsci" are COMPSCI), or null.
BWO.resolveSubject = function (index, text) {
  const t = String(text || "").toUpperCase().replace(/[^A-Z0-9&\s]/g, " ").replace(/\s+/g, " ").trim();
  if (!t) return null;
  const subjects = new Set(index.courses.map((r) => r.subject));
  const squashed = t.replace(/[\s&]+/g, "");
  for (const s of [t, BWO.SUBJECT_ALIASES[t], squashed, BWO.SUBJECT_ALIASES[squashed]]) if (s && subjects.has(s)) return s;
  return null;
};
// Up to n subjects near an unknown one: prefix and alias matches from the course search, then by edit distance.
BWO.nearestSubjects = function (index, text, n) {
  const want = String(text || "").toUpperCase().replace(/[^A-Z0-9&]/g, "");
  const out = [];
  for (const r of BWO.searchCourses(index, text, 50)) if (!out.includes(r.subject)) out.push(r.subject);
  const dist = (a, b) => {
    let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      for (let j = 1; j <= b.length; j++) cur.push(Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)));
      prev = cur;
    }
    return prev[b.length];
  };
  const rest = Array.from(new Set(index.courses.map((r) => r.subject))).filter((s) => !out.includes(s));
  rest.sort((a, b) => dist(want, a) - dist(want, b) || a.localeCompare(b));
  return out.concat(rest).slice(0, n || 3);
};
// Every course of a subject, most-joined first, then by number.
BWO.deptCourses = function (index, subject) {
  return index.courses.filter((r) => r.subject === subject)
    .sort((a, b) => (b.joins || 0) - (a.joins || 0) || a.key.localeCompare(b.key, "en", { numeric: true }));
};
