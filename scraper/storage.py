"""Snapshot storage layout, parquet metadata, and delta computation.

See docs/DESIGN_A2.md section 2 (binding) and section 11 (addendum).

Layout under ``data_root`` (the checkout of the ``data`` branch)::

    snapshots/date=YYYY-MM-DD/HHMM-baseline.parquet
    snapshots/date=YYYY-MM-DD/HHMM-delta.parquet
    status.json

Files are never rewritten: ``write_snapshot`` refuses to overwrite and writes
atomically (tmp file in the same directory, then ``os.replace``).

Every parquet file carries key-value metadata describing the run
(``RunMeta``). All metadata values are strings; lists are JSON-encoded.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from scraper.schema import (
    COUNT_FIELDS,
    FIELD_NAMES,
    SNAPSHOT_SCHEMA,
    TOMBSTONE_STATUS,
    SchemaError,
    SnapshotRow,
    rows_to_table,
    validate_table,
)

logger = logging.getLogger(__name__)

KINDS: tuple[str, ...] = ("baseline", "delta")
SCOPES: tuple[str, ...] = ("full", "priority")

SNAPSHOTS_DIR = "snapshots"
STATUS_FILE = "status.json"

_DATE_DIR_RE = re.compile(r"^date=(\d{4}-\d{2}-\d{2})$")
_SNAPSHOT_FILE_RE = re.compile(r"^(\d{2})(\d{2})-(baseline|delta)\.parquet$")

# pyarrow -> pandas nullable dtypes, so that nulls in int32 / bool / string
# columns stay nulls (pd.NA) instead of turning int columns into float64.
_PANDAS_TYPES: dict[pa.DataType, Any] = {
    pa.int32(): pd.Int32Dtype(),
    pa.int64(): pd.Int64Dtype(),
    pa.string(): pd.StringDtype(),
    pa.bool_(): pd.BooleanDtype(),
}

_INT_COUNT_FIELDS: tuple[str, ...] = tuple(
    f for f in COUNT_FIELDS if pa.types.is_integer(SNAPSHOT_SCHEMA.field(f).type)
)


# --------------------------------------------------------------------------
# Run metadata
# --------------------------------------------------------------------------


@dataclass
class RunMeta:
    """Per-file run metadata; mirrors the parquet key-value metadata table.

    ``observed_ids`` is the list of section ids successfully fetched in the
    run. It is persisted whenever given, except for a complete full-scope
    sweep (``scope == "full"`` and ``complete is True``), whose observed set
    rebuild.py reconstructs from the carried state; it reads back as ``None``
    when absent from a file.

    ``complete`` (metadata key ``complete`` = ``"true"`` / ``"false"``) says
    whether the run attempted the whole term universe: full scope, universe
    known, not truncated by a time budget or ``--limit``. ``None`` means the
    file predates the key.
    """

    run_started_at: datetime
    term_id: str
    source: str
    kind: str
    scope: str
    shard: str = ""
    priority_sha: str = ""
    missing_ids: list[str] = field(default_factory=list)
    n_observed: int = 0
    n_written: int = 0
    observed_ids: list[str] | None = None
    complete: bool | None = None

    def validate(self) -> None:
        """Raise ValueError if kind/scope/run_started_at are not acceptable."""
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {self.kind!r}")
        if self.scope not in SCOPES:
            raise ValueError(f"scope must be one of {SCOPES}, got {self.scope!r}")
        ensure_utc(self.run_started_at, "run_started_at")
        if not self.term_id:
            raise ValueError("term_id must be non-empty")
        if not self.source:
            raise ValueError("source must be non-empty")

    def to_metadata(self) -> dict[str, str]:
        """Serialize to parquet key-value metadata (all values strings).

        Lists are JSON-encoded, sorted and de-duplicated. ``observed_ids`` is
        written when it is not ``None``, except for a complete full-scope run
        (see the class docstring); ``complete`` is written when not ``None``.
        """
        self.validate()
        md = {
            "run_started_at": ensure_utc(self.run_started_at, "run_started_at").isoformat(),
            "term_id": str(self.term_id),
            "source": str(self.source),
            "kind": self.kind,
            "scope": self.scope,
            "shard": str(self.shard or ""),
            "priority_sha": str(self.priority_sha or ""),
            "missing_ids": _dump_ids(self.missing_ids),
            "n_observed": str(int(self.n_observed)),
            "n_written": str(int(self.n_written)),
        }
        if self.complete is not None:
            md["complete"] = "true" if self.complete else "false"
        if self.observed_ids is not None and not (self.scope == "full" and self.complete is True):
            md["observed_ids"] = _dump_ids(self.observed_ids)
        return md

    @classmethod
    def from_metadata(cls, metadata: Mapping[bytes | str, bytes | str] | None) -> "RunMeta":
        """Parse parquet key-value metadata. Raises ValueError on missing or
        malformed required keys; unknown keys are ignored."""
        if not metadata:
            raise ValueError("snapshot has no key-value metadata")
        md: dict[str, str] = {}
        for k, v in metadata.items():
            key = k.decode("utf-8") if isinstance(k, bytes) else str(k)
            val = v.decode("utf-8") if isinstance(v, bytes) else str(v)
            md[key] = val
        required = ("run_started_at", "term_id", "source", "kind", "scope")
        missing = [k for k in required if k not in md]
        if missing:
            raise ValueError(f"snapshot metadata missing keys: {missing}")
        try:
            run_started_at = datetime.fromisoformat(md["run_started_at"])
        except ValueError as exc:
            raise ValueError(f"bad run_started_at {md['run_started_at']!r}: {exc}") from exc
        observed = md.get("observed_ids")
        meta = cls(
            run_started_at=ensure_utc(run_started_at, "run_started_at"),
            term_id=md["term_id"],
            source=md["source"],
            kind=md["kind"],
            scope=md["scope"],
            shard=md.get("shard", ""),
            priority_sha=md.get("priority_sha", ""),
            missing_ids=_load_ids(md.get("missing_ids", "[]"), "missing_ids"),
            n_observed=_load_int(md.get("n_observed", "0"), "n_observed"),
            n_written=_load_int(md.get("n_written", "0"), "n_written"),
            observed_ids=None if observed is None else _load_ids(observed, "observed_ids"),
            complete=_load_bool(md.get("complete"), "complete"),
        )
        meta.validate()
        return meta


def _dump_ids(ids: Iterable[str] | None) -> str:
    """JSON-encode an id collection as a sorted, de-duplicated list of str."""
    if ids is None:
        return "[]"
    return json.dumps(sorted({str(x) for x in ids}), separators=(",", ":"))


def _load_ids(text: str, key: str) -> list[str]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"metadata {key} is not JSON: {exc}") from exc
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(f"metadata {key} must be a JSON list of strings")
    return value


def _load_bool(text: str | None, key: str) -> bool | None:
    if text is None:
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    raise ValueError(f"metadata {key} must be 'true' or 'false', got {text!r}")


def _load_int(text: str, key: str) -> int:
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"metadata {key} is not an integer: {text!r}") from exc


def ensure_utc(dt: datetime, what: str = "datetime") -> datetime:
    """Return ``dt`` converted to UTC; raise ValueError if it is naive."""
    if not isinstance(dt, datetime):
        raise ValueError(f"{what} must be a datetime, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware (UTC), got naive {dt!r}")
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


def snapshots_dir(data_root: Path) -> Path:
    return Path(data_root) / SNAPSHOTS_DIR


def status_path(data_root: Path) -> Path:
    return Path(data_root) / STATUS_FILE


def snapshot_path(data_root: Path, run_started_at: datetime, kind: str) -> Path:
    """``<data_root>/snapshots/date=YYYY-MM-DD/HHMM-<kind>.parquet``.

    Date partition and HHMM are the UTC date and time of ``run_started_at``.
    Raises ValueError for an unknown kind or a naive datetime.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    started = ensure_utc(run_started_at, "run_started_at")
    day = started.date().isoformat()
    return snapshots_dir(data_root) / f"date={day}" / f"{started:%H%M}-{kind}.parquet"


