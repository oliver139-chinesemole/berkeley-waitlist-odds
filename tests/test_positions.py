"""Tests for the FIFO position model in analysis.positions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from analysis.positions import SCENARIOS, cumulative_flows, time_to_clear, virtual_waitlisters

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def flows(rows: list[tuple[int, int, int, bool]], section_id: str = "1") -> pd.DataFrame:
    """rows: (admits, wl_drops, waitlist0, censored) per 30-minute interval, in order."""
    records = []
    for i, (admits, wl_drops, waitlist0, censored) in enumerate(rows):
        records.append(
            {
                "section_id": section_id,
                "t0": pd.Timestamp(T0 + timedelta(minutes=30 * i)),
                "t1": pd.Timestamp(T0 + timedelta(minutes=30 * (i + 1))),
                "interval_min": 30.0,
                "waitlist0": waitlist0,
                "admits": admits,
                "wl_joins": 0,
                "wl_drops": wl_drops,
                "enr_joins": 0,
                "enr_drops": 0,
                "censored": censored,
            }
        )
    frame = pd.DataFrame.from_records(records)
    frame["section_id"] = frame["section_id"].astype("string")
    return frame


def test_position_one_clears_at_first_admit() -> None:
    f = flows([(0, 0, 5, False), (1, 0, 5, False), (3, 0, 4, False)])
    assert time_to_clear(f, T0, 1, "pessimistic") == (60.0, False)
    assert time_to_clear(f, T0, 1, "central") == (60.0, False)
    assert time_to_clear(f, T0, 1, "optimistic") == (60.0, False)


def test_scenarios_order_and_drops() -> None:
    # position 4, waitlist of 8; interval 1: 1 admit + 2 drops; interval 2: 1 admit + 2 drops
    f = flows([(1, 2, 8, False), (1, 2, 5, False), (1, 0, 2, False), (1, 0, 1, False)])
    opt, _ = time_to_clear(f, T0, 4, "optimistic")  # 4 -> 1 -> cleared at end of interval 2
    cen, _ = time_to_clear(f, T0, 4, "central")  # 4 -> 4-1-2*(4/8)=2 -> 2-1-2*(2/5)=0.2 -> -0.8 at interval 3
    pes, _ = time_to_clear(f, T0, 4, "pessimistic")  # 4 -> 3 -> 2 -> 1 -> 0 at interval 4
    assert (opt, cen, pes) == (60.0, 90.0, 120.0)


def test_join_time_selects_later_intervals() -> None:
    f = flows([(5, 0, 5, False), (0, 0, 0, False), (1, 0, 1, False)])
    # joins at the start of interval 1; clears at the end of interval 2, 60 minutes later
    assert time_to_clear(f, T0 + timedelta(minutes=30), 1, "central") == (60.0, False)


def test_censored_interval_and_end_of_data() -> None:
    f = flows([(0, 0, 5, False), (0, 0, 5, True), (3, 0, 5, False)])
    assert time_to_clear(f, T0, 2, "central") == (None, True)
    f = flows([(1, 0, 5, False)])
    assert time_to_clear(f, T0, 2, "central") == (None, True)


def test_bad_arguments() -> None:
    f = flows([(1, 0, 5, False)])
    with pytest.raises(ValueError):
        time_to_clear(f, T0, 0, "central")
    with pytest.raises(ValueError):
        time_to_clear(f, T0, 1, "hopeful")
    assert SCENARIOS == ("optimistic", "central", "pessimistic")


def test_cumulative_flows() -> None:
    f = flows([(1, 2, 8, False), (1, 0, 5, False)])
    c = cumulative_flows(f)
    assert list(c["cum_admits"]) == [1, 2] and list(c["cum_wl_drops"]) == [2, 2]


def test_virtual_waitlisters_rows_and_events() -> None:
    f = flows([(1, 0, 3, False), (1, 0, 2, False), (0, 0, 1, True)])
    vw = virtual_waitlisters(f, positions=(1, 3, 5), scenario="pessimistic")
    # join at t0 of interval 0 (waitlist 3): positions 1 and 3 qualify (5 does not: waitlist 3 < 4)
    at0 = vw[vw["join_time"] == pd.Timestamp(T0)].set_index("position")
    assert sorted(at0.index) == [1, 3]
    assert at0.at[1, "event"] == 1 and at0.at[1, "duration_min"] == 30.0
    assert at0.at[3, "event"] == 0 and np.isnan(at0.at[3, "duration_min"])  # 2 admits then censored
    assert set(vw["scenario"]) == {"pessimistic"}
    assert str(vw["section_id"].dtype) == "string"


def test_virtual_waitlisters_empty() -> None:
    vw = virtual_waitlisters(flows([]).iloc[0:0] if False else flows([(1, 0, 0, False)]).iloc[0:0])
    assert len(vw) == 0 and list(vw.columns) == ["section_id", "join_time", "position", "waitlist0", "duration_min", "event", "scenario"]
