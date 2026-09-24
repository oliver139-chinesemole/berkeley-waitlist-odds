"""Offline tests for scraper.sources.classes_site against the saved fixtures."""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scraper.http import HttpError
from scraper.schema import rows_to_table
from scraper.sources.base import ParseError, PrioritySpec, TermNotPublished, TermSpec, shard_of
from scraper.sources.classes_site import (
    ABSENT_REPROBE_AFTER,
    INITIAL_LOOKBACK_NODES,
    MAX_REPROBES_PER_RUN,
    NODE_PROBE_BUDGET_SHARE,
    SELF_STUDY_COMPONENTS,
    ClassesSiteSource,
    SectionRef,
    merge_catalog,
    parse_node_title,
    parse_rss,
    parse_section_page,
    parse_section_meta,
    parse_section_ref,
    ref_from_feed_item,
)

FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"
SECTION_FIXTURE = FIXTURES / "classes_section_2026-fall-aeroeng-10-001-lec-001.html"

BASE = "https://classes.test"
FALL_2026 = TermSpec.from_name("Fall 2026")
SPRING_2027 = TermSpec.from_name("Spring 2027")
FETCHED_AT = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 19, 8, 0, tzinfo=timezone.utc)

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


# -- fakes ---------------------------------------------------------------------


class StubClient:
    """Implements the HttpClient surface the source uses, without threads.

    ``pages`` maps url -> bytes or HttpError; unrouted urls are 404.
    ``get_many`` attempts at most ``attempt_limit`` urls per call and
    reports the rest as budget exhausted.
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
                on_result(url, HttpError(0, url, "budget exhausted"))  # HttpError.budget_exhausted is derived from this message
                continue
            on_result(url, self.pages.get(url, HttpError(404, url, "not routed")))

    def fetched(self, index: int = -1) -> list[str]:
        return [u.rsplit("/", 1)[1] for u in self.get_many_calls[index][0]]


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now
        self.mono = 0.0

    def utcnow(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono


def section_html(
    term_name: str,
    subject: str,
    catalog: str,
    class_number: str,
    component: str,
    section_id: int,
    node_id: int,
    *,
    enrolled: int = 10,
    waitlisted: int = 2,
    term_id: str = "2268",
    title: str | None = None,
    instructors: str | None = None,
) -> bytes:
    """A minimal section page shaped like the live one (title, canonical, node id, blob,
    and the ``sf--course-title`` / ``sf--instructors`` elements)."""
    title = f"{subject} {catalog} title" if title is None else title
    instructors = f"{subject} {catalog} instructors" if instructors is None else instructors
    year, semester = term_name.split()[1], term_name.split()[0]
    slug = f"/content/{year}-{semester.lower()}-{subject.lower()}-{catalog.lower()}-{class_number.lower()}-{component.lower()}-{class_number.lower()}"
    settings = {
        "ucb": {
            "enrollment": {
                "available": {
                    "id": section_id,
                    "enrollmentStatus": {
                        "status": {"code": "O", "description": "Open"},
                        "enrolledCount": enrolled,
                        "reservedCount": 0,
                        "waitlistedCount": waitlisted,
                        "minEnroll": 0,
                        "maxEnroll": 100,
                        "maxWaitlist": 20,
                        "openReserved": 0,
                    },
                }
            }
        }
    }
    return (
        f'<html><head><title>{year} {semester} {subject} {catalog} {class_number} {component} {class_number} | UCB Class Search</title>'
        f'<link rel="canonical" href="{BASE}{slug}" />'
        '<script type="application/json" data-drupal-selector="drupal-settings-json">'
        + json.dumps(settings)
        + f'</script></head><body><article data-history-node-id="{node_id}"></article>'
        f'<div class="sf--course-title">{title}</div>'
        f'<div class="sf--instructors"><p><span class="icon icon-instructor" aria-label="Instructors"></span> {instructors}</p></div>'
        f'<div data-term="{term_id}" data-term-name="{term_name}"></div></body></html>'
    ).encode()


def slug_of(term_name: str, subject: str, catalog: str, class_number: str, component: str) -> str:
    year, semester = term_name.split()[1], term_name.split()[0]
    return f"/content/{year}-{semester.lower()}-{subject.lower()}-{catalog.lower()}-{class_number.lower()}-{component.lower()}-{class_number.lower()}"


def rss_xml(items: list[tuple[int, str, str, str, str, str]]) -> bytes:
    """items: (node_id, term_name, subject, catalog, class_number, component)."""
    parts = ["<?xml version='1.0'?><rss><channel><title>UCB Class Search</title>"]
    for node_id, term_name, subject, catalog, class_number, component in items:
        year, semester = term_name.split()[1], term_name.split()[0]
        parts.append(
            f"<item><title>{year} {semester} {subject} {catalog} {class_number} {component} {class_number}</title>"
            f"<link>{BASE}{slug_of(term_name, subject, catalog, class_number, component)}</link>"
            f'<guid isPermaLink="false">{node_id} at {BASE}</guid><pubDate>Sat, 19 Sep 2026 14:51:59 +0000</pubDate></item>'
        )
    parts.append("</channel></rss>")
    return "".join(parts).encode()


def catalog_with(tmp_path: Path, term: TermSpec, refs: list[SectionRef]) -> None:
    path = tmp_path / "catalog" / term.sis_term_id / "catalog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 3, "term_id": term.sis_term_id, "sections": [r.to_dict() for r in refs]}))


def site_state(tmp_path: Path, probed: int | None, seen: int | None) -> None:
    path = tmp_path / "catalog" / "site.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"max_node_probed": probed, "max_node_seen": seen}))


def read_catalog(tmp_path: Path, term_id: str = "2268") -> dict:
    return json.loads((tmp_path / "catalog" / term_id / "catalog.json").read_text())


def read_site_state(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "catalog" / "site.json").read_text())


def make_source(
    tmp_path: Path,
    pages: dict[str, bytes | HttpError],
    *,
    n_shards: int = 12,
    attempt_limit: int | None = None,
    clock: Clock | None = None,
    max_node_probes: int = 400,
) -> tuple[ClassesSiteSource, StubClient, Clock]:
    clock = clock or Clock()
    client = StubClient(pages, attempt_limit=attempt_limit)
    source = ClassesSiteSource(
        client,  # type: ignore[arg-type]
        tmp_path,
        n_shards,
        BASE,
        max_node_probes=max_node_probes,
        now=clock.utcnow,
        clock=clock.monotonic,
    )
    return source, client, clock


# A small site: the feed shows nodes 1010..1012, section pages live at their aliases and node urls.
FEED_ITEMS = [
    (1012, "Fall 2026", "COMPSCI", "61A", "001", "LEC"),
    (1011, "Fall 2026", "DATA", "C100", "001", "LEC"),
    (1010, "Fall 2026", "STAT", "199", "003", "IND"),  # self-study, ignored
]


def small_site(*, feed: list | None = None, extra: dict | None = None) -> dict[str, bytes | HttpError]:
    pages: dict[str, bytes | HttpError] = {f"{BASE}/rss.xml": rss_xml(FEED_ITEMS if feed is None else feed)}
    cs = section_html("Fall 2026", "COMPSCI", "61A", "001", "LEC", 29147, 1012)
    data = section_html("Fall 2026", "DATA", "C100", "001", "LEC", 20882, 1011)
    pages[f"{BASE}{slug_of('Fall 2026', 'COMPSCI', '61A', '001', 'LEC')}"] = cs
    pages[f"{BASE}/node/1012"] = cs
    pages[f"{BASE}{slug_of('Fall 2026', 'DATA', 'C100', '001', 'LEC')}"] = data
    pages[f"{BASE}/node/1011"] = data
    pages[f"{BASE}/node/1010"] = section_html("Fall 2026", "STAT", "199", "003", "IND", 555, 1010)
    pages[f"{BASE}/node/1009"] = b"<html><head><title>Home | UCB Class Search</title></head><body>not a section</body></html>"
    if extra:
        pages.update(extra)
    return pages


# -- pure parsers ----------------------------------------------------------------


def test_parse_node_title() -> None:
    identity = parse_node_title("2026 Fall AEROENG 10 001 LEC 001 | UCB Class Search")
    assert identity is not None
    assert (identity.term_name, identity.subject, identity.catalog_number) == ("Fall 2026", "AEROENG", "10")
    assert (identity.class_number, identity.component, identity.section_number) == ("001", "LEC", "001")
    assert identity.course_key == "AEROENG 10"
    assert parse_node_title("Home | UCB Class Search") is None
    assert parse_node_title("2027 Spring DATA C100 001 LEC 001").term_name == "Spring 2027"  # type: ignore[union-attr]


def test_parse_rss_items_newest_first() -> None:
    items = parse_rss(rss_xml(FEED_ITEMS))
    assert [i[0] for i in items] == [1012, 1011, 1010]
    assert items[0][1] == "/content/2026-fall-compsci-61a-001-lec-001"
    assert items[0][2] == "2026 Fall COMPSCI 61A 001 LEC 001"
    assert parse_rss(b"<rss><channel></channel></rss>") == []


def test_parse_section_ref_real_fixture() -> None:
    parsed = parse_section_ref(SECTION_FIXTURE.read_bytes())
    assert parsed is not None
    ref, identity = parsed
    assert ref.url_path == "/content/2026-fall-aeroeng-10-001-lec-001"
    assert ref.node_id == 515662 and ref.section_id == "" and ref.component == "LEC"
    assert identity.term_name == "Fall 2026"
    assert parse_section_ref(b"<html><head><title>Home | UCB Class Search</title></head></html>") is None


def test_ref_from_feed_item() -> None:
    parsed = ref_from_feed_item(1012, "/content/2026-fall-compsci-61a-001-lec-001", "2026 Fall COMPSCI 61A 001 LEC 001")
    assert parsed is not None and parsed[0].course_key == "COMPSCI 61A" and parsed[0].node_id == 1012
    assert ref_from_feed_item(5, "/content/x", "Home") is None


def test_merge_catalog_keeps_learned_state_and_adds_node_id() -> None:
    known = SectionRef(**{**AEROENG_10_REF.to_dict(), "last_status": 200, "probed_at": "2026-09-19T00:00:00+00:00"})
    fresh = [SectionRef(**{**AEROENG_10_REF.to_dict(), "section_id": "", "node_id": 515662}), AEROENG_10_REF]
    merged, added = merge_catalog([known], fresh)
    assert added == 0 and len(merged) == 1
    assert merged[0].section_id == "30174" and merged[0].last_status == 200 and merged[0].node_id == 515662


# -- section page parsing --------------------------------------------------------


def test_parse_section_page_real_fixture() -> None:
    row = parse_section_page(SECTION_FIXTURE.read_bytes(), AEROENG_10_REF, FETCHED_AT, FALL_2026)
    assert row["section_id"] == "30174" and row["term_id"] == "2268"
    assert (row["enrolled_count"], row["enroll_capacity"], row["waitlist_count"], row["waitlist_capacity"]) == (60, 64, 0, 15)
    assert (row["reserved_count"], row["open_reserved"], row["status"]) == (60, 0, "O")
    assert row["section_status"] is None and row["is_primary"] is None and row["source"] == "classes_site"
    assert rows_to_table([row]).num_rows == 1


def test_parse_section_page_adopts_page_id_when_unknown() -> None:
    ref = SectionRef(**{**AEROENG_10_REF.to_dict(), "section_id": ""})
    assert parse_section_page(SECTION_FIXTURE.read_bytes(), ref, FETCHED_AT, FALL_2026)["section_id"] == "30174"


def test_parse_section_page_id_mismatch() -> None:
    ref = SectionRef(**{**AEROENG_10_REF.to_dict(), "section_id": "99999"})
    with pytest.raises(ParseError, match="expected 99999"):
        parse_section_page(SECTION_FIXTURE.read_bytes(), ref, FETCHED_AT, FALL_2026)


def test_parse_section_page_term_mismatch_uses_page_value(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        row = parse_section_page(SECTION_FIXTURE.read_bytes(), AEROENG_10_REF, FETCHED_AT, SPRING_2027)
    assert row["term_id"] == "2268" and "data-term=2268" in caplog.text


def test_parse_section_page_without_blob() -> None:
    with pytest.raises(ParseError, match="drupal-settings-json"):
        parse_section_page(b"<html><body>nothing</body></html>", AEROENG_10_REF, FETCHED_AT, FALL_2026)


def test_parse_section_page_missing_keys() -> None:
    html = b'<html><script type="application/json" data-drupal-selector="drupal-settings-json">{"ucb": {}}</script></html>'
    with pytest.raises(ParseError, match="ucb.enrollment"):
        parse_section_page(html, AEROENG_10_REF, FETCHED_AT, FALL_2026)


# -- discovery -------------------------------------------------------------------


def test_first_run_reads_feed_initialises_watermark_and_probes(tmp_path: Path) -> None:
    source, client, _ = make_source(tmp_path, small_site())
    result = source.fetch(FALL_2026, priority=None, time_budget_s=1000)
    # feed added COMPSCI 61A and DATA C100 (STAT 199 IND is self-study); watermark starts newest - lookback
    state = read_site_state(tmp_path)
    assert state["max_node_seen"] == 1012
    # the lookback (2000) reaches below id 1, so the watermark starts at 0 and the first
    # run probes ids 1..400 (the per-run cap), leaving 401..1012 for later runs
    assert INITIAL_LOOKBACK_NODES > 1012
    assert state["max_node_probed"] == 400
    probe_urls = client.get_many_calls[0][0]
    assert probe_urls[0] == f"{BASE}/node/1" and probe_urls[-1] == f"{BASE}/node/400"
    assert client.get_many_calls[0][1] == pytest.approx(1000 * NODE_PROBE_BUDGET_SHARE)
    # rows: both sections observed via the normal fetch (the probe window did not reach 1011/1012)
    assert sorted(r["section_id"] for r in result.rows) == ["20882", "29147"]
    paths = {s["url_path"]: s for s in read_catalog(tmp_path)["sections"]}
    assert set(paths) == {"/content/2026-fall-compsci-61a-001-lec-001", "/content/2026-fall-data-c100-001-lec-001"}
    assert paths["/content/2026-fall-compsci-61a-001-lec-001"]["node_id"] == 1012
    assert paths["/content/2026-fall-compsci-61a-001-lec-001"]["section_id"] == "29147"


def test_enumeration_uses_probed_pages_as_observations(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1008, seen=None)
    source, client, _ = make_source(tmp_path, small_site())
    result = source.fetch(FALL_2026, priority=None, time_budget_s=1000)
    # probed 1009 (not a section), 1010 (self-study, skipped), 1011, 1012 (sections, prefetched)
    assert client.get_many_calls[0][0] == [f"{BASE}/node/{n}" for n in (1009, 1010, 1011, 1012)]
    assert read_site_state(tmp_path)["max_node_probed"] == 1012
    assert sorted(r["section_id"] for r in result.rows) == ["20882", "29147"]
    # second get_many call, if any, fetched nothing: both pages came from discovery
    assert len(client.get_many_calls) == 1 or client.get_many_calls[1][0] == []
    assert result.universe_ids == {"20882", "29147"}


def test_enumeration_skips_restricted_nodes_and_retries_transient_errors(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1006, seen=None)
    pages = small_site(extra={f"{BASE}/node/1007": HttpError(403, "x", "restricted"), f"{BASE}/node/1008": HttpError(503, "x", "down")})
    source, client, _ = make_source(tmp_path, pages)
    source.fetch(FALL_2026, priority=None, time_budget_s=1000)
    state = read_site_state(tmp_path)
    # the 403 and the 503 both advance the watermark; only the 503 is kept for retry
    assert state["max_node_probed"] == 1012 and state["retry_ids"] == [1008]
    # next run: the retry comes first, and once it resolves (now a section) it leaves the list
    pages2 = small_site(extra={f"{BASE}/node/1008": section_html("Fall 2026", "STAT", "134", "001", "LEC", 20746, 1008)})
    source2, client2, _ = make_source(tmp_path, pages2)
    result = source2.fetch(FALL_2026, priority=None, time_budget_s=1000)
    assert client2.get_many_calls[0][0][0] == f"{BASE}/node/1008"
    assert read_site_state(tmp_path)["retry_ids"] == []
    assert "20746" in {r["section_id"] for r in result.rows}


def test_enumeration_budget_cutoff_does_not_skip_ids(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1008, seen=None)
    source, client, _ = make_source(tmp_path, small_site(), attempt_limit=2)
    source.fetch(FALL_2026, priority=None, time_budget_s=1000)
    assert read_site_state(tmp_path)["max_node_probed"] == 1010  # 1009 and 1010 attempted, 1011.. not


def test_enumeration_capped_per_run(tmp_path: Path) -> None:
    site_state(tmp_path, probed=0, seen=None)
    source, client, _ = make_source(tmp_path, small_site(), max_node_probes=3)
    source.fetch(FALL_2026, priority=None, time_budget_s=1000)
    assert client.get_many_calls[0][0] == [f"{BASE}/node/{n}" for n in (1, 2, 3)]
    assert read_site_state(tmp_path)["max_node_probed"] == 3


def test_other_terms_go_to_their_own_catalog_and_new_term_is_discovered(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1012, seen=None)
    feed = [(1013, "Spring 2027", "DATA", "C100", "001", "LEC")] + FEED_ITEMS
    spring_page = section_html("Spring 2027", "DATA", "C100", "001", "LEC", 40001, 1013, term_id="2272")
    pages = small_site(feed=feed, extra={f"{BASE}/node/1013": spring_page, f"{BASE}{slug_of('Spring 2027', 'DATA', 'C100', '001', 'LEC')}": spring_page})
    source, client, _ = make_source(tmp_path, pages)
    # Fall run: probes node 1013 (Spring), records it in 2272's catalog, does not observe it
    result = source.fetch(FALL_2026, priority=None, time_budget_s=1000)
    assert sorted(r["section_id"] for r in result.rows) == ["20882", "29147"]
    spring = read_catalog(tmp_path, "2272")["sections"]
    assert [s["url_path"] for s in spring] == ["/content/2027-spring-data-c100-001-lec-001"] and spring[0]["node_id"] == 1013
    # Spring run now sees the term
    result2 = source.fetch(SPRING_2027, priority=None, time_budget_s=1000)
    assert [r["section_id"] for r in result2.rows] == ["40001"] and result2.rows[0]["term_id"] == "2272"


def test_term_not_published_when_nothing_found(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1012, seen=None)
    source, _, _ = make_source(tmp_path, small_site())
    with pytest.raises(TermNotPublished):
        source.fetch(SPRING_2027, priority=None, time_budget_s=1000)


def test_feed_failure_falls_back_to_stored_watermark(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    site_state(tmp_path, probed=1008, seen=1012)
    pages = small_site()
    pages[f"{BASE}/rss.xml"] = HttpError(503, f"{BASE}/rss.xml", "down")
    source, client, _ = make_source(tmp_path, pages)
    with caplog.at_level(logging.WARNING):
        result = source.fetch(FALL_2026, priority=None, time_budget_s=1000)
    assert "rss.xml not readable" in caplog.text
    assert client.get_many_calls[0][0] == [f"{BASE}/node/{n}" for n in (1009, 1010, 1011, 1012)]
    assert sorted(r["section_id"] for r in result.rows) == ["20882", "29147"]


def test_no_feed_and_no_watermark_skips_enumeration(tmp_path: Path) -> None:
    catalog_with(tmp_path, FALL_2026, [SectionRef(**{**AEROENG_10_REF.to_dict(), "section_id": ""})])
    pages = {f"{BASE}/rss.xml": HttpError(503, "x", "down"), f"{BASE}{AEROENG_10_REF.url_path}": SECTION_FIXTURE.read_bytes()}
    source, client, _ = make_source(tmp_path, pages)
    result = source.fetch(FALL_2026, priority=None, time_budget_s=1000)
    assert [r["section_id"] for r in result.rows] == ["30174"]
    assert client.get_many_calls[0][0] == [f"{BASE}{AEROENG_10_REF.url_path}"]
    assert not (tmp_path / "catalog" / "site.json").exists()


def test_legacy_listing_file_seeds_catalog(tmp_path: Path) -> None:
    legacy = tmp_path / "catalog" / "2268" / "sections.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps(
            {
                "term_id": "2268",
                "listed_at": "2026-09-19T02:30:00+00:00",
                "sections": [
                    AEROENG_10_REF.to_dict(),
                    {**AEROENG_10_REF.to_dict(), "section_id": "1", "url_path": "/content/2026-fall-aeroeng-199-001-ind-001", "component": "IND"},
                ],
            }
        )
    )
    site_state(tmp_path, probed=1012, seen=None)
    pages = small_site(extra={f"{BASE}{AEROENG_10_REF.url_path}": SECTION_FIXTURE.read_bytes()})
    source, _, _ = make_source(tmp_path, pages)
    result = source.fetch(FALL_2026, priority=None, time_budget_s=1000)
    assert sorted(r["section_id"] for r in result.rows) == ["20882", "29147", "30174"]
    paths = {s["url_path"] for s in read_catalog(tmp_path)["sections"]}
    assert "/content/2026-fall-aeroeng-199-001-ind-001" not in paths and AEROENG_10_REF.url_path in paths
    assert "IND" in SELF_STUDY_COMPONENTS


def test_catalog_written_only_when_changed(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1012, seen=1012)
    source, _, clock = make_source(tmp_path, small_site())
    source.fetch(FALL_2026, priority=None)
    path = tmp_path / "catalog" / "2268" / "catalog.json"
    text_before, mtime_before = path.read_text(), path.stat().st_mtime_ns
    clock.now = NOW + timedelta(hours=1)
    source2, _, _ = make_source(tmp_path, small_site(), clock=clock)
    source2.fetch(FALL_2026, priority=None)
    assert path.read_text() == text_before and path.stat().st_mtime_ns == mtime_before


# -- selection and fetching -------------------------------------------------------


def catalog_of(*courses: tuple[str, str]) -> list[SectionRef]:
    return [
        SectionRef(section_id="", url_path=slug_of("Fall 2026", s, c, "001", "LEC"), course_key=f"{s} {c}", subject=s,
                   catalog_number=c, class_number="001", section_number="001", component="LEC")
        for s, c in courses
    ]


def test_priority_rank_order_then_shard(tmp_path: Path) -> None:
    courses = [("MCELLBI", "102"), ("COMPSCI", "61A"), ("DATA", "C100"), ("ART", "1"), ("HISTORY", "7A"), ("MUSIC", "27"), ("PHYSICS", "7A")]
    catalog_with(tmp_path, FALL_2026, catalog_of(*courses))
    site_state(tmp_path, probed=1012, seen=1012)
    priority = PrioritySpec.from_text("COMPSCI *\nDATA *\nPHYSICS 7*\nMCELLBI *")
    source, client, _ = make_source(tmp_path, small_site(), n_shards=2)
    result = source.fetch(FALL_2026, priority=priority, shard=(1, 2))
    keys = client.fetched()
    assert keys[:4] == [
        "2026-fall-compsci-61a-001-lec-001",
        "2026-fall-data-c100-001-lec-001",
        "2026-fall-physics-7a-001-lec-001",
        "2026-fall-mcellbi-102-001-lec-001",
    ]
    expected_rest = sorted(
        slug_of("Fall 2026", s, c, "001", "LEC").rsplit("/", 1)[1]
        for s, c in (("ART", "1"), ("HISTORY", "7A"), ("MUSIC", "27"))
        if shard_of(slug_of("Fall 2026", s, c, "001", "LEC"), 2) == 1
    )
    assert sorted(keys[4:]) == expected_rest
    assert result.scope == "priority" and result.shard == "1/2" and result.priority_sha == priority.sha
    assert result.universe_ids is None


def test_priority_without_shard_fetches_priority_only(tmp_path: Path) -> None:
    catalog_with(tmp_path, FALL_2026, catalog_of(("COMPSCI", "61A"), ("ART", "1")))
    site_state(tmp_path, probed=1012, seen=1012)
    source, client, _ = make_source(tmp_path, small_site(), n_shards=0)
    source.fetch(FALL_2026, priority=PrioritySpec.from_text("COMPSCI *"), shard=None)
    assert client.fetched() == ["2026-fall-compsci-61a-001-lec-001"]


def test_missing_ids_only_for_known_sections(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1012, seen=1012)
    source, _, clock = make_source(tmp_path, small_site())
    source.fetch(FALL_2026, priority=None)
    pages = small_site()
    pages[f"{BASE}{slug_of('Fall 2026', 'DATA', 'C100', '001', 'LEC')}"] = HttpError(503, "x", "down")
    clock.now = NOW + timedelta(minutes=30)
    source2, _, _ = make_source(tmp_path, pages, clock=clock)
    result = source2.fetch(FALL_2026, priority=None)
    assert result.missing_ids == ["20882"] and result.universe_ids == {"29147", "20882"}
    entry = next(s for s in read_catalog(tmp_path)["sections"] if s["url_path"].endswith("data-c100-001-lec-001"))
    assert entry["last_status"] == 200 and entry["section_id"] == "20882"


def test_known_section_turning_404_goes_to_missing_and_absent(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1012, seen=1012)
    source, _, clock = make_source(tmp_path, small_site())
    source.fetch(FALL_2026, priority=None)
    pages = small_site()
    del pages[f"{BASE}{slug_of('Fall 2026', 'COMPSCI', '61A', '001', 'LEC')}"]
    clock.now = NOW + timedelta(minutes=30)
    source2, _, _ = make_source(tmp_path, pages, clock=clock)
    result = source2.fetch(FALL_2026, priority=None)
    assert result.missing_ids == ["29147"] and [r["section_id"] for r in result.rows] == ["20882"]
    entry = next(s for s in read_catalog(tmp_path)["sections"] if s["url_path"].endswith("compsci-61a-001-lec-001"))
    assert entry["last_status"] == 404 and entry["section_id"] == "29147"
    # absent slugs are skipped until due for a re-probe
    source3, client3, _ = make_source(tmp_path, pages, clock=clock)
    source3.fetch(FALL_2026, priority=None)
    assert client3.fetched() == ["2026-fall-data-c100-001-lec-001"]
    clock.now = NOW + ABSENT_REPROBE_AFTER + timedelta(days=1)
    source4, client4, _ = make_source(tmp_path, pages, clock=clock)
    source4.fetch(FALL_2026, priority=None)
    assert "2026-fall-compsci-61a-001-lec-001" in client4.fetched()


def test_reprobe_is_capped_per_run(tmp_path: Path) -> None:
    refs = [SectionRef(**{**r.to_dict(), "last_status": 404, "probed_at": "2026-01-01T00:00:00+00:00"}) for r in catalog_of(*[("SUBJ", str(i)) for i in range(MAX_REPROBES_PER_RUN + 20)])]
    catalog_with(tmp_path, FALL_2026, refs)
    site_state(tmp_path, probed=1012, seen=1012)
    source, client, _ = make_source(tmp_path, small_site())
    source.fetch(FALL_2026, priority=None)
    reprobed = [u for u in client.fetched() if "subj-" in u]
    assert len(reprobed) == MAX_REPROBES_PER_RUN


def test_parse_error_goes_to_missing_when_id_known(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1012, seen=1012)
    source, _, clock = make_source(tmp_path, small_site())
    source.fetch(FALL_2026, priority=None)
    pages = small_site()
    pages[f"{BASE}{slug_of('Fall 2026', 'COMPSCI', '61A', '001', 'LEC')}"] = b"<html>no blob</html>"
    clock.now = NOW + timedelta(minutes=30)
    source2, _, _ = make_source(tmp_path, pages, clock=clock)
    assert source2.fetch(FALL_2026, priority=None).missing_ids == ["29147"]


def test_time_budget_cutoff_marks_known_ids_missing(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1012, seen=1012)
    source, _, clock = make_source(tmp_path, small_site())
    source.fetch(FALL_2026, priority=None)
    clock.now = NOW + timedelta(minutes=30)
    source2, client2, _ = make_source(tmp_path, small_site(), clock=clock, attempt_limit=1)
    result = source2.fetch(FALL_2026, priority=None, time_budget_s=100)
    assert len(result.rows) == 1 and len(result.missing_ids) == 1
    assert client2.get_many_calls[-1][1] == pytest.approx(100.0)


def test_discovery_time_counts_against_budget(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1008, seen=None)
    clock = Clock()
    pages = small_site()
    source, client, _ = make_source(tmp_path, pages, clock=clock)
    original_get_many = client.get_many

    def slow_get_many(urls, on_result, time_budget_s=None):
        clock.mono += 50.0
        original_get_many(urls, on_result, time_budget_s)

    client.get_many = slow_get_many  # type: ignore[method-assign]
    catalog_with(tmp_path, FALL_2026, catalog_of(("ART", "1")))  # something left to fetch after discovery
    source.fetch(FALL_2026, priority=None, time_budget_s=200)
    assert client.get_many_calls[-1][1] == pytest.approx(150.0)


def test_limit_caps_selection_and_unknown_universe(tmp_path: Path) -> None:
    catalog_with(tmp_path, FALL_2026, catalog_of(*[("SUBJ", str(i)) for i in range(5)]))
    site_state(tmp_path, probed=1012, seen=1012)
    source, client, _ = make_source(tmp_path, small_site())
    result = source.fetch(FALL_2026, priority=None, limit=2)
    assert len(client.get_many_calls[-1][0]) == 2 and result.universe_ids is None


def test_fetch_rejects_bad_shard_and_limit(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1012, seen=1012)
    source, _, _ = make_source(tmp_path, small_site())
    with pytest.raises(ValueError):
        source.fetch(FALL_2026, priority=PrioritySpec.from_text("COMPSCI *"), shard=(5, 2))
    with pytest.raises(ValueError):
        source.fetch(FALL_2026, limit=0)


# -- course title and instructors in the catalog (Q7, 2026-09-23) ---------------------


def test_parse_section_meta_real_fixture() -> None:
    title, instructors = parse_section_meta(SECTION_FIXTURE.read_bytes())
    assert title == "Introduction to Aerospace Engineering Design"
    assert instructors == "Mark Wilfried Mueller, Daniel Pruzan"
    assert parse_section_meta(b"<html><body><p>no sf elements</p></body></html>") == ("", "")


def test_parse_section_ref_carries_title_and_instructors() -> None:
    parsed = parse_section_ref(SECTION_FIXTURE.read_bytes())
    assert parsed is not None
    ref, _ = parsed
    assert ref.title == "Introduction to Aerospace Engineering Design"
    assert ref.instructors == "Mark Wilfried Mueller, Daniel Pruzan"


def test_section_ref_from_dict_without_title_fields() -> None:
    old = {k: v for k, v in catalog_of(("DATA", "C100"))[0].to_dict().items() if k not in ("title", "instructors")}
    ref = SectionRef.from_dict(old)
    assert ref.title == "" and ref.instructors == ""
    assert SectionRef.from_dict(old | {"title": None, "instructors": None}).title == ""


def test_merge_catalog_takes_a_fresh_title_and_keeps_a_learned_one() -> None:
    base = catalog_of(("COMPSCI", "61A"))[0]
    known = replace(base, section_id="29147", last_status=200, title="Old title", instructors="A. Person")
    merged, added = merge_catalog([known], [replace(base, node_id=1012, title="New title", instructors="B. Person")])
    assert added == 0 and merged[0].section_id == "29147" and merged[0].node_id == 1012
    assert (merged[0].title, merged[0].instructors) == ("New title", "B. Person")
    merged, _ = merge_catalog([known], [replace(base, node_id=1012)])
    assert (merged[0].title, merged[0].instructors) == ("Old title", "A. Person")


def test_fetch_writes_title_and_instructors_once(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1012, seen=1012)
    source, _, clock = make_source(tmp_path, small_site())
    source.fetch(FALL_2026, priority=None)
    path = tmp_path / "catalog" / "2268" / "catalog.json"
    entries = {e["url_path"]: e for e in json.loads(path.read_text())["sections"]}
    cs = entries[slug_of("Fall 2026", "COMPSCI", "61A", "001", "LEC")]
    assert (cs["title"], cs["instructors"]) == ("COMPSCI 61A title", "COMPSCI 61A instructors")
    text_before = path.read_text()
    clock.now = NOW + timedelta(hours=1)
    source2, _, _ = make_source(tmp_path, small_site(), clock=clock)
    source2.fetch(FALL_2026, priority=None)
    assert path.read_text() == text_before


def test_reprobed_page_without_the_elements_keeps_learned_title(tmp_path: Path) -> None:
    """Discovery re-probes node 1012 (watermark just below it); that page prints no course
    title or instructors; the entry learned both earlier and must keep them."""
    learned = replace(
        catalog_of(("COMPSCI", "61A"))[0], section_id="29147", last_status=200, node_id=1012, title="Learned title", instructors="Learned person"
    )
    catalog_with(tmp_path, FALL_2026, [learned])
    site_state(tmp_path, probed=1011, seen=1012)
    blank = section_html("Fall 2026", "COMPSCI", "61A", "001", "LEC", 29147, 1012, title="", instructors="")
    cs_url = f"{BASE}{slug_of('Fall 2026', 'COMPSCI', '61A', '001', 'LEC')}"
    source, _, _ = make_source(tmp_path, small_site(extra={f"{BASE}/node/1012": blank, cs_url: blank}))
    source.fetch(FALL_2026, priority=None)
    entries = {e["url_path"]: e for e in json.loads((tmp_path / "catalog" / "2268" / "catalog.json").read_text())["sections"]}
    cs = entries[slug_of("Fall 2026", "COMPSCI", "61A", "001", "LEC")]
    assert (cs["title"], cs["instructors"]) == ("Learned title", "Learned person")


def test_fetch_rewrites_the_entry_when_only_the_instructors_change(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1012, seen=1012)
    source, _, clock = make_source(tmp_path, small_site())
    source.fetch(FALL_2026, priority=None)
    path = tmp_path / "catalog" / "2268" / "catalog.json"
    text_before = path.read_text()
    swapped = section_html("Fall 2026", "COMPSCI", "61A", "001", "LEC", 29147, 1012, instructors="New Person")
    cs_url = f"{BASE}{slug_of('Fall 2026', 'COMPSCI', '61A', '001', 'LEC')}"
    clock.now = NOW + timedelta(hours=1)
    source2, _, _ = make_source(tmp_path, small_site(extra={cs_url: swapped, f"{BASE}/node/1012": swapped}), clock=clock)
    source2.fetch(FALL_2026, priority=None)
    assert path.read_text() != text_before
    entries = {e["url_path"]: e for e in json.loads(path.read_text())["sections"]}
    cs = entries[slug_of("Fall 2026", "COMPSCI", "61A", "001", "LEC")]
    assert (cs["title"], cs["instructors"]) == ("COMPSCI 61A title", "New Person")


def test_fetch_of_a_page_without_the_elements_keeps_learned_values_and_the_file(tmp_path: Path) -> None:
    site_state(tmp_path, probed=1012, seen=1012)
    source, _, clock = make_source(tmp_path, small_site())
    source.fetch(FALL_2026, priority=None)
    path = tmp_path / "catalog" / "2268" / "catalog.json"
    text_before = path.read_text()
    blank = section_html("Fall 2026", "COMPSCI", "61A", "001", "LEC", 29147, 1012, title="", instructors="")
    cs_url = f"{BASE}{slug_of('Fall 2026', 'COMPSCI', '61A', '001', 'LEC')}"
    clock.now = NOW + timedelta(hours=1)
    source2, _, _ = make_source(tmp_path, small_site(extra={cs_url: blank, f"{BASE}/node/1012": blank}), clock=clock)
    source2.fetch(FALL_2026, priority=None)
    assert path.read_text() == text_before
