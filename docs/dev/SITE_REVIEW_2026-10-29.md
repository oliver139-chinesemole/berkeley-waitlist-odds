# Berkeley Waitlist Odds: site review, 2026-10-29

(Pasted by Oliver on 2026-10-29 21:00Z; committed verbatim. The session-11 plan for it is `docs/dev/plans/2026-10-29-batch6.md`.)

Repo `oliver139-chinesemole/berkeley-waitlist-odds`, `main` at `0927c458`, data branch as of 2026-10-29 07:00 UTC (section 0A re-checked at 21:00 UTC).

**How this was tested.** `site/` served locally. Every page loaded in headless Chromium at 1280px and 390px wide (46 page loads), with console errors, failed requests, horizontal overflow and internal links checked. Then the lookup, combobox, position input, copy buttons, course table sorting and filtering were driven by script. Site numbers were checked against `site/data/*.json`, `data` branch `status.json` and `catalog/*/catalog.json`, and the Spring 2027 catalog was diffed against `index.json`.

The unmerged branch `integration-2026-10-28` (`8f6422d1`) was then served and run through the same checks. Section 7 says which items it already fixes, so merge it before starting on this list.

Severity: **P0** loses data or is broken now · **P1** wrong number or misleading result · **P2** glitch or confusing UX · **P3** polish.

---

## 0. The problem that started this: "ECON 121 shows nothing"

**What happened.** Searching ECON 121 gives no suggestion. Submitting it shows "No data for ECON 121. Check the spelling, or the course had too few waitlisted students to estimate", then the ECON department curve.

**Why.**
1. **ECON 121 is not offered in Spring 2027.** The scraper's own Spring 2027 listing (`data:catalog/2272/catalog.json`, 7,631 sections, updated 2026-10-28) has no ECON 121 section. So there is correctly no forecast. But the message is wrong: it blames spelling or sample size when the course isn't on the schedule.
2. **The site only knows courses that had a waitlist in Spring 2026.** `analysis/export.py` `course_tables()` builds one entry per `course_key` in the cohort. A course with no Spring 2026 waitlist joiners never reaches `index.json`, so the combobox, course list, department pages and `course.html` don't know it exists.

**How big the gap is (Spring 2027 catalog vs `site/data/index.json`):**

| | Courses |
|---|---|
| Spring 2027 courses in the catalog | 2,571 |
| On the site | 1,430 |
| **Missing from the site** | **1,141** |
| Missing, with a lecture section | 800 |
| Missing, undergrad (under 200), with a lecture | 484 |

Missing ECON courses offered in Spring 2027: 128, 133, 135, 144, 152, 172, 182, C175, plus 23 grad courses. Other examples: AFRICAM 100, ASAMST 121, BIOENG 11, CHEM 104B, CHEM 120A, CHINESE 100B, ASTRON C10.

