"""Orchestration CLI: one sweep over a term, one snapshot file. DESIGN_A2 section 6.

Run as ``python -m scraper.fetch --term "Spring 2027"``.

Pipeline: choose source -> fetch -> ``rows_to_table`` -> decide kind
(``baseline`` if no baseline exists for today's UTC date or ``--force-baseline``,
else ``delta``) -> ``storage.write_snapshot`` -> ``status.json`` -> one summary
line on stdout. Logs go to stderr with timestamps.

Exit codes:
    0  success (also for ``--dry-run``)
    1  any unexpected exception (traceback logged)
    2  zero sections observed: nothing is written so the workflow fails loudly
    3  the term is not published on the source yet (classes_site before early October)
"""
from __future__ import annotations

import argparse
import inspect
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import pyarrow as pa

from scraper import config, storage
from scraper.schema import rows_to_table
from scraper.sources.base import FetchResult, PrioritySpec, Source, TermNotPublished, TermSpec

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_ROWS = 2
EXIT_TERM_NOT_PUBLISHED = 3

KIND_BASELINE = "baseline"
KIND_DELTA = "delta"
SCOPE_FULL = "full"
SCOPE_PRIORITY = "priority"

DRY_RUN_PATH = "(dry-run)"


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    """Argument parser with exactly the flags of DESIGN_A2 section 6 plus ``--catalog-max-pages``."""
    d = config.DEFAULTS
    p = argparse.ArgumentParser(
        prog="python -m scraper.fetch",
        description="Fetch one enrollment snapshot for a term and append it to the data branch.",
    )
    p.add_argument("--term", required=True, help='term name, e.g. "Spring 2027"')
    p.add_argument(
        "--source",
        choices=config.SOURCE_CHOICES,
        default=d["source"],
        help="auto: sis_api when SIS_CLASS_APP_ID and SIS_CLASS_APP_KEY are set, else classes_site",
    )
    p.add_argument("--data-root", type=Path, default=Path(d["data_root"]), help="checkout of the data branch")
    p.add_argument(
        "--priority-file",
        default=d["priority_file"],
        help='course patterns fetched every run (classes_site only); pass "none" to disable',
    )
    p.add_argument(
        "--n-shards",
        type=int,
        default=d["n_shards"],
        help="rotating shards of the non-priority remainder (classes_site); 0 = priority only",
    )
    p.add_argument(
        "--run-index",
        type=int,
        default=d["run_index"],
        help="drives shard rotation; default: number of snapshots already written today (UTC)",
    )
    p.add_argument("--time-budget-s", type=float, default=d["time_budget_s"], help="stop scheduling fetches after this")
    p.add_argument("--min-interval-s", type=float, default=d["min_interval_s"], help="global request spacing")
    p.add_argument("--max-concurrency", type=int, default=d["max_concurrency"], help="parallel requests")
    p.add_argument("--force-baseline", action="store_true", default=d["force_baseline"], help="write a baseline even if one exists today")
    p.add_argument("--limit", type=int, default=d["limit"], help="debug: cap the number of sections fetched")
    p.add_argument("--dry-run", action="store_true", default=d["dry_run"], help="fetch and print the summary, write nothing")
    p.add_argument("--catalog-max-pages", type=int, default=d["catalog_max_pages"], help="debug: cap listing pages read (classes_site)")
    return p


def configure_logging(env: Mapping[str, str] | None = None) -> None:
    """Timestamped logging to stderr; level from ``LOG_LEVEL`` (default INFO).

    ``basicConfig`` is a no-op when the root logger already has handlers, so
    pytest's capture is left untouched.
    """
    logging.basicConfig(
        level=config.log_level(env),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )


# ------------------------------------------------------------------ source setup


def resolve_source_name(requested: str, env: Mapping[str, str] | None = None) -> str:
    """Map ``auto`` to ``sis_api`` when both SIS credentials are set, else ``classes_site``."""
    if requested != "auto":
        return requested
    return "sis_api" if config.sis_credentials(env) else "classes_site"


