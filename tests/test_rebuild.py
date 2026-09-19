"""Tests for scraper/rebuild.py (DESIGN_A2 section 3).

The round-trip tests build synthetic runs, write them the way fetch.py does
(the first run of a UTC day is a baseline, a full-scope baseline carries the
tombstones of ids that vanished since the previous day, later runs are deltas
against the state seeded from earlier days) through the storage module, and
assert that ``rebuild_panel`` reproduces exactly the panel obtained by naive
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
from scraper.schema import COUNT_FIELDS, TOMBSTONE_STATUS, rows_to_table
from scraper.storage import (
    RunMeta,
    baseline_with_tombstones,
    carried_state,
    compute_delta,
    latest_state,
    list_snapshots,
    read_snapshot,
    write_snapshot,
)
from tests.conftest import make_row

TERM = "2272"
DAY = datetime(2026, 11, 2, 0, 7, tzinfo=timezone.utc)
N_SECTIONS = 44
ALL_IDS = [str(10000 + i) for i in range(1, N_SECTIONS + 1)]
PRIORITY_IDS = ALL_IDS[:12]
MISSING_ID = ALL_IDS[9]
GONE_ID = ALL_IDS[19]
NEW_ID = str(10000 + N_SECTIONS + 1)
ZOMBIE_A = ALL_IDS[25]  # vanishes on day 2: caught by the first full-scope delta after a priority baseline
ZOMBIE_B = ALL_IDS[26]  # vanishes on day 3: caught by that day's full-scope baseline itself
N_RUNS_DAY1 = 7
DAY2 = [DAY + timedelta(days=1, minutes=30 * k) for k in range(3)]
DAY3 = [DAY + timedelta(days=2, minutes=30 * k) for k in range(2)]


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


def run_spec(at: datetime, scope: str, rows: list[dict[str, Any]], universe: set[str] | None, missing: list[str] = ()) -> dict[str, Any]:
    """One run: time, scope, the source's observed rows (full table), universe (full scope only), missing ids."""
    return dict(at=at, scope=scope, rows=rows, universe=universe, missing=list(missing))


def _snapshot(state: dict[str, dict[str, Any]], at: datetime, ids: list[str]) -> list[dict[str, Any]]:
    return [dict(state[s], fetched_at=at + timedelta(seconds=int(s) % 50)) for s in ids]


def synthetic_day() -> list[dict[str, Any]]:
    """Seven runs on one UTC day: baseline + 6 deltas."""
    runs: list[dict[str, Any]] = []
    t = [DAY + timedelta(minutes=30 * k) for k in range(N_RUNS_DAY1)]
    state = {sid: base_row(sid, t[0]) for sid in ALL_IDS}

    # run 0: full baseline, everything observed
    runs.append(run_spec(t[0], "full", _snapshot(state, t[0], ALL_IDS), set(ALL_IDS)))

    # run 1: full, 5 changes, one section failed to fetch (missing)
    for s in ALL_IDS[:5]:
        state[s]["enrolled_count"] += 1
        state[s]["waitlist_count"] += 2
    state[ALL_IDS[6]]["status"] = "C"
    ids = [s for s in ALL_IDS if s != MISSING_ID]
    runs.append(run_spec(t[1], "full", _snapshot(state, t[1], ids), set(ALL_IDS), [MISSING_ID]))

    # run 2: priority scope, 12 sections observed, 3 changed, no universe
    for s in PRIORITY_IDS[:3]:
        state[s]["waitlist_count"] += 1
    state[PRIORITY_IDS[3]]["reserved_count"] = 3  # None -> 3 (only when i % 4 != 0)
    runs.append(run_spec(t[2], "priority", _snapshot(state, t[2], PRIORITY_IDS), None))

    # run 3: full; GONE_ID drops out of the universe (tombstone); NEW_ID appears; 2 changes
    state[NEW_ID] = base_row(NEW_ID, t[3], course_key="SUBJ NEW", catalog_number="NEW")
    state[ALL_IDS[30]]["enrolled_count"] -= 4
    state[ALL_IDS[31]]["section_status"] = "X"
    universe = {s for s in ALL_IDS if s != GONE_ID} | {NEW_ID}
    runs.append(run_spec(t[3], "full", _snapshot(state, t[3], sorted(universe)), universe))

    # run 4: priority scope while GONE_ID is tombstoned; one change among the priority ids
    state[PRIORITY_IDS[5]]["waitlist_count"] += 3
    runs.append(run_spec(t[4], "priority", _snapshot(state, t[4], PRIORITY_IDS), None))

    # run 5: full; nothing changed anywhere (empty delta file)
    runs.append(run_spec(t[5], "full", _snapshot(state, t[5], sorted(universe)), universe))

    # run 6: full; GONE_ID reappears; NEW_ID changes; MISSING_ID changes
    state[NEW_ID]["waitlist_count"] = 17
    state[MISSING_ID]["enrolled_count"] = 1
    state[GONE_ID]["enrolled_count"] = 77
    universe = set(ALL_IDS) | {NEW_ID}
    runs.append(run_spec(t[6], "full", _snapshot(state, t[6], sorted(universe)), universe))
    return runs


