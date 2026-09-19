"""Offline tests for ``python -m scraper.fetch`` (DESIGN_A2 sections 6 and 10).

A FakeSource stands in for the network; ``fetch.build_source`` is monkeypatched
to return it. Storage is the real module writing into a tmp data root. If
``scraper.storage`` is not importable yet the whole file skips.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

storage = pytest.importorskip("scraper.storage")

from scraper import fetch  # noqa: E402  (after importorskip on purpose)
from scraper.schema import SnapshotRow  # noqa: E402
from scraper.sources.base import FetchResult, TermNotPublished  # noqa: E402

TERM = "Fall 2026"
TERM_ID = "2268"


def make_row(section_id: str, *, enrolled: int = 10, waitlist: int = 0, course_key: str = "COMPSCI 61A") -> SnapshotRow:
    subject, catalog = course_key.split(" ", 1)
    return SnapshotRow(
        fetched_at=datetime.now(timezone.utc),
        term_id=TERM_ID,
        section_id=section_id,
        course_key=course_key,
        subject=subject,
        catalog_number=catalog,
        class_number="001",
        section_number="001",
        component="LEC",
        is_primary=None,
        session_id="1",
        enrolled_count=enrolled,
        enroll_capacity=100,
        waitlist_count=waitlist,
        waitlist_capacity=20,
        reserved_count=None,
        open_reserved=None,
        status="O",
        section_status="A",
        source="classes_site",
    )


@dataclass
class FakeSource:
    """Returns canned rows and records how ``fetch`` was called."""

    rows: list[SnapshotRow]
    missing_ids: list[str] = field(default_factory=list)
    scope: str = "full"
    shard: str = ""
    priority_sha: str = ""
    universe_ids: set[str] | None = None
    error: Exception | None = None
    name: str = "classes_site"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def fetch(self, term, *, priority=None, shard=None, time_budget_s=None, limit=None) -> FetchResult:
        self.calls.append({"term": term, "priority": priority, "shard": shard, "time_budget_s": time_budget_s, "limit": limit})
        if self.error is not None:
            raise self.error
        return FetchResult(
            rows=list(self.rows),
            missing_ids=list(self.missing_ids),
            universe_ids=self.universe_ids,
            scope=self.scope,
            shard=self.shard,
            priority_sha=self.priority_sha,
        )


def install(monkeypatch: pytest.MonkeyPatch, source: FakeSource) -> FakeSource:
    monkeypatch.setattr(fetch, "build_source", lambda name, **kwargs: source)
    return source


def base_args(data_root: Path, *extra: str) -> list[str]:
    return ["--term", TERM, "--source", "classes_site", "--data-root", str(data_root), "--priority-file", "none", *extra]


def files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def snapshot_files(root: Path, kind: str) -> list[Path]:
    return sorted(root.glob(f"snapshots/date=*/*-{kind}.parquet"))


def pin_clock(monkeypatch: pytest.MonkeyPatch, when: datetime) -> None:
    monkeypatch.setattr(fetch, "_utcnow", lambda: when)


# ------------------------------------------------------------------ behaviour


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    install(monkeypatch, FakeSource(rows=[make_row("1"), make_row("2")]))
    assert fetch.main(base_args(tmp_path, "--dry-run")) == fetch.EXIT_OK
    assert files_under(tmp_path) == []
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert "kind=baseline" in out[0] and "scope=full" in out[0]
    assert "n_observed=2" in out[0] and "n_written=2" in out[0]
    assert out[0].endswith("path=(dry-run)")


def test_zero_rows_exit_2_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    install(monkeypatch, FakeSource(rows=[], missing_ids=["1", "2"]))
    assert fetch.main(base_args(tmp_path)) == fetch.EXIT_NO_ROWS
    assert files_under(tmp_path) == []
    assert capsys.readouterr().out == ""


def test_first_run_baseline_then_delta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    t0 = datetime(2026, 9, 18, 12, 7, tzinfo=timezone.utc)
    pin_clock(monkeypatch, t0)
    install(monkeypatch, FakeSource(rows=[make_row("1", enrolled=10), make_row("2", enrolled=20)], universe_ids={"1", "2"}))
    assert fetch.main(base_args(tmp_path)) == fetch.EXIT_OK
    baselines = snapshot_files(tmp_path, "baseline")
    assert len(baselines) == 1 and snapshot_files(tmp_path, "delta") == []
    assert baselines[0].parent.name == "date=2026-09-18"
    assert pq.read_table(baselines[0]).num_rows == 2
    assert "kind=baseline" in capsys.readouterr().out

    pin_clock(monkeypatch, t0 + timedelta(minutes=30))
    install(monkeypatch, FakeSource(rows=[make_row("1", enrolled=11), make_row("2", enrolled=20)], universe_ids={"1", "2"}))
    assert fetch.main(base_args(tmp_path)) == fetch.EXIT_OK
    deltas = snapshot_files(tmp_path, "delta")
    assert len(deltas) == 1 and len(snapshot_files(tmp_path, "baseline")) == 1
    delta = pq.read_table(deltas[0])
    assert delta.column("section_id").to_pylist() == ["1"]
    assert delta.column("enrolled_count").to_pylist() == [11]
    out = capsys.readouterr().out
    assert "kind=delta" in out and "n_observed=2" in out and "n_written=1" in out


def test_delta_emits_tombstone_for_vanished_section_in_full_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = datetime(2026, 9, 18, 12, 7, tzinfo=timezone.utc)
    pin_clock(monkeypatch, t0)
    install(monkeypatch, FakeSource(rows=[make_row("1"), make_row("2")], universe_ids={"1", "2"}))
    assert fetch.main(base_args(tmp_path)) == fetch.EXIT_OK
    pin_clock(monkeypatch, t0 + timedelta(minutes=30))
    install(monkeypatch, FakeSource(rows=[make_row("1")], universe_ids={"1"}))
    assert fetch.main(base_args(tmp_path)) == fetch.EXIT_OK
    delta = pq.read_table(snapshot_files(tmp_path, "delta")[0]).to_pylist()
    gone = [r for r in delta if r["section_id"] == "2"]
    assert len(gone) == 1 and gone[0]["section_status"] == "GONE"


def test_force_baseline_writes_second_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = datetime(2026, 9, 18, 12, 7, tzinfo=timezone.utc)
    pin_clock(monkeypatch, t0)
    install(monkeypatch, FakeSource(rows=[make_row("1")]))
    assert fetch.main(base_args(tmp_path)) == fetch.EXIT_OK
    pin_clock(monkeypatch, t0 + timedelta(minutes=30))
    assert fetch.main(base_args(tmp_path, "--force-baseline")) == fetch.EXIT_OK
    assert len(snapshot_files(tmp_path, "baseline")) == 2
    assert snapshot_files(tmp_path, "delta") == []


def test_status_json_contents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = datetime(2026, 9, 18, 12, 7, 3, tzinfo=timezone.utc)
    pin_clock(monkeypatch, t0)
    install(monkeypatch, FakeSource(rows=[make_row("1"), make_row("2")], missing_ids=["9"]))
    assert fetch.main(base_args(tmp_path)) == fetch.EXIT_OK
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["last_run_at"] == t0.isoformat()
    assert status["term_id"] == TERM_ID
    assert status["source"] == "classes_site"
    assert status["kind"] == "baseline"
    assert status["scope"] == "full"
    assert status["n_observed"] == 2
    assert status["n_written"] == 2
    assert status["n_missing"] == 1
    assert isinstance(status["sweep_seconds"], float) and status["sweep_seconds"] >= 0
    assert Path(status["snapshot"]) == snapshot_files(tmp_path, "baseline")[0]
    assert not (tmp_path / "status.json.tmp").exists()


def test_priority_scope_records_observed_ids_and_rotates_shards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    priority_file = tmp_path / "priority.txt"
    priority_file.write_text("# test list\nCOMPSCI *\n")
    data_root = tmp_path / "data"
    data_root.mkdir()
    args = ["--term", TERM, "--source", "classes_site", "--data-root", str(data_root), "--priority-file", str(priority_file), "--n-shards", "4"]

    t0 = datetime(2026, 9, 18, 12, 7, tzinfo=timezone.utc)
    pin_clock(monkeypatch, t0)
    first = install(monkeypatch, FakeSource(rows=[make_row("1"), make_row("2")], scope="priority", shard="0/4", priority_sha="abc"))
    assert fetch.main(args) == fetch.EXIT_OK
    assert first.calls[0]["shard"] == (0, 4)
    assert first.calls[0]["priority"] is not None and first.calls[0]["priority"].patterns == ("COMPSCI *",)

    pin_clock(monkeypatch, t0 + timedelta(minutes=30))
    second = install(monkeypatch, FakeSource(rows=[make_row("1", enrolled=99), make_row("2")], scope="priority", shard="1/4", priority_sha="abc"))
    assert fetch.main(args) == fetch.EXIT_OK
    assert second.calls[0]["shard"] == (1, 4)  # run_index defaults to the number of snapshots today

    delta_path = snapshot_files(data_root, "delta")[0]
    meta = pq.read_schema(delta_path).metadata
    assert meta[b"scope"] == b"priority"
    assert meta[b"shard"] == b"1/4"
    assert json.loads(meta[b"observed_ids"]) == ["1", "2"]


def test_n_shards_zero_disables_sharding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    priority_file = tmp_path / "priority.txt"
    priority_file.write_text("COMPSCI *\n")
    src = install(monkeypatch, FakeSource(rows=[make_row("1")], scope="priority"))
    args = ["--term", TERM, "--source", "classes_site", "--data-root", str(tmp_path / "d"), "--priority-file", str(priority_file), "--n-shards", "0", "--dry-run"]
    assert fetch.main(args) == fetch.EXIT_OK
    assert src.calls[0]["shard"] is None


def test_missing_priority_file_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeSource(rows=[make_row("1")]))
    args = ["--term", TERM, "--source", "classes_site", "--data-root", str(tmp_path), "--priority-file", str(tmp_path / "nope.txt")]
    assert fetch.main(args) == fetch.EXIT_ERROR
    assert files_under(tmp_path) == []


def test_term_not_published_exit_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeSource(rows=[], error=TermNotPublished("Spring 2031 not on listing")))
    assert fetch.main(base_args(tmp_path)) == fetch.EXIT_TERM_NOT_PUBLISHED
    assert files_under(tmp_path) == []


def test_unexpected_error_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeSource(rows=[], error=RuntimeError("boom")))
    assert fetch.main(base_args(tmp_path)) == fetch.EXIT_ERROR
    assert files_under(tmp_path) == []


def test_observed_term_id_wins_over_derived(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [make_row("1")]
    rows[0]["term_id"] = "2272"
    install(monkeypatch, FakeSource(rows=rows))
    assert fetch.main(["--term", "Spring 2027", "--source", "classes_site", "--data-root", str(tmp_path), "--priority-file", "none"]) == fetch.EXIT_OK
    assert json.loads((tmp_path / "status.json").read_text())["term_id"] == "2272"


# ------------------------------------------------------------ pure helpers


def test_resolve_source_name_auto() -> None:
    creds = {"SIS_CLASS_APP_ID": "id", "SIS_CLASS_APP_KEY": "key"}
    assert fetch.resolve_source_name("auto", creds) == "sis_api"
    assert fetch.resolve_source_name("auto", {"SIS_CLASS_APP_ID": "id", "SIS_CLASS_APP_KEY": " "}) == "classes_site"
    assert fetch.resolve_source_name("auto", {}) == "classes_site"
    assert fetch.resolve_source_name("berkeleytime", creds) == "berkeleytime"


def test_build_source_missing_module_gives_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "scraper.sources.berkeleytime", None)  # makes the import raise ImportError
    with pytest.raises(RuntimeError, match="berkeleytime.*not available"):
        fetch.build_source("berkeleytime", data_root=tmp_path, n_shards=8, min_interval_s=1.0, max_concurrency=2)


def test_build_source_sis_api_requires_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scraper.sources.sis_api")
    with pytest.raises(RuntimeError, match="SIS_CLASS_APP_ID"):
        fetch.build_source("sis_api", data_root=tmp_path, n_shards=8, min_interval_s=1.0, max_concurrency=2, env={})


def test_parser_defaults_match_config() -> None:
    from scraper import config

    ns = fetch.build_parser().parse_args(["--term", TERM])
    assert ns.source == config.DEFAULTS["source"]
    assert ns.data_root == Path(config.DEFAULTS["data_root"])
    assert ns.priority_file == config.DEFAULTS["priority_file"]
    assert ns.n_shards == config.DEFAULTS["n_shards"]
    assert ns.run_index is None
    assert ns.time_budget_s == config.DEFAULTS["time_budget_s"]
    assert ns.min_interval_s == config.DEFAULTS["min_interval_s"]
    assert ns.max_concurrency == config.DEFAULTS["max_concurrency"]
    assert ns.force_baseline is False and ns.dry_run is False
    assert ns.limit is None and ns.catalog_max_pages is None
