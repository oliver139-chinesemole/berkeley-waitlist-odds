# Handoff: Berkeley Waitlist Odds

Written 2026-09-19 23:20 UTC at the end of the first two working sessions; updated 2026-09-20 00:10 UTC by the third session (its changes are marked "session 3" below) and 2026-09-20 03:30 UTC by the fourth (the backfill and backtest section below). Read this first in a new session, then `CLAUDE.md` (the `Current step` line) and `docs/dev/FINISH_PLAN_WAITLIST.md` (the step checklist and tracker at the bottom).

## Where everything is

| Thing | Location |
| --- | --- |
| Repo (public) | https://github.com/oliver139-chinesemole/berkeley-waitlist-odds, local checkout at `/Users/oliverguo/berkeley-waitlist-odds` (`main`, about 53 commits, CI green, 295 tests in 22 files) |
| Live site | https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/ (lookup page, methodology page; shows a no-data state until Spring 2027 waitlists clear) |
| Data | `data` branch of the repo: `snapshots/date=YYYY-MM-DD/HHMM-{baseline,delta}.parquet`, `catalog/<term_id>/catalog.json`, `catalog/site.json`, `status.json`. Local clone at `./data-branch` (gitignored). 12 snapshots so far, all Fall 2026 test data. |
| Environment | `source .venv/bin/activate` (Python 3.12.5, pinned in requirements.txt). `gh` is logged in as oliver139-chinesemole; the `origin` remote uses the SSH alias `github-chinesemole`. |
| Plan and design docs | `docs/dev/FINISH_PLAN_WAITLIST.md` (roadmap), `docs/SPEC.md` (original spec), `docs/PHASE0.md` (data-route evidence), `docs/DESIGN_A2.md` (scraper contract, sections 11 to 15 override earlier ones), `docs/DESIGN_A4.md` (flows), `docs/DESIGN_A5.md` (survival analysis), `docs/DESIGN_A6.md` (site), `docs/ASSUMPTIONS.md` (the documented assumptions with validation numbers) |
| Operations | `docs/RUNBOOK.md` (go-live state, how a run works, what to do when it fails, Sunday check, site and weekly analysis), `docs/DATA_LOG.md` (every outage, switch and decision with UTC times; step A4 reads it as censoring rules), `CLAIMS.md` (every resume claim with its check command and the last measured result) |
| Memory | `~/.claude/projects/-Users-oliverguo/memory/project_berkeley_waitlist_odds.md` |

## What has been done (steps A0 to A6 of the plan)

**A0, dates and access.** Spring 2027 dates confirmed from the registrar's Google Calendar feed: Schedule of Classes publishes Oct 4, 2026; Phase 1 opens Mon Oct 26; Phase 2 Nov 23; adjustment period Jan 11, 2027; instruction Jan 19; last automatic waitlist run Feb 5; add/drop deadline Feb 10. The SIS Class API was requested and **denied: API Central does not grant access to students**. The `sis_api` adapter stays in the code in case a sponsor ever opens it.

**A1, data route (docs/PHASE0.md).** classes.berkeley.edu section pages embed the SIS enrollment JSON (enrolled, capacity, waitlisted, waitlist capacity, reserved seats) without login and are the primary source. Findings that shaped everything after:
- The site returns 403 to Python `requests` and `httpx` because they advertise ALPN `http/1.1` alone; the stdlib `urllib` client passes, from macOS and from GitHub's Linux runners. Do not switch clients and do not impersonate a browser.
- The site's robots.txt disallows `/search/`, so the listing is never crawled. Discovery uses the site's own `/rss.xml` (10 newest nodes with ids) and `/node/<id>` enumeration above a watermark kept in `catalog/site.json`. Spring 2027 pages will be found this way after Oct 4.
- Berkeleytime's public GraphQL gateway works from a laptop (cross-checks agreed 20 of 20) but is blocked by Cloudflare for GitHub's whole network. It is a local cross-check only (`probe/crosscheck_berkeleytime.py`).

**A2, scraper and storage.** `scraper/` package: pinned pyarrow schema, append-only Parquet per run (daily baseline plus change-only deltas with tombstones), rebuild of the full panel, gap report, three source adapters, polite HTTP client (1 request/s, retries with Retry-After, deadline-aware, bounded bodies). Priority list in `config/priority_courses.txt` (ordered by importance; about 917 sections every run) plus 12 rotating shards for the remaining live primary sections (about 3,660 in total), 1,380-second budget per run. Snapshot files store run metadata once in the footer with zstd (about 15 KB per delta); the data branch grows about 1 MB a day.

