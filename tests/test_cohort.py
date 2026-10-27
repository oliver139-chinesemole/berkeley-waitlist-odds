"""Tests for analysis.cohort on hand-built flows."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from analysis.calendar import SPRING_2027
from analysis.cohort import COHORT_COLUMNS, build_cohort, censoring_horizon, course_level, cut_flows, joinable, position_bucket, thin_join_times

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)  # phase 1 of Spring 2027


def flows(section_id: str, rows: list[tuple[int, int, int, bool]], capacity: int = 100, reserved: int | None = None, full: bool = True) -> pd.DataFrame:
    """``full`` is the section's ``full0`` flag at every interval (no unreserved seat open)."""
    records = []
    for i, (admits, wl_drops, waitlist0, censored) in enumerate(rows):
        records.append(
            {
                "section_id": section_id,
                "t0": pd.Timestamp(T0 + timedelta(minutes=30 * i)),
                "t1": pd.Timestamp(T0 + timedelta(minutes=30 * (i + 1))),
                "interval_min": 30.0,
                "waitlist0": waitlist0,
                "capacity0": capacity,
                "full0": full,
                "reserved0": reserved,
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


def identity(*rows: tuple[str, str, str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"section_id": s, "course_key": ck, "subject": ck.split()[0], "catalog_number": cat, "component": comp} for s, ck, cat, comp in rows]
    )


def test_helpers() -> None:
    assert [position_bucket(p) for p in (1, 5, 6, 15, 16, 40, 41, 500)] == ["1-5", "1-5", "6-15", "6-15", "16-40", "16-40", "41+", "41+"]
    with pytest.raises(ValueError):
        position_bucket(0)
    assert [course_level(c) for c in ("61A", "C100", "H194", "200", "R1A", "N1", "298", None, "X")] == [
        "lower", "upper", "upper", "grad", "lower", "lower", "grad", None, None
    ]
    times = [pd.Timestamp(T0 + timedelta(minutes=m)) for m in (0, 30, 60, 240, 270, 500)]
    assert thin_join_times(times, 240) == [times[0], times[3], times[5]]


def test_censoring_horizon() -> None:
    f = flows("1", [(0, 0, 5, False), (0, 0, 5, False), (0, 0, 5, True), (0, 0, 5, False)])
    assert censoring_horizon(f, pd.Timestamp(T0)) == 60.0  # end of the last uncensored interval
    assert censoring_horizon(f, pd.Timestamp(T0 + timedelta(minutes=60))) == 0.0  # first interval censored
    assert censoring_horizon(f, pd.Timestamp(T0 + timedelta(minutes=300))) is None


def test_build_cohort_rows_and_covariates() -> None:
    f = pd.concat(
        [
            flows("1", [(1, 0, 3, False), (1, 0, 2, False), (0, 0, 1, False)], reserved=5),
            flows("2", [(0, 0, 0, False), (0, 0, 0, False)]),
        ],
        ignore_index=True,
    )
    ident = identity(("1", "COMPSCI 61A", "61A", "LEC"), ("2", "STAT 201", "201", "LEC"))
    cohort = build_cohort(f, ident, SPRING_2027, positions=(1, 2, 5), join_every_min=0, min_sections_per_group=1)
    assert list(cohort.columns) == list(COHORT_COLUMNS)
    s1 = cohort[cohort["section_id"] == "1"]
    # join at T0 (waitlist 3): positions 1 and 2 qualify (5 needs waitlist >= 4)
    at0 = s1[s1["join_time"] == pd.Timestamp(T0)].set_index("position")
    assert sorted(at0.index) == [1, 2]
    assert at0.at[1, "event"] == 1 and at0.at[1, "duration_min"] == 30.0
    assert at0.at[2, "event"] == 1 and at0.at[2, "duration_min"] == 60.0
    assert at0.at[1, "position_bucket"] == "1-5" and at0.at[1, "level"] == "lower" and at0.at[1, "phase"] == "phase1"
    assert at0.at[1, "reserved"] and at0.at[1, "wl_ratio"] == pytest.approx(0.03)
    assert at0.at[1, "days_to_instruction"] == pytest.approx((datetime(2027, 1, 19, tzinfo=timezone.utc) - T0).total_seconds() / 86400)
    # section 2 is full with an empty waitlist: only position 1 qualifies, never clears, censored at the horizon
    s2 = cohort[cohort["section_id"] == "2"]
    assert set(s2["position"]) == {1} and (s2["event"] == 0).all() and s2["duration_min"].max() == 60.0
    assert s2["level"].iloc[0] == "grad" and s2["scenario"].iloc[0] == "central"


def test_dept_pooling_and_thinning() -> None:
    f = pd.concat([flows(str(i), [(0, 0, 2, False)] * 20) for i in range(3)], ignore_index=True)
    ident = identity(("0", "MATH 1A", "1A", "LEC"), ("1", "MATH 1B", "1B", "LEC"), ("2", "ART 1", "1", "LEC"))
    cohort = build_cohort(f, ident, SPRING_2027, positions=(1,), join_every_min=240, min_sections_per_group=2)
    assert set(cohort["dept_group"]) == {"MATH", "OTHER"}
    joins = cohort[cohort["section_id"] == "0"]["join_time"].sort_values().tolist()
    assert joins == [pd.Timestamp(T0), pd.Timestamp(T0 + timedelta(minutes=240)), pd.Timestamp(T0 + timedelta(minutes=480))]


def test_scenarios_and_bad_scenario() -> None:
    f = flows("1", [(1, 2, 8, False), (1, 2, 5, False), (1, 0, 2, False), (1, 0, 1, False)])
    ident = identity(("1", "COMPSCI 61A", "61A", "LEC"))
    durations = {
        s: build_cohort(f, ident, SPRING_2027, scenario=s, positions=(4,), join_every_min=0, min_sections_per_group=1)["duration_min"].iloc[0]
        for s in ("optimistic", "central", "pessimistic")
    }
    assert durations == {"optimistic": 60.0, "central": 90.0, "pessimistic": 120.0}
    with pytest.raises(ValueError):
        build_cohort(f, ident, SPRING_2027, scenario="hopeful")


def test_empty_flows() -> None:
    empty = flows("1", [(0, 0, 0, False)]).iloc[0:0]
    cohort = build_cohort(empty, identity(("1", "COMPSCI 61A", "61A", "LEC")), SPRING_2027)
    assert len(cohort) == 0 and list(cohort.columns) == list(COHORT_COLUMNS)


def test_open_section_without_queue_is_not_joinable() -> None:
    """Nobody waits behind an open seat: no virtual joiner where seats are open and the queue is empty."""
    ident = identity(("1", "COMPSCI 61A", "61A", "LEC"))
    open_no_queue = flows("1", [(0, 0, 0, False)] * 3, full=False)
    assert len(build_cohort(open_no_queue, ident, SPRING_2027, positions=(1,), join_every_min=0, min_sections_per_group=1)) == 0
    full_no_queue = flows("1", [(0, 0, 0, False)] * 3, full=True)
    assert len(build_cohort(full_no_queue, ident, SPRING_2027, positions=(1,), join_every_min=0, min_sections_per_group=1)) == 3
    open_with_queue = flows("1", [(0, 0, 2, False)] * 3, full=False)  # a queue exists (reserved seats, say): joinable
    assert len(build_cohort(open_with_queue, ident, SPRING_2027, positions=(1,), join_every_min=0, min_sections_per_group=1)) == 3
    # without full0 the rule falls back to enrolled0 >= capacity0, then to "not full"
    no_flag = open_no_queue.drop(columns=["full0"]).assign(enrolled0=100)
    assert len(build_cohort(no_flag, ident, SPRING_2027, positions=(1,), join_every_min=0, min_sections_per_group=1)) == 3
    assert len(build_cohort(open_no_queue.drop(columns=["full0"]), ident, SPRING_2027, positions=(1,), join_every_min=0, min_sections_per_group=1)) == 0
    assert joinable(0, False) is False and joinable(0, None) is False and joinable(0, True) is True and joinable(3, False) is True


def test_follow_up_days_is_the_window_a_joiner_could_be_watched() -> None:
    """Censored rows end at the window; cleared rows end inside it; a gap after the join caps it."""
    f = flows("1", [(1, 0, 3, False), (0, 0, 2, False), (0, 0, 2, True), (0, 0, 2, False)])
    ident = identity(("1", "COMPSCI 61A", "61A", "LEC"))
    cohort = build_cohort(f, ident, SPRING_2027, positions=(1, 2), join_every_min=0, min_sections_per_group=1)
    assert "follow_up_days" in COHORT_COLUMNS and (cohort["duration_days"] <= cohort["follow_up_days"] + 1e-12).all()
    at0 = cohort[cohort["join_time"] == pd.Timestamp(T0)].set_index("position")
    assert at0.at[1, "event"] == 1 and at0.at[1, "duration_min"] == 30.0 and at0.at[1, "follow_up_days"] == pytest.approx(60 / 1440)  # gap at +60 min
    assert at0.at[2, "event"] == 0 and at0.at[2, "duration_min"] == 60.0 and at0.at[2, "follow_up_days"] == pytest.approx(60 / 1440)
    later = cohort[cohort["join_time"] == pd.Timestamp(T0 + timedelta(minutes=90))]
    assert np.allclose(later["follow_up_days"].to_numpy(), 30 / 1440)  # after the gap: to the end of the data


def test_cut_at_censors_at_the_instant_and_places_no_later_joiners() -> None:
    """With ``cut_at`` (off by default) follow-up ends at the cut: a clearing whose interval ends
    after it is not a clearing (the joiner is censored at the cut), no joiner is placed at or
    after it, and ``follow_up_days`` stops there. Without it nothing changes."""
    rows = [(0, 0, 3, False), (1, 0, 3, False), (1, 0, 2, False), (1, 0, 1, False), (0, 0, 3, False)]
    f = flows("1", rows)  # intervals [0,30], [30,60], [60,90], [90,120], [120,150] minutes after T0
    before = f.copy(deep=True)
    ident = identity(("1", "COMPSCI 61A", "61A", "LEC"))
    kw = dict(positions=(1, 2, 3), join_every_min=0, min_sections_per_group=1)
    cut = pd.Timestamp(T0 + timedelta(minutes=75))  # inside the third interval
    uncut = build_cohort(f, ident, SPRING_2027, **kw)
    cohort = build_cohort(f, ident, SPRING_2027, cut_at=cut, **kw)
    pd.testing.assert_frame_equal(f, before)  # the caller's flows are not touched
    # the panel spans the cut: uncut, joiners are placed after it and clear after it
    assert (uncut["join_time"] >= cut).any()
    at0_u = uncut[uncut["join_time"] == pd.Timestamp(T0)].set_index("position")
    assert at0_u["event"].tolist() == [1, 1, 1] and at0_u["duration_min"].tolist() == [60.0, 90.0, 120.0]
    # cut: no joiner at or after the cut; every row ends by the cut; clearings after it are censored at it
    assert (cohort["join_time"] < cut).all() and sorted(cohort["join_time"].unique()) == [pd.Timestamp(T0 + timedelta(minutes=m)) for m in (0, 30, 60)]
    ends = cohort["join_time"] + pd.to_timedelta(cohort["duration_min"], unit="min")
    assert (ends <= cut).all()
    assert (cohort["follow_up_days"] <= (cut - cohort["join_time"]).dt.total_seconds() / 86400 + 1e-12).all()
    at0 = cohort[cohort["join_time"] == pd.Timestamp(T0)].set_index("position")
    assert at0.at[1, "event"] == 1 and at0.at[1, "duration_min"] == 60.0  # cleared before the cut: unchanged
    assert at0.at[2, "event"] == 0 and at0.at[2, "duration_min"] == 75.0  # its clearing interval ends at 90, after the cut
    assert at0.at[3, "event"] == 0 and at0.at[3, "duration_min"] == 75.0
    assert np.allclose(at0["follow_up_days"].to_numpy(), 75 / 1440)
    at60 = cohort[cohort["join_time"] == pd.Timestamp(T0 + timedelta(minutes=60))]
    assert (at60["event"] == 0).all() and (at60["duration_min"] == 15.0).all()
    # off (the default) and a cut after the data ends: identical to the uncut cohort
    pd.testing.assert_frame_equal(build_cohort(f, ident, SPRING_2027, cut_at=None, **kw), uncut)
    pd.testing.assert_frame_equal(build_cohort(f, ident, SPRING_2027, cut_at=pd.Timestamp(T0 + timedelta(minutes=150)), **kw), uncut)
    # a cut on an interval boundary keeps that interval whole and drops the rest
    edge = cut_flows(f, pd.Timestamp(T0 + timedelta(minutes=90)))
    assert len(edge) == 3 and edge["admits"].tolist() == [0, 1, 1] and edge["t1"].max() == pd.Timestamp(T0 + timedelta(minutes=90))
