"""Offline tests for scraper.sources.classes_site against the saved fixtures."""
from __future__ import annotations

import email.message
import json
import logging
import math
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scraper.http import HttpClient, HttpError
from scraper.schema import rows_to_table
from scraper.sources.base import ParseError, PrioritySpec, TermNotPublished, TermSpec, shard_of
from scraper.sources.classes_site import (
    ClassesSiteSource,
    SectionRef,
    find_term_facet_id,
    parse_listing_page,
    parse_section_page,
    parse_term_facets,
)

FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"
SECTION_FIXTURE = FIXTURES / "classes_section_2026-fall-aeroeng-10-001-lec-001.html"
LISTING_FIXTURE = FIXTURES / "classes_listing_fall2026_page0_trimmed.html"

BASE = "https://classes.test"
FALL_2026 = TermSpec.from_name("Fall 2026")
FETCHED_AT = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)

AEROENG_10_REF = SectionRef(
    section_id="30174",
    url_path="/content/2026-fall-aeroeng-10-001-lec-001",
    course_key="AEROENG 10",
    subject="AEROENG",
    catalog_number="10",
    class_number="001",
    section_number="001",
    component="LEC",
)

# The trimmed listing fixture lost the term facet block, so discovery is
# exercised on a minimal page shaped like the live facet list.
FACET_HTML = b"""
<html><body>
<ul class="facets">
  <li><a href="/search/class?f%5B0%5D=term%3A8588" rel="nofollow"><span>Fall 2026 (6131)</span></a></li>
  <li><a href="/search/class?f[0]=term:8400"><span>Summer 2026 (2000)</span></a></li>
</ul>
<nav><a href="?f%5B0%5D=term%3A8588&amp;page=1" title="Go to next page">Next page</a></nav>
</body></html>
"""

EMPTY_LISTING = b"<html><body><div class='view-content'></div></body></html>"


def section_page(section_id: int, term_id: str | None = "2268", **status: object) -> bytes:
    """A minimal section page with the same drupal settings shape as the live site."""
    enrollment = {
        "status": {"code": "W", "description": "Wait List"},
        "enrolledCount": 100,
        "reservedCount": None,
        "waitlistedCount": 12,
        "minEnroll": 0,
        "maxEnroll": 100,
        "maxWaitlist": 20,
        "openReserved": None,
    }
    enrollment.update(status)
    settings = {
        "path": {"baseUrl": "/"},
        "ucb": {
            "enrollment": {"available": {"id": section_id, "enrollmentStatus": enrollment}},
            "termDetails": {"sessionDescription": "2026 Fall"},
        },
    }
    term_attr = f' data-term="{term_id}" data-term-name="Fall 2026"' if term_id is not None else ""
    return (
        "<html><head><meta charset='utf-8'></head><body>"
        f"<div data-element='textbook'{term_attr} data-section-id='{section_id}'></div>"
        '<script type="application/json" data-drupal-selector="drupal-settings-json">'
        f"{json.dumps(settings)}</script></body></html>"
    ).encode("utf-8")


# -- fakes --------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self.t

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.t += seconds


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.headers: dict[str, str] = {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


def http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, f"status {code}", email.message.Message(), None)


