# A6 design contract — the site (v3)

Static site under `site/`, published by `.github/workflows/pages.yml` to GitHub Pages (source: GitHub Actions, no branch juggling) at https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/. No backend, no build step, no framework, no external scripts or fonts (GoatCounter, when Oliver adds it, is the one planned exception). Several pages share one stylesheet (`site/assets/site.css`) and one script (`site/assets/site.js`, exposing `BWO`); each page carries its own short inline script. Data is the JSON `analysis/export.py` writes to `site/data/` (docs/DESIGN_A5.md section 4), committed to `main` by `.github/workflows/analysis.yml` every Sunday at 15:23 UTC (or by dispatch), which also copies the report and figures to `reports/`. Until the Spring 2027 collection has clearings, the JSON comes from the Fall 2026 backfill (`make backfill-analysis`, `make site-data`; docs/DESIGN_A5.md section 9) and `meta.data_source` is `berkeleytime_history`. The plan behind v3, with priorities and the decisions taken, is docs/dev/SITE_V3_PLAN.md.

## Rules every page keeps

- The pages read precomputed JSON and compute no statistic: a curve is read at a horizon (`BWO.readCurve`, the last grid point at or before the horizon; past the reach the last point stands, as a floor). Nothing simulated is shown outside the labelled figure on the Methods page.
- Berkeleytime-derived numbers carry "from Berkeleytime's public history" on every page that shows them (`BWO.sourceHtml`, `BWO.sourceLabel`).
- Horizons count down to the **forecast term** in `meta.json` (`forecast_term_name`, `deadline`, `instruction_start`, `dates`), so Fall 2026 curves can stand in for Spring 2027; the data term is named in the source sentence.
- "Today" is the browser's date, or `?today=YYYY-MM-DD` (tests pin it; a reader can ask what a page would have said). Internal links keep a pinned date (`BWO.withToday`).
- States every data page distinguishes: loading (skeleton), fetch failed (says so, offers reload; `state: "failed"` from `BWO.load`), no estimates yet (`meta.json` missing, `events` under 10, or no `deadline`/`instruction_start`: "No estimates yet", the Oct 26 start date and the counts so far; forms hidden), ready.
- "Got in" in headlines; "cleared" is defined once on the Methods page and used in the analysis. Buttons say what they do.
- What an estimate is follows `meta.estimate_level` (`BWO.estimateLevel`). At `course` (the default since the cross-term backtest), a course with 30 or more cases has its own curve and the department, then all courses, is a labelled `pooled` fallback; one sentence on the rule (`BWO.levelNote`) links the Accuracy page. At `dept`: a course's estimate is its department's curve for the bucket, the course's own cases appear as counts ("this course alone: N joiners in S sections", the "This course" column on the course page, the Cases column on Courses), nothing at department level is called pooled (the `pooled` tag and the "Too little data to call" rule apply only to all-course or level pools), the Courses filter hides only all-course pools, the Insights most-and-least list is dropped, and every page prints one sentence on the rule (`BWO.levelNote`) linking the Accuracy page.
- Colour: Berkeley Blue `#003262` and California Gold `#FDB515`. Gold has one meaning: you (your bucket, the two calendar dates, the current nav item). Blue is data. Position buckets are an ordinal ramp (`--s1` to `--s4`, validated for light and dark). No red or green verdicts. System font stack; `tabular-nums` on numbers in tables and axes only. Light and dark follow the system setting; `prefers-reduced-motion` is honoured.
- Accessibility: skip link, one `<nav aria-label="Site">` with `aria-current="page"`, ARIA combobox for search, `aria-sort` on sortable headers, `aria-live` on status and result regions, visible focus, `role="img"` with a label on every chart plus a keyboard-reachable readout and a "Show as table" twin, scroll regions focusable, 44 px targets, single column below 30 rem, no horizontal page scroll at 390 px.

## Pages

| Page | File | Data | Job |
| --- | --- | --- | --- |
| Lookup | `index.html` | `meta`, `index`, `pooled`, one `courses/<SUBJECT>.json` on demand, `titles` on demand (title and instructor queries only) | Course and position in, odds and dates out |
| Courses | `courses.html` | `meta`, `index` | Sortable, filterable table of every course |
| Course | `course.html?c=KEY&position=N` | `meta`, `index`, `pooled`, subject file; `live/latest.json` when present | One course, all buckets, related courses |
| Insights | `insights.html` | `meta`, `insights`, `pooled`, `index` | Findings, hero chart, grids, departments, daily flow, exits, extremes |
| Accuracy | `accuracy.html` | `meta`, `backtest` (optional) | Calibration, scores, what could not be tested, pre-registration |
| Methods | `methodology.html` | `meta` | Data, flows, odds, the "cleared" definition, tests, limits (`#cannot`), reproduction |
| About | `about.html` | `meta` | Who, not affiliated, data status, privacy, licence, feedback |
| 404 | `404.html` | none | Links back |

