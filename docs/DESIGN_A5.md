# A5 design contract — survival analysis

Binding interfaces for step A5 (docs/dev/FINISH_PLAN_WAITLIST.md A5; docs/SPEC.md section 6). Input: the flows table from `analysis.flows.interval_flows` and section identity from `analysis.panel`, or the same two tables from a backfilled term (section 9). Output: Kaplan-Meier curves, a Cox proportional-hazards fit with its assumption check, sensitivity across drop scenarios, an out-of-sample check, and the precomputed lookup tables the site (A6) reads. One command reproduces everything from the raw Parquet.

## 1. Unit of analysis (`analysis/cohort.py`)

A virtual waitlister is `(section_id, join_time, position)`: join times are the observed interval starts thinned to one every `join_every_min` minutes per section (default 240; every observed run would give tens of millions of correlated rows), positions are `DEFAULT_POSITIONS = (1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 60, 100)` (at least two per bucket; 60 and 100 so the `41+` bucket can be filled), kept only where the position is a real place in the queue (`waitlist0 >= position - 1`). A join time counts only where a waitlist could be joined (`joinable`): a queue exists, or the section is full (no unreserved seat open). Nobody waits behind an open seat; before this rule 44% of the Fall 2026 test rows were position-1 joiners in open sections that could never clear. Each row carries:

| column | meaning |
| --- | --- |
| `duration_min`, `event` | from the position model; `duration_days = duration_min / 1440` |
| `follow_up_days` | how long the joiner could have been followed whatever happened: to the first censored interval after the join, or the end of the section's data |
| `position`, `position_bucket` | `1-5`, `6-15`, `16-40`, `41+` |
| `log_position` | natural log of position |
| `waitlist0`, `capacity0`, `wl_ratio` | waitlist length and capacity at join; `wl_ratio = waitlist0 / capacity0` |
| `course_key`, `subject`, `catalog_number`, `component` | identity |
| `level` | `lower` (catalog number under 100), `upper` (100 to 199), `grad` (200 and above); letters stripped before parsing |
| `dept_group` | subject, with subjects that have fewer than `min_sections_per_group` (30) sections in the cohort pooled into `OTHER` |
| `phase` | enrollment phase at `join_time` from `analysis/calendar.py`: `phase1`, `between`, `phase2`, `adjustment`, `instruction` |
| `days_to_instruction` | days from `join_time` to the first day of instruction (negative after it) |
| `reserved` | `reserved0 > 0` at join |
| `scenario` | drop scenario used for `duration_min` |

```python
def build_cohort(flows: pd.DataFrame, identity: pd.DataFrame, calendar: TermCalendar, *, scenario: str = "central",
                 positions: Sequence[int] = DEFAULT_POSITIONS, join_every_min: float = 240, min_sections_per_group: int = 30) -> pd.DataFrame
def joinable(waitlist0: int, full0: bool | None) -> bool
def walk_positions(t0_ns, t1_ns, admits, wl_drops, waitlist0, censored, join_idx, positions, scenario) -> (duration_min, event)
```

`walk_positions` is `analysis.positions.time_to_clear` run in numpy for every joiner of a section at once, over the intervals where something happens (an admit, a waitlist drop or a censored interval); `tests/test_cohort.py` and the equivalence check in the 2026-09-20 session hold it to the reference row for row. Rows that do not clear are right-censored at the first censored interval's start after the join, or at the last observed interval end (`duration_min` becomes that horizon so lifelines gets a positive duration); a horizon of zero drops the row.

## 2. Term calendar (`analysis/calendar.py`)

```python
@dataclass(frozen=True)
class TermCalendar:
    term_id: str; name: str; phase1_start: date; phase1_end: date; phase2_start: date; phase2_end: date
    adjustment_start: date; instruction_start: date; last_auto_waitlist: date; add_drop_deadline: date
    def phase_at(self, when: datetime) -> str
    def days_to_instruction(self, when: datetime) -> float
SPRING_2027 = TermCalendar("2272", ..., last_auto_waitlist=2027-02-05, add_drop_deadline=2027-02-10)
FALL_2026 = TermCalendar("2268", ..., last_auto_waitlist=2026-09-11, add_drop_deadline=2026-09-16)
SPRING_2026 = TermCalendar("2262", ..., last_auto_waitlist=2026-02-06, add_drop_deadline=2026-02-11)
def calendar_for(term_id: str) -> TermCalendar
```

