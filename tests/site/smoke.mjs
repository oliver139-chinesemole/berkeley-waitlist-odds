// Browser smoke test for site/: opens every page at a phone and a laptop
// viewport, in light and dark schemes, screenshots each, runs axe-core, and
// fails on a console error, a failed request to the site itself, or a serious
// or critical accessibility violation. Playwright and axe-core come from
// npm (see .github/workflows/site-smoke.yml); the site itself has no build.
//
//   node tests/site/smoke.mjs <base url> <output dir> [<today>] [<course key>]
//
// <base url> serves the site with a data/ directory beside it (a static file
// server over a copy of site/ with the JSON the tests export, or the live site).
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const axeSource = require("axe-core").source;

const [base, outDir, today = "2027-01-10", courseKey = "COMPSCI 0"] = process.argv.slice(2);
const course = encodeURIComponent(courseKey);
if (!base || !outDir) {
  console.error("usage: node tests/site/smoke.mjs <base url> <output dir> [today]");
  process.exit(2);
}
mkdirSync(outDir, { recursive: true });

const PAGES = [
  ["index", `index.html?today=${today}`],
  ["lookup", `index.html?today=${today}&course=${course}&position=3`],
  ["courses", `courses.html?today=${today}`],
  ["course", `course.html?today=${today}&c=${course}&position=3`],
  ["insights", `insights.html?today=${today}`],
  ["accuracy", `accuracy.html?today=${today}`],
  ["methodology", "methodology.html"],
  ["about", "about.html"],
  ["404", "404.html"],
];
const VIEWPORTS = [["phone", 390, 844], ["laptop", 1280, 800]];
const SCHEMES = ["light", "dark"];

const browser = await chromium.launch();
const failures = [];
const report = [];
for (const [scheme] of SCHEMES.map((s) => [s])) {
  for (const [vpName, width, height] of VIEWPORTS) {
    const context = await browser.newContext({ viewport: { width, height }, colorScheme: scheme, reducedMotion: "reduce" });
    for (const [name, path] of PAGES) {
      const page = await context.newPage();
      const errors = [];
      page.on("console", (msg) => { if (msg.type() === "error" && !/live\/latest\.json|404/.test(msg.text() + (msg.location() && msg.location().url || ""))) errors.push(`console: ${msg.text()}`); });
      page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
      page.on("requestfailed", (req) => { if (req.url().startsWith(base)) errors.push(`request failed: ${req.url()} ${req.failure() && req.failure().errorText}`); });
      page.on("response", (res) => { if (res.url().startsWith(base) && res.status() >= 400 && !res.url().endsWith("backtest.json") && !res.url().includes("/live/")) errors.push(`HTTP ${res.status()}: ${res.url()}`); });
      const url = base.replace(/\/$/, "") + "/" + path;
      try {
        await page.goto(url, { waitUntil: "networkidle" });
        await page.waitForFunction(() => { const s = document.getElementById("status"); return !s || !/Loading/.test(s.textContent); }, null, { timeout: 15000 });
        await page.waitForTimeout(200);
        const shot = join(outDir, `${name}-${vpName}-${scheme}.png`);
        // long pages on a busy runner: one retry before a timeout counts as a failure
        try { await page.screenshot({ path: shot, fullPage: true, timeout: 60000 }); }
        catch (err) { if (!/Timeout/.test(err.message)) throw err; await page.waitForTimeout(1000); await page.screenshot({ path: shot, fullPage: true, timeout: 90000 }); }
        const wide = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
        if (wide) errors.push("page scrolls horizontally");
        await page.addScriptTag({ content: axeSource });
        const axe = await page.evaluate(async () => await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] } }));
        const serious = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
        for (const v of serious) errors.push(`axe ${v.impact} ${v.id}: ${v.help} (${v.nodes.length} nodes, e.g. ${v.nodes[0].target.join(" ")})`);
        report.push({ page: name, viewport: vpName, scheme, url, screenshot: shot, errors, axe_minor: axe.violations.filter((v) => !serious.includes(v)).map((v) => `${v.impact} ${v.id}`) });
      } catch (err) {
        errors.push(`exception: ${err.message}`);
        report.push({ page: name, viewport: vpName, scheme, url, errors });
      }
      if (errors.length) failures.push(`${name} ${vpName} ${scheme}: ${errors.join("; ")}`);
      await page.close();
    }
    await context.close();
  }
}
await browser.close();
writeFileSync(join(outDir, "report.json"), JSON.stringify(report, null, 1));
console.log(`${report.length} renders, ${failures.length} with problems; screenshots in ${outDir}`);
for (const f of failures) console.log("  " + f);
process.exit(failures.length ? 1 : 0);
