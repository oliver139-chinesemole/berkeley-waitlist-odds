# Berkeley Waitlist Odds: site v3 brainstorm (tabs, features, UI)

Written 2026-09-19 (PDT). Suggested home: `docs/dev/SITE_V3_PLAN.md`. Based on the live page, `site/index.html`, `site/data/*.json` on `main`, `docs/DESIGN_A6.md`, `analysis/export.py`, `.github/workflows/analysis.yml`, the data branch's `status.json`, and `docs/dev/STATUS.md`. This is a brainstorm with priorities, not an approved spec: section 10 lists the decisions Oliver makes before anything is built.

## 0. Summary of this file

1. Why the live page looks empty today, and the one step that fixes it (section 1).
2. Who the site is for and what "viable" means, as testable criteria (section 2).
3. The constraints from the repo that the new site keeps (section 3).
4. A site map: five tabs plus a course page and an about page, with wireframes (section 4).
5. About 55 features grouped by page, each with a priority, an effort size and the data it needs (section 5).
6. UI and visual direction: colour rules, type, layout, charts, copy, states, phone behaviour (section 6).
7. The new JSON files `analysis/export.py` and `scrape.yml` would have to write (section 7).
8. A build order tied to the project's dates (section 8).
9. What not to build, and why (section 9).
10. Seven decisions for Oliver, each with a recommendation (section 10).
11. Tests and checks, including a way for Claude Code sessions to see the page (section 11).
12. A prompt to paste into a Claude Code session (section 12).

## 1. Why the site looks empty today

The live page is not broken; it is in its empty state. `site/data/meta.json` on `main` was generated 2026-09-19 23:51Z from 13 runs of own data and has `"events": 0` and no `deadline` field. `index.html` hides the form and prints "No estimates yet" whenever `events < 10` or `deadline` is missing. So a visitor sees a blue header, one grey sentence and a footer.

The fix is STATUS section 4 item 1: commit the full-pull `site/data` (labelled `berkeleytime_history`), merge PR #3, run `pages.yml`. `analysis.yml` already keeps a published backfill until own data has 10 clearings (lines 53 to 65), so the weekly job will not put the empty state back. No UI work matters until this is done.

Once data is published, the page works but is still thin:

- One form, one number. Nothing to look at before typing, so a first-time visitor or a recruiter sees a form and leaves.
- The course field is a `<datalist>` that needs the exact classes.berkeley.edu spelling. "cs 61a", "CS61A" and "data 8" all fail. `<datalist>` is also poor on iOS Safari.
- A course with no data is a dead end instead of falling back to its department.
- No way to browse or compare courses, so nothing to share except a single lookup link.
- The backtest, which is the strongest part of the project, is only in the repo.
- The scraper reads about 917 sections every 30 minutes and none of that shows on the site.
- A failed `fetch` shows the same "No estimates yet" message as a real empty state.
- The chart joins grid points with straight lines, but `readCurve` treats the curve as a step function. The drawing should match the maths.
- No favicon, no link-preview image, no nav, no about page.

## 2. Who it is for and what "viable" means

| Visitor | Context | Wants |
| --- | --- | --- |
| Student on a waitlist | Phone, from a Reddit link or group chat, 30 seconds | A number, a date, what the number cannot see |
| Student planning enrollment | Laptop, before Phase 1 or Phase 2 | Which courses are safe to waitlist, by position |
| Recruiter or interviewer | Laptop, from the resume link, 60 seconds | The analysis and proof of rigour without typing a course name |

Viable means all of these hold:

1. The first screen shows something real without typing.
2. Any course is found in two taps with sloppy spelling.
3. Every result and every filtered view has a URL that can be shared, and the link unfurls with a title and image.
4. How accurate the estimates were is one click from anywhere.
5. No page shows a number that a command did not write into an export file.
6. Every page works on a 360 px phone, in light and dark, by keyboard.

## 3. Constraints kept from the repo

