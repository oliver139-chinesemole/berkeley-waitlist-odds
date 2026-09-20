"""Virtual waitlisters with covariates: the unit of analysis for step A5.

See docs/DESIGN_A5.md section 1. Each row is a hypothetical student who
joined a section's waitlist at a sampled observation time at a given
position; ``duration_min`` and ``event`` come from the FIFO position model
under one drop scenario, and the covariates are what a student could know
at the moment of joining. A row exists only where a waitlist could be joined
(``joinable``): a queue exists or the section is full.

The position walk is the one in ``analysis.positions`` (``time_to_clear``),
run here in numpy for every joiner of a section at once and only over the
intervals where something happens (an admit, a waitlist drop or a censored
interval), because a term-long backfill has thousands of sections with a
thousand intervals each.
"""
from __future__ import annotations

import math
import re
from typing import Sequence

import numpy as np
import pandas as pd

from analysis.calendar import TermCalendar
from analysis.positions import CENTRAL_CLEAR_AT, SCENARIOS, time_to_clear  # noqa: F401 - time_to_clear is the reference implementation

POSITION_BUCKETS = ((1, 5, "1-5"), (6, 15, "6-15"), (16, 40, "16-40"), (41, 10**9, "41+"))
# Virtual positions: at least two per bucket, and 60 and 100 so that the 41+ bucket can be filled.
DEFAULT_POSITIONS = (1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 60, 100)
LEVELS = ("lower", "upper", "grad")
OTHER_GROUP = "OTHER"
COHORT_COLUMNS = (
    "section_id",
    "join_time",
    "position",
    "position_bucket",
    "log_position",
    "waitlist0",
    "capacity0",
    "wl_ratio",
    "duration_min",
    "duration_days",
    "event",
    "course_key",
    "subject",
    "catalog_number",
    "component",
    "level",
    "dept_group",
    "phase",
    "days_to_instruction",
    "reserved",
    "scenario",
)

_NUMBER_RE = re.compile(r"(\d+)")
_NS_PER_MIN = 60_000_000_000


def joinable(waitlist0: int, full0: bool | None) -> bool:
    """Whether a student can join this section's waitlist at this moment: a queue
    already exists, or the section is full (no unreserved seat open). Nobody
    waits behind an open seat, so a virtual joiner placed there can never clear
    and would only drag the 1-5 bucket toward zero. ``full0`` unknown counts
    as not full."""
    return int(waitlist0) > 0 or bool(full0 is not None and not pd.isna(full0) and full0)


def position_bucket(position: int) -> str:
    for low, high, label in POSITION_BUCKETS:
        if low <= position <= high:
            return label
    raise ValueError(f"position must be >= 1, got {position}")


def course_level(catalog_number: str | None) -> str | None:
    """lower (under 100), upper (100 to 199), grad (200 and above) from the
    digits of the catalog number; None when there are no digits."""
    if catalog_number is None or (isinstance(catalog_number, float) and math.isnan(catalog_number)):
        return None
    m = _NUMBER_RE.search(str(catalog_number))
    if not m:
        return None
    n = int(m.group(1))
    if n < 100:
        return "lower"
    if n < 200:
        return "upper"
    return "grad"


def thin_join_times(t0s: Sequence[pd.Timestamp], join_every_min: float) -> list[pd.Timestamp]:
    """Greedy thinning: keep the first time, then each time at least
    ``join_every_min`` after the last kept one."""
    kept: list[pd.Timestamp] = []
    gap = pd.to_timedelta(float(join_every_min), unit="min")
    for t in sorted(pd.Timestamp(x) for x in t0s):
        if not kept or t - kept[-1] >= gap:
            kept.append(t)
    return kept


def _thin_indices(t_ns: np.ndarray, join_every_min: float) -> np.ndarray:
    """Row indices of ``thin_join_times`` on a sorted int64-nanosecond array."""
    gap = int(round(float(join_every_min) * _NS_PER_MIN))
    kept: list[int] = []
    last = None
    for i, t in enumerate(t_ns.tolist()):
        if last is None or t - last >= gap:
            kept.append(i)
            last = t
    return np.asarray(kept, dtype=np.int64)


