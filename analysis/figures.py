"""Figures for the report and the README. See docs/DESIGN_A5.md section 5."""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from lifelines import KaplanMeierFitter  # noqa: E402

from analysis.survival import BUCKET_ORDER  # noqa: E402

logger = logging.getLogger(__name__)

STYLE = {"figure.figsize": (7.5, 4.5), "axes.grid": True, "grid.alpha": 0.3, "axes.spines.top": False, "axes.spines.right": False, "font.size": 10}


def _order(keys: list[str], by: str) -> list[str]:
    if by == "position_bucket":
        return [k for k in BUCKET_ORDER if k in keys] + [k for k in keys if k not in BUCKET_ORDER]
    return sorted(keys)


def plot_km(fitters: dict[str, KaplanMeierFitter], by: str, path: Path, *, title: str | None = None, max_days: float | None = None) -> Path:
    """One KM plot with confidence bands per stratum; y is the share still waiting."""
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots()
        for key in _order(list(fitters), by):
            fitters[key].plot_survival_function(ax=ax, ci_show=True, ci_alpha=0.12, label=fitters[key]._label)
        ax.set_xlabel("days since joining the waitlist")
        ax.set_ylabel("share still waiting")
        ax.set_ylim(0, 1)
        if max_days is not None:
            ax.set_xlim(0, max_days)
        ax.set_title(title or f"Time to clear by {by.replace('_', ' ')}")
        ax.legend(loc="upper right", fontsize=8, frameon=False)
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=150)
        plt.close(fig)
    logger.info("wrote %s", path)
    return path


def plot_calibration(calibration: pd.DataFrame, path: Path, *, brier: float | None = None) -> Path:
    """Decile calibration of predicted versus observed 14-day clearing."""
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(4.8, 4.8))
        ax.plot([0, 1], [0, 1], linestyle="--", linewidth=1, label="perfect")
        if len(calibration):
            ax.plot(calibration["predicted"], calibration["observed"], marker="o", label="deciles")
            for _, row in calibration.iterrows():
                ax.annotate(str(int(row["n"])), (row["predicted"], row["observed"]), textcoords="offset points", xytext=(4, 4), fontsize=7)
        ax.set_xlabel("predicted P(clear within 14 days)")
        ax.set_ylabel("observed share cleared within 14 days")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_title("Out-of-sample calibration" + (f" (Brier {brier:.3f})" if brier is not None and brier == brier else ""))
        ax.legend(loc="upper left", fontsize=8, frameon=False)
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=150)
        plt.close(fig)
    logger.info("wrote %s", path)
    return path