**A3, live operation.** GitHub Actions `scrape.yml` runs every 30 minutes. GitHub's cron fired only every 2 to 4 hours for this new repository, so the workflow keeps its own cadence: the last step of each run sleeps to the next :07/:37 slot and dispatches its successor with the built-in token (pushes made with that token never trigger workflows, but `workflow_dispatch` does). It stands down when another run is active or pending. `heartbeat.yml` restarts a dead chain; the chain dispatches `monitor.yml` once a day after 15:00 UTC; `monitor.yml` opens a "Scraper gap alert" issue when fewer than 40 runs land or a gap exceeds 90 minutes or the median missing share exceeds 0.5. Verified 2026-09-19: chain links at 20:07, 20:37, 21:07, 21:37, 22:07, 22:37 all on the slot. A restricted node (530942, HTTP 403) had pinned the discovery watermark for a few runs; fixed in the last commit; the watermark finishes catching up around 00:07 UTC on Sep 20, after which every run should observe its whole selection.

**A4, flow reconstruction (validated).** `analysis/flows.py` splits count changes between consecutive observations into admits, waitlist joins, waitlist drops, direct enrolments and enrolled drops with an `ambiguous` flag and censoring from the data log; `analysis/positions.py` gives time to clear for a virtual waitlister under optimistic, central and pessimistic drop scenarios. `analysis/synthetic.py` simulates real students; at 30-minute sampling the reconstruction recovers admits within 9%, joins within 4%, single-event intervals exactly, and the central time-to-clear has a 25-minute median error (docs/ASSUMPTIONS.md section 7). A labelled figure of this is in the README and on the methodology page.

**A5, survival analysis (code complete, no real data yet).** `analysis/calendar.py` (phases per term), `cohort.py` (virtual waitlisters with covariates), `survival.py` (Kaplan-Meier by position bucket, level, department and phase; log-rank; Cox PH with cluster-robust errors, PH test and stratified refit; sensitivity across scenarios; out-of-sample scoring on Phase 2 joins with concordance, Brier and decile calibration), `profile.py` (data-quality profile), `export.py` (site JSON with pooling below 30 cases), `figures.py`, `run.py`. `make analysis TERM=2272` reproduces everything from the data branch. On Fall 2026 test data the cohort has no clearing events, so the report says so; the pipeline is exercised end to end on simulated data in `tests/test_run.py`.

**A6, site (v1 live).** `site/index.html` and `site/methodology.html`, deployed by `pages.yml`. `analysis.yml` runs every Sunday 15:23 UTC (or on dispatch), commits `site/data/*.json` and `reports/` to `main`, and dispatches the redeploy. Verified end to end on 2026-09-19. Session 3: `tests/test_site.py` renders the page's own script under node with a stub document and a file-backed `fetch` (`tests/site/harness.js`; node comes from PATH or `~/.nvm/versions/node/*`, the tests skip without it) and checks the empty state, the counts from `meta.json`, the full state, a lookup, the pooled tag, the missing-course and missing-bucket messages and the `?course=&position=` link. Writing it exposed a live bug: `analysis/run.py` put the per-scenario cohort sizes under `meta["cohort_rows"]`, so the no-data state read "704 sections, [object Object] hypothetical joiners"; fixed (the dict is now `cohort_rows_by_scenario`) and `analysis.yml` was dispatched to regenerate the live JSON.

**Claims.** `CLAIMS.md` rows for the test suite, the cross-check, the public repo, the flow reconstruction, the analysis command and the site are measured. Session 3 re-measured the cadence rows at 23:48Z on Sep 19: 13 runs in the 24 h window (which still holds the cron-only morning), but every slot since the chain started at 19:41Z (8 runs, largest gap 30.1 min, share under 45 min 1.0). The 24 h window can first pass after 19:41Z on Sep 20; re-run rows 5 to 7 then. The `claims-audit` skill at `~/.claude/skills/claims-audit/` re-runs every row.

## Session 4 (2026-09-20, 01:00Z to 03:30Z): Fall 2026 backfill and the backtests

Branch `backfill-backtest` (docs/dev/BACKFILL_BACKTEST.md is the plan; its checkboxes carry what each step found). Summary:

