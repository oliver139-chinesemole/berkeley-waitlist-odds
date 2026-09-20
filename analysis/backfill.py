"""Backfill a finished term from Berkeleytime's public enrollment history.

Berkeleytime polls SIS every 15 minutes and serves each section's history
through ``GetEnrollment`` as run-length segments: ``startTime`` to ``endTime``
during which every count was constant. This module turns those segments into
the panel shape ``analysis.flows.interval_flows`` reads, marks Berkeleytime's
own outages as censored intervals, and reports how much section-time is dark
per day, so a finished cycle (Fall 2026) can be modelled before this project's
own Spring 2027 collection exists.

Rules
- A segment's interior is observed stillness: one panel row at its start and
  one at its end with identical counts. The interval between them is never
  censored, however long, because Berkeleytime kept polling and nothing
  changed.
- The crossing from one segment's end to the next segment's start is where
  the change happened. A crossing of at most ``GAP_MIN`` (45) minutes is an
  ordinary poll interval. A wider one is a Berkeleytime gap: the interval is
  kept (the net change is real) but flagged ``censored``, so the position
  model stops there instead of attributing the change to a moment.
- Section selection never looks at today's waitlist or enrollment counts.
  Keeping the sections that are waitlisted today would keep exactly the ones
  that failed to clear. Selection is by component, the same self-study
  exclusion the scraper applies, from the term's ``GetCatalog`` listing, in a
  seeded permutation, so a pilot of N sections is the first N of the full pull.

Everything under ``backfill/`` is Berkeleytime's data. Its outputs carry
``data_source = "berkeleytime_history"`` and are never counted toward this
project's collection claims. Fetching needs a laptop: Berkeleytime's
Cloudflare blocks GitHub's runners. Tests never touch the network.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from analysis.flows import interval_flows, summary as flows_summary
from analysis.panel import IDENTITY_COLUMNS
from scraper.sources.base import ParseError, TermSpec
from scraper.sources.berkeleytime import BerkeleytimeError, BerkeleytimeSource, parse_catalog_class
from scraper.sources.classes_site import SELF_STUDY_COMPONENTS

logger = logging.getLogger(__name__)

GAP_MIN = 45.0  # a between-segment crossing wider than this is a Berkeleytime gap
DATA_SOURCE = "berkeleytime_history"
SOURCE = "berkeleytime"
DEFAULT_SLEEP_S = 2.0
PANEL_COLUMNS = (
    "section_id",
    "run_started_at",
    "enrolled_count",
    "enroll_capacity",
    "waitlist_count",
    "waitlist_capacity",
    "reserved_count",
    "open_reserved",
    "status",
    "section_status",
    "observed",
    "source",
    "scope",
    "kind",
    "term_id",
)
CROSSING_COLUMNS = ("section_id", "t0", "t1", "minutes", "wide")
SELECTION_COLUMNS = ("key", "subject", "catalog_number", "class_number", "section_number", "session_id", "component", "course_key")
_COUNTS = {
    "enrolledCount": "enrolled_count",
    "maxEnroll": "enroll_capacity",
    "waitlistedCount": "waitlist_count",
    "maxWaitlist": "waitlist_capacity",
    "reservedCount": "reserved_count",
    "openReserved": "open_reserved",
}


# ------------------------------------------------------------------ selection


def section_key(subject: str, catalog_number: str, class_number: str) -> str:
    return f"{subject}|{catalog_number}|{class_number}"


def select_sections(
    catalog: list[dict[str, Any]],
    term: TermSpec,
    *,
    exclude_components: frozenset[str] = SELF_STUDY_COMPONENTS,
    seed: int = 0,
    limit: int | None = None,
) -> pd.DataFrame:
    """Primary sections to pull, one row per class, in a seeded order.

    Uses only identity fields of the ``GetCatalog`` entries (subject, course
    number, class number, session, component); the counts in ``latest`` are
    read only to skip classes Berkeleytime never observed. With ``limit`` the
    first ``limit`` rows of the permutation are returned, so selections for
    growing limits are nested.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in catalog:
        try:
            row = parse_catalog_class(entry, datetime.now(timezone.utc), term)
        except ParseError as exc:
            logger.debug("select: skipping %s", exc)
            continue
        if row is None or row["component"] in exclude_components:
            continue
        key = section_key(row["subject"], row["catalog_number"], row["class_number"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "key": key,
                "subject": row["subject"],
                "catalog_number": row["catalog_number"],
                "class_number": row["class_number"],
                "section_number": row["section_number"],
                "session_id": row["session_id"],
                "component": row["component"],
                "course_key": row["course_key"],
            }
        )
    frame = pd.DataFrame(rows, columns=list(SELECTION_COLUMNS))
    if frame.empty:
        return frame
    frame = frame.sort_values(["subject", "catalog_number", "class_number"]).reset_index(drop=True)
    order = np.random.default_rng(int(seed)).permutation(len(frame))
    frame = frame.iloc[order].reset_index(drop=True)
    if limit is not None:
        frame = frame.head(int(limit)).reset_index(drop=True)
    return frame


