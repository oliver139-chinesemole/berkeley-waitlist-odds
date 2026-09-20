"""The linear-time score residual equals lifelines' quadratic one, and the robust
standard errors that depend on it are unchanged."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from lifelines import CoxPHFitter

from analysis import coxfast
from analysis.survival import design_matrix
from tests.test_survival import synthetic_cohort


def _fit(design: pd.DataFrame) -> CoxPHFitter:
    cph = CoxPHFitter(penalizer=0.01)
    cph.fit(design, duration_col="duration_days", event_col="event", cluster_col="section_id", robust=True, batch_mode=True)
    return cph


def test_fast_score_matches_lifelines_and_robust_se_unchanged() -> None:
    design = design_matrix(synthetic_cohort(n_sections=20, joins_per_section=4), time_resolution_days=0)  # distinct times, as lifelines' loop assumes
    coxfast.uninstall()
    try:
        slow = _fit(design)
        se_slow = slow.summary["se(coef)"].copy()
        model = slow._model if hasattr(slow, "_model") else slow
        sorted_design = design.sort_values("duration_days")
        X = sorted_design.drop(columns=["duration_days", "event", "section_id"])
        X_norm = (X - model._norm_mean) / model._norm_std
        T = sorted_design["duration_days"]
        E = sorted_design["event"]
        w = pd.Series(np.ones(len(X)), index=X.index)
        original = coxfast._ORIGINAL(model, X_norm, T, E, w, None)
        fast = coxfast.score_within_strata_fast(model, X_norm, T, E, w, None)
        assert original.shape == fast.shape and np.allclose(original, fast, atol=1e-8, rtol=1e-8)
    finally:
        coxfast.install()
    fast_fit = _fit(design)
    assert np.allclose(fast_fit.summary["se(coef)"].to_numpy(), se_slow.to_numpy(), rtol=1e-8, atol=1e-10)
    assert np.allclose(fast_fit.summary["coef"].to_numpy(), slow.summary["coef"].to_numpy())


def test_fast_score_is_linear_time() -> None:
    coxfast.install()
    big = design_matrix(synthetic_cohort(n_sections=200, joins_per_section=20))  # 24,000 rows
    t = time.time()
    _fit(big)
    assert time.time() - t < 60  # the quadratic loop takes minutes at this size
