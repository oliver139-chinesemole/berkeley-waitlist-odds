"""FIFO position model: when does a virtual waitlister clear?

See docs/DESIGN_A4.md section 3 and docs/ASSUMPTIONS.md sections 2 and 3.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

import numpy as np
import pandas as pd

from analysis.flows import FLOW_COLUMNS

SCENARIOS = ("optimistic", "central", "pessimistic")


def cumulative_flows(flows: pd.DataFrame) -> pd.DataFrame:
    """The flows table with per-section running totals ``cum_<flow>``."""
    out = flows.sort_values(["section_id", "t0"]).copy()
    for col in FLOW_COLUMNS:
        out[f"cum_{col}"] = out.groupby("section_id")[col].cumsum().astype("Int64")
    return out.reset_index(drop=True)


def _advance(k: float, admits: int, wl_drops: int, waitlist0: int, scenario: str) -> float:
    if scenario == "optimistic":
        return k - admits - wl_drops
    if scenario == "pessimistic":
        return k - admits
    if scenario == "central":
        share = (k / waitlist0) if waitlist0 > 0 else 0.0
        return k - admits - wl_drops * min(max(share, 0.0), 1.0)
    raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")


def time_to_clear(
    section_flows: pd.DataFrame,
    join_time: datetime,
    position: int,
    scenario: str = "central",
) -> tuple[float | None, bool]:
    """(minutes from ``join_time`` until a joiner at ``position`` clears, or None) and
    whether the outcome is censored.

    ``position`` counts the joiner itself: position 1 clears at the next admit.
    Intervals are walked in time order starting with the first whose ``t0`` is
    at or after ``join_time``; the walk stops with ``censored=True`` at the
    first censored interval or at the end of the data.
    """
    if position < 1:
        raise ValueError("position must be >= 1")
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")
    rows = section_flows[section_flows["t0"] >= pd.Timestamp(join_time)].sort_values("t0")
    k = float(position)
    for row in rows.itertuples(index=False):
        if bool(row.censored):
            return None, True
        k = _advance(k, int(row.admits), int(row.wl_drops), int(row.waitlist0), scenario)
        if k <= 0:
            return (pd.Timestamp(row.t1) - pd.Timestamp(join_time)).total_seconds() / 60.0, False
    return None, True


def virtual_waitlisters(
    flows: pd.DataFrame,
    *,
    positions: Sequence[int] = (1, 3, 5, 10, 20, 40),
    scenario: str = "central",
) -> pd.DataFrame:
    """One row per (section_id, join_time, position) for every observed ``t0`` at
    which the waitlist was at least ``position - 1`` long (so the position is a
    real place in the queue): ``duration_min`` and ``event`` (1 cleared, 0
    censored), plus ``scenario`` and ``waitlist0``."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")
    records: list[dict] = []
    for section_id, group in flows.groupby("section_id", sort=True):
        group = group.sort_values("t0").reset_index(drop=True)
        t0s = group["t0"].to_numpy()
        for i in range(len(group)):
            waitlist0 = int(group.at[i, "waitlist0"])
            join_time = pd.Timestamp(t0s[i])
            for position in positions:
                if waitlist0 < position - 1:
                    continue
                duration, censored = time_to_clear(group.iloc[i:], join_time, int(position), scenario)
                records.append(
                    {
                        "section_id": section_id,
                        "join_time": join_time,
                        "position": int(position),
                        "waitlist0": waitlist0,
                        "duration_min": duration if duration is not None else np.nan,
                        "event": 0 if censored else 1,
                        "scenario": scenario,
                    }
                )
    out = pd.DataFrame.from_records(records, columns=["section_id", "join_time", "position", "waitlist0", "duration_min", "event", "scenario"])
    if len(out):
        out["section_id"] = out["section_id"].astype("string")
        out["join_time"] = pd.to_datetime(out["join_time"], utc=True)
    return out
