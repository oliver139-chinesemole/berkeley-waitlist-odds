"""classes.berkeley.edu source. See docs/DESIGN_A2.md section 5a and docs/PHASE0.md.

Discovery: the site's ``/search/`` listing is disallowed by its robots.txt,
so the section universe comes from Berkeleytime's public ``GetCatalog``
(one request per term per day). Every catalog class has a primary section
whose page slug is derivable: ``/content/<year>-<sem>-<subject>-<catalog>-
<class#>-<component>-<class#>`` (verified 2026-09-19 against all 3,640
listed Fall 2026 primaries: the section number always equals the class
number). Classes that are not printed in the public schedule (about 40% of
the catalog: MBA, LAW, non-printed seminars) return 404; those slugs are
remembered as absent and re-probed on a later refresh run.

Section page: ``GET /content/<slug>`` (allowed by robots.txt) embeds the SIS
enrollment status in the ``drupal-settings-json`` script under
``ucb.enrollment.available``.

Module-level functions are pure (bytes or dicts in, values out) so they can
be tested against fixtures; ``ClassesSiteSource`` does the I/O.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, replace
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
LEGACY_CATALOG_FILENAME = "sections.json"  # listing-based file written before 2026-09-19
CATALOG_VERSION = 2
CATALOG_MAX_AGE = timedelta(hours=24)  # refresh from Berkeleytime after this
ABSENT_REPROBE_AFTER = timedelta(days=7)  # retry a 404 slug after this
MAX_REPROBES_PER_RUN = 300  # only on refresh runs; 404s are cheap but not free
# Primary-section components that never carry a waitlist in practice
# (independent study, group study, field work, tutorials...). They are
# excluded from the universe; the listing-era baseline showed them as noise.
SELF_STUDY_COMPONENTS = frozenset(
    {"IND", "GRP", "FLD", "TUT", "INT", "SLF", "PRA", "REC", "SES", "CLN", "WOR", "REA", "WBD", "VOL", "DEM"}
)
# The section page exposes ucb.termDetails.sessionDescription ("2026 Fall")
# but no session id; every section we scrape is in the regular session.
DEFAULT_SESSION_ID = "1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SectionRef:
    """A primary section known from the catalog plus its section page path.

    ``section_id`` is ``""`` until the page has been fetched once (the
    catalog does not carry SIS section ids); ``last_status`` is the HTTP
    status of the last probe (200, 404, ...) or None when never probed.
    """

    section_id: str  # "30174" or "" when not yet learned
    url_path: str  # "/content/2026-fall-aeroeng-10-001-lec-001"
    course_key: str  # "AEROENG 10" ("<SUBJECT> <CATALOG>", subject spaces removed)
    subject: str  # "AEROENG" (spaces removed: "EL ENG" -> "ELENG")
    catalog_number: str  # "10"
    class_number: str  # "001"
    section_number: str  # "001"
    component: str  # "LEC"
    last_status: int | None = None
    probed_at: str | None = None  # ISO-8601 UTC of the last probe

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
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"section ref malformed: {exc}") from exc


# -- catalog from Berkeleytime ---------------------------------------------


def section_slug(term: TermSpec, subject: str, catalog_number: str, class_number: str, component: str) -> str:
    """``/content/<year>-<semester>-<subject>-<catalog>-<class#>-<component>-<class#>``.

    Lower-cased; the subject loses its spaces. The section number of a
    primary section equals its class number (verified on the whole Fall 2026
    listing), so the class number appears twice.
    """
    subj = subject.replace(" ", "").lower()
    num = class_number.lower()
    return f"/content/{term.year}-{term.semester.lower()}-{subj}-{catalog_number.lower()}-{num}-{component.lower()}-{num}"


def catalog_refs(classes: list[dict[str, Any]], term: TermSpec) -> list[SectionRef]:
    """SectionRefs for every catalog class whose primary section is not
    self-study. Malformed entries are skipped with a warning; duplicates
    (same slug) keep the first."""
    refs: list[SectionRef] = []
    seen: set[str] = set()
    for entry in classes:
        try:
            subject_raw = str(entry["subject"])
            catalog_number = str(entry["courseNumber"])
            class_number = str(entry["number"])
            primary = entry.get("primarySection") or {}
            component = str(primary["component"])
        except (KeyError, TypeError) as exc:
            logger.warning("skipping catalog entry without %s: %s", exc, str(entry)[:120])
            continue
        if not subject_raw or not catalog_number or not class_number or not component:
            logger.warning("skipping catalog entry with empty fields: %s", str(entry)[:120])
            continue
        if component.upper() in SELF_STUDY_COMPONENTS:
            continue
        subject = subject_raw.replace(" ", "")
        path = section_slug(term, subject, catalog_number, class_number, component)
        if path in seen:
            continue
        seen.add(path)
        refs.append(
            SectionRef(
                section_id="",
                url_path=path,
                course_key=f"{subject} {catalog_number}",
                subject=subject,
                catalog_number=catalog_number,
                class_number=class_number,
                section_number=class_number,
                component=component.upper(),
            )
        )
    return refs


def merge_catalog(existing: list[SectionRef], fresh: list[SectionRef]) -> tuple[list[SectionRef], int]:
    """Union keyed by ``url_path``: known entries keep their learned id and
    probe state, new entries are appended. Returns the merged list and the
    number of entries added. Entries that vanished from the fresh catalog are
    kept (their next probe decides whether they are gone)."""
    by_path = {ref.url_path: ref for ref in existing}
    added = 0
    for ref in fresh:
        if ref.url_path not in by_path:
            by_path[ref.url_path] = ref
            added += 1
    return list(by_path.values()), added


# -- section page parsing --------------------------------------------------


def _parse_html(html: bytes | str) -> lxml.html.HtmlElement:
    """Parse a page; raises ParseError on an empty or unparsable document."""
    try:
        if isinstance(html, bytes):
            parser = lxml.html.HTMLParser(encoding="utf-8")
            return lxml.html.document_fromstring(html, parser=parser)
        return lxml.html.document_fromstring(html)
    except (lxml.etree.ParserError, lxml.etree.XMLSyntaxError, ValueError) as exc:
        raise ParseError(f"cannot parse HTML: {exc}") from exc


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


# -- source ---------------------------------------------------------------

CatalogProvider = Callable[[TermSpec], list[dict[str, Any]]]


def berkeleytime_catalog_provider(term: TermSpec) -> list[dict[str, Any]]:
    """Default provider: Berkeleytime ``GetCatalog(year, semester)`` raw classes."""
    from scraper.sources.berkeleytime import BerkeleytimeSource  # lazy: optional dependency path

    data = BerkeleytimeSource().execute("GetCatalog", {"year": term.year, "semester": term.berkeleytime_semester})
    classes = data.get("catalog")
    if not isinstance(classes, list):
        raise ParseError("GetCatalog: response has no catalog list")
    return classes


@dataclass
class _Catalog:
    refs: list[SectionRef]
    refreshed_at: datetime | None
    dirty: bool = False
    refreshed_now: bool = False


class ClassesSiteSource:
    """Scrapes classes.berkeley.edu section pages. ``name == "classes_site"``.

    ``now`` (UTC datetime) and ``clock`` (monotonic seconds) are injectable
    for tests; the ``client`` provides ``get`` and ``get_many``;
    ``catalog_provider`` returns Berkeleytime's raw catalog classes.
    """

    name = SOURCE_NAME

    def __init__(
        self,
        client: HttpClient,
        data_root: Path,
        n_shards: int = 8,
        base_url: str = DEFAULT_BASE_URL,
        *,
        catalog_provider: CatalogProvider = berkeleytime_catalog_provider,
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
        self._catalog_provider = catalog_provider
        if catalog_max_pages is not None:
            logger.info("catalog_max_pages is ignored: the catalog no longer comes from the listing")
        self._now = now
        self._clock = clock

    parse_section_page = staticmethod(parse_section_page)

    # -- urls and paths ----------------------------------------------------

    def section_url(self, ref: SectionRef) -> str:
        return f"{self._base_url}{ref.url_path}"

    def catalog_path(self, term_id: str) -> Path:
        return self._data_root / "catalog" / term_id / CATALOG_FILENAME

    def legacy_catalog_path(self, term_id: str) -> Path:
        return self._data_root / "catalog" / term_id / LEGACY_CATALOG_FILENAME

    # -- catalog -----------------------------------------------------------

    def _load_catalog(self, term: TermSpec) -> _Catalog | None:
        """The on-disk catalog regardless of age, or the legacy listing file
        converted (self-study components dropped), or None."""
        path = self.catalog_path(term.sis_term_id)
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                refs = [SectionRef.from_dict(d) for d in payload["sections"]]
                refreshed = payload.get("refreshed_at")
                refreshed_at = _as_utc(datetime.fromisoformat(str(refreshed))) if refreshed else None
                return _Catalog(refs=refs, refreshed_at=refreshed_at)
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
                return _Catalog(refs=refs, refreshed_at=None, dirty=True)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.warning("ignoring unreadable legacy catalog %s: %s", legacy, exc)
        return None

    def _save_catalog(self, term: TermSpec, catalog: _Catalog) -> Path:
        path = self.catalog_path(term.sis_term_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CATALOG_VERSION,
            "term_id": term.sis_term_id,
            "term_name": term.name,
            "source": "berkeleytime GetCatalog + classes.berkeleyedu probes",
            "refreshed_at": catalog.refreshed_at.isoformat() if catalog.refreshed_at else None,
            "sections": [ref.to_dict() for ref in sorted(catalog.refs, key=lambda r: r.url_path)],
        }
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, indent=0, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        catalog.dirty = False
        logger.info("wrote %s (%d sections)", path, len(catalog.refs))
        return path

    def load_or_refresh_catalog(self, term: TermSpec, *, force_refresh: bool = False) -> _Catalog:
        """Catalog for the term: refreshed from Berkeleytime when older than
        24 h (or absent), otherwise the cached copy. A failed refresh falls
        back to the cached copy with a warning; with nothing cached the
        failure propagates. An empty catalog and nothing cached means the
        term is not published yet (TermNotPublished)."""
        catalog = self._load_catalog(term)
        stale = catalog is None or catalog.refreshed_at is None or self._now() - catalog.refreshed_at >= CATALOG_MAX_AGE
        if not stale and not force_refresh:
            assert catalog is not None
            logger.info("reusing catalog for term %s (%d sections)", term.sis_term_id, len(catalog.refs))
            return catalog
        try:
            classes = self._catalog_provider(term)
        except Exception as exc:  # noqa: BLE001 - any provider failure means "use what we have"
            if catalog is None:
                raise
            logger.warning("catalog refresh for %s failed (%s); using cached copy from %s", term.name, exc, catalog.refreshed_at)
            return catalog
        fresh = catalog_refs(classes, term)
        if not fresh:
            if catalog is None:
                raise TermNotPublished(f"Berkeleytime lists no classes for {term.name} yet")
            logger.warning("catalog refresh for %s returned no classes; keeping cached copy", term.name)
            return catalog
        if catalog is None:
            merged, added = fresh, len(fresh)
        else:
            merged, added = merge_catalog(catalog.refs, fresh)
        logger.info("catalog for %s refreshed: %d classes -> %d primary sections (%d new)", term.name, len(classes), len(merged), added)
        return _Catalog(refs=merged, refreshed_at=self._now(), dirty=True, refreshed_now=True)

    # -- selection ---------------------------------------------------------

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
        *,
        reprobe: bool,
    ) -> list[SectionRef]:
        """Order of fetching: priority sections by rank (then course key),
        then shard ``k`` of ``n`` of the remainder (no shard means priority
        only; no priority means everything), then, on refresh runs only, up
        to ``MAX_REPROBES_PER_RUN`` absent slugs whose last probe is older
        than seven days. Absent slugs are otherwise skipped."""
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
        if reprobe:
            due = [r for r in refs if self._due_for_reprobe(r)]
            due.sort(key=lambda r: (r.probed_at or "", r.url_path))
            selected += due[:MAX_REPROBES_PER_RUN]
        return selected

    # -- fetch -------------------------------------------------------------

    def fetch(
        self,
        term: TermSpec,
        *,
        priority: PrioritySpec | None = None,
        shard: tuple[int, int] | None = None,
        time_budget_s: float | None = None,
        limit: int | None = None,
    ) -> FetchResult:
        """Load or refresh the catalog, select, fetch the pages, update the catalog.

        Scope is "full" (every live catalog section, ``universe_ids`` = ids of
        the live sections whose id is known) when ``priority`` is None, else
        "priority" (priority matches union shard members, ``universe_ids``
        None). ``limit`` caps the selection after it is made; under ``limit``
        the universe is unknown, so ``universe_ids`` is None. Catalog refresh
        time counts against ``time_budget_s``; every HTTP failure, parse
        failure, and unattempted page of a section with a known id lands in
        ``missing_ids``. Raises TermNotPublished when the term has no catalog.
        """
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        started = self._clock()
        catalog = self.load_or_refresh_catalog(term)
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
        selected = self._select(refs, priority, shard_pair if priority is not None else None, reprobe=catalog.refreshed_now)
        if limit is not None:
            selected = selected[:limit]
            universe_ids = None

        remaining = None
        if time_budget_s is not None:
            remaining = max(0.0, float(time_budget_s) - (self._clock() - started))
        rows, missing_ids, updates = self._fetch_pages(selected, term, remaining)

        if updates:
            by_path = {r.url_path: r for r in refs}
            changed = 0
            for path, new_ref in updates.items():
                if by_path.get(path) != new_ref:
                    by_path[path] = new_ref
                    changed += 1
            if changed:
                catalog.refs = list(by_path.values())
                catalog.dirty = True
        if catalog.dirty:
            self._save_catalog(term, catalog)

        logger.info(
            "classes_site term=%s scope=%s shard=%s catalog=%d live=%d selected=%d observed=%d missing=%d elapsed=%.1fs",
            term.sis_term_id,
            scope,
            shard_label or "-",
            len(refs),
            sum(1 for r in refs if not r.absent),
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
            with lock:
                parsed[index] = row
                if ref.section_id != row["section_id"] or ref.last_status != 200:
                    updates[ref.url_path] = replace(ref, section_id=row["section_id"], last_status=200, probed_at=fetched_at.isoformat())

        self._client.get_many(list(order), on_result, time_budget_s=time_budget_s)
        rows = [parsed[i] for i in sorted(parsed)]
        # A section observed twice in one run (cannot happen with unique slugs,
        # but guard the schema's unique-id rule anyway).
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
