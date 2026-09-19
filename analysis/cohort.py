"""Virtual waitlisters with covariates: the unit of analysis for step A5.

See docs/DESIGN_A5.md section 1. Each row is a hypothetical student who
joined a section's waitlist at a sampled observation time at a given
position; ``duration_min`` and ``event`` come from the FIFO position model
under one drop scenario, and the covariates are what a student could know
at the moment of joining.
"""
from __future__ import annotations

import math
import re
from typing import Sequence

import numpy as np
import pandas as pd

from analysis.calendar import TermCalendar
from analysis.positions import SCENARIOS, time_to_clear

POSITION_BUCKETS = ((1, 5, "1-5"), (6, 15, "6-15"), (16, 40, "16-40"), (41, 10**9, "41+"))
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


def build_cohort(
    flows: pd.DataFrame,
    identity: pd.DataFrame,
    calendar: TermCalendar,
    *,
    scenario: str = "central",
    positions: Sequence[int] = (1, 3, 5, 10, 20, 40),
    join_every_min: float = 240,
    min_sections_per_group: int = 30,
) -> pd.DataFrame:
    """One row per (section, sampled join time, position); see the module docstring."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")
    ident = identity.set_index("section_id") if "section_id" in identity.columns else identity
    records: list[dict] = []
    for section_id, group in flows.groupby("section_id", sort=True):
        group = group.sort_values("t0").reset_index(drop=True)
        info = ident.loc[section_id] if section_id in ident.index else None
        by_t0 = group.set_index("t0")
        for join_time in thin_join_times(group["t0"], join_every_min):
            state = by_t0.loc[join_time]
            if isinstance(state, pd.DataFrame):
                state = state.iloc[0]
            waitlist0 = int(state["waitlist0"])
            capacity0 = int(state["capacity0"])
            reserved0 = state.get("reserved0")
            reserved = bool(reserved0 is not None and not pd.isna(reserved0) and int(reserved0) > 0)
            for position in positions:
                if waitlist0 < position - 1:
                    continue
                duration, censored = time_to_clear(group, join_time, int(position), scenario)
                if duration is None:
                    duration = censoring_horizon(group, join_time)
                    if duration is None or duration <= 0:
                        continue
                    event = 0
                else:
                    event = 0 if censored else 1
                catalog_number = None if info is None else info.get("catalog_number")
                records.append(
                    {
                        "section_id": section_id,
                        "join_time": join_time,
                        "position": int(position),
                        "position_bucket": position_bucket(int(position)),
                        "log_position": float(np.log(position)),
                        "waitlist0": waitlist0,
                        "capacity0": capacity0,
                        "wl_ratio": (waitlist0 / capacity0) if capacity0 > 0 else np.nan,
                        "duration_min": float(duration),
                        "duration_days": float(duration) / 1440.0,
                        "event": int(event),
                        "course_key": None if info is None else info.get("course_key"),
                        "subject": None if info is None else info.get("subject"),
                        "catalog_number": catalog_number,
                        "component": None if info is None else info.get("component"),
                        "level": course_level(catalog_number),
                        "dept_group": None if info is None else info.get("subject"),
                        "phase": calendar.phase_at(join_time.to_pydatetime()),
                        "days_to_instruction": calendar.days_to_instruction(join_time.to_pydatetime()),
                        "reserved": reserved,
                        "scenario": scenario,
                    }
                )
    cohort = pd.DataFrame.from_records(records, columns=list(COHORT_COLUMNS))
    if len(cohort):
        sections_per_subject = cohort.groupby("dept_group")["section_id"].nunique()
        small = set(sections_per_subject[sections_per_subject < min_sections_per_group].index)
        cohort["dept_group"] = cohort["dept_group"].where(~cohort["dept_group"].isin(small), OTHER_GROUP)
        cohort["join_time"] = pd.to_datetime(cohort["join_time"], utc=True)
        for col in ("section_id", "position_bucket", "course_key", "subject", "catalog_number", "component", "level", "dept_group", "phase", "scenario"):
            cohort[col] = cohort[col].astype("string")
        cohort["reserved"] = cohort["reserved"].astype(bool)
        cohort["event"] = cohort["event"].astype(int)
    return cohort
