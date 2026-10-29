// Runs tests/fixtures/course_queries.csv through the site's own matcher.
//
//   node tests/site/queries.mjs
//
// The queries are evaluated inside a rendered index.html (tests/site/harness.js,
// against the committed site/data), so this and tests/test_site.py exercise the
// same matcher over the same fixture and cannot drift. Prints one JSON object on
// stdout: every row with the key and layer the matcher returned and the keys it
// offered as nearest; a one-line summary goes to stderr. Exits 1 on a failure.
//
// The title layer reads tests/fixtures/titles_sample.json, served as data/titles.json
// (HARNESS_TITLES_FILE), since the committed site/data has no titles file yet; every
// query goes through BWO.matchCourseAsync, the path the pages use, and the whole
// fixture may request titles.json at most once.
//
// An expected_key of "*" means "any course, the layer is what this row is for":
// it is for the rows whose key is decided by the joins ranking in the committed
// export, which a refresh can reorder without anything being wrong.
"use strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const FIXTURE = path.join(ROOT, "tests", "fixtures", "course_queries.csv");
const HARNESS = path.join(HERE, "harness.js");
const PAGE = path.join(ROOT, "site", "index.html");
const SITE = path.join(ROOT, "site");
const TITLES = path.join(ROOT, "tests", "fixtures", "titles_sample.json");

// The fixture is plain CSV: three fields, no quoting, no commas inside a field.
export function readFixture(text) {
  const lines = text.split("\n").filter((l) => l.length);
  const header = lines.shift();
  if (header !== "query,expected_key,expected_layer") throw new Error(`unexpected header: ${header}`);
  return lines.map((line, i) => {
    const parts = line.split(",");
    if (parts.length !== 3) throw new Error(`row ${i + 2} has ${parts.length} fields: ${line}`);
    return { query: parts[0], expected_key: parts[1], expected_layer: parts[2] };
  });
}

// One harness run for the whole fixture: the page loads the real index.json once.
export function runQueries(queries) {
  const expression = `(async function () { var qs = ${JSON.stringify(queries)}, out = [];
    for (var i = 0; i < qs.length; i++) {
      var m = await BWO.matchCourseAsync(BWO.loaded.index, qs[i]);
      out.push({ key: m.key, layer: m.layer, nearest: (m.nearest || []).map(function (r) { return r.key; }) });
    }
    return out; })()`;
  const out = execFileSync(process.execPath, [HARNESS, PAGE, SITE, "", "", "", expression], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024, env: { ...process.env, HARNESS_TITLES_FILE: TITLES } });
  const parsed = JSON.parse(out);
  if (parsed.eval_error) throw new Error(`harness could not evaluate the fixture: ${parsed.eval_error}`);
  return { results: parsed.eval, titleFetches: parsed.fetches.filter((u) => u === "data/titles.json").length };
}

export function check(rows, results) {
  const failures = [];
  rows.forEach((row, i) => {
    const got = results[i];
    const want = row.expected_layer === "miss" ? null : row.expected_key;
    if (want === "*" ? !got.key : got.key !== want) failures.push(`${JSON.stringify(row.query)}: expected key ${JSON.stringify(want)}, got ${JSON.stringify(got.key)}`);
    else if (got.layer !== row.expected_layer) failures.push(`${JSON.stringify(row.query)}: expected layer ${row.expected_layer}, got ${got.layer}`);
    if (row.expected_layer === "miss" && got.nearest.length > 3) failures.push(`${JSON.stringify(row.query)}: ${got.nearest.length} nearest offered, at most 3 allowed`);
  });
  return failures;
}

