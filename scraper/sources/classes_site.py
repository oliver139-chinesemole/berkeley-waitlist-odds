"""classes.berkeley.edu source. See docs/DESIGN_A2.md section 5a and docs/PHASE0.md.

Listing: ``GET /search/class?f[0]=term:<facet>&page=N`` renders 18
``div.views-row`` entries per page. Section page: ``GET /content/<slug>``
embeds the SIS enrollment status in the ``drupal-settings-json`` script
under ``ucb.enrollment.available``.

Module-level functions are pure parsers (bytes in, values out) so they can be
tested against fixtures; ``ClassesSiteSource`` does the I/O.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import lxml.etree
import lxml.html

from scraper.http import HttpClient, HttpError
from scraper.schema import SnapshotRow
from scraper.sources.base import (
    FetchResult,
    ParseError,
    PrioritySpec,
    TermNotPublished,
    TermSpec,
    shard_of,
)

logger = logging.getLogger(__name__)

SOURCE_NAME = "classes_site"
DEFAULT_BASE_URL = "https://classes.berkeley.edu"
ROWS_PER_PAGE = 18
CATALOG_MAX_AGE = timedelta(hours=24)
# The section page exposes ucb.termDetails.sessionDescription ("2026 Fall")
# but no session id; every section we scrape is in the regular session.
DEFAULT_SESSION_ID = "1"

_TERM_FACET_RE = re.compile(r"term(?:%3A|:)(\d+)", re.IGNORECASE)
_SECTION_ID_RE = re.compile(r"#\s*(\d+)")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SectionRef:
    """One row of the term listing: identity plus the section page path."""

    section_id: str  # "30174"
    url_path: str  # "/content/2026-fall-aeroeng-10-001-lec-001"
    course_key: str  # "AEROENG 10" ("<SUBJECT> <CATALOG>", subject spaces removed)
    subject: str  # "AEROENG" (spaces removed: "EL ENG" -> "ELENG")
    catalog_number: str  # "10"
    class_number: str  # "001"
    section_number: str  # "001"
    component: str  # "LEC"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "SectionRef":
        try:
            return SectionRef(**{k: str(data[k]) for k in SectionRef.__dataclass_fields__})
        except KeyError as exc:
            raise ValueError(f"section ref missing key {exc}") from exc


# -- parsing --------------------------------------------------------------


def _parse_html(html: bytes | str) -> lxml.html.HtmlElement:
    """Parse a page; raises ParseError on an empty or unparsable document."""
    try:
        if isinstance(html, bytes):
            parser = lxml.html.HTMLParser(encoding="utf-8")
            return lxml.html.document_fromstring(html, parser=parser)
        return lxml.html.document_fromstring(html)
    except (lxml.etree.ParserError, lxml.etree.XMLSyntaxError, ValueError) as exc:
        raise ParseError(f"cannot parse HTML: {exc}") from exc


def _has_class(name: str) -> str:
    """XPath predicate matching an element whose class list contains ``name``."""
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {name} ')"


def _text(element: lxml.html.HtmlElement) -> str:
    return " ".join(element.text_content().split())


def parse_term_facets(html: bytes | str) -> list[tuple[str, str]]:
    """Return ``(anchor text, facet id)`` for every term facet link on a page.

    A facet link is an anchor whose href contains ``term%3A<digits>`` (or
    ``term:<digits>``). Pager links share that href shape but have no term
    text, so callers must match on the text.
    """
    doc = _parse_html(html)
    facets: list[tuple[str, str]] = []
    for anchor in doc.xpath("//a[@href]"):
        match = _TERM_FACET_RE.search(anchor.get("href", ""))
        if match:
            facets.append((_text(anchor), match.group(1)))
    return facets


def find_term_facet_id(html: bytes | str, term_name: str) -> str | None:
    """Facet id whose link text starts with ``term_name`` followed by a space
    or "(" (e.g. ``Fall 2026 (6131)``), or equals it; None when absent."""
    wanted = " ".join(term_name.split()).lower()
    for text, facet_id in parse_term_facets(html):
        candidate = text.lower()
        if candidate == wanted or candidate.startswith(wanted + " ") or candidate.startswith(wanted + "("):
            return facet_id
    return None


def _split_course(name: str) -> tuple[str, str, str]:
    """``"ELENG 16A"`` -> ``("ELENG 16A", "ELENG", "16A")``.

    classes.berkeley.edu spells subjects without spaces (ELENG, POLSCI, NUCENG);
    should a spaced form ever appear ("EL ENG 16A") the spaces are stripped so
    ``course_key`` stays ``"<SUBJECT> <CATALOG>"`` with the schema's space-free
    subject, the same key sis_api and berkeleytime produce.
    """
    name = " ".join(name.split())
    subject_display, sep, catalog = name.rpartition(" ")
    if not sep or not subject_display or not catalog:
        raise ParseError(f"cannot split course name {name!r}")
    subject = subject_display.replace(" ", "")
    return f"{subject} {catalog}", subject, catalog


def _parse_listing_row(row: lxml.html.HtmlElement) -> SectionRef:
    """Build a SectionRef from one ``views-row``; ParseError when a part is missing."""
    number_nodes = row.xpath(f".//*[{_has_class('st--section-number')}]")
    if not number_nodes:
        raise ParseError("row has no st--section-number")
    id_match = _SECTION_ID_RE.search(_text(number_nodes[0]))
    if not id_match:
        raise ParseError(f"row section number {_text(number_nodes[0])!r} has no '#<digits>'")
    names = row.xpath(f".//span[{_has_class('st--section-name')}]")
    counts = row.xpath(f".//span[{_has_class('st--section-count')}]")
    codes = row.xpath(f".//span[{_has_class('st--section-code')}]")
    hrefs = row.xpath(".//a[starts-with(@href, '/content/')]/@href")
    if not names or len(counts) < 2 or not codes or not hrefs:
        raise ParseError(
            f"row #{id_match.group(1)} incomplete: names={len(names)} counts={len(counts)} "
            f"codes={len(codes)} hrefs={len(hrefs)}"
        )
    course_key, subject, catalog = _split_course(_text(names[0]))
    return SectionRef(
        section_id=id_match.group(1),
        url_path=str(hrefs[0]).strip(),
        course_key=course_key,
        subject=subject,
        catalog_number=catalog,
        class_number=_text(counts[0]),
        section_number=_text(counts[1]),
        component=_text(codes[0]),
    )


def parse_listing_page(html: bytes | str) -> list[SectionRef]:
    """Parse every ``div.views-row`` on a listing page, in page order.

    Malformed rows are skipped with a warning; if a page has rows but none
    parse, ParseError is raised because that signals a layout change.
    """
    doc = _parse_html(html)
    rows = doc.xpath(f"//div[{_has_class('views-row')}]")
    refs: list[SectionRef] = []
    for row in rows:
        article = row.xpath("./article")
        try:
            refs.append(_parse_listing_row(article[0] if article else row))
        except ParseError as exc:
            logger.warning("skipping listing row: %s", exc)
    if rows and not refs:
        raise ParseError(f"none of {len(rows)} listing rows parsed; layout changed?")
    return refs


def _load_drupal_settings(doc: lxml.html.HtmlElement) -> dict[str, Any]:
    scripts = doc.xpath("//script[@data-drupal-selector='drupal-settings-json']")
    if not scripts:
        raise ParseError("no drupal-settings-json script on page")
    try:
        settings = json.loads(scripts[0].text or "")
    except json.JSONDecodeError as exc:
        raise ParseError(f"drupal-settings-json is not JSON: {exc}") from exc
    if not isinstance(settings, dict):
        raise ParseError("drupal-settings-json is not an object")
    return settings


def _dig(mapping: Any, *keys: str) -> Any:
    """Nested lookup that raises ParseError naming the missing path."""
    current = mapping
    for i, key in enumerate(keys):
        if not isinstance(current, dict) or key not in current:
            raise ParseError(f"missing key {'.'.join(keys[: i + 1])!r} in drupal settings")
        current = current[key]
    return current


def _as_int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ParseError(f"{name}={value!r} is not an integer") from exc


def _as_optional_int(value: Any, name: str) -> int | None:
    return None if value is None else _as_int(value, name)


def _page_term_id(doc: lxml.html.HtmlElement) -> str | None:
    """The ``data-term="NNNN"`` attribute carried by the textbook widget."""
    values = doc.xpath("//*[@data-term]/@data-term")
    for value in values:
        text = str(value).strip()
        if text:
            return text
    return None


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def parse_section_page(html: bytes | str, ref: SectionRef, fetched_at: datetime, term: TermSpec) -> SnapshotRow:
    """Turn a section page into a SnapshotRow.

    Reads ``ucb.enrollment.available`` from the drupal-settings-json blob; the
    blob's ``id`` must equal ``ref.section_id`` (else ParseError). ``term_id``
    comes from the page's ``data-term`` attribute, falling back to
    ``term.sis_term_id`` when absent; a disagreement is logged and the page
    value wins. ``section_status`` and ``is_primary`` are None because the
    page does not expose them; ``session_id`` is "1" (regular session).
    """
    doc = _parse_html(html)
    settings = _load_drupal_settings(doc)
    available = _dig(settings, "ucb", "enrollment", "available")
    page_id = _as_int(_dig(available, "id"), "ucb.enrollment.available.id")
    try:
        expected_id = int(ref.section_id)
    except ValueError as exc:
        raise ParseError(f"ref.section_id {ref.section_id!r} is not numeric") from exc
    if page_id != expected_id:
        raise ParseError(f"page is section {page_id}, expected {expected_id} ({ref.url_path})")
    status = _dig(available, "enrollmentStatus")
    if not isinstance(status, dict):
        raise ParseError("enrollmentStatus is not an object")

    term_id = _page_term_id(doc)
    if term_id is None:
        term_id = term.sis_term_id
    elif term_id != term.sis_term_id:
        logger.warning(
            "section %s: page data-term=%s differs from expected %s for %s; using page value",
            ref.section_id,
            term_id,
            term.sis_term_id,
            term.name,
        )

    return SnapshotRow(
        fetched_at=_as_utc(fetched_at),
        term_id=term_id,
        section_id=ref.section_id,
        course_key=ref.course_key,
        subject=ref.subject,
        catalog_number=ref.catalog_number,
        class_number=ref.class_number,
        section_number=ref.section_number,
        component=ref.component,
        is_primary=None,
        session_id=DEFAULT_SESSION_ID,
        enrolled_count=_as_int(_dig(status, "enrolledCount"), "enrolledCount"),
        enroll_capacity=_as_int(_dig(status, "maxEnroll"), "maxEnroll"),
        waitlist_count=_as_int(_dig(status, "waitlistedCount"), "waitlistedCount"),
        waitlist_capacity=_as_int(_dig(status, "maxWaitlist"), "maxWaitlist"),
        reserved_count=_as_optional_int(status.get("reservedCount"), "reservedCount"),
        open_reserved=_as_optional_int(status.get("openReserved"), "openReserved"),
        status=str(_dig(status, "status", "code")),
        section_status=None,
        source=SOURCE_NAME,
    )


# -- source ---------------------------------------------------------------


class ClassesSiteSource:
    """Scrapes classes.berkeley.edu section pages. ``name == "classes_site"``.

    ``now`` (UTC datetime) and ``clock`` (monotonic seconds) are injectable
    for tests; the ``client`` provides ``get`` and ``get_many``.
    """

    name = SOURCE_NAME

    def __init__(
        self,
        client: HttpClient,
        data_root: Path,
        n_shards: int = 8,
        base_url: str = DEFAULT_BASE_URL,
        *,
        catalog_max_pages: int | None = None,
        now: Callable[[], datetime] = _utcnow,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if n_shards < 0:
            raise ValueError("n_shards must be >= 0")
        if catalog_max_pages is not None and catalog_max_pages < 1:
            raise ValueError("catalog_max_pages must be >= 1")
        self._client = client
        self._data_root = Path(data_root)
        self.n_shards = int(n_shards)
        self._base_url = base_url.rstrip("/")
        # Debug knob (scraper.fetch --catalog-max-pages): cap listing pages read.
        self.catalog_max_pages = catalog_max_pages
        self._now = now
        self._clock = clock

    # Pure parser exposed on the class too, so callers holding a source
    # instance need not import the module function.
    parse_section_page = staticmethod(parse_section_page)

    # -- urls and paths ----------------------------------------------------

    def search_url(self) -> str:
        return f"{self._base_url}/search/class"

    def listing_url(self, facet_id: str, page: int) -> str:
        return f"{self._base_url}/search/class?f%5B0%5D=term%3A{facet_id}&page={page}"

    def section_url(self, ref: SectionRef) -> str:
        return f"{self._base_url}{ref.url_path}"

    def catalog_path(self, term_id: str) -> Path:
        return self._data_root / "catalog" / term_id / "sections.json"

    # -- discovery ---------------------------------------------------------

    def discover_term_facet_id(self, term_name: str) -> str:
        """Facet id of ``term_name`` on the search page; TermNotPublished if absent."""
        url = self.search_url()
        html = self._client.get(url)
        facet_id = find_term_facet_id(html, term_name)
        if facet_id is None:
            raise TermNotPublished(f"no term facet for {term_name!r} on {url}")
        logger.info("term %s has facet id %s", term_name, facet_id)
        return facet_id

    # -- listing -----------------------------------------------------------

    def list_sections(
        self,
        facet_id: str,
        max_pages: int | None = None,
        *,
        term_id: str | None = None,
    ) -> list[SectionRef]:
        """All sections of the term (or the first ``max_pages`` pages).

        With ``term_id`` the full listing is cached at
        ``catalog/<term_id>/sections.json`` and reused while younger than 24h
        (and, when ``max_pages`` is given, at least ``max_pages * 18`` long).
        Partial listings (``max_pages`` set) are never written to the cache.
        Raises HttpError when a listing page cannot be fetched.
        """
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be >= 1")
        if term_id:
            cached = self._load_catalog(term_id, facet_id, max_pages)
            if cached is not None:
                logger.info("reusing cached listing for term %s (%d sections)", term_id, len(cached))
                return cached
        refs = self._crawl_listing(facet_id, max_pages)
        if term_id and max_pages is None:
            self._save_catalog(term_id, facet_id, refs)
        return refs

    def _crawl_listing(self, facet_id: str, max_pages: int | None) -> list[SectionRef]:
        refs: list[SectionRef] = []
        seen: set[str] = set()
        page = 0
        while max_pages is None or page < max_pages:
            url = self.listing_url(facet_id, page)
            try:
                html = self._client.get(url)
            except HttpError as exc:
                if exc.status == 404 and page > 0:
                    logger.info("listing ended with 404 at page %d", page)
                    break
                raise
            page_refs = parse_listing_page(html)
            if not page_refs:
                break
            for ref in page_refs:
                if ref.section_id not in seen:
                    seen.add(ref.section_id)
                    refs.append(ref)
            page += 1
        logger.info("listed %d sections over %d pages for facet %s", len(refs), page, facet_id)
        return refs

    def _load_catalog(self, term_id: str, facet_id: str, max_pages: int | None) -> list[SectionRef] | None:
        path = self.catalog_path(term_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            listed_at = _as_utc(datetime.fromisoformat(str(payload["listed_at"])))
            sections = [SectionRef.from_dict(d) for d in payload["sections"]]
            cached_facet = str(payload.get("facet_id", ""))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("ignoring unreadable catalog %s: %s", path, exc)
            return None
        if self._now() - listed_at >= CATALOG_MAX_AGE:
            return None
        if cached_facet != str(facet_id):
            logger.info("cached catalog is for facet %s, not %s; refetching", cached_facet, facet_id)
            return None
        if max_pages is not None and len(sections) < max_pages * ROWS_PER_PAGE:
            return None
        return sections

    def _save_catalog(self, term_id: str, facet_id: str, refs: list[SectionRef]) -> Path:
        path = self.catalog_path(term_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "term_id": term_id,
            "facet_id": str(facet_id),
            "listed_at": self._now().isoformat(),
            "sections": [ref.to_dict() for ref in refs],
        }
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, indent=0), encoding="utf-8")
        os.replace(tmp, path)
        logger.info("wrote %s (%d sections)", path, len(refs))
        return path

    # -- fetch -------------------------------------------------------------

    @staticmethod
    def _normalise_shard(shard: tuple[int, int] | int | None, n_shards: int) -> tuple[int, int] | None:
        """Accept ``(k, n)`` or a bare run index ``k`` (then ``n = n_shards``)."""
        if shard is None:
            return None
        if isinstance(shard, int):
            if n_shards <= 0:
                return None
            return (shard % n_shards, n_shards)
        k, n = int(shard[0]), int(shard[1])
        if n <= 0 or not 0 <= k < n:
            raise ValueError(f"shard {shard!r} must satisfy 0 <= k < n")
        return (k, n)

    def _select(
        self,
        refs: list[SectionRef],
        priority: PrioritySpec | None,
        shard: tuple[int, int] | None,
    ) -> list[SectionRef]:
        """Priority matches first (listing order), then shard k of n of the remainder.

        Priority sections are scheduled first so that a time-budget cutoff only
        trims the rotating shard, never the courses promised the 30-minute cadence
        (measured 2026-09-18: 886 priority + 613 to 701 shard pages per run at
        n_shards=8 against a 1,500 s budget at about one page per second).
        """
        if priority is None:
            return list(refs)
        first: list[SectionRef] = []
        rest: list[SectionRef] = []
        for ref in refs:
            if priority.matches(ref.course_key):
                first.append(ref)
            elif shard is not None and shard_of(ref.section_id, shard[1]) == shard[0]:
                rest.append(ref)
        return first + rest

    def fetch(
        self,
        term: TermSpec,
        *,
        priority: PrioritySpec | None = None,
        shard: tuple[int, int] | None = None,
        time_budget_s: float | None = None,
        limit: int | None = None,
    ) -> FetchResult:
        """Discover the term, list its sections, select, and fetch the pages.

        Scope is "full" (every listed section, ``universe_ids`` = all listed
        ids) when ``priority`` is None, else "priority" (priority matches
        union shard members, ``universe_ids`` None). ``limit`` caps the
        selection after it is made and shortens the listing to
        ``ceil(limit / 18) + 1`` pages; under ``limit`` the universe is
        unknown, so ``universe_ids`` is None. Listing time counts against
        ``time_budget_s``; every HTTP failure, parse failure, and unattempted
        URL lands in ``missing_ids``. Raises TermNotPublished or HttpError
        when discovery or listing fails outright.
        """
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        started = self._clock()
        facet_id = self.discover_term_facet_id(term.name)
        max_pages = self._listing_page_cap(limit)
        refs = self.list_sections(facet_id, max_pages, term_id=term.sis_term_id)

        shard_pair = self._normalise_shard(shard, self.n_shards)
        if priority is None:
            scope = "full"
            shard_label = ""
            priority_sha = ""
            universe_ids: set[str] | None = {ref.section_id for ref in refs}
        else:
            scope = "priority"
            shard_label = f"{shard_pair[0]}/{shard_pair[1]}" if shard_pair else ""
            priority_sha = priority.sha
            universe_ids = None
        selected = self._select(refs, priority, shard_pair if priority is not None else None)
        if limit is not None:
            selected = selected[:limit]
        if max_pages is not None:
            # A capped listing is not the term universe: never tombstone against it.
            universe_ids = None

        remaining = None
        if time_budget_s is not None:
            remaining = max(0.0, float(time_budget_s) - (self._clock() - started))
        rows, missing_ids = self._fetch_pages(selected, term, remaining)

        logger.info(
            "classes_site term=%s scope=%s shard=%s listed=%d selected=%d observed=%d missing=%d elapsed=%.1fs",
            term.sis_term_id,
            scope,
            shard_label or "-",
            len(refs),
            len(selected),
            len(rows),
            len(missing_ids),
            self._clock() - started,
        )
        return FetchResult(
            rows=rows,
            missing_ids=missing_ids,
            universe_ids=universe_ids,
            scope=scope,
            shard=shard_label,
            priority_sha=priority_sha,
        )

    def _listing_page_cap(self, limit: int | None) -> int | None:
        """Pages to list: ``ceil(limit / 18) + 1`` under ``limit``, capped by
        ``catalog_max_pages`` when set; None means the whole term."""
        caps = [c for c in (self.catalog_max_pages, None if limit is None else math.ceil(limit / ROWS_PER_PAGE) + 1) if c]
        return min(caps) if caps else None

    def _fetch_pages(
        self,
        selected: list[SectionRef],
        term: TermSpec,
        time_budget_s: float | None,
    ) -> tuple[list[SnapshotRow], list[str]]:
        """Fetch and parse the selected section pages; results in selection order."""
        order = {self.section_url(ref): i for i, ref in enumerate(selected)}
        ref_by_url = {self.section_url(ref): ref for ref in selected}
        parsed: dict[int, SnapshotRow] = {}
        failed: dict[int, str] = {}
        lock = threading.Lock()

        def on_result(url: str, payload: bytes | HttpError) -> None:
            ref = ref_by_url[url]
            index = order[url]
            if isinstance(payload, HttpError):
                level = logging.DEBUG if payload.budget_exhausted else logging.WARNING
                logger.log(level, "section %s not fetched: %s", ref.section_id, payload)
                with lock:
                    failed[index] = ref.section_id
                return
            fetched_at = self._now()
            try:
                row = parse_section_page(payload, ref, fetched_at, term)
            except ParseError as exc:
                logger.warning("section %s not parsed: %s", ref.section_id, exc)
                with lock:
                    failed[index] = ref.section_id
                return
            with lock:
                parsed[index] = row

        self._client.get_many(list(order), on_result, time_budget_s=time_budget_s)
        rows = [parsed[i] for i in sorted(parsed)]
        missing_ids = [failed[i] for i in sorted(failed)]
        return rows, missing_ids
