"""Tests for analysis.survival on a generated cohort with known structure."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from analysis.cohort import COHORT_COLUMNS, position_bucket
from analysis.survival import (
    check_ph,
    design_matrix,
    fit_cox,
    fit_cox_with_ph_check,
    headline,
    km_by,
    km_table,
    logrank_table,
    sensitivity,
)

T0 = datetime(2026, 10, 27, tzinfo=timezone.utc)


def synthetic_cohort(seed: int = 3, n_sections: int = 60, joins_per_section: int = 12) -> pd.DataFrame:
    """Exponential clearing times whose rate falls with position and differs by level;
    ~25% right-censoring; phase1 joins in the first half of the window, phase2 later."""
    rng = np.random.default_rng(seed)
    rows = []
    subjects = ["COMPSCI", "MATH", "STAT", "ART"]
    for s in range(n_sections):
        subject = subjects[s % len(subjects)]
        level = "lower" if s % 3 else "upper"
        capacity = int(rng.integers(30, 300))
        for j in range(joins_per_section):
            phase = "phase1" if j < joins_per_section // 2 else "phase2"
            join_time = T0 + timedelta(days=(0 if phase == "phase1" else 30) + j)
            for position in (1, 3, 5, 10, 20, 50):
                waitlist0 = position + int(rng.integers(0, 10))
                rate = 0.6 / (position ** 0.7) * (1.4 if level == "lower" else 1.0)
                duration = rng.exponential(1.0 / rate)
                censor = rng.exponential(6.0)
                event = int(duration <= censor)
                d = min(duration, censor)
                rows.append(
                    {
                        "section_id": str(s),
                        "join_time": join_time,
                        "position": position,
                        "position_bucket": position_bucket(position),
                        "log_position": float(np.log(position)),
                        "waitlist0": waitlist0,
                        "capacity0": capacity,
                        "wl_ratio": waitlist0 / capacity,
                        "duration_min": d * 1440,
                        "duration_days": d,
                        "event": event,
                        "course_key": f"{subject} {s}",
                        "subject": subject,
                        "catalog_number": str(s),
                        "component": "LEC",
                        "level": level,
                        "dept_group": subject if subject != "ART" else "OTHER",
                        "phase": phase,
                        "days_to_instruction": 84.0 - (join_time - T0).days,
                        "reserved": bool(s % 4 == 0),
                        "scenario": "central",
                    }
                )
    frame = pd.DataFrame(rows, columns=list(COHORT_COLUMNS))
    for col in ("section_id", "position_bucket", "course_key", "subject", "catalog_number", "component", "level", "dept_group", "phase", "scenario"):
        frame[col] = frame[col].astype("string")
    return frame


@pytest.fixture(scope="module")
def cohort() -> pd.DataFrame:
    return synthetic_cohort()


def test_km_by_and_table(cohort: pd.DataFrame) -> None:
    fitters = km_by(cohort, "position_bucket")
    assert set(fitters) == {"1-5", "6-15", "16-40", "41+"}
    table = km_table(fitters, at_days=(1, 7, 14)).set_index("stratum")
    # survival curves are monotone and clearing is faster at the front of the queue
    for key, kmf in fitters.items():
        s = kmf.survival_function_.iloc[:, 0].to_numpy()
        assert np.all(np.diff(s) <= 1e-12)
    assert table.at["1-5", "p_clear_by_7d"] > table.at["41+", "p_clear_by_7d"]
    assert table.at["1-5", "median_days"] < table.at["41+", "median_days"]
    assert (table["n"] > 0).all()


def test_logrank_table(cohort: pd.DataFrame) -> None:
    lr = logrank_table(cohort, "position_bucket")
    assert len(lr) == 6 and (lr["comparisons"] == 6).all()
    front_vs_back = lr[(lr["a"] == "1-5") & (lr["b"] == "41+")]
    assert float(front_vs_back["p"].iloc[0]) < 0.01


def test_design_matrix_and_cox(cohort: pd.DataFrame) -> None:
    design = design_matrix(cohort)
    assert {"duration_days", "event", "section_id", "log_position", "wl_ratio", "days_to_instruction", "reserved", "level=upper", "phase=phase2"} <= set(design.columns)
    assert not any(c in design.columns for c in ("level=lower", "phase=phase1", "dept_group=OTHER"))
    result = fit_cox(cohort)
    coef = result.summary.at["log_position", "coef"]
    assert coef < 0  # higher position, lower clearing hazard
    assert result.summary.at["level=upper", "coef"] < 0  # upper division clears slower in the generator


def test_ph_check_and_stratified_refit(cohort: pd.DataFrame) -> None:
    first, ph, refit = fit_cox_with_ph_check(cohort, alpha=0.05)
    assert {"covariate", "p", "violates"} <= set(ph.columns) and len(ph) >= 5
    if refit is not None:
        assert refit.strata and "log_position" in refit.summary.index
    stratified = fit_cox(cohort, strata=["level"])
    assert stratified.strata == ["level_stratum"] and "level=upper" not in stratified.summary.index


def test_sensitivity_and_headline(cohort: pd.DataFrame) -> None:
    faster = cohort.copy()
    faster["duration_days"] = faster["duration_days"] * 0.5
    table = sensitivity({"optimistic": faster, "central": cohort, "pessimistic": cohort})
    assert list(table["scenario"]) == ["optimistic", "central", "pessimistic"]
    assert table.set_index("scenario").at["optimistic", "median_days"] < table.set_index("scenario").at["central", "median_days"]
    result = fit_cox(cohort)
    h = headline(cohort, result)
    assert "lower_division_phase1_by_bucket" in h and len(h["lower_division_phase1_by_bucket"]) == 4
    assert "share_cleared_by_instruction_by_bucket" in h and 0 <= h["share_cleared_by_instruction_by_bucket"].max() <= 1
    assert 0 < h["position_hazard_ratio_per_log_unit"] < 1
    assert "largest_department_effect" in h and 0 <= h["largest_department_effect"]["p"] <= 1


def test_check_ph_runs_on_small_design(cohort: pd.DataFrame) -> None:
    result = fit_cox(cohort.head(600))
    ph = check_ph(result)
    assert set(ph["violates"].unique()) <= {True, False}


def test_cox_design_rounds_durations_and_ph_test_subsamples(cohort: pd.DataFrame) -> None:
    from analysis.survival import COX_TIME_RESOLUTION_DAYS, design_matrix

    design = design_matrix(cohort)
    steps = design["duration_days"] / COX_TIME_RESOLUTION_DAYS
    assert np.allclose(steps, np.round(steps)) and (design["duration_days"] > 0).all()
    assert (design["duration_days"] >= cohort.loc[design.index, "duration_days"] - 1e-9).all()  # rounded up, never earlier
    assert design_matrix(cohort, time_resolution_days=0)["duration_days"].equals(cohort.loc[design.index, "duration_days"].astype(float))
    result = fit_cox(cohort)
    ph = check_ph(result, max_rows=300)
    assert (ph["rows_tested"] == 300).all() and {"covariate", "p", "violates"} <= set(ph.columns)
    full = check_ph(result, max_rows=0)
    assert (full["rows_tested"] == len(result.design)).all()
