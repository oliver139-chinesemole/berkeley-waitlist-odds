"""Figure showing what the flow reconstruction recovers on simulated waitlists.

Deterministic (SimConfig(seed=1)); the output is committed under
reports/figures_validation/ and embedded in the README and the methodology
page, always labelled as simulated data.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analysis.flows import interval_flows  # noqa: E402
from analysis.positions import time_to_clear  # noqa: E402
from analysis.synthetic import SimConfig, simulate  # noqa: E402

STYLE = {"figure.figsize": (9, 4), "axes.grid": True, "grid.alpha": 0.3, "axes.spines.top": False, "axes.spines.right": False, "font.size": 10}


def make_figure(out_dir: Path, seed: int = 1) -> Path:
    panel, true_flows, students = simulate(SimConfig(seed=seed))
    flows = interval_flows(panel)
    # left: cumulative admits, true vs reconstructed, for the busiest section
    busiest = true_flows.groupby("section_id")["admits"].sum().idxmax()
    tf = true_flows[true_flows["section_id"] == busiest].sort_values("t0")
    rf = flows[flows["section_id"] == busiest].sort_values("t0")
    t_zero = pd.Timestamp(tf["t0"].min())
    days = lambda s: (pd.to_datetime(s) - t_zero).dt.total_seconds() / 86400  # noqa: E731
    # right: true vs central time-to-clear for students who cleared
    cleared = students.dropna(subset=["clear_time"]).copy()
    rows = []
    for st in cleared.itertuples(index=False):
        sf = flows[flows["section_id"] == st.section_id]
        first_run = panel[(panel["section_id"] == st.section_id) & (panel["run_started_at"] >= pd.Timestamp(st.join_time))]["run_started_at"].min()
        if pd.isna(first_run):
            continue
        est, censored = time_to_clear(sf, first_run, int(st.position_at_join), "central")
        if est is None:
            continue
        truth = (pd.Timestamp(st.clear_time) - pd.Timestamp(first_run)).total_seconds() / 60
        rows.append((truth / 60, est / 60))
    pts = np.array(rows)
    with plt.rc_context(STYLE):
        fig, (ax1, ax2) = plt.subplots(1, 2)
        ax1.step(days(tf["t1"]), tf["admits"].cumsum(), where="post", label="true admits", linewidth=2)
        ax1.step(days(rf["t1"]), rf["admits"].cumsum(), where="post", label="reconstructed from counts", linewidth=2, linestyle="--")
        ax1.set_xlabel("days")
        ax1.set_ylabel("cumulative admits")
        ax1.set_title(f"One simulated section ({len(tf)} intervals of 30 min)")
        ax1.legend(frameon=False, fontsize=9)
        lim = float(np.nanpercentile(pts, 98)) if len(pts) else 1.0
        ax2.plot([0, lim], [0, lim], linestyle="--", linewidth=1, color="gray")
        ax2.scatter(pts[:, 0], pts[:, 1], s=8, alpha=0.5)
        ax2.set_xlim(0, lim)
        ax2.set_ylim(0, lim)
        ax2.set_xlabel("true hours to clear")
        ax2.set_ylabel("estimated hours (central scenario)")
        ax2.set_title(f"{len(pts)} simulated students who cleared")
        fig.suptitle("Simulated data: what the reconstruction recovers at 30-minute sampling", fontsize=11)
        fig.tight_layout()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "reconstruction_validation.png"
        fig.savefig(path, dpi=140)
        plt.close(fig)
    return path


if __name__ == "__main__":
    path = make_figure(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("reports/figures_validation"))
    print(path)
