"""Tests for scraper/storage.py (DESIGN_A2 section 2 + addendum)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scraper.schema import COUNT_FIELDS, SNAPSHOT_SCHEMA, SchemaError, rows_to_table
from scraper.storage import (
    RunMeta,
    compute_delta,
    latest_state,
    list_snapshots,
    parse_snapshot_path,
    read_meta,
    read_snapshot,
    snapshot_path,
    table_to_frame,
    write_snapshot,
    write_status,
)
from tests.conftest import make_row

T0 = datetime(2026, 11, 2, 7, 37, tzinfo=timezone.utc)
TERM = "2272"


def meta(kind: str = "baseline", scope: str = "full", at: datetime = T0, **kw) -> RunMeta:
    return RunMeta(run_started_at=at, term_id=TERM, source="sis_api", kind=kind, scope=scope, **kw)


# ---------------------------------------------------------------- paths


def test_snapshot_path_layout(data_root: Path):
    p = snapshot_path(data_root, T0, "baseline")
    assert p == data_root / "snapshots" / "date=2026-11-02" / "0737-baseline.parquet"
    assert snapshot_path(data_root, T0, "delta").name == "0737-delta.parquet"


def test_snapshot_path_uses_utc_date_and_time(data_root: Path):
    pacific = timezone(timedelta(hours=-8))
    local = datetime(2026, 11, 1, 23, 5, tzinfo=pacific)  # 07:05 UTC next day
    p = snapshot_path(data_root, local, "delta")
    assert p.parent.name == "date=2026-11-02"
    assert p.name == "0705-delta.parquet"


def test_snapshot_path_rejects_naive_and_bad_kind(data_root: Path):
    with pytest.raises(ValueError, match="timezone-aware"):
        snapshot_path(data_root, datetime(2026, 11, 2, 7, 37), "baseline")
    with pytest.raises(ValueError, match="kind"):
        snapshot_path(data_root, T0, "full")


def test_parse_snapshot_path(data_root: Path):
    ref = parse_snapshot_path(data_root / "snapshots" / "date=2026-11-02" / "0737-delta.parquet")
    assert ref is not None
    assert (ref.date, ref.hhmm, ref.kind) == (date(2026, 11, 2), "0737", "delta")
    assert parse_snapshot_path(data_root / "snapshots" / "date=2026-11-02" / "notes.txt") is None
    assert parse_snapshot_path(data_root / "snapshots" / "other" / "0737-delta.parquet") is None


# ---------------------------------------------------------------- write / read


def test_write_is_atomic_and_leaves_no_temp_files(data_root: Path):
    table = rows_to_table([make_row()])
    path = write_snapshot(data_root, table, meta())
    assert path.exists()
    leftovers = [p for p in path.parent.iterdir() if p != path]
    assert leftovers == []
    got, _ = read_snapshot(path)
    assert got.equals(table)


def test_write_refuses_overwrite(data_root: Path):
    table = rows_to_table([make_row()])
    write_snapshot(data_root, table, meta())
    with pytest.raises(FileExistsError):
        write_snapshot(data_root, rows_to_table([make_row(enrolled_count=1)]), meta())
    got, _ = read_snapshot(snapshot_path(data_root, T0, "baseline"))
    assert got.to_pylist()[0]["enrolled_count"] == 1500  # original intact


def test_write_validates_table(data_root: Path):
    bad = pa.table({"section_id": ["1"]})
    with pytest.raises(SchemaError):
        write_snapshot(data_root, bad, meta())
    assert list_snapshots(data_root) == []


def test_write_rejects_bad_meta(data_root: Path):
    table = rows_to_table([make_row()])
    with pytest.raises(ValueError, match="kind"):
        write_snapshot(data_root, table, meta(kind="snapshot"))
    with pytest.raises(ValueError, match="scope"):
        write_snapshot(data_root, table, meta(scope="all"))


def test_write_accepts_empty_table(data_root: Path):
    path = write_snapshot(data_root, rows_to_table([]), meta(kind="delta", n_observed=12))
    table, got = read_snapshot(path)
    assert table.num_rows == 0
    assert table.schema.equals(SNAPSHOT_SCHEMA, check_metadata=False)
    assert got.n_written == 0
    assert got.n_observed == 12


def test_metadata_round_trip_priority(data_root: Path):
    m = meta(
        kind="delta",
        scope="priority",
        shard="3/8",
        priority_sha="ab" * 32,
        missing_ids=["30175", "30174"],
        n_observed=2,
        observed_ids=["2", "1", "1"],
    )
    path = write_snapshot(data_root, rows_to_table([make_row()]), m)
    raw = pq.read_schema(path).metadata
    assert all(isinstance(k, bytes) and isinstance(v, bytes) for k, v in raw.items())
    assert json.loads(raw[b"missing_ids"]) == ["30174", "30175"]
    assert json.loads(raw[b"observed_ids"]) == ["1", "2"]
    assert raw[b"n_written"] == b"1"
    assert raw[b"run_started_at"] == b"2026-11-02T07:37:00+00:00"
    _, got = read_snapshot(path)
    assert got == RunMeta(
        run_started_at=T0, term_id=TERM, source="sis_api", kind="delta", scope="priority",
        shard="3/8", priority_sha="ab" * 32, missing_ids=["30174", "30175"],
        n_observed=2, n_written=1, observed_ids=["1", "2"],
    )
    assert read_meta(path) == got


def test_metadata_full_scope_omits_observed_ids(data_root: Path):
    m = meta(kind="delta", scope="full", observed_ids=["1", "2"])
    path = write_snapshot(data_root, rows_to_table([]), m)
    raw = pq.read_schema(path).metadata
    assert b"observed_ids" not in raw
    assert raw[b"shard"] == b"" and raw[b"priority_sha"] == b""
    assert read_meta(path).observed_ids is None


def test_run_meta_from_metadata_rejects_missing_keys():
    with pytest.raises(ValueError, match="missing keys"):
        RunMeta.from_metadata({b"term_id": b"2272"})
    with pytest.raises(ValueError):
        RunMeta.from_metadata(None)


def test_read_snapshot_rejects_non_parquet(tmp_path: Path):
    p = tmp_path / "x.parquet"
    p.write_bytes(b"not parquet")
    with pytest.raises(ValueError):
        read_snapshot(p)
    with pytest.raises(ValueError):
        read_meta(p)


def test_list_snapshots_sorted_and_filtered(data_root: Path):
    d1, d2 = date(2026, 11, 2), date(2026, 11, 3)
    times = [
        (datetime(2026, 11, 3, 0, 7, tzinfo=timezone.utc), "baseline"),
        (datetime(2026, 11, 2, 23, 37, tzinfo=timezone.utc), "delta"),
        (datetime(2026, 11, 2, 0, 7, tzinfo=timezone.utc), "baseline"),
        (datetime(2026, 11, 2, 0, 37, tzinfo=timezone.utc), "delta"),
    ]
    for at, kind in times:
        write_snapshot(data_root, rows_to_table([]), meta(kind=kind, at=at))
    (data_root / "snapshots" / "date=2026-11-02" / ".0800-delta.abc.tmp").write_bytes(b"")
    (data_root / "snapshots" / "README.md").write_text("x")
    names = [f"{p.parent.name}/{p.name}" for p in list_snapshots(data_root)]
    assert names == [
        "date=2026-11-02/0007-baseline.parquet",
        "date=2026-11-02/0037-delta.parquet",
        "date=2026-11-02/2337-delta.parquet",
        "date=2026-11-03/0007-baseline.parquet",
    ]
    assert [p.name for p in list_snapshots(data_root, d1)] == [
        "0007-baseline.parquet", "0037-delta.parquet", "2337-delta.parquet",
    ]
    assert [p.name for p in list_snapshots(data_root, d2)] == ["0007-baseline.parquet"]
    assert list_snapshots(data_root, date(2026, 11, 4)) == []
    assert list_snapshots(data_root / "nope") == []


def test_write_status(data_root: Path):
    p = write_status(data_root, {"last_run_at": T0, "n_observed": 3})
    assert p == data_root / "status.json"
    assert json.loads(p.read_text()) == {"last_run_at": "2026-11-02 07:37:00+00:00", "n_observed": 3}
    write_status(data_root, {"n_observed": 4})
    assert json.loads(p.read_text()) == {"n_observed": 4}
    assert [q.name for q in data_root.iterdir()] == ["status.json"]


# ---------------------------------------------------------------- compute_delta


def previous_from(rows) -> pd.DataFrame:
    return table_to_frame(rows_to_table(rows)).set_index("section_id")


def test_compute_delta_with_no_previous_emits_everything():
    obs = rows_to_table([make_row(section_id="1"), make_row(section_id="2")])
    out = compute_delta(None, obs, {"1", "2"}, fetched_at=T0)
    assert out.equals(obs)


def test_compute_delta_changed_unchanged_new():
    prev = previous_from([
        make_row(section_id="1", enrolled_count=10),
        make_row(section_id="2", enrolled_count=20, reserved_count=None),
        make_row(section_id="3", waitlist_count=5),
        make_row(section_id="4", section_status=None),
    ])
    t1 = T0 + timedelta(minutes=30)
    obs = rows_to_table([
        make_row(section_id="1", enrolled_count=11, fetched_at=t1),  # changed
        make_row(section_id="2", enrolled_count=20, reserved_count=None, fetched_at=t1),  # unchanged (None==None)
        make_row(section_id="3", waitlist_count=5, fetched_at=t1),  # unchanged
        make_row(section_id="4", section_status="A", fetched_at=t1),  # None -> "A" changed
        make_row(section_id="5", fetched_at=t1),  # new
    ])
    out = compute_delta(prev, obs, {"1", "2", "3", "4", "5"}, fetched_at=t1)
    assert out.column("section_id").to_pylist() == ["1", "4", "5"]
    assert out.schema.equals(SNAPSHOT_SCHEMA)
    assert out.to_pylist()[0]["fetched_at"] == t1


def test_compute_delta_identity_change_alone_is_not_a_delta():
    prev = previous_from([make_row(section_id="1", course_key="COMPSCI 61A")])
    obs = rows_to_table([make_row(section_id="1", course_key="COMPSCI 61B", fetched_at=T0 + timedelta(hours=1))])
    out = compute_delta(prev, obs, None, fetched_at=T0 + timedelta(hours=1))
    assert out.num_rows == 0


def test_compute_delta_null_to_value_is_a_change():
    prev = previous_from([make_row(section_id="1", reserved_count=None, open_reserved=None)])
    obs = rows_to_table([make_row(section_id="1", reserved_count=3, open_reserved=None)])
    out = compute_delta(prev, obs, None, fetched_at=T0)
    assert out.column("section_id").to_pylist() == ["1"]


def test_compute_delta_tombstone():
    prev = previous_from([
        make_row(section_id="1", enrolled_count=10),
        make_row(section_id="2", enrolled_count=20, reserved_count=4, is_primary=None, course_key="MATH 1A",
                 subject="MATH", catalog_number="1A", source="classes_site"),
        make_row(section_id="3"),
    ])
    t1 = T0 + timedelta(minutes=30)
    obs = rows_to_table([make_row(section_id="1", enrolled_count=10, fetched_at=t1 + timedelta(seconds=5))])
    # 2 is gone (not observed, not in universe); 3 is in universe but missing -> no tombstone
    out = compute_delta(prev, obs, {"1", "3"}, fetched_at=t1)
    rows = out.to_pylist()
    assert [r["section_id"] for r in rows] == ["2"]
    tomb = rows[0]
    assert tomb["section_status"] == "GONE"
    assert tomb["fetched_at"] == t1
    assert tomb["source"] == "sis_api"  # current run's source, not previous row's
    assert tomb["enrolled_count"] == 20 and tomb["reserved_count"] == 4
    assert tomb["course_key"] == "MATH 1A" and tomb["subject"] == "MATH"
    assert tomb["is_primary"] is None
    assert tomb["term_id"] == TERM


def test_compute_delta_tombstone_source_override_and_empty_observed():
    prev = previous_from([make_row(section_id="9", source="sis_api")])
    out = compute_delta(prev, rows_to_table([]), set(), fetched_at=T0, source="classes_site")
    assert out.to_pylist()[0]["source"] == "classes_site"
    out = compute_delta(prev, rows_to_table([]), set(), fetched_at=T0)
    assert out.to_pylist()[0]["source"] == "sis_api"


def test_compute_delta_no_tombstones_without_universe():
    prev = previous_from([make_row(section_id="1"), make_row(section_id="2")])
    obs = rows_to_table([make_row(section_id="1")])
    out = compute_delta(prev, obs, None, fetched_at=T0)
    assert out.num_rows == 0


def test_compute_delta_already_gone_is_not_re_emitted_and_reappearance_is():
    prev = previous_from([make_row(section_id="1", section_status="GONE"), make_row(section_id="2", section_status="GONE")])
    obs = rows_to_table([make_row(section_id="2", section_status="A")])
    out = compute_delta(prev, obs, {"2"}, fetched_at=T0)
    assert out.column("section_id").to_pylist() == ["2"]
    assert out.to_pylist()[0]["section_status"] == "A"


def test_compute_delta_accepts_section_id_column_frame():
    prev = table_to_frame(rows_to_table([make_row(section_id="1", enrolled_count=1)]))
    obs = rows_to_table([make_row(section_id="1", enrolled_count=2)])
    assert compute_delta(prev, obs, None, fetched_at=T0).num_rows == 1


def test_compute_delta_rejects_naive_fetched_at():
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_delta(None, rows_to_table([]), None, fetched_at=datetime(2026, 11, 2))


# ---------------------------------------------------------------- latest_state


def test_latest_state_none_without_baseline(data_root: Path):
    assert latest_state(data_root, TERM, T0.date()) is None
    write_snapshot(data_root, rows_to_table([make_row()]), meta(kind="delta"))
    assert latest_state(data_root, TERM, T0.date()) is None


def test_latest_state_across_baseline_and_two_deltas(data_root: Path):
    t1, t2 = T0 + timedelta(minutes=30), T0 + timedelta(minutes=60)
    write_snapshot(data_root, rows_to_table([
        make_row(section_id="1", enrolled_count=10),
        make_row(section_id="2", enrolled_count=20, reserved_count=None),
        make_row(section_id="3", enrolled_count=30),
    ]), meta("baseline", at=T0))
    write_snapshot(data_root, rows_to_table([
        make_row(section_id="1", enrolled_count=11, fetched_at=t1),
        make_row(section_id="4", enrolled_count=40, fetched_at=t1),
    ]), meta("delta", at=t1))
    write_snapshot(data_root, rows_to_table([
        make_row(section_id="1", enrolled_count=12, fetched_at=t2),
        make_row(section_id="3", enrolled_count=30, section_status="GONE", fetched_at=t2),
    ]), meta("delta", at=t2))
    # a different term the same day must be ignored
    other = RunMeta(run_started_at=T0 + timedelta(minutes=5), term_id="2268", source="sis_api", kind="baseline", scope="full")
    write_snapshot(data_root, rows_to_table([make_row(section_id="1", term_id="2268", enrolled_count=999)]), other)

    state = latest_state(data_root, TERM, T0.date())
    assert state is not None
    assert state.index.name == "section_id"
    assert list(state.index) == ["1", "2", "3", "4"]
    assert set(state.columns) == set(SNAPSHOT_SCHEMA.names) - {"section_id"}
    assert state.loc["1", "enrolled_count"] == 12
    assert state.loc["1", "fetched_at"] == t2
    assert state.loc["2", "enrolled_count"] == 20
    assert state.loc["2", "reserved_count"] is pd.NA
    assert state.loc["3", "section_status"] == "GONE"
    assert state.loc["4", "enrolled_count"] == 40
    assert str(state["enrolled_count"].dtype) == "Int32"
    # the state feeds compute_delta directly
    obs = rows_to_table([make_row(section_id="1", enrolled_count=12), make_row(section_id="4", enrolled_count=41)])
    delta = compute_delta(state, obs, {"1", "2", "3", "4"}, fetched_at=t2 + timedelta(minutes=30))
    assert delta.column("section_id").to_pylist() == ["4"]


def test_latest_state_is_per_day(data_root: Path):
    write_snapshot(data_root, rows_to_table([make_row(section_id="1")]), meta("baseline", at=T0))
    assert latest_state(data_root, TERM, T0.date() + timedelta(days=1)) is None
    assert latest_state(data_root, TERM, T0.date()) is not None


def test_count_fields_are_the_compared_fields():
    # guard: COUNT_FIELDS drives compute_delta; every count field must be in the schema
    assert all(f in SNAPSHOT_SCHEMA.names for f in COUNT_FIELDS)