# ---------------------------------------------------------------------- cache


class Cache:
    """Gzipped JSON under ``root``: the catalog, one file per section, a state file."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.enrollment_dir = self.root / "enrollment"
        self.catalog_path = self.root / "catalog.json.gz"
        self.state_path = self.root / "state.json"

    def _write(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh)
        tmp.replace(path)

    @staticmethod
    def _read(path: Path) -> Any:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)

    def has_catalog(self) -> bool:
        return self.catalog_path.exists()

    def write_catalog(self, catalog: list[dict[str, Any]], fetched_at: datetime) -> None:
        self._write(self.catalog_path, {"fetched_at": fetched_at.isoformat(), "catalog": catalog})

    def read_catalog(self) -> list[dict[str, Any]]:
        return self._read(self.catalog_path)["catalog"]

    def section_path(self, key: str) -> Path:
        return self.enrollment_dir / (key.replace("|", "__").replace("/", "_") + ".json.gz")

    def has_section(self, key: str) -> bool:
        return self.section_path(key).exists()

    def write_section(self, key: str, payload: dict[str, Any]) -> None:
        self._write(self.section_path(key), payload)

    def read_section(self, key: str) -> dict[str, Any]:
        return self._read(self.section_path(key))

    def section_keys(self) -> list[str]:
        if not self.enrollment_dir.exists():
            return []
        return sorted(p.name[: -len(".json.gz")].replace("__", "|") for p in self.enrollment_dir.glob("*.json.gz"))

    def read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"failed": {}, "selection": None}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------- fetch


@dataclass
class FetchSummary:
    term_id: str
    selected: int
    cached_before: int
    fetched: int
    failed: int
    failures: dict[str, str] = field(default_factory=dict)


_SCHEMA_ERROR = "Cannot query field"


def get_enrollment(source: BerkeleytimeSource, term: TermSpec, row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    """The whole ``enrollment`` object (``sectionId`` and ``history``) for one primary section.

    The ops file records more than one ``GetEnrollment`` document with the same
    variables, and the gateway's schema has dropped fields some of them ask
    for. The recorded ops are tried in file order; a schema error ("Cannot
    query field ...") moves on to the next, and the first op that answers is
    remembered on the source for the rest of the pull.
    """
    variables = {
        "year": term.year,
        "semester": term.berkeleytime_semester,
        "sessionId": str(row["session_id"]),
        "subject": str(row["subject"]).replace(" ", ""),
        "courseNumber": str(row["catalog_number"]),
        "sectionNumber": str(row["section_number"]),
    }
    ops = source.ops.get("GetEnrollment") or []
    preferred = getattr(source, "_backfill_enrollment_op", None)
    candidates = [preferred] + [o for o in ops if o is not preferred] if preferred is not None else list(ops)
    if not candidates:
        raise ParseError("GetEnrollment: no persisted operation recorded")
    last: ParseError | None = None
    for op in candidates:
        try:
            data = source.execute("GetEnrollment", variables, op=op)
        except ParseError as exc:
            if _SCHEMA_ERROR in str(exc) and op is not candidates[-1]:
                logger.info("GetEnrollment op %s rejected by the gateway schema; trying the next recorded op", op.id[:8])
                last = exc
                continue
            raise
        source._backfill_enrollment_op = op  # type: ignore[attr-defined]
        break
    else:
        raise last or ParseError("GetEnrollment: every recorded op failed")
    enrollment = data.get("enrollment")
    if not isinstance(enrollment, dict) or not isinstance(enrollment.get("history"), list):
        raise ParseError(f"GetEnrollment: no history for {variables['subject']} {variables['courseNumber']} {variables['sectionNumber']} ({term.name})")
    return enrollment


def fetch(
    source: BerkeleytimeSource,
    term: TermSpec,
    cache: Cache,
    *,
    limit: int | None = None,
    seed: int = 0,
    sleep_s: float = DEFAULT_SLEEP_S,
    sleep: Callable[[float], None] = time.sleep,
    refresh_catalog: bool = False,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> FetchSummary:
    """Pull ``GetEnrollment`` for the selected sections into ``cache``; resumable.

    One ``GetCatalog`` request (cached) chooses the sections; sections already
    in the cache are skipped, one request goes out every ``sleep_s`` seconds
    for the rest, and failures are recorded in ``state.json`` and retried on
    the next call. The selection (seed, limit) is recorded too.
    """
    if refresh_catalog or not cache.has_catalog():
        data = source.execute("GetCatalog", {"year": term.year, "semester": term.berkeleytime_semester})
        catalog = data.get("catalog")
        if not isinstance(catalog, list):
            raise ParseError("GetCatalog: payload has no catalog list")
        cache.write_catalog(catalog, clock())
        logger.info("cached GetCatalog for %s: %d classes", term.name, len(catalog))
    selection = select_sections(cache.read_catalog(), term, seed=seed, limit=limit)
    state = cache.read_state()
    state["selection"] = {"seed": int(seed), "limit": limit, "n": int(len(selection)), "term_id": term.sis_term_id}
    failed: dict[str, str] = dict(state.get("failed") or {})
    cached_before = 0
    fetched = 0
    requests_made = 0
    for row in selection.itertuples(index=False):
        key = row.key
        if cache.has_section(key):
            cached_before += 1
            failed.pop(key, None)
            continue
        if requests_made:
            sleep(float(sleep_s))
        requests_made += 1
        try:
            enrollment = get_enrollment(source, term, row._asdict())
        except (ParseError, BerkeleytimeError) as exc:
            failed[key] = f"{type(exc).__name__}: {exc}"
            logger.warning("backfill: %s failed: %s", key, exc)
        else:
            payload = {
                "key": key,
                "term_id": term.sis_term_id,
                "term_name": term.name,
                "fetched_at": clock().isoformat(),
                "section": {c: getattr(row, c) for c in SELECTION_COLUMNS if c != "key"},
                "enrollment": enrollment,
            }
            cache.write_section(key, payload)
            failed.pop(key, None)
            fetched += 1
        if (fetched + len(failed)) % 25 == 0:
            state["failed"] = failed
            cache.write_state(state)
    state["failed"] = failed
    cache.write_state(state)
    summary = FetchSummary(term_id=term.sis_term_id, selected=int(len(selection)), cached_before=cached_before, fetched=fetched, failed=len(failed), failures=failed)
    logger.info("backfill fetch %s: %s", term.name, {k: v for k, v in asdict(summary).items() if k != "failures"})
    return summary


# ---------------------------------------------------------------- history -> panel


def _stamp(text: str) -> datetime:
    return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(timezone.utc)


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def history_segments(enrollment: dict[str, Any]) -> list[dict[str, Any]]:
    """Segments sorted by start, each with parsed ``start``/``end`` and the count fields."""
    out = []
    for seg in enrollment.get("history") or []:
        start = _stamp(seg["startTime"])
        end = _stamp(seg["endTime"])
        if end < start:
            start, end = end, start
        item = {"start": start, "end": end, "status": str(seg.get("status") or "")}
        for src, dst in _COUNTS.items():
            item[dst] = _int_or_none(seg.get(src))
        out.append(item)
    out.sort(key=lambda s: (s["start"], s["end"]))
    return out


def history_to_rows(enrollment: dict[str, Any], term_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(panel rows, crossings)`` for one section's history.

    Panel rows: one at each segment's start and (when later) end, all
    ``observed``. Crossings: one per pair of consecutive segments with
    ``t0`` the earlier end, ``t1`` the later start and ``minutes`` between.
    """
    section_id = str(enrollment.get("sectionId") or "")
    if not section_id:
        raise ParseError("GetEnrollment: enrollment has no sectionId")
    rows: list[dict[str, Any]] = []
    crossings: list[dict[str, Any]] = []
    last_time: datetime | None = None
    prev_end: datetime | None = None
    for seg in history_segments(enrollment):
        if prev_end is not None and seg["start"] > prev_end:
            crossings.append({"section_id": section_id, "t0": prev_end, "t1": seg["start"], "minutes": (seg["start"] - prev_end).total_seconds() / 60.0})
        for when in (seg["start"], seg["end"]):
            if last_time is not None and when <= last_time:
                continue
            rows.append(
                {
                    "section_id": section_id,
                    "run_started_at": when,
                    "enrolled_count": seg["enrolled_count"],
                    "enroll_capacity": seg["enroll_capacity"],
                    "waitlist_count": seg["waitlist_count"],
                    "waitlist_capacity": seg["waitlist_capacity"],
                    "reserved_count": seg["reserved_count"],
                    "open_reserved": seg["open_reserved"],
                    "status": seg["status"],
                    "section_status": None,
                    "observed": True,
                    "source": SOURCE,
                    "scope": "full",
                    "kind": "history",
                    "term_id": str(term_id),
                }
            )
            last_time = when
        prev_end = max(prev_end, seg["end"]) if prev_end is not None else seg["end"]
    return rows, crossings


def _panel_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(rows, columns=list(PANEL_COLUMNS))
    frame["run_started_at"] = pd.to_datetime(frame["run_started_at"], utc=True)
    for col in ("enrolled_count", "enroll_capacity", "waitlist_count", "waitlist_capacity", "reserved_count", "open_reserved"):
        frame[col] = pd.array(frame[col].astype(object).where(frame[col].notna(), None), dtype="Int32")
    for col in ("section_id", "status", "section_status", "source", "scope", "kind", "term_id"):
        frame[col] = frame[col].astype("string")
    frame["observed"] = frame["observed"].astype("boolean")
    return frame.sort_values(["run_started_at", "section_id"]).reset_index(drop=True)


def _crossing_frame(crossings: list[dict[str, Any]], gap_min: float) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(crossings, columns=["section_id", "t0", "t1", "minutes"])
    frame["section_id"] = frame["section_id"].astype("string")
    frame["t0"] = pd.to_datetime(frame["t0"], utc=True)
    frame["t1"] = pd.to_datetime(frame["t1"], utc=True)
    frame["minutes"] = frame["minutes"].astype(float)
    frame["wide"] = frame["minutes"] > float(gap_min)
    return frame[list(CROSSING_COLUMNS)].sort_values(["section_id", "t0"]).reset_index(drop=True)


def build_panel(payloads: list[dict[str, Any]], term_id: str, *, gap_min: float = GAP_MIN) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """``(panel, identity, crossings)`` from cached ``GetEnrollment`` payloads.

    ``panel`` has the ``scraper.rebuild`` shape plus ``term_id``; ``identity``
    one row per ``section_id`` with ``analysis.panel.IDENTITY_COLUMNS``,
    ``first_seen`` and ``last_seen``; ``crossings`` every between-segment
    crossing with ``wide = minutes > gap_min``.
    """
    rows: list[dict[str, Any]] = []
    crossings: list[dict[str, Any]] = []
    ident: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in payloads:
        enrollment = payload["enrollment"]
        try:
            section_rows, section_crossings = history_to_rows(enrollment, term_id)
        except ParseError as exc:
            logger.warning("build: skipping %s: %s", payload.get("key"), exc)
            continue
        if not section_rows:
            continue
        section_id = section_rows[0]["section_id"]
        if section_id in seen:
            logger.warning("build: duplicate section id %s from %s; keeping the first", section_id, payload.get("key"))
            continue
        seen.add(section_id)
        rows.extend(section_rows)
        crossings.extend(section_crossings)
        info = payload["section"]
        ident.append(
            {
                "section_id": section_id,
                "course_key": info["course_key"],
                "subject": info["subject"],
                "catalog_number": info["catalog_number"],
                "class_number": info["class_number"],
                "section_number": info["section_number"],
                "component": info["component"],
                "is_primary": True,
                "session_id": str(info["session_id"]),
                "first_seen": section_rows[0]["run_started_at"],
                "last_seen": section_rows[-1]["run_started_at"],
            }
        )
    panel = _panel_frame(rows)
    identity = pd.DataFrame(ident, columns=["section_id", *IDENTITY_COLUMNS, "first_seen", "last_seen"])
    for col in ("section_id", "course_key", "subject", "catalog_number", "class_number", "section_number", "component", "session_id"):
        identity[col] = identity[col].astype("string")
    identity["first_seen"] = pd.to_datetime(identity["first_seen"], utc=True)
    identity["last_seen"] = pd.to_datetime(identity["last_seen"], utc=True)
    return panel, identity, _crossing_frame(crossings, gap_min)


def backfill_flows(panel: pd.DataFrame, crossings: pd.DataFrame) -> pd.DataFrame:
    """``interval_flows`` on the backfilled panel with wide crossings censored.

    No data-log outages apply (those are this project's scraper's) and no
    maximum interval: a long interval inside a segment is observed stillness.
    """
    flows = interval_flows(panel)
    if flows.empty or crossings.empty:
        return flows
    wide = crossings.loc[crossings["wide"], ["section_id", "t0"]].drop_duplicates()
    wide = wide.assign(section_id=wide["section_id"].astype("string"), t0=pd.to_datetime(wide["t0"], utc=True), _wide=True)
    merged = flows.merge(wide, on=["section_id", "t0"], how="left")
    flows["censored"] = pd.array(flows["censored"].fillna(False).astype(bool).to_numpy() | merged["_wide"].notna().to_numpy(), dtype="boolean")
    return flows


# ------------------------------------------------------------------ gap report


def gap_report(crossings: pd.DataFrame, identity: pd.DataFrame) -> pd.DataFrame:
    """Share of covered section-time that falls inside a wide crossing, per UTC day.

    Columns: ``date``, ``sections_covered`` (histories spanning the day),
    ``sections_dark`` (with any dark time that day), ``share_time_in_gap``.
    """
    if identity.empty:
        return pd.DataFrame(columns=["date", "sections_covered", "sections_dark", "share_time_in_gap"])
    first = pd.to_datetime(identity["first_seen"], utc=True)
    last = pd.to_datetime(identity["last_seen"], utc=True)
    day_s = 86400.0
    f = np.array([t.timestamp() for t in first], dtype=float)
    l = np.array([t.timestamp() for t in last], dtype=float)
    start = np.floor(f.min() / day_s) * day_s
    stop = np.ceil(l.max() / day_s) * day_s  # a history ending exactly at midnight adds no day
    n_days = max(1, int(round((stop - start) / day_s)))
    day_starts = start + day_s * np.arange(n_days)
    day_stops = day_starts + day_s
    dates = [datetime.fromtimestamp(d, tz=timezone.utc).date().isoformat() for d in day_starts]

    covered = np.clip(np.minimum(l[:, None], day_stops[None, :]) - np.maximum(f[:, None], day_starts[None, :]), 0.0, None)
    covered_time = covered.sum(axis=0)
    sections_covered = (covered > 0).sum(axis=0)

    dark_time = np.zeros(n_days)
    dark_sections: list[set[str]] = [set() for _ in range(n_days)]
    wide = crossings[crossings["wide"]] if len(crossings) else crossings
    for row in wide.itertuples(index=False):
        a = pd.Timestamp(row.t0).timestamp()
        b = pd.Timestamp(row.t1).timestamp()
        i0 = int(np.searchsorted(day_starts, a, side="right") - 1)
        i1 = int(np.searchsorted(day_starts, b, side="right") - 1)
        for i in range(max(i0, 0), min(i1, n_days - 1) + 1):
            overlap = min(b, day_stops[i]) - max(a, day_starts[i])
            if overlap > 0:
                dark_time[i] += overlap
                dark_sections[i].add(str(row.section_id))
    share = np.divide(dark_time, covered_time, out=np.zeros(n_days), where=covered_time > 0)
    return pd.DataFrame(
        {
            "date": dates,
            "sections_covered": sections_covered.astype(int),
            "sections_dark": [len(s) for s in dark_sections],
            "share_time_in_gap": np.round(share, 4),
        }
    )


# ---------------------------------------------------------------------- build


@dataclass
class BuildSummary:
    term_id: str
    sections: int
    segments: int
    panel_rows: int
    intervals: int
    share_censored: float
    crossings_wide: int
    worst_days: list[dict[str, Any]]
    out_dir: str


def build(cache: Cache, term: TermSpec, out_dir: Path | str, *, gap_min: float = GAP_MIN) -> BuildSummary:
    """Read every cached section, write the panel, identity, crossings, flows,
    gap report and ``meta.json`` under ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payloads = [cache.read_section(k) for k in cache.section_keys()]
    segments = sum(len((p.get("enrollment") or {}).get("history") or []) for p in payloads)
    panel, identity, crossings = build_panel(payloads, term.sis_term_id, gap_min=gap_min)
    flows = backfill_flows(panel, crossings)
    report = gap_report(crossings, identity)
    panel.to_parquet(out_dir / "panel.parquet", index=False)
    identity.to_parquet(out_dir / "identity.parquet", index=False)
    crossings.to_parquet(out_dir / "gaps.parquet", index=False)
    flows.to_parquet(out_dir / "flows.parquet", index=False)
    report.to_csv(out_dir / "gap_report.csv", index=False)
    fsum = flows_summary(flows)
    worst = report.sort_values(["share_time_in_gap", "date"], ascending=[False, True]).head(10)
    meta = {
        "data_source": DATA_SOURCE,
        "term_id": term.sis_term_id,
        "term_name": term.name,
        "sections": int(len(identity)),
        "segments": int(segments),
        "panel_rows": int(len(panel)),
        "gap_min": float(gap_min),
        "crossings": int(len(crossings)),
        "crossings_wide": int(crossings["wide"].sum()) if len(crossings) else 0,
        "flows": fsum,
        "history_window": None if identity.empty else [identity["first_seen"].min().isoformat(), identity["last_seen"].max().isoformat()],
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return BuildSummary(
        term_id=term.sis_term_id,
        sections=int(len(identity)),
        segments=int(segments),
        panel_rows=int(len(panel)),
        intervals=int(fsum["intervals"]),
        share_censored=float(fsum["share_censored"]),
        crossings_wide=meta["crossings_wide"],
        worst_days=worst.to_dict(orient="records"),
        out_dir=str(out_dir),
    )


def load_backfill(out_dir: Path | str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """``(panel, identity, flows, meta)`` written by ``build``."""
    out_dir = Path(out_dir)
    panel = pd.read_parquet(out_dir / "panel.parquet")
    identity = pd.read_parquet(out_dir / "identity.parquet")
    flows = pd.read_parquet(out_dir / "flows.parquet")
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    return panel, identity, flows, meta


# ------------------------------------------------------------------------ CLI


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill a term from Berkeleytime's GetEnrollment history (laptop only).")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("fetch", "build"):
        s = sub.add_parser(name)
        s.add_argument("--term", required=True, help='e.g. "Fall 2026"')
        s.add_argument("--cache", type=Path, default=None, help="raw cache dir (default backfill/raw/<term_id>)")
    sub.choices["fetch"].add_argument("--limit", type=int, default=None, help="pilot: first N sections of the seeded permutation")
    sub.choices["fetch"].add_argument("--seed", type=int, default=0)
    sub.choices["fetch"].add_argument("--sleep", type=float, default=DEFAULT_SLEEP_S, help="seconds between requests")
    sub.choices["fetch"].add_argument("--refresh-catalog", action="store_true")
    sub.choices["build"].add_argument("--out", type=Path, default=None, help="output dir (default backfill/<term_id>)")
    sub.choices["build"].add_argument("--gap-min", type=float, default=GAP_MIN)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    term = TermSpec.from_name(args.term)
    cache = Cache(args.cache or Path("backfill") / "raw" / term.sis_term_id)
    if args.command == "fetch":
        source = BerkeleytimeSource()
        summary = fetch(source, term, cache, limit=args.limit, seed=args.seed, sleep_s=args.sleep, refresh_catalog=args.refresh_catalog)
        out = asdict(summary)
        out["failures"] = dict(list(out["failures"].items())[:20])
        print(json.dumps(out, indent=1))
        # exit 2 when the pull achieved nothing (every request failed): a rerun will not help
        return 2 if summary.failed and not summary.fetched and not summary.cached_before else 0
    summary = build(cache, term, args.out or Path("backfill") / term.sis_term_id, gap_min=args.gap_min)
    print(json.dumps(asdict(summary), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
