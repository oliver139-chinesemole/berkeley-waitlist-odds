# Berkeley Waitlist Odds — the website: what exists, what is left

Written 2026-09-24 for the next agent (human or AI) working on the site. Everything here was verified against the repository on that date; where a fact lives on a branch rather than `main`, the branch is named. Read this before touching `site/`, `analysis/export.py` or the site workflows; read `docs/dev/MASTER_PLAN.md` for the whole project and `docs/dev/HANDOFF.md` for the session history.

## 1. What the site is

A static GitHub Pages site, https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/, that answers "I am at position N on the waitlist for course X; how likely is my spot to clear before the last automatic waitlist run, and by when?" It reads precomputed JSON under `site/data/` and never computes a statistic: each page reads a Kaplan-Meier curve at a day and prints what it finds, with the sample size and a 95% band. No backend, no build step, no external scripts (GoatCounter analytics is the one planned exception and is not added yet).

Two data regimes exist. Until this project's own Spring 2027 snapshots have clearings (Phase 1 opens Oct 26, 2026), the curves come from a finished cycle recorded by Berkeleytime's public enrollment history, labelled `berkeleytime_history` on every page that shows them. The weekly `analysis.yml` replaces `site/data` with own-data estimates only when the analysed term is 2272 (Spring 2027) and the cohort has at least 10 clearings.

## 2. Versions and where they live