- Static files on GitHub Pages. No backend, no accounts, no build step, no framework.
- No external scripts or fonts, with one exception already planned: GoatCounter.
- The site reads precomputed JSON only. It may read a curve at a horizon; it never computes a statistic.
- Simulated numbers appear only in the labelled methodology figure.
- Berkeleytime-derived numbers carry the "from Berkeleytime's public history" label on every page that shows them.
- Only `scrape.yml` writes the `data` branch; only `analysis.yml` commits to `main` on its own.
- `tests/test_site.py` keeps running the page's real script under node.

One contract change: `DESIGN_A6.md` says one HTML file with inline CSS and JavaScript. Five pages cannot share inline code without copy-paste drift, so v3 moves shared code to `site/assets/site.css` and `site/assets/site.js` and updates the contract and the harness.

## 4. Site map

| Tab | File | Job |
| --- | --- | --- |
| Lookup | `index.html` | Course and position in, odds and dates out. The home page. |
| Courses | `courses.html` | Sortable, filterable table of every course with estimates. |
| Insights | `insights.html` | The findings in plain English with charts. What a recruiter reads and what Reddit shares. |
| Accuracy | `accuracy.html` | The backtest: calibration, scores against a baseline, what could not be tested, the pre-registered Spring 2027 test. |
| Methods | `methodology.html` | Exists. Gains the nav and links to Accuracy. |
| (not a tab) | `course.html?c=COMPSCI+61A` | One course: all position buckets, sections, related courses. Reached from Lookup and Courses. |
| (footer) | `about.html` | Who built it, contact, privacy, not affiliated, data status. |

Lookup wireframe (placeholder numbers, not results):

```
Berkeley Waitlist Odds      Lookup  Courses  Insights  Accuracy  Methods
------------------------------------------------------------------------
Spring 2027: Phase 1 opens Oct 26 (in 37 days)     [key dates strip]

Will you get off the waitlist?
[ cs 61a                      ] [ 12 ] [ Look up odds ]
Try: COMPSCI 61A at 12   DATA C8 at 40   CHEM 1A at 5

COMPSCI 61A, position 12 (positions 6 to 15)
About 14 in 20 got in by Feb 5                       Likely
● ● ● ● ● ● ● ● ● ● ● ● ● ● ○ ○ ○ ○ ○ ○    72% (95% interval 61 to 80)

By when                     Share who got in
7 days from now (Nov 3)         18%
14 days from now (Nov 10)       31%
First day of class (Jan 19)     55%
Last waitlist run (Feb 5)       72%

Other positions:   1-5  91%  |  6-15  72%  |  16-40  38%  |  41+  12%
[step chart, band, gold markers for the two dates]
Based on 412 cases in 6 sections. Fall 2026, from Berkeleytime's public history.
[Copy link] [Copy as text] [Save to my waitlists]     What this number cannot see >
```

Course page wireframe:

```
COMPSCI 61A    lower division    [ your position: 12 ]
[chart: four bucket curves, directly labelled, your bucket in gold]
Bucket   7 d   14 d   28 d   Median   Cases   Pooled
Sections now (as of 14 min ago)     LEC 001  1,920/1,950   waitlist 43/400
Other COMPSCI courses at positions 6 to 15      [5 rows, link to Courses]
```

## 5. Features by page

Priority: P0 this weekend, P1 before Oct 26, P2 during Phase 1 (Oct 26 to Nov 22), P3 Jan to Feb 2027. Effort: S under half a day, M about a day, L more.

### Lookup

