# Berkeley Waitlist Odds: where the project stands and what is left

Written 2026-09-20 03:55 UTC (session 4); site v3 rows added 2026-09-20 20:30 UTC (session 5, worktree `berkeley-waitlist-odds-site`, branch `site-v3`). Give this file to a Claude Code session, or read it yourself, to know the stage, what is still to build, what only Oliver can do, and what happens on which date. It is a snapshot; `docs/dev/HANDOFF.md` carries the detail, `docs/dev/BACKFILL_BACKTEST.md` the backfill plan with findings, `CLAIMS.md` the measured numbers, `CLAUDE.md` the current-step line.

## 1. In one paragraph

The scraper is live (30-minute snapshots of Fall 2026 as the test term, self-dispatching chain on GitHub Actions, data on the `data` branch). The whole analysis pipeline exists and has been exercised on real data: flows, virtual waitlisters, Kaplan-Meier, Cox, an IPCW backtest, precomputed site JSON, and a lookup page (v2) that reads the clearing curve at the asker's own days left. Because Spring 2027 collection cannot start before Oct 26, the site is being fed from the finished Fall 2026 cycle as recorded in Berkeleytime's public history: a 296-section pilot is analysed and backtested, and the full pull of every eligible Fall 2026 and Spring 2026 section is running right now. What remains is mostly operating and publishing, not building: install the full-pull outputs, install the data-driven priority list before Oct 26, switch the term on Oct 4, run the first own-data analysis in November, and Oliver's own launch items (resume, post, browser pass).

## 2. Stage map

