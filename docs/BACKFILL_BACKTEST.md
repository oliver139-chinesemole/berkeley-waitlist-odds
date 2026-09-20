# Backfill Fall 2026 and backtest — instructions for Claude Code

Owner: Oliver Guo · Written: Sat Sept 19, 2026 · Goes with the `backfill-backtest` patch (`analysis/backfill.py`, `analysis/backtest.py`).

**Why.** The site is live and empty until mid-November. `docs/PHASE0.md` already found that Berkeleytime's `GetEnrollment` returns every section's 15-minute history since 2026-03-22, so Fall 2026 is a finished enrollment cycle that can be modelled today. That gives the site real numbers before Spring 2027 Phase 1 opens on Oct 26, and a real backtest: freeze the model, predict held-out waitlisters, compare with what happened.

**What this does not change.** The resume's collection claims (30-minute snapshots, gap-logged, zero cost) are about this project's own scraper and Spring 2027. Backfilled data is Berkeleytime's copy of the SIS feed. It is labelled `berkeleytime_history` everywhere and never counted toward a collection claim.

Work the steps in order through the build loop in `docs/FINISH_PLAN_WAITLIST.md` section 1.2. Every step ends in a check. B1 to B3 need a laptop: Berkeleytime's Cloudflare blocks GitHub's runners.

---

## B0. Apply the patch (5 minutes)

- [ ] `git checkout -b backfill-backtest && git am backfill-backtest.patch`
- [ ] Check: `python -m pytest -q` is green (about 310 tests). `tests/test_backfill.py` and `tests/test_backtest.py` are new.

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

- [ ] `make backfill-pilot` (300 sections, about 10 minutes, writes `backfill/2268/`).
- [ ] Read `backfill/2268/gap_report.csv`. The one recorded history in `data/fixtures/` (DATA C100) is dark from 2026-08-19 22:45Z to 2026-09-01 18:30Z, which covers the end of the adjustment period and the first week of instruction. **Decide from the pilot whether that hole hits every section.**
  - Dark for everyone (`share_time_in_gap` near 1 on Aug 20 to Sep 1): Fall 2026 can validate Phase 1 and Phase 2 clearing (what students need on Oct 26 and Nov 23) but says nothing about first-week clearing. Write that into the methodology page and the README in one sentence each. It is also the best argument for this project's own gap-logged collection; add it to the README novelty paragraph with the measured dates.
  - Scattered: proceed with no caveat beyond the gap report.
- [ ] Probe Spring 2026: `python -m analysis.backfill fetch --term "Spring 2026" --cache backfill/raw/2262 --limit 20`, then `build`. Check whether histories exist and where they start. If they cover Oct 2025 to Feb 2026, the cross-term backtest in B3 is available.
- [ ] Log the pilot in `docs/DATA_LOG.md` as a `decision` row (source, date, sections pulled).

## B2. Full pull (overnight)

- [ ] Oliver: email the Berkeleytime team (ASUC OCTO) before the full pull. Two sentences: what the project is, that you will make one pass of about 4,000 to 6,000 `GetEnrollment` requests at one per two seconds. They are also the likeliest sponsor for the SIS API request.
- [ ] `make backfill` (resumable; rerun until `failed` is 0 or stable). If Spring 2026 exists: `make backfill TERM=2262 TERM_NAME="Spring 2026"`.
- [ ] Check: `build` prints sections, `share_censored`, and the ten worst days. Record them in `docs/DATA_LOG.md`.

## B3. Analysis and backtest

- [ ] `make backfill-analysis` → `analysis/out/2268/report.md`, figures, `site/data/*.json` with `"data_source": "berkeleytime_history"`.
- [ ] `make backtest` (temporal split at the start of Phase 2, Jul 20; scored against the last waitlist run and against instruction start; plus grouped folds). Reports land in `reports/backtest_2268/`.
- [ ] If Spring 2026 exists, the real test: `python -m analysis.backtest --cohort analysis/out/2268/cohort_central.parquet --term-id 2268 --split cross_term --train-cohort analysis/out/2262/cohort_central.parquet --which deadline --out reports/backtest_2268/cross_term`. This is the claim the site makes in October: last cycle says something about this one.
- [ ] Read the reports with `data:validate-data`. What to look for:
  - Does `course` beat `bucket`? If the Brier gain interval includes zero, course-level cells add noise, and the site should show department-level estimates until it has more than one term.
  - Does `cox` beat `bucket`, and is it calibrated (predicted vs observed by decile)?
  - How bad is `site`? See B4.
  - `share_unknown` by phase. If the adjustment and instruction phases are mostly unknown, say so and do not publish numbers for them.
