"""Print the backtest reports of a term as the sentences CLAIMS.md and the docs quote.

    python -m analysis.backtest_summary --reports reports/backtest_2268

Reads ``metrics.csv`` and ``coverage.csv`` from each subdirectory and prints,
per run, the scored and unobservable counts, coverage by phase, and for every
predictor the Brier score, the gain over the bucket baseline with its 95%
section-bootstrap interval, the AUC and the fallback share, with the numbers
exactly as the CSVs hold them (rounded to four decimals). Nothing is computed
here that the backtest did not already compute.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def summarise(run_dir: Path) -> str:
    metrics_path = run_dir / "metrics.csv"
    if not metrics_path.exists():
        return f"{run_dir.name}: no metrics.csv"
    metrics = pd.read_csv(metrics_path)
    lines = [f"{run_dir.name}:"]
    cov_path = run_dir / "coverage.csv"
    if cov_path.exists() and cov_path.stat().st_size > 0:
        cov = pd.read_csv(cov_path)
        if len(cov):
            parts = [f"{r.phase} {int(r.n)} rows {float(r.share_observable):.2f} observable" for r in cov.itertuples(index=False)]
            lines.append("  coverage: " + "; ".join(parts))
    if metrics.empty:
        report = run_dir / "report.md"
        note = ""
        if report.exists():
            for line in report.read_text().splitlines():
                if "too few scored rows" in line or "could not be followed" in line:
                    note = line.strip("- ").strip()
                    break
        lines.append("  no scored rows" + (f": {note}" if note else ""))
        return "\n".join(lines)
    n_test = int(metrics["n_test"].iloc[0])
    lines.append(f"  scored rows {n_test}")
    for r in metrics.itertuples(index=False):
        gain = "" if r.predictor == "bucket" else f", gain over bucket {r.gain:+.4f} [{r.gain_ci_low:+.4f}, {r.gain_ci_high:+.4f}]"
        fb = f", fallback share {r.share_fallback:.3f}" if r.share_fallback else ""
        auc = f", AUC {r.auc:.3f}" if pd.notna(r.auc) else ", AUC undefined"
        lines.append(f"  {r.predictor:<7} Brier {r.brier:.4f}{gain}{auc}, known-outcome rows {int(r.brier_rows)} (unknown share {r.share_unknown:.3f}){fb}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backtest reports as quotable sentences.")
    p.add_argument("--reports", type=Path, default=Path("reports/backtest_2268"))
    args = p.parse_args(argv)
    runs = sorted(d for d in args.reports.iterdir() if d.is_dir())
    if not runs:
        print(f"no runs under {args.reports}")
        return 1
    print("\n".join(summarise(d) for d in runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
