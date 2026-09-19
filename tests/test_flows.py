"""Rule-by-rule tests for analysis.flows.interval_flows on hand-built panels."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from analysis.flows import FLOW_COLUMNS, OUTPUT_COLUMNS, interval_flows, summary
from analysis.panel import Outage

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def panel(rows: list[dict]) -> pd.DataFrame:
    """rows: dicts with section_id, i (run index, 30 min apart), e, w, c=100, wc=20, observed=True, status=None, res=None, open_res=None."""
    records = []
    for r in rows:
        records.append(
            {
                "section_id": r.get("section_id", "1"),
                "run_started_at": T0 + timedelta(minutes=30 * r["i"]),
                "enrolled_count": r["e"],
                "enroll_capacity": r.get("c", 100),
                "waitlist_count": r["w"],
                "waitlist_capacity": r.get("wc", 20),
                "reserved_count": r.get("res"),
                "open_reserved": r.get("open_res"),
                "status": "O",
                "section_status": r.get("status"),
                "observed": r.get("observed", True),
                "source": "classes_site",
                "scope": "full",
                "kind": "delta",
                "term_id": "2268",
            }
        )
    frame = pd.DataFrame.from_records(records)
    for col in ("enrolled_count", "enroll_capacity", "waitlist_count", "waitlist_capacity", "reserved_count", "open_reserved"):
        frame[col] = frame[col].astype("Int32")
    frame["observed"] = frame["observed"].astype("boolean")
    frame["section_status"] = frame["section_status"].astype("string")
    return frame


def one(rows: list[dict]) -> pd.Series:
    flows = interval_flows(panel(rows))
    assert len(flows) == 1, flows
    return flows.iloc[0]


def flows_of(row: pd.Series) -> dict[str, int]:
    return {c: int(row[c]) for c in FLOW_COLUMNS}


def test_output_columns_and_types() -> None:
    flows = interval_flows(panel([{"i": 0, "e": 90, "w": 5}, {"i": 1, "e": 91, "w": 4}]))
    assert list(flows.columns) == list(OUTPUT_COLUMNS)
    assert str(flows["admits"].dtype) == "Int64" and str(flows["ambiguous"].dtype) == "boolean"
    assert flows.at[0, "interval_min"] == 30.0 and flows.at[0, "t1"] > flows.at[0, "t0"]


def test_rule_admit_exact() -> None:
    row = one([{"i": 0, "e": 100, "w": 5}, {"i": 1, "e": 102, "w": 3}])
    assert flows_of(row) == {"admits": 2, "wl_joins": 0, "wl_drops": 0, "enr_joins": 0, "enr_drops": 0}
    assert row["rule"] == "admit" and not row["ambiguous"] and row["full0"]


def test_rule_admit_queue_has_priority() -> None:
    # 3 enrolled up with a queue of 5, waitlist down 1: 3 admits and 2 joins (FIFO: no direct enrolment past a queue)
    row = one([{"i": 0, "e": 90, "w": 5}, {"i": 1, "e": 93, "w": 4}])
    assert flows_of(row) == {"admits": 3, "wl_joins": 2, "wl_drops": 0, "enr_joins": 0, "enr_drops": 0}
    assert row["rule"] == "admit_join" and not row["ambiguous"]
    # 1 enrolled up, 3 waitlist down: 1 admit + 2 waitlist drops
    row = one([{"i": 0, "e": 99, "w": 5}, {"i": 1, "e": 100, "w": 2}])
    assert flows_of(row) == {"admits": 1, "wl_joins": 0, "wl_drops": 2, "enr_joins": 0, "enr_drops": 0}
    assert row["rule"] == "admit_drop" and not row["ambiguous"]
    # enrolment up with a queue and a flat waitlist: admits replaced by joins
    row = one([{"i": 0, "e": 50, "w": 2}, {"i": 1, "e": 53, "w": 2}])
    assert flows_of(row) == {"admits": 3, "wl_joins": 3, "wl_drops": 0, "enr_joins": 0, "enr_drops": 0}
    assert row["ambiguous"]  # 3 admits from a queue of 2 means joins and admits interleaved
    # open reserved seats can take a direct enrolment past the queue: flagged
    row = one([{"i": 0, "e": 90, "w": 5, "open_res": 3}, {"i": 1, "e": 91, "w": 4}])
    assert row["rule"] == "admit" and row["ambiguous"]


def test_rule_enr_join() -> None:
    row = one([{"i": 0, "e": 50, "w": 0}, {"i": 1, "e": 53, "w": 0}])
    assert flows_of(row)["enr_joins"] == 3 and row["rule"] == "enr_join" and not row["ambiguous"]


def test_rule_enr_join_then_join() -> None:
    row = one([{"i": 0, "e": 50, "w": 0}, {"i": 1, "e": 52, "w": 3}])
    assert flows_of(row) == {"admits": 0, "wl_joins": 3, "wl_drops": 0, "enr_joins": 2, "enr_drops": 0}
    assert row["rule"] == "enr_join_then_join" and not row["ambiguous"]
    row = one([{"i": 0, "e": 100, "w": 0}, {"i": 1, "e": 102, "w": 3}])
    assert row["ambiguous"]  # section was full
    row = one([{"i": 0, "e": 50, "w": 0}, {"i": 1, "e": 52, "w": -1}])
    assert row["rule"] == "inconsistent" and row["ambiguous"]


def test_rule_join() -> None:
    row = one([{"i": 0, "e": 100, "w": 4}, {"i": 1, "e": 100, "w": 9}])
    assert flows_of(row)["wl_joins"] == 5 and row["rule"] == "join" and not row["ambiguous"]


def test_rule_wl_drop_and_capcut() -> None:
    row = one([{"i": 0, "e": 100, "w": 4}, {"i": 1, "e": 100, "w": 1}])
    assert flows_of(row)["wl_drops"] == 3 and row["rule"] == "wl_drop" and row["ambiguous"]  # full with a queue
    row = one([{"i": 0, "e": 90, "w": 4}, {"i": 1, "e": 90, "w": 1}])
    assert row["rule"] == "wl_drop" and not row["ambiguous"]
    row = one([{"i": 0, "e": 100, "w": 4, "c": 100}, {"i": 1, "e": 100, "w": 0, "c": 90}])
    assert row["rule"] == "wl_drop_capcut" and int(row["d_capacity"]) == -10 and not row["expansion"]


def test_rule_enr_drop() -> None:
    row = one([{"i": 0, "e": 80, "w": 0}, {"i": 1, "e": 78, "w": 0}])
    assert flows_of(row)["enr_drops"] == 2 and row["rule"] == "enr_drop" and not row["ambiguous"]
    row = one([{"i": 0, "e": 100, "w": 6}, {"i": 1, "e": 98, "w": 6}])
    assert row["ambiguous"]  # full with a waitlist, yet nobody admitted: batch processing


def test_rule_enr_drop_wl_drop_is_ambiguous() -> None:
    row = one([{"i": 0, "e": 100, "w": 6}, {"i": 1, "e": 98, "w": 5}])
    assert flows_of(row) == {"admits": 0, "wl_joins": 0, "wl_drops": 1, "enr_joins": 0, "enr_drops": 2}
    assert row["rule"] == "enr_drop_wl_drop" and row["ambiguous"]


def test_rule_enr_drop_join() -> None:
    row = one([{"i": 0, "e": 100, "w": 6}, {"i": 1, "e": 99, "w": 8}])
    assert flows_of(row) == {"admits": 0, "wl_joins": 2, "wl_drops": 0, "enr_joins": 0, "enr_drops": 1}
    assert row["rule"] == "enr_drop_join" and not row["ambiguous"]


def test_rule_none_and_expansion() -> None:
    row = one([{"i": 0, "e": 100, "w": 6, "c": 100}, {"i": 1, "e": 100, "w": 6, "c": 120}])
    assert flows_of(row) == {c: 0 for c in FLOW_COLUMNS} and row["rule"] == "none" and row["expansion"]


def test_full0_uses_open_reserved_when_known() -> None:
    row = one([{"i": 0, "e": 95, "w": 3, "c": 100, "open_res": 5}, {"i": 1, "e": 95, "w": 3}])
    assert row["full0"]  # 95 >= 100 - 5
    row = one([{"i": 0, "e": 95, "w": 3, "c": 100, "open_res": 0}, {"i": 1, "e": 95, "w": 3}])
    assert not row["full0"]


def test_unobserved_runs_are_skipped_and_lengthen_the_interval() -> None:
    flows = interval_flows(
        panel([{"i": 0, "e": 100, "w": 5}, {"i": 1, "e": 100, "w": 5, "observed": False}, {"i": 2, "e": 101, "w": 4}])
    )
    assert len(flows) == 1 and flows.at[0, "interval_min"] == 60.0 and int(flows.at[0, "admits"]) == 1


def test_tombstone_ends_the_series() -> None:
    flows = interval_flows(
        panel(
            [
                {"i": 0, "e": 100, "w": 5},
                {"i": 1, "e": 100, "w": 4},
                {"i": 2, "e": 100, "w": 4, "status": "GONE"},
                {"i": 3, "e": 100, "w": 0},
            ]
        )
    )
    assert len(flows) == 1 and flows.at[0, "t1"] == pd.Timestamp(T0 + timedelta(minutes=30))


def test_null_counts_produce_no_interval() -> None:
    frame = panel([{"i": 0, "e": 100, "w": 5}, {"i": 1, "e": 100, "w": 4}, {"i": 2, "e": 100, "w": 3}])
    frame.loc[1, "waitlist_count"] = pd.NA
    flows = interval_flows(frame)
    assert len(flows) == 1 and flows.at[0, "interval_min"] == 60.0


def test_sections_are_independent_and_sorted() -> None:
    frame = pd.concat(
        [
            panel([{"section_id": "b", "i": 0, "e": 10, "w": 0}, {"section_id": "b", "i": 1, "e": 11, "w": 0}]),
            panel([{"section_id": "a", "i": 0, "e": 10, "w": 2}, {"section_id": "a", "i": 1, "e": 10, "w": 3}]),
        ],
        ignore_index=True,
    )
    flows = interval_flows(frame)
    assert list(flows["section_id"]) == ["a", "b"] and int(flows.at[0, "wl_joins"]) == 1 and int(flows.at[1, "enr_joins"]) == 1


def test_censoring_by_outage_point_event_and_max_interval() -> None:
    rows = [{"i": 0, "e": 100, "w": 5}, {"i": 1, "e": 100, "w": 5}, {"i": 2, "e": 100, "w": 5}, {"i": 3, "e": 100, "w": 5}]
    outage = Outage(start=T0 + timedelta(minutes=40), end=T0 + timedelta(minutes=50), kind="outage", term_id="2268", scope="all", note="")
    other_term = Outage(start=T0 + timedelta(minutes=40), end=None, kind="outage", term_id="2272", scope="all", note="")
    switch = Outage(start=T0 + timedelta(minutes=75), end=None, kind="source_switch", term_id=None, scope="all", note="")
    flows = interval_flows(panel(rows), outages=[outage, other_term, switch])
    assert list(flows["censored"]) == [False, True, True]  # interval 1 overlaps the outage, interval 2 contains the switch
    open_outage = Outage(start=T0 + timedelta(minutes=40), end=None, kind="outage", term_id=None, scope="all", note="")
    flows = interval_flows(panel(rows), outages=[open_outage])
    assert list(flows["censored"]) == [False, True, True]
    flows = interval_flows(panel(rows), max_interval_min=29)
    assert flows["censored"].all()


def test_summary_counts() -> None:
    flows = interval_flows(panel([{"i": 0, "e": 100, "w": 5}, {"i": 1, "e": 102, "w": 3}, {"i": 2, "e": 102, "w": 6}]))
    s = summary(flows)
    assert s["sections"] == 1 and s["intervals"] == 2 and s["admits"] == 2 and s["wl_joins"] == 3
    assert s["share_ambiguous"] == 0.0 and s["median_interval_min"] == 30.0


def test_empty_panel() -> None:
    flows = interval_flows(panel([]).iloc[0:0]) if False else interval_flows(pd.DataFrame(columns=["section_id", "run_started_at", "enrolled_count", "enroll_capacity", "waitlist_count", "waitlist_capacity", "reserved_count", "open_reserved", "status", "section_status", "observed", "source", "scope", "kind"]))
    assert len(flows) == 0 and list(flows.columns) == list(OUTPUT_COLUMNS)
    with pytest.raises(KeyError):
        interval_flows(pd.DataFrame({"section_id": ["1"]}))