def synthetic_days() -> list[dict[str, Any]]:
    """Day 1 (``synthetic_day``) plus two days that cross the UTC day boundary.

    Day 2: a priority-scope baseline (no universe, so it cannot tombstone
    anything), then the first full-scope delta, from which ZOMBIE_A is absent
    (tombstoned against the state carried from day 1), then a priority run.
    Day 3: a full-scope baseline from which ZOMBIE_B is absent (the baseline
    carries its tombstone) while ZOMBIE_A stays GONE, then an unchanged full run.
    """
    runs = synthetic_day()
    state: dict[str, dict[str, Any]] = {}
    for run in runs:
        for r in run["rows"]:
            state[r["section_id"]] = copy.deepcopy(r)

    state[PRIORITY_IDS[1]]["enrolled_count"] += 5
    runs.append(run_spec(DAY2[0], "priority", _snapshot(state, DAY2[0], PRIORITY_IDS), None))
    universe = (set(ALL_IDS) | {NEW_ID}) - {ZOMBIE_A}
    runs.append(run_spec(DAY2[1], "full", _snapshot(state, DAY2[1], sorted(universe)), universe))
    runs.append(run_spec(DAY2[2], "priority", _snapshot(state, DAY2[2], PRIORITY_IDS), None))

    state[NEW_ID]["enrolled_count"] = 3
    universe = universe - {ZOMBIE_B}
    runs.append(run_spec(DAY3[0], "full", _snapshot(state, DAY3[0], sorted(universe)), universe))
    runs.append(run_spec(DAY3[1], "full", _snapshot(state, DAY3[1], sorted(universe)), universe))
    return runs


def naive_panel(runs: list[dict[str, Any]], source: str = "sis_api") -> list[dict[str, Any]]:
    """Carry-forward over full tables, independent of the delta machinery.

    A full-scope run marks every known id that is neither in its table nor in
    its universe as GONE (whatever its kind). Tombstones count as observed in
    every scope until the section reappears (section 3).
    """
    state: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    days_seen: set[date] = set()
    for run in runs:
        day = run["at"].date()
        kind = "delta" if day in days_seen else "baseline"
        days_seen.add(day)
        table_ids = {r["section_id"] for r in run["rows"]}
        for r in run["rows"]:
            state[r["section_id"]] = copy.deepcopy(r)
        if run["scope"] == "full":
            for sid, row in state.items():
                if sid not in table_ids and sid not in run["universe"] and row["section_status"] != TOMBSTONE_STATUS:
                    row["section_status"] = TOMBSTONE_STATUS
        gone = {sid for sid, row in state.items() if row["section_status"] == TOMBSTONE_STATUS}
        observed = (table_ids - set(run["missing"])) | gone
        for sid in sorted(state):
            out.append({
                "section_id": sid,
                "run_started_at": run["at"],
                **{f: state[sid][f] for f in COUNT_FIELDS},
                "observed": sid in observed,
                "source": source,
                "scope": run["scope"],
                "kind": kind,
            })
    return out