| Version | Where | State on 2026-09-24 |
| --- | --- | --- |
| v2, two pages (`site/index.html`, `site/methodology.html`), data in `site/data/courses.json` + `meta.json` | `main` | **Live.** Serves Fall 2026 (Berkeleytime history), course-level curves, Spring 2027 horizons. |
| v3, eight pages on shared assets, split data files, course matcher, accuracy page, live-count writer | branch `site-v3`, PR #4 (open, not draft, checks green, untouched since 2026-09-21) | Built and reviewed by a session; waiting for Oliver's browser pass and merge. |
| P4: v3 data re-exported from the **Spring 2026** cycle with the Spring 2027 calendar; pages name the term from `meta.json` | branch `p4-spring-source`, PR #11 (draft, stacked on `site-v3`) | Reviewed ("with fixes", fixed). Merge after #4, then run `pages.yml`. |
| Session 7 (2026-09-24 and 25): course search Q1 to Q3 and Q8; palette U3 and type U4; the section board S1 to S3 with its fixture and contract | branches `q1-q3-search` (PR #17), `u3-u4-design` (PR #16), `s1-s3-fixture` (PR #19) and `s1-s3-board` (PR #20, on #19), drafts stacked on `site-v3` | Each reviewed by a subagent with one fix round; rebase onto `main` after #4. #16 opens with three decisions for Oliver (the substituted interface face, the gold focus ring, `--rust` on error text and the pooled tag). |

Merge order for the site: #15 (session 7 docs, any time), #4, then #11, then `gh workflow run pages.yml`, then #17, #16, #19 and #20 rebased onto `main`, then `curl -s https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/data/meta.json | python -m json.tool | head` must show `term_name` Spring 2026, `forecast_term_name` Spring 2027, `estimate_level` course, `data_source` berkeleytime_history.

## 3. The v3 site (branch `site-v3`)

**Pages** (`site/`): `index.html` (lookup: course search, position, the headline probability at the asker's days left, the by-when table, the curve), `course.html` (one course: sections, curve, live counts block once `live/latest.json` exists), `courses.html` (table of every course with joins rank, sortable with `aria-sort`), `insights.html` (department and phase comparisons, admits per day), `accuracy.html` (the backtests and the pre-registration paragraph), `about.html`, `methodology.html`, `404.html`; `assets/site.css`, `assets/site.js` (namespace `BWO`: fetch of the data files, course matcher with about 60 subject aliases, step-chart kit, date formatting, `setStamp`); `favicon.svg`, `og.png`, `figures/`.

**Data files** (`site/data/`, written by `python -m analysis.export`, contract in `docs/DESIGN_A6.md` and `docs/DESIGN_A5.md` section 4):
- `meta.json`: `term_id`/`term_name` (the data term), `forecast_term_id`/`forecast_term_name` + `dates` + `deadline` + `instruction_start` (the term the pages count down to), `data_source`, `estimate_level`, `min_n` (30), `n_boot` (200), `courses`, `sections`, `cohort_rows`, `events`, `join_window`, `data_dates`, `backfill`, `flows`, `prereg_commit`/`prereg_date`, `subject_files`, `terms`, `generated_at`.
- `index.json`: one row per course with its joins rank and the probabilities at fixed horizons (`HORIZONS`).
- `courses/<SUBJECT>.json`: per course, per position bucket (1-5, 6-15, 16-40, 41+): the curve (`read_curve` step function), the section-bootstrap band, `n`, `pooled` flag and the fallback level. A course gets its own curve when the cell has at least `min_n` rows (`estimate_level` course), else the department's, else all courses', labelled as pooled.
- `pooled.json`: the department and all-course pools. `insights.json`: the insights page's tables. `backtest.json`: written separately by `python -m analysis.export_backtest` from `reports/backtest_<term>/`; the accuracy page reads its `term_name` (Fall 2026 today) independently of `meta.json`.
- The exporter deletes stale `courses/*.json` before writing; bootstraps are seeded (`section_bootstrap_band(seed=0)`), so a re-export is byte-identical apart from `generated_at`.

**Live counts**: `scraper/live.py` plus a step in `scrape.yml` write `live/latest.json` on the `data` branch after every run (the last observation of every full or waitlisted section, with `open_reserved`); the course page shows a live block from it. Nothing is written until #4 merges: the file is a 404 today.

**How the pages decide what to show**: `BWO.today()` (pinned by `?today=YYYY-MM-DD` for tests and screenshots); days left = forecast deadline minus today; the headline reads the course-bucket curve at that day; past the curve's reach the page prints a floor and says so; after the deadline the page becomes a look-back. Source sentence and "Data status" lines read `meta.term_name`, `meta.data_source` and `meta.estimate_level`; the pre-registration paragraph (about, accuracy) reads `meta.prereg_commit` (7f348ed for Spring 2026 on #11: the PR #6 commit that installed the Spring 2026 cohort; a7240f4 for Fall 2026).

## 4. Build, test, deploy

```
# environment: the main checkout's venv, Python 3.12
source /Users/oliverguo/berkeley-waitlist-odds/.venv/bin/activate

# rewrite site/data from a saved cohort (2 minutes; SITE_TERM is the cycle the site serves, 2262 since PR #11)
make site-data                       # = python -m analysis.export --cohort analysis/out/$(SITE_TERM)/cohort_central.parquet --term-id $(SITE_TERM) --forecast-term 2272 --out site/data --flows analysis/out/$(SITE_TERM)/flows.parquet --meta-from site/data/meta.json --estimate-level course
python -m analysis.export_backtest   # backtest.json from reports/backtest_<term>/

# tests: every page's own script rendered under node against a stub document and file-backed fetch
python -m pytest tests/test_site.py  # needs node (PATH or ~/.nvm/versions/node/*/bin/node); skips without it
python -m pytest                     # the whole suite (360+ on site-v3)

# render a real page against the real data, no browser
node tests/site/harness.js site/index.html site "" "COMPSCI 61A" 8 ""

# browser smoke (Playwright + axe-core): CI runs it in site-smoke.yml on every push and uploads light and dark screenshots as an artifact
NODE_PATH=/Users/oliverguo/paddleiq/node_modules node tests/site/smoke.mjs http://127.0.0.1:8000 screenshots 2027-01-10   # after `python -m http.server 8000 -d site`

# deploy: pages.yml publishes site/ from main; analysis.yml dispatches it after a weekly commit
gh workflow run pages.yml
```

Gotchas that cost time in September 2026:
- `--meta-from` carries source labels from the `meta.json` already in `site/data`; since #11 the exporter refuses to carry them when that file describes another term (Makefile `SITE_TERM` defaults to 2262; `backfill-analysis` writes its site files to `analysis/out/site_<term>`, never to `site/data`).
- The cohort and flows inputs (`analysis/out/<term>/`) and the backfills (`backfill/<term>/`) are gitignored and exist only in the main checkout at `/Users/oliverguo/berkeley-waitlist-odds`; a worktree does not have them. Pass absolute paths.
- Claude Code worktrees: `EnterWorktree` creates `.claude/worktrees/<name>` on branch `worktree-<name>` from `origin/main`; the guard refuses git pointed elsewhere (`-C`, command substitution, shell variables next to git) and heredocs containing git-ish words, so write scripts and long files with the Write tool and run them by path. Do not switch worktrees while a reviewer subagent runs: the guard is session-wide.
- `python -m pytest -q` hides the summary line (addopts already has `-q`).
- The methodology page's request-rate sentence deliberately names no number: the scraper's rate is set in `scrape.yml` and logged in `docs/DATA_LOG.md` (one request per second until 2026-09-23, at most two per second with four in flight after PR #8). Fixed on `site-v3` in session 7 (commit ea61bf4): the sentence links the data log and the priority list is described as generated, not fixed.

## 5. Done (v3, PR #4, plus #11)

From `docs/dev/SITE_V3_PLAN.md` section 13 and MASTER_PLAN section 2: shared assets and eight pages; split data files; the course matcher (`cs61a`, `CS 61A`, `comp sci 61a`, `data 8` → `DATA C8`, about 60 aliases, ranked by joins); verdict chip; copy-link and copy-text; compare; `aria-sort` tables; the step-chart kit; favicon, `og.png`, tags, 404; L0 to L9 and L13 (the "what this number cannot see" list linking `methodology.html#cannot`); C1 to C4; D1 to D4; I1 to I6 and I8; A1 to A5 (accuracy page from `reports/backtest_2268`, five predictors, cross-term runs); B1; X3 to X7 (X7 = Playwright screenshots in CI, done); `scraper/live.py` and its workflow step; `estimate_level` (course, with department then all-courses fallbacks); the Spring 2026 source with the Spring 2027 calendar and the pages naming the term from `meta.json` (#11). Design decisions taken: gold means "you" and "now", an ordinal blue ramp for position buckets, no red/green.

## 6. Left to build (IDs from `docs/dev/MASTER_PLAN.md` section 3; order from its section 5)

Nothing site-side should start before #4 merges (P1): stacking on an unmerged branch produces conflicts, not speed. After #4 and #11:

Session 7 (2026-09-24) worked Track B of `docs/dev/NEXT_2026-09-24.md` while #4 waited: B1 (the methodology sentence, on `site-v3`), B2 (PR #17) and B3 (PR #16) stacked on `site-v3`; B4 (PR #19: the section-board fixture, the harness hooks and the strict-xfail contract) and then A3 itself (PR #20: the board, S1 to S3, with the `scraper/live.py` columns and selection) followed after Oliver's go-ahead; PR #18 adds the `.claude/agents/` definitions (see `docs/dev/HANDOFF.md` session 7).

| ID | Item | Status | Notes |
| --- | --- | --- | --- |
| P3 | `live/latest.json` starts being written | lands with #4 | verify the file on the `data` branch after the first run |
| P6 | GoatCounter on every page | Oliver | needs his site code; visits cannot be backfilled, so before any link is shared |
| S1 | Live section board: one row per section, enrolled/capacity, waitlist/capacity, seats open, seats open but reserved, "read N minutes ago" | draft PR #20 (on PR #19, stacked on `site-v3`) | one row per section with enrolled/capacity, waitlist/capacity, seats open, the reserved line, `read N min ago`, a blue status ramp; PR #19 holds the fixture, the harness hooks and the contract test. `scraper/live.py` now emits `reserved_count` and `open_reserved` and writes every section of a course with a full or waitlisted section (about 160 KB, 30 KB gzipped) |
| S2 | Reserved-seat line per row from `open_reserved` ("4 seats open, all reserved") | draft PR #20 | registrar's wording: `N seats open, all reserved`, `N seats open, anyone can take them`, `N seats open, M of them reserved` |
| S3 | Staleness warning when a section is off the priority list and its number is six hours old | draft PR #20 | a plain note inside any row read six hours ago or more; the page cannot see the priority list, but a section on it is read every 30 minutes |
| S4 | Section history export: daily waitlist series, admits per week, deepest position that cleared | open | needs own data (after Oct 26) |
| S5 | Section fallback ladder printed on the page; a section-level curve only where n ≥ 30 | open | |
| S6 | Cross-listed sections as separate rows, never merged | open | |
| S7 | "Which section should I waitlist": queue depth, admits per week, deepest cleared, side by side; not a model output | open | |
| S8 | Recent openings feed from consecutive own snapshots | open | needs own data |
| S9 | Watchlist in `localStorage` + `Notification` while the tab is open; no backend | open | |
| Q1 | Full subject names (`computer science 61a`) from a generated `config/subject_names.json`; hand nicknames in a separate file | draft PR #17 (stacked on `site-v3`) | generated `config/subject_names.json` (an Internet Archive snapshot of the Academic Guide's subject list, recorded as `_source`; 133 of 137 named, four under `_todo`) and hand-written `config/course_nicknames.json`; `scripts/subject_names.py --check` runs in the tests |
| Q2 | Filler stripping (`berkeley cs61a`, `cs61a discussion`), split suffix (`cs 61 a`), bare number (`61a`) | open | |
| Q3 | Fuzzy subject only (Damerau-Levenshtein ≤1 up to five characters, ≤2 above); numbers never fuzzed | open | |
| Q4 | Title and instructor search; `titles.json` lazy-loaded so a plain code query never fetches it | open | titles and instructors land in `catalog/<term>/catalog.json` on the `data` branch with PR #10 (Q7); the exporter can read them from there |
| Q5 | "Showing COMPSCI 61A for *compsi 61a*" whenever a fuzzy or title match fires | open | |
| Q6 | Miss handling: three nearest candidates, browse-by-department, a logged miss event | open | |
| Q8 | `tests/fixtures/course_queries.csv`, about 150 rows, run in pytest and in the node harness | open | |
| U1 | Term timeline on every page with today as a gold tick; the chart shares its horizontal scale | open | |
| U2 | Queue strip as the hero (N ticks, your position in gold, shaded to the historical reach); also favicon and OG | open | |
| U3 | Palette: `--bg #F2F5F9`, `--ink #10202E`, `--line #C9D4E0`, `--blue #003262` data, `--gold #FDB515` you/now only, `--rust #8C4A1F` seats held back; dark `--bg #0B1622`, `--paper #13202E`, `--ink #E6EDF5`, `--blue #7FB2E5` | open | |
| U4 | Type: Source Serif 4 headlines, Atkinson Hyperlegible interface, self-hosted subset woff2 under `site/assets/fonts/` (about 60 KB), scale 12.8/16/20/25/31/39/49/61, `tabular-nums lining` on figures | open | |
| U5 | Density: lookup and board dense at 38/68 rem; insights and accuracy at 64 rem with air | open | |
| U6 | One animation (queue strip fills, gold tick drops), one signal (freshness dot); `prefers-reduced-motion` off | open | |
| U7 | Section status as a blue ramp, never red/green | open | |
| U8 | No all-caps labels, no single accented headline word, no monospace standing in for "data" | open | |
| L11 | My waitlists in `localStorage` | open | |
| L15 | Outcome form: course, position, date joined, outcome | open | the only individual-level ground truth |
| C5, C6 | Row sparklines; CSV download of the current view | open | |
| I5 to I8 | Admits per day against the calendar with the Aug 19 to Sep 1 outage shaded; exit composition; Cox forest plot; hardest and easiest courses | open | I7 not started |
| B2 | Data-status line read from the data branch's `status.json` | open | reading `status.json` live is not done |
| — | Department pages (`/dept/COMPSCI`) | open | keyed by subject |
| X8 | Custom domain | Oliver, optional | before the r/berkeley post |
| — | Off-season home page | moot | v3 counts down to Spring 2027 and the key-dates strip carries Oct 26; revisit only if the browser pass says otherwise |

Data-side items the site depends on: the first own-data analysis (`make analysis TERM=2272`) from Nov 9; the refit after Phase 2 closes (Jan 2027) and the pre-registered cross-term test after Feb 10, 2027, which the accuracy page is written to display.

## 7. Rules that must hold (MASTER_PLAN section 8)

- Static files only, no build step, no external scripts, no external fonts except GoatCounter and self-hosted faces.
- The site reads exported JSON and never computes a statistic.
- No simulated numbers outside the labelled methodology figure.
- Berkeleytime-derived numbers keep their `berkeleytime_history` label everywhere they appear.
- Only `scrape.yml` writes the `data` branch; only `analysis.yml` commits to `main` on its own; the `live/latest.json` step stays `continue-on-error`.
- Every number in `CLAIMS.md` is copied from command output, never typed (the site rows: "GitHub Pages 200" and "Site source for Spring 2027").
- One PR per item, draft, for Oliver's review; keep `tests/test_site.py` green; update `docs/DESIGN_A6.md` to match what you build.

## 8. Oliver's items that gate the site

Browser pass of v3 (phone and laptop, light and dark, including `?today=2026-09-15` for the look-back state); the GoatCounter code; the resume line ("Spring 2027 enrollment cycle") and the two paragraphs that mention it; the custom domain; the r/berkeley post (soft launch before Nov 23 if the numbers hold).