| ID | Feature | P | Effort | Needs |
| --- | --- | --- | --- | --- |
| L0 | First screen has content before typing: key-dates strip with a countdown, example chips, a one-line findings teaser linking to Insights | P1 | S | `meta.json` dates, `index.json` |
| L1 | Forgiving course search: custom ARIA combobox replacing `<datalist>`; ignores case, spaces and a missing space ("cs61a"); subject aliases (CS, EE, MCB, IB, BIO, PE, NST, STATS, DS, PS, BA); matches a number with or without the cross-list "C" ("data 8" finds DATA C8); cross-listed courses resolve to one entry | P1 | M | `config/subject_aliases.json`, `index.json` |
| L2 | All four position buckets shown in a row under the headline, the asker's highlighted | P1 | S | existing cells |
| L3 | "By when" table: 7 days, 14 days, first day of class, last waitlist run, each with its calendar date from today | P1 | S | existing curves |
| L4 | Natural-frequency sentence and the 20-dot line ("About 14 in 20 got in by Feb 5"), with the percentage and interval beside it | P1 | S | existing curves |
| L5 | Verdict chip (Likely, Could go either way, Unlikely) with thresholds printed on the page; replaced by "Too little data to call" when the interval is wide or the cell is pooled over all courses | P1 | S | decision 2 |
| L6 | Fallback, never a dead end: no course data gives the department estimate, then all courses at that level, labelled as pooled | P1 | S | `pooled.json` |
| L7 | Share: "Copy link", "Copy as text" for group chats; the result card prints the site name and an "as of" date so screenshots carry attribution | P1 | S | none |
| L8 | Example chips chosen from the most-joined courses in the export, not hardcoded | P1 | S | `index.json` join rank |
| L9 | Three separate states: loading skeleton, fetch failed (say so, offer reload), no estimates yet | P0 | S | none |
| L10 | Live section counts under the result: enrolled/capacity and waitlist/capacity per section, "as of N min ago". Own data only | P2 | M | `live/latest.json` |
| L11 | My waitlists: save course and position pairs in `localStorage`; the home page re-reads them at today's horizon on each visit. Remove and clear-all buttons. No account | P2 | M | none |
| L12 | Compare up to three course and position pairs on one chart and one table; state in the URL | P2 | M | existing curves |
| L13 | "What this number cannot see" checklist: reserved seats, time conflicts, unit cap, full discussion sections. Copy the wording from the registrar's waitlist page and link it; do not invent rules | P2 | S | registrar page |
| L14 | Term selector once two terms exist | P3 | S | `terms.json` |
| L15 | "Tell us if you got in" link to a short form: course, position when joined, date joined, outcome, date. No identifiers. The only individual-level ground truth this project can get | P2 | S | decision 6 |

### Courses

| ID | Feature | P | Effort | Needs |
| --- | --- | --- | --- | --- |
| C1 | Table of every course: level, share who got in at the chosen horizon with interval, median days, cases, pooled tag. Sort on any column with `aria-sort` | P1 | M | `index.json` |
| C2 | Controls: position bucket (default 6 to 15), horizon (7, 14, 28 days), department, level, text filter, "hide pooled" on by default | P1 | S | `index.json` |
| C3 | Row opens the course page | P1 | S | none |
| C4 | Filter state in the URL (`?dept=COMPSCI&bucket=6-15&sort=p14`) | P2 | S | none |
| C5 | Tiny curve sparkline per row | P2 | S | compact curve in `index.json` |
| C6 | Download the current view as CSV (Blob, no server) | P2 | S | none |

### Course page

| ID | Feature | P | Effort | Needs |
| --- | --- | --- | --- | --- |
| D1 | Four bucket curves on one chart with direct labels; table of cases, clearings, median, pooled flag per bucket | P1 | M | per-subject file |
| D2 | Position input on the page that highlights the bucket and prints the same sentence as Lookup (shared code) | P1 | S | none |
| D3 | Five related courses from the same department at the same bucket | P1 | S | `index.json` |
| D4 | Sections table with live counts | P2 | M | `live/latest.json` |
| D5 | Split by when the student joined (Phase 1, Phase 2, adjustment period) where each cell has 30 or more cases | P2 | S | export change |
| D6 | Waitlist length over the term from own snapshots, Spring 2027 only. For Fall 2026 link to the course's Berkeleytime page instead of redrawing their series | P3 | M | export change |

### Insights

