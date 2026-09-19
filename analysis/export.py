"""Precomputed lookup tables for the static site. See docs/DESIGN_A5.md section 4."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter

from analysis.calendar import TermCalendar
from analysis.survival import BUCKET_ORDER

logger = logging.getLogger(__name__)

MIN_N = 30


def _km(durations: pd.Series, events: pd.Series) -> KaplanMeierFitter:
    return KaplanMeierFitter().fit(durations.to_numpy(dtype=float), event_observed=events.to_numpy(dtype=int))


CURVE_DAYS = (1, 2, 3, 5, 7, 10, 14, 21, 28, 42, 56)


def _estimate(rows: pd.DataFrame, horizon_days: float) -> dict:
    kmf = _km(rows["duration_days"], rows["event"])
    p_by_horizon = float(1.0 - kmf.predict(max(horizon_days, 0.0)))
    median = float(kmf.median_survival_time_)
    last = float(rows["duration_days"].max())
    curve = [[d, round(float(1.0 - kmf.predict(float(d))), 3)] for d in CURVE_DAYS if d <= last]
    return {
        "p_clear_by_instruction": round(p_by_horizon, 2),
        "horizon_days": round(max(horizon_days, 0.0), 1),
        "median_days": None if not np.isfinite(median) else round(median, 2),
        "n": int(len(rows)),
        "events": int(rows["event"].sum()),
        "curve": curve,  # [days since joining, P(cleared by then)] up to the longest follow-up
    }


def course_tables(cohort: pd.DataFrame, calendar: TermCalendar, *, min_n: int = MIN_N) -> dict:
    """``{course_key: {bucket: {p_clear_by_instruction, median_days, n, events, pooled}}}``.

    The horizon is the median ``days_to_instruction`` of the rows in the cell
    (how long those joiners had before instruction started). Cells with fewer
    than ``min_n`` rows fall back to the department-level estimate for the same
    bucket and are marked ``pooled``; a department cell that is itself too
    small falls back to the whole cohort's bucket estimate (``pooled: "all"``).
    """
    out: dict = {}
    if cohort.empty:
        return out
    by_dept_bucket = {k: g for k, g in cohort.groupby(["dept_group", "position_bucket"], observed=True)}
    by_bucket = {k: g for k, g in cohort.groupby("position_bucket", observed=True)}
    for course_key, course_rows in cohort.groupby("course_key", sort=True, observed=True):
        dept = str(course_rows["dept_group"].iloc[0])
        cells: dict = {}
        for bucket in BUCKET_ORDER:
            rows = course_rows[course_rows["position_bucket"] == bucket]
            if len(rows) == 0:
                continue
            horizon = float(rows["days_to_instruction"].median())
            if len(rows) >= min_n:
                cell = _estimate(rows, horizon)
                cell["pooled"] = False
            else:
                pool = by_dept_bucket.get((dept, bucket))
                if pool is not None and len(pool) >= min_n:
                    cell = _estimate(pool, horizon)
                    cell["pooled"] = dept
                else:
                    pool = by_bucket.get(bucket)
                    if pool is None or len(pool) < min_n:
                        continue
                    cell = _estimate(pool, horizon)
                    cell["pooled"] = "all"
                cell["n_course"] = int(len(rows))
            cells[bucket] = cell
        if cells:
            out[str(course_key)] = {
                "subject": str(course_rows["subject"].iloc[0]),
                "level": None if pd.isna(course_rows["level"].iloc[0]) else str(course_rows["level"].iloc[0]),
                "buckets": cells,
            }
    return out


def export_site_tables(cohort: pd.DataFrame, calendar: TermCalendar, out_dir: Path | str, *, meta: dict | None = None, min_n: int = MIN_N) -> tuple[Path, Path]:
    """Write ``courses.json`` and ``meta.json`` under ``out_dir``; returns both paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    courses = course_tables(cohort, calendar, min_n=min_n)
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
        "instruction_start": calendar.instruction_start.isoformat(),
    }
    if meta:
        info.update(meta)
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps(info, indent=1, sort_keys=True), encoding="utf-8")
    logger.info("wrote %s (%d courses) and %s", courses_path, len(courses), meta_path)
    return courses_path, meta_path