def censoring_horizon(section_flows: pd.DataFrame, join_time: pd.Timestamp) -> float | None:
    """Minutes from ``join_time`` to the end of observation for a joiner who did
    not clear: the ``t1`` of the last uncensored interval before the first
    censored one (or the censored interval's ``t0``); None when nothing is
    observed after the join."""
    rows = section_flows[section_flows["t0"] >= join_time].sort_values("t0")
    horizon: pd.Timestamp | None = None
    for row in rows.itertuples(index=False):
        if bool(row.censored):
            horizon = pd.Timestamp(row.t0) if horizon is None else horizon
            break
        horizon = pd.Timestamp(row.t1)
    if horizon is None:
        return None
    minutes = (horizon - join_time).total_seconds() / 60.0
    return max(minutes, 0.0)


def _ns(series: pd.Series) -> np.ndarray:
    stamps = pd.to_datetime(series)
    if getattr(stamps.dt, "tz", None) is not None:
        stamps = stamps.dt.tz_convert("UTC").dt.tz_localize(None)
    return stamps.to_numpy("datetime64[ns]").astype("int64")


def _int_array(series: pd.Series | None, n: int, fill: int = 0) -> np.ndarray:
    if series is None:
        return np.full(n, fill, dtype=np.int64)
    return pd.to_numeric(series, errors="coerce").fillna(fill).to_numpy(dtype=np.int64)


