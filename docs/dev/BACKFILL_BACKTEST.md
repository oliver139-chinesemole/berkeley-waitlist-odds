# Backfill Fall 2026 and backtest — instructions for Claude Code

Owner: Oliver Guo · Written: Sat Sept 19, 2026 · Goes with the `backfill-backtest` patch (`analysis/backfill.py`, `analysis/backtest.py`).

**Why.** The site is live and empty until mid-November. `docs/PHASE0.md` already found that Berkeleytime's `GetEnrollment` returns every section's 15-minute history since 2026-03-22, so Fall 2026 is a finished enrollment cycle that can be modelled today. That gives the site real numbers before Spring 2027 Phase 1 opens on Oct 26, and a real backtest: freeze the model, predict held-out waitlisters, compare with what happened.

**What this does not change.** The resume's collection claims (30-minute snapshots, gap-logged, zero cost) are about this project's own scraper and Spring 2027. Backfilled data is Berkeleytime's copy of the SIS feed. It is labelled `berkeleytime_history` everywhere and never counted toward a collection claim.

Work the steps in order through the build loop in `docs/dev/FINISH_PLAN_WAITLIST.md` section 1.2. Every step ends in a check. B1 to B3 need a laptop: Berkeleytime's Cloudflare blocks GitHub's runners.

---

## B0. Apply the patch (5 minutes)

- [x] `git checkout -b backfill-backtest` (2026-09-20; the patch did not exist as a file, so the modules were written in the session: commits f6848f7, 78a2e49 and the observability commit that follows them)
- [x] Check: `python -m pytest -q` is green: 320 tests in about 70 s (was 295 in 181 s; the cohort walk is now numpy). `tests/test_backfill.py` and `tests/test_backtest.py` are new.

What the patch contains:

| File | Change |
| --- | --- |
| `analysis/cohort.py` | Bug fix. Virtual waitlisters were placed at position 1 in sections with open seats and no queue (879 of 1,998 rows, 44%, on the data branch on Sep 19). Nobody waits there and those rows can never clear, so they would have pulled the 1–5 bucket toward zero. New `joinable()` rule: a queue exists, or the section is full. |
| `analysis/backfill.py` | Berkeleytime run-length history → the panel `interval_flows` reads. A long interval inside a segment is observed stillness (not censored); a between-segment crossing wider than 45 minutes is a Berkeleytime gap (censored). `gap_report` gives the share of section-time dark per day. `fetch` is resumable, one request every 2 s, gzip cache. Section selection never looks at today's waitlist (that would keep exactly the sections that failed to clear). |
| `analysis/backtest.py` | Temporal, grouped-by-course and cross-term splits. Scores four predictors at each test row's own horizon: position-bucket KM (baseline), course × bucket KM with the site's pooling, the literal site number, Cox. IPCW-weighted Brier, AUC, calibration; Brier gain over the baseline with a section-level bootstrap interval. |
| `analysis/run.py` | `--backfill-dir` runs the whole analysis on a backfilled term; `run_analysis(flows=..., site_meta=...)`. |
| `analysis/calendar.py` | `SPRING_2026` (term 2262) from the registrar ICS fixture. |
| `Makefile` | `backfill-pilot`, `backfill`, `backfill-analysis`, `backtest`. |

## B1. Pilot pull and the gap question (30 minutes)

- [x] `make backfill-pilot` (2026-09-20 01:34Z to 01:45Z; 300 selected, 296 histories, 20,266 segments, 37,978 panel rows; `backfill/2268/`). Also found: the gateway rejects the second recorded `GetEnrollment` op (schema dropped `seatReservationTypes`); `fetch` now tries the recorded ops in order.
- [x] Read `backfill/2268/gap_report.csv`. **Dark for everyone.** The one recorded history in `data/fixtures/` (DATA C100) is dark from 2026-08-19 22:45Z to 2026-09-01 18:30Z, which covers the end of the adjustment period and the first week of instruction. **Decide from the pilot whether that hole hits every section.**
  - Dark for everyone (`share_time_in_gap` near 1 on Aug 20 to Sep 1): Fall 2026 can validate Phase 1 and Phase 2 clearing (what students need on Oct 26 and Nov 23) but says nothing about first-week clearing. Write that into the methodology page and the README in one sentence each. It is also the best argument for this project's own gap-logged collection; add it to the README novelty paragraph with the measured dates.
  - Scattered: proceed with no caveat beyond the gap report.
