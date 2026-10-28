"""Tests for analysis.backtest_summary: the backtest reports as quotable sentences
that CLAIMS.md and the docs cite verbatim."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from analysis.backtest_summary import main, summarise

METRICS_COLUMNS = [
    "predictor", "n_test", "brier_rows", "share_unknown", "brier", "auc",
    "brier_baseline", "gain", "gain_ci_low", "gain_ci_high", "skill", "share_fallback",
]


def _write_run(run_dir: Path, *, metrics: pd.DataFrame | None, coverage: pd.DataFrame | None = None, report_md: str | None = None) -> None:
    run_dir.mkdir(parents=True)
    if metrics is not None:
        metrics.to_csv(run_dir / "metrics.csv", index=False)
    if coverage is not None:
        coverage.to_csv(run_dir / "coverage.csv", index=False)
    if report_md is not None:
        (run_dir / "report.md").write_text(report_md, encoding="utf-8")


def test_summary_sentences_carry_the_numbers_from_the_input(tmp_path: Path, capsys) -> None:
    reports = tmp_path / "backtest_2268"
    metrics = pd.DataFrame(
        [
            ["bucket", 100, 95, 0.05, 0.25, 0.65, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0],
            ["site", 100, 95, 0.05, 0.21, 0.70, 0.25, 0.04, 0.01, 0.07, 0.16, 0.05],
        ],
        columns=METRICS_COLUMNS,
    )
    coverage = pd.DataFrame([["instruction", 100, 100, 1.0], ["adjustment", 20, 0, 0.0]], columns=["phase", "n", "observable", "share_observable"])
    _write_run(reports / "temporal_deadline", metrics=metrics, coverage=coverage)

    assert main(["--reports", str(reports)]) == 0
    out = capsys.readouterr().out

    assert "temporal_deadline:" in out
    assert "coverage: instruction 100 rows 1.00 observable; adjustment 20 rows 0.00 observable" in out
    assert "scored rows 100" in out
    # bucket is the baseline: no "gain over bucket", but its own Brier and known-outcome rows appear
    assert "bucket  Brier 0.2500" in out and "known-outcome rows 95 (unknown share 0.050)" in out
    assert "gain over bucket" not in out.split("bucket  Brier")[1].split("\n")[0]
    # site carries its gain (with CI), AUC, and fallback share straight from the CSV
    assert "site    Brier 0.2100, gain over bucket +0.0400 [+0.0100, +0.0700], AUC 0.700" in out
    assert "fallback share 0.050" in out


def test_run_with_no_scored_rows_prints_the_report_note_not_a_crash(tmp_path: Path, capsys) -> None:
    reports = tmp_path / "backtest_2268"
    empty_metrics = pd.DataFrame(columns=METRICS_COLUMNS)
    note_report = "# Backtest: tiny (days:14)\n\nSplit `temporal`.\n\n## Notes\n\n- too few scored rows (12); need 30\n"
    _write_run(reports / "temporal_days14", metrics=empty_metrics, report_md=note_report)

    assert main(["--reports", str(reports)]) == 0
    out = capsys.readouterr().out
    assert "temporal_days14:" in out
    assert "no scored rows: too few scored rows (12); need 30" in out


def test_missing_reports_directory_fails_cleanly(tmp_path: Path, capsys) -> None:
    # a --reports path that does not exist at all (typo, wrong term, report never ran):
    # main() must print a clean message and return a non-zero code, not let
    # Path.iterdir() raise an unhandled FileNotFoundError with a traceback.
    missing = tmp_path / "backtest_9999"
    assert not missing.exists()

    assert main(["--reports", str(missing)]) == 2
    out = capsys.readouterr().out
    assert f"--reports {missing}: no such directory" in out


def test_empty_reports_directory_with_no_runs_fails_cleanly(tmp_path: Path, capsys) -> None:
    # distinct from the above: the directory exists (e.g. the term's report dir was
    # created) but no run subdirectories landed in it.
    empty_reports = tmp_path / "backtest_9999"
    empty_reports.mkdir()

    assert main(["--reports", str(empty_reports)]) == 1
    out = capsys.readouterr().out
    assert f"no runs under {empty_reports}" in out


def test_summarise_reports_a_run_dir_missing_metrics_csv(tmp_path: Path) -> None:
    run_dir = tmp_path / "incomplete_run"
    run_dir.mkdir()
    assert summarise(run_dir) == "incomplete_run: no metrics.csv"
