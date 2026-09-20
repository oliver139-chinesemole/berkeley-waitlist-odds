"""``site/data/backtest.json`` from the backtest reports (docs/DESIGN_A5.md section 4).

Reads every run directory under ``reports/backtest_<term>/`` written by
``python -m analysis.backtest`` (``metrics.csv``, ``calibration.csv``,
``coverage.csv``, ``by_bucket.csv``, ``by_phase.csv``, ``report.md``) and
writes one JSON file the Accuracy page reads. Nothing is computed here: the
numbers are the reports' numbers, and the page prints them.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

RUN_RE = re.compile(r"^(?P<split>temporal|grouped|cross_term)_(?P<which>days\d+|deadline|instruction)$")
COUNTS_RE = re.compile(r"(?P<train>\d+) training rows, (?P<test>\d+) scored test rows, (?P<past>\d+) test rows past their horizon at joining and (?P<unobservable>\d+) whose follow-up ended before their horizon")


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if hasattr(v, "item"):
        v = v.item()
    return v


def _records(path: Path, round_to: int = 4) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        frame = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return []
    out = []
    for rec in frame.to_dict(orient="records"):
        row = {}
        for k, v in rec.items():
            v = _clean(v)
            row[k] = round(v, round_to) if isinstance(v, float) else v
        out.append(row)
    return out


def which_label(which: str) -> str:
    m = re.match(r"days(\d+)", which)
    if m:
        return f"within {m.group(1)} days"
    return {"deadline": "by the last automatic waitlist run", "instruction": "by the first day of instruction"}.get(which, which)


def read_run(run_dir: Path) -> dict | None:
    m = RUN_RE.match(run_dir.name)
    if not m or not (run_dir / "metrics.csv").exists():
        return None
    calibration: dict[str, list[dict]] = {}
    for rec in _records(run_dir / "calibration.csv"):
        calibration.setdefault(str(rec.pop("predictor")), []).append(rec)
    counts = None
    report = run_dir / "report.md"
    if report.exists():
        found = COUNTS_RE.search(report.read_text(encoding="utf-8"))
        if found:
            counts = {k: int(v) for k, v in found.groupdict().items()}
    return {
        "name": run_dir.name,
        "split": m.group("split"),
        "which": m.group("which"),
        "horizon_label": which_label(m.group("which")),
        "counts": counts,
        "metrics": _records(run_dir / "metrics.csv"),
        "calibration": calibration,
        "coverage": _records(run_dir / "coverage.csv"),
        "by_bucket": _records(run_dir / "by_bucket.csv"),
        "by_phase": _records(run_dir / "by_phase.csv"),
    }


def export_backtest(reports_dir: Path | str, out_path: Path | str, *, term_id: str, term_name: str | None = None, meta: dict | None = None) -> Path:
    reports_dir = Path(reports_dir)
    runs = []
    for run_dir in sorted(p for p in reports_dir.iterdir() if p.is_dir()) if reports_dir.exists() else []:
        run = read_run(run_dir)
        if run and run["metrics"]:
            runs.append(run)
        elif run:
            logger.info("skipping %s: no scored rows", run_dir.name)
    info = {
        "term_id": term_id,
        "term_name": term_name,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "predictors": {
            "bucket": "position bucket alone (the baseline)",
            "course": "the course-and-bucket curve the pages use, read at each joiner's own horizon",
            "site": "the literal number the lookup showed when it read the curve at a fixed lead time (site v1)",
            "cox": "the Cox proportional-hazards model",
        },
        "runs": runs,
    }
    if meta:
        info.update(meta)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(info, indent=0, sort_keys=True, allow_nan=False), encoding="utf-8")
    logger.info("wrote %s (%d runs)", out_path, len(runs))
    return out_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Write site/data/backtest.json from reports/backtest_<term>/.")
    p.add_argument("--reports", type=Path, required=True, help="e.g. reports/backtest_2268")
    p.add_argument("--term-id", required=True)
    p.add_argument("--term-name", default=None)
    p.add_argument("--out", type=Path, default=Path("site/data/backtest.json"))
    p.add_argument("--data-source", default=None)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    meta = {"data_source": args.data_source} if args.data_source else None
    out = export_backtest(args.reports, args.out, term_id=args.term_id, term_name=args.term_name, meta=meta)
    info = json.loads(out.read_text(encoding="utf-8"))
    print(json.dumps({"out": str(out), "runs": [r["name"] for r in info["runs"]]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
