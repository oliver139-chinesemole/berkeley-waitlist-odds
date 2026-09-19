"""SIS Class API source (`name = "sis_api"`). See docs/DESIGN_A2.md 5b, docs/PHASE0.md.

Sweeps ``GET https://gateway.api.berkeley.edu/sis/v1/classes/sections`` for one
term, page by page, and turns every class section into a ``SnapshotRow``.

Semantics that matter downstream:

- Scope is always ``"full"``: the sweep observes the whole term. ``universe_ids``
  is the set of ids the sweep saw (parsed rows plus sections that were present
  but failed to parse). Cancelled sections (``status.code == "X"``) are dropped
  from rows *and* from the universe unless ``include_cancelled`` is set, so
  ``compute_delta`` tombstones them the first time they disappear. That is the
  desired signal: a cancellation is a real event.
- If the sweep cannot be completed (time budget exhausted, ``limit`` reached),
  ``universe_ids`` is ``None`` so nothing is tombstoned on partial knowledge.
- A page that keeps failing after retries aborts the run with ``SisApiError``;
  we would rather record a gap than a partial sweep that looks complete.

The HTTP layer is an injectable transport ``get_json(url, params, headers) ->
(status, dict)`` so tests never touch the network. The default transport uses
``requests`` (the gateway does not block it; only classes.berkeley.edu does).
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from scraper.schema import SnapshotRow
from scraper.sources.base import FetchResult, ParseError, PrioritySpec, TermSpec

logger = logging.getLogger(__name__)

VERSION = "0.1.0"
# Honest identification per docs/PHASE0.md. The repo has no remote yet, so the
# GitHub URL from DESIGN_A2.md section 4 is left to scraper/http.py once known.
USER_AGENT = f"berkeley-waitlist-odds/{VERSION} (+mailto:oliver139@berkeley.edu)"

BASE_URL = "https://gateway.api.berkeley.edu/sis/v1/classes/sections"
ENV_APP_ID = "SIS_CLASS_APP_ID"
ENV_APP_KEY = "SIS_CLASS_APP_KEY"
DEFAULT_TIMEOUT_S = 60.0
CANCELLED_STATUS = "X"
SOURCE_NAME = "sis_api"

GetJson = Callable[[str, dict[str, str], dict[str, str]], tuple[int, dict[str, Any]]]
Sleep = Callable[[float], None]
Clock = Callable[[], datetime]


class TransportError(RuntimeError):
    """The transport could not complete the HTTP exchange (DNS, connection reset, timeout)."""


class SisApiError(RuntimeError):
    """A page could not be fetched after retries, or the gateway rejected the request (403, 4xx)."""

    def __init__(self, message: str, *, status: int, url: str, page: int) -> None:
        super().__init__(message)
        self.status = status
        self.url = url
        self.page = page


def utc_now() -> datetime:
    """Current time as a tz-aware UTC datetime (the only kind ``fetched_at`` accepts)."""
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- transport


def requests_get_json(
    url: str,
    params: dict[str, str],
    headers: dict[str, str],
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> tuple[int, dict[str, Any]]:
    """Default transport: ``requests.get`` returning ``(status, json_body)``.

    A body that is not a JSON object (HTML error page, empty 404) becomes ``{}``
    so callers can branch on status alone. Network-level failures raise
    ``TransportError`` so the retry loop can treat them like a 5xx.
    """
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout_s)
    except requests.RequestException as exc:
        raise TransportError(f"GET {url} failed: {exc}") from exc
    return resp.status_code, _json_object(resp)


def _json_object(resp: requests.Response) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


# --------------------------------------------------------------------------- parsing


def _dig(obj: Any, path: str) -> Any:
    """Value at dotted ``path`` inside nested dicts; ``None`` when any hop is missing."""
    cur = obj
    for key in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _require(section: dict[str, Any], path: str) -> Any:
    value = _dig(section, path)
    if value is None:
        raise ParseError(f"section {section.get('id')!r}: missing {path}")
    return value


def _to_int(value: Any, what: str) -> int:
    """Coerce an int-like JSON value (int or digit string, never bool) to ``int``."""
    if isinstance(value, bool):
        raise ParseError(f"{what}: expected an integer, got a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise ParseError(f"{what}: expected an integer, got {value!r}")


def _required_int(section: dict[str, Any], path: str) -> int:
    return _to_int(_require(section, path), f"section {section.get('id')!r} {path}")


def _optional_int(section: dict[str, Any], path: str) -> int | None:
    value = _dig(section, path)
    if value is None:
        return None
    return _to_int(value, f"section {section.get('id')!r} {path}")


def class_sections(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ``apiResponse.response.classSections`` from one page payload.

    Raises ``ParseError`` when the envelope is not there: an unexpected wrapper
    must fail loudly rather than look like the end of the sweep, because ending
    early would tombstone every section on the unread pages.
    """
    sections = _dig(payload, "apiResponse.response.classSections")
    if sections is None:
        raise ParseError("payload has no apiResponse.response.classSections")
    if not isinstance(sections, list):
        raise ParseError(f"classSections is {type(sections).__name__}, expected a list")
    return sections