| ID | Feature | P | Effort | Needs |
| --- | --- | --- | --- | --- |
| I1 | Two or three headline findings at the top, the same sentences as `CLAIMS.md` (STATUS item 2) | P1 | S | `insights.json` |
| I2 | Hero chart: curves by position bucket, all courses. Same data as the README hero plot (STATUS item 3) | P1 | S | `insights.json` |
| I3 | How much position matters: bucket by horizon grid (7, 14, 28 days, longest follow-up) | P1 | M | `insights.json` |
| I4 | Departments: dot with interval for share who got in within 28 days at positions 6 to 15; departments with 30 or more cases and two or more sections only | P1 | M | `pooled.json` |
| I5 | When waitlists move: admits per day against the enrollment calendar, with Berkeleytime's Aug 19 to Sep 1 outage shaded "not recorded" | P2 | M | daily flow series |
| I6 | How people leave a waitlist: admitted, dropped, still waiting at the end | P2 | S | flow totals |
| I7 | Cox effects as a forest plot, one plain sentence per row, with the proportional-hazards caveat | P2 | M | Cox table |
| I8 | Ten hardest and ten easiest courses, un-pooled cells only, with intervals and a note about noise | P2 | S | `index.json` |
| I9 | First-week clearing from own Spring 2027 data: the thing Fall 2026 could not show | P3 | M | own data |
| I10 | Fall 2026 against Spring 2027 | P3 | M | two terms |

### Accuracy

| ID | Feature | P | Effort | Needs |
| --- | --- | --- | --- | --- |
| A1 | Calibration plot: predicted against observed by decile for the number the site shows, at 14 and 28 days | P1 | M | `backtest.json` |
| A2 | Score table: four predictors by split (temporal, held-out courses, Spring 2026 to Fall 2026): IPCW Brier, AUC, gain over the bucket baseline with its bootstrap interval | P1 | S | `backtest.json` |
| A3 | One plain sentence per horizon: "when the site said about 70%, X% got in" | P1 | S | `backtest.json` |
| A4 | What could not be tested: first week of instruction, reserved seats, Cox across the Phase 1 to Phase 2 shift | P1 | S | none |
| A5 | Pre-registration box: commit hash and date of the frozen Fall 2026 model, and what will be scored after Feb 10, 2027 | P1 | S | merge commit of PR #3 |
| A6 | The Spring 2027 result, filled in | P3 | S | Feb refit |
| A7 | Self-reported outcomes against predictions | P3 | S | L15 responses |

### About, status and cross-cutting

| ID | Feature | P | Effort | Needs |
| --- | --- | --- | --- | --- |
| X1 | Publish the backfill JSON (STATUS item 1) | P0 | - | full pull |
| X2 | GoatCounter on every page before any link is shared; count each lookup as an event keyed by course | P0 | S | Oliver's account, decision 4 |
| X3 | Shared shell: nav with current-page state, footer with "data through" line, skip link, `assets/site.css`, `assets/site.js` (data loading, formatters, curve reader, SVG chart helpers) | P1 | M | none |
| X4 | Split data so phones do not download every curve: `index.json` for search and tables, `courses/<SUBJECT>.json` for curves on demand | P1 | M | export change |
| X5 | Chart kit: step-drawn curves, axis titles, second x-axis in calendar dates, tap or hover readout, direct labels, hatch past the data's reach, "Show as table" under every chart | P1 | M | none |
| X6 | SVG favicon, `og.png` (1200 by 630), Open Graph and Twitter tags, `theme-color`, `404.html` | P1 | S | none |
| X7 | Playwright smoke test with screenshots in CI (section 11) | P1 | M | CI only |
| B1 | About: who built it, contact, not affiliated with UC Berkeley or Berkeleytime, privacy (no cookies, no accounts, page counts only), licence, feedback by GitHub issue or email | P1 | S | none |
| B2 | Data status: last snapshot N minutes ago, sections observed, source, read live from the data branch's `status.json` | P2 | S | verified readable, section 7 |
| X8 | Custom domain | P2 | S | decision 5 |

## 6. UI and visual direction