@dataclass(frozen=True)
class SnapshotRef:
    """What a snapshot path encodes: its UTC partition date, HHMM, and kind."""

    path: Path
    date: date
    hhmm: str
    kind: str

    @property
    def sort_key(self) -> tuple[str, str, int]:
        return (self.date.isoformat(), self.hhmm, KINDS.index(self.kind))


def parse_snapshot_path(path: Path) -> SnapshotRef | None:
    """Decode a snapshot path; ``None`` if it is not a snapshot file name."""
    path = Path(path)
    m_dir = _DATE_DIR_RE.match(path.parent.name)
    m_file = _SNAPSHOT_FILE_RE.match(path.name)
    if not m_dir or not m_file:
        return None
    try:
        day = date.fromisoformat(m_dir.group(1))
    except ValueError:
        return None
    return SnapshotRef(path=path, date=day, hhmm=m_file.group(1) + m_file.group(2), kind=m_file.group(3))


def list_snapshots(data_root: Path, date: date | None = None) -> list[Path]:
    """All snapshot files (both kinds) sorted by time, optionally for one UTC date.

    Sorting is by the path (partition date, HHMM, baseline before delta) and
    never opens the files. Temporary and foreign files are ignored.
    """
    base = snapshots_dir(data_root)
    if not base.is_dir():
        return []
    if date is not None:
        dirs = [base / f"date={date.isoformat()}"]
    else:
        dirs = sorted(p for p in base.iterdir() if p.is_dir() and _DATE_DIR_RE.match(p.name))
    refs: list[SnapshotRef] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.iterdir():
            ref = parse_snapshot_path(p)
            if ref is not None and p.is_file():
                refs.append(ref)
            else:
                logger.debug("ignoring non-snapshot file %s", p)
    refs.sort(key=lambda r: r.sort_key)
    return [r.path for r in refs]