def walk_positions(
    t0_ns: np.ndarray,
    t1_ns: np.ndarray,
    admits: np.ndarray,
    wl_drops: np.ndarray,
    waitlist0: np.ndarray,
    censored: np.ndarray,
    join_idx: np.ndarray,
    positions: np.ndarray,
    scenario: str,
) -> tuple[np.ndarray, np.ndarray]:
    """``(duration_min, event)`` for joiners at rows ``join_idx`` with ``positions``,
    following ``analysis.positions.time_to_clear`` exactly: walk the intervals
    from the join row, advance under the scenario, clear at the threshold, stop
    censored at the first censored interval or the end of the data (duration
    is then the censoring horizon: that interval's ``t0``, or the last ``t1``).
    Durations of zero or less (nothing observed after the join) come back NaN."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")
    n = len(t0_ns)
    m = len(join_idx)
    k = positions.astype(float).copy()
    done = np.zeros(m, dtype=bool)
    event = np.zeros(m, dtype=np.int64)
    horizon_ns = np.full(m, t1_ns[-1] if n else 0, dtype=np.int64)
    threshold = CENTRAL_CLEAR_AT if scenario == "central" else 0.0
    event_rows = np.flatnonzero((admits > 0) | (wl_drops > 0) | censored)
    first = int(join_idx.min()) if m else n
    for r in event_rows[event_rows >= first].tolist():
        active = ~done & (join_idx <= r)
        if not active.any():
            if done.all():
                break
            continue
        if censored[r]:
            done[active] = True
            horizon_ns[active] = t0_ns[r]
            continue
        a = int(admits[r])
        d = int(wl_drops[r])
        if scenario == "optimistic":
            k[active] -= a + d
        elif scenario == "pessimistic":
            k[active] -= a
        else:
            w0 = int(waitlist0[r])
            share = np.clip((k[active] - 1.0) / (w0 - 1.0), 0.0, 1.0) if w0 > 1 else 0.0
            k[active] -= a + d * share
        cleared = active & (k <= threshold)
        if cleared.any():
            horizon_ns[cleared] = t1_ns[r]
            event[cleared] = 1
            done[cleared] = True
    duration = (horizon_ns - t0_ns[join_idx]) / _NS_PER_MIN
    duration = np.where(duration > 0, duration, np.nan)
    return duration, event


def build_cohort(
    flows: pd.DataFrame,
    identity: pd.DataFrame,
    calendar: TermCalendar,
    *,
    scenario: str = "central",
    positions: Sequence[int] = DEFAULT_POSITIONS,
    join_every_min: float = 240,
    min_sections_per_group: int = 30,
) -> pd.DataFrame:
    """One row per (section, sampled join time, position); see the module docstring."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")
    ident = identity.set_index("section_id") if "section_id" in identity.columns else identity
    pos_arr = np.asarray(sorted(int(p) for p in positions), dtype=np.int64)
    pieces: list[pd.DataFrame] = []
    for section_id, group in flows.groupby("section_id", sort=True):
        group = group.sort_values("t0").reset_index(drop=True)
        n = len(group)
        if n == 0:
            continue
        info = ident.loc[section_id] if section_id in ident.index else None
        t0_ns = _ns(group["t0"])
        t1_ns = _ns(group["t1"])
        admits = _int_array(group.get("admits"), n)
        wl_drops = _int_array(group.get("wl_drops"), n)
        waitlist0 = _int_array(group["waitlist0"], n)
        capacity0 = _int_array(group["capacity0"], n)
        censored = group["censored"].fillna(False).astype(bool).to_numpy() if "censored" in group else np.zeros(n, dtype=bool)
        if "full0" in group:
            full0 = group["full0"].astype(object)
            if "enrolled0" in group:
                enrolled = pd.to_numeric(group["enrolled0"], errors="coerce")
                full0 = full0.where(full0.notna(), (enrolled >= capacity0).where(enrolled.notna(), None))
            full0 = full0.map(lambda v: bool(v) if v is not None and not pd.isna(v) else False).to_numpy(dtype=bool)
        elif "enrolled0" in group:
            enrolled = pd.to_numeric(group["enrolled0"], errors="coerce")
            full0 = (enrolled >= capacity0).fillna(False).to_numpy(dtype=bool)
        else:
            full0 = np.zeros(n, dtype=bool)
        reserved0 = _int_array(group.get("reserved0"), n) if "reserved0" in group else np.zeros(n, dtype=np.int64)

        join_rows = _thin_indices(t0_ns, join_every_min)
        join_rows = join_rows[(waitlist0[join_rows] > 0) | full0[join_rows]]
        if len(join_rows) == 0:
            continue
        # pairs (join row, position) where the position is a real place in the queue
        jr = np.repeat(join_rows, len(pos_arr))
        pp = np.tile(pos_arr, len(join_rows))
        keep = waitlist0[jr] >= pp - 1
        jr, pp = jr[keep], pp[keep]
        if len(jr) == 0:
            continue
        duration, event = walk_positions(t0_ns, t1_ns, admits, wl_drops, waitlist0, censored, jr, pp, scenario)
        ok = ~np.isnan(duration)
        jr, pp, duration, event = jr[ok], pp[ok], duration[ok], event[ok]
        if len(jr) == 0:
            continue
        join_times = pd.to_datetime(t0_ns[jr], unit="ns", utc=True)
        unique_rows, inverse = np.unique(jr, return_inverse=True)
        unique_times = pd.to_datetime(t0_ns[unique_rows], unit="ns", utc=True)
        phases = np.asarray([calendar.phase_at(t.to_pydatetime()) for t in unique_times], dtype=object)[inverse]
        days_to = np.asarray([calendar.days_to_instruction(t.to_pydatetime()) for t in unique_times], dtype=float)[inverse]
        catalog_number = None if info is None else info.get("catalog_number")
        w0 = waitlist0[jr]
        c0 = capacity0[jr]
        pieces.append(
            pd.DataFrame(
                {
                    "section_id": section_id,
                    "join_time": join_times,
                    "position": pp,
                    "position_bucket": [position_bucket(int(p)) for p in pp],
                    "log_position": np.log(pp.astype(float)),
                    "waitlist0": w0,
                    "capacity0": c0,
                    "wl_ratio": np.where(c0 > 0, w0 / np.where(c0 > 0, c0, 1), np.nan),
                    "duration_min": duration.astype(float),
                    "duration_days": duration.astype(float) / 1440.0,
                    "event": event.astype(int),
                    "course_key": None if info is None else info.get("course_key"),
                    "subject": None if info is None else info.get("subject"),
                    "catalog_number": catalog_number,
                    "component": None if info is None else info.get("component"),
                    "level": course_level(catalog_number),
                    "dept_group": None if info is None else info.get("subject"),
                    "phase": phases,
                    "days_to_instruction": days_to,
                    "reserved": reserved0[jr] > 0,
                    "scenario": scenario,
                }
            )
        )
    if not pieces:
        return pd.DataFrame(columns=list(COHORT_COLUMNS))
    cohort = pd.concat(pieces, ignore_index=True)[list(COHORT_COLUMNS)]
    sections_per_subject = cohort.groupby("dept_group")["section_id"].nunique()
    small = set(sections_per_subject[sections_per_subject < min_sections_per_group].index)
    cohort["dept_group"] = cohort["dept_group"].where(~cohort["dept_group"].isin(small), OTHER_GROUP)
    cohort["join_time"] = pd.to_datetime(cohort["join_time"], utc=True)
    for col in ("section_id", "position_bucket", "course_key", "subject", "catalog_number", "component", "level", "dept_group", "phase", "scenario"):
        cohort[col] = cohort[col].astype("string")
    cohort["reserved"] = cohort["reserved"].astype(bool)
    cohort["event"] = cohort["event"].astype(int)
    cohort["position"] = cohort["position"].astype(int)
    cohort["waitlist0"] = cohort["waitlist0"].astype(int)
    cohort["capacity0"] = cohort["capacity0"].astype(int)
    return cohort
