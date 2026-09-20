"""Tests for analysis.backtest: IPCW scoring, the four predictors, the splits and the CLI."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis.backtest import (
    PREDICTORS,
    PooledKM,
    brier,
    calibration_table,
    censor_at,
    grouped_folds,
    horizon_days,
    ipcw_weights,
    main,
    observability,
    run_backtest,
    temporal_split,
    weighted_auc,
    write_report,
)
from analysis.calendar import SPRING_2027, TermCalendar
from tests.test_survival import T0, synthetic_cohort


def test_ipcw_toy_example() -> None:
    """Why unknown outcomes cannot simply be dropped: with independent censoring the
    complete cases keep every early clearing and lose only the slow ones, so the
    naive clearing rate at 7 days is biased upward; IPCW recovers the truth."""
    rng = np.random.default_rng(0)
    n = 4000
    t = rng.exponential(5.0, n)  # true time to clear: P(T <= 7) = 1 - exp(-7/5)
    c = rng.exponential(6.0, n)  # independent censoring
    duration = np.minimum(t, c)
    event = (t <= c).astype(int)
    horizon = np.full(n, 7.0)
    y, w = ipcw_weights(duration, event, horizon)
    truth = 1.0 - np.exp(-7.0 / 5.0)
    ipcw = float(np.sum(w * y) / np.sum(w))
    naive = float(y[w > 0].mean())
    assert (w == 0).sum() > 0.1 * n  # a real share of rows has an unknown outcome
    assert abs(ipcw - truth) < 0.03
    assert naive > truth + 0.05
    assert abs(ipcw - truth) < abs(naive - truth)
    # a constant prediction equal to the truth scores better than the naive rate under IPCW
    assert brier(y, np.full(n, truth), w) < brier(y, np.full(n, naive), w)


def test_weighted_auc_and_calibration() -> None:
    y = np.array([0, 1, 1, 0, 1, 0], dtype=float)  # deliberately unsorted so the ranking has to be done
    p = np.array([0.2, 0.9, 0.8, 0.1, 0.3, 0.3])
    w = np.ones(6)
    # pairs (pos, neg): 3 x 3 = 9; positives 0.9, 0.8 beat all three negatives (6), 0.3 beats 0.2 and 0.1 (2) and ties 0.3 (0.5)
    assert weighted_auc(y, p, w) == pytest.approx(8.5 / 9)
    assert weighted_auc(y, np.where(y == 1, 1.0, 0.0), w) == 1.0
    assert weighted_auc(y, np.full(6, 0.5), w) == 0.5
    w2 = np.array([1, 1, 1, 1, 0, 2.0])  # dropping the 0.3 positive and doubling the 0.3 negative
    assert weighted_auc(y, p, w2) == pytest.approx(1.0)
    cal = calibration_table(y, p, w, deciles=3)
    assert list(cal.columns) == ["decile", "n", "weight", "predicted", "observed"] and cal["n"].sum() == 6
    assert (cal["observed"].diff().dropna() >= 0).all()


def test_horizons() -> None:
    join = pd.to_datetime(pd.Series([datetime(2027, 2, 5, 12, tzinfo=timezone.utc), datetime(2027, 2, 7, tzinfo=timezone.utc), datetime(2027, 1, 18, tzinfo=timezone.utc)]), utc=True)
    frame = pd.DataFrame({"join_time": join})
    assert horizon_days(frame, SPRING_2027, "deadline").tolist() == pytest.approx([0.5, -1.0, 19.0])  # end of Feb 5
    assert horizon_days(frame, SPRING_2027, "instruction").tolist() == pytest.approx([-17.5, -19.0, 1.0])
    assert horizon_days(frame, SPRING_2027, "days:14").tolist() == [14.0, 14.0, 14.0]
    with pytest.raises(ValueError):
        horizon_days(frame, SPRING_2027, "weeks:2")


def test_censor_at_and_temporal_split() -> None:
    cohort = synthetic_cohort()
    split_at = pd.Timestamp(datetime(2026, 11, 23, tzinfo=timezone.utc))
    train, test = temporal_split(cohort, split_at)
    assert (pd.to_datetime(train["join_time"], utc=True) < split_at).all() and (pd.to_datetime(test["join_time"], utc=True) >= split_at).all()
    cap = (split_at - pd.to_datetime(train["join_time"], utc=True)).dt.total_seconds() / 86400.0
    assert (train["duration_days"] <= cap + 1e-9).all() and (train["duration_days"] > 0).all()
    capped = cohort.loc[train.index, "duration_days"] > cap
    assert capped.any() and (train.loc[capped, "event"] == 0).all()
    untouched = ~capped
    assert (train.loc[untouched, "event"] == cohort.loc[train.index[untouched], "event"]).all()
    raw_train, _ = temporal_split(cohort, split_at, as_of=False)
    assert len(raw_train) >= len(train) and (raw_train["duration_days"] >= train.reindex(raw_train.index)["duration_days"].fillna(0)).all()
    one = censor_at(cohort.head(1).assign(duration_days=30.0, event=1), pd.Timestamp(T0 + timedelta(days=10)))
    assert one["duration_days"].iloc[0] == pytest.approx(10.0) and one["event"].iloc[0] == 0


def test_grouped_folds_keep_courses_apart() -> None:
    cohort = synthetic_cohort(n_sections=20, joins_per_section=2)
    folds = grouped_folds(cohort, folds=5, seed=1)
    assert len(folds) == 5
    tested = pd.concat([t for _, t in folds])
    assert len(tested) == len(cohort) and tested.index.is_unique
    for train, test in folds:
        assert not (set(train["course_key"]) & set(test["course_key"]))


@pytest.fixture(scope="module")
def temporal_result():
    return run_backtest(synthetic_cohort(), SPRING_2027, split="temporal", which="days:14", n_boot=50)


def test_temporal_backtest_scores_four_predictors(temporal_result) -> None:
    res = temporal_result
    m = res.metrics.set_index("predictor")
    assert list(m.index) == list(PREDICTORS) and res.n_test == len(res.predictions) > 0
    assert (m["brier"].between(0, 1)).all() and (m["auc"].between(0, 1)).all()
    assert m.at["bucket", "gain"] == 0 and m.at["bucket", "gain_ci_low"] == 0 == m.at["bucket", "gain_ci_high"]
    for name in ("dept", "course", "site", "cox"):
        assert m.at[name, "gain_ci_low"] <= m.at[name, "gain"] <= m.at[name, "gain_ci_high"]
        assert m.at[name, "brier_baseline"] == m.at["bucket", "brier"]
    # position drives the generator, so ranking by bucket alone is already informative
    assert m.at["bucket", "auc"] > 0.6 and m.at["cox", "auc"] > 0.6
    assert set(res.by_phase["phase"]) == {"phase2"} and len(res.by_bucket) == 4
    assert {"p_bucket", "p_dept", "p_course", "p_site", "p_cox", "horizon_days", "site_fallback", "cox_fallback"} <= set(res.predictions.columns)
    assert (res.predictions["p_dept"].between(0, 1)).all()
    assert (res.predictions["horizon_days"] == 14.0).all()
    assert any("censored at the split" in n for n in res.notes)


def test_site_number_ignores_the_row_horizon(temporal_result) -> None:
    pred = temporal_result.predictions
    # the site reads the curve at the training cell's median lead time (about 80 days) instead of the 14-day horizon
    assert (pred["p_site"] >= pred["p_course"] - 0.006).mean() > 0.9 and (pred["p_site"] - pred["p_course"] > 0.05).mean() > 0.2
    assert (np.round(pred["p_site"], 2) == pred["p_site"]).all()
    assert not pred["site_fallback"].all()


def test_pooled_km_fallbacks() -> None:
    train = synthetic_cohort(n_sections=8, joins_per_section=6)
    model = PooledKM(min_n=30).fit(train)
    test = train.head(12).copy()
    test["course_key"] = "NEW 1"
    test["subject"] = "NEW"
    h = np.full(len(test), 5.0)
    p, level = model.predict(test, h)
    assert set(level) <= {"dept", "bucket", "all"} and (p >= 0).all() and (p <= 1).all()
    site, fallback = model.predict_site(test)
    assert fallback.all() and (site >= 0).all()
    assert (model.dept_of(test) == "OTHER").all()


def test_cross_term_and_grouped_runs() -> None:
    this_term = synthetic_cohort(seed=4, n_sections=30, joins_per_section=8)
    last_term = synthetic_cohort(seed=3, n_sections=30, joins_per_section=8)
    res = run_backtest(this_term, SPRING_2027, split="cross_term", which="deadline", train_cohort=last_term, n_boot=20)
    assert res.n_train == len(last_term) and res.n_test == len(this_term) and np.isfinite(res.metrics["brier"]).all()
    assert (res.predictions["horizon_days"] > 60).all()  # joins in Oct/Nov, deadline Feb 5
    grouped = run_backtest(this_term, SPRING_2027, split="grouped", which="instruction", folds=3, n_boot=20)
    assert grouped.n_test == len(this_term) and len(grouped.metrics) == 5 and any("3 folds" in n for n in grouped.notes)
    assert (grouped.predictions["course_level"] != "course").all()  # a course never scores itself


def test_too_small_returns_a_note_not_an_error() -> None:
    res = run_backtest(synthetic_cohort(n_sections=2, joins_per_section=2), SPRING_2027, split="temporal", which="days:14")
    assert res.metrics.empty and any("too few" in n or "skipped" in n for n in res.notes)
    with pytest.raises(ValueError):
        run_backtest(synthetic_cohort(n_sections=2, joins_per_section=2), SPRING_2027, split="cross_term")


def test_cli_writes_reports(tmp_path: Path) -> None:
    cohort = synthetic_cohort(n_sections=24, joins_per_section=6)
    path = tmp_path / "cohort_central.parquet"
    cohort.to_parquet(path, index=False)
    out = tmp_path / "bt"
    assert main(["--cohort", str(path), "--term-id", "2272", "--split", "temporal", "--which", "deadline", "--bootstrap", "20", "--out", str(out)]) == 0
    for name in ("metrics.csv", "by_phase.csv", "by_bucket.csv", "calibration.csv", "predictions.parquet", "report.md"):
        assert (out / name).exists(), name
    report = (out / "report.md").read_text()
    assert "## Predictors" in report and "| cox |" in report and "| dept |" in report and "## Calibration: site" in report and "## Calibration: dept" in report
    metrics = pd.read_csv(out / "metrics.csv")
    assert list(metrics["predictor"]) == list(PREDICTORS)
    res = run_backtest(cohort, SPRING_2027, split="temporal", which="days:14", n_boot=5)
    assert write_report(res, tmp_path / "again").exists()


def test_unobservable_horizons_are_excluded_not_scored() -> None:
    """A joiner whose section went dark before the horizon cannot be a known negative, so the
    row is excluded whatever its outcome; rows the data followed far enough are kept."""
    cohort = synthetic_cohort(n_sections=30, joins_per_section=8)
    cohort["follow_up_days"] = np.where(cohort["phase"] == "phase2", 5.0, 100.0)
    cohort.loc[cohort["phase"] == "phase2", "duration_days"] = cohort.loc[cohort["phase"] == "phase2", "duration_days"].clip(upper=5.0)
    ok, cov = observability(cohort, np.full(len(cohort), 14.0))
    assert set(cov["phase"]) == {"phase1", "phase2"}
    assert cov.set_index("phase").at["phase2", "share_observable"] == 0.0 and cov.set_index("phase").at["phase1", "share_observable"] == 1.0
    res = run_backtest(cohort, SPRING_2027, split="temporal", which="days:14", n_boot=10)
    assert res.metrics.empty and res.n_unobservable == int((cohort["phase"] == "phase2").sum())
    assert any("could not be followed" in n for n in res.notes) and len(res.coverage) == 1
    grouped = run_backtest(cohort, SPRING_2027, split="grouped", which="days:14", folds=3, n_boot=10)
    assert grouped.n_test == int((cohort["phase"] == "phase1").sum()) and grouped.n_unobservable == int((cohort["phase"] == "phase2").sum())
    assert set(grouped.predictions["phase"]) == {"phase1"}
    ok3, _ = observability(cohort.drop(columns=["follow_up_days"]), np.full(len(cohort), 14.0))
    assert ok3.all()  # no window information: every row is assumed observable