def section_id_of(section: dict[str, Any]) -> str:
    """The SIS class section id (``id``) as a string; raises ``ParseError`` if absent."""
    return str(_to_int(_require(section, "id"), "section id"))


def is_cancelled(section: dict[str, Any]) -> bool:
    """True when the section's ``status.code`` is ``"X"`` (cancelled)."""
    return _dig(section, "status.code") == CANCELLED_STATUS


def parse_section(section: dict[str, Any], fetched_at: datetime, term: TermSpec) -> SnapshotRow:
    """Convert one SIS ``classSection`` object into a ``SnapshotRow``.

    Field paths follow docs/PHASE0.md. Cancelled sections are *not* filtered
    here; see ``parse_sections``. The term id is taken from the payload
    (``class.session.term.id``); a mismatch with ``term.sis_term_id`` is logged
    and the payload value kept, mirroring the classes_site rule.
    """
    section_id = section_id_of(section)
    # SIS spells some subjects with spaces ("EL ENG"); subject and course_key strip
    # them ("ELENG", "ELENG 16A"), which is also how classes.berkeley.edu spells them.
    subject = "".join(str(_require(section, "class.course.subjectArea.code")).split())
    catalog_number = str(_require(section, "class.course.catalogNumber.formatted")).strip()
    term_id = str(_require(section, "class.session.term.id"))
    if term_id != term.sis_term_id:
        logger.warning(
            "section %s reports term %s but the sweep is for %s; keeping the payload value",
            section_id,
            term_id,
            term.sis_term_id,
        )
    primary = _dig(section, "association.primary")
    if primary is not None and not isinstance(primary, bool):
        raise ParseError(f"section {section_id}: association.primary is not a boolean")
    section_status = _dig(section, "status.code")
    return SnapshotRow(
        fetched_at=fetched_at,
        term_id=term_id,
        section_id=section_id,
        course_key=f"{subject} {catalog_number}",
        subject=subject,
        catalog_number=catalog_number,
        class_number=str(_require(section, "class.number")),
        section_number=str(_require(section, "number")),
        component=str(_require(section, "component.code")),
        is_primary=primary,
        session_id=str(_require(section, "class.session.id")),
        enrolled_count=_required_int(section, "enrollmentStatus.enrolledCount"),
        enroll_capacity=_required_int(section, "enrollmentStatus.maxEnroll"),
        waitlist_count=_required_int(section, "enrollmentStatus.waitlistedCount"),
        waitlist_capacity=_required_int(section, "enrollmentStatus.maxWaitlist"),
        reserved_count=_optional_int(section, "enrollmentStatus.reservedCount"),
        open_reserved=_optional_int(section, "enrollmentStatus.openReserved"),
        status=str(_require(section, "enrollmentStatus.status.code")),
        section_status=None if section_status is None else str(section_status),
        source=SOURCE_NAME,
    )


def parse_sections(
    payload: dict[str, Any],
    fetched_at: datetime,
    term: TermSpec,
    include_cancelled: bool = False,
) -> list[SnapshotRow]:
    """Parse one page payload into rows, skipping cancelled sections unless asked.

    Strict: any malformed section raises ``ParseError``. ``fetch`` uses the
    lenient per-section path so one bad section costs one ``missing_ids`` entry
    instead of the whole page.
    """
    rows: list[SnapshotRow] = []
    for section in class_sections(payload):
        if not include_cancelled and is_cancelled(section):
            continue
        rows.append(parse_section(section, fetched_at, term))
    return rows


