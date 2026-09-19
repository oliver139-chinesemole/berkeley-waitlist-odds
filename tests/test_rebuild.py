"""Tests for scraper/rebuild.py (DESIGN_A2 section 3).

The round-trip test builds one synthetic UTC day of runs, writes them as a
baseline plus deltas through the storage module, and asserts that
``rebuild_panel`` reproduces exactly the panel obtained by naive
carry-forward over the full per-run tables (which never touch the delta
machinery), observed flags included.
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from scraper.rebuild import PANEL_COLUMNS, rebuild_panel
from scraper.schema import COUNT_FIELDS, rows_to_table
from scraper.storage import RunMeta, compute_delta, latest_state, write_snapshot
from tests.conftest import make_row

TERM = "2272"
DAY = datetime(2026, 11, 2, 0, 7, tzinfo=timezone.utc)
N_SECTIONS = 44
ALL_IDS = [str(10000 + i) for i in range(1, N_SECTIONS + 1)]
PRIORITY_IDS = ALL_IDS[:12]
MISSING_ID = ALL_IDS[9]
GONE_ID = ALL_IDS[19]
NEW_ID = str(10000 + N_SECTIONS + 1)


def base_row(sid: str, at: datetime, **kw: Any) -> dict[str, Any]:
    i = int(sid) - 10000
    fields: dict[str, Any] = dict(
        section_id=sid,
        fetched_at=at + timedelta(seconds=i % 50),
        course_key=f"SUBJ {i}",
        catalog_number=str(i),
        subject="SUBJ",
        class_number=f"{i:03d}",
        section_number=f"{i:03d}",
        component="LEC" if i % 3 else "DIS",
        is_primary=None if i % 7 == 0 else (i % 3 != 0),
        enrolled_count=100 + i,
        enroll_capacity=150,
        waitlist_count=i % 5,
        waitlist_capacity=20,
        reserved_count=None if i % 4 else i,
        open_reserved=None if i % 4 else 0,
        status="O" if i % 2 else "W",
        section_status="A",
        term_id=TERM,
    )
    fields.update(kw)
    return dict(make_row(**fields))


def synthetic_day() -> list[dict[str, Any]]:
    """Six runs: baseline + 5 deltas. Each run: time, scope, the source's
    observed rows (full table), universe (full scope only), missing ids."""
    runs: list[dict[str, Any]] = []
    t = [DAY + timedelta(minutes=30 * k) for k in range(6)]
    state = {sid: base_row(sid, t[0]) for sid in ALL_IDS}

    def snapshot(at: datetime, ids: list[str]) -> list[dict[str, Any]]:
        return [dict(state[s], fetched_at=at + timedelta(seconds=int(s) % 50)) for s in ids]

    # run 0: full baseline, everything observed
    runs.append(dict(at=t[0], scope="full", rows=snapshot(t[0], ALL_IDS), universe=set(ALL_IDS), missing=[]))

    # run 1: full, 5 changes, one section failed to fetch (missing)
    for s in ALL_IDS[:5]:
        state[s]["enrolled_count"] += 1
        state[s]["waitlist_count"] += 2
    state[ALL_IDS[6]]["status"] = "C"
    ids = [s for s in ALL_IDS if s != MISSING_ID]
    runs.append(dict(at=t[1], scope="full", rows=snapshot(t[1], ids), universe=set(ALL_IDS), missing=[MISSING_ID]))

    # run 2: priority scope, 12 sections observed, 3 changed, no universe
    for s in PRIORITY_IDS[:3]:
        state[s]["waitlist_count"] += 1
    state[PRIORITY_IDS[3]]["reserved_count"] = 3  # None -> 3 (only when i % 4 != 0)
    runs.append(dict(at=t[2], scope="priority", rows=snapshot(t[2], PRIORITY_IDS), universe=None, missing=[]))

    # run 3: full; GONE_ID drops out of the universe (tombstone); NEW_ID appears; 2 changes
    state[NEW_ID] = base_row(NEW_ID, t[3], course_key="SUBJ NEW", catalog_number="NEW")
    state[ALL_IDS[30]]["enrolled_count"] -= 4
    state[ALL_IDS[31]]["section_status"] = "X"
    universe = {s for s in ALL_IDS if s != GONE_ID} | {NEW_ID}
    runs.append(dict(at=t[3], scope="full", rows=snapshot(t[3], sorted(universe)), universe=universe, missing=[]))

    # run 4: full; nothing changed anywhere (empty delta file)
    runs.append(dict(at=t[4], scope="full", rows=snapshot(t[4], sorted(universe)), universe=universe, missing=[]))

    # run 5: full; GONE_ID reappears; NEW_ID changes; MISSING_ID changes
    state[NEW_ID]["waitlist_count"] = 17
    state[MISSING_ID]["enrolled_count"] = 1
    state[GONE_ID]["enrolled_count"] = 77
    universe = set(ALL_IDS) | {NEW_ID}
    runs.append(dict(at=t[5], scope="full", rows=snapshot(t[5], sorted(universe)), universe=universe, missing=[]))
    return runs


def naive_panel(runs: list[dict[str, Any]], source: str = "sis_api") -> list[dict[str, Any]]:
    """Carry-forward over full tables, independent of the delta machinery."""
    state: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for k, run in enumerate(runs):
        table_ids = {r["section_id"] for r in run["rows"]}
        for r in run["rows"]:
            state[r["section_id"]] = copy.deepcopy(r)
        if run["scope"] == "full":
            for sid, row in state.items():
                if sid not in table_ids and sid not in run["universe"] and row["section_status"] != "GONE":
                    row["section_status"] = "GONE"
            observed = table_ids | {sid for sid, row in state.items() if row["section_status"] == "GONE"}
        else:
            observed = set(table_ids)
        observed -= set(run["missing"])
        for sid in sorted(state):
            out.append({
                "section_id": sid,
                "run_started_at": run["at"],
                **{f: state[sid][f] for f in COUNT_FIELDS},
                "observed": sid in observed,
                "source": source,
                "scope": run["scope"],
                "kind": "baseline" if k == 0 else "delta",
            })
    return out


def write_day(data_root: Path, runs: list[dict[str, Any]]) -> None:
    """Write the runs the way fetch.py would: first run baseline, rest deltas."""
    for k, run in enumerate(runs):
        table = rows_to_table(run["rows"])
        kind = "baseline" if k == 0 else "delta"
        if kind == "delta":
            prev = latest_state(data_root, TERM, run["at"].date())
            assert prev is not None
            table = compute_delta(prev, table, run["universe"] if run["scope"] == "full" else None, fetched_at=run["at"])
        meta = RunMeta(
            run_started_at=run["at"], term_id=TERM, source="sis_api", kind=kind, scope=run["scope"],
            missing_ids=list(run["missing"]), n_observed=len(run["rows"]),
            observed_ids=[r["section_id"] for r in run["rows"]] if run["scope"] == "priority" else None,
        )
        write_snapshot(data_root, table, meta)


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    for rec in df.to_dict("records"):
        clean = {}
        for k, v in rec.items():
            if v is pd.NA or v is None:
                clean[k] = None
            elif isinstance(v, pd.Timestamp):
                clean[k] = v.to_pydatetime()
            elif hasattr(v, "item"):
                clean[k] = v.item()
            else:
                clean[k] = v
        out.append(clean)
    return out


@pytest.fixture
def day(data_root: Path):
    runs = synthetic_day()
    write_day(data_root, runs)
    return runs


def test_synthetic_day_shape(data_root: Path, day):
    from scraper.storage import list_snapshots, read_snapshot

    paths = list_snapshots(data_root)
    kinds = [p.name.split("-")[1].split(".")[0] for p in paths]
    assert kinds == ["baseline"] + ["delta"] * 5
    rows = [read_snapshot(p)[0].num_rows for p in paths]
    assert rows[0] == N_SECTIONS
    assert rows[4] == 0  # the no-change run still wrote an (empty) delta file
    t3, m3 = read_snapshot(paths[3])
    gone = [r for r in t3.to_pylist() if r["section_status"] == "GONE"]
    assert [r["section_id"] for r in gone] == [GONE_ID]
    assert read_snapshot(paths[2])[1].observed_ids == sorted(PRIORITY_IDS)
    assert read_snapshot(paths[1])[1].missing_ids == [MISSING_ID]


def test_round_trip_matches_naive_carry_forward(data_root: Path, day):
    panel = rebuild_panel(data_root, TERM)
    expected = naive_panel(day)
    assert list(panel.columns) == list(PANEL_COLUMNS)
    assert list(PANEL_COLUMNS) == ["section_id", "run_started_at", *COUNT_FIELDS, "observed", "source", "scope", "kind"]
    assert len(panel) == len(expected) == N_SECTIONS * 3 + (N_SECTIONS + 1) * 3
    got = records(panel)
    assert got == expected
    # the panel is sorted by run then section
    keys = [(r["run_started_at"], r["section_id"]) for r in got]
    assert keys == sorted(keys)


def test_round_trip_observed_flags(data_root: Path, day):
    panel = rebuild_panel(data_root, TERM).set_index(["run_started_at", "section_id"])
    t = [DAY + timedelta(minutes=30 * k) for k in range(6)]
    obs = panel["observed"]
    assert obs.loc[t[0]].all()
    assert not obs.loc[(t[1], MISSING_ID)] and obs.loc[t[1]].sum() == N_SECTIONS - 1
    assert obs.loc[t[2]].sum() == len(PRIORITY_IDS)
    assert obs.loc[(t[2], PRIORITY_IDS[0])] and not obs.loc[(t[2], ALL_IDS[-1])]
    assert obs.loc[(t[3], GONE_ID)]  # tombstone counts as observed
    assert panel.loc[(t[3], GONE_ID), "section_status"] == "GONE"
    assert obs.loc[(t[4], GONE_ID)] and panel.loc[(t[4], GONE_ID), "section_status"] == "GONE"
    assert obs.loc[(t[4], NEW_ID)]  # new section observed on an unchanged full run
    assert obs.loc[t[4]].all()
    assert panel.loc[(t[5], GONE_ID), "section_status"] == "A"
    assert panel.loc[(t[5], GONE_ID), "enrolled_count"] == 77
    assert panel.loc[(t[5], NEW_ID), "waitlist_count"] == 17
    assert (panel.loc[t[2], "scope"] == "priority").all()
    assert (panel.loc[t[0], "kind"] == "baseline").all() and (panel.loc[t[1], "kind"] == "delta").all()


def test_panel_dtypes(data_root: Path, day):
    panel = rebuild_panel(data_root, TERM)
    assert str(panel["enrolled_count"].dtype) == "Int32"
    assert str(panel["reserved_count"].dtype) == "Int32"
    assert str(panel["observed"].dtype) == "boolean"
    assert str(panel["run_started_at"].dtype).startswith("datetime64[") and "UTC" in str(panel["run_started_at"].dtype)
    assert panel["reserved_count"].isna().any()


def test_rebuild_filters_by_term_and_range(data_root: Path, day):
    other = RunMeta(run_started_at=DAY + timedelta(minutes=1), term_id="2268", source="sis_api", kind="baseline", scope="full")
    write_snapshot(data_root, rows_to_table([dict(base_row("99999", DAY), term_id="2268")]), other)
    panel = rebuild_panel(data_root, TERM)
    assert "99999" not in set(panel["section_id"])
    assert rebuild_panel(data_root, "2268")["section_id"].tolist() == ["99999"]
    assert rebuild_panel(data_root, "0000").empty
    assert list(rebuild_panel(data_root, "0000").columns) == list(PANEL_COLUMNS)
    assert rebuild_panel(data_root, TERM, start=date(2026, 11, 3)).empty
    assert len(rebuild_panel(data_root, TERM, end=date(2026, 11, 1))) == 0


def test_rebuild_carries_state_across_days_and_warms_up_before_start(data_root: Path, day):
    day2 = DAY + timedelta(days=1)
    # next day's baseline is priority scope: only 3 sections, one changed
    rows = [base_row(s, day2) for s in ALL_IDS[:3]]
    rows[0]["enrolled_count"] = 5
    meta = RunMeta(run_started_at=day2, term_id=TERM, source="classes_site", kind="baseline", scope="priority",
                   n_observed=3, observed_ids=[r["section_id"] for r in rows])
    write_snapshot(data_root, rows_to_table(rows), meta)
    full = rebuild_panel(data_root, TERM)
    last = full[full["run_started_at"] == day2].set_index("section_id")
    assert len(last) == N_SECTIONS + 1  # everything from day 1 carried forward
    assert last.loc[ALL_IDS[0], "enrolled_count"] == 5
    assert last.loc[ALL_IDS[0], "observed"] and not last.loc[ALL_IDS[-1], "observed"]
    assert last.loc[NEW_ID, "waitlist_count"] == 17  # carried from day 1's last run
    assert (last["source"] == "classes_site").all()
    windowed = rebuild_panel(data_root, TERM, start=day2.date())
    assert windowed["run_started_at"].nunique() == 1
    pd.testing.assert_frame_equal(windowed.reset_index(drop=True), full[full["run_started_at"] == day2].reset_index(drop=True))


def test_priority_run_without_observed_ids_falls_back_to_file_ids(data_root: Path, caplog):
    rows = [base_row(s, DAY) for s in ALL_IDS[:4]]
    write_snapshot(data_root, rows_to_table(rows), RunMeta(run_started_at=DAY, term_id=TERM, source="sis_api", kind="baseline", scope="full"))
    t1 = DAY + timedelta(minutes=30)
    changed = [dict(base_row(ALL_IDS[0], t1), enrolled_count=1)]
    write_snapshot(data_root, rows_to_table(changed), RunMeta(run_started_at=t1, term_id=TERM, source="sis_api", kind="delta", scope="priority"))
    with caplog.at_level("WARNING"):
        panel = rebuild_panel(data_root, TERM)
    run1 = panel[panel["run_started_at"] == t1].set_index("section_id")["observed"]
    assert run1.tolist() == [True, False, False, False]
    assert any("observed_ids" in m for m in caplog.messages)
