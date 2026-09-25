"""The "Sections now" block on course.html, and the contract the A3 board must meet.

``tests/fixtures/latest_sample.json`` is ``live/latest.json`` as it looks now that
A3 has added ``reserved_count`` and ``open_reserved`` to ``scraper.live.COLUMNS``
and widened the selection to every section of a course that has a full or
waitlisted one. The harness serves it as the page's absolute ``LIVE_URL``
(``HARNESS_LIVE_FILE``) and pins ``Date.now()`` (``HARNESS_NOW``), so the per-row
ages are fixed numbers.

The first test pins what the page renders today. The second pins A3 (S1 to S3):
it was a strict xfail until A3 was built, and the marker came off with the board.
The last pins S6: cross-listed partners (DATA C8 and STAT C8, SIS ids 20817 and
20818 in the Fall 2026 catalog) are separate rows, and each page shows only its own.
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
SECTIONS = (("LEC 001", "20 / 30", "0 / 10"), ("DIS 101", "30 / 30", "5 / 10"), ("DIS 102", "30 / 30", "0 / 0"), ("DIS 103", "26 / 30", "0 / 10"), ("DIS 104", "28 / 30", "0 / 10"), ("DIS 105", "26 / 30", "0 / 10"),
            ("DIS 106", "— / 30", "0 / 10"), ("DIS 107", "25 / —", "0 / 10"), ("DIS 108", "25 / 30", "— / 10"), ("DIS 109", "— / —", "— / 10"))
# The sections with a missing count: one of enrolled, capacity and waitlist null in
# each of the first three (the published names of the snapshot's enrolled_count,
# enroll_capacity and waitlist_count), all three null in the last, with their ages.
UNREAD = (("DIS 106", "read 10 min ago"), ("DIS 107", "read 9 min ago"), ("DIS 108", "read 8 min ago"), ("DIS 109", "read 6 min ago"))
STATUS_CLASSES = ("status-open", "status-waitlist", "status-full", "status-reserved")


@pytest.fixture(scope="module")
def live_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The synthetic export, with four courses renamed to the keys the live fixture uses.

    DATA C8 and STAT C8 are a cross-listed pair; the subject is taken from the new key
    too, so DATA C8 (renamed from COMPSCI 4) sits under DATA as it does in the catalog.
    """
    root = tmp_path_factory.mktemp("site_live")
    cohort = synthetic_cohort().copy()
    renames = {"COMPSCI 0": "COMPSCI 61A", "MATH 1": "MATH 1A", "COMPSCI 4": "DATA C8", "STAT 2": "STAT C8"}
    keys = [renames.get(k, k) for k in cohort["course_key"].astype(str)]
    cohort["course_key"] = keys
    cohort["subject"] = [k.split(" ", 1)[0] for k in keys]
    cohort["catalog_number"] = [k.split(" ", 1)[1] for k in keys]
    export_site_tables(cohort, CAL, root / "data", n_boot=20)
    return root


def cells(row: str) -> list[str]:
    """A row's cells, each as its opening tag's attributes and its content, e.g. ' class="num">20 / 30'."""
    return [chunk.split("</td>")[0] for chunk in row.split("<td")[1:]]


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


def test_a_row_with_a_missing_count_is_not_read(live_site: Path) -> None:
    """Any null among enrolled, capacity and waitlist: the status is an em dash with no ramp class, never "open"."""
    out = render(live_site, page="course.html", search=SEARCH, env=LIVE_ENV)
    html = board(out)
    for label, read in UNREAD:
        row = row_of(html, label)
        section, enrolled, waitlist, seats, status, age = cells(row)
        assert status == ' aria-label="not read">—', f"{label}: {status}"
        assert not any(cls in row for cls in STATUS_CLASSES), label
        assert seats == ">—", f"{label}: {seats}"  # the seats cell, not a zero and not a count
        assert read in age, label  # every row still says how long ago it was read
    for label, _, _ in SECTIONS:
        if label not in dict(UNREAD):
            assert "not read" not in row_of(html, label), label  # the rows with every count keep their word


def test_the_board_table_carries_the_phone_rows_class(live_site: Path) -> None:
    """Below 38 rem the board's rows break into two lines; the rule targets the board's own table class."""
    out = render(live_site, page="course.html", search=SEARCH, env=LIVE_ENV)
    html = board(out)
    assert re.search(r'<table class="board"[^>]*aria-label="Sections now"', html)
    css = (ROOT / "site" / "assets" / "site.css").read_text()
    rule = re.search(r"@media \(width < 38rem\) \{(.*?)\n\}", css, re.S)
    assert rule, "no phone-row rule for the board"
    body = rule.group(1)
    selectors = re.findall(r"^\s*([^{}]+?)\s*\{", body, re.M)
    assert selectors and all(s.startswith("table.board") for part in selectors for s in (x.strip() for x in part.split(","))), selectors
    assert "tabular-nums lining-nums" in body  # figures stay aligned on the second line
    assert not re.search(r"(?<!-)color\s*:|background", body)  # no colour change


# S6: a cross-listed pair, one row each in the fixture, with the ratios the page prints.
CROSSLISTED = {
    "DATA C8": ("400 / 400", "25 / 50", "read 2 min ago"),  # section_id 20817
    "STAT C8": ("380 / 400", "12 / 50", "read 11 min ago"),  # section_id 20818
}
# What a merged row would print: the two sections' counts summed.
MERGED = ("780 / 800", "37 / 100", "780", "37")


@pytest.mark.parametrize("key", sorted(CROSSLISTED))
def test_cross_listed_sections_are_separate_rows(live_site: Path, key: str) -> None:
    """Each partner's page shows exactly its own row with its own counts; the pair is never merged."""
    (partner,) = set(CROSSLISTED) - {key}
    out = render(live_site, page="course.html", search="?c=" + key.replace(" ", "+"), env=LIVE_ENV)
    html = board(out)
    assert "Sections now" in html, key
    body = html.split("<tbody>")[1]
    assert body.count("<tr") == 1, body  # one row, not the partner's as well
    section, enrolled, waitlist, seats, status, age = cells(row_of(body, "LEC 001"))
    own_enrolled, own_waitlist, own_age = CROSSLISTED[key]
    assert enrolled == f' class="num">{own_enrolled}' and waitlist == f' class="num">{own_waitlist}', (enrolled, waitlist)
    assert own_age in age
    other_enrolled, other_waitlist, other_age = CROSSLISTED[partner]
    for text in (other_enrolled, other_waitlist, other_age, partner):
        assert text not in html, f"{key} shows {partner}'s {text!r}"
    page = " ".join(el["html"] for el in out["elements"].values())
    for text in MERGED[:2]:
        assert text not in page, f"{key}: a merged count {text!r} on the page"
    for text in MERGED[2:]:
        assert not re.search(rf"(?<![\d.]){text}(?![\d.])", html), f"{key}: a merged count {text!r} in the board"
