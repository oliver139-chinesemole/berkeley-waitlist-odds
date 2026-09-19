# A5 design contract — survival analysis

Binding interfaces for step A5 (docs/FINISH_PLAN_WAITLIST.md A5; docs/SPEC.md section 6). Input: the flows table from `analysis.flows.interval_flows` and section identity from `analysis.panel`. Output: Kaplan-Meier curves, a Cox proportional-hazards fit with its assumption check, sensitivity across drop scenarios, out-of-sample calibration, and the precomputed lookup tables the site (A6) reads. One command reproduces everything from the raw Parquet.

## 1. Unit of analysis (`analysis/cohort.py`)

A virtual waitlister is `(section_id, join_time, position)` from `analysis.positions.virtual_waitlisters`, thinned so that join times are sampled every `join_every_min` minutes per section (default 240; every observed run would give tens of millions of correlated rows). Each row carries:

| column | meaning |
| --- | --- |
| `duration_min`, `event` | from the position model; `duration_days = duration_min / 1440` |
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
                 positions: Sequence[int] = (1, 3, 5, 10, 20, 40), join_every_min: float = 240, min_sections_per_group: int = 30) -> pd.DataFrame
```

Rows whose `duration_min` is null and `event == 0` are right-censored at the last observed interval end of their section (`duration_min` then becomes that horizon so lifelines gets a positive duration).

## 2. Term calendar (`analysis/calendar.py`)

```python
@dataclass(frozen=True)
class TermCalendar:
    term_id: str; phase1_start: date; phase1_end: date; phase2_start: date; phase2_end: date
    adjustment_start: date; instruction_start: date; last_auto_waitlist: date; add_drop_deadline: date
    def phase_at(self, when: datetime) -> str
SPRING_2027 = TermCalendar("2272", 2026-10-26, 2026-11-15, 2026-11-23, 2027-01-10, 2027-01-11, 2027-01-19, 2027-02-05, 2027-02-10)
FALL_2026 = TermCalendar("2268", ...)   # from the registrar ICS in data/fixtures for the test term
def calendar_for(term_id: str) -> TermCalendar
```

Dates come from docs/PHASE0.md (registrar ICS). `phase_at` uses UTC midnight boundaries of the Pacific dates (a 7 hour offset is immaterial at this resolution).

## 3. Models (`analysis/survival.py`)

- `km_by(cohort, by: str) -> dict[str, KaplanMeierFitter]` with `lifelines.KaplanMeierFitter` per stratum of `position_bucket`, `level`, `dept_group`, `phase`; `logrank_table(cohort, by)` with pairwise `lifelines.statistics.logrank_test` p-values (Bonferroni noted, not applied).
- `fit_cox(cohort) -> CoxPHFitter` with covariates `log_position`, `wl_ratio`, `level` (one-hot, lower as reference), `dept_group` (one-hot, OTHER as reference), `phase` (one-hot, phase1 as reference), `days_to_instruction`, `reserved`; `cluster_col="section_id"`, `robust=True`. `check_ph(fitter, cohort) -> pd.DataFrame` runs `proportional_hazard_test`; covariates with p below 0.05 are moved to `strata` and the model refit (`fit_cox_stratified`). Both fits are reported.
- `sensitivity(flows, identity, calendar)` rebuilds the cohort under all three scenarios and reports the headline number (median days to clear at position 10, lower division, phase 1) under each.
- `out_of_sample(cohort)` fits on `phase == "phase1"` joins and scores `phase == "phase2"` joins: concordance index, Brier score for the event "cleared within 14 days" (IPCW-free version on rows with 14 days of follow-up, stated as such), and a decile calibration table of predicted versus observed 14-day clearing.
- `headline(cohort, fitters) -> dict` returns the two or three plain-English results with their numbers (median days to clear by position bucket for lower-division courses in phase 1; share cleared by the first day of instruction by bucket; the largest department effect in the Cox fit).

## 4. Site tables (`analysis/export.py`)

`export_site_tables(cohort, out_dir: Path)` writes `site/data/courses.json`: for each `course_key` and `position_bucket`, `p_clear_by_instruction` (KM estimate at `days_to_instruction`), `median_days`, `n`, and `pooled: false`; when `n < 30` the department-level KM is used instead and `pooled: true`. Also `site/data/meta.json` with the term, the data window, the run count and the generation time. Numbers are rounded to two decimals; nothing else is post-processed by hand.

## 5. Figures (`analysis/figures.py`)

Matplotlib, saved under `analysis/out/figures/<term>/`: KM curves with confidence bands per stratum variable (four files), the calibration plot, and a hero plot (KM by position bucket for lower-division courses in phase 1) that the README embeds. One consistent style; axes in days; the sample size in every legend.

## 6. Command

```
make analysis TERM=2272
```

runs `python -m analysis.run --data-root ./data-branch --term-id 2272 --out analysis/out` which: loads the panel and identity, computes flows with the data-log censoring, builds the cohort for the three scenarios, fits KM and Cox, checks PH, runs the out-of-sample scoring, writes tables (`analysis/out/<term>/*.csv`), figures, `site/data/*.json`, and `analysis/out/<term>/report.md` with the headline results and every table. Deterministic given the data branch. Versions are pinned in requirements.txt (lifelines 0.30.3, matplotlib 3.11.2, pandas 2.3.3).

## 7. Tests

`tests/test_calendar.py` (phase boundaries), `tests/test_cohort.py` (buckets, levels, pooling, thinning, censoring horizon on a hand-built flows table), `tests/test_survival.py` (on the A4 simulator's output: KM curves are monotone, Cox fits without error and recovers the sign of the position effect, PH check runs, out-of-sample scoring returns numbers in range, export writes valid JSON with the pooled flag). Network-free; the simulator provides the data.

## 8. What A5 does not do

It does not claim causal effects, does not model individual students, and does not extrapolate beyond the last automatic waitlist run. Small strata are pooled and labelled; every number on the site carries its sample size.
