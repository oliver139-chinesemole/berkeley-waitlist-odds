"""Offline tests for scraper.sources.sis_api (DESIGN_A2.md 5b)."""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from scraper.schema import rows_to_table
from scraper.sources.base import FetchResult, ParseError, TermSpec
from scraper.sources.sis_api import (
    BASE_URL,
    ENV_APP_ID,
    ENV_APP_KEY,
    SisApiError,
    SisApiSource,
    class_sections,
    parse_sections,
)

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"
FALL_2026 = TermSpec.from_name("Fall 2026")
NOW = datetime(2026, 9, 18, 20, 15, 7, tzinfo=timezone.utc)


@pytest.fixture
def synthetic_page() -> dict[str, Any]:
    return json.loads((FIXTURES / "sis_sections_page_synthetic.json").read_text(encoding="utf-8"))


def make_page(template: dict[str, Any], ids: list[int]) -> dict[str, Any]:
    """A page payload holding copies of the fixture's primary (active) section with the given ids."""
    primary = next(s for s in class_sections(template) if s["id"] == 29147)
    sections = []
    for i in ids:
        s = copy.deepcopy(primary)
        s["id"] = i
        s["association"]["primaryAssociatedSectionId"] = i
        sections.append(s)
    return {"apiResponse": {"httpStatus": {"code": "200", "description": "OK"}, "response": {"classSections": sections}}}


