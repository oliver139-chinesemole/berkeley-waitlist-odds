"""Gap report over snapshot run times. See docs/DESIGN_A2.md section 7.

Reads ``run_started_at``, ``n_observed`` and ``missing_ids`` from the
metadata of every snapshot file (both kinds) of a term within the window and
reports the gaps between consecutive runs in minutes plus the per-run
missing share ``n_missing / (n_observed + n_missing)`` (median and maximum
over the window), so a partial outage that still writes files is visible.
Used by ``monitor.yml`` and by ``CLAIMS.md``.

CLI::

    python -m scraper.gaps --data-root data-branch --term-id 2268 --hours 24 \
        --fail-if-gap-min 90 --fail-if-runs-lt 40 --fail-if-missing-share-gt 0.5

Prints the report as JSON and exits 1 when a threshold is breached
(``--fail-if-missing-share-gt`` compares against the median missing share).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from scraper.storage import ensure_utc, list_snapshots, read_meta

logger = logging.getLogger(__name__)

GAP_TARGET_MIN = 45.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _gap_stats(times: Sequence[datetime]) -> dict[str, Any]:
    """Gap statistics (minutes) between consecutive sorted run times."""
    gaps = [(b - a).total_seconds() / 60.0 for a, b in zip(times[:-1], times[1:])]
    if not gaps:
        return {"n_runs": len(times), "largest_gap_min": None, "p95_gap_min": None, "share_gaps_le_45min": None}
    arr = np.asarray(gaps, dtype=float)
    return {
        "n_runs": len(times),
        "largest_gap_min": round(float(arr.max()), 3),
        "p95_gap_min": round(float(np.percentile(arr, 95)), 3),
        "share_gaps_le_45min": round(float((arr <= GAP_TARGET_MIN).mean()), 4),
    }


def gap_report(
    data_root: Path,
    term_id: str,
    since_hours: float = 24,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Summarize run cadence for ``term_id`` over the last ``since_hours``.

    Keys: ``n_runs``, ``largest_gap_min``, ``p95_gap_min``,
    ``share_gaps_le_45min`` (``None`` when fewer than 2 runs), ``first``/``last``
    (ISO-8601 or ``None``), ``minutes_since_last``, ``by_scope`` (the same gap
    statistics per scope, gaps computed between runs of that scope),
    ``runs_by_kind`` and ``runs_by_scope`` counts, ``median_missing_share``
    and ``max_missing_share`` (per-run ``n_missing / (n_observed + n_missing)``
    from the file metadata; runs with nothing in scope are skipped; ``None``
    without runs), plus ``term_id``, ``since_hours`` and ``now``. ``now``
    defaults to the current UTC time.
    """
    now_utc = ensure_utc(now if now is not None else _utcnow(), "now")
    window_start = now_utc - timedelta(hours=float(since_hours))
    runs: list[tuple[datetime, str, str, float | None]] = []
    for path in list_snapshots(data_root):
        try:
            meta = read_meta(path)
        except ValueError as exc:
            logger.warning("skipping unreadable snapshot %s: %s", path, exc)
            continue
        if meta.term_id != term_id or meta.run_started_at < window_start or meta.run_started_at > now_utc:
            continue
        runs.append((meta.run_started_at, meta.kind, meta.scope, missing_share(meta.n_observed, len(meta.missing_ids))))
    runs.sort(key=lambda r: r[0])
    times = [r[0] for r in runs]
    shares = [r[3] for r in runs if r[3] is not None]
    report: dict[str, Any] = {
        "term_id": term_id,
        "since_hours": float(since_hours),
        "now": now_utc.isoformat(),
        **_gap_stats(times),
        "first": times[0].isoformat() if times else None,
        "last": times[-1].isoformat() if times else None,
        "minutes_since_last": round((now_utc - times[-1]).total_seconds() / 60.0, 3) if times else None,
        "runs_by_kind": dict(sorted(Counter(r[1] for r in runs).items())),
        "runs_by_scope": dict(sorted(Counter(r[2] for r in runs).items())),
        "median_missing_share": round(float(np.median(shares)), 4) if shares else None,
        "max_missing_share": round(float(max(shares)), 4) if shares else None,
        "by_scope": {
            scope: _gap_stats([r[0] for r in runs if r[2] == scope])
            for scope in sorted({r[2] for r in runs})
        },
    }
    return report


def missing_share(n_observed: int, n_missing: int) -> float | None:
    """``n_missing / (n_observed + n_missing)``; ``None`` when nothing was in scope."""
    total = int(n_observed) + int(n_missing)
    return int(n_missing) / total if total else None


def breaches(
    report: dict[str, Any],
    fail_if_gap_min: float | None,
    fail_if_runs_lt: int | None,
    fail_if_missing_share_gt: float | None = None,
) -> list[str]:
    """Human-readable threshold violations for ``report`` (empty when healthy).

    ``fail_if_missing_share_gt`` is compared against ``median_missing_share``.
    """
    out: list[str] = []
    if fail_if_gap_min is not None:
        largest = report.get("largest_gap_min")
        if largest is not None and largest > fail_if_gap_min:
            out.append(f"largest gap {largest:.1f} min exceeds {fail_if_gap_min:g} min")
    if fail_if_runs_lt is not None and report.get("n_runs", 0) < fail_if_runs_lt:
        out.append(f"only {report.get('n_runs', 0)} runs, fewer than {fail_if_runs_lt}")
    if fail_if_missing_share_gt is not None:
        median = report.get("median_missing_share")
        if median is not None and median > fail_if_missing_share_gt:
            out.append(f"median missing share {median:.3f} exceeds {fail_if_missing_share_gt:g}")
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m scraper.gaps", description=__doc__.split("CLI::")[0].strip())
    p.add_argument("--data-root", type=Path, required=True, help="checkout of the data branch")
    p.add_argument("--term-id", required=True, help="SIS term id, e.g. 2268")
    p.add_argument("--hours", type=float, default=24.0, help="window length in hours (default 24)")
    p.add_argument("--fail-if-gap-min", type=float, default=None, help="exit 1 if the largest gap exceeds this")
    p.add_argument("--fail-if-runs-lt", type=int, default=None, help="exit 1 if fewer runs than this")
    p.add_argument(
        "--fail-if-missing-share-gt",
        type=float,
        default=None,
        help="exit 1 if the median per-run missing share n_missing/(n_observed+n_missing) exceeds this (default: no check)",
    )
    p.add_argument("--now", type=datetime.fromisoformat, default=None, help="window end (ISO-8601 UTC); default: now")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint: print the JSON report; return 1 on a breached threshold."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    args = build_parser().parse_args(argv)
    now = args.now
    if now is not None and now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    report = gap_report(args.data_root, args.term_id, since_hours=args.hours, now=now)
    print(json.dumps(report, indent=2))
    problems = breaches(report, args.fail_if_gap_min, args.fail_if_runs_lt, args.fail_if_missing_share_gt)
    for problem in problems:
        print(f"BREACH: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