- [ ] Add CLAIMS.md rows with the exact commands and measured results. Never type a number you did not see.

## B4. Site fixes the backtest will demand (do before publishing any number)

1. **Horizon.** `analysis/export.py` evaluates each cell once, at the median `days_to_instruction` of its training rows, so a student asking two days before instruction gets the same number as one asking in Phase 1. On simulated data the literal site number predicted 0.92 against an actual 0.49 (Brier 0.43 vs 0.15 for the position-only baseline). Fix: export the curve out to the deadline and have `site/index.html` read it at the asker's own days remaining (today → deadline, from `meta.json` dates). Extend `tests/site/harness.js` to pin "today".
2. **Deadline.** Headline "cleared by the last automatic waitlist run"; keep "by the first day of instruction" as the second line. Most clearing happens after instruction starts.
3. **Positions.** Virtual positions are 1, 3, 5, 10, 20, 40: the `41+` bucket can never be filled and `6-15` rests on position 10 alone. Add 2, 7, 15, 30, 60, 100, or serve the Cox estimate for a continuous position.
4. **Uncertainty.** "n hypothetical joiners" counts correlated copies of the same section. Show the number of sections and a section-bootstrap interval.
5. **Source label.** When `meta.data_source` is `berkeleytime_history`, the status card reads "Fall 2026, from Berkeleytime's public history. Live Spring 2027 collection starts Oct 26." The no-data state goes away.
6. `analysis/survival.py::out_of_sample` drops rows censored before 14 days but keeps early clearings, which inflates the clearing rate. Replace it with `analysis.backtest.run_backtest(..., which="days:14")` (IPCW) and delete the old function.

Review with `design:ux-copy` (how a probability reads to a stressed student) and `design:accessibility-review`.

## B5. Use the backfill for Spring 2027

- [ ] Rebuild `config/priority_courses.txt` from data: rank Fall 2026 (and Spring 2026) courses by reconstructed waitlist joins, take the top ~900 sections' courses. Only 99 of 478 waitlisted Fall sections matched the hand-written list. Log the new `priority_sha` in the data log before Oct 26.
- [ ] Pre-register: once Fall 2026 numbers are on the site, the commit timestamp is the prediction date. In February, run the cross-term backtest Fall 2026 → Spring 2027 on this project's own snapshots. "Predictions committed before the outcomes existed" is the headline validation.

## B6. Repo hygiene (Oliver, 20 minutes)

- [ ] `CLAIMS.md` (status paragraph) and `docs/FINISH_PLAN_WAITLIST.md` (section 3, "Reality check") say in public that the resume claims a Spring 2026 cycle that was never captured. Fix the resume line, then delete both paragraphs.
- [ ] Add a LICENSE (MIT for code; note that `backfill/` data is Berkeleytime's and is not redistributed).
- [ ] `gh repo edit --homepage https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/`
- [ ] Add GoatCounter to both site pages before anything is shared. Visits cannot be backfilled either.
- [ ] Move session scaffolding (`HANDOFF.md`, `NEXT_SESSION.md`, `FINISH_PLAN_WAITLIST.md`, `superpowers/plans/`, this file) under `docs/dev/` and fix the links in `CLAUDE.md` and the README.

## Interview notes this work earns

- Why the unknown-outcome rows cannot simply be dropped (informative missingness; IPCW), with the toy example in `tests/test_backtest.py`.
- Why rows are resampled by section, not by row.
- Why section selection for the backfill ignores the current waitlist.
- What the backtest could not validate (first-week clearing, if the Berkeleytime hole is global) and how the Spring 2027 collection closes that.
