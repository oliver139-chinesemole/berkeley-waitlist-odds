"""Tests for scraper/gaps.py (DESIGN_A2 section 7)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scraper.gaps import breaches, gap_report, main
from scraper.schema import rows_to_table
from scraper.storage import RunMeta, write_snapshot
from tests.conftest import make_row

TERM = "2272"
T0 = datetime(2026, 11, 2, 0, 7, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 2, 4, 0, tzinfo=timezone.utc)


def write_runs(data_root: Path, offsets_min: list[int], term: str = TERM, scopes: list[str] | None = None) -> None:
    for i, off in enumerate(offsets_min):
        at = T0 + timedelta(minutes=off)
        kind = "baseline" if i == 0 else "delta"
        scope = scopes[i] if scopes else "full"
        meta = RunMeta(run_started_at=at, term_id=term, source="sis_api", kind=kind, scope=scope,
                       observed_ids=["1"] if scope == "priority" else None)
        table = rows_to_table([make_row(fetched_at=at, term_id=term)]) if kind == "baseline" else rows_to_table([])
        write_snapshot(data_root, table, meta)


def test_known_timestamps(data_root: Path):
    # gaps: 30, 30, 90, 30 minutes
    write_runs(data_root, [0, 30, 60, 150, 180], scopes=["full", "priority", "full", "priority", "full"])
    rep = gap_report(data_root, TERM, since_hours=24, now=NOW)
    assert rep["n_runs"] == 5
    assert rep["largest_gap_min"] == 90.0
    assert rep["share_gaps_le_45min"] == 0.75
    assert rep["p95_gap_min"] == 81.0  # linear interpolation over [30, 30, 30, 90]
    assert rep["first"] == "2026-11-02T00:07:00+00:00"
    assert rep["last"] == "2026-11-02T03:07:00+00:00"
    assert rep["minutes_since_last"] == 53.0
    assert rep["runs_by_kind"] == {"baseline": 1, "delta": 4}
    assert rep["runs_by_scope"] == {"full": 3, "priority": 2}
    assert rep["by_scope"]["full"]["n_runs"] == 3 and rep["by_scope"]["full"]["largest_gap_min"] == 120.0
    assert rep["by_scope"]["priority"]["largest_gap_min"] == 120.0
    assert rep["term_id"] == TERM and rep["since_hours"] == 24.0
    json.dumps(rep)  # must be JSON-serializable


def test_window_and_term_filter(data_root: Path):
    write_runs(data_root, [0, 30, 60, 90])
    write_runs(data_root, [15, 45], term="2268")
    rep = gap_report(data_root, TERM, since_hours=2.0, now=T0 + timedelta(minutes=90))  # window starts at -30
    assert rep["n_runs"] == 4
    rep = gap_report(data_root, TERM, since_hours=1.0, now=T0 + timedelta(minutes=90))  # window starts at +30
    assert rep["n_runs"] == 3 and rep["first"] == (T0 + timedelta(minutes=30)).isoformat()
    rep = gap_report(data_root, "2268", since_hours=24, now=NOW)
    assert rep["n_runs"] == 2 and rep["largest_gap_min"] == 30.0
    # runs after `now` are ignored
    rep = gap_report(data_root, TERM, since_hours=24, now=T0 + timedelta(minutes=45))
    assert rep["n_runs"] == 2


def test_empty_and_single_run(data_root: Path):
    rep = gap_report(data_root, TERM, now=NOW)
    assert rep["n_runs"] == 0
    assert rep["largest_gap_min"] is None and rep["p95_gap_min"] is None and rep["share_gaps_le_45min"] is None
    assert rep["first"] is None and rep["last"] is None and rep["minutes_since_last"] is None
    assert rep["runs_by_kind"] == {} and rep["by_scope"] == {}
    write_runs(data_root, [0])
    rep = gap_report(data_root, TERM, now=NOW)
    assert rep["n_runs"] == 1 and rep["largest_gap_min"] is None
    assert rep["first"] == rep["last"] == T0.isoformat()


def test_gap_report_uses_current_time_by_default(data_root: Path, monkeypatch):
    write_runs(data_root, [0, 30])
    monkeypatch.setattr("scraper.gaps._utcnow", lambda: NOW)
    assert gap_report(data_root, TERM)["n_runs"] == 2
    monkeypatch.setattr("scraper.gaps._utcnow", lambda: NOW + timedelta(days=3))
    assert gap_report(data_root, TERM)["n_runs"] == 0


def test_breaches():
    rep = {"n_runs": 5, "largest_gap_min": 90.0}
    assert breaches(rep, 90.0, None) == []
    assert breaches(rep, 89.9, None)
    assert breaches(rep, None, 5) == []
    assert breaches(rep, None, 6)
    assert len(breaches(rep, 10.0, 40)) == 2
    assert breaches({"n_runs": 1, "largest_gap_min": None}, 90.0, None) == []


def test_cli_exit_codes(data_root: Path, capsys):
    write_runs(data_root, [0, 30, 60, 150, 180])
    base = ["--data-root", str(data_root), "--term-id", TERM, "--hours", "24", "--now", NOW.isoformat()]
    assert main(base + ["--fail-if-gap-min", "90", "--fail-if-runs-lt", "5"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_runs"] == 5 and out["largest_gap_min"] == 90.0

    assert main(base + ["--fail-if-gap-min", "60"]) == 1
    captured = capsys.readouterr()
    assert "BREACH" in captured.err and json.loads(captured.out)["largest_gap_min"] == 90.0

    assert main(base + ["--fail-if-runs-lt", "40"]) == 1
    assert "fewer than 40" in capsys.readouterr().err

    assert main(base) == 0  # no thresholds: never fails
    assert main(["--data-root", str(data_root), "--term-id", TERM, "--now", "2026-11-02T04:00:00", "--fail-if-gap-min", "90"]) == 0


def test_cli_requires_args():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
