"""backtest.json for the Accuracy page, from the backtest report directories."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.export_backtest import export_backtest, main, read_run, which_label

METRICS = """predictor,n_test,brier_rows,share_unknown,brier,auc,brier_baseline,gain,gain_ci_low,gain_ci_high,skill,share_fallback
bucket,2938,2938,0.0,0.314678892751093,0.5784507697935025,0.314678892751093,0.0,0.0,0.0,0.0,0.0
site,2938,2938,0.0,0.2860266848196052,0.6175740593721943,0.314678892751093,0.028652207931487816,-0.034045079325094,0.08189032564652421,0.09105220779504697,0.1259
cox,2938,2938,0.0,0.5104600848740213,0.5867506255611346,0.314678892751093,-0.19578119212292827,-0.22669702782386147,-0.14999590338457705,-0.6221618183898616,0.0871
"""
CALIBRATION = """predictor,decile,n,weight,predicted,observed
bucket,0,829.0,829.0,0.24466322237153315,0.28347406513872137
bucket,1,829.0,829.0,0.3624150296733157,0.38721351025331724
site,0,300.0,300.0,0.7,0.61
"""
COVERAGE = """phase,n,observable,share_observable
adjustment,1085,0,0.0
phase1,7512,4688,0.624
"""
BY_BUCKET = """position_bucket,n,share_unknown,brier_bucket,brier_course,brier_site,brier_cox
1-5,6010,0.0,0.2577,0.2577,0.2703,0.2237
"""
REPORT = """# Backtest: Fall 2026 temporal (days:14)

Split `temporal`, horizon `days:14`: 87324 training rows, 2938 scored test rows, 0 test rows past their horizon at joining and 9739 whose follow-up ended before their horizon (neither scored).
"""


def make_reports(root: Path) -> Path:
    reports = root / "backtest_2268"
    run = reports / "temporal_days14"
    run.mkdir(parents=True)
    (run / "metrics.csv").write_text(METRICS)
    (run / "calibration.csv").write_text(CALIBRATION)
    (run / "coverage.csv").write_text(COVERAGE)
    (run / "by_bucket.csv").write_text(BY_BUCKET)
    (run / "report.md").write_text(REPORT)
    empty = reports / "temporal_days28"  # a run with no observable rows writes only the header
    empty.mkdir()
    (empty / "metrics.csv").write_text(METRICS.splitlines()[0] + "\n")
    (empty / "calibration.csv").write_text("")  # a run with no observable rows leaves this empty
    (reports / "notes").mkdir()  # not a run
    return reports


def test_read_run_parses_every_table(tmp_path: Path) -> None:
    reports = make_reports(tmp_path)
    run = read_run(reports / "temporal_days14")
    assert run["split"] == "temporal" and run["which"] == "days14" and run["horizon_label"] == "within 14 days"
    assert run["counts"] == {"train": 87324, "test": 2938, "past": 0, "unobservable": 9739}
    assert [m["predictor"] for m in run["metrics"]] == ["bucket", "site", "cox"]
    site = run["metrics"][1]
    assert site["gain"] == pytest.approx(0.0287, abs=1e-4) and site["gain_ci_low"] == pytest.approx(-0.034, abs=1e-3) and site["n_test"] == 2938
    assert run["calibration"]["site"] == [{"decile": 0, "n": 300.0, "weight": 300.0, "predicted": 0.7, "observed": 0.61}]
    assert run["coverage"][1] == {"phase": "phase1", "n": 7512, "observable": 4688, "share_observable": 0.624}
    assert run["by_bucket"][0]["position_bucket"] == "1-5" and run["by_phase"] == []
    assert read_run(reports / "notes") is None


def test_export_skips_empty_runs_and_labels_predictors(tmp_path: Path) -> None:
    reports = make_reports(tmp_path)
    out = export_backtest(reports, tmp_path / "site" / "backtest.json", term_id="2268", term_name="Fall 2026", meta={"data_source": "berkeleytime_history"})
    info = json.loads(out.read_text())
    assert info["term_id"] == "2268" and info["term_name"] == "Fall 2026" and info["data_source"] == "berkeleytime_history"
    assert [r["name"] for r in info["runs"]] == ["temporal_days14"]
    assert set(info["predictors"]) == {"bucket", "course", "site", "cox"}
    assert "NaN" not in out.read_text()


def test_export_without_reports_writes_no_runs(tmp_path: Path) -> None:
    out = export_backtest(tmp_path / "missing", tmp_path / "backtest.json", term_id="2272")
    assert json.loads(out.read_text())["runs"] == []


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    reports = make_reports(tmp_path)
    assert main(["--reports", str(reports), "--term-id", "2268", "--out", str(tmp_path / "b.json"), "--data-source", "berkeleytime_history"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["runs"] == ["temporal_days14"]


def test_which_labels() -> None:
    assert which_label("days28") == "within 28 days" and which_label("deadline").startswith("by the last") and which_label("instruction").startswith("by the first")
