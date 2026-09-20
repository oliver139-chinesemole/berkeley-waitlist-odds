"""A linear-time score residual for lifelines' Cox model.

lifelines 0.30.3 computes the score residuals it needs for robust
(cluster) standard errors in ``SemiParametricPHFitter._compute_score_within_strata``
with a Python loop over rows that sums over every earlier row: O(n^2 d).
On the 475,079-row Fall 2026 design that is hours; at 50,000 rows it is
minutes. The loop evaluates, for rows sorted by time with ``R_j`` the
weighted risk-set sum at row j and ``xbar_j`` the risk-set weighted mean of
the covariates,

    score_i = -phi_i * sum_{j <= i} (E_j w_j / R_j) (x_i - xbar_j) + E_i (x_i - xbar_i)

which is ``-phi_i (x_i A_i - B_i) + E_i (x_i - xbar_i)`` with ``A_i =
cumsum_j(E_j w_j / R_j)`` and ``B_i = cumsum_j((E_j w_j / R_j) xbar_j)``:
two cumulative sums, O(n d). ``install()`` swaps the method in at import of
``analysis.survival``; ``tests/test_coxfast.py`` holds it to the original
implementation to 1e-8 on a cohort where the original is affordable. The
Breslow tie handling of the original is kept as is (lifelines notes the
same "doesn't handle ties" there).
"""
from __future__ import annotations

import numpy as np
from lifelines.fitters import coxph_fitter as _coxph

_ORIGINAL = _coxph.SemiParametricPHFitter._compute_score_within_strata


def score_within_strata_fast(self, X, _T, E, weights, entries=None) -> np.ndarray:
    X = np.asarray(X.values if hasattr(X, "values") else X, dtype=float)
    E = np.asarray(E.values if hasattr(E, "values") else E).astype(int)
    weights = np.asarray(weights.values if hasattr(weights, "values") else weights, dtype=float)
    n, d = X.shape
    beta = self.params_.values * self._norm_std
    phi = np.exp(X @ beta)
    w_phi = weights * phi
    risk_phi_x = (X * w_phi[:, None])[::-1].cumsum(0)[::-1]  # sum over rows >= j
    risk_phi = w_phi[::-1].cumsum()[::-1]
    xbar = risk_phi_x / risk_phi[:, None]
    coef = E * weights / risk_phi  # E_j w_j / R_j
    a = np.cumsum(coef)  # A_i
    b = np.cumsum(coef[:, None] * xbar, axis=0)  # B_i
    score = -phi[:, None] * (X * a[:, None] - b) + E[:, None] * (X - xbar)
    return score * weights[:, None]


def install() -> None:
    """Replace lifelines' quadratic score residual with the linear one (idempotent)."""
    if _coxph.SemiParametricPHFitter._compute_score_within_strata is not score_within_strata_fast:
        _coxph.SemiParametricPHFitter._compute_score_within_strata = score_within_strata_fast


def uninstall() -> None:
    _coxph.SemiParametricPHFitter._compute_score_within_strata = _ORIGINAL
