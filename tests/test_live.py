"""live/latest.json: the last observation of every section of a course that has a
full or waitlisted one (scraper/live.py)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scraper.live import COLUMNS, SELECTION_ACTIVE_COURSES, SELECTION_ALL, build_live, is_active, main, resolve_term_id, write_live
from scraper.schema import TOMBSTONE_STATUS, rows_to_table
from scraper.storage import RunMeta, compute_delta, latest_state, write_snapshot
from tests.conftest import make_row

TERM = "2272"
# Yesterday, so the CLI's default window (the last seven days up to now) covers the fixture.
T0 = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=7, minute=37, second=0, microsecond=0)


def seed(data_root: Path) -> None:
    """A baseline with five sections, then a delta that admits from one waitlist and tombstones another."""
    rows = [
        make_row(section_id="1", course_key="COMPSCI 61A", catalog_number="61A", enrolled_count=1600, enroll_capacity=1600, waitlist_count=120, waitlist_capacity=300),  # full, waitlist
        make_row(section_id="2", course_key="MATH 1A", subject="MATH", catalog_number="1A", enrolled_count=200, enroll_capacity=300, waitlist_count=0),  # open, no queue
        make_row(section_id="3", course_key="STAT 20", subject="STAT", catalog_number="20", enrolled_count=400, enroll_capacity=400, waitlist_count=0),  # full, no queue
        make_row(section_id="4", course_key="ART 8", subject="ART", catalog_number="8", enrolled_count=10, enroll_capacity=30, waitlist_count=3, waitlist_capacity=10),  # open with a queue
        make_row(section_id="5", course_key="COMPSCI 61A", catalog_number="61A", component="DIS", section_number="101", enrolled_count=20, enroll_capacity=30, waitlist_count=0, waitlist_capacity=10, reserved_count=8, open_reserved=4),  # open, same course as 1
    ]
    meta = RunMeta(run_started_at=T0, term_id=TERM, source="classes_site", kind="baseline", scope="full", complete=True, n_observed=len(rows))
    write_snapshot(data_root, rows_to_table(rows), meta)
    later = T0 + timedelta(minutes=30)
    prev = latest_state(data_root, TERM, later.date())
    observed = rows_to_table([
        make_row(section_id="1", course_key="COMPSCI 61A", catalog_number="61A", fetched_at=later, enrolled_count=1600, enroll_capacity=1600, waitlist_count=118, waitlist_capacity=300),
        make_row(section_id="2", course_key="MATH 1A", subject="MATH", catalog_number="1A", fetched_at=later, enrolled_count=201, enroll_capacity=300, waitlist_count=0),
        make_row(section_id="3", course_key="STAT 20", subject="STAT", catalog_number="20", fetched_at=later, enrolled_count=400, enroll_capacity=400, waitlist_count=0),
    ])
    delta = compute_delta(prev, observed, {"1", "2", "3"}, fetched_at=later, source="classes_site")
    gone = rows_to_table([make_row(section_id="4", course_key="ART 8", subject="ART", catalog_number="8", fetched_at=later, status=TOMBSTONE_STATUS)])  # 4 vanished
    import pyarrow as pa

    delta = pa.concat_tables([delta.replace_schema_metadata(None), gone])
    write_snapshot(data_root, delta, RunMeta(run_started_at=later, term_id=TERM, source="classes_site", kind="delta", scope="full", complete=True, n_observed=3))


def test_is_active() -> None:
    assert is_active(10, 30, 3) and is_active(400, 400, 0) and is_active(401, 400, 0)
    assert not is_active(200, 300, 0) and not is_active(None, None, None) and not is_active(0, 0, 0)


def test_build_live_keeps_the_latest_rows_of_the_courses_under_pressure(tmp_path: Path) -> None:
    seed(tmp_path)
    now = T0 + timedelta(hours=1)
    live = build_live(tmp_path, TERM, term_name="Spring 2027", now=now)
    assert live["columns"] == list(COLUMNS) and live["term_id"] == TERM and live["term_name"] == "Spring 2027"
    # The key readers already have, now false in both modes; ``selection`` says the rule.
    assert live["only_active"] is False and live["selection"] == SELECTION_ACTIVE_COURSES
    by_id = {r[0]: dict(zip(live["columns"], r)) for r in live["rows"]}
    # 5 rides in on 1's course, 2 is a course with no full or waitlisted section, 4 is a tombstone.
    assert set(by_id) == {"1", "3", "5"} and live["n_sections"] == 3
    cs = by_id["1"]
    assert cs["course_key"] == "COMPSCI 61A" and cs["enrolled"] == 1600 and cs["capacity"] == 1600 and cs["waitlist"] == 118 and cs["waitlist_capacity"] == 300
    assert cs["observed_at"] == (T0 + timedelta(minutes=30)).isoformat(timespec="seconds") and cs["status"] != TOMBSTONE_STATUS
    everything = build_live(tmp_path, TERM, now=now, only_active=False)
    assert {r[0] for r in everything["rows"]} == {"1", "2", "3", "5"} and everything["selection"] == SELECTION_ALL
    assert everything["only_active"] is False


def test_build_live_carries_the_reserved_columns(tmp_path: Path) -> None:
    """``reserved_count`` and ``open_reserved`` come through, nullable, in schema order."""
    seed(tmp_path)
    assert COLUMNS.index("reserved_count") == COLUMNS.index("waitlist_capacity") + 1
    assert COLUMNS.index("open_reserved") == COLUMNS.index("status") - 1
    live = build_live(tmp_path, TERM, now=T0 + timedelta(hours=1))
    by_id = {r[0]: dict(zip(live["columns"], r)) for r in live["rows"]}
    assert by_id["5"]["reserved_count"] == 8 and by_id["5"]["open_reserved"] == 4
    assert by_id["1"]["reserved_count"] is None and by_id["1"]["open_reserved"] is None  # the source had neither


def test_build_live_selection_keeps_the_open_sections_of_a_pressed_course(tmp_path: Path) -> None:
    """One full section pulls its course's open sections in; a course with none stays out."""
    seed(tmp_path)
    live = build_live(tmp_path, TERM, now=T0 + timedelta(hours=1))
    courses = {r[1] for r in live["rows"]}
    assert courses == {"COMPSCI 61A", "STAT 20"} and "MATH 1A" not in courses
    cs = sorted(r[0] for r in live["rows"] if r[1] == "COMPSCI 61A")
    assert cs == ["1", "5"]  # the full lecture and the discussion with room
    assert not is_active(20, 30, 0)  # 5 on its own would never have been written