- **Backfill** (`analysis/backfill.py`, `make backfill-pilot` / `make backfill`): Berkeleytime's `GetEnrollment` run-length history becomes the panel `interval_flows` reads; within-segment intervals are observed stillness, crossings wider than 180 min are that recorder's gaps and are censored; `gap_report.csv` per day; selection never reads today's counts and is a seeded permutation (a pilot is a prefix of the full pull); resumable gzip cache under `backfill/` (gitignored, Berkeleytime's data, labelled `berkeleytime_history`). The gateway rejects the second recorded `GetEnrollment` op; the recorded ops are tried in order.
- **Pilot pull** (296 sections): Berkeleytime was dark for every section from 2026-08-19 22:45Z to 2026-09-01 18:30Z (end of adjustment and first week of instruction), plus May 22, May 28 and Jul 18 to 19; its poll spacing at changes was 15 min from July but 45 to 130 min in March to June (hence the 180-min gap rule, not 45). Spring 2026 histories exist (20 of 20 probed, from Phase 1 start).
- **Backtest** (`analysis/backtest.py`, `make backtest`): temporal (training rows censored at the split), grouped-by-course and cross-term splits; bucket KM, pooled course KM, the literal site number and Cox scored at each row's own horizon with IPCW, weighted AUC, calibration and a section bootstrap. Observability rule: a row is scored only at horizons inside its `follow_up_days` window (a joiner who cleared before a gap is seen, one who did not is not, so no weighting recovers negatives); on Fall 2026 the deadline and instruction horizons are unobservable for every joiner before the hole, so the term is scored at 14- and 28-day horizons. Pilot results are in CLAIMS.md (Cox +0.037 over the bucket baseline within a regime; every Phase 1 model under-predicts Phase 2; course cells add nothing over buckets).
- **Cohort**: `joinable` rule (a queue exists or the section is full; 44% of the earlier test rows were impossible joiners), positions 1 to 100, numpy position walk identical to `time_to_clear` and more than 100 times faster, `follow_up_days` column. The whole suite now runs in about 70 s.
- **Site** (`site/index.html`, `analysis/export.py`): the curve is exported out to each cell's reach with a section-bootstrap band and section counts; the page reads it at the asker's own days left before the last automatic waitlist run (headline) and before instruction (second line), notes a floor past the reach, becomes a look-back after the deadline, labels the Berkeleytime source, and accepts `?today=` (the tests pin it). `p_clear_by_instruction` is the report's number only.
- **Calendar**: `SPRING_2026`; the last automatic run for terms without an explicit row is the last day to add without a fee (FA26 Sep 11, SP26 Feb 6), because Spring 2027's registrar row puts them on the same day.
- Docs: DESIGN_A5 (section 9), DESIGN_A6, methodology page, README, DATA_LOG (pilot decision row), CLAIMS (three rows).

## What is left