def _accepts_parameter(func: Callable[..., Any], name: str) -> bool:
    """True when ``func`` takes a parameter called ``name`` or ``**kwargs``."""
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def build_source(
    name: str,
    *,
    data_root: Path,
    n_shards: int,
    min_interval_s: float,
    max_concurrency: int,
    catalog_max_pages: int | None = None,
    env: Mapping[str, str] | None = None,
) -> Source:
    """Instantiate the named source.

    Imports happen inside each branch so that a source module that is missing
    from this checkout only breaks that source, with a message naming it,
    instead of breaking the whole CLI at import time.
    """
    try:
        if name == "classes_site":
            from scraper.http import HttpClient
            from scraper.sources.classes_site import ClassesSiteSource

            client = HttpClient(config.USER_AGENT, min_interval_s=min_interval_s, max_concurrency=max_concurrency)
            extra: dict[str, Any] = {}
            if catalog_max_pages is not None and _accepts_parameter(ClassesSiteSource, "catalog_max_pages"):
                extra["catalog_max_pages"] = catalog_max_pages
            source: Source = ClassesSiteSource(client, data_root, n_shards, **extra)
            if catalog_max_pages is not None and not extra:
                # The source contract does not name this debug knob; expose it as an attribute.
                setattr(source, "catalog_max_pages", catalog_max_pages)
                logger.warning("ClassesSiteSource has no catalog_max_pages parameter; set as attribute (may be ignored)")
            return source
        if name == "sis_api":
            from scraper.sources.sis_api import SisApiSource

            creds = config.sis_credentials(env)
            if creds is None:
                raise RuntimeError(
                    f"source sis_api needs {config.ENV_SIS_APP_ID} and {config.ENV_SIS_APP_KEY} in the environment"
                )
            return SisApiSource(*creds)
        if name == "berkeleytime":
            from scraper.sources.berkeleytime import BerkeleytimeSource

            return BerkeleytimeSource()
    except ImportError as exc:
        raise RuntimeError(f"source {name!r} is not available in this checkout: {exc}") from exc
    raise ValueError(f"unknown source {name!r}; expected one of {config.SOURCE_CHOICES[1:]}")


def load_priority(priority_file: str, source_name: str) -> PrioritySpec | None:
    """PrioritySpec for classes_site runs; None for other sources or when disabled.

    Raises FileNotFoundError when the file is missing, so a typo in the path
    fails the run instead of silently sweeping the whole catalog.
    """
    disabled = priority_file.strip().lower() == config.PRIORITY_DISABLED
    if source_name != "classes_site":
        if not disabled:
            logger.info("priority list is only used by classes_site; ignored for %s", source_name)
        return None
    if disabled:
        logger.info("priority list disabled; full sweep")
        return None
    path = Path(priority_file)
    if not path.is_file():
        raise FileNotFoundError(f"priority file not found: {path} (pass --priority-file none to disable)")
    spec = PrioritySpec.from_file(path)
    logger.info("priority list %s: %d patterns, sha=%s", path, len(spec.patterns), spec.sha[:12])
    return spec


def choose_shard(priority: PrioritySpec | None, n_shards: int, run_index: int) -> tuple[int, int] | None:
    """``(k, n)`` for rotating sweeps of the non-priority remainder; None when sharding is off.

    Sharding only applies to priority-scope runs: a full sweep covers everything
    and ``--n-shards 0`` means "priority list only".
    """
    if priority is None or n_shards <= 0:
        return None
    return (run_index % n_shards, n_shards)


# ------------------------------------------------------------- storage helpers


def _utcnow() -> datetime:
    """Current UTC time; a function so tests can pin the clock."""
    return datetime.now(timezone.utc)


def snapshots_today(data_root: Path, today: date) -> list[Path]:
    """Snapshot files already written for ``today`` (UTC); empty when the root does not exist yet."""
    if not data_root.exists():
        return []
    return list(storage.list_snapshots(data_root, date=today))


def default_run_index(data_root: Path, today: date) -> int:
    """Number of snapshots written today, so consecutive runs rotate through shards."""
    return len(snapshots_today(data_root, today))


def has_baseline_today(data_root: Path, today: date) -> bool:
    """True when a ``*-baseline.parquet`` exists in today's partition."""
    suffix = f"-{KIND_BASELINE}.parquet"
    return any(p.name.endswith(suffix) for p in snapshots_today(data_root, today))