def test_build_live_without_snapshots_is_empty(tmp_path: Path) -> None:
    live = build_live(tmp_path, TERM, now=T0)
    assert live["rows"] == [] and live["n_sections"] == 0


def test_write_live_is_compact_and_atomic(tmp_path: Path) -> None:
    seed(tmp_path)
    out = tmp_path / "live" / "latest.json"
    payload = write_live(tmp_path, out, TERM, now=T0 + timedelta(hours=1))
    text = out.read_text()
    assert json.loads(text) == payload and "\n " not in text and not (tmp_path / "live" / "latest.json.tmp").exists()
    assert "NaN" not in text


def test_resolve_term_id(tmp_path: Path) -> None:
    assert resolve_term_id(tmp_path, "Spring 2027", "2268") == "2268"
    assert resolve_term_id(tmp_path, "Spring 2027", None) == "2272"
    (tmp_path / "status.json").write_text(json.dumps({"term_id": "2268"}))
    assert resolve_term_id(tmp_path, "Spring 2027", None) == "2268"
    with pytest.raises(SystemExit):
        resolve_term_id(tmp_path / "nothing", None, None)


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    seed(tmp_path)
    assert main(["--data-root", str(tmp_path), "--term", "Spring 2027"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["out"] == str(tmp_path / "live" / "latest.json") and printed["term_id"] == TERM and printed["n_sections"] == 3
    written = json.loads((tmp_path / "live" / "latest.json").read_text())
    assert written["selection"] == SELECTION_ACTIVE_COURSES
    assert main(["--data-root", str(tmp_path), "--term", "Spring 2027", "--all"]) == 0
    assert json.loads(capsys.readouterr().out)["n_sections"] == 4  # --all still writes everything
    assert json.loads((tmp_path / "live" / "latest.json").read_text())["selection"] == SELECTION_ALL
