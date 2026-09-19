# A6 design contract — the lookup site

Static site under `site/`, published by `.github/workflows/pages.yml` to GitHub Pages (source: GitHub Actions, no branch juggling) at https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/. No backend, no build step, no external scripts or fonts: one HTML file with inline CSS and JavaScript, plus a methodology page. Data is the JSON `analysis/export.py` writes to `site/data/` (docs/DESIGN_A5.md section 4), committed to `main` by `.github/workflows/analysis.yml` every Sunday at 15:23 UTC (or by dispatch), which also copies the report and figures to `reports/`.

## Page behaviour (`site/index.html`)

1. Load `data/meta.json`. If it is missing, or `events` is below 10, show the empty state ("No estimates yet", the Oct 26 start date, and the counts collected so far) and hide the form. Nothing simulated is ever shown.
2. Otherwise load `data/courses.json`, fill the course datalist, and show the term, the number of courses, sections, hypothetical joiners and clearings, and the data-through date.
3. On submit: normalise the course key (upper case, single spaces), map the position to its bucket (1-5, 6-15, 16-40, 41+), and render: the share who cleared by the first day of instruction as the headline number, the horizon in days, the median time to clear, the sample size (with the course's own count when the estimate is pooled) and the number who cleared, a `pooled` tag when the estimate comes from the department or all courses, and an inline SVG of the cumulative clearing curve with the instruction day marked. Missing course or bucket gives a specific message naming the buckets that do have data.
4. `?course=COMPSCI%2061A&position=12` in the URL runs a lookup on load so results can be shared.
5. The footer states the assumptions in one sentence and links the methodology and the repository.

Accessibility: semantic form labels, `aria-live` on the status and result regions, visible focus rings, a `role="img"` label on the chart with per-point titles, colour contrast that works in the light and dark schemes. Works on a phone: single column below 30 rem.

## Methodology page (`site/methodology.html`)

Data source and cadence, counts to flows, flows to odds, what the numbers cannot tell you, how to reproduce. Links docs/ASSUMPTIONS.md and CLAIMS.md rather than repeating them.

## Checks

- CLAIMS.md row 4: `curl -sS -o /dev/null -w '%{http_code}\n' https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/` prints 200; the same for `data/meta.json` once the analysis workflow has committed it.
- The page must render the empty state correctly with no `site/data/*.json` present (the state before Oct 26) and the full state on the JSON produced by `tests/test_run.py`'s simulated cohort. `tests/test_site.py` checks both, plus the lookup, pooling tag, missing-course and missing-bucket messages and the `?course=&position=` link, by running the page's own inline script under node with a stub document and a file-backed `fetch` (`tests/site/harness.js`); the tests are skipped when node is not installed. A pass in a real browser is still due before the soft launch.
