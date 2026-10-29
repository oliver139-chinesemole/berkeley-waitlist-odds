"""The "Sections now" block on course.html, and the contract the A3 board must meet.

``tests/fixtures/latest_sample.json`` is ``live/latest.json`` as it looks now that
A3 has added ``reserved_count`` and ``open_reserved`` to ``scraper.live.COLUMNS``
and widened the selection to every section of a course that has a full or
waitlisted one. The harness serves it as the page's absolute ``LIVE_URL``
(``HARNESS_LIVE_FILE``) and pins ``Date.now()`` (``HARNESS_NOW``), so the per-row
ages are fixed numbers. Its ``term_id`` (2272, Spring 2027) is the forecast term
the test export counts down to, as on the real site once the scraper reads
Spring 2027; the page shows the board only for that term.

The first test pins what the page renders today, and the next one that a file for
another term renders no board. ``test_the_board_states_of_a3`` pins A3 (S1 to S3):
it was a strict xfail until A3 was built, and the marker came off with the board.
``test_cross_listed_sections_are_separate_rows`` pins S6: cross-listed partners
(DATA C8 and STAT C8, SIS ids 20817 and 20818 in the Fall 2026 catalog) are
separate rows, and each page shows only its own.

The source sentence's collection clause, and the Methods page's collection
sentence, follow the data branch's ``status.json`` the same way
(``HARNESS_STATUS_FILE``): "begins with Phase 1 on Oct 26, 2026" while the file is not read, or before that
day while the scraper reads its test term; "has not started" after it while the
scraper still reads its test term; "has started" once it reads the forecast term.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from analysis.calendar import SPRING_2027
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
    The pages count down to Spring 2027 (``forecast_term_id`` 2272, the fixture's term)
    from Berkeleytime history, as ``make site-data`` exports them today
    (``--forecast-term 2272``, ``data_source`` carried by ``--meta-from``).
    """
    root = tmp_path_factory.mktemp("site_live")
    cohort = synthetic_cohort().copy()
    renames = {"COMPSCI 0": "COMPSCI 61A", "MATH 1": "MATH 1A", "COMPSCI 4": "DATA C8", "STAT 2": "STAT C8"}
    keys = [renames.get(k, k) for k in cohort["course_key"].astype(str)]
    cohort["course_key"] = keys
    cohort["subject"] = [k.split(" ", 1)[0] for k in keys]
    cohort["catalog_number"] = [k.split(" ", 1)[1] for k in keys]
    export_site_tables(cohort, CAL, root / "data", n_boot=20, forecast_calendar=SPRING_2027, meta={"data_source": "berkeleytime_history"})
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


def board_age(out: dict) -> str:
    """The age in the board's first sentence, e.g. "about 3 min ago"."""
    m = re.search(r"This project's own snapshots of classes\.berkeley\.edu, as of (.+?) \(Spring 2027\)\.</p>", board(out))
    assert m, board(out)
    return m.group(1)


@pytest.mark.parametrize(
    ("run_minutes", "term_id", "age"),
    [
        (2, "2272", "about 2 min ago"),  # the last snapshot ran after the newest row: one age, the status line's
        (3, "2272", "about 3 min ago"),
        (12, "2272", "about 3 min ago"),  # the newest row is newer than the status file says: the board's own
        (2, "2268", "about 3 min ago"),  # a run of another term says nothing about these rows
        (None, None, "about 3 min ago"),  # no status file read
    ],
    ids=["status_newer", "same_minute", "rows_newer", "other_term", "no_status"],
)
def test_the_board_and_the_status_line_give_one_age(live_site: Path, tmp_path: Path, run_minutes: int | None, term_id: str | None, age: str) -> None:
    """Audit item 8: the status line (status.json) and the board (live/latest.json) said "37 min ago" and
    "as of 65 min ago" on one page. A row is rewritten only when its counts change, so the newest row can
    be older than the last snapshot that read it: the board takes the status line's age, to the minute,
    whenever that snapshot (of the board's term, with its sentence shown) is the newer one."""
    env = dict(LIVE_ENV)
    if run_minutes is not None:
        run = (datetime.fromisoformat(NOW) - timedelta(minutes=run_minutes)).isoformat()
        env["HARNESS_STATUS_FILE"] = str(status_for(tmp_path, term_id=term_id, last_run_at=run))
    out = render(live_site, page="course.html", search=SEARCH, env=env)
    assert board_age(out) == age
    if run_minutes is not None:
        assert f"ran about {run_minutes} min ago" in out["elements"]["status"]["html"]  # the line itself is unchanged
    out = render(live_site, page="course.html", search=SEARCH, env={**env, "HARNESS_STATUS_REJECT": "1"})
    assert board_age(out) == "about 3 min ago"  # a dropped status request leaves the board as it was


