"""Rebuild the (section_id, run) panel from baseline + delta snapshots.

See docs/DESIGN_A2.md section 3.

Semantics per run, applied in time order with state carried forward across
days (a baseline replaces state only for the ids it contains):

* every file is an upsert of its rows into the carried state;
* scope ``full``: the observed set is every id in the carried state after
  applying this file (the day's baseline ids, ids introduced by files since,
  and ids carried from earlier days) minus ``missing_ids``. A full sweep
  attempts the whole universe, so a carried id that is not in the file was
  either unchanged, already tombstoned (``GONE`` is carried with
  ``observed=True`` until the section reappears), or in ``missing_ids``;
* scope ``priority``: the observed set is ``observed_ids`` from the file
  metadata minus ``missing_ids`` (falls back to the ids in the file, with a
  warning, when the metadata key is absent).

Not-observed rows carry the previous values forward with ``observed=False``.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa

from scraper.schema import COUNT_FIELDS, SNAPSHOT_SCHEMA
from scraper.storage import (
    RunMeta,
    list_snapshots,
    parse_snapshot_path,
    read_meta,
    read_snapshot,
    table_to_frame,
)

logger = logging.getLogger(__name__)

PANEL_SCHEMA = pa.schema(
    [pa.field("section_id", pa.string(), nullable=False),
     pa.field("run_started_at", pa.timestamp("us", tz="UTC"), nullable=False)]
    + [SNAPSHOT_SCHEMA.field(name) for name in COUNT_FIELDS]
    + [
        pa.field("observed", pa.bool_(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("scope", pa.string(), nullable=False),
        pa.field("kind", pa.string(), nullable=False),
    ]
)

PANEL_COLUMNS: tuple[str, ...] = tuple(PANEL_SCHEMA.names)


def rebuild_panel(
    data_root: Path,
    term_id: str,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """One row per (section_id, run) for every run of ``term_id`` in range.

    ``start``/``end`` are inclusive UTC partition dates. Files before
    ``start`` are still applied to the carried state (without emitting rows)
    so the window starts from the correct carried values.

    Columns: ``section_id, run_started_at, *COUNT_FIELDS, observed, source,
    scope, kind`` sorted by ``run_started_at`` then ``section_id``; nullable
    pandas dtypes (Int32 / string / boolean).
    """
    state: dict[str, dict[str, Any]] = {}
    pieces: list[pa.Table] = []
    n_runs = 0
    for path in list_snapshots(data_root):
        ref = parse_snapshot_path(path)
        if ref is None or (end is not None and ref.date > end):
            continue
        meta = read_meta(path)
        if meta.term_id != term_id:
            continue
        table, _ = read_snapshot(path)
        rows = table.to_pylist()
        for row in rows:
            state[row["section_id"]] = row
        if start is not None and ref.date < start:
            continue  # warm-up only
        observed = _observed_set(meta, rows, state)
        pieces.append(_panel_piece(meta, state, observed))
        n_runs += 1
    logger.info("rebuilt panel for term %s: %d runs, %d sections in final state", term_id, n_runs, len(state))
    if pieces:
        panel = pa.concat_tables(pieces)
    else:
        panel = PANEL_SCHEMA.empty_table()
    panel = panel.sort_by([("run_started_at", "ascending"), ("section_id", "ascending")])
    return table_to_frame(panel)[list(PANEL_COLUMNS)]


def _observed_set(meta: RunMeta, rows: list[dict[str, Any]], state: dict[str, dict[str, Any]]) -> set[str]:
    """Ids counted as observed in this run (see module docstring)."""
    missing = set(meta.missing_ids)
    if meta.scope == "priority":
        if meta.observed_ids is None:
            logger.warning(
                "priority-scope run %s has no observed_ids metadata; using ids in the file",
                meta.run_started_at.isoformat(),
            )
            ids = {r["section_id"] for r in rows}
        else:
            ids = set(meta.observed_ids)
        return ids - missing
    return set(state) - missing


def _panel_piece(meta: RunMeta, state: dict[str, dict[str, Any]], observed: set[str]) -> pa.Table:
    """Panel rows for one run: the whole carried state, flagged by observation."""
    ids = sorted(state)
    columns: dict[str, list[Any]] = {
        "section_id": ids,
        "run_started_at": [meta.run_started_at] * len(ids),
    }
    for name in COUNT_FIELDS:
        columns[name] = [state[sid][name] for sid in ids]
    columns["observed"] = [sid in observed for sid in ids]
    columns["source"] = [meta.source] * len(ids)
    columns["scope"] = [meta.scope] * len(ids)
    columns["kind"] = [meta.kind] * len(ids)
    return pa.Table.from_pydict(columns, schema=PANEL_SCHEMA)


__all__ = ["PANEL_COLUMNS", "PANEL_SCHEMA", "rebuild_panel"]