class FakePages:
    """Injected transport: serves prebuilt pages, 404 beyond them; queued failures per page; records calls."""

    def __init__(self, pages: dict[int, dict[str, Any]], failures: dict[int, list[int]] | None = None) -> None:
        self.pages = pages
        self.failures = failures or {}
        self.calls: list[tuple[str, dict[str, str], dict[str, str]]] = []
        self._lock = threading.Lock()

    def __call__(self, url: str, params: dict[str, str], headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        page = int(params["page-number"])
        with self._lock:
            self.calls.append((url, dict(params), dict(headers)))
            queued = self.failures.get(page)
            if queued:
                return queued.pop(0), {"error": "synthetic failure"}
        if page in self.pages:
            return 200, self.pages[page]
        return 404, {"apiResponse": {"httpStatus": {"code": "404", "description": "Not Found"}}}

    def pages_requested(self) -> list[int]:
        return sorted({int(p["page-number"]) for _, p, _ in self.calls})


def make_source(transport: FakePages, **kwargs: Any) -> tuple[SisApiSource, list[float]]:
    sleeps: list[float] = []
    kwargs.setdefault("max_in_flight", 2)
    src = SisApiSource("id-123", "key-456", transport=transport, sleep=sleeps.append, clock=lambda: NOW, **kwargs)
    return src, sleeps


# ----------------------------------------------------------------------------- parsing


def test_parse_synthetic_page_skips_cancelled(synthetic_page: dict[str, Any]) -> None:
    rows = parse_sections(synthetic_page, NOW, FALL_2026)
    assert [r["section_id"] for r in rows] == ["29147", "34692"]
    by_id = {r["section_id"]: r for r in rows}

    lec = by_id["29147"]
    assert lec["course_key"] == "COMPSCI 61A"
    assert lec["subject"] == "COMPSCI"
    assert lec["catalog_number"] == "61A"
    assert lec["class_number"] == "001"
    assert lec["section_number"] == "001"
    assert lec["component"] == "LEC"
    assert lec["is_primary"] is True
    assert lec["session_id"] == "1"
    assert lec["term_id"] == "2268"
    assert (lec["enrolled_count"], lec["enroll_capacity"]) == (1472, 1750)
    assert (lec["waitlist_count"], lec["waitlist_capacity"]) == (0, 500)
    assert (lec["reserved_count"], lec["open_reserved"]) == (489, 11)  # section with seatReservations
    assert lec["status"] == "O"
    assert lec["section_status"] == "A"
    assert lec["source"] == "sis_api"
    assert lec["fetched_at"] == NOW

    dis = by_id["34692"]
    assert dis["is_primary"] is False
    assert dis["component"] == "DIS"
    assert dis["section_number"] == "101"
    assert dis["class_number"] == "001"
    assert (dis["waitlist_count"], dis["waitlist_capacity"]) == (2, 5)

    table = rows_to_table(rows)
    assert table.num_rows == 2


def test_parse_include_cancelled_keeps_the_x_section_and_strips_subject_spaces(synthetic_page: dict[str, Any]) -> None:
    rows = parse_sections(synthetic_page, NOW, FALL_2026, include_cancelled=True)
    assert len(rows) == 3
    cancelled = next(r for r in rows if r["section_id"] == "31555")
    assert cancelled["section_status"] == "X"
    assert cancelled["subject"] == "ELENG"  # "EL ENG" with the space removed
    assert cancelled["course_key"] == "ELENG 16A"  # spaces stripped, as classes.berkeley.edu spells it
    assert cancelled["status"] == "C"
    assert cancelled["enroll_capacity"] == 0
    rows_to_table(rows)


def test_parse_rejects_missing_envelope_and_malformed_section(synthetic_page: dict[str, Any]) -> None:
    with pytest.raises(ParseError):
        parse_sections({}, NOW, FALL_2026)
    with pytest.raises(ParseError):
        parse_sections({"apiResponse": {"response": {}}}, NOW, FALL_2026)
    broken = copy.deepcopy(synthetic_page)
    del class_sections(broken)[0]["enrollmentStatus"]
    with pytest.raises(ParseError, match="29147"):
        parse_sections(broken, NOW, FALL_2026)


def test_parse_keeps_payload_term_id_on_mismatch(synthetic_page: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    spring = TermSpec.from_name("Spring 2027")
    with caplog.at_level("WARNING", logger="scraper.sources.sis_api"):
        rows = parse_sections(synthetic_page, NOW, spring)
    assert {r["term_id"] for r in rows} == {"2268"}
    assert any("2272" in rec.message for rec in caplog.records)


# ----------------------------------------------------------------------------- fetch / pagination


def test_fetch_paginates_until_404(synthetic_page: dict[str, Any]) -> None:
    pages = {1: make_page(synthetic_page, [1, 2]), 2: make_page(synthetic_page, [3, 4]), 3: make_page(synthetic_page, [5])}
    transport = FakePages(pages)
    src, sleeps = make_source(transport, max_in_flight=2)

    result = src.fetch(FALL_2026)

    assert isinstance(result, FetchResult)
    assert result.scope == "full"
    assert [r["section_id"] for r in result.rows] == ["1", "2", "3", "4", "5"]
    assert result.universe_ids == {"1", "2", "3", "4", "5"}
    assert result.missing_ids == []
    assert result.observed_ids == ["1", "2", "3", "4", "5"]
    assert sleeps == []
    # batch 1 = pages 1,2; batch 2 = pages 3,4 (4 is the 404); nothing beyond
    assert transport.pages_requested() == [1, 2, 3, 4]
    url, params, headers = transport.calls[0]
    assert url == BASE_URL
    assert params == {"term-id": "2268", "page-number": "1", "page-size": "50"}
    assert headers["app_id"] == "id-123" and headers["app_key"] == "key-456"
    assert headers["User-Agent"].startswith("berkeley-waitlist-odds/")
    rows_to_table(result.rows)


def test_fetch_stops_on_empty_class_sections(synthetic_page: dict[str, Any]) -> None:
    pages = {1: make_page(synthetic_page, [10]), 2: make_page(synthetic_page, [])}
    transport = FakePages(pages)
    src, _ = make_source(transport, max_in_flight=1)

    result = src.fetch(FALL_2026)

    assert [r["section_id"] for r in result.rows] == ["10"]
    assert transport.pages_requested() == [1, 2]


def test_fetch_retries_5xx_then_succeeds(synthetic_page: dict[str, Any]) -> None:
    transport = FakePages({1: make_page(synthetic_page, [7])}, failures={1: [500, 503]})
    src, sleeps = make_source(transport, max_in_flight=1, backoff_base_s=0.5)

    result = src.fetch(FALL_2026)

    assert [r["section_id"] for r in result.rows] == ["7"]
    assert sleeps == [0.5, 1.0]  # exponential backoff between the two failed attempts
    assert sum(1 for _, p, _ in transport.calls if p["page-number"] == "1") == 3


def test_fetch_raises_after_retries_exhausted(synthetic_page: dict[str, Any]) -> None:
    transport = FakePages({1: make_page(synthetic_page, [7])}, failures={1: [502, 502, 502, 502]})
    src, sleeps = make_source(transport, max_in_flight=1, retries=3)

    with pytest.raises(SisApiError) as excinfo:
        src.fetch(FALL_2026)

    assert excinfo.value.status == 502 and excinfo.value.page == 1
    assert len(sleeps) == 3  # three retries, four attempts


def test_fetch_does_not_retry_403(synthetic_page: dict[str, Any]) -> None:
    transport = FakePages({1: make_page(synthetic_page, [7])}, failures={1: [403]})
    src, sleeps = make_source(transport, max_in_flight=1)

    with pytest.raises(SisApiError) as excinfo:
        src.fetch(FALL_2026)

    assert excinfo.value.status == 403
    assert sleeps == []


def test_fetch_skips_cancelled_and_reports_malformed_in_missing(synthetic_page: dict[str, Any]) -> None:
    page = copy.deepcopy(synthetic_page)
    extra = copy.deepcopy(class_sections(page)[0])
    extra["id"] = 99999
    del extra["enrollmentStatus"]["maxEnroll"]
    class_sections(page).append(extra)
    src, _ = make_source(FakePages({1: page}), max_in_flight=1)

    result = src.fetch(FALL_2026)

    assert [r["section_id"] for r in result.rows] == ["29147", "34692"]
    assert result.missing_ids == ["99999"]
    # cancelled 31555 is absent from the universe (tombstoned downstream); the malformed one stays in it
    assert result.universe_ids == {"29147", "34692", "99999"}


def test_fetch_limit_truncates_and_leaves_universe_unknown(synthetic_page: dict[str, Any]) -> None:
    pages = {1: make_page(synthetic_page, [1, 2]), 2: make_page(synthetic_page, [3, 4])}
    src, _ = make_source(FakePages(pages), max_in_flight=1)

    result = src.fetch(FALL_2026, limit=3)

    assert [r["section_id"] for r in result.rows] == ["1", "2", "3"]
    assert result.universe_ids is None


def test_fetch_include_cancelled_flag(synthetic_page: dict[str, Any]) -> None:
    src, _ = make_source(FakePages({1: synthetic_page}), max_in_flight=1, include_cancelled=True)
    result = src.fetch(FALL_2026)
    assert "31555" in result.universe_ids and len(result.rows) == 3


# ----------------------------------------------------------------------------- construction


def test_constructor_requires_credentials() -> None:
    with pytest.raises(ValueError):
        SisApiSource("", "key")
    with pytest.raises(ValueError):
        SisApiSource("id", "")


def test_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_APP_ID, raising=False)
    monkeypatch.delenv(ENV_APP_KEY, raising=False)
    assert SisApiSource.credentials_in_env() is False
    with pytest.raises(ValueError):
        SisApiSource.from_env()
    monkeypatch.setenv(ENV_APP_ID, "abc")
    monkeypatch.setenv(ENV_APP_KEY, "def")
    assert SisApiSource.credentials_in_env() is True
    src = SisApiSource.from_env(transport=FakePages({}))
    assert src.name == "sis_api"