**Backfill, in order (docs/dev/BACKFILL_BACKTEST.md B2 to B6):**
1. **Oliver:** two-sentence note to the Berkeleytime team (ASUC OCTO) before the full pull: what the project is, one pass of about 3,600 `GetEnrollment` requests at one per two seconds. Then `make backfill` (Fall 2026, resumable, about 2 hours) and `make backfill TERM=2262 TERM_NAME="Spring 2026"`; both from a laptop.
2. `make backfill-analysis TERM=2268` (writes `site/data`, labelled `berkeleytime_history`), `make backtest TERM=2268`, and the cross-term run in B3 with the Spring 2026 cohort. Re-read the B3 questions on the full pull; re-measure the three CLAIMS rows; commit `site/data` and `reports/backtest_2268/`; dispatch `pages.yml`. The commit timestamp is the pre-registration date for the Spring 2027 cross-term test (B5).
3. B5: rebuild `config/priority_courses.txt` from reconstructed waitlist joins (top ~900 sections' courses) and log the new `priority_sha` before Oct 26. B6: fix the resume line, delete the two "Spring 2026" paragraphs (CLAIMS status, plan section 3), LICENSE, homepage, GoatCounter, move session scaffolding under `docs/dev/`.
4. A browser pass on the new page states (no browser in the sessions so far).

**Time-gated (nothing to build, just do on the date):**
1. **Sep 20 after 19:41 UTC, first check in a new session:** `git -C data-branch pull -q && python -m scraper.gaps --data-root ./data-branch --term-id 2268 --hours 24`. Expect about 48 runs, `share_gaps_le_45min` at or above 0.95, `median_missing_share` near 0 (node-id discovery finished with the 00:07Z run on Sep 20; the 00:37Z run observed all 1,287 selected sections, `n_missing` 0, in 1,341 s of the 1,380 s budget, so there is about 40 s of slack at one request per second: a bigger catalog or a slower site trims the shard tail first, never the priority list). If missing share stays around 0.14, the budget is short: a run selects about 917 priority plus about 240 shard sections at one request per second against a 1,380 s budget, so a bigger catalog or slower site trims the shard tail; see docs/RUNBOOK.md section 3. Then re-run the claims audit (rows 5 to 7). Issue #1 ("Scraper gap alert", opened by the 17:58Z monitor run on Sep 19) stays open until a monitor run passes; the chain dispatches the monitor after 15:00 UTC daily, so close it by hand on Sep 21 at the earliest (`gh issue close 1`).
2. **Oct 4 (Spring 2027 schedule publishes):** run RUNBOOK step 7: `gh variable set SCRAPE_TERM --body "Spring 2027"`, dispatch a forced baseline, confirm the pages report `data-term` 2272, add a `term_switch` row to docs/DATA_LOG.md. Discovery finds the new pages automatically over the following runs (about 6,000 nodes at 400 per run).
3. **Oct 12:** deadline for Spring collection to be running (it will be, if step 2 is done).
4. **Nov 9 onward (Phase 1 data exists):** first real `make analysis TERM=2272`, read `analysis/out/2272/report.md` and `profile.md`, write the two or three headline results in plain English into CLAIMS.md and the README, replace the simulated figure with `reports/figures_2272/hero.png`, check the site renders real estimates. Soft launch before Phase 2 (Nov 23) if the numbers hold up.
5. **Jan 2027 (Phase 2 closes):** refit, out-of-sample validation on Phase 2 joins, final numbers after Feb 10.
6. **Before mid-April 2027:** A7 ship (see below).

**Oliver's (cannot be done by the assistant):**
- Sunday two-minute check through Feb 14 (RUNBOOK section 4).
- Open the live site in a browser once and confirm the no-data state reads well (no browser was available in the sessions).
- Review `config/priority_courses.txt` before Oct 26: only 99 of 478 waitlisted Fall sections matched the original list; UGBA, MEC ENG and PHYSED were added; ENGLISH, MUSIC, PBHLTH and HISTORY are the next largest gaps. Any edit changes `priority_sha`; log it in the data log.
- Optional sponsored request for the SIS Class API (a professor or the ASUC OCTO Berkeleytime team).
- A7: the r/berkeley post, the resume bullets ("Spring 2027 enrollment cycle", real section and snapshot counts, one headline result), pinning the repo on the GitHub profile, the private interview-prep page, LinkedIn.
- The design-critique, accessibility and UX-copy reviews the plan names as skills were done by hand; a human pass on the site before the soft launch is still worth doing.

**Engineering that could still be done now (not required):**
- The plan's `superpowers`, `data`, `design` and `humanizer` skills are not installed in this environment; their disciplines were applied by hand. Installing them is section 0 of the plan.
- Done in session 3: the site render test (above). Measured and closed without a code change: `catalog.json` was rewritten on every run only because the stuck watermark (data log, 20:37Z row) re-probed the same 400 node ids each run and stamped 169 entries with a new `probed_at`; that cost about 7.7 KB (gzip) per run next to a 15.8 KB Parquet delta. Ordinary fetches do not touch the catalog (a live section's entry changes only when its id, status or node id changes), so after the catch-up the file changes only when something is learned.

## How to resume

```
cd /Users/oliverguo/berkeley-waitlist-odds && source .venv/bin/activate
git pull -q origin main
git -C data-branch pull -q || git clone -q --branch data --single-branch git@github-chinesemole:oliver139-chinesemole/berkeley-waitlist-odds.git data-branch
python -m pytest -q                                   # 320 tests, about 70 s; tests/test_site.py needs node (PATH or ~/.nvm)
python -m scraper.gaps --data-root ./data-branch --term-id 2268 --hours 24
gh run list -R oliver139-chinesemole/berkeley-waitlist-odds --workflow scrape.yml --limit 6
```

One more thing before resuming: on the evening of Sep 19 up to three Claude Code sessions were open on this same checkout (the second one found a commit it had not made; at 01:00Z on Sep 20 a third was writing an uncommitted backfill and backtest feature, `analysis/backfill.py` and `analysis/backtest.py`, which that session documents itself). Close other sessions before starting a new one, or at least run `git status` and `git log -3` first and never stage with `git add -A`.

## Decisions worth knowing before changing anything

- Only `scrape.yml` writes the `data` branch; only `analysis.yml` commits to `main` (site data and reports). Never commit to `data` by hand.
- Workflows dispatch each other with the built-in token on purpose; a push made by a workflow does not trigger other workflows.
- Flows are lower bounds; an enrolment gain with a non-empty waitlist counts as admits (FIFO); intervals overlapping a logged outage are censored; a `source_switch` or `schema` row in the data log is a point event, an `outage` row is a span.
- The site never shows simulated numbers; the validation figure is labelled as simulated everywhere it appears.
- Berkeley's registrar runs the last automatic waitlist process on Feb 5, 2027; nothing after it counts as queue movement.
