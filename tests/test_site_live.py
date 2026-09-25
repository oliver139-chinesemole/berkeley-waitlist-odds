"""The "Sections now" block on course.html, and the contract the A3 board must meet.

``tests/fixtures/latest_sample.json`` is ``live/latest.json`` as it looks now that
A3 has added ``reserved_count`` and ``open_reserved`` to ``scraper.live.COLUMNS``
and widened the selection to every section of a course that has a full or
waitlisted one. The harness serves it as the page's absolute ``LIVE_URL``
(``HARNESS_LIVE_FILE``) and pins ``Date.now()`` (``HARNESS_NOW``), so the per-row
ages are fixed numbers.

The first test pins what the page renders today. The second pins A3 (S1 to S3):
it was a strict xfail until A3 was built, and the marker came off with the board.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from analysis.export import export_site_tables
from tests.test_site import CAL, NODE, render
from tests.test_survival import synthetic_cohort

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "latest_sample.json"
NOW = "2027-01-10T12:00:00+00:00"  # the fixture's generated_at; its date is tests.test_site.TODAY
LIVE_ENV = {"HARNESS_LIVE_FILE": str(FIXTURE), "HARNESS_NOW": NOW}
SEARCH = "?c=COMPSCI+61A&position=3"
# The course's own sections in the fixture, with the ratios the page prints from them.
SECTIONS = (("LEC 001", "20 / 30", "0 / 10"), ("DIS 101", "30 / 30", "5 / 10"), ("DIS 102", "30 / 30", "0 / 0"), ("DIS 103", "26 / 30", "0 / 10"), ("DIS 104", "28 / 30", "0 / 10"), ("DIS 105", "26 / 30", "0 / 10"))


@pytest.fixture(scope="module")
def live_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The synthetic export, with two courses renamed to the keys the live fixture uses."""
    root = tmp_path_factory.mktemp("site_live")
    cohort = synthetic_cohort().copy()
    renames = {"COMPSCI 0": "COMPSCI 61A", "MATH 1": "MATH 1A"}
    keys = [renames.get(k, k) for k in cohort["course_key"].astype(str)]
    cohort["course_key"] = keys
    cohort["catalog_number"] = [k.split(" ", 1)[1] for k in keys]
    export_site_tables(cohort, CAL, root / "data", n_boot=20)
    return root


def board(out: dict) -> str:
    """The live block's HTML ("" when the page never rendered it)."""
    return out["elements"].get("live", {"html": ""})["html"]


def row_of(html: str, label: str) -> str:
    """The one table row that names this section, e.g. "DIS 103"."""
    found = [chunk for chunk in html.split("<tr")[1:] if label in chunk]
    assert len(found) == 1, f"{label}: {len(found)} rows in {html}"
    return found[0]


def test_the_block_renders_only_this_courses_sections(live_site: Path) -> None:
    out = render(live_site, page="course.html", search=SEARCH, env=LIVE_ENV)
    html = board(out)
    assert "Sections now" in html and "Spring 2027" in html
    body = html.split("<tbody>")[1]
    assert body.count("<tr") == len(SECTIONS)  # one row each, and none of MATH 1A's two
    assert "MATH" not in html
    for label, enrolled, waitlist in SECTIONS:
        row = row_of(body, label)
        assert enrolled in row and waitlist in row, label
    assert "3 min ago" in html  # the newest row's age, against the pinned clock
    # render passes the shell's environment through, so this one fails if you export
    # HARNESS_LIVE_FILE yourself; unset it rather than weakening the assertion.
    without = render(live_site, page="course.html", search=SEARCH)
    assert board(without) == ""  # no live file, no block, no error


def test_the_board_states_of_a3(live_site: Path) -> None:
    """S1 seats open per row, S2 the reserved line in the registrar's wording, S3 the stale warning."""
    out = render(live_site, page="course.html", search=SEARCH, env=LIVE_ENV)
    html = board(out)

    open_row = row_of(html, "LEC 001")  # 20 of 30, nothing reserved
    assert "10 seats open, anyone can take them" in open_row and "read 12 min ago" in open_row and "status-open" in open_row

    waitlist_row = row_of(html, "DIS 101")  # 30 of 30 with 5 of 10 waiting
    assert "0 seats open" in waitlist_row and "5 / 10" in waitlist_row and "read 7 min ago" in waitlist_row and "status-waitlist" in waitlist_row

    full_row = row_of(html, "DIS 102")  # 30 of 30, no waitlist at all
    assert "0 seats open" in full_row and "read 3 min ago" in full_row and "status-full" in full_row

    reserved_row = row_of(html, "DIS 103")  # 26 of 30, all four open seats reserved
    assert "4 seats open, all reserved" in reserved_row and "read 5 min ago" in reserved_row and "status-reserved" in reserved_row

    partly_reserved_row = row_of(html, "DIS 105")  # 26 of 30, two of the four open seats reserved
    assert "4 seats open, 2 of them reserved" in partly_reserved_row and "read 4 min ago" in partly_reserved_row and "status-open" in partly_reserved_row

    stale_row = row_of(html, "DIS 104")  # 28 of 30, read seven hours before the pinned now
    assert "2 seats open, anyone can take them" in stale_row and "status-open" in stale_row
    assert "read 420 min ago" in stale_row or "read 7 hours ago" in stale_row
    assert re.search(r'class="[^"]*(warn|stale)', stale_row) and "hours" in stale_row  # S3

    assert not re.search(r"\b(red|green)\b", html, re.I)  # the ramp is blue, never a traffic light
    for claim in ("your position", "you are", "your spot"):
        assert claim not in html.lower()  # the block never claims to know a student's own position