The subject is a queue, so the one memorable element is the line: 20 dots in a row, filled for the students who got in by your date. It is the result's hero, the favicon and the link-preview image. Everything around it stays quiet.

- Colour: keep Berkeley Blue `#003262` and California Gold `#FDB515` from the current CSS, with the existing ink, paper and background tokens for light and dark. Give gold one meaning: you (your bucket, your dates, your saved cards). Blue is data. The interval band is blue at 12%. No green or red for verdicts: it fails for colour-blind readers and promises more than the data can. The chip is text first.
- Type: system UI stack, since external fonts are out. `font-variant-numeric: tabular-nums` on every number. The headline number at 3 to 4 rem. Sentence case everywhere, no all-caps labels. A self-hosted open-licence font in `site/assets/fonts/` is allowed by the contract but is polish, not P1.
- Layout: Lookup stays a narrow column (42 rem) because it is a tool. Courses, Insights and Accuracy go to about 68 rem. Left-aligned. Fewer boxes: only the result and saved waitlists are cards; the rest is type and rules.
- Phone: the nav is one scrollable row of five short labels. The Courses table becomes two-line rows (course and headline number, tap for the rest) instead of scrolling sideways. 44 px tap targets. `inputmode="numeric"` on position.
- Charts: see X5. No animation on load; honour `prefers-reduced-motion`. Markers for the first day of class and the last waitlist run in gold.
- Copy: students say "got in", the docs say "cleared". Use "got in" in headlines and define "cleared" once (decision 7). Buttons say what they do: "Look up odds", "Copy link", "Save to my waitlists". Errors say what happened and what to do next.
- States every page handles: loading, fetch failed, no estimates yet, course not found, bucket not found, pooled, horizon past the data's reach (floor), after the deadline (look back), live data unavailable (hide the block, no error).
- Accessibility: ARIA combobox pattern for search, `aria-sort` on table headers, `aria-live` on results (exists), visible focus (exists), a data table under every chart, contrast checked in both schemes.

## 7. Data and export changes

Written by `analysis/export.py` into `site/data/` (so the `analysis.yml` guard covers all of them together):

| File | Contents |
| --- | --- |
| `meta.json` | Exists. Add `terms`, `prereg_commit`, `prereg_date`. |
| `index.json` | One row per course: key, subject, level, join rank, and per bucket the share at 7, 14, 28 days and at reach with intervals, median days, cases, clearings, sections, pooled flag. Drives search, chips, Courses, related courses. |
| `courses/<SUBJECT>.json` | Today's `courses.json` split by subject: full curves per course and bucket. Loaded on demand. |
| `pooled.json` | Department cells and all-course cells by level and bucket, with curves. Drives the fallback and the department chart. |
| `insights.json` | Overall curves by bucket and by level; bucket by horizon grid; daily admits, joins and drops relative to instruction with gap days flagged; exit composition; Cox table with intervals; the headline numbers. |
| `backtest.json` | Per split, horizon and predictor: Brier, baseline Brier, gain with interval, AUC, test rows, decile calibration points. Built from `reports/backtest_<term>/`. |

`courses.json` is 99 KB today with 429 courses and mostly empty curves. With 34 grid points, four values each, four buckets and every eligible course, the full pull could reach several MB. Measure it after the pull; the split in X4 is what keeps the phone load small. Budget: Lookup under 100 KB before data, `index.json` under 300 KB gzipped.

Written by `scrape.yml` to the `data` branch each run, following the `status.json` precedent (a small file rewritten in the same commit as the Parquet file):

| File | Contents |
| --- | --- |
| `live/latest.json` | `generated_at`, `term_id`, and one compact row per section with its last observation: section id, course key, component, section number, enrolled, capacity, waitlist, waitlist capacity, minutes since observed. |

