"""Reconstruct waitlist flows from consecutive observed counts.

See docs/DESIGN_A4.md section 2 and docs/ASSUMPTIONS.md. Net changes in
enrolled and waitlisted counts between two observations are decomposed into
admits, waitlist joins, waitlist drops, direct enrolments and enrolled drops
under stated rules; each interval carries an ``ambiguous`` flag when more
than one story fits and a ``censored`` flag when it overlaps a logged gap.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from analysis.panel import Outage, load_panel, parse_data_log
from scraper.schema import TOMBSTONE_STATUS

logger = logging.getLogger(__name__)

FLOW_COLUMNS = ("admits", "wl_joins", "wl_drops", "enr_joins", "enr_drops")
OUTPUT_COLUMNS = (
    "section_id",
    "t0",
    "t1",
    "interval_min",
    "d_enrolled",
    "d_waitlist",
    "d_capacity",
    "d_wl_capacity",
    "enrolled0",
    "capacity0",
    "waitlist0",
    "reserved0",
    "open_reserved0",
    "full0",
    *FLOW_COLUMNS,
    "expansion",
    "ambiguous",
    "censored",
    "rule",
)

_COUNTS = ("enrolled_count", "enroll_capacity", "waitlist_count", "waitlist_capacity")


def _observed_series(panel: pd.DataFrame) -> pd.DataFrame:
    """Observed rows with complete counts, cut at the first tombstone per section."""
    frame = panel.copy()
    frame["observed"] = frame["observed"].fillna(False).astype(bool)
    frame = frame.sort_values(["section_id", "run_started_at"])
    gone = frame["section_status"].fillna("") == TOMBSTONE_STATUS
    # rows at or after a section's first tombstone are dropped
    first_gone = frame[gone].groupby("section_id")["run_started_at"].min()
    if len(first_gone):
        cutoff = frame["section_id"].map(first_gone)
        frame = frame[cutoff.isna() | (frame["run_started_at"] < cutoff)]
    frame = frame[frame["observed"]]
    frame = frame.dropna(subset=list(_COUNTS))
    return frame


def _is_censored(t0: datetime, t1: datetime, term_id: str | None, outages: Iterable[Outage]) -> bool:
    return any(o.overlaps(t0, t1, term_id) for o in outages)


def interval_flows(
    panel: pd.DataFrame,
    *,
    outages: Iterable[Outage] = (),
    max_interval_min: float | None = None,
) -> pd.DataFrame:
    """One row per section per pair of consecutive observed runs (docs/DESIGN_A4.md section 2)."""
    outages = list(outages)
    series = _observed_series(panel)
    if series.empty:
        return pd.DataFrame(columns=list(OUTPUT_COLUMNS))
    g = series.groupby("section_id", sort=False)
    nxt = g[["run_started_at", *_COUNTS]].shift(-1)
    has_next = nxt["run_started_at"].notna()
    cur = series[has_next]
    nxt = nxt[has_next]

    t0 = pd.to_datetime(cur["run_started_at"])
    t1 = pd.to_datetime(nxt["run_started_at"])
    e0 = cur["enrolled_count"].astype("int64").to_numpy()
    e1 = nxt["enrolled_count"].astype("int64").to_numpy()
    w0 = cur["waitlist_count"].astype("int64").to_numpy()
    w1 = nxt["waitlist_count"].astype("int64").to_numpy()
    c0 = cur["enroll_capacity"].astype("int64").to_numpy()
    c1 = nxt["enroll_capacity"].astype("int64").to_numpy()
    wc0 = cur["waitlist_capacity"].astype("int64").to_numpy()
    wc1 = nxt["waitlist_capacity"].astype("int64").to_numpy()
    reserved0 = cur["reserved_count"] if "reserved_count" in cur else pd.Series(pd.NA, index=cur.index)
    open_res0 = cur["open_reserved"] if "open_reserved" in cur else pd.Series(pd.NA, index=cur.index)
    open_res_known = open_res0.notna().to_numpy()
    open_res_val = open_res0.fillna(0).astype("int64").to_numpy()

    dE = e1 - e0
    dW = w1 - w0
    dC = c1 - c0
    dWC = wc1 - wc0
    full0 = np.where(open_res_known, e0 >= c0 - open_res_val, e0 >= c0)

    n = len(cur)
    admits = np.zeros(n, dtype="int64")
    wl_joins = np.zeros(n, dtype="int64")
    wl_drops = np.zeros(n, dtype="int64")
    enr_joins = np.zeros(n, dtype="int64")
    enr_drops = np.zeros(n, dtype="int64")
    ambiguous = np.zeros(n, dtype=bool)
    rule = np.full(n, "none", dtype=object)

    # 1. admit: enrolment up, waitlist down
    m = (dE > 0) & (dW < 0)
    admits[m] = np.minimum(dE[m], -dW[m])
    enr_joins[m] = dE[m] - admits[m]
    wl_drops[m] = -dW[m] - admits[m]
    ambiguous[m] = dE[m] != -dW[m]
    rule[m] = "admit"
    # 2. direct enrolment, waitlist flat
    m = (dE > 0) & (dW == 0)
    enr_joins[m] = dE[m]
    ambiguous[m] = w0[m] > 0
    rule[m] = "enr_join"
    # 3. joins and direct enrolments together
    m = (dE > 0) & (dW > 0)
    enr_joins[m] = dE[m]
    wl_joins[m] = dW[m]
    ambiguous[m] = (w0[m] > 0) | full0[m]
    rule[m] = "join_and_enr_join"
    # 4. joins only
    m = (dE == 0) & (dW > 0)
    wl_joins[m] = dW[m]
    rule[m] = "join"
    # 5. waitlist drops only
    m = (dE == 0) & (dW < 0)
    wl_drops[m] = -dW[m]
    rule[m] = "wl_drop"
    rule[m & (dC < 0)] = "wl_drop_capcut"
    # 6. enrolled drops only
    m = (dE < 0) & (dW == 0)
    enr_drops[m] = -dE[m]
    ambiguous[m] = (w0[m] > 0) & full0[m]
    rule[m] = "enr_drop"
    # 7. enrolled drops and waitlist drops
    m = (dE < 0) & (dW < 0)
    enr_drops[m] = -dE[m]
    wl_drops[m] = -dW[m]
    ambiguous[m] = True
    rule[m] = "enr_drop_wl_drop"
    # 8. enrolled drops and joins
    m = (dE < 0) & (dW > 0)
    enr_drops[m] = -dE[m]
    wl_joins[m] = dW[m]
    rule[m] = "enr_drop_join"

    interval_min = (t1.to_numpy() - t0.to_numpy()).astype("timedelta64[s]").astype("int64") / 60.0
    term_ids = cur["term_id"] if "term_id" in cur else pd.Series(None, index=cur.index)
    censored = np.zeros(n, dtype=bool)
    if outages:
        t0_list = list(t0)
        t1_list = list(t1)
        terms = list(term_ids.astype(object)) if "term_id" in cur else [None] * n
        censored = np.array([_is_censored(a, b, None if pd.isna(t) else str(t), outages) for a, b, t in zip(t0_list, t1_list, terms)], dtype=bool) if n else censored
    if max_interval_min is not None:
        censored = censored | (interval_min > float(max_interval_min))

    out = pd.DataFrame(
        {
            "section_id": cur["section_id"].astype("string").to_numpy(),
            "t0": t0.to_numpy(),
            "t1": t1.to_numpy(),
            "interval_min": interval_min,
            "d_enrolled": dE,
            "d_waitlist": dW,
            "d_capacity": dC,
            "d_wl_capacity": dWC,
            "enrolled0": e0,
            "capacity0": c0,
            "waitlist0": w0,
            "reserved0": reserved0.to_numpy(),
            "open_reserved0": open_res0.to_numpy(),
            "full0": full0,
            "admits": admits,
            "wl_joins": wl_joins,
            "wl_drops": wl_drops,
            "enr_joins": enr_joins,
            "enr_drops": enr_drops,
            "expansion": dC > 0,
            "ambiguous": ambiguous,
            "censored": censored,
            "rule": rule.astype(str),
        }
    )
    for col in ("d_enrolled", "d_waitlist", "d_capacity", "d_wl_capacity", "enrolled0", "capacity0", "waitlist0", *FLOW_COLUMNS):
        out[col] = out[col].astype("Int64")
    out["reserved0"] = pd.array(out["reserved0"], dtype="Int64")
    out["open_reserved0"] = pd.array(out["open_reserved0"], dtype="Int64")
    for col in ("full0", "expansion", "ambiguous", "censored"):
        out[col] = out[col].astype("boolean")
    out["rule"] = out["rule"].astype("string")
    out["section_id"] = out["section_id"].astype("string")
    out["t0"] = pd.to_datetime(out["t0"], utc=True)
    out["t1"] = pd.to_datetime(out["t1"], utc=True)
    return out.sort_values(["section_id", "t0"]).reset_index(drop=True)


def summary(flows: pd.DataFrame) -> dict[str, float | int]:
    n = len(flows)
    totals = {c: int(flows[c].sum()) if n else 0 for c in FLOW_COLUMNS}
    return {
        "sections": int(flows["section_id"].nunique()) if n else 0,
        "intervals": n,
        "share_ambiguous": round(float(flows["ambiguous"].mean()), 4) if n else 0.0,
        "share_censored": round(float(flows["censored"].mean()), 4) if n else 0.0,
        "median_interval_min": round(float(flows["interval_min"].median()), 1) if n else 0.0,
        **totals,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Reconstruct per-interval waitlist flows from the data branch.")
    p.add_argument("--data-root", type=Path, default=Path("./data-branch"))
    p.add_argument("--term-id", required=True)
    p.add_argument("--out", type=Path, default=None, help="parquet path for the flows table")
    p.add_argument("--data-log", type=Path, default=Path("docs/DATA_LOG.md"))
    p.add_argument("--max-interval-min", type=float, default=None, help="censor intervals longer than this")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    panel = load_panel(args.data_root, args.term_id)
    outages = parse_data_log(args.data_log) if args.data_log.exists() else []
    flows = interval_flows(panel, outages=outages, max_interval_min=args.max_interval_min)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        flows.to_parquet(args.out, index=False)
        logger.info("wrote %s (%d rows)", args.out, len(flows))
    print(summary(flows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