def test_a_live_file_for_another_term_shows_no_board(live_site: Path, tmp_path: Path) -> None:
    """Until the scraper switches, live/latest.json holds the test term (Fall 2026, 2268): no board under Spring 2027 curves."""
    meta = json.loads((live_site / "data" / "meta.json").read_text())
    live = json.loads(FIXTURE.read_text())
    assert live["term_id"] == meta["forecast_term_id"] == "2272"  # the fixture is the term the pages count down to
    live.update(term_id="2268", term_name="Fall 2026")
    fall = tmp_path / "latest_2268.json"
    fall.write_text(json.dumps(live))
    out = render(live_site, page="course.html", search=SEARCH, env={**LIVE_ENV, "HARNESS_LIVE_FILE": str(fall)})
    assert board(out) == ""  # no block, no heading, no rows
    page = " ".join(el["html"] for el in out["elements"].values())
    assert "Sections now" not in page and "Fall 2026" not in page and "min ago" not in page
    assert "COMPSCI 61A" in out["elements"]["course"]["html"]  # the rest of the page rendered as usual


def test_is_forecast_term(live_site: Path) -> None:
    """The rule both data-branch readers use: the file's term_id is meta.forecast_term_id, compared as text."""
    cases = [["2272", {"forecast_term_id": "2272"}, True], [2272, {"forecast_term_id": "2272"}, True], ["2268", {"forecast_term_id": "2272"}, False],
             [None, {"forecast_term_id": "2272"}, False], ["2272", {}, False], [None, {}, False], ["2272", None, False]]
    expression = "[" + ", ".join(f"BWO.isForecastTerm({json.dumps(t)}, {json.dumps(m)})" for t, m, _ in cases) + "]"
    out = render(live_site, page="course.html", search=SEARCH, expression=expression)
    assert "eval_error" not in out, out.get("eval_error")
    assert out["eval"] == [want for _, _, want in cases]


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


# 1.4: the source sentence (Berkeleytime history) says when this project's own
# collection begins, right above B2's status line from status.json, and the Methods
# page's Data section says it once more. Once that file names the forecast term
# the date would sit next to a Spring 2027 snapshot, so both lose it. The dated
# form is the fallback, so it is worded to stay true after Oct 26.
STATUS_FIXTURE = ROOT / "tests" / "fixtures" / "status_sample.json"
SOURCE_PAGES = {"index.html": "", "courses.html": "", "course.html": SEARCH, "dept.html": "?subject=COMPSCI", "insights.html": ""}
DATED = "Live Spring 2027 collection by this project begins with Phase 1 on Oct 26, 2026; the estimates switch to its own snapshots once Spring waitlists start clearing."
STARTED = "Live Spring 2027 collection by this project has started; the estimates switch to its own snapshots once Spring waitlists start clearing."
METHODS_DATED = "Collection for Spring 2027 begins with Phase 1 on Oct 26, 2026."
METHODS_STARTED = "Collection for Spring 2027 has started."
# Past Phase 1's start (NOW is Jan 10, 2027) with a run of an earlier term, the date goes: "has not started"
# next to "has not started collecting" (review of 2026-10-29, section 7); test_site.py pins the dated form before Oct 26.
UNSWITCHED = "Live Spring 2027 collection by this project has not started; the estimates switch to its own snapshots once Spring waitlists start clearing."
METHODS_UNSWITCHED = "Collection for Spring 2027 has not started."
# The status sentence for each file (audit item 7): a 2268 run says Spring 2027 collection has not started yet.
NOT_STARTED = "This project has not started collecting Spring 2027 yet; its last snapshot, of Fall 2026, ran about 12 min ago: 1,425 sections read, 1 not reached."
LAST_SPRING = "This project&#39;s last Spring 2027 snapshot ran about 12 min ago: 1,425 sections read, 1 not reached."
SENTENCE = {"2268": NOT_STARTED, "2272": LAST_SPRING}


