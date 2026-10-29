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

// Review of 2026-10-29, 1.3 (Task 20b): the result card's calibration line, read from the served
// site/data/backtest.json. The expected gap is worked out here from the file itself: the cross-term run at
// 14 or 28 days, the deciles of the predictor the pages use, predicted minus observed, averaged.
function harness(search, expression, page = PAGE) {
  const out = execFileSync(process.execPath, [HARNESS, page, SITE, search, "", "", expression], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  return JSON.parse(out);
}
export function calibrationChecks() {
  const failures = [];
  const backtest = JSON.parse(fs.readFileSync(path.join(SITE, "data", "backtest.json"), "utf8"));
  const meta = JSON.parse(fs.readFileSync(path.join(SITE, "data", "meta.json"), "utf8"));
  const predictor = meta.estimate_level === "dept" ? "dept" : "course";
  const expect = (h) => {
    const pts = backtest.runs.find((r) => r.name === `cross_term_days${h}`).calibration[predictor];
    return pts.reduce((s, q) => s + q.predicted - q.observed, 0) / pts.length;
  };
  const got = harness("", `(async function () { var m = BWO.loaded.meta, bt = await BWO.loadBacktest(m);
    var without = { runs: bt.runs.filter(function (r) { return r.name !== "cross_term_days14"; }) };
    return { g14: BWO.calibrationGap(bt, m, 14), g7: BWO.calibrationGap(bt, m, 7), g28: BWO.calibrationGap(bt, m, 28), g29: BWO.calibrationGap(bt, m, 29),
      line14: BWO.calibrationHtml(bt, m, 14), missing: BWO.calibrationHtml(without, m, 14), none: BWO.calibrationHtml(null, m, 14) }; })()`).eval;
  const served = { gap14: expect(14), gap28: expect(28) };
  for (const [h, key] of [[14, "g14"], [28, "g28"]]) {
    const g = got[key];
    if (!g || g.run !== `cross_term_days${h}` || g.horizon !== h || Math.abs(g.gap - expect(h)) > 1e-9) failures.push(`calibration at ${h} days: expected a gap of ${expect(h)} from cross_term_days${h}, got ${JSON.stringify(g)}`);
  }
  if (!got.g7 || got.g7.run !== "cross_term_days14") failures.push(`a 7-day headline reads the 14-day run, got ${JSON.stringify(got.g7)}`);
  if (got.g29 !== null) failures.push(`past 28 days there is no calibration line, got ${JSON.stringify(got.g29)}`);
  const points = Math.round(Math.abs(expect(14)) * 100), word = expect(14) > 0 ? "high" : "low";
  const line = `In <a href="accuracy.html">testing</a> on Fall 2026, estimates like this ran about ${points} points ${word} at 14 days.`;
  if (Math.abs(expect(14)) >= 0.05 && !(got.line14 || "").includes(line)) failures.push(`calibration line: expected ${JSON.stringify(line)}, got ${JSON.stringify(got.line14)}`);
  if (got.missing !== "" || got.none !== "") failures.push(`no calibration line without the run or the file, got ${JSON.stringify([got.missing, got.none])}`);
  // On the card: a headline read at 14 days (today 14 days before the end of the last run's day) carries the line; one read at months does not.
  const at14 = harness("?course=COMPSCI%2061A&position=10&today=2027-01-23", "").result;
  if (!at14.includes("within 14 days of joining") || !at14.includes(line)) failures.push("the lookup card with a 14-day headline has no calibration line");
  const card = harness("?c=COMPSCI%2061A&position=10&today=2027-01-23", "", path.join(SITE, "course.html")).elements.course.html;
  if (!card.includes("within 14 days of joining") || !card.includes(line)) failures.push("the course page's card with a 14-day headline has no calibration line");
  // A course whose own curve at positions 6 to 15 follows joiners for more than 40 days, looked up 45 days before the end of the run's day: a headline past 40 days.
  const index = JSON.parse(fs.readFileSync(path.join(SITE, "data", "index.json"), "utf8"));
  const long = index.courses.find((r) => r.buckets["6-15"] && r.buckets["6-15"].pooled === false && r.buckets["6-15"].reach[1] > 40);
  const far = harness(`?course=${encodeURIComponent(long.key)}&position=10&today=2026-12-23`, "").result;
  if (!far.includes(`${long.key} · position 10`) || !/got in within 4\d days/.test(far) || far.includes('class="muted small calibration"')) failures.push(`the lookup card for ${long.key} with a headline past 28 days shows a calibration line, or no headline`);
  return { served: { ...served, points14: points }, failures };
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