### Lookup (`index.html`)

1. Key-dates strip (`BWO.keyDatesHtml`): the forecast term's next three dates with "in N days"; the first day of class and the last automatic run in gold.
2. Course combobox (`BWO.combobox`): suggestions from `BWO.searchCourses`, most-joined first. `BWO.findCourse` ignores case and spaces, expands subject aliases (`SUBJECT_ALIASES`: CS, EE, MCB, IB, BIO, PE, NST, STATS, DS, PS, BA, ME, CE, IEOR, MSE, NE, BIOE and the two-word spellings), accepts a missing space ("cs61a"), and resolves cross-listed numbers with or without the C ("data 8" and "DATA C8"; a trailing C, H, N or W before the digits belongs to the number). Position is `inputmode="numeric"`. Example chips are the three most-joined courses with their own estimate at positions 6 to 15 (`BWO.topCourses`), never hardcoded.
3. On submit: bucket the position (1-5, 6-15, 16-40, 41+), load the subject file, resolve the cell (`BWO.resolveCell`: the course's own curve, or the pool it points at). Render, in this order: the site name and "as of" date (so screenshots carry attribution); the course line with a `pooled` tag when pooled; the natural-frequency sentence and the 20-dot line; the headline share by the last automatic waitlist run with its 95% interval; the verdict chip (Likely at 75% or more, Could go either way 40 to 74%, Unlikely below 40%, Too little data to call when the interval is wider than 30 points, the cell has one section, or it is pooled over all courses; the thresholds are printed on the page); the floor note past the reach; the share by the first day of instruction, or "Instruction has begun"; the by-when table (7 and 14 days from today with their dates, first day of class, last waitlist run); the other buckets at the same date with the asker's in gold; the step-drawn curve with its band and gold date markers, a readout and a table; median and cases (with the course's own counts when pooled); the pooled sentence and source label; Copy link and Copy as text; the verdict thresholds; what the number cannot see.
4. After the deadline the page is a look back (the value at the reach, "no longer processed automatically"). Fallbacks, never a dead end: an unknown course shows the department's curve for the bucket, then the level's, then all courses', labelled and explained; a course without that bucket names the buckets with data and shows the same fallback.
5. `?course=COMPSCI%2061A&position=12` runs a lookup on load; the URL is rewritten to the current lookup so results share. The findings teaser under the form links Insights. The footer stamp shows data-through, generation time, the pinned date, and the deadline countdown.

### Courses (`courses.html`)

Controls in one row: position bucket (default 6-15), horizon (7, 14, 28 days; default 14), department, level, text filter (forgiving), "Hide pooled estimates" (on by default). Table: course (with level and a `pooled` tag), share who got in with its interval and a "floor" flag when the reach is shorter than the horizon, median days, cases, sections. Any header sorts (`aria-sort`). State lives in the URL (`?bucket=&h=&dept=&level=&q=&pooled=1&sort=&dir=`). On phones the rows become two lines. A row opens the course page.

### Course (`course.html`)

Header, level tag, a position input that re-renders. The headline block is the same code as the lookup (`BWO.headlineHtml`). One chart with every bucket's curve, direct labels, legend, the asker's bucket thicker with its band, gold date markers. A table per bucket: share at 7, 14 and 28 days, median, cases, got in, sections, pooled flag. Five related courses of the same subject at the same bucket. "Sections now": the live counts from `live/latest.json` on the data branch (own snapshots only; the block stays hidden when the file is absent or has no rows for the course).

### Insights (`insights.html`)

"In short": sentences composed from `insights.all_by_bucket` and `by_level` (share within 14 days by bucket, medians by bucket, lower against upper division, the counts behind them). Hero chart: lower-division courses, Phase 1 joiners, one curve per bucket (the README hero plot's data). Grid: bucket by 7, 14, 28 days and the longest follow-up, with intervals. All-course curves. Departments: dot with interval for the share within 28 days at positions 6 to 15, departments with 30 or more cases in two or more sections, with a table. When flows were exported: admits per day against the data term's calendar with Berkeleytime's dark days hatched, and how waitlisters left the queue (admitted, dropped, still waiting). Extremes: mid-list courses that moved most and least, own estimate from three or more sections, intervals shown, noise noted.

### Accuracy (`accuracy.html`)

Reads `data/backtest.json` (`analysis/export_backtest.py` from `reports/backtest_<term>/`). Without it: says the backtest is not published yet. With it, per run (split and horizon): the counts, "when the estimate said about 70%, X% got in" from the deciles of the predictor the pages use (the department curve at the department level, else the course curve, else the fixed-lead-time number), a calibration plot for it (predicted against observed by decile, with a table), the score table for every predictor in a fixed order (bucket, department, course, site v1, Cox; Brier, AUC, gain over the bucket baseline with its interval, joiners scored), and which joiners could be scored by phase. Static text lists what Fall 2026 could not test. The pre-registration box prints `meta.prereg_commit` and `meta.prereg_date` when set and states what will be scored after Feb 10, 2027.

## Charts (`BWO.curveChart`)

Step-drawn curves (the maths is a step function, so is the drawing), 2 px lines, band at 12% for the series that asks for one, hairline solid grid, y from 0 to 100%, x in days since joining with the calendar date under each tick when today is known, a hatched region beyond the data's reach, end markers with a surface ring, direct end labels nudged apart, gold vertical markers for the two calendar dates with staggered labels, a crosshair readout on hover, tap and arrow keys (the SVG is focusable), a legend for two or more series, and a "Show as table" details block. No animation.

## Title and instructor search: `titles.json`

`site/data/titles.json` (docs/DESIGN_A5.md section 4; `make site-data` with a data-branch checkout, or `python -m analysis.export --titles-only`) maps each course in `index.json` to its catalog `title` and `instructors`, so "data structures" or "hilfinger" can find a course (MASTER_PLAN Q4). From the Fall 2026 catalog of 2026-09-24 it held 1728 of the index's 2050 courses in 199535 bytes (49407 gzipped), so it is lazy-loaded: the matcher fetches it only when `meta.titles_file` names it and a query has no digit and no known subject token (a subject, or an alias from `SUBJECT_ALIASES`). A plain code query ("cs61a", "COMPSCI 61A", "data 8") never fetches it. Without `meta.titles_file`, or when the fetch fails, search quietly falls back to codes alone. Titles are labels from the catalog term (`catalog_term_id`); they carry no estimate and the pages compute nothing from them.

## Data branch: `live/latest.json`

Written by `scrape.yml` after every snapshot (`python -m scraper.live`, `continue-on-error: true`, same commit as the Parquet file): `generated_at`, `term_id`, `term_name`, `only_active`, `n_sections`, `columns`, and one compact row per section that is full or has a waitlist (section id, course key, subject, catalog number, component, section number, enrolled, capacity, waitlist, waitlist capacity, status, observed at). The site reads it from `raw.githubusercontent.com` (CORS allowed, five-minute cache); own snapshots only.

## Assets

`favicon.svg` (the dots), `og.png` (1200 by 630, `python scripts/og_image.py`), Open Graph and Twitter tags on every page, `theme-color`, `404.html`.

## Checks

- CLAIMS.md rows: every page returns 200 (`curl -sS -o /dev/null -w '%{http_code}\n' <url>` for each file), `data/meta.json` once the analysis workflow has committed it, the number of searchable courses printed by the exporter.
- `tests/test_site.py` renders every page's own script after `assets/site.js` under node with a stub document and a file-backed `fetch` (`tests/site/harness.js`; skipped without node). It checks the empty state, the counts from `meta.json`, the fetch-failure state, the full state (source sentence, key dates, chips, teaser, stamp), the Berkeleytime label, a lookup at pinned horizons (`?today=2027-01-10`: 27 days to the deadline, 9 to instruction) with the dots, verdict, by-when table, bucket row, step chart, band and marks, the look-back after the deadline, the pooled tag and sentence, the department, level and all-course fallbacks, the missing-bucket message, the `?course=&position=` link, forgiving search and cross-listed numbers, the verdict thresholds, the Courses filters, sort and URL state, the course page (every bucket, the same headline, the hidden live block), the Insights sections, Accuracy with and without `backtest.json`, and the About and Methods data status.
- `tests/site/smoke.mjs` (CI: `.github/workflows/site-smoke.yml`, Playwright) opens every page at 390 by 844 and 1280 by 800, light and dark, against the synthetic data `tests/site/export_fixture.py` writes, screenshots each (uploaded as an artifact, so a session without a browser can look), fails on a console error, a failed request to the site, horizontal page scroll, or a serious or critical axe-core violation. `tests/test_export.py`, `tests/test_export_backtest.py` and `tests/test_live.py` cover the files the pages read.
- A pass in a real browser by Oliver (phone and laptop, light and dark) is still due before the soft launch.