class FakeOpener:
    """URL -> queue of FakeResponse or exception; the last outcome repeats."""

    def __init__(self, routes: dict[str, list]) -> None:
        self.routes = {url: list(queue) for url, queue in routes.items()}
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def open(self, request: urllib.request.Request, timeout: float | None = None) -> FakeResponse:
        url = request.full_url
        with self._lock:
            self.calls.append(url)
            queue = self.routes.get(url)
            if not queue:
                raise AssertionError(f"unexpected url {url}")
            outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class StubClient:
    """Implements the HttpClient surface the source uses, without threads.

    ``pages`` maps url -> bytes or HttpError. ``get_many`` attempts at most
    ``attempt_limit`` urls and reports the rest as budget exhausted.
    """

    def __init__(self, pages: dict[str, bytes | HttpError], attempt_limit: int | None = None) -> None:
        self.pages = pages
        self.attempt_limit = attempt_limit
        self.get_calls: list[str] = []
        self.get_many_calls: list[tuple[list[str], float | None]] = []

    def get(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        self.get_calls.append(url)
        payload = self.pages.get(url, HttpError(404, url, "not routed"))
        if isinstance(payload, HttpError):
            raise payload
        return payload

    def get_many(self, urls: list[str], on_result, time_budget_s: float | None = None) -> None:
        self.get_many_calls.append((list(urls), time_budget_s))
        for i, url in enumerate(urls):
            if self.attempt_limit is not None and i >= self.attempt_limit:
                on_result(url, HttpError(0, url, "budget exhausted"))
                continue
            payload = self.pages.get(url, HttpError(404, url, "not routed"))
            on_result(url, payload)


def listing_url(page: int, facet_id: str = "8588") -> str:
    return f"{BASE}/search/class?f%5B0%5D=term%3A{facet_id}&page={page}"


def standard_pages(section_pages: dict[str, bytes | HttpError]) -> dict[str, bytes | HttpError]:
    pages: dict[str, bytes | HttpError] = {
        f"{BASE}/search/class": FACET_HTML,
        listing_url(0): LISTING_FIXTURE.read_bytes(),
        listing_url(1): EMPTY_LISTING,
    }
    pages.update(section_pages)
    return pages


# -- parsing ------------------------------------------------------------------


def test_parse_section_page_real_fixture() -> None:
    row = parse_section_page(SECTION_FIXTURE.read_bytes(), AEROENG_10_REF, FETCHED_AT, FALL_2026)
    assert row["section_id"] == "30174"
    assert row["term_id"] == "2268"
    assert row["enrolled_count"] == 60
    assert row["enroll_capacity"] == 64
    assert row["waitlist_count"] == 0
    assert row["waitlist_capacity"] == 15
    assert row["reserved_count"] == 60
    assert row["open_reserved"] == 0
    assert row["status"] == "O"
    assert row["section_status"] is None
    assert row["is_primary"] is None
    assert row["session_id"] == "1"
    assert row["source"] == "classes_site"
    assert row["course_key"] == "AEROENG 10"
    assert row["subject"] == "AEROENG"
    assert row["catalog_number"] == "10"
    assert row["class_number"] == "001"
    assert row["section_number"] == "001"
    assert row["component"] == "LEC"
    assert row["fetched_at"] == FETCHED_AT
    table = rows_to_table([row])
    assert table.num_rows == 1


def test_parse_section_page_is_reachable_on_the_class() -> None:
    row = ClassesSiteSource.parse_section_page(SECTION_FIXTURE.read_bytes(), AEROENG_10_REF, FETCHED_AT, FALL_2026)
    assert row["section_id"] == "30174"


def test_parse_section_page_term_mismatch_uses_page_value(caplog: pytest.LogCaptureFixture) -> None:
    spring = TermSpec.from_name("Spring 2027")
    with caplog.at_level(logging.WARNING, logger="scraper.sources.classes_site"):
        row = parse_section_page(SECTION_FIXTURE.read_bytes(), AEROENG_10_REF, FETCHED_AT, spring)
    assert row["term_id"] == "2268"
    assert any("data-term=2268" in rec.getMessage() and "2272" in rec.getMessage() for rec in caplog.records)


def test_parse_section_page_without_data_term_falls_back() -> None:
    ref = SectionRef("30013", "/content/x", "AEROENG 1", "AEROENG", "1", "001", "001", "SEM")
    row = parse_section_page(section_page(30013, term_id=None), ref, FETCHED_AT, FALL_2026)
    assert row["term_id"] == FALL_2026.sis_term_id
    assert row["status"] == "W"
    assert row["reserved_count"] is None
    assert row["open_reserved"] is None


def test_parse_section_page_naive_fetched_at_becomes_utc() -> None:
    row = parse_section_page(SECTION_FIXTURE.read_bytes(), AEROENG_10_REF, FETCHED_AT.replace(tzinfo=None), FALL_2026)
    assert row["fetched_at"].tzinfo is not None
    assert row["fetched_at"] == FETCHED_AT


def test_parse_section_page_id_mismatch() -> None:
    wrong = SectionRef("99999", "/content/x", "AEROENG 10", "AEROENG", "10", "001", "001", "LEC")
    with pytest.raises(ParseError, match="30174"):
        parse_section_page(SECTION_FIXTURE.read_bytes(), wrong, FETCHED_AT, FALL_2026)


def test_parse_section_page_without_blob() -> None:
    with pytest.raises(ParseError, match="drupal-settings-json"):
        parse_section_page(b"<html><body><p>maintenance</p></body></html>", AEROENG_10_REF, FETCHED_AT, FALL_2026)


def test_parse_section_page_missing_keys() -> None:
    broken = (
        b'<html><body><script data-drupal-selector="drupal-settings-json">'
        b'{"ucb": {"enrollment": {"available": {"id": 30174}}}}</script></body></html>'
    )
    with pytest.raises(ParseError, match="enrollmentStatus"):
        parse_section_page(broken, AEROENG_10_REF, FETCHED_AT, FALL_2026)


def test_parse_listing_fixture() -> None:
    refs = parse_listing_page(LISTING_FIXTURE.read_bytes())
    assert len(refs) == 3
    assert [r.section_id for r in refs] == ["30013", "30174", "30590"]
    aeroeng_10 = refs[1]
    assert aeroeng_10 == AEROENG_10_REF
    assert refs[0].course_key == "AEROENG 1" and refs[0].component == "SEM"
    assert refs[2].course_key == "AEROENG 100" and refs[2].url_path == "/content/2026-fall-aeroeng-100-001-lec-001"


def test_parse_listing_subject_spaces_and_bad_rows(caplog: pytest.LogCaptureFixture) -> None:
    html = b"""
    <div class="views-row"><article>
      <div class="st--section-number">#12345</div>
      <a href="/content/2026-fall-el-eng-16a-001-lec-001">
        <span class="st--section-name">EL ENG 16A</span>
        <span class="st--section-count">001</span> -
        <span class="st--section-code">LEC</span>
        <span class="st--section-count">002</span>
      </a></article></div>
    <div class="views-row"><article><div class="st--section-number">#1</div></article></div>
    """
    with caplog.at_level(logging.WARNING, logger="scraper.sources.classes_site"):
        refs = parse_listing_page(html)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.course_key == "ELENG 16A"  # subject spaces stripped, as the live site spells it
    assert ref.subject == "ELENG"
    assert ref.catalog_number == "16A"
    assert ref.class_number == "001" and ref.section_number == "002"
    assert any("skipping listing row" in rec.getMessage() for rec in caplog.records)


def test_parse_listing_all_rows_broken_raises() -> None:
    with pytest.raises(ParseError):
        parse_listing_page(b"<div class='views-row'><article></article></div>")


def test_parse_listing_empty_page() -> None:
    assert parse_listing_page(EMPTY_LISTING) == []


def test_term_facets() -> None:
    assert parse_term_facets(FACET_HTML) == [
        ("Fall 2026 (6131)", "8588"),
        ("Summer 2026 (2000)", "8400"),
        ("Next page", "8588"),
    ]
    assert find_term_facet_id(FACET_HTML, "Fall 2026") == "8588"
    assert find_term_facet_id(FACET_HTML, "Summer 2026") == "8400"
    assert find_term_facet_id(FACET_HTML, "Fall 202") is None
    assert find_term_facet_id(FACET_HTML, "Spring 2031") is None


# -- source: discovery and listing --------------------------------------------


def test_discover_term_facet_id(tmp_path: Path) -> None:
    client = StubClient({f"{BASE}/search/class": FACET_HTML})
    source = ClassesSiteSource(client, tmp_path, base_url=BASE)
    assert source.discover_term_facet_id("Fall 2026") == "8588"
    with pytest.raises(TermNotPublished):
        source.discover_term_facet_id("Spring 2031")


def test_discover_ignores_pager_links_in_trimmed_fixture(tmp_path: Path) -> None:
    # The trimmed listing has only pager anchors with term%3A8588 hrefs and no term text.
    client = StubClient({f"{BASE}/search/class": LISTING_FIXTURE.read_bytes()})
    source = ClassesSiteSource(client, tmp_path, base_url=BASE)
    with pytest.raises(TermNotPublished):
        source.discover_term_facet_id("Fall 2026")


def test_list_sections_paginates_and_caches(tmp_path: Path) -> None:
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    client = StubClient(standard_pages({}))
    source = ClassesSiteSource(client, tmp_path, base_url=BASE, now=lambda: now)

    refs = source.list_sections("8588", term_id="2268")
    assert [r.section_id for r in refs] == ["30013", "30174", "30590"]
    assert client.get_calls == [listing_url(0), listing_url(1)]

    catalog = tmp_path / "catalog" / "2268" / "sections.json"
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    assert set(payload) == {"term_id", "facet_id", "listed_at", "sections"}
    assert payload["term_id"] == "2268" and payload["facet_id"] == "8588"
    assert payload["listed_at"] == now.isoformat()
    assert payload["sections"][1]["section_id"] == "30174"

    # Fresh cache: no listing request.
    again = source.list_sections("8588", term_id="2268")
    assert again == refs
    assert len(client.get_calls) == 2

    # Limited run against the short cache: 3 < 18 rows, so one page is refetched
    # and the partial result is not written back.
    assert source.list_sections("8588", max_pages=1, term_id="2268") == refs
    assert client.get_calls[2:] == [listing_url(0)]
    assert json.loads(catalog.read_text(encoding="utf-8"))["sections"] == payload["sections"]

    # A cache long enough for the requested pages is reused; too short is refetched.
    long_refs = [
        SectionRef(str(40000 + i), f"/content/s{i}", "COMPSCI 61A", "COMPSCI", "61A", "001", f"{i:03d}", "DIS")
        for i in range(40)
    ]
    catalog.write_text(
        json.dumps(
            {
                "term_id": "2268",
                "facet_id": "8588",
                "listed_at": now.isoformat(),
                "sections": [r.to_dict() for r in long_refs],
            }
        ),
        encoding="utf-8",
    )
    assert source.list_sections("8588", max_pages=2, term_id="2268") == long_refs  # 40 >= 36
    assert len(client.get_calls) == 3
    assert source.list_sections("8588", max_pages=3, term_id="2268") == refs  # 40 < 54: refetch
    assert client.get_calls[3:] == [listing_url(0), listing_url(1)]

    # Stale cache: refetched and rewritten.
    stale = ClassesSiteSource(client, tmp_path, base_url=BASE, now=lambda: now + timedelta(hours=25))
    assert stale.list_sections("8588", term_id="2268") == refs
    assert client.get_calls[5:] == [listing_url(0), listing_url(1)]
    assert len(json.loads(catalog.read_text(encoding="utf-8"))["sections"]) == 3


def test_list_sections_partial_listing_not_cached(tmp_path: Path) -> None:
    client = StubClient(standard_pages({}))
    source = ClassesSiteSource(client, tmp_path, base_url=BASE)
    refs = source.list_sections("8588", max_pages=1, term_id="2268")
    assert len(refs) == 3
    assert client.get_calls == [listing_url(0)]
    assert not (tmp_path / "catalog").exists()


def test_list_sections_stops_on_404_after_first_page(tmp_path: Path) -> None:
    pages = standard_pages({})
    pages[listing_url(1)] = HttpError(404, listing_url(1))
    source = ClassesSiteSource(StubClient(pages), tmp_path, base_url=BASE)
    assert len(source.list_sections("8588")) == 3


def test_list_sections_propagates_first_page_error(tmp_path: Path) -> None:
    pages = standard_pages({})
    pages[listing_url(0)] = HttpError(503, listing_url(0))
    source = ClassesSiteSource(StubClient(pages), tmp_path, base_url=BASE)
    with pytest.raises(HttpError):
        source.list_sections("8588")


# -- source: fetch --------------------------------------------------------------


def test_fetch_with_real_http_client_retry_and_404(tmp_path: Path) -> None:
    clock = FakeClock()
    url_30013 = f"{BASE}/content/2026-fall-aeroeng-1-001-sem-001"
    url_30174 = f"{BASE}/content/2026-fall-aeroeng-10-001-lec-001"
    url_30590 = f"{BASE}/content/2026-fall-aeroeng-100-001-lec-001"
    opener = FakeOpener(
        {
            f"{BASE}/search/class": [FakeResponse(FACET_HTML)],
            listing_url(0): [FakeResponse(LISTING_FIXTURE.read_bytes())],
            listing_url(1): [FakeResponse(EMPTY_LISTING)],
            url_30013: [FakeResponse(section_page(30013, enrolledCount=7, maxEnroll=7, status={"code": "C"}))],
            url_30174: [http_error(url_30174, 500), FakeResponse(SECTION_FIXTURE.read_bytes())],
            url_30590: [http_error(url_30590, 404)],
        }
    )
    client = HttpClient(
        "test-agent/0",
        min_interval_s=1.0,
        max_concurrency=1,
        retries=3,
        sleep=clock.sleep,
        clock=clock.now,
        opener=opener,
        rng=lambda: 0.0,
    )
    fetched = datetime(2026, 9, 18, 21, 30, tzinfo=timezone.utc)
    source = ClassesSiteSource(client, tmp_path, base_url=BASE, now=lambda: fetched)

    result = source.fetch(FALL_2026)

    assert result.scope == "full"
    assert result.shard == "" and result.priority_sha == ""
    assert result.universe_ids == {"30013", "30174", "30590"}
    assert result.missing_ids == ["30590"]
    assert result.observed_ids == ["30013", "30174"]
    by_id = {row["section_id"]: row for row in result.rows}
    assert by_id["30174"]["enrolled_count"] == 60 and by_id["30174"]["term_id"] == "2268"
    assert by_id["30013"]["enrolled_count"] == 7 and by_id["30013"]["status"] == "C"
    assert all(row["fetched_at"] == fetched for row in result.rows)
    assert opener.calls.count(url_30174) == 2  # 500 then 200
    assert opener.calls.count(url_30590) == 1  # 404 never retried
    assert rows_to_table(result.rows).num_rows == 2
    assert (tmp_path / "catalog" / "2268" / "sections.json").exists()


def test_fetch_parse_error_goes_to_missing(tmp_path: Path) -> None:
    pages = standard_pages(
        {
            f"{BASE}/content/2026-fall-aeroeng-1-001-sem-001": section_page(30013),
            f"{BASE}/content/2026-fall-aeroeng-10-001-lec-001": section_page(11111),  # wrong id
            f"{BASE}/content/2026-fall-aeroeng-100-001-lec-001": b"<html><body>no blob</body></html>",
        }
    )
    source = ClassesSiteSource(StubClient(pages), tmp_path, base_url=BASE)
    result = source.fetch(FALL_2026)
    assert result.observed_ids == ["30013"]
    assert result.missing_ids == ["30174", "30590"]


def test_fetch_time_budget_cutoff(tmp_path: Path) -> None:
    pages = standard_pages(
        {
            f"{BASE}/content/2026-fall-aeroeng-1-001-sem-001": section_page(30013),
            f"{BASE}/content/2026-fall-aeroeng-10-001-lec-001": section_page(30174),
            f"{BASE}/content/2026-fall-aeroeng-100-001-lec-001": section_page(30590),
        }
    )
    client = StubClient(pages, attempt_limit=1)
    fake = FakeClock()
    source = ClassesSiteSource(client, tmp_path, base_url=BASE, clock=fake.now)
    result = source.fetch(FALL_2026, time_budget_s=100.0)
    assert result.observed_ids == ["30013"]
    assert result.missing_ids == ["30174", "30590"]
    # the whole budget is handed to get_many when listing took no time
    assert client.get_many_calls[0][1] == pytest.approx(100.0)


def test_fetch_listing_time_counts_against_budget(tmp_path: Path) -> None:
    fake = FakeClock()
    pages = standard_pages({})

    class SlowListingClient(StubClient):
        def get(self, url: str, headers: dict[str, str] | None = None) -> bytes:
            fake.sleep(30.0)
            return super().get(url, headers)

    client = SlowListingClient(pages)
    source = ClassesSiteSource(client, tmp_path, base_url=BASE, clock=fake.now)
    result = source.fetch(FALL_2026, time_budget_s=60.0)
    # discovery + 2 listing pages = 90s > 60s budget: nothing attempted
    assert client.get_many_calls[0][1] == 0.0
    assert result.rows == []
    assert result.missing_ids == ["30013", "30174", "30590"]


def test_fetch_priority_and_shard(tmp_path: Path) -> None:
    section_urls = {
        f"{BASE}/content/2026-fall-aeroeng-1-001-sem-001": section_page(30013),
        f"{BASE}/content/2026-fall-aeroeng-10-001-lec-001": section_page(30174),
        f"{BASE}/content/2026-fall-aeroeng-100-001-lec-001": section_page(30590),
    }
    client = StubClient(standard_pages(section_urls))
    source = ClassesSiteSource(client, tmp_path, base_url=BASE)
    priority = PrioritySpec.from_text("# impacted\nAEROENG 10\n")
    n = 4
    k = shard_of("30590", n)

    result = source.fetch(FALL_2026, priority=priority, shard=(k, n))

    expected = {"30174"} | {sid for sid in ("30013", "30174", "30590") if shard_of(sid, n) == k}
    assert set(result.observed_ids) == expected
    assert "30590" in result.observed_ids
    assert result.scope == "priority"
    assert result.shard == f"{k}/{n}"
    assert result.priority_sha == priority.sha
    assert result.universe_ids is None
    assert result.missing_ids == []
    requested = client.get_many_calls[0][0]
    assert len(requested) == len(expected)


def test_fetch_priority_without_shard(tmp_path: Path) -> None:
    section_urls = {f"{BASE}/content/2026-fall-aeroeng-10-001-lec-001": section_page(30174)}
    client = StubClient(standard_pages(section_urls))
    source = ClassesSiteSource(client, tmp_path, base_url=BASE)
    result = source.fetch(FALL_2026, priority=PrioritySpec.from_text("AEROENG 10\n"))
    assert result.observed_ids == ["30174"]
    assert result.shard == ""
    assert result.scope == "priority"


def test_fetch_limit_shortens_listing_and_selection(tmp_path: Path) -> None:
    section_urls = {
        f"{BASE}/content/2026-fall-aeroeng-1-001-sem-001": section_page(30013),
        f"{BASE}/content/2026-fall-aeroeng-10-001-lec-001": section_page(30174),
    }
    client = StubClient(standard_pages(section_urls))
    source = ClassesSiteSource(client, tmp_path, base_url=BASE)
    result = source.fetch(FALL_2026, limit=2)
    assert result.observed_ids == ["30013", "30174"]
    assert result.universe_ids is None
    listing_calls = [u for u in client.get_calls if "page=" in u]
    assert len(listing_calls) <= math.ceil(2 / 18) + 1
    assert not (tmp_path / "catalog").exists()  # partial listing is not cached


def test_fetch_catalog_max_pages_caps_listing(tmp_path: Path) -> None:
    section_urls = {
        f"{BASE}/content/2026-fall-aeroeng-1-001-sem-001": section_page(30013),
        f"{BASE}/content/2026-fall-aeroeng-10-001-lec-001": section_page(30174),
        f"{BASE}/content/2026-fall-aeroeng-100-001-lec-001": section_page(30590),
    }
    client = StubClient(standard_pages(section_urls))
    source = ClassesSiteSource(client, tmp_path, base_url=BASE, catalog_max_pages=1)
    result = source.fetch(FALL_2026)
    assert result.observed_ids == ["30013", "30174", "30590"]
    assert result.scope == "full"
    assert result.universe_ids is None  # capped listing is not the universe
    assert [u for u in client.get_calls if "page=" in u] == [listing_url(0)]
    assert not (tmp_path / "catalog").exists()
    with pytest.raises(ValueError):
        ClassesSiteSource(client, tmp_path, base_url=BASE, catalog_max_pages=0)


def test_fetch_term_not_published(tmp_path: Path) -> None:
    source = ClassesSiteSource(StubClient(standard_pages({})), tmp_path, base_url=BASE)
    with pytest.raises(TermNotPublished):
        source.fetch(TermSpec.from_name("Spring 2031"))


def test_fetch_rejects_bad_shard(tmp_path: Path) -> None:
    source = ClassesSiteSource(StubClient(standard_pages({})), tmp_path, base_url=BASE)
    with pytest.raises(ValueError):
        source.fetch(FALL_2026, priority=PrioritySpec.from_text("AEROENG 10\n"), shard=(4, 4))


def test_fetch_priority_sections_are_scheduled_before_shard_members(tmp_path: Path) -> None:
    """A budget cutoff must trim the rotating shard, never the priority list."""
    section_urls = {
        f"{BASE}/content/2026-fall-aeroeng-1-001-sem-001": section_page(30013),
        f"{BASE}/content/2026-fall-aeroeng-10-001-lec-001": section_page(30174),
        f"{BASE}/content/2026-fall-aeroeng-100-001-lec-001": section_page(30590),
    }
    # AEROENG 100 (30590) is the LAST listing row; shard (0, 1) covers every section.
    client = StubClient(standard_pages(section_urls), attempt_limit=1)
    source = ClassesSiteSource(client, tmp_path, base_url=BASE)

    result = source.fetch(FALL_2026, priority=PrioritySpec.from_text("AEROENG 100\n"), shard=(0, 1))

    requested = client.get_many_calls[0][0]
    assert requested[0].endswith("/content/2026-fall-aeroeng-100-001-lec-001")
    assert [u.rsplit("/", 1)[1] for u in requested[1:]] == [
        "2026-fall-aeroeng-1-001-sem-001", "2026-fall-aeroeng-10-001-lec-001",
    ]
    assert result.observed_ids == ["30590"]
    assert result.missing_ids == ["30013", "30174"]