**Fix.**
- In `export_site_tables()`, when `catalog` (the forecast term's `catalog.json`) is passed, add a row for every catalog course that isn't already in `courses`. Give it `dept_group` from the same subject-to-group rule `cohort.py` uses, `level` from `course_level()`, and pointer cells `{"pooled": <dept or "all">, "n_course": 0, "sections_course": 0}` for each bucket the pool has. `site.js` already renders a "stub for a course with no data" (`site.js:293`), so the pages show "pooled, this course had no cases" with no front-end change.
- Pass the Spring 2027 catalog into `analysis.run` and `make site-data`. This is the same wiring as the still-open "wire the catalog into analysis.run so titles.json survives" item in `CLAUDE.md`, so it also turns on title search (see 2.6).
- For a course that's in neither the index nor the forecast-term catalog, change the message at `index.html:126` and `course.html:172` to "ECON 121 isn't on the Spring 2027 schedule." Keep the department fallback below it.
- Add a test: a catalog course with no cohort rows appears in `index.json` with `pooled` cells and `n_course: 0`.

---

## 0A. Why GitHub emails "All jobs have failed"

Checked through the GitHub API at 2026-10-29 21:00Z: run list, job steps and annotations for runs 40841659063, 40946132033, 40854967812 and 40947380577, issue #57, plus every `status.json` commit on the `data` branch since Oct 24. The raw job logs and the `fetch-log` artifacts could not be downloaded from here (the storage host is blocked), so the per-request timeout and 504 counts below are inferred, not read.

### What is failing

| Workflow | Oct 28 | Oct 29 (to 21:00Z) | Failing step | Annotation |
|---|---|---|---|---|
| `scrape` | 3 failed / 36 ok | **10 failed** / 31 ok | `Fetch snapshot` | `Process completed with exit code 4` |
| `monitor` | 1 failed | 2 failed | `Fail the job when the gap check failed` | (gap breach, issue #57) |
| `heartbeat`, `ci`, `site-smoke` | all ok | all ok | | |

Failed scrape slots on Oct 29: 07:07, 07:37, 08:07 (cron 08:22), 09:07, 09:37, 10:07, 18:37, 19:07, 20:07Z. The 07:00 to 11:00Z run of failures left **a 240-minute hole**.

### Root cause: the site got slower after Phase 1 opened, so runs hit the coverage gate

1. **Exit 4 is `EXIT_LOW_COVERAGE`** (`scraper/fetch.py:53`, `:494-499`). When more than half the selected sections weren't fetched before the 1,380 s budget ran out (`--max-missing-share`, default 0.5), the run **writes nothing at all**, even the sections it did read. The job fails, and GitHub sends the email.
2. **Same work, slower server.** Every run selects about 1,430 sections, but the median sweep time has climbed since Phase 1 opened on Oct 26:

   | Day | Runs written | Median sweep (budget 1,380 s) | Worst missing share |
   |---|---|---|---|
   | Oct 24 | 6 | 823 s | 0.000 |
   | Oct 25 | 48 | 846 s | 0.114 |
   | Oct 26 (Phase 1 opens) | 46 | 930 s | 0.403 |
   | Oct 27 | 46 | 967 s | 0.461 |
   | Oct 28 | 45 | 1,180 s | 0.326 |
   | Oct 29 | 31 | **1,379 s** | 0.488 |

   The runs right next to the failures read 726 to 880 of about 1,430 sections (0.53 to 0.64 pages per second). At 4 pages in flight that's roughly 6 to 7.5 s per page. The request policy only covers the selection up to about 3.8 s per page (`docs/DESIGN_A2.md` section 16). This is the Sep 21-23 failure mode (`docs/DATA_LOG.md` rows 61-64, issue #7), now driven by enrollment traffic on classes.berkeley.edu.
3. **Partial runs lose data too.** Even successful runs dropped 179 to 649 sections at 01:00, 01:30, 02:30, 04:30, 11:00, 11:30, 12:00, 17:30, 18:00 and 18:30Z, including priority sections.
4. **The monitor is working correctly.** `scraper.gaps` breached on "largest gap 240 min > 90" and "37 runs < 40 in 24 h" (issue #57). It will stay red until the scrape runs stop failing. Don't silence it.
5. **And all of it is spent on the wrong term.** Every one of these runs scraped Fall 2026 (`term_id 2268`, see 1.1). So the budget the slow server leaves is going to a finished term, and none of it is Spring 2027 data.

### Fix (in order; the first two are needed together)

1. **Switch the term (1.1).** This doesn't fix the speed, but it stops the failures from costing a term that's already over.
2. **Stop throwing away partial runs.** In `scrape.yml`'s `Fetch snapshot` args, add `--max-missing-share 0.95`. Exit 2 (zero rows) still catches a dead run. The rebuild already reads unfetched sections from `missing_ids` as unobserved (`DATA_LOG.md` row 70), so a run with 726 of 1,430 sections is real data, not corruption. Add a `decision` row to `DATA_LOG.md`. Comment it in the workflow: `# shortcut: keeps partial sweeps during upstream slowdowns; return to 0.5 if rebuild ever stops honouring missing_ids`.
3. **Shrink the per-run selection for Spring 2027 (1.2).** Regenerate `config/priority_courses.txt` from courses that are in `catalog/2272/catalog.json` *and* had waitlist joins. Spring 2027 lists 7,631 sections against Fall's 3,900, so each 1/12 shard also roughly doubles. Aim for a selection under about 1,000 pages, or raise `--n-shards` to 24.
4. **Only if 2 and 3 aren't enough:** `--max-concurrency 6` (already sized in `DESIGN_A2` section 16, covers up to about 5.7 s per page at the same 2-per-second ceiling). This is your call and needs a `decision` row. Don't raise `--min-interval-s` throughput further while the site is under enrollment load, and roll back on any 429 or 403 (RUNBOOK item 9).
5. **Log the holes:** `outage` rows in `DATA_LOG.md` for 2026-10-29 07:07Z to 11:00Z and 18:37Z to the first good run (both term 2268), so `analysis/panel.py` censors them. Then close issue #57 once the 24 h report is clean.

### Not failing yet, but in the same annotations (P3)
- `Node.js 20 is deprecated ... actions/checkout@v4, actions/setup-python@v5, actions/upload-artifact@v4` are being forced onto Node 24. Bump each to its current major that targets Node 24 (check each action's release notes), in every workflow file.
- `The ubuntu-latest label will migrate to Ubuntu 26 beginning October 19, 2026.` Pin `runs-on: ubuntu-24.04` until after the Feb 10 add/drop deadline, so the image doesn't change in the middle of the cycle.

---

## 1. Fix first (in this order)

### 1.1 P0: the scraper is still collecting Fall 2026, three days into Spring 2027 Phase 1
- `data:status.json` at 06:37 UTC today has `"term_id": "2268"`, and every commit on the `data` branch today is `snapshot Fall 2026 ...`. Phase 1 opened Mon Oct 26, and the runbook deadline for the switch was Oct 12.
- Data gaps are permanent (`CLAUDE.md`). Every day before the switch is Phase 1 data the Spring 2027 test can never have.
- It also blocks the site from ever switching to its own data. `analysis.yml:53-67` only replaces `site/data` for term 2272 with at least 10 clearings, and the weekly run has been analysing 2268 (commits `analysis: Fall 2026` on Oct 4, 11, 18, 25 only touched `reports/`).
- **Fix** (RUNBOOK step 7, needs your `gh` login):
  ```
  gh variable set SCRAPE_TERM --body "Spring 2027"
  gh workflow run scrape.yml -f term="Spring 2027" -f force_baseline=true
  gh run watch
  git fetch origin data && git show origin/data:status.json   # expect "term_id": "2272", "kind": "baseline"
  ```
  Then add a `term_switch` row to `docs/DATA_LOG.md`, plus a row saying Oct 26 to the switch time is a gap for 2272.

### 1.2 P0: 38% of priority sections aren't reached per run, and the site prints it on every page
- `status.json`: `n_observed 880`, `n_missing 551`, `missing_share 0.385`, `sweep_seconds 1392.6` against the 1,380 s budget. Every page shows "880 sections read, 551 not reached" in the status line.
- For Spring 2027, only 564 of the 1,013 priority-list entries match a Spring 2027 course (the list was built from Fall 2026 and Spring 2026). So the list is both too long for the budget and partly aimed at courses that aren't running.
- **Fix:** after 1.1, regenerate `config/priority_courses.txt` with `python -m analysis.priority_from_flows` restricted to courses in `catalog/2272/catalog.json`, and cut it until `missing=` in the run logs stays under a few dozen. Log the `priority_sha` change in `docs/DATA_LOG.md`.

### 1.3 P1: the estimates are optimistic for the case the site actually serves
`accuracy.html`, the runs "Fit on Spring 2026, scored on Fall 2026". These score exactly the curves the pages show:

| Horizon | Estimate said | Actually got in |
|---|---|---|
| 14 days | 54% / 68% / 89% | 38% / 51% / 67% |
| 28 days | 28% / 53% / 72% / 87% | 21% / 36% / 57% / 67% |
| Last auto run | 34% / 51% / 67% / 94% | 47% / 61% / 71% / 92% |

At 14 and 28 days the site over-predicts by 15 to 22 points. Every page also says "a course's own curve predicted better than its position alone". That is true for cross-cycle ranking (AUC), but the within-term "later joiners" runs show the course curve doing worse than the baseline (gain −0.023 and −0.015), and calibration is off in both directions.
- **Fix (pick one, smallest first):**
  (a) Say it on the result card: "In testing on Fall 2026, numbers like this ran about 15 to 20 points high at 14 and 28 days." Link to accuracy.
  (b) Recalibrate: fit an isotonic map from predicted to observed on the cross-cycle backtest and apply it in export.
  (c) Soften the "predicted better" sentence to say ranking, not calibration.

---

## 2. Bugs and wrong numbers

### 2.1 P1: "Almost everyone got in" / "100% floor" comes from the Kaplan-Meier tail, not the data
- COMPSCI 61A at position 40: headline "Almost everyone got in by Feb 5, 2027 · 100%", but only 407 of 611 hypothetical joiners cleared, follow-up is 30 days, and the curve is 61% at 7 days and 76% at 14 days. DATA C8 at position 10: "100%" from 45 cases followed for 4 days. MATH 54 at position 3: "99% (95% interval 99% to 99%)".
- The course list's default sort puts these first: the top of `courses.html` at "6 to 15 · 14 days" is ASAMST 20A, COMPSCI 61B, DATA C8, ECON C181, EECS 127, ENGIN 125, all "100% floor", mostly one section.
- Cause: a KM curve jumps to 1.0 when the last few joiners still at risk all clear. `readCurve` (`site.js:252`) then carries that value forward as a "floor". A floor of 100% isn't a floor.
- **Fix:** in export, cut each curve at the last day with at least N at risk (for example 20, or 10% of n) and use that as `reach`. On the page, never print "floor" at 99% or above; say "at least X% within D days, the longest the data follow". Change the courses default sort to put rows with fewer than 2 sections or a `floor` value below the rest, or sort by the interval's lower bound.

### 2.2 P1: the headline contradicts the verdict on the same card
ECON 121 (pooled ECON): "About 15 in 20 got in" and 15 filled dots, then directly below "Too little data to call". COMPSCI 61A at 40: "Almost everyone got in", then "Too little data to call (one section only)".
- **Fix** (`headlineHtml`, `site.js:720-740`): when `verdict(...).label === "Too little data to call"`, use a neutral lead ("Spring 2026 rate: 75%, but see below") and dim the dots (`dots(p, {dim: true})` already exists).

### 2.3 P1: degenerate intervals look precise
"99% (95% interval 99% to 99%)" for MATH 54 comes from a section bootstrap over 2 sections. With 2 or fewer sections the bootstrap can't produce an interval.
- **Fix:** in export, set `lo`/`hi` to null when `sections < 3`. The verdict then already says "Too little data to call", same as for 1 section.

### 2.4 P1: Cox model scores look like a scoring bug
Accuracy, within-term runs: Cox Brier 0.581 and 0.548. A constant 0.5 would score 0.25, so this is worse than guessing. The other runs give 0.20 to 0.32.
- **Fix:** check `analysis/backtest.py` Cox scoring at each joiner's own horizon. The usual suspects are survival vs. event probability (1−S vs S) or the baseline hazard not being re-indexed to the horizon. If it's real, say so in "What could not be tested"; the current note only explains a Phase 1 to Phase 2 shift.

### 2.5 P2: "Copy as text" produces broken English
MATH 54 at 3 copies "almost everyone comparable students got in by Feb 5, 2027". "Almost no one" breaks the same way.
- **Fix** (`index.html:77`): `frequency(p)` already returns "Almost everyone" / "About k in 20". Use `"of comparable students"` after "About k in 20" and drop "comparable students" for the two phrase cases, or reword to "`${pct} of comparable students got in by ...`".

### 2.6 P2: course-title search is shipped but dead
`site.js:577-594` loads `data/titles.json` via `meta.titles_file`, but `meta.json` has no `titles_file` and there's no `titles.json`, because the catalog isn't passed to the export. Searching "industrial organization" or an instructor name finds nothing. This is fixed by the same catalog wiring as section 0.

### 2.7 P2: the position from the URL isn't validated like the form
- `index.html?course=MATH%2054&position=1000` shows "position 1000", but the form caps at 500 (`index.html:39`) and `course.html:38` clamps to 500.
- `position=0`, `-5` and `abc` silently become position 1, while the input box shows `0` / `-5` / empty.
- **Fix** (`index.html:177`): clamp to 1..500 the same way `course.html:38` does, and write the clamped value back to the input.

### 2.8 P2: two pages, two names for the same parameter
`index.html` reads `?course=`, `course.html` reads `?c=` (`course.html:168`). `course.html?course=ECON%20100A` says "No data for this course. Check the spelling" for a course that exists. Internal links all use `c`, so this only hits hand-typed or shared URLs.
- **Fix:** `BWO.params().get("c") || BWO.params().get("course")`.

### 2.9 P2: insights curves cross, and the page reads them as a ranking
- "All courses and phases" endpoints: 16-40 at 85%, 6-15 at 84%, 41+ at 79%, 1-5 at 74%. On the lower-division Phase 1 chart, 6-15 (92%) ends above 1-5 (83%). The 41+ line jumps from 47% to 68% around day 49.
- These are tail artifacts with few joiners at risk (same cause as 2.1). Positions 1-5 also contain many sections that never move. Meanwhile "In short" says "Position matters most in the first two weeks", which is true, but the charts show the opposite at the right edge with no explanation.
- **Fix:** apply the at-risk cut from 2.1 to these curves too, and add one line: "after about 4 weeks the curves rest on few joiners; read the 14- and 28-day columns."

### 2.10 P3: "Lower-division waitlists moved faster" is a 1-point difference
Insights: "61% ... against 60% in upper-division". The generator should only claim a difference when the intervals don't overlap, and say "about the same" otherwise.

### 2.11 P3: "Still waiting at the end: 0% (0)"
`insights.json.exits.still_waiting = 0`, because the last observation is mid-May, after the registrar purges waitlists. That pushes the end-of-term purge into "Dropped the list (22%)". Either drop the "still waiting" bar, or measure at the last automatic waitlist run (Feb 6, 2026) and label the purge.

---

## 3. Glitches and UX

| # | Sev | Where | What | Fix |
|---|---|---|---|---|
| 3.1 | P2 | `courses.html` at 390px | Table rows stack into bare numbers (`2.8`, `62`, `1`) with no column labels, so median days, cases and sections are unreadable | Add `data-label` per cell and a CSS `::before` label in the mobile layout, or show only "Share" plus "Cases" on mobile |
| 3.2 | P2 | Nav at 390px | Last tab is cut to "M" (Methods) with no scroll hint | Shrink tab padding below 420px, or let the row wrap |
| 3.3 | P2 | Lookup "Did you mean" | ECON 121 suggests ECON 100A, 100B, 1 (most-joined), not near numbers. "xyz" suggests the three example chips | Rank `nearest` by catalog-number distance within the subject first; don't offer suggestions for a subject that doesn't exist |
| 3.4 | P2 | `dept.html?subject=NOPE` | "Nearest: Earth and Planetary Science, Environmental Science, Policy, and Management, Global Poverty and Practice", which are unrelated | Only list near matches under an edit-distance cutoff, otherwise just "browse every course" |
| 3.5 | P3 | Lookup card at 390px | The 20-dot row wraps 17 + 3 | `flex-wrap: nowrap` and smaller dots under 420px |
| 3.6 | P3 | Insights charts | All four position lines are close blues, and endpoint labels stack and overlap where curves meet | Use the dataviz palette's 4 distinct hues and push labels apart |
| 3.7 | P3 | Combobox | Suggestions show "· 538 joins" with no explanation, and the number differs from "562 cases" on the department page for the same course | Rename to "waitlist joins, Spring 2026" or drop it from the suggestion row |
| 3.8 | P3 | `dept.html` | "grad division" (should be "graduate"); DISSTD listed by code because its name is `""` in `config/subject_names.json` | Fix the label; fill in the name |
| 3.9 | P3 | Calendar strip | Phase 1 is open now (ends Nov 15), but the strip starts at "Phase 2 opens" | Add "Phase 1 (continuing) ends Nov 15" while it's running |
| 3.10 | P3 | `404.html` | No `meta description`; every other page has one | Add one |

---

## 4. Stale or wrong copy (all written before Oct 26 and now false)

| Where | Says | Reality now |
|---|---|---|
| Every page's source banner, `site.js:161` | "Live Spring 2027 collection by this project starts Oct 26, 2026" | It's Oct 29 and collection hasn't started (1.1) |
| Every result card, `site.js:290` | "Section curves need ... Spring 2027 snapshots; none exist before Oct 26, 2026" | Implies they exist now; they don't |
| `methodology.html:29` | "Collection for Spring 2027 starts when Phase 1 opens on Oct 26, 2026" | Same |
| `about.html:38` | "an outcome form will be linked from the lookup page once Spring 2027 enrollment opens" | Enrollment opened Oct 26; there's no form |
| `site.js:152` `emptyHtml` | "first curves appear ... (planned for mid-November)" | Only shown in the empty state, but the date needs re-checking after 1.1 |
| Status line on every page | "This project's last **Fall 2026** snapshot ..." | Accurate, but it tells every visitor the scraper is on last term |
| Footer | "Data through May 15, 2026 ... page generated Sep 24, 2026" | Not wrong, but the site data hasn't changed in 5 weeks (see 1.1) |

**Fix:** make these dates conditional on `status.json` (`term_id === meta.forecast_term_id`), not hard-coded. For example, "Live Spring 2027 collection started Oct 26" once `status.term_id` is 2272, and "has not started yet" before.

---

## 5. What works well (keep it)

- **No runtime errors.** Zero console errors, page errors or failed requests across 46 page loads (9 pages, edge-case URLs, both widths).
- **No horizontal overflow** on any page at 390px (`scrollWidth == clientWidth`).
- **No broken internal links.** Every relative link resolves. The external links (repo, CLAIMS.md, ASSUMPTIONS.md, DATA_LOG.md, issues) point to files that exist on `main`.
- **Forgiving course matching.** `cs61a`, `math54`, `Data 8` → DATA C8 ("Showing DATA C8 for Data 8"), `econ100a` and `compsci 61b` all resolve. Arrow-down and Enter in the combobox picks the suggestion and submits.
- **Form validation** uses native constraints: 0, -3, 501, 2.5 and an empty course are all blocked with the browser's message.
- **Fallback ladder works.** An unknown course or a missing bucket falls back to the department, then all courses, and says which ("ECON 121 had no cases", "the waitlist there was never that long. Positions with data: 1-5, 6-15, 16-40").
- **Honest labelling.** Source, sample size, sections, median and interval are printed on every estimate, the verdict cut-offs are printed under every verdict, and "floor" is marked whenever the horizon passes the data.
- **Accessibility basics.** `lang="en"`, one `h1` per page, skip link, charts with keyboard reading ("arrow keys") and a "Show as table" alternative, `role="img"` with an `aria-label` on the dots, `aria-live` on the copy confirmation, labelled inputs.
- **Copy link** produces a clean, shareable URL (`index.html?course=MATH%2054&position=3`).
- **Courses table** sorts (Cases puts PHYSED 1, UGBA 135, MATH 54 first), and the filter text and sort persist in the URL (`courses.html?q=econ+1&sort=n`).
- **The accuracy page is the strongest page.** It's pre-registered (frozen at `7f348ed`), lists what couldn't be tested (the Aug 19 to Sep 1 Berkeleytime hole), and shows the bad results too. That's what makes 1.3 fixable rather than hidden.
- **Scraper cadence is otherwise healthy.** 43 to 48 runs a day from Oct 18 to 28, and the live status line reads `status.json` correctly.

---

## 6. Not checked

- The deployed GitHub Pages copy (not reachable from this environment). Everything above is from `main`'s `site/`. If Pages is behind `main`, re-check the copy items there.
- Screen-reader behaviour (VoiceOver) and color contrast numbers. Only structure was checked.
- Whether the Kaplan-Meier and bootstrap numbers in `site/data` match a fresh `make site-data` run.
- Safari and Firefox. Only Chromium was used.

---

## 7. Status on `integration-2026-10-28` (same checks, run on that branch)

Still zero console errors and zero overflow on that branch.

**Already fixed there (merge it, then close these):**
- 2.2 The verdict now leads the card when it's "Too little data to call", and the headline moves below it.
- 2.5 Copy as text now reads "almost everyone among comparable students got in ...".
- 2.6 `data/titles.json` (catalog 2272) and `meta.titles_file` are written, so title search has data. Not exercised in this review.
- 2.10 The "Lower-division waitlists moved faster" sentence is gone.
- 3.2 All five nav tabs fit at 390px.
- 4 The status line says "This project has not started collecting Spring 2027 yet"; the "none exist before Oct 26" line is gone; the outcome-form promise became "may be linked ... later"; "floor" is replaced by "at least" and "the longest the data follow anyone".

**Still present on that branch:**
- 0A The failing scrape and monitor jobs. The branch's `scrape.yml` has the same flags (no `--max-missing-share`, `--max-concurrency 4`) and the same `@v4`/`@v5` actions on `ubuntu-latest`.
- 0 The 1,141 missing Spring 2027 courses. `titles.json` only covers courses already in the index. ECON 121 still says "Check the spelling ...".
- 1.1, 1.2 Scraper term and coverage (not code, not fixable by a merge).
- 1.3 No calibration warning; "a course's own curve predicted better than its position alone" is still on every page.
- 2.1 The tail still reaches 100%. COMPSCI 61A at 40 shows "First day of class 100%" with only 407 of 611 cleared, and the course list still opens on six 100% rows. The "floor" label is gone from the table, so it now looks more certain than before.
- 2.3 "99% (95% interval 99% to 99%)" for MATH 54.
- 2.4 Cox Brier scores (not checked on the branch's reports).
- 2.7 `position=1000` still accepted from the URL; `abc` still becomes 1 with an empty box.
- 2.8 `course.html` still only reads `?c=`.
- 2.9, 2.11 Crossing tail curves; "Still waiting at the end: 0% (0)".
- 3.1 Mobile course table still shows bare `2.8 / 62 / 1` with no labels.
- 3.3, 3.4 Poor "Did you mean" / "Nearest" suggestions.
- 4 (banner) "Live Spring 2027 collection by this project begins with Phase 1 on Oct 26, 2026" now sits next to "has not started collecting", which contradicts it.