# --------------------------------------------------------------------------- source


class SisApiSource:
    """Full-term sweep of the SIS Class API. Implements the ``Source`` protocol.

    Pages are requested in batches of ``max_in_flight`` on a thread pool; the
    sweep ends at the first page that returns 404 or an empty ``classSections``.
    Each page is retried ``retries`` times on 5xx / 429 / transport failure with
    exponential backoff (``backoff_base_s * 2**k``), sleeping via the injectable
    ``sleep`` so tests run instantly.
    """

    name = SOURCE_NAME

    def __init__(
        self,
        app_id: str,
        app_key: str,
        transport: GetJson | None = None,
        page_size: int = 50,
        max_in_flight: int = 8,
        *,
        include_cancelled: bool = False,
        retries: int = 3,
        backoff_base_s: float = 1.0,
        base_url: str = BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        sleep: Sleep = time.sleep,
        clock: Clock = utc_now,
    ) -> None:
        if not app_id or not app_key:
            raise ValueError("SIS Class API needs both app_id and app_key")
        if page_size <= 0 or max_in_flight <= 0:
            raise ValueError("page_size and max_in_flight must be positive")
        self.page_size = page_size
        self.max_in_flight = max_in_flight
        self.include_cancelled = include_cancelled
        self.retries = max(0, retries)
        self.backoff_base_s = backoff_base_s
        self.base_url = base_url
        self._headers = {"app_id": app_id, "app_key": app_key, "User-Agent": USER_AGENT, "Accept": "application/json"}
        self._transport: GetJson = transport or (
            lambda url, params, headers: requests_get_json(url, params, headers, timeout_s=timeout_s)
        )
        self._sleep = sleep
        self._clock = clock

    @classmethod
    def from_env(cls, **kwargs: Any) -> "SisApiSource":
        """Build a source from ``SIS_CLASS_APP_ID`` / ``SIS_CLASS_APP_KEY``; ``ValueError`` if either is unset."""
        app_id = os.environ.get(ENV_APP_ID, "")
        app_key = os.environ.get(ENV_APP_KEY, "")
        if not app_id or not app_key:
            raise ValueError(f"set both {ENV_APP_ID} and {ENV_APP_KEY} to use the SIS Class API")
        return cls(app_id, app_key, **kwargs)

    @staticmethod
    def credentials_in_env() -> bool:
        """True when both credential variables are set and non-empty (drives ``--source auto``)."""
        return bool(os.environ.get(ENV_APP_ID)) and bool(os.environ.get(ENV_APP_KEY))

    # ---- one page

    def _params(self, term: TermSpec, page: int) -> dict[str, str]:
        return {"term-id": term.sis_term_id, "page-number": str(page), "page-size": str(self.page_size)}

    def fetch_page(self, term: TermSpec, page: int) -> tuple[dict[str, Any] | None, datetime]:
        """Fetch one page. Returns ``(payload, fetched_at)``; payload is ``None`` on 404 (past the last page).

        Retries on 5xx, 429 and transport failures; any other non-2xx status
        (403 bad credentials, 400 bad term) raises ``SisApiError`` at once.
        """
        params = self._params(term, page)
        status = 0
        detail = ""
        attempt = 0
        for attempt in range(1, self.retries + 2):
            try:
                status, body = self._transport(self.base_url, params, self._headers)
                detail = ""
            except TransportError as exc:
                status, body, detail = 0, {}, str(exc)
            fetched_at = self._clock()
            if 200 <= status < 300:
                return body, fetched_at
            if status == 404:
                logger.debug("page %d: 404, end of term %s", page, term.sis_term_id)
                return None, fetched_at
            retryable = status == 0 or status == 429 or status >= 500
            if not retryable or attempt > self.retries:
                break
            delay = self.backoff_base_s * (2 ** (attempt - 1))
            logger.warning(
                "page %d: HTTP %s on attempt %d/%d, retrying in %.1fs %s",
                page,
                status or "transport error",
                attempt,
                self.retries + 1,
                delay,
                detail,
            )
            self._sleep(delay)
        suffix = f": {detail}" if detail else ""
        raise SisApiError(
            f"page {page} of term {term.sis_term_id}: HTTP {status} after {attempt} attempt(s){suffix}",
            status=status,
            url=self.base_url,
            page=page,
        )

    def _parse_page(
        self, payload: dict[str, Any], fetched_at: datetime, term: TermSpec
    ) -> tuple[list[SnapshotRow], list[str], int]:
        """Lenient page parse: ``(rows, ids that failed to parse, number of sections on the page)``.

        A section whose id is readable but whose fields are malformed lands in
        the second list (it becomes a ``missing_ids`` entry and stays in the
        universe so it is not tombstoned). A section without a readable id
        raises ``ParseError``: that is schema drift, not one bad record.
        """
        rows: list[SnapshotRow] = []
        failed: list[str] = []
        sections = class_sections(payload)
        for section in sections:
            if not self.include_cancelled and is_cancelled(section):
                continue
            section_id = section_id_of(section)
            try:
                rows.append(parse_section(section, fetched_at, term))
            except ParseError as exc:
                logger.warning("section %s skipped: %s", section_id, exc)
                failed.append(section_id)
        return rows, failed, len(sections)

    # ---- the sweep

    def fetch(
        self,
        term: TermSpec,
        *,
        priority: PrioritySpec | None = None,
        shard: tuple[int, int] | None = None,
        time_budget_s: float | None = None,
        limit: int | None = None,
    ) -> FetchResult:
        """Sweep every page of the term. ``priority`` and ``shard`` are accepted for
        protocol compatibility and ignored: this source is fast enough to be full-scope always."""
        if priority is not None or shard is not None:
            logger.info("sis_api ignores priority/shard; the sweep is always full scope")
        started = time.monotonic()
        rows: list[SnapshotRow] = []
        missing: list[str] = []
        seen: set[str] = set()
        truncated = False
        pages_read = 0
        page = 1
        with ThreadPoolExecutor(max_workers=self.max_in_flight, thread_name_prefix="sis-page") as pool:
            while True:
                if time_budget_s is not None and time.monotonic() - started > time_budget_s:
                    logger.warning("time budget %.0fs exhausted after %d pages; sweep is partial", time_budget_s, pages_read)
                    truncated = True
                    break
                batch = list(range(page, page + self.max_in_flight))
                futures: list[Future[tuple[dict[str, Any] | None, datetime]]] = [
                    pool.submit(self.fetch_page, term, p) for p in batch
                ]
                finished = self._consume_batch(batch, futures, term, rows, missing, seen)
                pages_read += len(batch)
                if finished:
                    break
                if limit is not None and len(rows) >= limit:
                    truncated = True
                    break
                page += self.max_in_flight
        if limit is not None and len(rows) > limit:
            del rows[limit:]
            truncated = True
        universe = None if truncated else {r["section_id"] for r in rows} | set(missing)
        logger.info(
            "sis_api term %s: %d rows, %d unparseable, universe=%s, %.1fs",
            term.sis_term_id,
            len(rows),
            len(missing),
            "unknown (partial)" if universe is None else len(universe),
            time.monotonic() - started,
        )
        return FetchResult(rows=rows, missing_ids=missing, universe_ids=universe, scope="full")

    def _consume_batch(
        self,
        batch: list[int],
        futures: list[Future[tuple[dict[str, Any] | None, datetime]]],
        term: TermSpec,
        rows: list[SnapshotRow],
        missing: list[str],
        seen: set[str],
    ) -> bool:
        """Fold one batch of page futures into the accumulators, in page order.

        Returns True when a terminal page (404 or empty) was seen, meaning the
        sweep is complete. Pages after the terminal one in the same batch are
        ignored (and logged if they unexpectedly carried data).
        """
        finished = False
        for page, future in zip(batch, futures):
            payload, fetched_at = future.result()  # SisApiError / ParseError propagate: abort the run
            if payload is None:
                finished = True
                continue
            page_rows, failed, n_sections = self._parse_page(payload, fetched_at, term)
            if n_sections == 0:
                logger.debug("page %d: empty classSections, end of term %s", page, term.sis_term_id)
                finished = True
                continue
            if finished:
                logger.warning("page %d carried %d sections after an earlier terminal page; ignored", page, n_sections)
                continue
            for row in page_rows:
                if row["section_id"] in seen:
                    logger.warning("duplicate section %s on page %d; keeping the first copy", row["section_id"], page)
                    continue
                seen.add(row["section_id"])
                rows.append(row)
            missing.extend(i for i in failed if i not in seen)
        return finished