- [x] Probe Spring 2026 (20 of 20 histories, 2025-10-27 to 2026-05-16, 3 of 202 days above 0.5 dark; cross-term available after the full Spring pull): `python -m analysis.backfill fetch --term "Spring 2026" --cache backfill/raw/2262 --limit 20`, then `build`. Check whether histories exist and where they start. If they cover Oct 2025 to Feb 2026, the cross-term backtest in B3 is available.
- [x] Logged in `docs/DATA_LOG.md` (row 2026-09-20T01:32Z). Two more findings from the pilot: Berkeleytime's poll spacing at changes was 15 min from July 2026 but 45 to 130 min from March to June, so the gap rule is 180 min, not 45 (a 45-min rule censored ordinary polls exactly where queues moved); and the hole makes the deadline and instruction horizons unobservable for every joiner before Aug 19 (a joiner who cleared before the hole is seen, one who did not is not, so no reweighting recovers the negatives): the backtest now excludes rows it cannot follow to their horizon and reports coverage by phase, and Fall 2026 is scored at fixed 14- and 28-day horizons.

## B2. Full pull (overnight)

- [ ] **Oliver: email the Berkeleytime team (ASUC OCTO) before the full pull.** Not done as of 2026-09-20; the full pull waits for it. Two sentences: what the project is, that you will make one pass of about 4,000 to 6,000 `GetEnrollment` requests at one per two seconds. They are also the likeliest sponsor for the SIS API request.
- [x] `make backfill` (Fall 2026: started 2026-09-20 02:44Z, fetch done 09:42Z with the laptop asleep for part of the night, 6,074 selected, 6,016 histories, 58 "no history" failures, stable on rerun). Spring 2026 pull started 19:29Z the same day. Note: Berkeleytime's `GetCatalog` for Fall 2026 has no MATH 1A or MATH 1B entries at all, so those courses cannot be backfilled.
- [x] Check: `build` on the full pull: 6,016 sections, 402,573 segments, 753,891 panel rows, 747,875 intervals, share censored 0.0721; 53,925 of 396,557 crossings wider than 180 min; worst days Aug 20 to 31 (share 1.0, all 5,975 covered sections), May 22, Jul 18 to 19, May 28. Recorded in `docs/DATA_LOG.md`.

## B3. Analysis and backtest