Dates come from the registrar ICS in `data/fixtures/`. `phase_at` uses UTC midnight boundaries of the Pacific dates (a 7 hour offset is immaterial at this resolution). Only Spring 2027 has an explicit "last automatic waitlist run" row (Feb 5, the same day as "last day to add without a fee"); for the other terms that day stands in for it.

## 3. Models (`analysis/survival.py`)

- `km_by(cohort, by: str) -> dict[str, KaplanMeierFitter]` with `lifelines.KaplanMeierFitter` per stratum of `position_bucket`, `level`, `dept_group`, `phase`; `logrank_table(cohort, by)` with pairwise `lifelines.statistics.logrank_test` p-values (Bonferroni noted, not applied).
- `fit_cox(cohort) -> CoxResult` with covariates `log_position`, `wl_ratio`, `level` (one-hot, lower as reference), `dept_group` (one-hot, OTHER as reference), `phase` (one-hot, phase1 as reference), `days_to_instruction`, `reserved`; `cluster_col="section_id"`, `robust=True`. `check_ph(result)` runs `proportional_hazard_test`; covariates with p below 0.05 are moved to `strata` and the model refit (`fit_cox_with_ph_check`). Both fits are reported.
- `sensitivity` / `headline_median`: the headline number (median days to clear at position 10, lower division, phase 1) under each drop scenario.
- The out-of-sample check is `analysis.backtest.run_backtest(cohort, calendar, split="temporal", which="days:14")` (section 9): fit on joins before Phase 2 with their follow-up censored at the split, score joins after it on "cleared within 14 days" with IPCW. The earlier `out_of_sample` dropped rows censored before 14 days but kept early clearings, which inflated the clearing rate; it is gone.
- `headline(cohort, fitters) -> dict` returns the plain-English results with their numbers (median days to clear by position bucket for lower-division courses in phase 1; share cleared by the first day of instruction by bucket; the largest department effect in the Cox fit).

## 4. Site tables (`analysis/export.py`)

`export_site_tables(cohort, calendar, out_dir, *, meta=None, min_n=30, n_boot=200, forecast_calendar=None, flows=None, estimate_level="dept")` writes the site's JSON under `site/data/` and returns `(index.json, meta.json)`. `estimate_level` is what a course's estimate is: `"dept"` (the default since 2026-09-20) makes every course cell a pointer to its department's curve for the bucket, because the Fall 2026 backtest found course-level curves no better than the position-bucket baseline out of time (Brier gain -0.023 [-0.034, -0.011]) and indistinguishable across held-out courses (docs/dev/BACKFILL_BACKTEST.md B3); `"course"` gives a course with `min_n` rows its own curve and is kept for later terms (`--estimate-level`, `ESTIMATE_LEVEL` in the Makefile). `meta.estimate_level` records the choice and the pages word their copy from it. `calendar` is the data term's; `forecast_calendar` (default: the same) is the term whose dates the pages count down to, so a finished cycle (Fall 2026) can stand in for the coming one (Spring 2027) and be labelled as such. `python -m analysis.export --cohort <cohort.parquet> --term-id 2268 --forecast-term 2272 --flows <flows.parquet> --meta-from site/data/meta.json` (`make site-data`) rewrites the files from a saved cohort without a refit, carrying `data_source`, `flows`, `backfill`, `cohort_rows_by_scenario`, `prereg_commit` and `prereg_date` over from the meta.json already there.

A **cell** is the Kaplan-Meier clearing curve of one group of virtual waitlisters:

| field | meaning |
| --- | --- |
| `curve` | `[days since joining, P(got in by then), 95% low, 95% high]` on a fixed grid (`CURVE_DAYS`, 0.5 to 182 days) cut at the group's longest follow-up, plus that reach as the last point; the band comes from `n_boot` resamples of sections, `null` when the group has one section |
| `reach_days` | the longest follow-up; the pages treat a reading past it as a floor |
| `n`, `events`, `sections` | rows, clearings and distinct sections behind the curve |
| `median_days` | first day at which the curve reaches one half, `null` if never |

