"""Offline tests for scraper.sources.classes_site against the saved fixtures."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scraper.http import HttpError
from scraper.schema import rows_to_table
from scraper.sources.base import ParseError, PrioritySpec, TermNotPublished, TermSpec, shard_of
from scraper.sources.classes_site import (
    ABSENT_REPROBE_AFTER,
    CATALOG_MAX_AGE,
    MAX_REPROBES_PER_RUN,
    SELF_STUDY_COMPONENTS,
    ClassesSiteSource,
    SectionRef,
    catalog_refs,
    merge_catalog,
    parse_section_page,
    section_slug,
)

FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"
SECTION_FIXTURE = FIXTURES / "classes_section_2026-fall-aeroeng-10-001-lec-001.html"
CATALOG_FIXTURE = FIXTURES / "berkeleytime_getcatalog_small.json"

BASE = "https://classes.test"
FALL_2026 = TermSpec.from_name("Fall 2026")
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


# -- fakes --------------------------------------------------------------------


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


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now
        self.mono = 0.0

    def utcnow(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono


def section_html(section_id: int, enrolled: int = 10, waitlisted: int = 2, term_id: str = "2268") -> bytes:
    """A minimal section page shaped like the live one."""
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
        "<html><head><script type=\"application/json\" data-drupal-selector=\"drupal-settings-json\">"
        + json.dumps(settings)
        + f"</script></head><body><div data-term=\"{term_id}\" data-term-name=\"Fall 2026\"></div></body></html>"
    ).encode()


def catalog_classes() -> list[dict]:
    return json.loads(CATALOG_FIXTURE.read_text())["data"]["catalog"]


def make_class(subject: str, number: str, class_number: str = "001", component: str = "LEC") -> dict:
    return {
        "subject": subject,
        "courseNumber": number,
        "number": class_number,
        "sessionId": "1",
        "primarySection": {"component": component, "enrollment": {"latest": {"status": "O"}}},
    }


def make_source(
    tmp_path: Path,
    pages: dict[str, bytes | HttpError],
    classes: list[dict] | Exception | None = None,
    *,
    n_shards: int = 8,
    attempt_limit: int | None = None,
    clock: Clock | None = None,
) -> tuple[ClassesSiteSource, StubClient, Clock]:
    clock = clock or Clock()
    client = StubClient(pages, attempt_limit=attempt_limit)

    def provider(term: TermSpec) -> list[dict]:
        if isinstance(classes, Exception):
            raise classes
        return list(classes) if classes is not None else catalog_classes()

    source = ClassesSiteSource(
        client,  # type: ignore[arg-type]
        tmp_path,
        n_shards,
        BASE,
        catalog_provider=provider,
        now=clock.utcnow,
        clock=clock.monotonic,
    )
    return source, client, clock


def read_catalog(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "catalog" / "2268" / "catalog.json").read_text())


# -- section page parsing -----------------------------------------------------


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
    assert row["source"] == "classes_site"
    assert rows_to_table([row]).num_rows == 1


def test_parse_section_page_adopts_page_id_when_unknown() -> None:
    ref = SectionRef(**{**AEROENG_10_REF.to_dict(), "section_id": ""})
    row = parse_section_page(SECTION_FIXTURE.read_bytes(), ref, FETCHED_AT, FALL_2026)
    assert row["section_id"] == "30174"


def test_parse_section_page_id_mismatch() -> None:
    ref = SectionRef(**{**AEROENG_10_REF.to_dict(), "section_id": "99999"})
    with pytest.raises(ParseError, match="expected 99999"):
        parse_section_page(SECTION_FIXTURE.read_bytes(), ref, FETCHED_AT, FALL_2026)


def test_parse_section_page_term_mismatch_uses_page_value(caplog: pytest.LogCaptureFixture) -> None:
    spring = TermSpec.from_name("Spring 2027")
    with caplog.at_level(logging.WARNING):
        row = parse_section_page(SECTION_FIXTURE.read_bytes(), AEROENG_10_REF, FETCHED_AT, spring)
    assert row["term_id"] == "2268"
    assert "data-term=2268" in caplog.text


def test_parse_section_page_without_data_term_falls_back() -> None:
    html = SECTION_FIXTURE.read_bytes().replace(b'data-term="2268"', b"")
    row = parse_section_page(html, AEROENG_10_REF, FETCHED_AT, FALL_2026)
    assert row["term_id"] == "2268"


def test_parse_section_page_without_blob() -> None:
    with pytest.raises(ParseError, match="drupal-settings-json"):
        parse_section_page(b"<html><body>nothing</body></html>", AEROENG_10_REF, FETCHED_AT, FALL_2026)


def test_parse_section_page_missing_keys() -> None:
    html = b'<html><script type="application/json" data-drupal-selector="drupal-settings-json">{"ucb": {}}</script></html>'
    with pytest.raises(ParseError, match="ucb.enrollment"):
        parse_section_page(html, AEROENG_10_REF, FETCHED_AT, FALL_2026)


# -- catalog building ---------------------------------------------------------


def test_section_slug_matches_live_pattern() -> None:
    assert section_slug(FALL_2026, "AEROENG", "10", "001", "LEC") == "/content/2026-fall-aeroeng-10-001-lec-001"
    assert section_slug(FALL_2026, "EL ENG", "16A", "001", "LEC") == "/content/2026-fall-eleng-16a-001-lec-001"
    assert section_slug(TermSpec.from_name("Spring 2027"), "DATA", "C100", "001", "LEC") == "/content/2027-spring-data-c100-001-lec-001"


def test_catalog_refs_from_fixture() -> None:
    refs = catalog_refs(catalog_classes(), FALL_2026)
    assert [r.course_key for r in refs][:1] == ["COMPSCI 61A"]
    first = refs[0]
    assert first.url_path == "/content/2026-fall-compsci-61a-001-lec-001"
    assert first.section_id == ""
    assert first.class_number == first.section_number == "001"
    assert first.component == "LEC"
    assert first.last_status is None


def test_catalog_refs_skips_self_study_and_malformed(caplog: pytest.LogCaptureFixture) -> None:
    classes = [
        make_class("COMPSCI", "61A"),
        make_class("COMPSCI", "199", "003", "IND"),
        make_class("COMPSCI", "198", "004", "GRP"),
        {"subject": "DATA"},  # malformed
        make_class("COMPSCI", "61A"),  # duplicate slug
    ]
    with caplog.at_level(logging.WARNING):
        refs = catalog_refs(classes, FALL_2026)
    assert [r.course_key for r in refs] == ["COMPSCI 61A"]
    assert "skipping catalog entry" in caplog.text
    assert "IND" in SELF_STUDY_COMPONENTS and "GRP" in SELF_STUDY_COMPONENTS


def test_merge_catalog_keeps_learned_state() -> None:
    known = SectionRef(**{**AEROENG_10_REF.to_dict(), "last_status": 200, "probed_at": "2026-09-19T00:00:00+00:00"})
    fresh = catalog_refs([make_class("AEROENG", "10"), make_class("DATA", "C100")], FALL_2026)
    merged, added = merge_catalog([known], fresh)
    assert added == 1
    by_path = {r.url_path: r for r in merged}
    assert by_path[known.url_path] == known  # id and probe state survive
    assert by_path["/content/2026-fall-data-c100-001-lec-001"].section_id == ""


# -- source: catalog lifecycle ------------------------------------------------


def test_first_run_builds_catalog_and_learns_ids(tmp_path: Path) -> None:
    pages = {f"{BASE}/content/2026-fall-compsci-61a-001-lec-001": section_html(29147)}
    source, client, _ = make_source(tmp_path, pages)
    result = source.fetch(FALL_2026, priority=None)
    ids = [r["section_id"] for r in result.rows]
    assert ids == ["29147"]
    assert result.scope == "full"
    # The other two fixture classes 404 (not routed): marked absent, not "missing"
    # because their ids were never known.
    assert result.missing_ids == []
    catalog = read_catalog(tmp_path)
    by_path = {s["url_path"]: s for s in catalog["sections"]}
    assert by_path["/content/2026-fall-compsci-61a-001-lec-001"]["section_id"] == "29147"
    assert by_path["/content/2026-fall-compsci-61a-001-lec-001"]["last_status"] == 200
    absent = [s for s in catalog["sections"] if s["last_status"] == 404]
    assert len(absent) == 2 and all(s["probed_at"] for s in absent)
    assert catalog["refreshed_at"] == NOW.isoformat()


def test_second_run_reuses_catalog_and_skips_absent(tmp_path: Path) -> None:
    pages = {f"{BASE}/content/2026-fall-compsci-61a-001-lec-001": section_html(29147)}
    source, client, clock = make_source(tmp_path, pages)
    source.fetch(FALL_2026, priority=None)
    clock.now = NOW + timedelta(hours=1)
    calls: list[int] = []
    source2, client2, _ = make_source(tmp_path, pages, classes=Exception("provider must not be called"), clock=clock)
    result = source2.fetch(FALL_2026, priority=None)
    assert [r["section_id"] for r in result.rows] == ["29147"]
    urls = client2.get_many_calls[0][0]
    assert urls == [f"{BASE}/content/2026-fall-compsci-61a-001-lec-001"]  # absent slugs skipped
    assert result.universe_ids == {"29147"}
    assert not calls


def test_stale_catalog_refreshes_and_reprobes_absent(tmp_path: Path) -> None:
    pages = {f"{BASE}/content/2026-fall-compsci-61a-001-lec-001": section_html(29147)}
    source, _, clock = make_source(tmp_path, pages)
    source.fetch(FALL_2026, priority=None)
    # 25 hours later: refresh due, absent slugs older than 7 days are not yet due
    clock.now = NOW + CATALOG_MAX_AGE + timedelta(hours=1)
    source2, client2, _ = make_source(tmp_path, pages, clock=clock)
    source2.fetch(FALL_2026, priority=None)
    assert client2.get_many_calls[0][0] == [f"{BASE}/content/2026-fall-compsci-61a-001-lec-001"]
    # 8 days later: refresh run re-probes the absent slugs (still 404 -> stay absent, probed_at moves)
    clock.now = NOW + ABSENT_REPROBE_AFTER + timedelta(days=1)
    source3, client3, _ = make_source(tmp_path, pages, clock=clock)
    source3.fetch(FALL_2026, priority=None)
    urls = client3.get_many_calls[0][0]
    assert len(urls) == 3 and urls[0].endswith("compsci-61a-001-lec-001")
    catalog = read_catalog(tmp_path)
    absent = [s for s in catalog["sections"] if s["last_status"] == 404]
    assert all(s["probed_at"] == clock.now.isoformat() for s in absent)


def test_reprobe_is_capped_per_run(tmp_path: Path) -> None:
    classes = [make_class("SUBJ", str(i)) for i in range(MAX_REPROBES_PER_RUN + 50)]
    source, client, clock = make_source(tmp_path, {}, classes=classes)
    source.fetch(FALL_2026, priority=None)  # everything 404s -> all absent
    clock.now = NOW + ABSENT_REPROBE_AFTER + timedelta(days=1)
    source2, client2, _ = make_source(tmp_path, {}, classes=classes, clock=clock)
    source2.fetch(FALL_2026, priority=None)
    assert len(client2.get_many_calls[0][0]) == MAX_REPROBES_PER_RUN


def test_refresh_failure_falls_back_to_cached_catalog(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    pages = {f"{BASE}/content/2026-fall-compsci-61a-001-lec-001": section_html(29147)}
    source, _, clock = make_source(tmp_path, pages)
    source.fetch(FALL_2026, priority=None)
    clock.now = NOW + CATALOG_MAX_AGE + timedelta(hours=1)
    source2, client2, _ = make_source(tmp_path, pages, classes=RuntimeError("berkeleytime down"), clock=clock)
    with caplog.at_level(logging.WARNING):
        result = source2.fetch(FALL_2026, priority=None)
    assert [r["section_id"] for r in result.rows] == ["29147"]
    assert "using cached copy" in caplog.text


def test_refresh_failure_without_cache_propagates(tmp_path: Path) -> None:
    source, _, _ = make_source(tmp_path, {}, classes=RuntimeError("berkeleytime down"))
    with pytest.raises(RuntimeError, match="berkeleytime down"):
        source.fetch(FALL_2026)


def test_empty_catalog_means_term_not_published(tmp_path: Path) -> None:
    source, _, _ = make_source(tmp_path, {}, classes=[])
    with pytest.raises(TermNotPublished):
        source.fetch(TermSpec.from_name("Spring 2027"))


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
    pages = {
        f"{BASE}/content/2026-fall-aeroeng-10-001-lec-001": SECTION_FIXTURE.read_bytes(),
        f"{BASE}/content/2026-fall-compsci-61a-001-lec-001": section_html(29147),
    }
    source, client, _ = make_source(tmp_path, pages, classes=[make_class("COMPSCI", "61A")])
    result = source.fetch(FALL_2026, priority=None)
    assert sorted(r["section_id"] for r in result.rows) == ["29147", "30174"]
    paths = {s["url_path"] for s in read_catalog(tmp_path)["sections"]}
    assert "/content/2026-fall-aeroeng-199-001-ind-001" not in paths  # self-study dropped
    assert "/content/2026-fall-aeroeng-10-001-lec-001" in paths


def test_catalog_written_only_when_changed(tmp_path: Path) -> None:
    pages = {f"{BASE}/content/2026-fall-compsci-61a-001-lec-001": section_html(29147)}
    source, _, clock = make_source(tmp_path, pages)
    source.fetch(FALL_2026, priority=None)
    path = tmp_path / "catalog" / "2268" / "catalog.json"
    before = path.stat().st_mtime_ns
    text_before = path.read_text()
    clock.now = NOW + timedelta(hours=1)
    source2, _, _ = make_source(tmp_path, pages, clock=clock)
    source2.fetch(FALL_2026, priority=None)
    assert path.read_text() == text_before and path.stat().st_mtime_ns == before


# -- source: selection and fetching -------------------------------------------


def test_priority_rank_order_then_shard(tmp_path: Path) -> None:
    classes = [
        make_class("MCELLBI", "102"),
        make_class("COMPSCI", "61A"),
        make_class("DATA", "C100"),
        make_class("ART", "1"),
        make_class("HISTORY", "7A"),
        make_class("MUSIC", "27"),
        make_class("PHYSICS", "7A"),
    ]
    priority = PrioritySpec.from_text("COMPSCI *\nDATA *\nPHYSICS 7*\nMCELLBI *")
    source, client, _ = make_source(tmp_path, {}, classes=classes, n_shards=2)
    result = source.fetch(FALL_2026, priority=priority, shard=(1, 2))
    urls = client.get_many_calls[0][0]
    keys = [u.rsplit("/", 1)[1] for u in urls]
    assert keys[:4] == [
        "2026-fall-compsci-61a-001-lec-001",
        "2026-fall-data-c100-001-lec-001",
        "2026-fall-physics-7a-001-lec-001",
        "2026-fall-mcellbi-102-001-lec-001",
    ]
    rest = keys[4:]
    expected_rest = sorted(
        f"2026-fall-{s.lower()}-{c.lower()}-001-lec-001"
        for s, c in (("ART", "1"), ("HISTORY", "7A"), ("MUSIC", "27"))
        if shard_of(f"/content/2026-fall-{s.lower()}-{c.lower()}-001-lec-001", 2) == 1
    )
    assert sorted(rest) == expected_rest
    assert result.scope == "priority" and result.shard == "1/2" and result.priority_sha == priority.sha
    assert result.universe_ids is None


def test_priority_without_shard_fetches_priority_only(tmp_path: Path) -> None:
    classes = [make_class("COMPSCI", "61A"), make_class("ART", "1")]
    source, client, _ = make_source(tmp_path, {}, classes=classes, n_shards=0)
    source.fetch(FALL_2026, priority=PrioritySpec.from_text("COMPSCI *"), shard=None)
    assert [u.rsplit("/", 1)[1] for u in client.get_many_calls[0][0]] == ["2026-fall-compsci-61a-001-lec-001"]


def test_missing_ids_only_for_known_sections(tmp_path: Path) -> None:
    pages = {
        f"{BASE}/content/2026-fall-compsci-61a-001-lec-001": section_html(29147),
        f"{BASE}/content/2026-fall-data-c100-001-lec-001": section_html(20882),
    }
    classes = [make_class("COMPSCI", "61A"), make_class("DATA", "C100")]
    source, _, clock = make_source(tmp_path, pages, classes=classes)
    source.fetch(FALL_2026, priority=None)
    # Next run: DATA C100 fails with a 503 (known id -> missing), COMPSCI parses.
    pages2 = {
        f"{BASE}/content/2026-fall-compsci-61a-001-lec-001": section_html(29147),
        f"{BASE}/content/2026-fall-data-c100-001-lec-001": HttpError(503, "x", "down"),
    }
    clock.now = NOW + timedelta(minutes=30)
    source2, _, _ = make_source(tmp_path, pages2, classes=classes, clock=clock)
    result = source2.fetch(FALL_2026, priority=None)
    assert result.missing_ids == ["20882"]
    assert result.universe_ids == {"29147", "20882"}
    # a 503 does not change the catalog entry
    entry = next(s for s in read_catalog(tmp_path)["sections"] if s["url_path"].endswith("data-c100-001-lec-001"))
    assert entry["last_status"] == 200 and entry["section_id"] == "20882"


def test_known_section_turning_404_goes_to_missing_and_absent(tmp_path: Path) -> None:
    pages = {f"{BASE}/content/2026-fall-compsci-61a-001-lec-001": section_html(29147)}
    source, _, clock = make_source(tmp_path, pages, classes=[make_class("COMPSCI", "61A")])
    source.fetch(FALL_2026, priority=None)
    clock.now = NOW + timedelta(minutes=30)
    source2, _, _ = make_source(tmp_path, {}, classes=[make_class("COMPSCI", "61A")], clock=clock)
    result = source2.fetch(FALL_2026, priority=None)
    assert result.rows == [] and result.missing_ids == ["29147"]
    entry = read_catalog(tmp_path)["sections"][0]
    assert entry["last_status"] == 404 and entry["section_id"] == "29147"


def test_parse_error_goes_to_missing_when_id_known(tmp_path: Path) -> None:
    pages = {f"{BASE}/content/2026-fall-compsci-61a-001-lec-001": section_html(29147)}
    source, _, clock = make_source(tmp_path, pages, classes=[make_class("COMPSCI", "61A")])
    source.fetch(FALL_2026, priority=None)
    clock.now = NOW + timedelta(minutes=30)
    bad = {f"{BASE}/content/2026-fall-compsci-61a-001-lec-001": b"<html>no blob</html>"}
    source2, _, _ = make_source(tmp_path, bad, classes=[make_class("COMPSCI", "61A")], clock=clock)
    result = source2.fetch(FALL_2026, priority=None)
    assert result.missing_ids == ["29147"]


def test_time_budget_cutoff_marks_known_ids_missing(tmp_path: Path) -> None:
    classes = [make_class("SUBJ", str(i)) for i in range(4)]
    pages = {f"{BASE}/content/2026-fall-subj-{i}-001-lec-001": section_html(1000 + i) for i in range(4)}
    source, _, clock = make_source(tmp_path, pages, classes=classes)
    source.fetch(FALL_2026, priority=None)
    clock.now = NOW + timedelta(minutes=30)
    source2, client2, _ = make_source(tmp_path, pages, classes=classes, clock=clock, attempt_limit=2)
    result = source2.fetch(FALL_2026, priority=None, time_budget_s=100)
    assert len(result.rows) == 2 and len(result.missing_ids) == 2
    assert client2.get_many_calls[0][1] == 100.0


def test_catalog_refresh_time_counts_against_budget(tmp_path: Path) -> None:
    clock = Clock()
    source, client, _ = make_source(tmp_path, {}, classes=[make_class("COMPSCI", "61A")], clock=clock)
    original = source._catalog_provider

    def slow_provider(term: TermSpec) -> list[dict]:
        clock.mono += 50.0
        return original(term)

    source._catalog_provider = slow_provider
    source.fetch(FALL_2026, priority=None, time_budget_s=120)
    assert client.get_many_calls[0][1] == pytest.approx(70.0)


def test_limit_caps_selection_and_unknown_universe(tmp_path: Path) -> None:
    classes = [make_class("SUBJ", str(i)) for i in range(5)]
    source, client, _ = make_source(tmp_path, {}, classes=classes)
    result = source.fetch(FALL_2026, priority=None, limit=2)
    assert len(client.get_many_calls[0][0]) == 2
    assert result.universe_ids is None


def test_fetch_rejects_bad_shard(tmp_path: Path) -> None:
    source, _, _ = make_source(tmp_path, {}, classes=[make_class("COMPSCI", "61A")])
    with pytest.raises(ValueError):
        source.fetch(FALL_2026, priority=PrioritySpec.from_text("COMPSCI *"), shard=(5, 2))


def test_fetch_rejects_bad_limit(tmp_path: Path) -> None:
    source, _, _ = make_source(tmp_path, {}, classes=[make_class("COMPSCI", "61A")])
    with pytest.raises(ValueError):
        source.fetch(FALL_2026, limit=0)