- [x] `make backfill-analysis` on the pilot (site JSON written to a scratch dir, not `site/data`, until the full pull): 21,831 virtual waitlisters per scenario, 9,933 clearings; KM median time to clear 6.4 days at positions 1 to 5, 26 days at 6 to 15; Cox hazard ratio 0.60 per log unit of position; PH violated for position and phase (stratified refit written).
- [x] `make backtest` on the pilot (reports in a scratch dir until the full pull). Grouped by course, 14 days: Cox Brier gain over the bucket baseline +0.037 [+0.024, +0.053], course cells identical to buckets, site −0.015 [−0.028, +0.000]. Temporal at Jul 20, 14 days (2,938 scored rows, 9,739 unobservable): course −0.014 [−0.064, +0.035], site +0.029 [−0.034, +0.082], Cox −0.196 [−0.227, −0.150] with predictions of 2 to 34% against observed 54 to 77%: a model fit on Phase 1 does not know Phase 2 clears faster. Deadline horizon: only the 2,406 joiners after Sep 1 are observable. 28-day and instruction horizons: nothing observable.
- [x] Done 2026-09-20 23:47Z to 00:09Z on the full Spring 2026 pull (6,131 sections, 531,568 virtual waitlisters, 299,826 clearings; `reports/backtest_2268/cross_term_*`). Fit on Spring 2026, scored on Fall 2026: at 14 days course +0.0095 [+0.0035, +0.0162] over bucket, dept +0.0051 [+0.0010, +0.0086], site (v1) -0.0437, Cox -0.0153 (AUC 0.725, miscalibrated); at 28 days course +0.0246 [+0.0166, +0.0324], dept +0.0095 [+0.0046, +0.0145]; at the deadline (instruction-phase joiners) course +0.0191 [+0.0119, +0.0274], dept +0.0119 [+0.0069, +0.0175], Cox -0.0901. **Decision reversed:** the site serves course-level curves again (`DEFAULT_LEVEL = "course"`), because the test that matches the page's use says course identity transfers across cycles; the within-term temporal verdict was the Phase 1 to Phase 2 speed-up. If Spring 2026 exists, the real test: `python -m analysis.backtest --cohort analysis/out/2268/cohort_central.parquet --term-id 2268 --split cross_term --train-cohort analysis/out/2262/cohort_central.parquet --which deadline --out reports/backtest_2268/cross_term`. This is the claim the site makes in October: last cycle says something about this one.
- [x] Read the reports (by hand; the `data` plugin is not installed). Answers on the full pull (6,016 sections, 493,364 virtual waitlisters, 220,196 clearings; the pilot answers below them were the same in direction):
  - Does `course` beat `bucket`? No. Full pull, temporal at Jul 20, 14 days (63,743 scored rows): course Brier 0.3139 vs bucket 0.2911, gain -0.0229 [-0.0340, -0.0111]; grouped by course, 14 days (183,335 rows): +0.0027 [-0.0000, +0.0053]. Decision taken: the site serves department-level curves (`export_site_tables(level="dept")`, commit a762e14) until a second cycle exists; the course's own counts stay visible. Caveat the same run adds: across the Phase 1 to Phase 2 shift the department curve is itself slightly worse than the bucket alone (temporal 14 days: dept 0.3081 vs bucket 0.2911, gain -0.0174 [-0.0252, -0.0102]); within a regime it adds a little (grouped +0.0027 [-0.0000, +0.0053]). The Spring 2026 to Fall 2026 cross-term run then showed both course and department curves transfer across terms (course +0.0095, dept +0.0051 over bucket at 14 days, intervals clear of zero), so the level went back to course the same night (see B3's cross-term row). (Pilot: interval included zero.)
  - Does `cox` beat `bucket`, and is it calibrated? Within a regime yes: grouped 14 days +0.0339 [+0.0299, +0.0375] (Brier 0.2026 vs 0.2365, AUC 0.753 vs 0.602). Across the Phase 1 to Phase 2 split no: temporal 14 days -0.2896 [-0.3007, -0.2803], predicted 1 to 25% by decile against observed 52 to 76% (`days_to_instruction` and the phase dummies extrapolate; PH fails for every family, stratified refit written). The site keeps serving KM curves; Cox is a report, not a product. (Pilot: +0.037 / -0.196.)
  - How bad is `site` (the v1 rule)? Not worse than bucket in these tests (temporal 14 days +0.0127 [-0.0006, +0.0237]; deadline, instruction-phase joiners only, +0.0234 [+0.0059, +0.0399]): the horizon mismatch over-predicts and the regime shift makes over-prediction land closer. Across held-out courses it is worse (-0.0153 [-0.0178, -0.0120]). The B4.1 fix removes the mismatch regardless; the page now reads the department curve at the asker's own horizon.
  - Coverage by phase (the replacement for `share_unknown`): at 14 days, phase 1 62%, phase 2 16%, instruction 53%, adjustment 0%, after 0%; at 28 days and at the instruction horizon nothing is observable, at the deadline horizon only the 52,227 instruction-phase joiners after Sep 1. Fall 2026 numbers for the adjustment period are not publishable; the site's floor note handles horizons past a cell's reach.