| Step | What | Status |
| --- | --- | --- |
| A0 dates and access | Registrar dates, API Central request | Done. SIS API denied to students; classes.berkeley.edu is primary. |
| A1 data route | Probe sources, cross-check | Done (`docs/PHASE0.md`; 20 of 20 cross-checks agree). |
| A2 scraper and storage | Schema, Parquet per run, rebuild, gaps, 3 sources, workflows | Done (295+ tests then; 322 now). |
| A3 go live and monitor | Chain, heartbeat, monitor, data log | **Running.** Chain on every :07/:37 slot since 19:41Z Sep 19. Open: 24 h cadence check after 19:41Z Sep 20; close issue #1 after a passing monitor run (Sep 21 earliest); Oliver's Sunday check. |
| A4 flow reconstruction | Flows, position model, ASSUMPTIONS, synthetic validation | Done. |
| A5 survival analysis | Calendar, cohort, KM, Cox, PH check, sensitivity, out of sample, `make analysis` | Code done and run on the Fall 2026 pilot. Open: "two or three headline results in plain English" once the full pull is analysed. |
| A6 publish | Site, methodology, README | Site v2 live. **Site v3 built** on branch `site-v3` (session 5; docs/dev/SITE_V3_PLAN.md section 13): Lookup, Courses, course page, Insights, Accuracy, Methods, About, 404; shared assets; split JSON (`index.json`, `courses/<SUBJECT>.json`, `pooled.json`, `insights.json`, `backtest.json`); `live/latest.json` writer in `scrape.yml`; Playwright smoke in CI; 353 tests. Open: land it after item 1 (rebase, `make site-data` with the install commit's hash, merge, `pages.yml`); README hero plot; GoatCounter; Oliver's browser pass. |
| A7 ship | Resume, r/berkeley post, LinkedIn | Oliver's; not started. |
| B0 backfill patch | `analysis/backfill.py`, `analysis/backtest.py`, cohort fix | Done (PR #2, merged as 4711e1c). |
| B1 pilot and gap question | 300 sections, gap report, Spring 2026 probe | Done. Berkeleytime dark for every section Aug 19 22:45Z to Sep 1 18:30Z; gap rule 180 min; Spring 2026 histories exist. |
| B2 full pull | Fall 2026 and Spring 2026, every eligible section | **Running** (started 02:44Z Sep 20, about 4 h; Oliver chose to start it and send the Berkeleytime note in parallel). |
| B3 analysis and backtest | Reports, cross-term test, CLAIMS rows | Pilot done; full-pull versions run automatically at the end of B2; review and commit still to do. |
| B4 site fixes | Horizon, deadline headline, positions, uncertainty, source label, IPCW out of sample | Done (PR #2). |
| B5 priority list from data | Rank courses by reconstructed joins | Tool done (`analysis/priority_from_flows.py`); install from the full pull before Oct 26. |
| B6 repo hygiene | LICENSE, homepage, docs/dev, GoatCounter, resume paragraphs | LICENSE, homepage, docs/dev done. Open: GoatCounter (needs Oliver's account); the two "resume says Spring 2026" paragraphs come out after Oliver fixes the resume line. |

## 3. Running right now (2026-09-20 03:55Z)

A detached script (`full_pull.sh`, log in the session scratchpad) is doing, in order: Fall 2026 fetch (2,225 of about 3,640 sections cached at 03:55Z), Fall build, Fall analysis into `analysis/out/2268` and `site/data`, `make backtest TERM=2268` into `reports/backtest_2268/`, Spring 2026 fetch, Spring build, Spring analysis into `analysis/out/2262`, and three cross-term backtests (fit on Spring 2026, score Fall 2026) at 14 days, 28 days and the deadline. Branch `backfill-full` (draft PR #3) holds the hygiene commits and will receive the outputs. `main` is at 4711e1c.

Peer sessions: two other Claude Code sessions were open on the same checkout on Sep 19 and 20. Run `ListAgents` and `git log -3` first, and tell an open peer before switching branches.

## 4. Still to implement or run (in order)

(2026-09-20 18:23Z: session oliverguo-29 killed and restarted the full-pull chain with a Cox speed fix after the laptop slept overnight; that session owns item 1. Session 5 built site v3 in parallel in a separate worktree; item 1b is its landing.)

1. **Install the full-pull results** (when the chain prints `=== done`): read `analysis/out/2268/report.md` and `reports/backtest_2268/*/report.md`; answer the B3 questions in `docs/dev/BACKFILL_BACKTEST.md` on the full data (does `course` beat `bucket`; is Cox calibrated within a regime; coverage by phase); re-measure the three backfill rows in `CLAIMS.md` with the printed numbers; copy `analysis/out/2268/report.md` to `reports/report_2268_berkeleytime.md` and the figures to `reports/figures_2268_berkeleytime/`; commit `site/data`, `reports/`, add a `decision` row to `docs/DATA_LOG.md` (sections, segments, gap share, commit hash); merge PR #3; `gh workflow run pages.yml`; check the live page shows "from Berkeleytime's public 15-minute enrollment history". The merge commit's timestamp is the pre-registration date for the Spring 2027 cross-term test.
1b. **Land site v3** (branch `site-v3`, draft PR; docs/DESIGN_A6.md is the contract): after the install commit, rebase the branch on `main`, run `make site-data` from the installed cohort with `--prereg-commit <install sha> --prereg-date <date>` (see docs/RUNBOOK.md section 5) and `python -m analysis.export_backtest --reports reports/backtest_2268 --term-id 2268 --term-name "Fall 2026" --out site/data/backtest.json --data-source berkeleytime_history`, commit `site/data` (the old `courses.json` goes away), merge, `gh workflow run pages.yml`, then curl every page for 200 and download the `site-smoke` artifact to see the pages. Copy the printed course count into CLAIMS.md.
2. **Headline results in plain English** (A5's last box; the Insights page already composes them from `insights.json`, so the CLAIMS sentences must use the same numbers): two or three sentences with numbers from the full report (median days to clear by bucket, share cleared within 14 days, the Cox position effect), into `CLAIMS.md` "Rows to add later", the README status, and the site's methodology page if useful. Never a number that was not printed by a command.
3. **README hero plot**: replace the simulated figure with `reports/figures_2268_berkeleytime/hero.png` (lower-division Phase 1 joiners by bucket) and relabel the caption as Berkeleytime history, not simulation.
4. **B5, before Oct 26**: `python -m analysis.priority_from_flows --flows backfill/2268/flows.parquet backfill/2262/flows.parquet --identity backfill/2268/identity.parquet backfill/2262/identity.parquet --top-sections 900`; review the candidate (courses of the 900 most-joined sections, ordered by joins) against the budget (a run fetches about 917 priority pages plus a shard in 1,380 s); install it as `config/priority_courses.txt`; add a `priority_list` row to `docs/DATA_LOG.md` with the new `priority_sha` (printed in the next run's metadata) and the coverage numbers the tool prints.
5. **Oct 4 term switch** (`docs/RUNBOOK.md` step 7): `gh variable set SCRAPE_TERM --body "Spring 2027"`, dispatch a forced baseline, confirm `data-term` 2272 in the pages, add a `term_switch` row. Discovery finds the new pages over the following runs. Deadline for Spring collection to be running: Oct 12.
6. **Nov 9 onward**: first `make analysis TERM=2272` on own data. The weekly `analysis.yml` replaces `site/data` on its own once the own-data cohort has 10 clearings; until then it keeps the backfill. Watch `reports/report_2272.md` weekly.
7. **Jan to Feb 2027**: refit after Phase 2 closes; the real cross-term backtest, Fall 2026 (frozen, pre-registered) against Spring 2027; final numbers after Feb 10.
8. **Optional model work the pilot suggested** (not required for the claims): the Cox model extrapolates badly across the Phase 1 to Phase 2 shift because `days_to_instruction` is linear and the phase dummies are absent from a Phase 1 fit (consider a spline or phase-specific baselines); with per-course cells adding nothing over buckets in the pilot, the site could pool to department by default until two cycles exist; the position model never clears a "tail" joiner in an empty queue when a seat opens (a documented limitation of aggregate counts).

## 5. Only Oliver can do these

- Send the two-sentence note to the Berkeleytime team (ASUC OCTO); the pull is already running with a User-Agent that carries your email.
- Open the live page in a real browser (phone and laptop, light and dark) once the backfilled JSON is published; the sessions had no browser. Check the headline sentence, the floor note, the look-back state (`?today=2026-09-15`), and the pooled tag.
- Create a GoatCounter site and add its script tag to every page under `site/` (eight pages; one line each, before `</body>`) before anything is shared; visits cannot be backfilled. Counting each lookup by course (plan decision 4) is a one-line `window.goatcounter.count` call in `index.html`'s submit handler once the tag exists.
- Fix the resume line to "Spring 2027 enrollment cycle", then delete the two paragraphs that mention it (`CLAIMS.md` status paragraph, `docs/dev/FINISH_PLAN_WAITLIST.md` section 3).
- Sunday two-minute check through Feb 14 (`docs/RUNBOOK.md` section 4). Billing page shows $0 (CLAIMS row).
- A7: the r/berkeley post (soft launch before Nov 23 if the numbers hold; main launch two weeks before Fall 2027 Phase 1), resume bullets from `CLAIMS.md`, pin the repo, LinkedIn, the private interview page (why IPCW; why resample by section; why selection ignores today's waitlist; what Fall 2026 could not validate).

## 6. Dates that drive everything

| Date | What |
| --- | --- |
| Sep 20, after 19:41 UTC | First 24 h window fully on the chain: `python -m scraper.gaps --data-root ./data-branch --term-id 2268 --hours 24` should show about 48 runs and `share_gaps_le_45min` at or above 0.95; re-run CLAIMS rows 5 to 7. |
| Sep 21 or later | Close issue #1 after a monitor run passes (`gh issue close 1`). |
| Oct 4 | Spring 2027 schedule publishes: term switch (item 5 above). |
| Oct 12 | Drop-dead: Spring 2027 collection must be running. |
| Oct 26 | Phase 1 opens. Priority list (item 4) must be installed before this. |
| Nov 9 to 22 | First own-data analysis; soft launch if it holds. |
| Nov 23 | Phase 2 opens. |
| Jan 11 / Jan 19 / Feb 5 / Feb 10, 2027 | Adjustment period; instruction; last automatic waitlist run; add/drop deadline (freeze). |

## 7. Facts a new session must not rediscover

- classes.berkeley.edu: stdlib `urllib` only (the site rejects `requests`/`httpx` TLS handshakes); never request `/search/`; discovery by `/rss.xml` and `/node/<id>`. Berkeleytime is Cloudflare-403 from GitHub runners: the backfill runs from a laptop only.
- Berkeleytime `GetEnrollment` returns run-length history with real SIS `sectionId`; the gateway rejects the second recorded op (schema dropped `seatReservationTypes`), the first works; one request per 2 s. Poll spacing at changes was 15 min from July 2026 but 45 to 130 min in March to June, hence the 180-minute gap rule. Every section was dark Aug 19 22:45Z to Sep 1 18:30Z: Fall 2026 validates Phase 1 and Phase 2 clearing only; the backtest scores only observable horizons (14 and 28 days).
- Only `scrape.yml` writes the `data` branch; only `analysis.yml` commits to `main` on its own; workflows dispatch each other with the built-in token. Data gaps are permanent and logged in `docs/DATA_LOG.md` (rows are never edited; corrections are new rows).
- `backfill/` is gitignored Berkeleytime data, labelled `berkeleytime_history`, never a collection claim. The resume's collection claims are about Spring 2027 only.
- Tests: `python -m pytest` (addopts already has `-q`; a second `-q` hides the summary line), 322 tests in about 60 s; `tests/test_site.py` needs node (`~/.nvm/versions/node/*/bin/node`).
- `CLAIMS.md` numbers are copied from command output, never typed.
- Site v3 (session 5) lives in a second checkout, `/Users/oliverguo/berkeley-waitlist-odds-site` (git worktree, branch `site-v3`), so the main checkout can stay on whatever branch the pull owner needs. The pages compute nothing: `analysis/export.py` writes `index.json` (search, tables), `courses/<SUBJECT>.json` (curves on demand; pooled cells are pointers), `pooled.json` (department, level, all), `insights.json`, `meta.json` (with a forecast term whose dates the pages count down to); `analysis/export_backtest.py` writes `backtest.json`; `make site-data` rewrites them from a saved cohort in two minutes. `tests/test_site.py` renders every page under node; `tests/site/smoke.mjs` screenshots them in Chromium (locally with `NODE_PATH=/Users/oliverguo/paddleiq/node_modules`, which has Playwright 1.62.1 and axe-core; in CI through `site-smoke.yml`). `scrape.yml` now also writes `live/latest.json` to the data branch (about 1,050 active sections, 97 KB) in a `continue-on-error` step.

## 8. How to resume

```
cd /Users/oliverguo/berkeley-waitlist-odds && source .venv/bin/activate
git status && git log -3 --oneline && git branch --show-current     # expect backfill-full (or main after PR #3 merges)
git -C data-branch pull -q
python -m pytest                                                     # 322 passed
gh run list --workflow scrape.yml --limit 4                          # chain alive?
grep -E "^=== |^exit " <scratchpad>/full_pull.log | tail            # if the pull is still running; else see backfill/2268/meta.json
```

Prompt to paste into a new Claude Code session:

```
Continue the Berkeley Waitlist Odds project at /Users/oliverguo/berkeley-waitlist-odds. Read docs/dev/STATUS.md
first (stage, what is left, dates), then docs/dev/HANDOFF.md, docs/dev/SITE_V3_PLAN.md section 13 and the Current step
line in CLAUDE.md. Run ListAgents
and git log -3 before editing (other sessions may be open on this checkout). Do the first open item in STATUS.md
section 4 that is due, through the build loop in docs/dev/FINISH_PLAN_WAITLIST.md section 1.2. Rules: never commit
to the data branch by hand; only analysis.yml commits to main on its own; every number in CLAIMS.md is copied from
command output; backfilled Berkeleytime data is labelled berkeleytime_history and never a collection claim; the site
never shows simulated numbers.
```