The pages read a curve as a step function (`read_curve`): the last grid point at or before the horizon, `0` before the first point, the last point past the reach. A **summary** is a cell without its curve: `p`, `lo`, `hi` at `HORIZONS` (7, 14 and 28 days), `reach` (`[share at the reach, reach in days]`), `median_days` and the counts.

| file | contents |
| --- | --- |
| `meta.json` | `term_id`, `term_name` (the data term); `estimate_level`; `forecast_term_id`, `forecast_term_name`, `dates` (the eight calendar dates of the forecast term) and `data_dates` (the data term's); `deadline` (the forecast term's last automatic waitlist run, the headline horizon), `instruction_start`, `add_drop_deadline`; counts, `join_window`, `scenario`, `min_n`, `n_boot`, `horizons`, `positions`; `files`, `subject_files` (subject to `courses/<SUBJECT>.json`); `rank` (`wl_joins` when flows were given); `data_source` (`own_snapshots` or `berkeleytime_history`), `terms`, and whatever `meta` adds (`flows`, `backfill`, `cohort_rows_by_scenario`, `prereg_commit`, `prereg_date`) |
| `index.json` | `courses`: one row per course (`key`, `subject`, `number`, `level`, `dept_group`, `joins`, `buckets`); each bucket a summary plus `pooled` (`false`, a department or `"all"`) and, when pooled, the course's own `n_course` and `sections_course`. Drives search, the example chips (top `joins`), the Courses table and related courses |
| `courses/<SUBJECT>.json` | `courses`: `{course_key: {subject, number, level, dept_group, buckets}}`; a bucket is a pointer `{pooled, n_course, sections_course}` to the department's cell for the same bucket, or to the all-course cell when the department has fewer than `min_n` rows; at `estimate_level="course"` a bucket with `min_n` rows or more is instead a cell with `pooled: false`; a bucket with no pool is left out |
| `pooled.json` | `all` (bucket to cell), `dept` (department group to bucket to cell) and `level` (lower, upper, grad to bucket to cell), each with `min_n` rows or more |
| `insights.json` | `counts`; `all_by_bucket` (cells); `hero` (lower-division courses, Phase 1 joiners, by bucket; the README hero plot's data); `by_level` and `by_phase` (summaries by bucket); with flows: `daily` (`date`, `admits`, `joins`, `drops`, `intervals`, `share_censored` per UTC day) and `exits` (`admitted`, `dropped`, `still_waiting` at each section's last interval) |

The Kaplan-Meier estimate is computed in numpy (`km_clear_at`) because the bootstrap fits tens of thousands of curves. Shares are rounded to three decimals, medians to two, reaches to one; nothing else is post-processed by hand, and the pages compute no statistic of their own.

## 5. Figures (`analysis/figures.py`)

Matplotlib, saved under `analysis/out/<term>/figures/`: KM curves with confidence bands per stratum variable (four files), the out-of-sample calibration plot, and a hero plot (KM by position bucket for lower-division courses in phase 1) that the README embeds. One consistent style; axes in days; the sample size in every legend.

## 6. Commands

```
make analysis TERM=2272                         # from ./data-branch (this project's snapshots)
make backfill-analysis TERM=2268                # from backfill/2268 (Berkeleytime history, section 9)
```

`python -m analysis.run --data-root ./data-branch --term-id 2272 --out analysis/out` loads the panel and identity, computes flows with the data-log censoring, builds the cohort for the three scenarios, fits KM and Cox, checks PH, runs the out-of-sample backtest, writes tables (`analysis/out/<term>/*.csv`, `backtest_14d.csv`), figures, `site/data/*.json` and `analysis/out/<term>/report.md`. `--backfill-dir backfill/<term>` takes the panel, identity and pre-censored flows from `analysis.backfill build` instead and labels the site data `berkeleytime_history`. `run_analysis(panel, identity, calendar, out_dir, *, flows=None, site_meta=None, ...)` is the in-memory form. Deterministic given the inputs. Versions are pinned in requirements.txt (lifelines 0.30.3, matplotlib 3.11.2, pandas 2.3.3).

## 7. Tests