# --------------------------------------------------------------------------
# Read / write
# --------------------------------------------------------------------------


def write_snapshot(data_root: Path, table: pa.Table, meta: RunMeta) -> Path:
    """Validate and write ``table`` with ``meta`` as parquet metadata.

    Refuses to overwrite an existing file (FileExistsError). Writes to a
    temporary file in the target directory and renames it into place so a
    crash never leaves a partial parquet at the final path. ``n_written`` in
    the file metadata is always the number of rows written. An empty table
    is accepted (a run with observed sections but no changes).
    Returns the final path.
    """
    validate_table(table)
    meta.validate()
    path = snapshot_path(data_root, meta.run_started_at, meta.kind)
    if path.exists():
        raise FileExistsError(f"snapshot already exists, refusing to overwrite: {path}")
    if meta.scope == "priority" and meta.observed_ids is None:
        logger.warning(
            "priority-scope snapshot %s has no observed_ids; rebuild will fall back to ids in the file",
            path.name,
        )
    file_meta = dataclasses.replace(meta, n_written=table.num_rows)
    # The run metadata goes into the file footer once, through the writer, rather
    # than into the Arrow schema (which pyarrow would then serialise a second time,
    # base64-encoded, inside the ARROW:schema key). Column statistics are skipped
    # and zstd used: a 43-row delta shrinks from about 30 KB to about 12 KB.
    kv = {
        (k.decode() if isinstance(k, bytes) else str(k)): (v.decode() if isinstance(v, bytes) else str(v))
        for k, v in file_meta.to_metadata().items()
    }
    bare = table.replace_schema_metadata(None)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with pq.ParquetWriter(tmp, bare.schema, compression="zstd", write_statistics=False) as writer:
            writer.write_table(bare)
            writer.add_key_value_metadata(kv)
        if path.exists():  # re-check: never clobber a file that appeared meanwhile
            raise FileExistsError(f"snapshot appeared during write, refusing to overwrite: {path}")
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover - best effort cleanup
            logger.warning("could not remove temp file %s: %s", tmp, exc)
        raise
    logger.info(
        "wrote %s kind=%s scope=%s rows=%d observed=%d missing=%d",
        path, meta.kind, meta.scope, table.num_rows, meta.n_observed, len(meta.missing_ids),
    )
    return path