def status_for(tmp_path: Path, **changes: object) -> Path:
    """The status fixture with the last run 12 minutes before the pinned now, and ``changes`` applied."""
    status = json.loads(STATUS_FIXTURE.read_text())
    status["last_run_at"] = (datetime.fromisoformat(NOW) - timedelta(minutes=12)).isoformat()
    status.update(changes)
    path = tmp_path / "status.json"
    path.write_text(json.dumps(status))
    return path


@pytest.mark.parametrize(
    ("term_id", "term_name", "clause"),
    [("2268", "Fall 2026", UNSWITCHED), ("2272", "Spring 2027", STARTED)],
    ids=["before_the_switch", "after_the_switch"],
)
@pytest.mark.parametrize("page", sorted(SOURCE_PAGES))
def test_the_source_sentence_follows_the_status_term(live_site: Path, tmp_path: Path, page: str, term_id: str, term_name: str, clause: str) -> None:
    out = render(live_site, page=page, search=SOURCE_PAGES[page], env={"HARNESS_STATUS_FILE": str(status_for(tmp_path, term_id=term_id)), "HARNESS_NOW": NOW})
    status = out["elements"]["status"]["html"]
    assert clause in status, status
    assert status.count("Live Spring 2027 collection") == 1
    assert SENTENCE[term_id] in status
    assert "starts" not in status  # the old "starts Oct 26, 2026" is gone in both forms
    if term_id == "2272":
        assert "Oct 26" not in status  # nothing dated next to a Spring 2027 snapshot


@pytest.mark.parametrize(
    ("term_id", "term_name", "sentence"),
    [("2268", "Fall 2026", METHODS_UNSWITCHED), ("2272", "Spring 2027", METHODS_STARTED)],
    ids=["before_the_switch", "after_the_switch"],
)
def test_the_methods_collection_sentence_follows_the_status_term(live_site: Path, tmp_path: Path, term_id: str, term_name: str, sentence: str) -> None:
    """The Data section's static sentence (``#collection``) under the Methods page's own status line."""
    out = render(live_site, page="methodology.html", env={"HARNESS_STATUS_FILE": str(status_for(tmp_path, term_id=term_id)), "HARNESS_NOW": NOW})
    assert out["elements"]["collection"]["html"] == sentence
    assert SENTENCE[term_id] in out["elements"]["data-status"]["html"]
    markup = (ROOT / "site" / "methodology.html").read_text()
    assert f'<span id="collection">{METHODS_DATED}</span>' in markup  # the dated form is what the page ships, for every reader
    assert "starts when Phase 1 opens" not in markup