The site reads it from `raw.githubusercontent.com/<owner>/<repo>/data/live/latest.json`. Checked on 2026-09-19: that host answers `access-control-allow-origin: *` with `cache-control: max-age=300`, so a Pages site can fetch it and five-minute caching is fine for 30-minute data. Add the writer as its own step after the Parquet commit with `continue-on-error: true` so it can never fail a collection run, and land it while Fall 2026 is still the test term (before Oct 4, Oct 12 at the latest). The UI that uses it can come later.

## 8. Build order

| Phase | Dates | What |
| --- | --- | --- |
| 0 | Sep 19 to 21 | X1 publish backfill, L9 states, X2 GoatCounter, Oliver's browser pass. The site stops being empty. |
| 1 | Sep 22 to Oct 4 | X3 shell, X4 data split, X5 chart kit, Lookup L0 to L8, Insights I1 to I3, B1 about, X6 meta and images, X7 Playwright in CI, the `live/latest.json` writer. |
| 2 | Oct 5 to Oct 25 | Courses C1 to C3, course page D1 to D3, Accuracy A1 to A5, I4. Done before Phase 1 opens, when students start asking the question. |
| 3 | Oct 26 to Nov 22 | Live counts L10, D4, B2; my waitlists L11; compare L12; checklist L13; outcome form L15; I5 to I8; C4 to C6; D5; X8 domain if chosen, before the post. Soft launch inside this window. |
| 4 | Jan to Feb 2027 | Term selector L14, D6, I9, I10, A6, A7. |

Site work must not displace the dated operations in STATUS section 6: term switch Oct 4, collection running by Oct 12, priority list installed before Oct 26.

## 9. Not building

- Accounts, or email and text alerts when a seat opens: needs a backend and invites seat sniping.
- Anything that needs a CalCentral login or a student's real position feed.
- Grade distributions, professor ratings, schedule building. Berkeleytime does these well; link to it.
- Charts that redraw Berkeleytime's per-section history. Aggregates with a label are fine; their series is theirs.
- A Cox-model probability on the site until it is calibrated across phases (STATUS item 8). The site keeps the Kaplan-Meier cells.
- Rankings that include pooled or tiny cells.
- A dark-mode toggle (the system setting is already honoured), load animations, a framework, a bundler.
- Simulated numbers anywhere except the labelled methodology figure.

## 10. Decisions for Oliver

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | Several pages with shared assets, or one file with hash tabs | Several pages. Real URLs share better, GoatCounter counts them separately, each file stays small. Cost: update `DESIGN_A6.md` and the harness. |
| 2 | Verdict chip | Yes, with guardrails: Likely at 75% or more, Could go either way from 40 to 74%, Unlikely below 40%; "Too little data to call" when the interval is wider than 30 points or the cell is pooled over all courses. Thresholds printed on the page. |
| 3 | Live counts through `live/latest.json` | Yes. Writer before the term switch, UI in phase 3. |
| 4 | Count lookups per course in GoatCounter | Yes. No personal data, it shows which courses belong on the priority list, and it gives a measured usage number for `CLAIMS.md`. |
| 5 | Custom domain | Optional, about $12 a year. Worth it before the r/berkeley post because the current URL carries the long username. GitHub Pages redirects the old URL, so links shared earlier keep working. |
| 6 | Outcome form | Yes, in phase 3. A Google Form is enough. |
| 7 | "Got in" or "cleared" | "Got in" in headlines, "cleared" defined once and used in Methods. |

## 11. Tests and checks

- Harness: load `assets/site.js` and then the page's own script, one test module per page. Keep every existing assertion for Lookup.
- New cases: alias and cross-list matching ("cs61a", "data 8"); fallback to department then all courses; fetch failure state; bucket row and by-when table at a pinned `?today=`; Courses sort, filters and URL state; course page with a missing subject file; Accuracy with a missing `backtest.json`; live block hidden when `latest.json` is absent.
- Playwright in CI only (the site still ships with no build step): open every page against the synthetic-cohort JSON at 390 by 844 and 1280 by 800, light and dark; upload screenshots as artifacts; run axe-core with zero serious violations. The screenshots let a Claude Code session see the page, which STATUS section 5 says the sessions could not. Oliver's phone pass still happens before launch.
- `CLAIMS.md` rows to add once measurable: every page returns 200; number of searchable courses (printed by the exporter); lookups counted (GoatCounter export). Copied from output, never typed.