`tests/test_calendar.py` (phase boundaries, the last-automatic-run convention), `tests/test_cohort.py` (buckets, levels, pooling, thinning, censoring horizon, the joinable rule, on a hand-built flows table), `tests/test_survival.py` (KM curves are monotone, Cox fits and recovers the sign of the position effect, PH check runs), `tests/test_run.py` (end to end on the simulator with a 21-day term whose Phase 2 starts on day 5, so the 14-day out-of-sample check has known outcomes; the exporter's pooling rule, curve monotonicity and band), `tests/test_backfill.py` and `tests/test_backtest.py` (section 9). Network-free.

## 8. What A5 does not do

It does not claim causal effects, does not model individual students, and does not extrapolate beyond the last automatic waitlist run. Small strata are pooled and labelled; every number on the site carries its sample size and, where there is more than one section, an interval.

## 9. Backfill and backtest (`analysis/backfill.py`, `analysis/backtest.py`)

Added 2026-09-20 (docs/dev/BACKFILL_BACKTEST.md). The site is otherwise empty until mid-November; Fall 2026 is a finished cycle whose 15-minute history Berkeleytime serves publicly, so it can be modelled now and used to test the model honestly.

**Backfill.** `python -m analysis.backfill fetch --term "Fall 2026"` pulls one `GetCatalog` (cached) and one `GetEnrollment` per eligible primary section into `backfill/raw/<term>/` (gzip JSON, one request every 2 s, resumable, failures recorded and retried; the recorded `GetEnrollment` ops are tried in file order because the gateway's schema rejects the second one). Eligible means the same component exclusion as the scraper; selection never reads today's counts (keeping today's waitlisted sections would keep exactly the ones that failed to clear) and is a seeded permutation, so a `--limit 300` pilot is the first 300 of the full pull. `build` turns each history's run-length segments into the panel `interval_flows` reads: a row at each segment's start and end (observed stillness inside a segment is never censored, however long), and a crossing between segments where the change happened; a crossing wider than `GAP_MIN` (180 minutes; Berkeleytime's poll spacing at changes was 15 minutes from July 2026 and 45 to 130 minutes from March to June, so 45 would censor ordinary polls) is a Berkeleytime gap and the interval is flagged `censored`. Outputs `panel.parquet`, `identity.parquet`, `gaps.parquet`, `flows.parquet`, `gap_report.csv` (share of covered section-time dark per UTC day) and `meta.json` (`data_source: berkeleytime_history`). None of this counts toward the collection claims in CLAIMS.md.

**Backtest.** `python -m analysis.backtest --cohort analysis/out/<term>/cohort_central.parquet --term-id <term> --split temporal|grouped|cross_term --which deadline|instruction|days:N` scores four predictors at each test row's own horizon: `bucket` (KM per position bucket, the baseline), `course` (the site's pooled course-and-bucket KM read at the row's horizon), `site` (the literal site number: the same curve at the training cell's median lead time, rounded to two decimals) and `cox` (`fit_cox` on the training rows). Observability comes first: a row is scored at horizon h only when `follow_up_days >= h`; where a gap or the end of the data falls before h, a joiner who cleared before it is seen and one who did not is not, so the probability of observing a negative is zero and no weighting recovers it. Such rows are excluded and counted by phase (`coverage.csv`). Then scoring is IPCW (Graf): rows censored before their horizon weigh 0, cleared rows 1/G(T-), rows still waiting 1/G(h), with G the censoring Kaplan-Meier on the test rows floored at 0.05; Brier self-normalised by the weights, weighted Mann-Whitney AUC, weighted decile calibration, and the Brier gain over the baseline with a 95% interval from resampling sections. `temporal` censors the training rows at the split date (default: Phase 2 start) so nothing after it leaks into the fit; `grouped` is K folds by course; `cross_term` fits on another term's cohort. Reports land in `reports/backtest_<term>/<split>_<which>/` (`metrics.csv`, `by_phase.csv`, `by_bucket.csv`, `calibration.csv`, `predictions.parquet`, `report.md`, `calibration_cox.png`); `make backtest` runs the temporal 14- and 28-day horizons, the grouped 14-day horizon, and the temporal deadline and instruction horizons (which on Fall 2026 report themselves unobservable for every joiner before the Aug 19 to Sep 1 hole). `tests/test_backtest.py::test_ipcw_toy_example` is the argument for IPCW over dropping unknown rows.
