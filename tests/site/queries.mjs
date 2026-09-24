// Runs tests/fixtures/course_queries.csv through the site's own matcher.
//
//   node tests/site/queries.mjs
//
// The queries are evaluated inside a rendered index.html (tests/site/harness.js,
// against the committed site/data), so this and tests/test_site.py exercise the
// same matcher over the same fixture and cannot drift. Prints one JSON object on
// stdout: every row with the key and layer the matcher returned and the keys it
// offered as nearest; a one-line summary goes to stderr. Exits 1 on a failure.
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
  const expression = `(function () { var qs = ${JSON.stringify(queries)}; return qs.map(function (q) {
    var m = BWO.matchCourse(BWO.loaded.index, q);
    return { key: m.key, layer: m.layer, nearest: (m.nearest || []).map(function (r) { return r.key; }) };
  }); })()`;
  const out = execFileSync(process.execPath, [HARNESS, PAGE, SITE, "", "", "", expression], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  const parsed = JSON.parse(out);
  if (parsed.eval_error) throw new Error(`harness could not evaluate the fixture: ${parsed.eval_error}`);
  return parsed.eval;
}

export function check(rows, results) {
  const failures = [];
  rows.forEach((row, i) => {
    const got = results[i];
    const want = row.expected_layer === "miss" ? null : row.expected_key;
    if (got.key !== want) failures.push(`${JSON.stringify(row.query)}: expected key ${JSON.stringify(want)}, got ${JSON.stringify(got.key)}`);
    else if (got.layer !== row.expected_layer) failures.push(`${JSON.stringify(row.query)}: expected layer ${row.expected_layer}, got ${got.layer}`);
    if (row.expected_layer === "miss" && got.nearest.length > 3) failures.push(`${JSON.stringify(row.query)}: ${got.nearest.length} nearest offered, at most 3 allowed`);
  });
  return failures;
}

const rows = readFixture(fs.readFileSync(FIXTURE, "utf8"));
const results = runQueries(rows.map((r) => r.query));
const failures = check(rows, results);
process.stdout.write(JSON.stringify({ rows: rows.map((r, i) => ({ ...r, ...results[i] })), failures }));
process.stderr.write(`${rows.length - failures.length} of ${rows.length} fixture queries matched\n`);
for (const f of failures) process.stderr.write(`  ${f}\n`);
process.exit(failures.length ? 1 : 0);