def decide_kind(data_root: Path, today: date, force_baseline: bool) -> str:
    """``baseline`` for the first run of a UTC day or on request, else ``delta``."""
    if force_baseline or not has_baseline_today(data_root, today):
        return KIND_BASELINE
    return KIND_DELTA


def effective_term_id(table: pa.Table, term: TermSpec) -> str:
    """Term id to record for this run.

    Sources that read the id off the page (classes_site, Addendum) may report a
    value that differs from the derived one; when every row agrees, the observed
    value wins and a warning is logged. Mixed values fall back to the derived id.
    """
    observed = set(table.column("term_id").to_pylist())
    if len(observed) == 1:
        term_id = str(observed.pop())
        if term_id != term.sis_term_id:
            logger.warning(
                "source reports term_id %s for %s (derived %s); recording the observed value",
                term_id, term.name, term.sis_term_id,
            )
        return term_id
    logger.warning("rows carry %d distinct term_ids %s; recording derived %s", len(observed), sorted(observed), term.sis_term_id)
    return term.sis_term_id


def _positional_arity(func: Callable[..., Any]) -> int:
    """Number of parameters that can be passed positionally (excluding ``*args``/``**kwargs``)."""
    try:
        params = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):
        return 0
    return sum(1 for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))


def compute_delta_table(
    previous: Any, observed: pa.Table, universe_ids: set[str] | None, fetched_at: datetime
) -> pa.Table:
    """Call ``storage.compute_delta`` with or without ``fetched_at``.

    DESIGN_A2 section 2 spells the function with three parameters; the build
    task adds ``fetched_at`` (timestamp for tombstone rows). Both are accepted.
    """
    if _positional_arity(storage.compute_delta) >= 4:
        return storage.compute_delta(previous, observed, universe_ids, fetched_at)
    return storage.compute_delta(previous, observed, universe_ids)


def build_output_table(
    kind: str,
    data_root: Path,
    term_id: str,
    today: date,
    observed: pa.Table,
    result: FetchResult,
    fetched_at: datetime,
) -> pa.Table:
    """Rows to write: everything for a baseline, changed rows (+ tombstones) for a delta."""
    if kind == KIND_BASELINE:
        return observed
    previous = storage.latest_state(data_root, term_id, today)
    if previous is None:
        logger.warning("no prior state for term %s on %s although a baseline exists; delta treats every row as new", term_id, today)
    universe = result.universe_ids if result.scope == SCOPE_FULL else None
    return compute_delta_table(previous, observed, universe, fetched_at)


def build_meta(
    run_started_at: datetime, term_id: str, source_name: str, kind: str, result: FetchResult, n_written: int
) -> Any:
    """``storage.RunMeta`` for this run; ``observed_ids`` only for priority scope (section 3)."""
    wanted: dict[str, Any] = {
        "run_started_at": run_started_at,
        "term_id": term_id,
        "source": source_name,
        "kind": kind,
        "scope": result.scope,
        "shard": result.shard,
        "priority_sha": result.priority_sha,
        "missing_ids": list(result.missing_ids),
        "n_observed": len(result.rows),
        "n_written": n_written,
        "observed_ids": list(result.observed_ids) if result.scope == SCOPE_PRIORITY else None,
    }
    accepted = {k: v for k, v in wanted.items() if _accepts_parameter(storage.RunMeta, k)}
    dropped = sorted(set(wanted) - set(accepted))
    if dropped:
        logger.warning("storage.RunMeta does not accept %s; dropped from metadata", dropped)
    return storage.RunMeta(**accepted)


def build_status(
    run_started_at: datetime, term_id: str, source_name: str, kind: str, result: FetchResult,
    n_written: int, sweep_seconds: float, path: Path,
) -> dict[str, Any]:
    """Contents of ``status.json``: the section 6 keys plus the file just written and the version."""
    return {
        "last_run_at": run_started_at.isoformat(),
        "term_id": term_id,
        "source": source_name,
        "kind": kind,
        "scope": result.scope,
        "shard": result.shard,
        "n_observed": len(result.rows),
        "n_written": n_written,
        "n_missing": len(result.missing_ids),
        "sweep_seconds": round(sweep_seconds, 3),
        "snapshot": str(path),
        "version": config.VERSION,
    }


