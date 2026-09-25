"""``live/latest.json`` on the data branch: the last observation of every section
of a course that is under pressure, for the site's live counts (docs/DESIGN_A6.md).

Written by ``scrape.yml`` after each snapshot, into the same commit, in a step
that can never fail the run. The site reads it from
``raw.githubusercontent.com/<owner>/<repo>/data/live/latest.json``. Compact by
design (one array per section, columns listed once) because it is rewritten
every 30 minutes on a branch that keeps every version.

    python -m scraper.live --data-root data-branch --term "Spring 2027" --out data-branch/live/latest.json

"Active" means the section is full or has a waitlist. The default selection is
every section of any course with at least one active section, so a discussion
with open seats appears next to the full ones: "which section has room" is the
question the site's board answers. ``--all`` keeps every section of every
course. The ``selection`` key names the rule the file was written under, and
``only_active`` stays for readers that exist, now always false because open
sections are included either way. Only this project's own snapshots feed it;
Berkeleytime's history never does.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from scraper.schema import TOMBSTONE_STATUS
from scraper.sources.base import TermSpec
from scraper.storage import DEFAULT_LOOKBACK_DAYS, carried_state

COLUMNS = ("section_id", "course_key", "subject", "catalog_number", "component", "section_number", "enrolled", "capacity", "waitlist", "waitlist_capacity", "reserved_count", "open_reserved", "status", "observed_at")

# The ``selection`` key: which sections the file holds, in plain words.
SELECTION_ACTIVE_COURSES = "courses_with_a_full_or_waitlisted_section"
SELECTION_ALL = "all_sections"


def _int(v: Any) -> int | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA:
        return None
    return int(v)


def is_active(enrolled: int | None, capacity: int | None, waitlist: int | None) -> bool:
    """Full, or someone waiting."""
    if waitlist is not None and waitlist > 0:
        return True
    return capacity is not None and enrolled is not None and capacity > 0 and enrolled >= capacity


def build_live(
    data_root: Path,
    term_id: str,
    *,
    term_name: str | None = None,
    now: datetime | None = None,
    only_active: bool = True,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """The file's contents: ``columns``, one ``rows`` entry per section (tombstones
    dropped), and how the file was built.

    ``only_active`` selects every section of a course that has at least one full
    or waitlisted section, so open sections of a course under pressure are kept;
    False keeps every section of every course (the CLI's ``--all``)."""
    now = now or datetime.now(timezone.utc)
    state = carried_state(data_root, term_id, now.date(), lookback_days=lookback_days)
    candidates: list[tuple[list[Any], str, bool]] = []
    if state is not None:
        for section_id, r in state.sort_index().iterrows():
            if r["status"] == TOMBSTONE_STATUS:
                continue
            enrolled, capacity = _int(r["enrolled_count"]), _int(r["enroll_capacity"])
            waitlist, wl_capacity = _int(r["waitlist_count"]), _int(r["waitlist_capacity"])
            reserved, open_reserved = _int(r["reserved_count"]), _int(r["open_reserved"])
            observed = r["fetched_at"]
            observed_iso = observed.isoformat(timespec="seconds") if hasattr(observed, "isoformat") else str(observed)
            row = [str(section_id), r["course_key"], r["subject"], r["catalog_number"], r["component"], r["section_number"], enrolled, capacity, waitlist, wl_capacity, reserved, open_reserved, r["status"], observed_iso]
            candidates.append((row, str(r["course_key"]), is_active(enrolled, capacity, waitlist)))
    if only_active:
        under_pressure = {key for _, key, active in candidates if active}
        rows = [row for row, key, _ in candidates if key in under_pressure]
    else:
        rows = [row for row, _, _ in candidates]
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "term_id": term_id,
        "term_name": term_name,
        # Kept for readers that exist; false either way now, because open
        # sections are written too. ``selection`` is the key that says what.
        "only_active": False,
        "selection": SELECTION_ACTIVE_COURSES if only_active else SELECTION_ALL,
        "n_sections": len(rows),
        "columns": list(COLUMNS),
        "rows": rows,
    }


def write_live(data_root: Path, out: Path, term_id: str, **kw: Any) -> dict[str, Any]:
    """Build and write atomically (tmp file + rename); returns the contents."""
    payload = build_live(data_root, term_id, **kw)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    return payload


def resolve_term_id(data_root: Path, term: str | None, term_id: str | None) -> str:
    """``--term-id`` if given, else the id the last run observed (status.json), else the name's SIS id."""
    if term_id:
        return term_id
    status = data_root / "status.json"
    if status.exists():
        try:
            found = json.loads(status.read_text(encoding="utf-8")).get("term_id")
            if found:
                return str(found)
        except (OSError, ValueError):
            pass
    if term:
        return TermSpec.from_name(term).sis_term_id
    raise SystemExit("give --term-id or --term, or a data root with status.json")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Write live/latest.json (last observation of every section of a course with a full or waitlisted section).")
    p.add_argument("--data-root", type=Path, default=Path("data-branch"))
    p.add_argument("--term", default=None, help='term name, e.g. "Spring 2027"')
    p.add_argument("--term-id", default=None)
    p.add_argument("--out", type=Path, default=None, help="default: <data-root>/live/latest.json")
    p.add_argument("--all", action="store_true", help="keep every section of every course, not only the courses with a full or waitlisted section")
    p.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    args = p.parse_args(argv)
    term_id = resolve_term_id(args.data_root, args.term, args.term_id)
    out = args.out or args.data_root / "live" / "latest.json"
    payload = write_live(args.data_root, out, term_id, term_name=args.term, only_active=not args.all, lookback_days=args.lookback_days)
    print(json.dumps({"out": str(out), "term_id": term_id, "n_sections": payload["n_sections"], "bytes": out.stat().st_size}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
