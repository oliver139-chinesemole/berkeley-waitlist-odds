"""classes.berkeley.edu source. See docs/DESIGN_A2.md sections 5a, 13 and 14, and docs/PHASE0.md.

Discovery is self-contained on the site and uses only paths its robots.txt
allows (``/search/`` is disallowed; Berkeleytime is unreachable from GitHub's
network). Every section page is a Drupal node with a sequential id, served
both at ``/node/<id>`` and at its alias ``/content/<year>-<sem>-<subject>-
<catalog>-<class#>-<component>-<section#>``. Two allowed resources give a
complete index over time:

- ``/rss.xml``: the 10 newest nodes with their ids (``<guid>``), titles
  (``"2026 Fall AEROENG 10 001 LEC 001"``) and aliases.
- ``/node/<id>``: the page itself (200) or 404 for a missing id.

A site-wide watermark (``catalog/site.json``) records the highest node id
probed. Each run reads the feed, adds its items to the right term catalog,
and probes the ids between the watermark and the newest feed id (bounded per
run). A probed page that is a section of the current term is also used as
that run's observation of the section, so discovery is never wasted work.
Sections of other terms go to their own catalog files.

Section page: ``GET /content/<slug>`` (or ``/node/<id>``) embeds the SIS
enrollment status in the ``drupal-settings-json`` script under
``ucb.enrollment.available``.

Module-level functions are pure (bytes or strings in, values out) so they can
be tested against fixtures; ``ClassesSiteSource`` does the I/O.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field, replace
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
CATALOG_FILENAME = "catalog.json"
SITE_STATE_FILENAME = "site.json"
LEGACY_CATALOG_FILENAME = "sections.json"  # listing-based file written before 2026-09-19
CATALOG_VERSION = 3
ABSENT_REPROBE_AFTER = timedelta(days=7)  # retry a 404 slug after this
MAX_REPROBES_PER_RUN = 100
MAX_NODE_PROBES_PER_RUN = 400  # ids enumerated per run while catching up
NODE_PROBE_BUDGET_SHARE = 0.3  # at most this share of the remaining budget goes to enumeration
INITIAL_LOOKBACK_NODES = 2000  # first run ever: sweep this many ids below the newest feed id
# Primary-section components that never carry a waitlist in practice
# (independent study, group study, field work, tutorials...). They are
# excluded from the universe; the listing-era baseline showed them as noise.
SELF_STUDY_COMPONENTS = frozenset(
    {"IND", "GRP", "FLD", "TUT", "INT", "SLF", "PRA", "REC", "SES", "CLN", "WOR", "REA", "WBD", "VOL", "DEM"}
)
# The section page exposes ucb.termDetails.sessionDescription ("2026 Fall")
# but no session id; every section we scrape is in the regular session.
DEFAULT_SESSION_ID = "1"

_TITLE_RE = re.compile(r"^\s*(\d{4})\s+(Spring|Summer|Fall)\s+(\S+)\s+(\S+)\s+(\S+)\s+([A-Za-z]{2,4})\s+(\S+)\s*$")
_SLUG_RE = re.compile(r"^/content/(\d{4})-(spring|summer|fall)-(.+)$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SectionRef:
    """A section known to the catalog plus its page path.

    ``section_id`` is ``""`` until the page has been fetched once (the SIS id
    is only on the page); ``node_id`` is the Drupal node id when known;
    ``last_status`` is the HTTP status of the last probe (200, 404, ...) or
    None when never probed.
    """

    section_id: str  # "30174" or "" when not yet learned
    url_path: str  # "/content/2026-fall-aeroeng-10-001-lec-001"
    course_key: str  # "AEROENG 10" ("<SUBJECT> <CATALOG>", subject spaces removed)
    subject: str  # "AEROENG"
    catalog_number: str  # "10"
    class_number: str  # "001"
    section_number: str  # "001"
    component: str  # "LEC"
    last_status: int | None = None
    probed_at: str | None = None  # ISO-8601 UTC of the last probe
    node_id: int | None = None
    title: str = ""  # course title as the page prints it (sf--course-title); "" until a page was read
    instructors: str = ""  # comma-separated as the page prints them (sf--instructors); "" until read

    @property
    def absent(self) -> bool:
        return self.last_status == 404

    @property
    def key(self) -> str:
        """Stable identity used for shard assignment: the page path."""
        return self.url_path

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "SectionRef":
        try:
            status = data.get("last_status")
            node = data.get("node_id")
            return SectionRef(
                section_id=str(data.get("section_id") or ""),
                url_path=str(data["url_path"]),
                course_key=str(data["course_key"]),
                subject=str(data["subject"]),
                catalog_number=str(data["catalog_number"]),
                class_number=str(data["class_number"]),
                section_number=str(data["section_number"]),
                component=str(data["component"]),
                last_status=None if status is None else int(status),
                probed_at=None if data.get("probed_at") is None else str(data["probed_at"]),
                node_id=None if node is None else int(node),
                title=str(data.get("title") or ""),
                instructors=str(data.get("instructors") or ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"section ref malformed: {exc}") from exc


@dataclass(frozen=True)
class PageIdentity:
    """What a node title or slug says about a section page."""

    term_name: str  # "Fall 2026"
    subject: str  # "AEROENG"
    catalog_number: str  # "10"
    class_number: str  # "001"
    component: str  # "LEC"
    section_number: str  # "001"

    @property
    def course_key(self) -> str:
        return f"{self.subject} {self.catalog_number}"


# -- pure parsers ------------------------------------------------------------


def parse_node_title(title: str) -> PageIdentity | None:
    """``"2026 Fall AEROENG 10 001 LEC 001"`` (with or without a
    ``" | UCB Class Search"`` suffix) -> PageIdentity; None if not a section title."""
    text = title.split("|", 1)[0]
    m = _TITLE_RE.match(text)
    if not m:
        return None
    year, semester, subject, catalog, class_number, component, section_number = m.groups()
    return PageIdentity(
        term_name=f"{semester.capitalize()} {year}",
        subject=subject.replace(" ", "").upper(),
        catalog_number=catalog.upper(),
        class_number=class_number.upper(),
        component=component.upper(),
        section_number=section_number.upper(),
    )


def parse_rss(xml: bytes | str) -> list[tuple[int, str, str]]:
    """``(node id, url path, title)`` for every item of the site feed, newest first.

    Tolerant of namespaces and CDATA; items without a numeric guid or a
    ``/content/`` link are skipped.
    """
    text = xml.decode("utf-8", "ignore") if isinstance(xml, bytes) else xml
    out: list[tuple[int, str, str]] = []
    for item in re.findall(r"<item>(.*?)</item>", text, re.S):
        guid = re.search(r"<guid[^>]*>\s*(?:<!\[CDATA\[)?\s*(\d+)", item)
        link = re.search(r"<link>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)", item)
        title = re.search(r"<title>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</title>", item, re.S)
        if not guid or not link:
            continue
        path = link.group(1)
        i = path.find("/content/")
        if i < 0:
            continue
        out.append((int(guid.group(1)), path[i:], title.group(1) if title else ""))
    return out


def parse_section_ref(html: bytes | str, *, node_id: int | None = None) -> tuple[SectionRef, PageIdentity] | None:
    """Identity of a fetched section page (via ``/node/<id>`` or its alias):
    the canonical ``/content/`` slug and the ``<title>``. None when the page is
    not a section page (no enrollment blob or no parsable title)."""
    doc = _parse_html(html)
    if not doc.xpath("//script[@data-drupal-selector='drupal-settings-json']"):
        return None
    titles = doc.xpath("//title/text()")
    identity = parse_node_title(str(titles[0])) if titles else None
    canonical = doc.xpath("//link[@rel='canonical']/@href")
    if identity is None or not canonical:
        return None
    href = str(canonical[0])
    i = href.find("/content/")
    if i < 0:
        return None
    if node_id is None:
        nid = doc.xpath("//*[@data-history-node-id]/@data-history-node-id")
        node_id = int(nid[0]) if nid and str(nid[0]).isdigit() else None
    title, instructors = parse_section_meta(doc)
    ref = SectionRef(
        section_id="",
        url_path=href[i:],
        course_key=identity.course_key,
        subject=identity.subject,
        catalog_number=identity.catalog_number,
        class_number=identity.class_number,
        section_number=identity.section_number,
        component=identity.component,
        node_id=node_id,
        title=title,
        instructors=instructors,
    )
    return ref, identity


def ref_from_feed_item(node_id: int, url_path: str, title: str) -> tuple[SectionRef, PageIdentity] | None:
    identity = parse_node_title(title)
    if identity is None or not _SLUG_RE.match(url_path):
        return None
    ref = SectionRef(
        section_id="",
        url_path=url_path,
        course_key=identity.course_key,
        subject=identity.subject,
        catalog_number=identity.catalog_number,
        class_number=identity.class_number,
        section_number=identity.section_number,
        component=identity.component,
        node_id=node_id,
    )
    return ref, identity


def merge_catalog(existing: list[SectionRef], fresh: list[SectionRef]) -> tuple[list[SectionRef], int]:
    """Union keyed by ``url_path``: known entries keep their learned id and
    probe state (gaining a node id if they lacked one, and a title or
    instructors when the fresh ref carries a non-empty one), new entries are
    appended. Returns the merged list and the number added."""
    by_path = {ref.url_path: ref for ref in existing}
    added = 0
    for ref in fresh:
        current = by_path.get(ref.url_path)
        if current is None:
            by_path[ref.url_path] = ref
            added += 1
            continue
        changes: dict[str, Any] = {}
        if current.node_id is None and ref.node_id is not None:
            changes["node_id"] = ref.node_id
        if ref.title and ref.title != current.title:
            changes["title"] = ref.title
        if ref.instructors and ref.instructors != current.instructors:
            changes["instructors"] = ref.instructors
        if changes:
            by_path[ref.url_path] = replace(current, **changes)
    return list(by_path.values()), added


# -- section page parsing ----------------------------------------------------


def _parse_html(html: bytes | str) -> lxml.html.HtmlElement:
    """Parse a page; raises ParseError on an empty or unparsable document."""
    try:
        if isinstance(html, bytes):
            parser = lxml.html.HTMLParser(encoding="utf-8")
            return lxml.html.document_fromstring(html, parser=parser)
        return lxml.html.document_fromstring(html)
    except (lxml.etree.ParserError, lxml.etree.XMLSyntaxError, ValueError) as exc:
        raise ParseError(f"cannot parse HTML: {exc}") from exc


def parse_section_meta(html: bytes | str | lxml.html.HtmlElement) -> tuple[str, str]:
    """``(course title, instructors)`` as the page prints them in its
    ``sf--course-title`` and ``sf--instructors`` elements, whitespace collapsed;
    ``""`` for an element that is not there. Read off the page a run fetches
    anyway, so it costs no request (Q7, 2026-09-23)."""
    doc = html if isinstance(html, lxml.html.HtmlElement) else _parse_html(html)

    def text_of(cls: str) -> str:
        nodes = doc.xpath(f"//*[contains(concat(' ', normalize-space(@class), ' '), ' {cls} ')]")
        return " ".join(nodes[0].text_content().split()) if nodes else ""

    return text_of("sf--course-title"), text_of("sf--instructors")


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
    if isinstance(value, bool):
        raise ParseError(f"{name}={value!r} is not an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ParseError(f"{name}={value!r} is not an integer") from exc


def _as_optional_int(value: Any, name: str) -> int | None:
    return None if value is None else _as_int(value, name)


def _page_term_id(doc: lxml.html.HtmlElement) -> str | None:
    """The ``data-term="NNNN"`` attribute carried by the textbook widget."""
    for value in doc.xpath("//*[@data-term]/@data-term"):
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

    Reads ``ucb.enrollment.available`` from the drupal-settings-json blob.
    When ``ref.section_id`` is known the blob's ``id`` must equal it (else
    ParseError); when it is ``""`` the page's id is adopted. ``term_id``
    comes from the page's ``data-term`` attribute, falling back to
    ``term.sis_term_id`` when absent; a disagreement is logged and the page
    value wins. ``section_status`` and ``is_primary`` are None because the
    page does not expose them; ``session_id`` is "1" (regular session).
    """
    doc = _parse_html(html)
    settings = _load_drupal_settings(doc)
    available = _dig(settings, "ucb", "enrollment", "available")
    page_id = _as_int(_dig(available, "id"), "ucb.enrollment.available.id")
    if ref.section_id:
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
            page_id,
            term_id,
            term.sis_term_id,
            term.name,
        )

    return SnapshotRow(
        fetched_at=_as_utc(fetched_at),
        term_id=term_id,
        section_id=str(page_id),
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


# -- state on disk -----------------------------------------------------------


@dataclass
class _Catalog:
    term: TermSpec
    refs: list[SectionRef]
    dirty: bool = False

    def by_path(self) -> dict[str, SectionRef]:
        return {r.url_path: r for r in self.refs}


MAX_RETRY_IDS = 200  # node ids that answered with an error (not 404) are retried on later runs


@dataclass
class _SiteState:
    max_node_probed: int | None = None  # every id <= this has been probed (or predates the watermark)
    max_node_seen: int | None = None  # highest id seen in the feed
    retry_ids: list[int] = field(default_factory=list)  # probed but not resolved (HTTP error other than 404)
    updated_at: str | None = None
    dirty: bool = False


@dataclass
class _Discovery:
    """What one run's discovery pass produced."""

    feed_items: int = 0
    probed: int = 0
    found_sections: int = 0
    prefetched_rows: dict[str, SnapshotRow] = field(default_factory=dict)  # url_path -> row for the current term
    prefetched_refs: dict[str, SectionRef] = field(default_factory=dict)


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
        n_shards: int = 12,
        base_url: str = DEFAULT_BASE_URL,
        *,
        max_node_probes: int = MAX_NODE_PROBES_PER_RUN,
        catalog_max_pages: int | None = None,  # accepted for CLI compatibility; unused
        now: Callable[[], datetime] = _utcnow,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if n_shards < 0:
            raise ValueError("n_shards must be >= 0")
        self._client = client
        self._data_root = Path(data_root)
        self.n_shards = int(n_shards)
        self._base_url = base_url.rstrip("/")
        self.max_node_probes = int(max_node_probes)
        if catalog_max_pages is not None:
            logger.info("catalog_max_pages is ignored: discovery no longer reads a listing")
        self._now = now
        self._clock = clock

    parse_section_page = staticmethod(parse_section_page)

    # -- urls and paths --------------------------------------------------------

    def section_url(self, ref: SectionRef) -> str:
        return f"{self._base_url}{ref.url_path}"

    def node_url(self, node_id: int) -> str:
        return f"{self._base_url}/node/{node_id}"

    def rss_url(self) -> str:
        return f"{self._base_url}/rss.xml"

    def catalog_path(self, term_id: str) -> Path:
        return self._data_root / "catalog" / term_id / CATALOG_FILENAME

    def legacy_catalog_path(self, term_id: str) -> Path:
        return self._data_root / "catalog" / term_id / LEGACY_CATALOG_FILENAME

    def site_state_path(self) -> Path:
        return self._data_root / "catalog" / SITE_STATE_FILENAME

    # -- catalog files -----------------------------------------------------------

    def load_catalog(self, term: TermSpec) -> _Catalog:
        """The on-disk catalog for the term (possibly empty), seeded once from
        a legacy listing file if present."""
        path = self.catalog_path(term.sis_term_id)
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                refs = [SectionRef.from_dict(d) for d in payload["sections"]]
                return _Catalog(term=term, refs=refs)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.warning("ignoring unreadable catalog %s: %s", path, exc)
        legacy = self.legacy_catalog_path(term.sis_term_id)
        if legacy.exists():
            try:
                payload = json.loads(legacy.read_text(encoding="utf-8"))
                refs = [
                    SectionRef.from_dict(d)
                    for d in payload["sections"]
                    if str(d.get("component", "")).upper() not in SELF_STUDY_COMPONENTS
                ]
                logger.info("seeded catalog from legacy listing %s (%d sections kept)", legacy, len(refs))
                return _Catalog(term=term, refs=refs, dirty=True)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.warning("ignoring unreadable legacy catalog %s: %s", legacy, exc)
        return _Catalog(term=term, refs=[])

    def _save_catalog(self, catalog: _Catalog) -> Path:
        path = self.catalog_path(catalog.term.sis_term_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CATALOG_VERSION,
            "term_id": catalog.term.sis_term_id,
            "term_name": catalog.term.name,
            "source": "classes.berkeley.edu rss.xml + /node/<id> enumeration + section page probes",
            "updated_at": self._now().isoformat(),
            "sections": [ref.to_dict() for ref in sorted(catalog.refs, key=lambda r: r.url_path)],
        }
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, indent=0, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        catalog.dirty = False
        logger.info("wrote %s (%d sections)", path, len(catalog.refs))
        return path

    def load_site_state(self) -> _SiteState:
        path = self.site_state_path()
        if not path.exists():
            return _SiteState()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            probed = payload.get("max_node_probed")
            seen = payload.get("max_node_seen")
            retry = [int(x) for x in payload.get("retry_ids") or []]
            return _SiteState(
                max_node_probed=None if probed is None else int(probed),
                max_node_seen=None if seen is None else int(seen),
                retry_ids=retry[:MAX_RETRY_IDS],
                updated_at=payload.get("updated_at"),
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("ignoring unreadable site state %s: %s", path, exc)
            return _SiteState()

    def _save_site_state(self, state: _SiteState) -> Path:
        path = self.site_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "max_node_probed": state.max_node_probed,
            "max_node_seen": state.max_node_seen,
            "retry_ids": sorted(set(state.retry_ids))[:MAX_RETRY_IDS],
            "updated_at": self._now().isoformat(),
        }
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, indent=0, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        state.dirty = False
        return path

    # -- discovery ---------------------------------------------------------------

    def _catalog_for(self, catalogs: dict[str, _Catalog], term_name: str) -> _Catalog | None:
        try:
            term = TermSpec.from_name(term_name)
        except ValueError:
            return None
        if term.sis_term_id not in catalogs:
            catalogs[term.sis_term_id] = self.load_catalog(term)
        return catalogs[term.sis_term_id]

    def _add_ref(self, catalog: _Catalog, ref: SectionRef) -> bool:
        if ref.component in SELF_STUDY_COMPONENTS:
            return False
        merged, added = merge_catalog(catalog.refs, [ref])
        if added or merged != catalog.refs:
            catalog.refs = merged
            catalog.dirty = True
        return bool(added)

    def discover(
        self,
        term: TermSpec,
        catalogs: dict[str, _Catalog],
        state: _SiteState,
        time_budget_s: float | None,
    ) -> _Discovery:
        """Read the feed, then enumerate node ids above the watermark.

        Adds every section found to the catalog of its own term (creating
        other terms' catalogs as needed). Pages of ``term`` fetched during
        enumeration are parsed once and returned as pre-fetched rows.
        """
        result = _Discovery()
        # 1. feed
        try:
            items = parse_rss(self._client.get(self.rss_url()))
        except HttpError as exc:
            logger.warning("rss.xml not readable (%s); enumeration uses the stored watermark", exc)
            items = []
        result.feed_items = len(items)
        for node_id, path, title in items:
            parsed = ref_from_feed_item(node_id, path, title)
            if parsed is None:
                continue
            ref, identity = parsed
            catalog = self._catalog_for(catalogs, identity.term_name)
            if catalog is not None and self._add_ref(catalog, ref):
                logger.info("feed: new section %s (%s) node %d", ref.course_key, identity.term_name, node_id)
        newest = max((n for n, _, _ in items), default=None)
        if newest is not None and (state.max_node_seen is None or newest > state.max_node_seen):
            state.max_node_seen = newest
            state.dirty = True
        if state.max_node_seen is None:
            logger.warning("no feed and no stored watermark: node enumeration skipped this run")
            return result
        if state.max_node_probed is None:
            state.max_node_probed = max(0, state.max_node_seen - INITIAL_LOOKBACK_NODES)
            state.dirty = True
            logger.info("watermark initialised at node %d (newest %d)", state.max_node_probed, state.max_node_seen)
        # 2. enumerate: earlier ids that answered with an error first, then new ids
        first = state.max_node_probed + 1
        retry = [i for i in sorted(set(state.retry_ids)) if i <= state.max_node_probed][:MAX_RETRY_IDS]
        room = max(0, self.max_node_probes - len(retry))
        last = min(state.max_node_seen, first + room - 1)
        ids = retry + (list(range(first, last + 1)) if last >= first else [])
        if not ids:
            return result
        budget = None
        if time_budget_s is not None:
            budget = max(0.0, float(time_budget_s) * NODE_PROBE_BUDGET_SHARE)
            if budget < 1.0:
                return result
        url_to_id = {self.node_url(i): i for i in ids}
        outcomes: dict[int, str] = {}  # id -> "section" | "other" | "missing" | "error" | "unattempted"
        lock = threading.Lock()

        def on_result(url: str, payload: bytes | HttpError) -> None:
            node_id = url_to_id[url]
            if isinstance(payload, HttpError):
                # 404: no such node. 401/403/410: a node we may not read (a restricted
                # course page, seen live at node 530942), never a section for us.
                # Anything else (5xx, timeouts) is transient and retried later.
                if payload.status == 404:
                    kind = "missing"
                elif payload.status in (401, 403, 410):
                    kind = "other"
                elif getattr(payload, "budget_exhausted", False):
                    kind = "unattempted"
                else:
                    kind = "error"
                with lock:
                    outcomes[node_id] = kind
                return
            try:
                parsed = parse_section_ref(payload, node_id=node_id)
            except ParseError:
                parsed = None
            if parsed is None:
                with lock:
                    outcomes[node_id] = "other"
                return
            ref, identity = parsed
            with lock:
                outcomes[node_id] = "section"
                catalog = self._catalog_for(catalogs, identity.term_name)
                if catalog is None:
                    return
                self._add_ref(catalog, ref)
                if catalog.term.sis_term_id == term.sis_term_id and ref.component not in SELF_STUDY_COMPONENTS:
                    try:
                        row = parse_section_page(payload, ref, self._now(), term)
                    except ParseError as exc:
                        logger.warning("node %d parsed as section but not as a snapshot: %s", node_id, exc)
                        return
                    result.prefetched_rows[ref.url_path] = row
                    result.prefetched_refs[ref.url_path] = replace(
                        ref, section_id=row["section_id"], last_status=200, probed_at=row["fetched_at"].isoformat()
                    )

        self._client.get_many(list(url_to_id), on_result, time_budget_s=budget)
        # The watermark advances over the contiguous prefix of NEW ids that were attempted
        # (any outcome but "unattempted"); ids that answered with an error are kept in
        # retry_ids so a persistently failing node cannot block discovery, and are
        # retried at the start of later runs until they resolve.
        probed_to = state.max_node_probed
        for node_id in range(first, last + 1) if last >= first else []:
            if outcomes.get(node_id) in ("section", "other", "missing", "error"):
                probed_to = node_id
            else:
                break
        errors = sorted(n for n in ids if outcomes.get(n) == "error" and n <= probed_to)
        resolved = {n for n in retry if outcomes.get(n) in ("section", "other", "missing")}
        new_retry = sorted((set(state.retry_ids) - resolved) | set(errors))[-MAX_RETRY_IDS:]
        attempted = sum(1 for n in ids if outcomes.get(n) not in (None, "unattempted"))
        result.probed = attempted
        result.found_sections = sum(1 for n in ids if outcomes.get(n) == "section")
        if probed_to != state.max_node_probed or new_retry != sorted(set(state.retry_ids)):
            state.max_node_probed = probed_to
            state.retry_ids = new_retry
            state.dirty = True
        logger.info(
            "discovery: feed items=%d, attempted %d ids (%d retries, %d sections found, %d errors kept for retry), watermark now %d of %d",
            result.feed_items,
            attempted,
            len(retry),
            result.found_sections,
            len(new_retry),
            state.max_node_probed,
            state.max_node_seen,
        )
        return result

    # -- selection ---------------------------------------------------------------

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

    def _due_for_reprobe(self, ref: SectionRef) -> bool:
        if not ref.absent:
            return False
        if ref.probed_at is None:
            return True
        try:
            probed = _as_utc(datetime.fromisoformat(ref.probed_at))
        except ValueError:
            return True
        return self._now() - probed >= ABSENT_REPROBE_AFTER

    def _select(
        self,
        refs: list[SectionRef],
        priority: PrioritySpec | None,
        shard: tuple[int, int] | None,
    ) -> list[SectionRef]:
        """Order of fetching: priority sections by rank (then course key),
        then shard ``k`` of ``n`` of the remainder (no shard means priority
        only; no priority means everything), then up to
        ``MAX_REPROBES_PER_RUN`` absent slugs whose last probe is older than
        seven days. Absent slugs are otherwise skipped."""
        live = [r for r in refs if not r.absent]
        if priority is None:
            first: list[SectionRef] = []
            rest = list(live)
        else:
            ranked: list[tuple[int, str, SectionRef]] = []
            rest = []
            for ref in live:
                rank = priority.rank(ref.course_key)
                if rank is None:
                    if shard is not None and shard_of(ref.key, shard[1]) == shard[0]:
                        rest.append(ref)
                else:
                    ranked.append((rank, ref.course_key, ref))
            ranked.sort(key=lambda item: (item[0], item[1], item[2].url_path))
            first = [item[2] for item in ranked]
        selected = first + rest
        due = [r for r in refs if self._due_for_reprobe(r)]
        due.sort(key=lambda r: (r.probed_at or "", r.url_path))
        return selected + due[:MAX_REPROBES_PER_RUN]

    # -- fetch -------------------------------------------------------------------

    def fetch(
        self,
        term: TermSpec,
        *,
        priority: PrioritySpec | None = None,
        shard: tuple[int, int] | None = None,
        time_budget_s: float | None = None,
        limit: int | None = None,
    ) -> FetchResult:
        """Discover, select, fetch the pages, update the catalog.

        Scope is "full" (every live catalog section, ``universe_ids`` = ids of
        the live sections whose id is known) when ``priority`` is None, else
        "priority" (priority matches union shard members, ``universe_ids``
        None). ``limit`` caps the selection after it is made; under ``limit``
        the universe is unknown, so ``universe_ids`` is None. Discovery time
        counts against ``time_budget_s``; every HTTP failure, parse failure,
        and unattempted page of a section with a known id lands in
        ``missing_ids``. Raises TermNotPublished when the term has no catalog
        entries after discovery.
        """
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        started = self._clock()
        catalogs: dict[str, _Catalog] = {term.sis_term_id: self.load_catalog(term)}
        state = self.load_site_state()
        disc = self.discover(term, catalogs, state, time_budget_s)
        catalog = catalogs[term.sis_term_id]
        if not catalog.refs:
            self._persist(catalogs, state)
            raise TermNotPublished(f"no {term.name} sections on classes.berkeley.edu yet (feed and node enumeration)")
        refs = catalog.refs

        shard_pair = self._normalise_shard(shard, self.n_shards)
        if priority is None:
            scope = "full"
            shard_label = ""
            priority_sha = ""
            universe_ids: set[str] | None = {r.section_id for r in refs if r.section_id and not r.absent}
        else:
            scope = "priority"
            shard_label = f"{shard_pair[0]}/{shard_pair[1]}" if shard_pair else ""
            priority_sha = priority.sha
            universe_ids = None
        selected = self._select(refs, priority, shard_pair if priority is not None else None)
        if limit is not None:
            selected = selected[:limit]
            universe_ids = None
        # pages already fetched during discovery are not fetched again
        to_fetch = [r for r in selected if r.url_path not in disc.prefetched_rows]
        prefetched = [disc.prefetched_rows[r.url_path] for r in selected if r.url_path in disc.prefetched_rows]

        remaining = None
        if time_budget_s is not None:
            remaining = max(0.0, float(time_budget_s) - (self._clock() - started))
        rows, missing_ids, updates = self._fetch_pages(to_fetch, term, remaining)
        rows = prefetched + rows
        known = catalog.by_path()
        for path, ref in disc.prefetched_refs.items():
            current = known.get(path)
            if current is not None:
                # A re-probed page that lacks the sf-- elements must not blank what an
                # earlier page taught us: the same rule as the ordinary fetch.
                ref = replace(ref, title=ref.title or current.title, instructors=ref.instructors or current.instructors)
            updates.setdefault(path, ref)

        if updates:
            by_path = catalog.by_path()
            changed = 0
            for path, new_ref in updates.items():
                if by_path.get(path) != new_ref:
                    by_path[path] = new_ref
                    changed += 1
            if changed:
                catalog.refs = list(by_path.values())
                catalog.dirty = True
        # full scope: prefetched rows also widen the universe
        if universe_ids is not None:
            universe_ids |= {r["section_id"] for r in prefetched}
        self._persist(catalogs, state)

        logger.info(
            "classes_site term=%s scope=%s shard=%s catalog=%d live=%d selected=%d observed=%d (%d via discovery) missing=%d elapsed=%.1fs",
            term.sis_term_id,
            scope,
            shard_label or "-",
            len(refs),
            sum(1 for r in refs if not r.absent),
            len(selected),
            len(rows),
            len(prefetched),
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

    def _persist(self, catalogs: dict[str, _Catalog], state: _SiteState) -> None:
        for catalog in catalogs.values():
            if catalog.dirty:
                self._save_catalog(catalog)
        if state.dirty:
            self._save_site_state(state)

    def _fetch_pages(
        self,
        selected: list[SectionRef],
        term: TermSpec,
        time_budget_s: float | None,
    ) -> tuple[list[SnapshotRow], list[str], dict[str, SectionRef]]:
        """Fetch and parse the selected pages, in selection order.

        Returns rows, ``missing_ids`` (known ids that failed or were never
        attempted), and catalog updates keyed by ``url_path``: a learned id
        and status 200 on success, status 404 on a missing page. Transport
        errors and budget cutoffs do not change the catalog."""
        order = {self.section_url(ref): i for i, ref in enumerate(selected)}
        ref_by_url = {self.section_url(ref): ref for ref in selected}
        parsed: dict[int, SnapshotRow] = {}
        failed: dict[int, str] = {}
        updates: dict[str, SectionRef] = {}
        lock = threading.Lock()

        def on_result(url: str, payload: bytes | HttpError) -> None:
            ref = ref_by_url[url]
            index = order[url]
            if isinstance(payload, HttpError):
                if payload.status == 404:
                    logger.info("section page absent (404): %s", ref.url_path)
                    with lock:
                        updates[ref.url_path] = replace(ref, last_status=404, probed_at=self._now().isoformat())
                        if ref.section_id:
                            failed[index] = ref.section_id
                    return
                level = logging.DEBUG if getattr(payload, "budget_exhausted", False) else logging.WARNING
                logger.log(level, "section %s not fetched: %s", ref.section_id or ref.url_path, payload)
                if ref.section_id:
                    with lock:
                        failed[index] = ref.section_id
                return
            fetched_at = self._now()
            try:
                row = parse_section_page(payload, ref, fetched_at, term)
            except ParseError as exc:
                logger.warning("section %s not parsed: %s", ref.section_id or ref.url_path, exc)
                if ref.section_id:
                    with lock:
                        failed[index] = ref.section_id
                return
            # A second lxml parse of a page already parsed for its counts: about a
            # millisecond next to a network round trip, and it keeps SnapshotRow's
            # pinned columns out of this.
            title, instructors = parse_section_meta(payload)
            title, instructors = title or ref.title, instructors or ref.instructors
            with lock:
                parsed[index] = row
                if (
                    ref.section_id != row["section_id"]
                    or ref.last_status != 200
                    or ref.title != title
                    or ref.instructors != instructors
                ):
                    updates[ref.url_path] = replace(
                        ref,
                        section_id=row["section_id"],
                        last_status=200,
                        probed_at=fetched_at.isoformat(),
                        title=title,
                        instructors=instructors,
                    )

        if selected:
            self._client.get_many(list(order), on_result, time_budget_s=time_budget_s)
        rows = [parsed[i] for i in sorted(parsed)]
        seen: set[str] = set()
        unique_rows: list[SnapshotRow] = []
        for row in rows:
            if row["section_id"] in seen:
                logger.warning("duplicate section id %s in one run; keeping the first", row["section_id"])
                continue
            seen.add(row["section_id"])
            unique_rows.append(row)
        missing_ids = [failed[i] for i in sorted(failed) if failed[i] not in seen]
        return unique_rows, missing_ids, updates