def read_raw_metadata(path: Path) -> dict[bytes, bytes]:
    """Key-value metadata of a snapshot.

    Files written since 2026-09-19 carry it in the Parquet footer only (the
    writer adds it after the row group, so pyarrow does not merge it into the
    Arrow schema on read); older files carry it in the schema. Both are read.
    """
    try:
        file_meta = pq.read_metadata(path)
    except (OSError, pa.ArrowException) as exc:
        raise ValueError(f"cannot read parquet metadata from {path}: {exc}") from exc
    kv = dict(file_meta.metadata or {})
    kv.pop(b"ARROW:schema", None)
    if kv:
        return kv
    schema = pq.read_schema(path)
    return dict(schema.metadata or {})


def read_meta(path: Path) -> RunMeta:
    """Read only the run metadata of a snapshot (does not load the rows)."""
    return RunMeta.from_metadata(read_raw_metadata(path))


def read_snapshot(path: Path) -> tuple[pa.Table, RunMeta]:
    """Read a snapshot file; validates the table and parses its metadata."""
    try:
        table = pq.read_table(path)
    except (OSError, pa.ArrowException) as exc:
        raise ValueError(f"cannot read parquet file {path}: {exc}") from exc
    meta = RunMeta.from_metadata(read_raw_metadata(path))
    validate_table(table)
    return table, meta


def table_to_frame(table: pa.Table) -> pd.DataFrame:
    """Convert an arrow table to pandas using nullable dtypes (Int32,
    boolean, string) so nulls stay nulls."""
    return table.to_pandas(types_mapper=_PANDAS_TYPES.get)