def test_the_methods_span_matches_collection_dated_in_site_js() -> None:
    """Pins the swap's precondition: ``liveStatus()`` finds ``COLLECTION_DATED`` in the Methods
    span by a literal string replace (B2, site.js). It reads the live constant out of
    site.js itself, not a copy kept here, so an edit to one side without the other fails
    this test instead of silently breaking the swap once Spring 2027 collection starts.
    """
    js = (ROOT / "site" / "assets" / "site.js").read_text()
    m = re.search(r'const COLLECTION_DATED = "([^"]+)";', js)
    assert m, "COLLECTION_DATED not found in site.js"
    collection_dated = m.group(1)

    markup = (ROOT / "site" / "methodology.html").read_text()
    span = re.search(r'<span id="collection">([^<]+)</span>', markup)
    assert span, 'no <span id="collection"> in methodology.html'

    assert collection_dated in span.group(1), (
        f"COLLECTION_DATED {collection_dated!r} (site.js) is not in the Methods span "
        f"{span.group(1)!r} (methodology.html); liveStatus()'s replace() would stop matching."
    )


@pytest.mark.parametrize(("page", "search", "el", "dated"), [("course.html", SEARCH, "status", DATED), ("methodology.html", "", "collection", METHODS_DATED)], ids=["source", "methods"])
def test_a_status_file_that_is_not_read_keeps_the_dated_form(live_site: Path, tmp_path: Path, page: str, search: str, el: str, dated: str) -> None:
    """No status file, or a Spring 2027 one with no last_run_at (no status line): the dated form stays as the page printed it."""
    before = render(live_site, page=page, search=search)["elements"][el]["html"]
    assert dated in before
    status = status_for(tmp_path, term_id="2272")
    status.write_text(json.dumps({k: v for k, v in json.loads(status.read_text()).items() if k != "last_run_at"}))
    out = render(live_site, page=page, search=search, env={"HARNESS_STATUS_FILE": str(status), "HARNESS_NOW": NOW})
    assert out["elements"][el]["html"] == before


# The Lookup page sets its status line once; BWO.liveStatus then appends the status
# sentence and, for a forecast-term file, swaps the clause. A lookup used to rewrite
# the whole line to carry its "Showing X for query" note, so a form or chip search
# after status.json had arrived brought the dated form back and dropped the
# sentence, and so did a ?course= link whose match waits on a fetch (a title query,
# which loads titles.json; a course-code link resolves before status.json returns).
# The note has its own element now (#showing), right under the line.
TITLES = ROOT / "tests" / "fixtures" / "titles_sample.json"
LOOKUPS = {  # how -> (render arguments, extra environment, the #showing it leaves)
    "form": ({"course": "COMPSCI 61A", "position": "3"}, {}, ""),
    "fuzzy": ({"course": "compsi 61a", "position": "3"}, {}, '<p class="note">Showing <strong>COMPSCI 61A</strong> for <em>compsi 61a</em>.</p>'),
    "title_link": ({"search": "?course=structure%20and%20interpretation&position=3"}, {"HARNESS_TITLES_FILE": str(TITLES)},
                   '<p class="note">Showing <strong>COMPSCI 61A</strong> for <em>structure and interpretation</em>.</p>'),
}


@pytest.mark.parametrize(
    ("term_id", "term_name", "clause"),
    [("2268", "Fall 2026", UNSWITCHED), ("2272", "Spring 2027", STARTED)],
    ids=["before_the_switch", "after_the_switch"],
)
@pytest.mark.parametrize("how", sorted(LOOKUPS))
def test_a_lookup_keeps_the_status_line(live_site: Path, tmp_path: Path, how: str, term_id: str, term_name: str, clause: str) -> None:
    kwargs, extra, expected = LOOKUPS[how]
    out = render(live_site, **kwargs, env={"HARNESS_STATUS_FILE": str(status_for(tmp_path, term_id=term_id)), "HARNESS_NOW": NOW, **extra})
    assert "COMPSCI 61A · position 3" in out["result"], out["result"]  # the lookup ran
    status = out["elements"]["status"]["html"]
    assert clause in status and status.count("Live Spring 2027 collection") == 1, status
    assert status.count("live-status") == 1, status
    assert SENTENCE[term_id] in status, status
    if term_id == "2272":
        assert "Oct 26" not in status
    assert "Showing" not in status
    showing = out["elements"].get("showing", {"html": ""})["html"]
    assert showing == expected, showing
