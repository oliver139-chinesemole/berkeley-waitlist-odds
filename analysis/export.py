"""Precomputed lookup tables for the static site. See docs/DESIGN_A5.md section 4.

Files written under ``out_dir`` (``site/data``):

- ``meta.json``: the data term, the forecast term whose calendar the pages use
  for horizons, counts, the data window, ``data_source`` and the file map.
- ``index.json``: one row per course with, per position bucket, the share who
  got in within 7, 14 and 28 days and at the cell's reach (each with its 95%
  band), the median, counts, the pooled flag, and the reconstructed waitlist
  joins the pages rank courses by. Drives search, the Courses table and the
  related-courses list; small enough to load on a phone.
- ``courses/<SUBJECT>.json``: per course and bucket, a pointer to the pool
  that stands in for it plus the course's own counts; at
  ``estimate_level="course"`` a cell with ``min_n`` rows or more carries its
  own curve instead. Loaded on demand.
- ``pooled.json``: department, level and all-course cells per bucket, with
  curves. The fallback for pooled cells and for courses with no data.
- ``insights.json``: all-course curves by bucket, the hero cut (lower-division
  courses, Phase 1 joiners), level and phase grids, and, when flows are given,
  daily admits, joins and drops and how waitlisters left the queue.

Every cell is the Kaplan-Meier clearing curve of its virtual waitlisters on a
fixed grid of days since joining, out to the longest follow-up the cell has
(``reach_days``), with a 95% band from resampling sections (not rows: the rows
of one section are copies of the same queue). The pages read a curve as a step
function at the asker's own days left (``read_curve``): the last grid point at
or before the horizon; past the reach the last point stands, as a floor. The
pages compute no statistic of their own.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.calendar import TermCalendar, calendar_for
from analysis.survival import BUCKET_ORDER

logger = logging.getLogger(__name__)

MIN_N = 30
N_BOOT = 200
CURVE_DAYS = (0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 21, 24, 28, 32, 36, 42, 49, 56, 63, 70, 77, 84, 98, 112, 126, 140, 154, 168, 182)
HORIZONS = (7.0, 14.0, 28.0)  # the fixed horizons index.json and the grids carry
# What a course's estimate is by default. "dept": the department's curve for the
# bucket (the Fall 2026 backtest found course-level curves did not beat the
# position-bucket baseline, docs/dev/BACKFILL_BACKTEST.md B3); "course": the
# course's own curve when it has min_n rows, kept for later terms.
ESTIMATE_LEVELS = ("dept", "course")
DEFAULT_ESTIMATE_LEVEL = "dept"
LEVEL_ORDER = ("lower", "upper", "grad")
PHASE_ORDER = ("before", "phase1", "between", "phase2", "adjustment", "instruction", "after")
META_CARRY = ("data_source", "flows", "backfill", "cohort_rows_by_scenario", "prereg_commit", "prereg_date")
CALENDAR_FIELDS = ("phase1_start", "phase1_end", "phase2_start", "phase2_end", "adjustment_start", "instruction_start", "last_auto_waitlist", "add_drop_deadline")


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


def read_curve(curve: list, h: float) -> tuple[float, float | None, float | None, float]:
    """The pages' rule: ``(p, low, high, day)`` at the last grid point at or before
    ``h`` days; ``(0, None, None, 0)`` before the first point; past the reach the
    last point stands (a floor)."""
    pt = None
    for c in curve:
        if c[0] <= h:
            pt = c
        else:
            break
    if pt is None:
        return 0.0, None, None, 0.0
    return float(pt[1]), pt[2], pt[3], float(pt[0])


def _grid(reach_days: float) -> np.ndarray:
    days = [d for d in CURVE_DAYS if d <= reach_days]
    if not days or days[-1] < reach_days:
        days.append(round(float(reach_days), 2))
    return np.asarray(days, dtype=float)


def _cell(rows: pd.DataFrame, *, n_boot: int = N_BOOT) -> dict:
    """One curve cell: the KM clearing curve with its band, the reach, the median and the counts."""
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
    median = median_clear_days(d, e)
    return {
        "curve": curve,  # [days since joining, P(got in by then), 95% low, 95% high] out to the longest follow-up
        "reach_days": round(reach, 1),
        "median_days": None if median is None else round(median, 2),
        "n": int(len(rows)),
        "events": int(e.sum()),
        "sections": int(rows["section_id"].nunique()),
    }


def _summary(cell: dict) -> dict:
    """The cell without its curve: the share at each fixed horizon and at the reach, the median and the counts."""
    p, lo, hi = [], [], []
    for h in HORIZONS:
        v = read_curve(cell["curve"], h)
        p.append(v[0])
        lo.append(v[1])
        hi.append(v[2])
    last = cell["curve"][-1]
    return {
        "p": p,  # at HORIZONS; a horizon past reach_days reads the reach (a floor)
        "lo": lo,
        "hi": hi,
        "reach": [last[1], cell["reach_days"]],  # [share at the reach, reach in days]
        "median_days": cell["median_days"],
        "n": cell["n"],
        "events": cell["events"],
        "sections": cell["sections"],
    }


def _ordered(keys: list[str], order: tuple[str, ...]) -> list[str]:
    known = [k for k in order if k in keys]
    return known + sorted(k for k in keys if k not in order)


def pool_tables(cohort: pd.DataFrame, *, min_n: int = MIN_N, n_boot: int = N_BOOT) -> dict:
    """``{"all": {bucket: cell}, "dept": {dept_group: {bucket: cell}}, "level": {level: {bucket: cell}}}``
    for every pool with ``min_n`` rows or more."""
    pools: dict = {"all": {}, "dept": {}, "level": {}}
    if cohort.empty:
        return pools
    for bucket, g in cohort.groupby("position_bucket", observed=True):
        if len(g) >= min_n:
            pools["all"][str(bucket)] = _cell(g, n_boot=n_boot)
    for (dept, bucket), g in cohort.groupby(["dept_group", "position_bucket"], observed=True):
        if len(g) >= min_n:
            pools["dept"].setdefault(str(dept), {})[str(bucket)] = _cell(g, n_boot=n_boot)
    for (level, bucket), g in cohort.groupby(["level", "position_bucket"], observed=True):
        if len(g) >= min_n:
            pools["level"].setdefault(str(level), {})[str(bucket)] = _cell(g, n_boot=n_boot)
    return pools


def resolve_pool(pools: dict, pooled: str, bucket: str) -> dict | None:
    """The pool cell a pooled course cell points at (a department name or ``"all"``)."""
    if pooled == "all":
        return pools["all"].get(bucket)
    return pools["dept"].get(pooled, {}).get(bucket)


def course_tables(cohort: pd.DataFrame, calendar: TermCalendar, *, min_n: int = MIN_N, n_boot: int = N_BOOT, pools: dict | None = None, estimate_level: str = DEFAULT_ESTIMATE_LEVEL) -> dict:
    """``{course_key: {subject, number, level, dept_group, buckets: {bucket: cell}}}``.

    A pointer cell names in ``pooled`` the department whose curve for the same
    bucket stands in, or ``"all"`` when the department pool is itself too
    small, with ``n_course`` and ``sections_course`` for the course alone. At
    ``estimate_level="dept"`` (the default) every cell is a pointer. At
    ``"course"`` a cell with ``min_n`` rows or more is a curve cell (``_cell``)
    with ``pooled: false`` and only smaller cells are pointers. A cell with no
    pool is left out.
    """
    if estimate_level not in ESTIMATE_LEVELS:
        raise ValueError(f"estimate_level must be one of {ESTIMATE_LEVELS}, got {estimate_level!r}")
    out: dict = {}
    if cohort.empty:
        return out
    if pools is None:
        pools = pool_tables(cohort, min_n=min_n, n_boot=n_boot)
    for course_key, course_rows in cohort.groupby("course_key", sort=True, observed=True):
        dept = str(course_rows["dept_group"].iloc[0])
        cells: dict = {}
        for bucket in BUCKET_ORDER:
            rows = course_rows[course_rows["position_bucket"] == bucket]
            if len(rows) == 0:
                continue
            if estimate_level == "course" and len(rows) >= min_n:
                cell = _cell(rows, n_boot=n_boot)
                cell["pooled"] = False
            else:
                if bucket in pools["dept"].get(dept, {}):
                    pooled = dept
                elif bucket in pools["all"]:
                    pooled = "all"
                else:
                    continue
                cell = {"pooled": pooled, "n_course": int(len(rows)), "sections_course": int(rows["section_id"].nunique())}
            cells[bucket] = cell
        if cells:
            level = course_rows["level"].iloc[0]
            out[str(course_key)] = {
                "subject": str(course_rows["subject"].iloc[0]),
                "number": str(course_rows["catalog_number"].iloc[0]),
                "level": None if pd.isna(level) else str(level),
                "dept_group": dept,
                "buckets": cells,
            }
    return out


def joins_by_course(cohort: pd.DataFrame, flows: pd.DataFrame | None) -> dict[str, int]:
    """Reconstructed waitlist joins per course (the rank behind the example chips), from
    the flows of the sections the cohort knows; empty without flows."""
    if flows is None or flows.empty or cohort.empty or "wl_joins" not in flows.columns:
        return {}
    section_course = cohort[["section_id", "course_key"]].drop_duplicates("section_id")
    merged = flows[["section_id", "wl_joins"]].merge(section_course, on="section_id", how="inner")
    totals = merged.groupby("course_key", observed=True)["wl_joins"].sum()
    return {str(k): int(v) for k, v in totals.items()}


def index_rows(courses: dict, pools: dict, joins: dict[str, int] | None = None) -> list[dict]:
    """One compact row per course for ``index.json``; pooled cells carry the pool's numbers plus the course's own counts."""
    rows = []
    for key, entry in courses.items():
        buckets: dict = {}
        for bucket, cell in entry["buckets"].items():
            if cell["pooled"] is False:
                s = _summary(cell)
            else:
                pool = resolve_pool(pools, cell["pooled"], bucket)
                if pool is None:
                    continue
                s = _summary(pool)
                s["n_course"] = cell["n_course"]
                s["sections_course"] = cell["sections_course"]
            s["pooled"] = cell["pooled"]
            buckets[bucket] = s
        rows.append(
            {
                "key": key,
                "subject": entry["subject"],
                "number": entry["number"],
                "level": entry["level"],
                "dept_group": entry["dept_group"],
                "joins": int(joins.get(key, 0)) if joins else None,
                "buckets": buckets,
            }
        )
    return rows


def _grid_of(cells: dict) -> dict:
    return {k: _summary(c) for k, c in cells.items()}


def insights_tables(cohort: pd.DataFrame, pools: dict, *, min_n: int = MIN_N, n_boot: int = N_BOOT, flows: pd.DataFrame | None = None) -> dict:
    """Term-wide tables for the Insights page (see the module docstring)."""
    out: dict = {
        "horizons": list(HORIZONS),
        "counts": {
            "rows": int(len(cohort)),
            "events": int(cohort["event"].sum()) if len(cohort) else 0,
            "sections": int(cohort["section_id"].nunique()) if len(cohort) else 0,
            "courses": int(cohort["course_key"].nunique()) if len(cohort) else 0,
        },
        "all_by_bucket": {b: pools["all"][b] for b in _ordered(list(pools["all"]), BUCKET_ORDER)},
        "by_level": {lvl: _grid_of(pools["level"][lvl]) for lvl in _ordered(list(pools["level"]), LEVEL_ORDER)},
        "hero": {},
        "by_phase": {},
    }
    if cohort.empty:
        return out
    hero_rows = cohort[(cohort["level"] == "lower") & (cohort["phase"] == "phase1")]
    for bucket, g in hero_rows.groupby("position_bucket", observed=True):
        if len(g) >= min_n:
            out["hero"][str(bucket)] = _cell(g, n_boot=n_boot)
    out["hero"] = {b: out["hero"][b] for b in _ordered(list(out["hero"]), BUCKET_ORDER)}
    by_phase: dict = {}
    for (phase, bucket), g in cohort.groupby(["phase", "position_bucket"], observed=True):
        if len(g) >= min_n:
            by_phase.setdefault(str(phase), {})[str(bucket)] = _summary(_cell(g, n_boot=n_boot))
    out["by_phase"] = {p: by_phase[p] for p in _ordered(list(by_phase), PHASE_ORDER)}
    if flows is not None and len(flows) and {"t1", "admits", "wl_joins", "wl_drops"} <= set(flows.columns):
        f = flows.copy()
        f["day"] = pd.to_datetime(f["t1"], utc=True).dt.strftime("%Y-%m-%d")
        daily = f.groupby("day").agg(admits=("admits", "sum"), joins=("wl_joins", "sum"), drops=("wl_drops", "sum"), intervals=("admits", "size"))
        if "censored" in f.columns:
            daily["share_censored"] = f.groupby("day")["censored"].mean()
        out["daily"] = [
            {
                "date": str(day),
                "admits": int(r["admits"]),
                "joins": int(r["joins"]),
                "drops": int(r["drops"]),
                "intervals": int(r["intervals"]),
                "share_censored": round(float(r["share_censored"]), 3) if "share_censored" in daily.columns else None,
            }
            for day, r in daily.sort_index().iterrows()
        ]
        last = f.sort_values("t1").groupby("section_id", observed=True).tail(1)
        still = (last["waitlist0"] + last["d_waitlist"]).clip(lower=0).sum() if {"waitlist0", "d_waitlist"} <= set(last.columns) else None
        out["exits"] = {
            "admitted": int(f["admits"].sum()),
            "dropped": int(f["wl_drops"].sum()),
            "still_waiting": None if still is None else int(still),
        }
    return out


def _subject_file(subject: str) -> str:
    return "courses/" + re.sub(r"[^A-Z0-9]+", "_", subject.upper()).strip("_") + ".json"


def _dump(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=0, sort_keys=True, allow_nan=False), encoding="utf-8")


def export_site_tables(
    cohort: pd.DataFrame,
    calendar: TermCalendar,
    out_dir: Path | str,
    *,
    meta: dict | None = None,
    min_n: int = MIN_N,
    n_boot: int = N_BOOT,
    forecast_calendar: TermCalendar | None = None,
    flows: pd.DataFrame | None = None,
    estimate_level: str = DEFAULT_ESTIMATE_LEVEL,
) -> tuple[Path, Path]:
    """Write the site's JSON under ``out_dir``; returns ``(index.json, meta.json)``.

    ``calendar`` is the data term's; ``forecast_calendar`` (default: the same)
    is the term whose dates the pages count down to, so a finished cycle can
    stand in for the coming one and be labelled as such. ``estimate_level`` is
    what a course's estimate is (``course_tables``); ``meta.json`` records it.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    forecast = forecast_calendar or calendar
    pools = pool_tables(cohort, min_n=min_n, n_boot=n_boot)
    courses = course_tables(cohort, calendar, min_n=min_n, n_boot=n_boot, pools=pools, estimate_level=estimate_level)
    joins = joins_by_course(cohort, flows)

    courses_dir = out_dir / "courses"
    courses_dir.mkdir(exist_ok=True)
    for stale in courses_dir.glob("*.json"):
        stale.unlink()
    legacy = out_dir / "courses.json"
    if legacy.exists():
        legacy.unlink()
    by_subject: dict[str, dict] = {}
    for key, entry in courses.items():
        by_subject.setdefault(entry["subject"], {})[key] = entry
    subject_files: dict[str, str] = {}
    for subject, entries in sorted(by_subject.items()):
        rel = _subject_file(subject)
        subject_files[subject] = rel
        _dump(out_dir / rel, {"subject": subject, "term_id": calendar.term_id, "courses": entries})

    index_path = out_dir / "index.json"
    _dump(index_path, {"term_id": calendar.term_id, "horizons": list(HORIZONS), "courses": index_rows(courses, pools, joins)})
    _dump(out_dir / "pooled.json", {"term_id": calendar.term_id, **pools})
    _dump(out_dir / "insights.json", {"term_id": calendar.term_id, **insights_tables(cohort, pools, min_n=min_n, n_boot=n_boot, flows=flows)})

    info = {
        "term_id": calendar.term_id,
        "term_name": calendar.name,
        "forecast_term_id": forecast.term_id,
        "forecast_term_name": forecast.name,
        "dates": {k: getattr(forecast, k).isoformat() for k in CALENDAR_FIELDS},
        "data_dates": {k: getattr(calendar, k).isoformat() for k in CALENDAR_FIELDS},
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
        "estimate_level": estimate_level,
        "horizons": list(HORIZONS),
        "positions": sorted(int(p) for p in cohort["position"].unique()) if len(cohort) else [],
        "instruction_start": forecast.instruction_start.isoformat(),
        "deadline": forecast.last_auto_waitlist.isoformat(),  # last automatic waitlist run of the forecast term (the headline horizon)
        "add_drop_deadline": forecast.add_drop_deadline.isoformat(),
        "files": {"index": "index.json", "pooled": "pooled.json", "insights": "insights.json"},
        "subject_files": subject_files,
        "rank": "wl_joins" if joins else None,
    }
    if meta:
        info.update(meta)
    info.setdefault("terms", [{"term_id": calendar.term_id, "term_name": calendar.name, "data_source": info.get("data_source")}])
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps(info, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    logger.info("wrote %s (%d courses, %d subject files), %s and %s", index_path, len(courses), len(subject_files), out_dir / "pooled.json", meta_path)
    return index_path, meta_path


def main(argv: list[str] | None = None) -> int:
    """Rebuild ``site/data`` from a saved cohort without re-running the whole analysis
    (the by-hand refresh in docs/RUNBOOK.md)."""
    p = argparse.ArgumentParser(description="Write the site's JSON from a cohort Parquet file.")
    p.add_argument("--cohort", type=Path, required=True, help="e.g. analysis/out/2268/cohort_central.parquet")
    p.add_argument("--term-id", required=True, help="the cohort's term (its enrollment calendar)")
    p.add_argument("--forecast-term", default=None, help="term whose dates the pages count down to (default: the cohort's)")
    p.add_argument("--out", type=Path, default=Path("site/data"))
    p.add_argument("--flows", type=Path, default=None, help="flows Parquet of the same term (joins rank, daily series)")
    p.add_argument("--meta-from", type=Path, default=None, help="an existing meta.json whose source labels are carried over: " + ", ".join(META_CARRY))
    p.add_argument("--data-source", default=None, help="own_snapshots or berkeleytime_history (overrides --meta-from)")
    p.add_argument("--prereg-commit", default=None)
    p.add_argument("--prereg-date", default=None)
    p.add_argument("--n-boot", type=int, default=N_BOOT)
    p.add_argument("--min-n", type=int, default=MIN_N)
    p.add_argument("--estimate-level", choices=ESTIMATE_LEVELS, default=DEFAULT_ESTIMATE_LEVEL, help="dept: the department's curve stands in for every course (default); course: a course with min_n rows gets its own curve")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    cohort = pd.read_parquet(args.cohort)
    flows = pd.read_parquet(args.flows) if args.flows else None
    meta: dict = {}
    if args.meta_from and args.meta_from.exists():
        old = json.loads(args.meta_from.read_text(encoding="utf-8"))
        meta.update({k: old[k] for k in META_CARRY if k in old})
    if args.data_source:
        meta["data_source"] = args.data_source
    if args.prereg_commit:
        meta["prereg_commit"] = args.prereg_commit
    if args.prereg_date:
        meta["prereg_date"] = args.prereg_date
    index_path, meta_path = export_site_tables(
        cohort,
        calendar_for(args.term_id),
        args.out,
        meta=meta,
        min_n=args.min_n,
        n_boot=args.n_boot,
        forecast_calendar=calendar_for(args.forecast_term) if args.forecast_term else None,
        flows=flows,
        estimate_level=args.estimate_level,
    )
    info = json.loads(meta_path.read_text(encoding="utf-8"))
    print(json.dumps({"index": str(index_path), "meta": str(meta_path), "courses": info["courses"], "events": info["events"], "sections": info["sections"], "data_source": info.get("data_source"), "estimate_level": info["estimate_level"], "subject_files": len(info["subject_files"])}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