def write_status(data_root: Path, status: dict[str, Any]) -> Path:
    """Rewrite ``status.json`` atomically (tmp file + rename)."""
    data_root.mkdir(parents=True, exist_ok=True)
    target = data_root / config.STATUS_FILENAME
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def summary_line(
    kind: str, scope: str, n_observed: int, n_written: int, n_missing: int, sweep_seconds: float, path: str
) -> str:
    """The one line printed to stdout at the end of a run."""
    return (
        f"kind={kind} scope={scope} n_observed={n_observed} n_written={n_written} "
        f"n_missing={n_missing} sweep_seconds={sweep_seconds:.1f} path={path}"
    )


# ------------------------------------------------------------------------ run


def run(args: argparse.Namespace, env: Mapping[str, str] | None = None) -> int:
    """Execute one sweep; returns the exit code. Exceptions propagate to ``main``."""
    env = os.environ if env is None else env
    run_started_at = _utcnow()
    today = run_started_at.date()
    term = TermSpec.from_name(args.term)
    source_name = resolve_source_name(args.source, env)
    data_root = Path(args.data_root)
    run_index = args.run_index if args.run_index is not None else default_run_index(data_root, today)
    priority = load_priority(args.priority_file, source_name)
    shard = choose_shard(priority, args.n_shards, run_index)
    source = build_source(
        source_name,
        data_root=data_root,
        n_shards=args.n_shards,
        min_interval_s=args.min_interval_s,
        max_concurrency=args.max_concurrency,
        catalog_max_pages=args.catalog_max_pages,
        env=env,
    )
    logger.info(
        "run start term=%s (sis %s) source=%s run_index=%d shard=%s budget=%.0fs limit=%s dry_run=%s",
        term.name, term.sis_term_id, source_name, run_index, shard, args.time_budget_s, args.limit, args.dry_run,
    )

    t0 = time.monotonic()
    result = source.fetch(term, priority=priority, shard=shard, time_budget_s=args.time_budget_s, limit=args.limit)
    sweep_seconds = time.monotonic() - t0
    n_observed = len(result.rows)
    n_missing = len(result.missing_ids)
    logger.info("fetch done scope=%s observed=%d missing=%d in %.1fs", result.scope, n_observed, n_missing, sweep_seconds)
    if n_missing:
        logger.warning("missing ids (%d), first few: %s", n_missing, result.missing_ids[:10])
    if n_observed == 0:
        logger.error("zero sections observed; writing nothing (exit %d)", EXIT_NO_ROWS)
        return EXIT_NO_ROWS

    observed = rows_to_table(result.rows)
    term_id = effective_term_id(observed, term)
    kind = decide_kind(data_root, today, args.force_baseline)
    out = build_output_table(kind, data_root, term_id, today, observed, result, run_started_at)
    n_written = out.num_rows
    logger.info("kind=%s rows_to_write=%d", kind, n_written)

    if args.dry_run:
        logger.info("dry run: nothing written")
        print(summary_line(kind, result.scope, n_observed, n_written, n_missing, sweep_seconds, DRY_RUN_PATH))
        return EXIT_OK

    meta = build_meta(run_started_at, term_id, source_name, kind, result, n_written)
    path = storage.write_snapshot(data_root, out, meta)
    status = build_status(run_started_at, term_id, source_name, kind, result, n_written, sweep_seconds, path)
    write_status(data_root, status)
    logger.info("wrote %s (%d rows) and %s", path, n_written, config.STATUS_FILENAME)
    print(summary_line(kind, result.scope, n_observed, n_written, n_missing, sweep_seconds, str(path)))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: parse, run, map exceptions to exit codes."""
    args = build_parser().parse_args(argv)
    configure_logging()
    try:
        return run(args)
    except TermNotPublished as exc:
        logger.error("term not published on the source yet: %s (exit %d)", exc, EXIT_TERM_NOT_PUBLISHED)
        return EXIT_TERM_NOT_PUBLISHED
    except Exception:  # noqa: BLE001 - process boundary: every failure becomes exit 1 with a traceback
        logger.exception("fetch failed (exit %d)", EXIT_ERROR)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
