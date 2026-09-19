"""Data-quality profile of the rebuilt panel, run before any modelling.

docs/FINISH_PLAN_WAITLIST.md step A5 asks for null rates, observation gaps,
impossible transitions and sections that vanish. Everything here is a plain
pandas computation on the panel from ``analysis.panel.load_panel``; the
result is a dict of small tables and numbers that ``analysis.run`` writes
into the report.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from scraper.schema import TOMBSTONE_STATUS

COUNT_COLUMNS = ("enrolled_count", "enroll_capacity", "waitlist_count", "waitlist_capacity", "reserved_count", "open_reserved")


@dataclass
class PanelProfile:
    runs: int
    sections: int
    rows: int
    observed_share: float
    first_run: pd.Timestamp | None
    last_run: pd.Timestamp | None
    null_rates: pd.Series
    run_gaps_min: pd.Series  # describe() of gaps between consecutive runs
    sections_by_observations: pd.Series  # how many sections were observed k times (binned)
    impossible: pd.DataFrame  # counts of impossible states per kind
    vanished: int  # sections with a tombstone
    reappeared: int  # sections observed again after a tombstone
    big_jumps: pd.DataFrame  # largest single-interval count changes (possible data glitches)
    notes: list[str] = field(default_factory=list)

    def as_markdown(self) -> str:
        lines = [
            "## Panel profile",
            "",
            f"{self.runs} runs from {self.first_run} to {self.last_run}; {self.sections} sections; {self.rows} rows; observed share {self.observed_share:.3f}.",
            "",
            "Null rate per count column (observed rows):",
            "",
            *[f"- {k}: {v:.3f}" for k, v in self.null_rates.items()],
            "",
            "Gaps between consecutive runs (minutes):",
            "",
            *[f"- {k}: {v:.1f}" for k, v in self.run_gaps_min.items() if k != "count"],
            "",
            "Sections by number of observations:",
            "",
            *[f"- {k}: {int(v)}" for k, v in self.sections_by_observations.items()],
            "",
            "Impossible states (observed rows):",
            "",
            *[f"- {row['kind']}: {int(row['rows'])} rows in {int(row['sections'])} sections" for _, row in self.impossible.iterrows()],
            "",
            f"Vanished sections (tombstoned): {self.vanished}; reappeared after a tombstone: {self.reappeared}.",
            "",
        ]
        if len(self.big_jumps):
            lines += ["Largest single-interval changes (candidates for a data glitch or an expansion event):", "", "| section_id | run_started_at | column | from | to |", "| --- | --- | --- | --- | --- |"]
            for _, r in self.big_jumps.iterrows():
                lines.append(f"| {r['section_id']} | {r['run_started_at']} | {r['column']} | {r['from']} | {r['to']} |")
            lines.append("")
        for note in self.notes:
            lines.append(f"- Note: {note}")
        return "\n".join(lines)


def profile_panel(panel: pd.DataFrame, *, top_jumps: int = 15) -> PanelProfile:
    frame = panel.copy()
    frame["observed"] = frame["observed"].fillna(False).astype(bool)
    runs = frame["run_started_at"].drop_duplicates().sort_values()
    obs = frame[frame["observed"]]
    notes: list[str] = []

    null_rates = pd.Series({c: float(obs[c].isna().mean()) if c in obs and len(obs) else float("nan") for c in COUNT_COLUMNS})

    gaps = runs.diff().dropna().dt.total_seconds().div(60.0) if len(runs) > 1 else pd.Series(dtype=float)
    run_gaps = gaps.describe() if len(gaps) else pd.Series({"count": 0.0})

    per_section = obs.groupby("section_id").size()
    bins = pd.cut(per_section, bins=[0, 1, 2, 5, 10, 48, 96, np.inf], labels=["1", "2", "3-5", "6-10", "11-48", "49-96", "97+"], right=True)
    by_obs = bins.value_counts().sort_index() if len(per_section) else pd.Series(dtype=int)

    checks = {
        "enrolled above capacity": obs["enrolled_count"] > obs["enroll_capacity"],
        "waitlist above waitlist capacity": obs["waitlist_count"] > obs["waitlist_capacity"],
        "negative count": (obs[list(COUNT_COLUMNS[:4])] < 0).any(axis=1),
        "waitlist while seats open (no reserved info)": (obs["waitlist_count"] > 0) & (obs["enrolled_count"] < obs["enroll_capacity"]) & obs["open_reserved"].isna(),
        "waitlist while unreserved seats open": (obs["waitlist_count"] > 0) & (obs["enrolled_count"] < obs["enroll_capacity"] - obs["open_reserved"].fillna(0)),
    }
    impossible = pd.DataFrame(
        [{"kind": k, "rows": int(m.fillna(False).sum()), "sections": int(obs.loc[m.fillna(False), "section_id"].nunique())} for k, m in checks.items()]
    )
    if len(obs) and float(checks["enrolled above capacity"].fillna(False).mean()) > 0.02:
        notes.append("more than 2% of observed rows show enrolment above capacity; reserved seats or manual overrides are common in this term")

    gone = frame["section_status"].fillna("") == TOMBSTONE_STATUS
    vanished = int(frame.loc[gone, "section_id"].nunique())
    reappeared = 0
    if vanished:
        first_gone = frame[gone].groupby("section_id")["run_started_at"].min()
        later = obs.merge(first_gone.rename("gone_at"), left_on="section_id", right_index=True)
        reappeared = int(later[(later["run_started_at"] > later["gone_at"]) & (later["section_status"].fillna("") != TOMBSTONE_STATUS)]["section_id"].nunique())

    jumps: list[dict] = []
    if len(obs):
        srt = obs.sort_values(["section_id", "run_started_at"])
        for col in ("enrolled_count", "waitlist_count", "enroll_capacity"):
            prev = srt.groupby("section_id")[col].shift(1)
            diff = (srt[col].astype("float") - prev.astype("float")).abs()
            top = diff.nlargest(top_jumps)
            for idx, d in top.items():
                if pd.isna(d) or d == 0:
                    continue
                jumps.append({"section_id": srt.at[idx, "section_id"], "run_started_at": srt.at[idx, "run_started_at"], "column": col, "from": prev.at[idx], "to": srt.at[idx, col], "abs_change": float(d)})
    big = pd.DataFrame(jumps, columns=["section_id", "run_started_at", "column", "from", "to", "abs_change"])
    if len(big):
        big = big.sort_values("abs_change", ascending=False).head(top_jumps).drop(columns=["abs_change"]).reset_index(drop=True)

    return PanelProfile(
        runs=int(len(runs)),
        sections=int(frame["section_id"].nunique()),
        rows=int(len(frame)),
        observed_share=float(frame["observed"].mean()) if len(frame) else float("nan"),
        first_run=runs.min() if len(runs) else None,
        last_run=runs.max() if len(runs) else None,
        null_rates=null_rates,
        run_gaps_min=run_gaps,
        sections_by_observations=by_obs,
        impossible=impossible,
        vanished=vanished,
        reappeared=reappeared,
        big_jumps=big,
        notes=notes,
    )
