"""Load the rebuilt panel with section identity and the data-log censoring rules.

See docs/DESIGN_A4.md section 1.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from scraper.rebuild import rebuild_panel
from scraper.storage import list_snapshots

logger = logging.getLogger(__name__)

IDENTITY_COLUMNS = (
    "course_key",
    "subject",
    "catalog_number",
    "class_number",
    "section_number",
    "component",
    "is_primary",
    "session_id",
)
CENSORING_KINDS = frozenset({"outage", "source_switch", "schema", "term_switch"})
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:T(\d{2}):(\d{2})Z)?$")


@dataclass(frozen=True)
class Outage:
    start: datetime
    end: datetime | None
    kind: str
    term_id: str | None
    scope: str
    note: str

    @property
    def is_point_event(self) -> bool:
        """Switches and schema changes without an end are moments, not spans."""
        return self.end is None and self.kind != "outage"

    def overlaps(self, t0: datetime, t1: datetime, term_id: str | None = None) -> bool:
        """True when the interval [t0, t1] is affected by this row and the row
        applies to ``term_id`` (a row with no term applies to all).

        An ``outage`` with no end is open-ended (everything after ``start``).
        A ``source_switch``, ``schema`` or ``term_switch`` row with no end is a
        point event: only an interval that contains the moment is affected.
        With an end, every kind is the span [start, end)."""
        if term_id is not None and self.term_id is not None and self.term_id != term_id:
            return False
        if self.is_point_event:
            return t0 <= self.start <= t1
        if t1 < self.start:
            return False
        if self.end is not None and t0 >= self.end:
            return False
        return True


def _parse_stamp(text: str) -> datetime | None:
    text = text.strip()
    if text in ("", "-"):
        return None
    m = _DATE_RE.match(text)
    if not m:
        raise ValueError(f"unparsable timestamp in data log: {text!r}")
    day = date.fromisoformat(m.group(1))
    hour = int(m.group(2) or 0)
    minute = int(m.group(3) or 0)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


def parse_data_log(path: Path | str = Path("docs/DATA_LOG.md")) -> list[Outage]:
    """Rows of the data log whose kind is a censoring rule (docs/DATA_LOG.md format).

    Rows of kind ``correction`` that name an earlier row's start and carry an
    end close that row: the corrected row's end becomes the correction's
    end_utc when it is given, else the correction's start.
    """
    text = Path(path).read_text(encoding="utf-8")
    rows: list[tuple[str, str, str, str, str, str]] = []
    for line in text.splitlines():
        if not line.startswith("| 20"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) < 6:
            continue
        rows.append((cells[0], cells[1], cells[2], cells[3], cells[4], cells[5]))
    outages: list[Outage] = []
    for start, end, kind, term_id, scope, note in rows:
        if kind in CENSORING_KINDS:
            try:
                s = _parse_stamp(start)
                e = _parse_stamp(end)
            except ValueError as exc:
                logger.warning("skipping data log row: %s", exc)
                continue
            if s is None:
                continue
            outages.append(Outage(start=s, end=e, kind=kind, term_id=None if term_id in ("", "-") else term_id, scope=scope, note=note))
    # apply corrections that close an earlier row
    for start, end, kind, term_id, scope, note in rows:
        if kind != "correction":
            continue
        m = re.search(r"starts (\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}Z)?)", note)
        if not m:
            continue
        target = _parse_stamp(m.group(1))
        closing = _parse_stamp(end) or _parse_stamp(start)
        m2 = re.search(r"end_utc is (\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}Z)?)", note)
        if m2:
            closing = _parse_stamp(m2.group(1))
        for i, o in enumerate(outages):
            if o.start == target and o.end is None and closing is not None:
                outages[i] = Outage(o.start, closing, o.kind, o.term_id, o.scope, o.note)
    return outages


def section_identity(data_root: Path | str, term_id: str) -> pd.DataFrame:
    """One row per section_id: identity columns from its latest snapshot row,
    plus ``first_seen`` and ``last_seen`` (fetched_at)."""
    data_root = Path(data_root)
    frames = []
    columns = ["section_id", "term_id", "fetched_at", *IDENTITY_COLUMNS]
    for path in list_snapshots(data_root):
        table = pq.read_table(path, columns=columns)
        if table.num_rows == 0:
            continue
        frame = table.to_pandas(types_mapper=pd.ArrowDtype)
        frame = frame[frame["term_id"] == term_id]
        if len(frame):
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["section_id", *IDENTITY_COLUMNS, "first_seen", "last_seen"])
    allrows = pd.concat(frames, ignore_index=True)
    allrows = allrows.sort_values(["section_id", "fetched_at"])
    latest = allrows.groupby("section_id", as_index=False).last()
    first = allrows.groupby("section_id", as_index=False)["fetched_at"].first().rename(columns={"fetched_at": "first_seen"})
    out = latest.rename(columns={"fetched_at": "last_seen"}).merge(first, on="section_id")
    out = out[["section_id", *IDENTITY_COLUMNS, "first_seen", "last_seen"]]
    for col in ("section_id", "course_key", "subject", "catalog_number", "class_number", "section_number", "component", "session_id"):
        out[col] = out[col].astype("string")
    return out.reset_index(drop=True)


def load_panel(data_root: Path | str, term_id: str, *, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """The rebuilt panel joined with section identity; sorted by section then time."""
    data_root = Path(data_root)
    panel = rebuild_panel(data_root, term_id, start=start, end=end)
    identity = section_identity(data_root, term_id)
    merged = panel.merge(identity.drop(columns=["first_seen", "last_seen"]), on="section_id", how="left")
    merged["section_id"] = merged["section_id"].astype("string")
    return merged.sort_values(["section_id", "run_started_at"]).reset_index(drop=True)
