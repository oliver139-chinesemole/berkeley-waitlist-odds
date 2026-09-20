"""Kaplan-Meier, Cox proportional hazards and sensitivity across drop scenarios.

See docs/DESIGN_A5.md section 3. Inputs are cohorts from ``analysis.cohort``
(one row per virtual waitlister with ``duration_days`` and ``event``).
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd
from lifelines import CoxPHFitter, KaplanMeierFitter
from lifelines.statistics import logrank_test, proportional_hazard_test

from analysis import coxfast

coxfast.install()  # lifelines' O(n^2) score residual -> O(n); see analysis/coxfast.py

logger = logging.getLogger(__name__)

STRATA = ("position_bucket", "level", "dept_group", "phase")
COX_NUMERIC = ("log_position", "wl_ratio", "days_to_instruction", "reserved")
COX_CATEGORICAL = {"level": "lower", "dept_group": "OTHER", "phase": "phase1"}
BUCKET_ORDER = ("1-5", "6-15", "16-40", "41+")
HORIZON_DAYS = 14.0  # the fixed horizon analysis.run uses for its out-of-sample check
# Durations are rounded to this many days before the Cox fit (0.01 day is 14.4 minutes, finer
# than any source's poll: Berkeleytime 15 min, this project's scraper 30 min). Nearly-unique
# times send lifelines down its per-row path, which took over eight hours on the 493,364-row
# Fall 2026 cohort; ties let it batch by event time.
COX_TIME_RESOLUTION_DAYS = 0.01
PH_TEST_MAX_ROWS = 50_000  # the Schoenfeld test runs on a seeded random subsample above this
# Optional row cap for every Cox fit in the pipeline (analysis.run --cox-max-rows and the
# backtest's Cox predictor): a seeded random subsample above it. None means no cap: with the
# linear-time score residual (analysis/coxfast.py) the full Fall 2026 cohort (475,079 design
# rows, 49 covariates) fits in 14 s; before it the fit did not finish in 40 minutes.
COX_MAX_ROWS: int | None = None


# ---------------------------------------------------------------- Kaplan-Meier


def km_by(cohort: pd.DataFrame, by: str, *, min_rows: int = 10) -> dict[str, KaplanMeierFitter]:
    """One fitted KaplanMeierFitter per stratum of ``by`` with at least ``min_rows`` rows."""
    fitters: dict[str, KaplanMeierFitter] = {}
    for key, group in cohort.groupby(by, sort=True, observed=True):
        if len(group) < min_rows:
            continue
        kmf = KaplanMeierFitter(label=f"{by}={key} (n={len(group)})")
        kmf.fit(group["duration_days"].to_numpy(dtype=float), event_observed=group["event"].to_numpy(dtype=int))
        fitters[str(key)] = kmf
    return fitters


def km_table(fitters: dict[str, KaplanMeierFitter], *, at_days: Iterable[float] = (1, 3, 7, 14, 30)) -> pd.DataFrame:
    """Survival (still waiting) probability at fixed horizons plus the median time to clear per stratum."""
    rows = []
    for key, kmf in fitters.items():
        row = {"stratum": key, "n": int(kmf.event_observed.shape[0]), "events": int(kmf.event_observed.sum()), "median_days": float(kmf.median_survival_time_)}
        for d in at_days:
            row[f"p_clear_by_{int(d)}d"] = float(1.0 - kmf.predict(float(d)))
        rows.append(row)
    return pd.DataFrame(rows)


def logrank_table(cohort: pd.DataFrame, by: str) -> pd.DataFrame:
    """Pairwise log-rank tests between strata of ``by`` (p-values uncorrected; the
    number of comparisons is in the table so a Bonferroni bound can be applied)."""
    groups = {str(k): g for k, g in cohort.groupby(by, sort=True, observed=True) if len(g) >= 2}
    rows = []
    for a, b in itertools.combinations(groups, 2):
        ga, gb = groups[a], groups[b]
        res = logrank_test(ga["duration_days"], gb["duration_days"], event_observed_A=ga["event"], event_observed_B=gb["event"])
        rows.append({"by": by, "a": a, "b": b, "n_a": len(ga), "n_b": len(gb), "statistic": float(res.test_statistic), "p": float(res.p_value)})
    out = pd.DataFrame(rows, columns=["by", "a", "b", "n_a", "n_b", "statistic", "p"])
    out["comparisons"] = len(out)
    return out


# ------------------------------------------------------------------------ Cox


def design_matrix(cohort: pd.DataFrame, *, time_resolution_days: float = COX_TIME_RESOLUTION_DAYS) -> pd.DataFrame:
    """Covariates for the Cox model: numeric columns as they are (``reserved``
    as 0/1) and one-hot columns for the categorical ones with the reference
    level dropped. Keeps ``duration_days`` (rounded up to ``time_resolution_days``
    so tied times exist and stay positive), ``event`` and ``section_id``."""
    frame = cohort.copy()
    durations = frame["duration_days"].astype(float)
    if time_resolution_days and time_resolution_days > 0:
        durations = np.ceil(durations / time_resolution_days) * time_resolution_days
    cols: dict[str, pd.Series] = {
        "duration_days": durations,
        "event": frame["event"].astype(int),
        "section_id": frame["section_id"].astype(str),
    }
    for c in COX_NUMERIC:
        cols[c] = frame[c].astype(float) if c != "reserved" else frame[c].astype(bool).astype(float)
    for c, reference in COX_CATEGORICAL.items():
        values = frame[c].astype(str)
        for level in sorted(v for v in values.unique() if v != reference and v != "None" and v != "<NA>"):
            cols[f"{c}={level}"] = (values == level).astype(float)
    out = pd.DataFrame(cols, index=frame.index)
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    # drop constant columns (a stratum absent from this cohort)
    constant = [c for c in out.columns if c not in ("duration_days", "event", "section_id") and out[c].nunique() <= 1]
    return out.drop(columns=constant)


@dataclass
class CoxResult:
    fitter: CoxPHFitter
    design: pd.DataFrame
    strata: list[str] = field(default_factory=list)

    @property
    def summary(self) -> pd.DataFrame:
        return self.fitter.summary

    @property
    def rows_fit(self) -> int:
        return int(len(self.design))


def fit_cox(cohort: pd.DataFrame, *, strata: Iterable[str] = (), penalizer: float = 0.01, max_rows: int | None = COX_MAX_ROWS, seed: int = 0) -> CoxResult:
    """Cox PH with robust (cluster by section) standard errors; ``strata`` names
    columns of the design matrix (one-hot prefixes are expanded). With
    ``max_rows`` the fit uses a seeded random subsample of that many rows
    (``result.rows_fit`` says how many were used)."""
    design = design_matrix(cohort)
    if max_rows is not None and len(design) > int(max_rows):
        design = design.sample(n=int(max_rows), random_state=seed).sort_index()
    strata_cols: list[str] = []
    for s in strata:
        strata_cols += [c for c in design.columns if c == s or c.startswith(f"{s}=")]
    cph = CoxPHFitter(penalizer=penalizer)
    fit_kwargs = {"duration_col": "duration_days", "event_col": "event", "cluster_col": "section_id", "robust": True, "batch_mode": True}
    if strata_cols:
        # lifelines wants strata as categorical columns: collapse each one-hot family into a label
        collapsed = design.copy()
        families = sorted({c.split("=")[0] for c in strata_cols})
        labels: list[str] = []
        for fam in families:
            members = [c for c in collapsed.columns if c.startswith(f"{fam}=")]
            if members:
                collapsed[f"{fam}_stratum"] = collapsed[members].idxmax(axis=1).where(collapsed[members].sum(axis=1) > 0, f"{fam}=ref")
                collapsed = collapsed.drop(columns=members)
            else:
                collapsed[f"{fam}_stratum"] = collapsed[fam].astype(str)
                collapsed = collapsed.drop(columns=[fam])
            labels.append(f"{fam}_stratum")
        cph.fit(collapsed, strata=labels, **fit_kwargs)
        return CoxResult(fitter=cph, design=collapsed, strata=labels)
    cph.fit(design, **fit_kwargs)
    return CoxResult(fitter=cph, design=design)


def check_ph(result: CoxResult, *, alpha: float = 0.05, max_rows: int = PH_TEST_MAX_ROWS, seed: int = 0) -> pd.DataFrame:
    """Proportional-hazards test per covariate (Schoenfeld residuals, rank transform).

    lifelines runs the test on the frame a fitter was trained on, and its cost
    grows with rows times event times, so above ``max_rows`` a plain Cox with
    the same covariates (and strata) is refit on a seeded random subsample and
    tested instead; 50,000 rows give the test ample power. ``rows_tested`` says
    which frame was used."""
    frame = result.design
    fitter = result.fitter
    if max_rows and len(frame) > max_rows:
        # the diagnostic fit has no cluster column, so the frame it is tested on must not either
        frame = frame.sample(n=int(max_rows), random_state=seed).drop(columns=["section_id"])
        diagnostic = CoxPHFitter(penalizer=fitter.penalizer)
        diagnostic.fit(frame, duration_col="duration_days", event_col="event", strata=result.strata or None, batch_mode=True)
        fitter = diagnostic
    test = proportional_hazard_test(fitter, frame, time_transform="rank")
    out = test.summary.reset_index()
    out = out.rename(columns={out.columns[0]: "covariate", "-log2(p)": "neg_log2_p"})
    out["violates"] = out["p"] < alpha
    out["rows_tested"] = int(len(frame))
    return out


def fit_cox_with_ph_check(cohort: pd.DataFrame, *, alpha: float = 0.05, max_rows: int | None = COX_MAX_ROWS) -> tuple[CoxResult, pd.DataFrame, CoxResult | None]:
    """Fit, test PH, and refit with the violating covariate families as strata.
    Returns (first fit, PH table, stratified refit or None)."""
    first = fit_cox(cohort, max_rows=max_rows)
    ph = check_ph(first, alpha=alpha)
    violating = sorted({str(c).split("=")[0] for c in ph.loc[ph["violates"], "covariate"]})
    # only categorical families can be stratified; numeric violators are reported, not stratified
    families = [f for f in violating if f in COX_CATEGORICAL]
    if not families:
        return first, ph, None
    return first, ph, fit_cox(cohort, strata=families, max_rows=max_rows)


# ---------------------------------------------------------------- sensitivity


def headline_median(cohort: pd.DataFrame, *, position: int = 10, level: str = "lower", phase: str = "phase1") -> float:
    """Median days to clear (KM) for joiners at ``position`` in ``level`` courses during ``phase``; NaN when undefined."""
    sub = cohort[(cohort["position"] == position) & (cohort["level"] == level) & (cohort["phase"] == phase)]
    if len(sub) < 10:
        return float("nan")
    kmf = KaplanMeierFitter().fit(sub["duration_days"].astype(float), event_observed=sub["event"].astype(int))
    return float(kmf.median_survival_time_)


def sensitivity(cohorts: dict[str, pd.DataFrame], **kwargs) -> pd.DataFrame:
    """Headline median under each scenario (keys of ``cohorts``)."""
    rows = [{"scenario": s, "median_days": headline_median(c, **kwargs), "n": len(c)} for s, c in cohorts.items()]
    return pd.DataFrame(rows)


# The out-of-sample check lives in analysis.backtest (IPCW-weighted; the old
# out_of_sample here dropped rows censored before 14 days but kept early
# clearings, which inflated the clearing rate).


# ------------------------------------------------------------------- headline


def headline(cohort: pd.DataFrame, cox: CoxResult | None = None) -> dict:
    """The plain-English results with their numbers (docs/DESIGN_A5.md section 3)."""
    out: dict = {}
    lower_p1 = cohort[(cohort["level"] == "lower") & (cohort["phase"] == "phase1")]
    by_bucket = km_by(lower_p1, "position_bucket") if len(lower_p1) else {}
    table = km_table(by_bucket, at_days=(7, 14)) if by_bucket else pd.DataFrame()
    out["lower_division_phase1_by_bucket"] = table
    if len(cohort):
        horizon = cohort["days_to_instruction"].clip(lower=0)
        cleared_by_instruction = ((cohort["event"] == 1) & (cohort["duration_days"] <= horizon)).groupby(cohort["position_bucket"]).mean()
        out["share_cleared_by_instruction_by_bucket"] = cleared_by_instruction.reindex(BUCKET_ORDER).dropna()
    if cox is not None:
        summ = cox.summary
        dept = summ[summ.index.str.startswith("dept_group=")]
        if len(dept):
            strongest = dept["coef"].abs().idxmax()
            out["largest_department_effect"] = {"covariate": strongest, "hazard_ratio": float(np.exp(dept.at[strongest, "coef"])), "p": float(dept.at[strongest, "p"])}
        if "log_position" in summ.index:
            out["position_hazard_ratio_per_log_unit"] = float(np.exp(summ.at["log_position", "coef"]))
    return out
