# A6 design contract — the lookup site

Static site under `site/`, published by `.github/workflows/pages.yml` to GitHub Pages (source: GitHub Actions, no branch juggling) at https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/. No backend, no build step, no external scripts or fonts: one HTML file with inline CSS and JavaScript, plus a methodology page. Data is the JSON `analysis/export.py` writes to `site/data/` (docs/DESIGN_A5.md section 4), committed to `main` by `.github/workflows/analysis.yml` every Sunday at 15:23 UTC (or by dispatch), which also copies the report and figures to `reports/`. Until the Spring 2027 collection has clearings, the JSON comes from the Fall 2026 backfill (`make backfill-analysis`, docs/DESIGN_A5.md section 9) and `meta.data_source` is `berkeleytime_history`.

## Page behaviour (`site/index.html`)

1. Load `data/meta.json`. If it is missing, `events` is below 10, or it lacks `deadline` and `instruction_start`, show the empty state ("No estimates yet", the Oct 26 start date, and the counts collected so far) and hide the form. Nothing simulated is ever shown.
2. Otherwise load `data/courses.json`, fill the course datalist, and show the term, the number of courses, sections, hypothetical joiners and clearings, and the data-through date. When `meta.data_source` is `berkeleytime_history` the status card says so: "Fall 2026, from Berkeleytime's public 15-minute enrollment history … Live Spring 2027 collection by this project starts Oct 26, 2026".
3. "Today" is the browser's date, or `?today=YYYY-MM-DD` when given (the tests pin it; a reader can ask what the page would have said on a date). From `meta.deadline` (the last automatic waitlist run) and `meta.instruction_start` the page computes the asker's own horizons: days until the end of the deadline day and days until 00:00 UTC on the first day of instruction. The footer stamp shows the deadline and how far away it is.
4. On submit: normalise the course key (upper case, single spaces), map the position to its bucket (1-5, 6-15, 16-40, 41+), and read the cell's `curve` (a step function on a grid of days since joining, out to the cell's `reach_days`) at each horizon: the last grid point at or before the horizon. Render, in this order:
   - headline: the share who had cleared within the days left before the last automatic waitlist run, with the 95% section-bootstrap interval when the cell has one (two or more sections);
   - second line: the share cleared by the first day of instruction when it is still ahead, otherwise "Instruction has begun; most clearing happens after the first day of class";
   - when the horizon lies beyond `reach_days`, the value at the reach is shown with "The data follow joiners for N days; treat this as a floor";
   - after the deadline the page is a look back: the value at the reach with a sentence that waitlists are no longer processed automatically;
   - the median time to clear; the cases line as "S sections, N hypothetical joiners, E cleared" (plus the course's own joiners and sections when pooled); a `pooled` tag when the estimate comes from the department or all courses; an inline SVG of the curve with its band and the two horizons marked.
   Missing course or bucket gives a specific message naming the buckets that do have data. The page never prints `p_clear_by_instruction`; that field is the report's number at the cell's median lead time and is kept only for the analysis output.
5. `?course=COMPSCI%2061A&position=12` in the URL runs a lookup on load so results can be shared; `&today=` can be added.
6. The footer states the assumptions in one sentence and links the methodology and the repository.

Accessibility: semantic form labels, `aria-live` on the status and result regions, visible focus rings, a `role="img"` label on the chart with per-point titles, colour contrast that works in the light and dark schemes. Works on a phone: single column below 30 rem.

## Methodology page (`site/methodology.html`)

Data source and cadence (own snapshots, and the Berkeleytime history the Fall 2026 numbers come from), counts to flows, flows to odds, what the numbers cannot tell you (including what the backfill could not validate), the backtest, how to reproduce. Links docs/ASSUMPTIONS.md and CLAIMS.md rather than repeating them.

## Checks

- CLAIMS.md row 4: `curl -sS -o /dev/null -w '%{http_code}\n' https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/` prints 200; the same for `data/meta.json` once the analysis workflow has committed it.
- The page must render the empty state correctly with no `site/data/*.json` present and the full state on the JSON produced from `tests/test_survival.py`'s synthetic cohort. `tests/test_site.py` checks both, plus the lookup at pinned horizons (`?today=2027-01-10`: 27 days to the deadline, 9 to instruction), the floor note, the look-back state after the deadline, the backfill source label, the pooling tag, the missing-course and missing-bucket messages and the `?course=&position=` link, by running the page's own inline script under node with a stub document and a file-backed `fetch` (`tests/site/harness.js`); the tests are skipped when node is not installed. A pass in a real browser is still due before the soft launch.
