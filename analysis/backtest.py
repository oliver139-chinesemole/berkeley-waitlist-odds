"""Backtests: freeze the model on one set of virtual waitlisters, score another.

Four predictors are scored at each test row's own horizon:

- ``bucket``: Kaplan-Meier per position bucket (the baseline);
- ``course``: Kaplan-Meier per course and bucket with the site's pooling rule
  (department, then all courses, below ``min_n`` rows), read at the row's horizon;
- ``site``: the literal number the site would show, i.e. the same pooled
  curve read at the *training* cell's median lead time before instruction
  and rounded to two decimals, whatever the test row's own horizon is;
- ``cox``: the Cox proportional-hazards fit from ``analysis.survival``.

Scores are inverse-probability-of-censoring weighted (IPCW, Graf 1999). A
test row whose outcome at its horizon is unknown (censored before it) gets
weight 0; a row cleared by the horizon is weighted by 1/G(T-), a row still
waiting at the horizon by 1/G(h), where G is the Kaplan-Meier estimate of the
censoring distribution on the test set. Dropping the unknown rows instead
would keep every early clearing and lose only slow ones, inflating the
clearing rate (``tests/test_backtest.py::test_ipcw_toy_example``). The
Brier score is self-normalised by the weights; the AUC is the weighted
Mann-Whitney statistic; calibration is weighted by decile of the prediction.
Uncertainty on the gain over the baseline comes from resampling sections,
not rows, because the rows of one section are copies of the same queue.

Observability comes first. A row is scored at horizon h only if it could
have been followed to h whatever happened (``follow_up_days >= h``): where a
gap or the end of the data falls before h, a joiner who cleared before it is
seen and one who did not is not, so the probability of observing a negative
is zero and no weighting can recover it. Such rows are excluded and counted,
by phase. In Berkeleytime's Fall 2026 history a recorder outage from Aug 19
to Sep 1 makes "cleared by the last automatic waitlist run" and "cleared by
the first day of instruction" unobservable for every joiner before it; fixed
horizons (``days:7``, ``days:14``, ``days:28``) are what that term can score.

Splits: ``temporal`` (train before a date, test after; training rows are
censored at the split date so nothing after it leaks into the fit),
``grouped`` (K folds by course, every row scored once out of fold) and
``cross_term`` (fit on another term's cohort, score this one).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter

from analysis.calendar import TermCalendar, calendar_for
from analysis.survival import BUCKET_ORDER, design_matrix, fit_cox

logger = logging.getLogger(__name__)

PREDICTORS = ("bucket", "course", "site", "cox")
SPLITS = ("temporal", "grouped", "cross_term")
BASELINE = "bucket"
MIN_TRAIN_ROWS = 50
MIN_TRAIN_EVENTS = 10
MIN_TEST_ROWS = 50
G_FLOOR = 0.05  # weights are capped at 1 / G_FLOOR


# ------------------------------------------------------------------ horizons


def horizon_days(cohort: pd.DataFrame, calendar: TermCalendar, which: str) -> pd.Series:
    """Days from each row's ``join_time`` to the horizon named by ``which``:
    ``deadline`` (end of the last automatic waitlist run's day), ``instruction``
    (00:00 UTC on the first day of instruction) or ``days:N`` (a fixed N)."""
    join = pd.to_datetime(cohort["join_time"], utc=True)
    if which == "deadline":
        d = calendar.last_auto_waitlist + timedelta(days=1)
        target = pd.Timestamp(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
        return ((target - join).dt.total_seconds() / 86400.0).astype(float)
    if which == "instruction":
        d = calendar.instruction_start
        target = pd.Timestamp(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
        return ((target - join).dt.total_seconds() / 86400.0).astype(float)
    if which.startswith("days:"):
        return pd.Series(float(which.split(":", 1)[1]), index=cohort.index, dtype=float)
    raise ValueError(f"unknown horizon {which!r}; expected deadline, instruction or days:N")


# ------------------------------------------------------------------------ IPCW


def _km_step(durations: np.ndarray, events: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``(times, survival)`` of a Kaplan-Meier step function (right-continuous)."""
    kmf = KaplanMeierFitter().fit(np.asarray(durations, dtype=float), event_observed=np.asarray(events, dtype=int))
    sf = kmf.survival_function_
    return sf.index.to_numpy(dtype=float), sf.iloc[:, 0].to_numpy(dtype=float)


def _step_at(times: np.ndarray, values: np.ndarray, t: np.ndarray, *, left: bool = False) -> np.ndarray:
    """Value of the step function at ``t`` (or just before it when ``left``); 1 before the first jump."""
    t = np.asarray(t, dtype=float)
    idx = np.searchsorted(times, t, side="left" if left else "right") - 1
    out = np.ones_like(t, dtype=float)
    ok = idx >= 0
    out[ok] = values[idx[ok]]
    return out


def ipcw_weights(duration: np.ndarray, event: np.ndarray, horizon: np.ndarray, *, g_floor: float = G_FLOOR) -> tuple[np.ndarray, np.ndarray]:
    """``(y, w)``: the outcome "cleared by the row's horizon" and its IPCW weight
    (0 when the outcome is unknown). ``G`` is the censoring Kaplan-Meier on
    these rows, floored at ``g_floor``."""
    duration = np.asarray(duration, dtype=float)
    event = np.asarray(event, dtype=int)
    horizon = np.asarray(horizon, dtype=float)
    times, g = _km_step(duration, 1 - event)
    cleared = (event == 1) & (duration <= horizon)
    still = duration > horizon
    g_at_t = np.maximum(_step_at(times, g, duration, left=True), g_floor)
    g_at_h = np.maximum(_step_at(times, g, horizon), g_floor)
    w = np.where(cleared, 1.0 / g_at_t, np.where(still, 1.0 / g_at_h, 0.0))
    return cleared.astype(float), w


def brier(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    """Weighted mean squared error over rows with a known outcome (self-normalised IPCW)."""
    mask = (w > 0) & np.isfinite(p)
    if not mask.any():
        return float("nan")
    return float(np.sum(w[mask] * (y[mask] - p[mask]) ** 2) / np.sum(w[mask]))


def weighted_auc(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    """Weighted Mann-Whitney AUC: P(p_pos > p_neg) with ties counted half."""
    mask = (w > 0) & np.isfinite(p)
    y, p, w = y[mask], p[mask], w[mask]
    sum_pos = float(np.sum(w[y == 1]))
    sum_neg = float(np.sum(w[y == 0]))
    if sum_pos == 0 or sum_neg == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    p, y, w = p[order], y[order], w[order]
    total = 0.0
    neg_below = 0.0
    i = 0
    n = len(p)
    while i < n:
        j = i
        while j < n and p[j] == p[i]:
            j += 1
        block_neg = float(np.sum(w[i:j][y[i:j] == 0]))
        block_pos_w = w[i:j][y[i:j] == 1]
        total += float(np.sum(block_pos_w)) * (neg_below + 0.5 * block_neg)
        neg_below += block_neg
        i = j
    return float(total / (sum_pos * sum_neg))


def calibration_table(y: np.ndarray, p: np.ndarray, w: np.ndarray, *, deciles: int = 10) -> pd.DataFrame:
    mask = (w > 0) & np.isfinite(p)
    frame = pd.DataFrame({"p": p[mask], "y": y[mask], "w": w[mask]})
    if frame.empty:
        return pd.DataFrame(columns=["decile", "n", "weight", "predicted", "observed"])
    bins = min(deciles, max(1, frame["p"].nunique()))
    frame["decile"] = pd.qcut(frame["p"].rank(method="first"), bins, labels=False)
    out = frame.groupby("decile").apply(
        lambda g: pd.Series({"n": len(g), "weight": g["w"].sum(), "predicted": np.average(g["p"], weights=g["w"]), "observed": np.average(g["y"], weights=g["w"])}),
        include_groups=False,
    )
    return out.reset_index()


def bootstrap_gain(section_id: np.ndarray, y: np.ndarray, p_model: np.ndarray, p_base: np.ndarray, w: np.ndarray, *, n_boot: int = 200, seed: int = 0) -> tuple[float, float]:
    """95% interval for ``brier(base) - brier(model)`` resampling sections with replacement."""
    if n_boot <= 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    sections = pd.Series(np.arange(len(section_id))).groupby(np.asarray(section_id, dtype=str)).apply(lambda s: s.to_numpy()).tolist()
    if len(sections) < 2:
        return float("nan"), float("nan")
    gains = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, len(sections), len(sections))
        idx = np.concatenate([sections[i] for i in pick])
        gains[b] = brier(y[idx], p_base[idx], w[idx]) - brier(y[idx], p_model[idx], w[idx])
    return float(np.nanpercentile(gains, 2.5)), float(np.nanpercentile(gains, 97.5))


# ----------------------------------------------------------------- predictors


class _Curve:
    __slots__ = ("times", "surv", "n", "events")

    def __init__(self, durations: pd.Series, events: pd.Series) -> None:
        self.times, self.surv = _km_step(durations.to_numpy(dtype=float), events.to_numpy(dtype=int))
        self.n = int(len(durations))
        self.events = int(events.sum())

    def p_clear(self, h: np.ndarray) -> np.ndarray:
        return 1.0 - _step_at(self.times, self.surv, np.maximum(np.asarray(h, dtype=float), 0.0))


class PooledKM:
    """Kaplan-Meier per course and bucket with the site's pooling rule, and the
    per-bucket baseline. ``fit`` on the training cohort; ``predict`` reads the
    chosen curve at the row's own horizon; ``predict_site`` reads it at the
    training cell's median lead time and rounds like ``analysis.export``."""

    def __init__(self, *, min_n: int = 30) -> None:
        self.min_n = min_n
        self.by_bucket: dict[str, _Curve] = {}
        self.by_dept: dict[tuple[str, str], _Curve] = {}
        self.by_course: dict[tuple[str, str], _Curve] = {}
        self.course_horizon: dict[tuple[str, str], float] = {}
        self.bucket_horizon: dict[str, float] = {}
        self.depts: set[str] = set()
        self.all: _Curve | None = None

    def fit(self, train: pd.DataFrame) -> "PooledKM":
        self.all = _Curve(train["duration_days"], train["event"])
        for bucket, g in train.groupby("position_bucket", observed=True):
            self.by_bucket[str(bucket)] = _Curve(g["duration_days"], g["event"])
            self.bucket_horizon[str(bucket)] = float(g["days_to_instruction"].median())
        for (dept, bucket), g in train.groupby(["dept_group", "position_bucket"], observed=True):
            if len(g) >= self.min_n:
                self.by_dept[(str(dept), str(bucket))] = _Curve(g["duration_days"], g["event"])
        for (course, bucket), g in train.groupby(["course_key", "position_bucket"], observed=True):
            self.course_horizon[(str(course), str(bucket))] = float(g["days_to_instruction"].median())
            if len(g) >= self.min_n:
                self.by_course[(str(course), str(bucket))] = _Curve(g["duration_days"], g["event"])
        self.depts = {str(d) for d in train["dept_group"].dropna().unique()}
        return self

    def dept_of(self, test: pd.DataFrame) -> pd.Series:
        """The training department group a test row falls in: its subject when
        the training set has that department, else ``OTHER``."""
        subj = test["subject"].astype(str)
        return subj.where(subj.isin(self.depts), "OTHER")

    def _curve(self, course: str, dept: str, bucket: str) -> tuple[_Curve, str]:
        if (course, bucket) in self.by_course:
            return self.by_course[(course, bucket)], "course"
        if (dept, bucket) in self.by_dept:
            return self.by_dept[(dept, bucket)], "dept"
        if bucket in self.by_bucket:
            return self.by_bucket[bucket], "bucket"
        return self.all, "all"  # type: ignore[return-value]

    def predict_bucket(self, test: pd.DataFrame, h: np.ndarray) -> np.ndarray:
        out = np.empty(len(test))
        buckets = test["position_bucket"].astype(str).to_numpy()
        for i, (b, hi) in enumerate(zip(buckets, h)):
            curve = self.by_bucket.get(b, self.all)
            out[i] = curve.p_clear(np.array([hi]))[0]  # type: ignore[union-attr]
        return out

    def predict(self, test: pd.DataFrame, h: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``(p, level)`` with ``level`` in course/dept/bucket/all per row."""
        out = np.empty(len(test))
        level = np.empty(len(test), dtype=object)
        courses = test["course_key"].astype(str).to_numpy()
        depts = self.dept_of(test).to_numpy()
        buckets = test["position_bucket"].astype(str).to_numpy()
        for i in range(len(test)):
            curve, lvl = self._curve(courses[i], depts[i], buckets[i])
            out[i] = curve.p_clear(np.array([h[i]]))[0]
            level[i] = lvl
        return out, level

    def predict_site(self, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """``(p, fallback)``: the site's number for the row's course and bucket; when
        the training cohort has no rows for that course and bucket the site would
        show nothing, and the bucket curve at the bucket's median lead time stands in."""
        out = np.empty(len(test))
        fallback = np.zeros(len(test), dtype=bool)
        courses = test["course_key"].astype(str).to_numpy()
        depts = self.dept_of(test).to_numpy()
        buckets = test["position_bucket"].astype(str).to_numpy()
        for i in range(len(test)):
            key = (courses[i], buckets[i])
            if key in self.course_horizon:
                curve, _ = self._curve(courses[i], depts[i], buckets[i])
                horizon = self.course_horizon[key]
            else:
                curve = self.by_bucket.get(buckets[i], self.all)  # type: ignore[assignment]
                horizon = self.bucket_horizon.get(buckets[i], float(np.nanmedian(list(self.bucket_horizon.values()))) if self.bucket_horizon else 0.0)
                fallback[i] = True
            out[i] = round(float(curve.p_clear(np.array([max(horizon, 0.0)]))[0]), 2)
        return out, fallback


class CoxPredictor:
    def __init__(self) -> None:
        self.result = None
        self.columns: list[str] = []
        self.error: str | None = None
        self.depts: set[str] = set()

    def fit(self, train: pd.DataFrame) -> "CoxPredictor":
        self.depts = {str(d) for d in train["dept_group"].dropna().unique()}
        try:
            self.result = fit_cox(train)
            self.columns = [c for c in self.result.design.columns if c not in ("duration_days", "event", "section_id")]
        except Exception as exc:  # noqa: BLE001 - a singular fit is a result, not a crash
            self.error = f"{type(exc).__name__}: {exc}"
            logger.warning("Cox fit failed: %s", self.error)
        return self

    def predict(self, test: pd.DataFrame, h: np.ndarray, fallback: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``(p, used_fallback)``; rows the design matrix drops (missing covariates) take ``fallback``."""
        out = np.array(fallback, dtype=float, copy=True)
        used = np.ones(len(test), dtype=bool)
        if self.result is None:
            return out, used
        frame = test.copy()
        subj = frame["subject"].astype(str)
        frame["dept_group"] = subj.where(subj.isin(self.depts), "OTHER")
        design = design_matrix(frame)
        if design.empty:
            return out, used
        x = design.drop(columns=["duration_days", "event", "section_id"]).reindex(columns=self.columns, fill_value=0.0)
        ph = self.result.fitter.predict_partial_hazard(x).to_numpy(dtype=float)
        base = self.result.fitter.baseline_survival_
        times = base.index.to_numpy(dtype=float)
        surv = base.iloc[:, 0].to_numpy(dtype=float)
        pos = test.index.get_indexer(design.index)
        s0 = _step_at(times, surv, np.maximum(h[pos], 0.0))
        out[pos] = 1.0 - np.power(s0, ph)
        used[pos] = False
        return out, used


# --------------------------------------------------------------------- splits


def censor_at(cohort: pd.DataFrame, moment: pd.Timestamp) -> pd.DataFrame:
    """Rows as they were known at ``moment``: durations capped at ``moment - join_time``, events after it undone."""
    out = cohort.copy()
    cap = (pd.Timestamp(moment) - pd.to_datetime(out["join_time"], utc=True)).dt.total_seconds() / 86400.0
    over = out["duration_days"].astype(float) > cap
    out.loc[over, "event"] = 0
    out.loc[over, "duration_days"] = cap[over]
    out["duration_min"] = out["duration_days"] * 1440.0
    out = out[out["duration_days"] > 0]
    return out


def temporal_split(cohort: pd.DataFrame, split_at: pd.Timestamp, *, as_of: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    join = pd.to_datetime(cohort["join_time"], utc=True)
    train = cohort[join < split_at]
    test = cohort[join >= split_at]
    if as_of:
        train = censor_at(train, split_at)
    return train, test


def grouped_folds(cohort: pd.DataFrame, *, folds: int = 5, seed: int = 0) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """K folds by ``course_key``; a course is never in both halves of a fold."""
    courses = np.array(sorted(cohort["course_key"].astype(str).unique()))
    rng = np.random.default_rng(seed)
    assignment = dict(zip(courses[rng.permutation(len(courses))], np.arange(len(courses)) % folds))
    fold_of = cohort["course_key"].astype(str).map(assignment)
    return [(cohort[fold_of != k], cohort[fold_of == k]) for k in range(folds) if (fold_of == k).any()]


# ------------------------------------------------------------------- scoring


@dataclass
class BacktestResult:
    split: str
    which: str
    n_train: int
    n_test: int
    n_excluded: int  # test rows already past their horizon when they joined
    metrics: pd.DataFrame
    by_phase: pd.DataFrame
    by_bucket: pd.DataFrame
    calibration: pd.DataFrame
    predictions: pd.DataFrame
    notes: list[str] = field(default_factory=list)
    n_unobservable: int = 0  # test rows whose follow-up window ends before their horizon
    coverage: pd.DataFrame = field(default_factory=pd.DataFrame)  # per phase: rows, observable, share

    def as_dict(self) -> dict:
        return {
            "split": self.split,
            "which": self.which,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "n_excluded": self.n_excluded,
            "n_unobservable": self.n_unobservable,
            "coverage": self.coverage.to_dict(orient="records") if len(self.coverage) else [],
            "metrics": self.metrics.to_dict(orient="records"),
            "notes": self.notes,
        }


def _empty_result(split: str, which: str, n_train: int, n_test: int, notes: list[str], *, n_unobservable: int = 0, coverage: pd.DataFrame | None = None) -> BacktestResult:
    cols = ["predictor", "n_test", "brier_rows", "share_unknown", "brier", "auc", "brier_baseline", "gain", "gain_ci_low", "gain_ci_high", "skill", "share_fallback"]
    return BacktestResult(split, which, n_train, n_test, 0, pd.DataFrame(columns=cols), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), list(notes), n_unobservable, coverage if coverage is not None else pd.DataFrame())


def observability(test: pd.DataFrame, h: np.ndarray) -> tuple[np.ndarray, pd.DataFrame]:
    """``(observable mask, coverage by phase)``: a row is observable at its horizon
    when its follow-up window (``follow_up_days``; unlimited when the column is
    missing or NaN) reaches the horizon."""
    if "follow_up_days" in test:
        follow = pd.to_numeric(test["follow_up_days"], errors="coerce").to_numpy(dtype=float)
        follow = np.where(np.isnan(follow), np.inf, follow)
    else:
        follow = np.full(len(test), np.inf)
    ok = follow + 1e-9 >= h
    frame = pd.DataFrame({"phase": test["phase"].astype(str).to_numpy(), "observable": ok})
    cov = frame.groupby("phase").agg(n=("observable", "size"), observable=("observable", "sum")).reset_index()
    cov["share_observable"] = (cov["observable"] / cov["n"]).round(4)
    return ok, cov


def predict_all(train: pd.DataFrame, test: pd.DataFrame, calendar: TermCalendar, which: str, *, min_n: int = 30) -> tuple[pd.DataFrame, list[str]]:
    """Fit the four predictors on ``train`` and score every ``test`` row at its horizon."""
    notes: list[str] = []
    test = test.reset_index(drop=True)
    h = horizon_days(test, calendar, which).to_numpy(dtype=float)
    keep = h > 0
    excluded = int((~keep).sum())
    test = test[keep].reset_index(drop=True)
    h = h[keep]
    observable, coverage = observability(test, h)
    unobservable = int((~observable).sum())
    test = test[observable].reset_index(drop=True)
    h = h[observable]
    if len(test) == 0:
        empty = pd.DataFrame(columns=["section_id", "course_key", "position_bucket", "phase", "join_time", "duration_days", "event", "horizon_days", "p_bucket", "p_course", "course_level", "p_site", "site_fallback", "p_cox", "cox_fallback"])
        empty.attrs.update({"n_excluded": excluded, "n_unobservable": unobservable, "coverage": coverage})
        return empty, notes
    pooled = PooledKM(min_n=min_n).fit(train)
    p_bucket = pooled.predict_bucket(test, h)
    p_course, level = pooled.predict(test, h)
    p_site, site_fallback = pooled.predict_site(test)
    cox = CoxPredictor().fit(train)
    p_cox, cox_fallback = cox.predict(test, h, p_bucket)
    if cox.error:
        notes.append(f"Cox fit failed ({cox.error}); the cox column repeats the bucket baseline")
    pred = pd.DataFrame(
        {
            "section_id": test["section_id"].astype(str),
            "course_key": test["course_key"].astype(str),
            "position_bucket": test["position_bucket"].astype(str),
            "phase": test["phase"].astype(str),
            "join_time": pd.to_datetime(test["join_time"], utc=True),
            "duration_days": test["duration_days"].astype(float),
            "event": test["event"].astype(int),
            "horizon_days": h,
            "p_bucket": p_bucket,
            "p_course": p_course,
            "course_level": level,
            "p_site": p_site,
            "site_fallback": site_fallback,
            "p_cox": p_cox,
            "cox_fallback": cox_fallback,
        }
    )
    pred.attrs.update({"n_excluded": excluded, "n_unobservable": unobservable, "coverage": coverage})
    return pred, notes


def score(pred: pd.DataFrame, *, n_boot: int = 200, seed: int = 0, g_floor: float = G_FLOOR) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """``(metrics, by_phase, by_bucket, calibration)`` for the pooled predictions."""
    y, w = ipcw_weights(pred["duration_days"].to_numpy(), pred["event"].to_numpy(), pred["horizon_days"].to_numpy(), g_floor=g_floor)
    pred = pred.assign(y=y, w=w)
    base = pred[f"p_{BASELINE}"].to_numpy(dtype=float)
    b_base = brier(y, base, w)
    rows = []
    calib = []
    for name in PREDICTORS:
        p = pred[f"p_{name}"].to_numpy(dtype=float)
        b = brier(y, p, w)
        lo, hi = (0.0, 0.0) if name == BASELINE else bootstrap_gain(pred["section_id"].to_numpy(), y, p, base, w, n_boot=n_boot, seed=seed)
        fallback_col = f"{name}_fallback"
        rows.append(
            {
                "predictor": name,
                "n_test": int(len(pred)),
                "brier_rows": int((w > 0).sum()),
                "share_unknown": round(float((w == 0).mean()), 4) if len(pred) else float("nan"),
                "brier": b,
                "auc": weighted_auc(y, p, w),
                "brier_baseline": b_base,
                "gain": b_base - b,
                "gain_ci_low": lo,
                "gain_ci_high": hi,
                "skill": (1.0 - b / b_base) if b_base and np.isfinite(b_base) and b_base > 0 else float("nan"),
                "share_fallback": round(float(pred[fallback_col].mean()), 4) if fallback_col in pred else 0.0,
            }
        )
        c = calibration_table(y, p, w)
        c.insert(0, "predictor", name)
        calib.append(c)
    metrics = pd.DataFrame(rows)

    def _by(col: str, order: list[str] | None = None) -> pd.DataFrame:
        out = []
        keys = [k for k in (order or []) if k in set(pred[col])] + sorted(set(pred[col]) - set(order or []))
        for key in keys:
            m = (pred[col] == key).to_numpy()
            row = {col: key, "n": int(m.sum()), "share_unknown": round(float((w[m] == 0).mean()), 4)}
            for name in PREDICTORS:
                row[f"brier_{name}"] = brier(y[m], pred.loc[m, f"p_{name}"].to_numpy(dtype=float), w[m])
            out.append(row)
        return pd.DataFrame(out)

    return metrics, _by("phase"), _by("position_bucket", list(BUCKET_ORDER)), pd.concat(calib, ignore_index=True) if calib else pd.DataFrame()


def run_backtest(
    cohort: pd.DataFrame,
    calendar: TermCalendar,
    *,
    split: str = "temporal",
    which: str = "deadline",
    split_at: pd.Timestamp | None = None,
    train_cohort: pd.DataFrame | None = None,
    folds: int = 5,
    n_boot: int = 200,
    seed: int = 0,
    min_n: int = 30,
    g_floor: float = G_FLOOR,
    as_of: bool = True,
) -> BacktestResult:
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; expected one of {SPLITS}")
    cohort = cohort.reset_index(drop=True)
    pairs: list[tuple[pd.DataFrame, pd.DataFrame]]
    notes: list[str] = [f"IPCW weights floored at G >= {g_floor}; Brier self-normalised by the weights; AUC is the weighted Mann-Whitney statistic; intervals from {n_boot} section bootstraps"]
    if split == "temporal":
        if split_at is None:
            d = calendar.phase2_start
            split_at = pd.Timestamp(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
        pairs = [temporal_split(cohort, pd.Timestamp(split_at), as_of=as_of)]
        notes.append(f"temporal split at {pd.Timestamp(split_at).isoformat()}; training rows {'censored at the split' if as_of else 'kept with their full follow-up'}")
    elif split == "grouped":
        pairs = grouped_folds(cohort, folds=folds, seed=seed)
        notes.append(f"{len(pairs)} folds grouped by course; every row scored once out of fold")
    else:
        if train_cohort is None:
            raise ValueError("cross_term needs train_cohort")
        pairs = [(train_cohort.reset_index(drop=True), cohort)]
        notes.append("cross-term: fit on the training cohort, scored on this term")
    preds: list[pd.DataFrame] = []
    coverages: list[pd.DataFrame] = []
    n_train = 0
    excluded = 0
    unobservable = 0
    for train, test in pairs:
        n_train += len(train)
        if len(train) < MIN_TRAIN_ROWS or int(train["event"].sum()) < MIN_TRAIN_EVENTS or len(test) == 0:
            notes.append(f"skipped a fold: {len(train)} training rows with {int(train['event'].sum()) if len(train) else 0} events, {len(test)} test rows")
            continue
        pred, fold_notes = predict_all(train, test, calendar, which, min_n=min_n)
        excluded += int(pred.attrs.get("n_excluded", 0))
        unobservable += int(pred.attrs.get("n_unobservable", 0))
        cov = pred.attrs.get("coverage")
        if cov is not None and len(cov):
            coverages.append(cov)
        pred.attrs = {}  # the coverage frame must not ride along into the parquet metadata
        notes.extend(fold_notes)
        if len(pred):
            preds.append(pred)
    coverage = pd.DataFrame()
    if coverages:
        coverage = pd.concat(coverages).groupby("phase", as_index=False)[["n", "observable"]].sum()
        coverage["share_observable"] = (coverage["observable"] / coverage["n"]).round(4)
    if unobservable:
        notes.append(f"{unobservable} test rows could not be followed to their horizon (a gap or the end of the data came first) and were not scored; see coverage by phase")
    if not preds or sum(len(p) for p in preds) < MIN_TEST_ROWS:
        n_test = sum(len(p) for p in preds)
        return _empty_result(split, which, n_train, n_test, notes + [f"too few scored rows ({n_test}); need {MIN_TEST_ROWS}"], n_unobservable=unobservable, coverage=coverage)
    pred = pd.concat(preds, ignore_index=True)
    metrics, by_phase, by_bucket, calibration = score(pred, n_boot=n_boot, seed=seed, g_floor=g_floor)
    return BacktestResult(split, which, n_train, int(len(pred)), excluded, metrics, by_phase, by_bucket, calibration, pred, notes, unobservable, coverage)


# -------------------------------------------------------------------- report


def _md(frame: pd.DataFrame) -> str:
    if frame is None or len(frame) == 0:
        return "_none_"
    shown = frame.copy()
    for col in shown.columns:
        if shown[col].dtype.kind == "f":
            shown[col] = shown[col].map(lambda v: f"{v:.3f}" if pd.notna(v) else "")
    cols = [str(c) for c in shown.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, row in shown.iterrows():
        lines.append("| " + " | ".join(str(v) for v in row.tolist()) + " |")
    return "\n".join(lines)


def write_report(result: BacktestResult, out_dir: Path | str, *, title: str = "") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result.metrics.to_csv(out_dir / "metrics.csv", index=False)
    result.by_phase.to_csv(out_dir / "by_phase.csv", index=False)
    result.by_bucket.to_csv(out_dir / "by_bucket.csv", index=False)
    result.calibration.to_csv(out_dir / "calibration.csv", index=False)
    result.coverage.to_csv(out_dir / "coverage.csv", index=False)
    if len(result.predictions):
        result.predictions.to_parquet(out_dir / "predictions.parquet", index=False)
    lines = [
        f"# Backtest: {title or result.split} ({result.which})",
        "",
        f"Split `{result.split}`, horizon `{result.which}`: {result.n_train} training rows, {result.n_test} scored test rows, {result.n_excluded} test rows past their horizon at joining and {result.n_unobservable} whose follow-up ended before their horizon (neither scored).",
        "",
        "## Coverage: test rows that could be followed to their horizon, by phase",
        "",
        _md(result.coverage),
        "",
        "Every number here is produced by `python -m analysis.backtest`; nothing is edited by hand. `gain` is the baseline's Brier score minus the predictor's (positive is better) with a 95% section-bootstrap interval; `skill` is `1 - brier / brier_baseline`; `share_unknown` is the share of test rows censored before their horizon (weight 0 under IPCW); `share_fallback` is the share of rows the predictor could not cover and scored with the bucket baseline.",
        "",
        "## Predictors",
        "",
        _md(result.metrics),
        "",
        "## By enrollment phase of the test rows",
        "",
        _md(result.by_phase),
        "",
        "## By position bucket",
        "",
        _md(result.by_bucket),
        "",
    ]
    for name in ("cox", "site"):
        sub = result.calibration[result.calibration["predictor"] == name] if len(result.calibration) else pd.DataFrame()
        lines += [f"## Calibration: {name}", "", _md(sub.drop(columns=["predictor"]) if len(sub) else sub), ""]
    if result.notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in result.notes] + [""]
    path = out_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    try:
        from analysis.figures import plot_calibration

        cox_cal = result.calibration[result.calibration["predictor"] == "cox"] if len(result.calibration) else pd.DataFrame()
        if len(cox_cal):
            b = float(result.metrics.set_index("predictor").at["cox", "brier"])
            plot_calibration(cox_cal.drop(columns=["predictor"]), out_dir / "calibration_cox.png", brier=b)
    except Exception as exc:  # noqa: BLE001 - the figure is a convenience
        logger.warning("calibration figure skipped: %s", exc)
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backtest the waitlist-clearing predictors on a cohort parquet.")
    p.add_argument("--cohort", type=Path, required=True, help="cohort_central.parquet from analysis.run")
    p.add_argument("--term-id", required=True)
    p.add_argument("--split", choices=SPLITS, default="temporal")
    p.add_argument("--which", default="deadline", help="deadline | instruction | days:N")
    p.add_argument("--split-date", default=None, help="temporal: YYYY-MM-DD (default: Phase 2 start)")
    p.add_argument("--train-cohort", type=Path, default=None, help="cross_term: the other term's cohort parquet")
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--bootstrap", type=int, default=200)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--min-n", type=int, default=30)
    p.add_argument("--no-as-of", action="store_true", help="temporal: do not censor training rows at the split date")
    p.add_argument("--out", type=Path, default=None, help="report dir (default reports/backtest_<term>/<split>_<which>)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    calendar = calendar_for(args.term_id)
    cohort = pd.read_parquet(args.cohort)
    train_cohort = pd.read_parquet(args.train_cohort) if args.train_cohort else None
    split_at = pd.Timestamp(args.split_date, tz="UTC") if args.split_date else None
    result = run_backtest(
        cohort,
        calendar,
        split=args.split,
        which=args.which,
        split_at=split_at,
        train_cohort=train_cohort,
        folds=args.folds,
        n_boot=args.bootstrap,
        seed=args.seed,
        min_n=args.min_n,
        as_of=not args.no_as_of,
    )
    out = args.out or Path("reports") / f"backtest_{args.term_id}" / f"{args.split}_{args.which.replace(':', '')}"
    path = write_report(result, out, title=f"{calendar.name} {args.split}")
    print(json.dumps({"report": str(path), **result.as_dict()}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