## 12. Prompt to paste into a Claude Code session

```
Continue the Berkeley Waitlist Odds project at /Users/oliverguo/berkeley-waitlist-odds. Read docs/dev/STATUS.md,
then docs/dev/SITE_V3_PLAN.md, then docs/DESIGN_A6.md and site/index.html. Run ListAgents and git log -3 before
editing. Do not start site work until STATUS section 4 item 1 is done (the backfill JSON is published).

Work on the earliest unfinished phase in SITE_V3_PLAN.md section 8, using the decisions recorded in section 10.
Use superpowers:brainstorming to confirm the phase's scope with me, superpowers:writing-plans for the plan, and
superpowers:test-driven-development while building. Use frontend-design for the visual pass against section 6,
design:ux-copy for result sentences and error messages, and design:accessibility-review before opening the PR.

Rules: static files only, no build step, no external scripts or fonts except GoatCounter; the site reads exported
JSON and never computes a statistic; no simulated numbers outside the labelled methodology figure; Berkeleytime-
derived numbers keep their label on every page; only scrape.yml writes the data branch and the live/latest.json
step must be continue-on-error; every number in CLAIMS.md is copied from command output. Update DESIGN_A6.md to
match what you build, keep tests/test_site.py green, and work on a branch with a draft PR.
```

## 13. Progress (2026-09-20, branch `site-v3`, session 5)

Built in one pass on 2026-09-20 in a git worktree (`/Users/oliverguo/berkeley-waitlist-odds-site`, branch `site-v3`). The decisions in section 10 were taken as recommended: several pages with shared assets (1), the verdict chip with its thresholds printed (2), live counts through `live/latest.json` (3, writer landed, UI on the course page), GoatCounter lookups (4, still needs Oliver's account), domain (5) and outcome form (6) left to Oliver, "got in" in headlines (7). The `superpowers`, `frontend-design` and `design` skills named in section 12 are not installed in this environment; their disciplines were applied by hand, and `dataviz` was used for the chart kit and the bucket palette.

| ID | State | Note |
| --- | --- | --- |
| X1 | with oliverguo-29 | the install commit of the full pull; `make site-data` then rewrites `site/data` in the v3 format |
| X2 | Oliver | needs the GoatCounter site code |
| X3, X4, X5, X6, X7 | done | `assets/site.css`, `assets/site.js`; `index.json`, `courses/<SUBJECT>.json`, `pooled.json`, `insights.json`, `backtest.json`; step-chart kit; favicon, `og.png`, tags, `404.html`; `tests/site/smoke.mjs` and `site-smoke.yml` |
| L0 to L9, L13 | done | L13 as a short list linking `methodology.html#cannot` |
| L10 | writer done, UI on the course page | `scraper/live.py`, `scrape.yml` step; the lookup shows no live block yet |
| L11, L12, L14, L15 | not started | P2 and P3 |
| C1 to C4 | done | C5 sparklines and C6 CSV not started |
| D1 to D4 | done | D5 (split by phase joined) and D6 not started |
| I1 to I6, I8 | done | I7 (Cox forest plot) not started; I9, I10 need Spring 2027 |
| A1 to A5 | done | A5 prints `meta.prereg_commit` once the install commit's hash is passed to `make site-data`; A6, A7 need Spring 2027 |
| B1 | done | B2 reads `meta.json`; reading the data branch's `status.json` live is not done |
| X8 | Oliver | |

Rule change the same evening (from the full-pull backtest, docs/dev/BACKFILL_BACKTEST.md B3): course-level curves do not beat the position-bucket baseline, so the exporter's default is `estimate_level="dept"` (every course shows its department's curve for the bucket, its own cases as counts) and the pages read `meta.estimate_level`; `--estimate-level course` keeps the per-course behaviour for a later term.
