"""Tests for analysis.profile on hand-built and simulated panels."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from analysis.profile import profile_panel
from analysis.synthetic import SimConfig, simulate

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def panel(rows: list[dict]) -> pd.DataFrame:
    records = []
    for r in rows:
        records.append(
            {
                "section_id": r.get("s", "1"),
                "run_started_at": T0 + timedelta(minutes=30 * r["i"]),
                "enrolled_count": r.get("e", 10),
                "enroll_capacity": r.get("c", 100),
                "waitlist_count": r.get("w", 0),
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


def test_profile_counts_and_impossible_states() -> None:
    rows = [
        {"s": "1", "i": 0, "e": 101, "c": 100, "w": 3},  # enrolled above capacity, waitlist while... no seats open
        {"s": "1", "i": 1, "e": 90, "c": 100, "w": 2, "open_res": 0},  # waitlist while unreserved seats open
        {"s": "1", "i": 2, "e": 90, "c": 100, "w": 2, "open_res": 10},  # seats open but all reserved: fine
        {"s": "2", "i": 0, "w": 25, "wc": 20},  # waitlist above waitlist capacity
        {"s": "2", "i": 1, "observed": False},
        {"s": "2", "i": 2, "status": "GONE"},
        {"s": "2", "i": 3},  # reappeared after a tombstone
    ]
    prof = profile_panel(panel(rows))
    assert prof.runs == 4 and prof.sections == 2 and prof.rows == 7
    assert prof.observed_share == 6 / 7
    imp = prof.impossible.set_index("kind")["rows"]
    assert imp["enrolled above capacity"] == 1
    assert imp["waitlist above waitlist capacity"] == 1
    # section 1 row 1 (90 of 100 with 0 reserved) and section 2 row 0 (10 of 100, no reserved info)
    assert imp["waitlist while unreserved seats open"] == 2
    assert imp["waitlist while seats open (no reserved info)"] == 1  # only section 2 row 0 lacks reserved info
    assert prof.vanished == 1 and prof.reappeared == 1
    assert prof.run_gaps_min["max"] == 30.0
    assert set(prof.big_jumps["column"]) <= {"enrolled_count", "waitlist_count", "enroll_capacity"}
    md = prof.as_markdown()
    assert "## Panel profile" in md and "Vanished sections (tombstoned): 1" in md


def test_profile_on_simulated_panel() -> None:
    p, _, _ = simulate(SimConfig(seed=2, n_sections=10, days=3))
    prof = profile_panel(p)
    assert prof.runs == p["run_started_at"].nunique() and prof.sections == 10
    assert prof.impossible.set_index("kind")["rows"]["enrolled above capacity"] == 0
    assert prof.null_rates["enrolled_count"] == 0.0
    assert prof.sections_by_observations.sum() == 10


def test_profile_empty() -> None:
    prof = profile_panel(panel([{"i": 0}]).iloc[0:0])
    assert prof.runs == 0 and prof.sections == 0 and prof.vanished == 0 and "## Panel profile" in prof.as_markdown()