// Review of 2026-10-29, 1.3 (Task 20b): the result card's calibration line. The gap is the export's
// (analysis/export_backtest.py writes runs[*].calibration_gap); the page picks the run and the predictor.
// The served site/data/backtest.json predates the field, so the served cards print no line; the same file
// with the field added, as the export now writes it, prints it.
function harness(search, expression, page = PAGE) {
  const out = execFileSync(process.execPath, [HARNESS, page, SITE, search, "", "", expression], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  return JSON.parse(out);
}
export function calibrationChecks() {
  const failures = [];
  const backtest = JSON.parse(fs.readFileSync(path.join(SITE, "data", "backtest.json"), "utf8"));
  const served = { has_field: backtest.runs.some((r) => "calibration_gap" in r), runs: backtest.runs.length };
  const got = harness("", `(async function () { var m = BWO.loaded.meta, bt = await BWO.loadBacktest(m);
    var withGap = Object.assign({}, bt, { runs: bt.runs.map(function (r) { return r.name === "cross_term_days14" ? Object.assign({}, r, { calibration_gap: { course: 16.0, dept: 15.4 } }) : r; }) });
    return { served14: BWO.calibrationGap(bt, m, 14), servedLine: BWO.calibrationHtml(bt, m, 14), g14: BWO.calibrationGap(withGap, m, 14), g7: BWO.calibrationGap(withGap, m, 7),
      g20: BWO.calibrationGap(withGap, m, 20), g29: BWO.calibrationGap(withGap, m, 29), line14: BWO.calibrationHtml(withGap, m, 14), none: BWO.calibrationHtml(null, m, 14) }; })()`).eval;
  if (!served.has_field && (got.served14 !== null || got.servedLine !== "")) failures.push(`the served backtest has no calibration_gap, yet a line or gap came out: ${JSON.stringify([got.served14, got.servedLine])}`);
  if (!got.g14 || got.g14.points !== 16 || got.g14.run !== "cross_term_days14" || got.g14.term !== backtest.term_name) failures.push(`calibration at 14 days: ${JSON.stringify(got.g14)}`);
  if (!got.g7 || got.g7.run !== "cross_term_days14") failures.push(`a 7-day headline reads the 14-day run, got ${JSON.stringify(got.g7)}`);
  if (got.g20 !== null) failures.push(`the 28-day run has no field here, so no gap at 20 days, got ${JSON.stringify(got.g20)}`);
  if (got.g29 !== null) failures.push(`past 28 days there is no calibration line, got ${JSON.stringify(got.g29)}`);
  const line = `In <a href="accuracy.html">testing</a> on ${backtest.term_name}, estimates like this ran about 16 points high at 14 days.`;
  if (!(got.line14 || "").includes(line)) failures.push(`calibration line: expected ${JSON.stringify(line)}, got ${JSON.stringify(got.line14)}`);
  if (got.none !== "") failures.push(`no calibration line without the file, got ${JSON.stringify(got.none)}`);
  // On the served cards, at a 14-day headline: the slot is there and stays empty until backtest.json has the field.
  for (const [what, page, search, html] of [["lookup", PAGE, "?course=COMPSCI%2061A&position=10&today=2027-01-23", (o) => o.result], ["course page", path.join(SITE, "course.html"), "?c=COMPSCI%2061A&position=10&today=2027-01-23", (o) => o.elements.course.html]]) {
    const o = harness(search, "", page);
    const slot = (o.elements["calibration-line"] || {}).html || "";
    if (!html(o).includes("within 14 days of joining") || !html(o).includes('<div id="calibration-line"></div>')) failures.push(`the served ${what} card has no 14-day headline or no calibration slot`);
    if (!served.has_field && slot !== "") failures.push(`the served ${what} card printed a calibration line without the field: ${slot}`);
  }
  return { served, failures };
}

const rows = readFixture(fs.readFileSync(FIXTURE, "utf8"));
const { results, titleFetches } = runQueries(rows.map((r) => r.query));
const failures = check(rows, results);
if (titleFetches > 1) failures.push(`titles.json was requested ${titleFetches} times; at most once per page load`);
const calibration = calibrationChecks();
failures.push(...calibration.failures);
process.stdout.write(JSON.stringify({ rows: rows.map((r, i) => ({ ...r, ...results[i] })), calibration: calibration.served, failures }));
process.stderr.write(`${rows.length - (failures.length - calibration.failures.length)} of ${rows.length} fixture queries matched; ${calibration.failures.length ? calibration.failures.length + " calibration checks failed" : "calibration checks passed"}\n`);
for (const f of failures) process.stderr.write(`  ${f}\n`);
process.exit(failures.length ? 1 : 0);