- [x] CLAIMS.md rows added (pilot results, marked as such; re-measure after the full pull).

## B4. Site fixes the backtest will demand (do before publishing any number) — done 2026-09-20 (commit 78a2e49); a browser pass is still due

1. **Horizon.** `analysis/export.py` evaluates each cell once, at the median `days_to_instruction` of its training rows, so a student asking two days before instruction gets the same number as one asking in Phase 1. On simulated data the literal site number predicted 0.92 against an actual 0.49 (Brier 0.43 vs 0.15 for the position-only baseline). Fix: export the curve out to the deadline and have `site/index.html` read it at the asker's own days remaining (today → deadline, from `meta.json` dates). Extend `tests/site/harness.js` to pin "today".
2. **Deadline.** Headline "cleared by the last automatic waitlist run"; keep "by the first day of instruction" as the second line. Most clearing happens after instruction starts.
3. **Positions.** Virtual positions are 1, 3, 5, 10, 20, 40: the `41+` bucket can never be filled and `6-15` rests on position 10 alone. Add 2, 7, 15, 30, 60, 100, or serve the Cox estimate for a continuous position.
4. **Uncertainty.** "n hypothetical joiners" counts correlated copies of the same section. Show the number of sections and a section-bootstrap interval.
5. **Source label.** When `meta.data_source` is `berkeleytime_history`, the status card reads "Fall 2026, from Berkeleytime's public history. Live Spring 2027 collection starts Oct 26." The no-data state goes away.
6. `analysis/survival.py::out_of_sample` drops rows censored before 14 days but keeps early clearings, which inflates the clearing rate. Replace it with `analysis.backtest.run_backtest(..., which="days:14")` (IPCW) and delete the old function.

Review with `design:ux-copy` (how a probability reads to a stressed student) and `design:accessibility-review`. Neither plugin is installed; the copy was reviewed by hand and `tests/test_site.py` renders every state under node. Still open for a human: a pass in a real browser.

## B5. Use the backfill for Spring 2027

- [ ] Rebuild `config/priority_courses.txt` from data: rank Fall 2026 (and Spring 2026) courses by reconstructed waitlist joins, take the top ~900 sections' courses. Only 99 of 478 waitlisted Fall sections matched the hand-written list. Log the new `priority_sha` in the data log before Oct 26.
- [ ] Pre-register: once Fall 2026 numbers are on the site, the commit timestamp is the prediction date. In February, run the cross-term backtest Fall 2026 → Spring 2027 on this project's own snapshots. "Predictions committed before the outcomes existed" is the headline validation.

## B6. Repo hygiene (Oliver, 20 minutes)

- [ ] `CLAIMS.md` (status paragraph) and `docs/dev/FINISH_PLAN_WAITLIST.md` (section 3, "Reality check") say in public that the resume claims a Spring 2026 cycle that was never captured. Fix the resume line, then delete both paragraphs.
- [x] LICENSE added (MIT, with a scope note that `backfill/` data is Berkeleytime's and is not redistributed).
- [x] `gh repo edit --homepage https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/` (done 2026-09-20)
- [ ] Add GoatCounter to both site pages before anything is shared. Visits cannot be backfilled either.
- [x] Moved session scaffolding (`HANDOFF.md`, `NEXT_SESSION.md`, `FINISH_PLAN_WAITLIST.md`, `plans/`, this file) under `docs/dev/` and fixed the links in `CLAUDE.md`, the README and the design docs (2026-09-20). Data-log rows keep their historical paths.

## Interview notes this work earns

- Why the unknown-outcome rows cannot simply be dropped (informative missingness; IPCW), with the toy example in `tests/test_backtest.py`.
- Why rows are resampled by section, not by row.
- Why section selection for the backfill ignores the current waitlist.
- What the backtest could not validate (first-week clearing, if the Berkeleytime hole is global) and how the Spring 2027 collection closes that.