def write_days(data_root: Path, runs: list[dict[str, Any]], source: str = "sis_api") -> None:
    """Write the runs the way fetch.py does.

    The first run of a UTC day is a baseline; a full-scope baseline with a
    known universe carries tombstones for the carried ids missing from it.
    Later runs are deltas against the seeded state. ``observed_ids`` is
    persisted unless the run is a complete full sweep.
    """
    days_seen: set[date] = set()
    for run in runs:
        day = run["at"].date()
        table = rows_to_table(run["rows"])
        universe = run["universe"] if run["scope"] == "full" else None
        if day in days_seen:
            kind = "delta"
            prev = latest_state(data_root, TERM, day)
            assert prev is not None
            table = compute_delta(prev, table, universe, fetched_at=run["at"], source=source)
        else:
            kind = "baseline"
            days_seen.add(day)
            if universe is not None:
                carried = carried_state(data_root, TERM, day)
                table = baseline_with_tombstones(carried, table, universe, fetched_at=run["at"], source=source)
        complete = universe is not None
        meta = RunMeta(
            run_started_at=run["at"], term_id=TERM, source=source, kind=kind, scope=run["scope"],
            missing_ids=list(run["missing"]), n_observed=len(run["rows"]), complete=complete,
            observed_ids=None if complete else [r["section_id"] for r in run["rows"]],
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
    write_days(data_root, runs)
    return runs


@pytest.fixture
def days(data_root: Path):
    runs = synthetic_days()
    write_days(data_root, runs)
    return runs


def test_synthetic_day_shape(data_root: Path, day):
    paths = list_snapshots(data_root)
    kinds = [p.name.split("-")[1].split(".")[0] for p in paths]
    assert kinds == ["baseline"] + ["delta"] * (N_RUNS_DAY1 - 1)
    rows = [read_snapshot(p)[0].num_rows for p in paths]
    assert rows[0] == N_SECTIONS
    assert rows[5] == 0  # the no-change run still wrote an (empty) delta file
    t3, _ = read_snapshot(paths[3])
    gone = [r for r in t3.to_pylist() if r["section_status"] == "GONE"]
    assert [r["section_id"] for r in gone] == [GONE_ID]
    assert read_snapshot(paths[2])[1].observed_ids == sorted(PRIORITY_IDS)
    assert read_snapshot(paths[4])[1].observed_ids == sorted(PRIORITY_IDS)
    m1 = read_snapshot(paths[1])[1]
    assert m1.missing_ids == [MISSING_ID]
    assert m1.complete is True and m1.observed_ids is None
    assert read_snapshot(paths[2])[1].complete is False


def test_round_trip_matches_naive_carry_forward(data_root: Path, day):
    panel = rebuild_panel(data_root, TERM)
    expected = naive_panel(day)
    assert list(panel.columns) == list(PANEL_COLUMNS)
    assert list(PANEL_COLUMNS) == ["section_id", "run_started_at", *COUNT_FIELDS, "observed", "source", "scope", "kind"]
    assert len(panel) == len(expected) == N_SECTIONS * 3 + (N_SECTIONS + 1) * 4
    got = records(panel)
    assert got == expected
    # the panel is sorted by run then section
    keys = [(r["run_started_at"], r["section_id"]) for r in got]
    assert keys == sorted(keys)


def test_round_trip_observed_flags(data_root: Path, day):
    panel = rebuild_panel(data_root, TERM).set_index(["run_started_at", "section_id"])
    t = [DAY + timedelta(minutes=30 * k) for k in range(N_RUNS_DAY1)]
    obs = panel["observed"]
    assert obs.loc[t[0]].all()
    assert not obs.loc[(t[1], MISSING_ID)] and obs.loc[t[1]].sum() == N_SECTIONS - 1
    assert obs.loc[t[2]].sum() == len(PRIORITY_IDS)
    assert obs.loc[(t[2], PRIORITY_IDS[0])] and not obs.loc[(t[2], ALL_IDS[-1])]
    assert obs.loc[(t[3], GONE_ID)]  # tombstone counts as observed
    assert panel.loc[(t[3], GONE_ID), "section_status"] == "GONE"
    # a priority run while GONE_ID is tombstoned: the tombstone still counts as observed (section 3)
    assert obs.loc[(t[4], GONE_ID)] and panel.loc[(t[4], GONE_ID), "section_status"] == "GONE"
    assert obs.loc[t[4]].sum() == len(PRIORITY_IDS) + 1
    assert not obs.loc[(t[4], ALL_IDS[-1])]
    assert obs.loc[(t[5], GONE_ID)] and panel.loc[(t[5], GONE_ID), "section_status"] == "GONE"
    assert obs.loc[(t[5], NEW_ID)]  # new section observed on an unchanged full run
    assert obs.loc[t[5]].all()
    assert panel.loc[(t[6], GONE_ID), "section_status"] == "A"
    assert panel.loc[(t[6], GONE_ID), "enrolled_count"] == 77
    assert panel.loc[(t[6], NEW_ID), "waitlist_count"] == 17
    assert (panel.loc[t[2], "scope"] == "priority").all() and (panel.loc[t[4], "scope"] == "priority").all()
    assert (panel.loc[t[0], "kind"] == "baseline").all() and (panel.loc[t[1], "kind"] == "delta").all()


def test_two_day_round_trip_matches_naive_carry_forward(data_root: Path, days):
    panel = rebuild_panel(data_root, TERM)
    expected = naive_panel(days)
    n_day1 = N_SECTIONS * 3 + (N_SECTIONS + 1) * 4
    assert len(panel) == len(expected) == n_day1 + (N_SECTIONS + 1) * 5
    assert records(panel) == expected


def test_day_boundary_zombies_are_tombstoned(data_root: Path, days):
    paths = list_snapshots(data_root)
    # day 2: the priority baseline has no tombstones; the first full delta holds exactly ZOMBIE_A's
    d2_base, d2_base_meta = read_snapshot(paths[N_RUNS_DAY1])
    d2_delta, _ = read_snapshot(paths[N_RUNS_DAY1 + 1])
    assert d2_base_meta.kind == "baseline" and d2_base_meta.scope == "priority"
    assert TOMBSTONE_STATUS not in set(d2_base.column("section_status").to_pylist())
    assert [(r["section_id"], r["section_status"]) for r in d2_delta.to_pylist()] == [(ZOMBIE_A, TOMBSTONE_STATUS)]
    # day 3: the full baseline carries ZOMBIE_B's tombstone and does not repeat ZOMBIE_A's
    d3_base, d3_meta = read_snapshot(paths[N_RUNS_DAY1 + 3])
    assert d3_meta.kind == "baseline" and d3_meta.scope == "full" and d3_meta.complete is True
    gone = [r for r in d3_base.to_pylist() if r["section_status"] == TOMBSTONE_STATUS]
    assert [r["section_id"] for r in gone] == [ZOMBIE_B]
    assert gone[0]["fetched_at"] == DAY3[0] and gone[0]["source"] == "sis_api"
    assert d3_base.num_rows == (N_SECTIONS + 1 - 2) + 1
    assert d3_meta.n_observed == N_SECTIONS + 1 - 2 and d3_meta.n_written == d3_base.num_rows
    assert read_snapshot(paths[-1])[0].num_rows == 0  # unchanged full run after the baseline

    panel = rebuild_panel(data_root, TERM).set_index(["run_started_at", "section_id"])
    assert panel.loc[(DAY2[0], ZOMBIE_A), "section_status"] == "A" and not panel.loc[(DAY2[0], ZOMBIE_A), "observed"]
    assert panel.loc[(DAY2[1], ZOMBIE_A), "section_status"] == TOMBSTONE_STATUS and panel.loc[(DAY2[1], ZOMBIE_A), "observed"]
    assert panel.loc[(DAY2[2], ZOMBIE_A), "observed"]  # priority run: the tombstone still counts as observed
    assert panel.loc[(DAY2[2], ZOMBIE_B), "section_status"] == "A" and not panel.loc[(DAY2[2], ZOMBIE_B), "observed"]
    assert panel.loc[(DAY3[0], ZOMBIE_B), "section_status"] == TOMBSTONE_STATUS and panel.loc[(DAY3[0], ZOMBIE_B), "observed"]
    assert panel.loc[(DAY3[0], ZOMBIE_A), "section_status"] == TOMBSTONE_STATUS and panel.loc[(DAY3[0], ZOMBIE_A), "observed"]
    assert panel.loc[DAY3[1], "observed"].all()
    assert panel.loc[(DAY3[1], NEW_ID), "enrolled_count"] == 3


def test_partial_full_scope_run_marks_only_its_observed_ids(data_root: Path):
    ids = ALL_IDS[:4]
    write_snapshot(data_root, rows_to_table([base_row(s, DAY) for s in ids]),
                   RunMeta(run_started_at=DAY, term_id=TERM, source="sis_api", kind="baseline", scope="full", complete=True))
    t1 = DAY + timedelta(minutes=30)
    # a truncated full sweep attempted ids[0] and ids[1] only; ids[1] failed
    meta = RunMeta(run_started_at=t1, term_id=TERM, source="sis_api", kind="delta", scope="full",
                   complete=False, observed_ids=[ids[0]], missing_ids=[ids[1]], n_observed=1)
    write_snapshot(data_root, rows_to_table([dict(base_row(ids[0], t1), enrolled_count=1)]), meta)
    panel = rebuild_panel(data_root, TERM)
    run1 = panel[panel["run_started_at"] == t1].set_index("section_id")["observed"]
    assert run1.to_dict() == {ids[0]: True, ids[1]: False, ids[2]: False, ids[3]: False}


def test_tombstones_count_as_observed_in_priority_runs(data_root: Path):
    ids = ALL_IDS[:4]
    write_snapshot(data_root, rows_to_table([base_row(s, DAY) for s in ids]),
                   RunMeta(run_started_at=DAY, term_id=TERM, source="sis_api", kind="baseline", scope="full", complete=True))
    t1, t2 = DAY + timedelta(minutes=30), DAY + timedelta(minutes=60)
    write_snapshot(data_root, rows_to_table([dict(base_row(ids[3], t1), section_status=TOMBSTONE_STATUS)]),
                   RunMeta(run_started_at=t1, term_id=TERM, source="sis_api", kind="delta", scope="full", complete=True))
    write_snapshot(data_root, rows_to_table([]),
                   RunMeta(run_started_at=t2, term_id=TERM, source="sis_api", kind="delta", scope="priority", observed_ids=[ids[0]]))
    panel = rebuild_panel(data_root, TERM)
    run2 = panel[panel["run_started_at"] == t2].set_index("section_id")["observed"]
    assert run2.to_dict() == {ids[0]: True, ids[1]: False, ids[2]: False, ids[3]: True}


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
