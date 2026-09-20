"""Precomputed lookup tables for the static site. See docs/DESIGN_A5.md section 4.

Each course and position bucket gets the Kaplan-Meier clearing curve of its
virtual waitlisters on a fixed grid of days since joining, out to the longest
follow-up the cell has (``reach_days``), with a 95% band from resampling
sections (not rows: the rows of one section are copies of the same queue).
The page reads the curve at the asker's own days remaining before the last
automatic waitlist run and before the first day of instruction, so one
export serves a student asking in Phase 1 and one asking two days before
class. ``p_clear_by_instruction`` (the curve at the cell's median lead time)
is kept for the report.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.calendar import TermCalendar
from analysis.survival import BUCKET_ORDER

logger = logging.getLogger(__name__)

MIN_N = 30
N_BOOT = 200
# What the page serves. "dept": the department-by-bucket curve for every course (the course's own
# counts alongside); "course": the course's own curve when it has MIN_N rows, else the department's.
# The Fall 2026 backtest found course cells no better than the bucket baseline out of time
# (Brier gain -0.023 [-0.034, -0.011]) and indistinguishable across held-out courses, so dept is
# the default until a second cycle says otherwise (docs/dev/BACKFILL_BACKTEST.md B3).
LEVELS = ("dept", "course")
DEFAULT_LEVEL = "dept"
CURVE_DAYS = (0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 21, 24, 28, 32, 36, 42, 49, 56, 63, 70, 77, 84, 98, 112, 126, 140, 154, 168, 182)


def km_clear_at(durations: np.ndarray, events: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """P(cleared by each day in ``grid``) from the Kaplan-Meier estimate, in numpy
    (the exporter fits tens of thousands of bootstrap curves)."""
    d = np.asarray(durations, dtype=float)
    e = np.asarray(events, dtype=int)
    if len(d) == 0:
        return np.zeros(len(grid))
    order = np.argsort(d, kind="mergesort")
    d, e = d[order], e[order]
    times, first, _ = np.unique(d, return_index=True, return_counts=True)
    at_risk = len(d) - first
    deaths = np.add.reduceat(e, first)
    surv = np.cumprod(1.0 - deaths / at_risk)
    idx = np.searchsorted(times, np.asarray(grid, dtype=float), side="right") - 1
    s = np.where(idx >= 0, surv[np.clip(idx, 0, None)], 1.0)
    return 1.0 - s


def median_clear_days(durations: np.ndarray, events: np.ndarray) -> float | None:
    """First day at which the KM clearing probability reaches one half; None if it never does."""
    d = np.asarray(durations, dtype=float)
    e = np.asarray(events, dtype=int)
    if len(d) == 0:
        return None
    times = np.unique(d[e == 1])
    if len(times) == 0:
        return None
    p = km_clear_at(d, e, times)
    hit = np.flatnonzero(p >= 0.5)
    return float(times[hit[0]]) if len(hit) else None


def section_bootstrap_band(rows: pd.DataFrame, grid: np.ndarray, *, n_boot: int = N_BOOT, seed: int = 0) -> tuple[np.ndarray, np.ndarray] | None:
    """2.5th and 97.5th percentiles of the clearing curve over resamples of sections; None below two sections."""
    sections = rows.groupby("section_id", observed=True).indices
    keys = list(sections)
    if len(keys) < 2 or n_boot <= 0:
        return None
    rng = np.random.default_rng(seed)
    d = rows["duration_days"].to_numpy(dtype=float)
    e = rows["event"].to_numpy(dtype=int)
    idx_lists = [np.asarray(sections[k]) for k in keys]
    curves = np.empty((n_boot, len(grid)))
    for b in range(n_boot):
        pick = rng.integers(0, len(idx_lists), len(idx_lists))
        idx = np.concatenate([idx_lists[i] for i in pick])
        curves[b] = km_clear_at(d[idx], e[idx], grid)
    return np.percentile(curves, 2.5, axis=0), np.percentile(curves, 97.5, axis=0)


def _grid(reach_days: float) -> np.ndarray:
    days = [d for d in CURVE_DAYS if d <= reach_days]
    if not days or days[-1] < reach_days:
        days.append(round(float(reach_days), 2))
    return np.asarray(days, dtype=float)


def _estimate(rows: pd.DataFrame, horizon_days: float, *, n_boot: int = N_BOOT) -> dict:
    d = rows["duration_days"].to_numpy(dtype=float)
    e = rows["event"].to_numpy(dtype=int)
    reach = float(d.max())
    grid = _grid(reach)
    p = km_clear_at(d, e, grid)
    band = section_bootstrap_band(rows, grid, n_boot=n_boot)
    curve = []
    for i, day in enumerate(grid):
        point = [float(day), round(float(p[i]), 3)]
        if band is not None:
            point += [round(float(band[0][i]), 3), round(float(band[1][i]), 3)]
        else:
            point += [None, None]
        curve.append(point)
    p_by_horizon = float(km_clear_at(d, e, np.array([max(horizon_days, 0.0)]))[0])
    median = median_clear_days(d, e)
    return {
        "p_clear_by_instruction": round(p_by_horizon, 2),  # at the cell's median lead time; the page reads the curve instead
        "horizon_days": round(max(horizon_days, 0.0), 1),
        "median_days": None if median is None else round(median, 2),
        "n": int(len(rows)),
        "events": int(e.sum()),
        "sections": int(rows["section_id"].nunique()),
        "reach_days": round(reach, 1),
        "curve": curve,  # [days since joining, P(cleared by then), 95% low, 95% high] out to the longest follow-up
    }


def course_tables(cohort: pd.DataFrame, calendar: TermCalendar, *, min_n: int = MIN_N, n_boot: int = N_BOOT, level: str = DEFAULT_LEVEL) -> dict:
    """``{course_key: {subject, level, buckets: {bucket: cell}}}`` (cell fields in ``_estimate``).

    ``horizon_days`` is the median ``days_to_instruction`` of the rows in the
    cell. With ``level="dept"`` every cell is the department-level estimate for
    the bucket, marked ``pooled: <dept>`` with ``n_course`` and
    ``sections_course`` for the course alone; with ``level="course"`` a cell
    with at least ``min_n`` rows is the course's own curve (``pooled: false``)
    and smaller cells fall back to the department. A department cell that is
    itself too small falls back to the whole cohort's bucket (``pooled: "all"``).
    """
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    out: dict = {}
    if cohort.empty:
        return out
    by_dept_bucket = {k: g for k, g in cohort.groupby(["dept_group", "position_bucket"], observed=True)}
    by_bucket = {k: g for k, g in cohort.groupby("position_bucket", observed=True)}
    cache: dict = {}

    def pooled_estimate(key: tuple, pool: pd.DataFrame, horizon: float) -> dict:
        # the pool's curve does not depend on the course; only the horizon field does
        if key not in cache:
            cache[key] = _estimate(pool, horizon, n_boot=n_boot)
        cell = dict(cache[key])
        cell["p_clear_by_instruction"] = round(float(km_clear_at(pool["duration_days"].to_numpy(dtype=float), pool["event"].to_numpy(dtype=int), np.array([max(horizon, 0.0)]))[0]), 2)
        cell["horizon_days"] = round(max(horizon, 0.0), 1)
        return cell

    for course_key, course_rows in cohort.groupby("course_key", sort=True, observed=True):
        dept = str(course_rows["dept_group"].iloc[0])
        cells: dict = {}
        for bucket in BUCKET_ORDER:
            rows = course_rows[course_rows["position_bucket"] == bucket]
            if len(rows) == 0:
                continue
            horizon = float(rows["days_to_instruction"].median())
            if level == "course" and len(rows) >= min_n:
                cell = _estimate(rows, horizon, n_boot=n_boot)
                cell["pooled"] = False
            else:
                pool = by_dept_bucket.get((dept, bucket))
                if pool is not None and len(pool) >= min_n:
                    cell = pooled_estimate(("dept", dept, bucket), pool, horizon)
                    cell["pooled"] = dept
                else:
                    pool = by_bucket.get(bucket)
                    if pool is None or len(pool) < min_n:
                        continue
                    cell = pooled_estimate(("all", bucket), pool, horizon)
                    cell["pooled"] = "all"
                cell["n_course"] = int(len(rows))
                cell["sections_course"] = int(rows["section_id"].nunique())
            cells[bucket] = cell
        if cells:
            out[str(course_key)] = {
                "subject": str(course_rows["subject"].iloc[0]),
                "level": None if pd.isna(course_rows["level"].iloc[0]) else str(course_rows["level"].iloc[0]),
                "buckets": cells,
            }
    return out


def export_site_tables(
    cohort: pd.DataFrame,
    calendar: TermCalendar,
    out_dir: Path | str,
    *,
    meta: dict | None = None,
    min_n: int = MIN_N,
    n_boot: int = N_BOOT,
    level: str = DEFAULT_LEVEL,
) -> tuple[Path, Path]:
    """Write ``courses.json`` and ``meta.json`` under ``out_dir``; returns both paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    courses = course_tables(cohort, calendar, min_n=min_n, n_boot=n_boot, level=level)
    courses_path = out_dir / "courses.json"
    courses_path.write_text(json.dumps(courses, indent=0, sort_keys=True), encoding="utf-8")
    info = {
        "term_id": calendar.term_id,
        "term_name": calendar.name,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "courses": len(courses),
        "cohort_rows": int(len(cohort)),
        "events": int(cohort["event"].sum()) if len(cohort) else 0,
        "sections": int(cohort["section_id"].nunique()) if len(cohort) else 0,
        "join_window": None
        if cohort.empty
        else [cohort["join_time"].min().isoformat(timespec="seconds"), cohort["join_time"].max().isoformat(timespec="seconds")],
        "scenario": None if cohort.empty else str(cohort["scenario"].iloc[0]),
        "min_n": min_n,
        "n_boot": n_boot,
        "estimate_level": level,
        "positions": sorted(int(p) for p in cohort["position"].unique()) if len(cohort) else [],
        "instruction_start": calendar.instruction_start.isoformat(),
        "deadline": calendar.last_auto_waitlist.isoformat(),  # last automatic waitlist run (the page's headline horizon)
        "add_drop_deadline": calendar.add_drop_deadline.isoformat(),
    }
    if meta:
        info.update(meta)
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps(info, indent=1, sort_keys=True), encoding="utf-8")
    logger.info("wrote %s (%d courses) and %s", courses_path, len(courses), meta_path)
    return courses_path, meta_path