def write_status(data_root: Path, status: Mapping[str, Any]) -> Path:
    """Atomically (re)write ``status.json`` (last run summary)."""
    path = status_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".status.", suffix=".tmp", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(dict(status), fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")
    os.replace(tmp_name, path)
    return path


# --------------------------------------------------------------------------
# State and deltas
# --------------------------------------------------------------------------


DEFAULT_LOOKBACK_DAYS = 7


def latest_baseline_meta(data_root: Path, term_id: str, as_of_date: date) -> RunMeta | None:
    """Metadata of the most recent baseline written for ``term_id`` on
    ``as_of_date`` (UTC); ``None`` when that day has no baseline for the term.
    Reads only file footers."""
    found: RunMeta | None = None
    for path in list_snapshots(data_root, as_of_date):
        ref = parse_snapshot_path(path)
        if ref is None or ref.kind != "baseline":
            continue
        meta = read_meta(path)
        if meta.term_id == term_id:
            found = meta
    return found


def _window(as_of_date: date, lookback_days: int) -> list[date]:
    """``as_of_date`` and the ``lookback_days`` UTC days before it, oldest first."""
    if lookback_days < 0:
        raise ValueError(f"lookback_days must be >= 0, got {lookback_days}")
    return [as_of_date - timedelta(days=k) for k in range(lookback_days, -1, -1)]


def _replay(data_root: Path, term_id: str, days: Iterable[date]) -> tuple[dict[str, dict[str, Any]], int]:
    """Upsert every file of ``term_id`` for ``days`` in time order.
    Returns the state and the number of files applied."""
    state: dict[str, dict[str, Any]] = {}
    n_files = 0
    for day in days:
        for path in list_snapshots(data_root, day):
            meta = read_meta(path)
            if meta.term_id != term_id:
                continue
            table, _ = read_snapshot(path)
            for row in table.to_pylist():
                state[row["section_id"]] = row
            n_files += 1
    return state, n_files


def _state_frame(state: Mapping[str, dict[str, Any]]) -> pd.DataFrame:
    rows = [state[sid] for sid in sorted(state)]
    table = pa.Table.from_pylist(rows, schema=SNAPSHOT_SCHEMA) if rows else rows_to_table([])
    return table_to_frame(table).set_index("section_id")


def carried_state(
    data_root: Path, term_id: str, as_of_date: date, *, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> pd.DataFrame | None:
    """State a run on ``as_of_date`` (UTC) starts from, baseline or not.

    Every file of ``term_id`` from the ``lookback_days`` days before
    ``as_of_date`` and from ``as_of_date`` itself, applied in time order as
    upserts (the same carry-forward rebuild.py performs, limited to the
    window). Returns a DataFrame indexed by ``section_id`` with every other
    schema field, or ``None`` when no file of the term lies in the window.
    This is what a full-scope baseline compares against to tombstone the ids
    that vanished since the previous day (``baseline_with_tombstones``).
    """
    state, n_files = _replay(data_root, term_id, _window(as_of_date, lookback_days))
    return _state_frame(state) if n_files else None


def latest_state(
    data_root: Path,
    term_id: str,
    as_of_date: date,
    *,
    seed_from_previous_days: bool = True,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame | None:
    """Most recent observation of every section known on ``as_of_date`` (UTC).

    ``None`` when the day has no baseline for ``term_id``. Otherwise the
    day's files are applied in time order as upserts on top of the state
    carried from the previous ``lookback_days`` days (``carried_state``), so
    a section present in yesterday's final state but absent from today's
    baseline is still compared against, and the first full-scope delta of
    the day tombstones it when it is not in the universe either. Pass
    ``seed_from_previous_days=False`` (or ``lookback_days=0``) for the day's
    files alone. Returns a DataFrame indexed by ``section_id`` with every
    other schema field (identity + COUNT_FIELDS, nullable dtypes).
    """
    if latest_baseline_meta(data_root, term_id, as_of_date) is None:
        return None
    days = _window(as_of_date, lookback_days if seed_from_previous_days else 0)
    state, _ = _replay(data_root, term_id, days)
    return _state_frame(state)


def compute_delta(
    previous: pd.DataFrame | None,
    observed: pa.Table,
    universe_ids: set[str] | None,
    fetched_at: datetime,
    source: str | None = None,
) -> pa.Table:
    """Rows of ``observed`` that are new or whose COUNT_FIELDS changed, plus tombstones.

    Comparison is null-safe (``None == None`` is unchanged). Sections absent
    from ``previous`` are always emitted. When ``universe_ids`` is given
    (full scope), a tombstone row is emitted for every id in ``previous``
    that is in neither ``observed`` nor ``universe_ids``, is not already a
    tombstone, and whose ``source`` is the current source: ``section_status=
    "GONE"``, other COUNT_FIELDS and identity fields copied from ``previous``,
    ``fetched_at`` = the run time passed in, ``source`` = the current source.

    The current source is ``source`` if given, else the source of the
    ``observed`` rows; when neither is known (nothing observed) the previous
    row's source is used and the guard is moot. Rows written by another
    source are never tombstoned: their ids may live in another namespace
    (Berkeleytime's ``bt:...``) or scope, so their absence says nothing.
    Result validates against SNAPSHOT_SCHEMA and may be empty.
    """
    validate_table(observed)
    run_time = ensure_utc(fetched_at, "fetched_at")
    prev_rows = _previous_rows(previous)
    observed_rows = observed.to_pylist()
    observed_ids = {r["section_id"] for r in observed_rows}
    current_source = _current_source(source, observed_rows)

    changed: list[SnapshotRow] = []
    for row in observed_rows:
        prev = prev_rows.get(row["section_id"])
        if prev is None or _counts(prev) != _counts(row):
            changed.append(row)  # type: ignore[arg-type]

    tombstones = _tombstones(prev_rows, observed_ids, universe_ids, run_time, current_source)
    logger.info(
        "delta: %d changed/new of %d observed, %d tombstones",
        len(changed), len(observed_rows), len(tombstones),
    )
    return rows_to_table(changed + tombstones)


def compute_tombstones(
    previous: pd.DataFrame | None,
    observed: pa.Table,
    universe_ids: set[str] | None,
    fetched_at: datetime,
    source: str | None = None,
) -> pa.Table:
    """Only the tombstone rows ``compute_delta`` would emit for the same arguments.

    Empty when ``universe_ids`` or ``previous`` is ``None``. Used by fetch.py
    so that a full-scope baseline can express the disappearance of ids
    carried from the previous day.
    """
    validate_table(observed)
    run_time = ensure_utc(fetched_at, "fetched_at")
    prev_rows = _previous_rows(previous)
    observed_rows = observed.to_pylist()
    observed_ids = {r["section_id"] for r in observed_rows}
    return rows_to_table(_tombstones(prev_rows, observed_ids, universe_ids, run_time, _current_source(source, observed_rows)))


def baseline_with_tombstones(
    previous: pd.DataFrame | None,
    observed: pa.Table,
    universe_ids: set[str] | None,
    fetched_at: datetime,
    source: str | None = None,
) -> pa.Table:
    """``observed`` (every row of a baseline) followed by ``compute_tombstones(...)``.

    ``previous`` is the state carried into the run (``carried_state``); ids
    in it that are in neither ``observed`` nor ``universe_ids`` get a GONE
    row, so the day boundary cannot turn a vanished section into a zombie.
    Returns ``observed`` itself when there is nothing to tombstone.
    """
    tombstones = compute_tombstones(previous, observed, universe_ids, fetched_at, source)
    if tombstones.num_rows == 0:
        return observed
    table = pa.concat_tables([observed.replace_schema_metadata(None), tombstones])
    validate_table(table)
    logger.info("baseline: %d observed rows, %d tombstones", observed.num_rows, tombstones.num_rows)
    return table


def _current_source(source: str | None, observed_rows: list[dict[str, Any]]) -> str | None:
    if source:
        return str(source)
    return observed_rows[0]["source"] if observed_rows else None


def _tombstones(
    prev_rows: Mapping[str, dict[str, Any]],
    observed_ids: set[str],
    universe_ids: set[str] | None,
    run_time: datetime,
    current_source: str | None,
) -> list[SnapshotRow]:
    """GONE rows for previous rows of the current source that are neither observed nor in the universe."""
    out: list[SnapshotRow] = []
    if universe_ids is None:
        return out
    for sid in sorted(prev_rows):
        prev = prev_rows[sid]
        if sid in observed_ids or sid in universe_ids:
            continue
        if prev.get("section_status") == TOMBSTONE_STATUS:
            continue  # already recorded as gone; unchanged
        if current_source is not None and prev.get("source") != current_source:
            continue  # another source's row: never tombstoned across sources
        out.append(_tombstone(prev, run_time, current_source or prev["source"]))
    return out


def _tombstone(prev: dict[str, Any], run_time: datetime, source: str) -> SnapshotRow:
    row = {name: prev.get(name) for name in FIELD_NAMES}
    row["fetched_at"] = run_time
    row["section_status"] = TOMBSTONE_STATUS
    row["source"] = source
    return row  # type: ignore[return-value]


def _counts(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(_py(row.get(f)) for f in COUNT_FIELDS)


def _previous_rows(previous: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    """``previous`` as ``{section_id: row dict}`` with plain Python values."""
    if previous is None or len(previous) == 0:
        return {}
    frame = previous
    if "section_id" not in frame.columns:
        if frame.index.name != "section_id":
            raise ValueError("previous must be indexed by section_id or have a section_id column")
        frame = frame.reset_index()
    out: dict[str, dict[str, Any]] = {}
    for rec in frame.to_dict("records"):
        row = {k: _py(v) for k, v in rec.items()}
        for f in _INT_COUNT_FIELDS:
            v = row.get(f)
            if isinstance(v, float) and v.is_integer():
                row[f] = int(v)
        out[str(row["section_id"])] = row
    return out


def _py(value: Any) -> Any:
    """Normalize a pandas/numpy scalar to a plain Python value (nulls -> None)."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "KINDS",
    "SCOPES",
    "RunMeta",
    "SnapshotRef",
    "SchemaError",
    "baseline_with_tombstones",
    "carried_state",
    "compute_delta",
    "compute_tombstones",
    "ensure_utc",
    "latest_baseline_meta",
    "latest_state",
    "list_snapshots",
    "parse_snapshot_path",
    "read_meta",
    "read_snapshot",
    "snapshot_path",
    "snapshots_dir",
    "status_path",
    "table_to_frame",
    "write_snapshot",
    "write_status",
]
