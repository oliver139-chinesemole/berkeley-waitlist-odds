"""Tests for analysis.panel: data-log parsing, censoring semantics, identity join."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


from analysis.panel import IDENTITY_COLUMNS, Outage, load_panel, parse_data_log, section_identity
from scraper.storage import RunMeta, write_snapshot
from scraper.schema import rows_to_table
from tests.conftest import make_row

LOG = """# Data log

## Entries

| start_utc | end_utc | kind | term_id | scope | note | who |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-18 | - | decision | - | all | not a censoring row | claude |
| 2026-09-19T02:46Z | - | outage | 2268 | all | schedule paused | claude |
| 2026-09-19T07:30Z | - | source_switch | 2268 | all | discovery changed | claude |
| 2026-09-19T08:01Z | - | correction | 2268 | all | Closes the outage row that starts 2026-09-19T02:46Z: end_utc is 2026-09-19T08:01Z, when the first run landed. | claude |
| 2026-10-04 | 2026-10-05 | term_switch | - | all | spring appears | oliver |
| bad-date | - | outage | 2268 | all | unparsable | claude |
"""


def test_parse_data_log(tmp_path: Path) -> None:
    path = tmp_path / "DATA_LOG.md"
    path.write_text(LOG)
    rows = parse_data_log(path)
    kinds = [(r.kind, r.start.isoformat(), r.end.isoformat() if r.end else None, r.term_id) for r in rows]
    assert kinds == [
        ("outage", "2026-09-19T02:46:00+00:00", "2026-09-19T08:01:00+00:00", "2268"),
        ("source_switch", "2026-09-19T07:30:00+00:00", None, "2268"),
        ("term_switch", "2026-10-04T00:00:00+00:00", "2026-10-05T00:00:00+00:00", None),
    ]


def test_overlaps_semantics() -> None:
    t = lambda h, m=0: datetime(2026, 9, 19, h, m, tzinfo=timezone.utc)  # noqa: E731
    span = Outage(start=t(2, 46), end=t(8, 1), kind="outage", term_id="2268", scope="all", note="")
    assert span.overlaps(t(2), t(3)) and span.overlaps(t(7), t(9)) and not span.overlaps(t(8, 1), t(9)) and not span.overlaps(t(1), t(2))
    assert not span.overlaps(t(2), t(3), term_id="2272") and span.overlaps(t(2), t(3), term_id="2268")
    open_outage = Outage(start=t(10), end=None, kind="outage", term_id=None, scope="all", note="")
    assert open_outage.overlaps(t(12), t(13)) and not open_outage.overlaps(t(8), t(9)) and open_outage.overlaps(t(9), t(11), term_id="2272")
    point = Outage(start=t(10), end=None, kind="source_switch", term_id=None, scope="all", note="")
    assert point.is_point_event and point.overlaps(t(9, 30), t(10, 30)) and not point.overlaps(t(10, 30), t(11)) and not point.overlaps(t(9), t(9, 59))


def test_section_identity_and_load_panel(tmp_path: Path) -> None:
    t0 = datetime(2026, 11, 1, 8, 7, tzinfo=timezone.utc)
    rows = [
        make_row(section_id="1", term_id="2268", course_key="COMPSCI 61A", subject="COMPSCI", catalog_number="61A", component="LEC", fetched_at=t0),
        make_row(section_id="2", term_id="2268", course_key="DATA C100", subject="DATA", catalog_number="C100", component="LEC", fetched_at=t0),
    ]
    meta = RunMeta(run_started_at=t0, term_id="2268", source="classes_site", kind="baseline", scope="full", n_observed=2, complete=True)
    write_snapshot(tmp_path, rows_to_table(rows), meta)
    ident = section_identity(tmp_path, "2268")
    assert list(ident["section_id"]) == ["1", "2"] and list(ident["course_key"]) == ["COMPSCI 61A", "DATA C100"]
    assert set(IDENTITY_COLUMNS) <= set(ident.columns)
    panel = load_panel(tmp_path, "2268")
    assert len(panel) == 2 and list(panel["course_key"]) == ["COMPSCI 61A", "DATA C100"]
    assert "observed" in panel.columns and panel["observed"].all()
    assert section_identity(tmp_path, "2272").empty
