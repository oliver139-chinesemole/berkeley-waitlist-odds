"""``python -m analysis.run --meta-from``: which labels of an existing meta.json a run carries
into the site files it writes (the weekly analysis.yml passes ``--meta-from site/data/meta.json``).

A run rebuilds its cohort, so the labels that describe the cohort are its own; it carries only
what it cannot compute (the pre-registration fields), and only from a meta.json describing the
same term and source: the pages print ``prereg_commit`` as "the <term> cohort behind the curves
this site shows was frozen at commit ...", which Spring 2026's would make false on Spring 2027's
own snapshots."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

import analysis.run as run
from tests.test_run import sim_inputs

SPRING_2026_SITE = {"term_id": "2262", "data_source": "berkeleytime_history", "prereg_commit": "7f348ed", "prereg_date": "2026-09-21", "flows": {"admits": 85115}, "backfill": {"sections": 6131}, "cohort_rows_by_scenario": {"central": 531568}}


def _meta(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "published_meta.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_carries_only_the_prereg_fields_from_the_same_term_and_source(tmp_path: Path) -> None:
    old = {"term_id": "2272", "data_source": "own_snapshots", "prereg_commit": "abc1234", "prereg_date": "2027-01-11", "flows": {"admits": 1}, "cohort_rows_by_scenario": {"central": 5}, "backfill": {"sections": 1}, "events": 40}
    assert run.carried_meta(_meta(tmp_path, old), "2272", "own_snapshots") == {"prereg_commit": "abc1234", "prereg_date": "2027-01-11"}


def test_carries_nothing_from_the_published_spring_2026_site_onto_own_spring_2027_data(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert run.carried_meta(_meta(tmp_path, SPRING_2026_SITE), "2272", "own_snapshots") == {}
    assert "carrying none of its labels" in caplog.text


def test_carries_nothing_from_a_backfill_of_the_same_term(tmp_path: Path) -> None:
    fall_backfill = {**SPRING_2026_SITE, "term_id": "2268", "prereg_commit": "a7240f4", "prereg_date": "2026-09-20"}
    assert run.carried_meta(_meta(tmp_path, fall_backfill), "2268", "own_snapshots") == {}


def test_a_missing_meta_from_carries_nothing_and_says_so(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="analysis.run")
    assert run.carried_meta(tmp_path / "missing.json", "2272", "own_snapshots") == {}
    assert "not found" in caplog.text and "carrying nothing" in caplog.text


def _main_with_sim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: list[str]) -> dict:
    """``run.main`` on a small simulated term (loaders and calendar patched, the analysis real);
    returns the meta.json it writes."""
    panel, identity, cal = sim_inputs()
    few = panel[(panel["run_started_at"] < panel["run_started_at"].min() + timedelta(days=3)) & panel["section_id"].isin(sorted(panel["section_id"].unique())[:2])]
    monkeypatch.setattr(run, "load_panel", lambda root, term: few)
    monkeypatch.setattr(run, "section_identity", lambda root, term: identity)
    monkeypatch.setattr(run, "calendar_for", lambda term: cal)
    site = tmp_path / "site"
    argv = ["--term-id", cal.term_id, "--data-root", str(tmp_path), "--data-log", str(tmp_path / "no_log.md"), "--out", str(tmp_path / "out"), "--site-dir", str(site), "--join-every-min", "1440"]
    assert run.main(argv + extra) == 0
    return json.loads((site / "meta.json").read_text(encoding="utf-8"))


def test_main_carries_the_prereg_fields_beside_the_runs_own_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = {"term_id": "9999", "data_source": "own_snapshots", "prereg_commit": "abc1234", "prereg_date": "2027-01-11", "flows": {"admits": -1}, "cohort_rows_by_scenario": {"central": -1}}
    meta = _main_with_sim(tmp_path, monkeypatch, ["--meta-from", str(_meta(tmp_path, old))])
    assert (meta["prereg_commit"], meta["prereg_date"]) == ("abc1234", "2027-01-11")
    assert meta["data_source"] == "own_snapshots" and meta["flows"]["admits"] >= 0 and meta["cohort_rows_by_scenario"]["central"] == meta["cohort_rows"] > 0


def test_main_without_a_matching_meta_writes_no_prereg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = _main_with_sim(tmp_path, monkeypatch, ["--meta-from", str(_meta(tmp_path, SPRING_2026_SITE))])
    assert "prereg_commit" not in meta and "prereg_date" not in meta and "backfill" not in meta
    assert meta["data_source"] == "own_snapshots" and meta["flows"]["admits"] != 85115
