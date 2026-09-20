"""Berkeleytime GraphQL source (`name = "berkeleytime"`). See docs/DESIGN_A2.md 5c.

Berkeleytime (https://berkeleytime.com) exposes a persisted-operations-only
GraphQL gateway: ``POST /api/graphql`` with ``{"id": <op id>, "variables": {...}}``.
The op ids are copied from Berkeleytime's public repo into
``data/fixtures/berkeleytime_persisted_ops.json``.

This source exists for cross-checks and emergencies, and its rows differ from
the SIS-backed sources in ways the reader of the data must know:

- ``GetCatalog`` does not return SIS ``sectionId``. ``section_id`` is therefore
  the synthetic key ``bt:<subject>:<courseNumber>:<number>`` (e.g.
  ``bt:COMPSCI:61A:001``) and is NOT comparable to ``sis_api`` /
  ``classes_site`` ids. ``section_status`` is null (not reported).
- Only each class's primary section is present (``is_primary=True``), one row
  per class. Secondary sections, with real SIS ids, come from ``get_class``.
- The counts are third-party data captured at Berkeleytime's 15-minute cadence.

The HTTP layer is an injectable transport ``post_json(url, json_body, headers)
-> (status, dict, retry_after_s)`` so tests never touch the network (the older
``(status, dict)`` shape is still accepted); the default uses ``requests``
(this host does not block it), never follows redirects (a 3xx is a hard
``BerkeleytimeError``) and streams the body under a ``MAX_BODY_BYTES`` cap
(GetCatalog is about 13 MB). Retries back off exponentially with jitter and
honour ``Retry-After`` when it is larger.
"""
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests

from scraper import config
from scraper.http import parse_retry_after
from scraper.schema import SnapshotRow
from scraper.sources.base import FetchResult, ParseError, PrioritySpec, TermSpec
from scraper.sources.sis_api import (
    TransportError,
    TransportResult,
    json_object,
    read_bounded,
    unpack_transport_result,
    utc_now,
)

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://berkeleytime.com/api/graphql"
DEFAULT_OPS_PATH = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "berkeleytime_persisted_ops.json"
DEFAULT_TIMEOUT_S = 60.0
MAX_BODY_BYTES = 64 * 1024 * 1024  # GetCatalog for a full term is ~13 MB; leave headroom
DEFAULT_SESSION_ID = "1"  # regular academic session; required by GetClass
SOURCE_NAME = "berkeleytime"

PostJson = Callable[[str, dict[str, Any], dict[str, str]], TransportResult]
Sleep = Callable[[float], None]
Clock = Callable[[], datetime]
Rng = Callable[[], float]


class BerkeleytimeError(RuntimeError):
    """The gateway answered with a non-200 status and no GraphQL error body, even after retries."""

    def __init__(self, message: str, *, status: int, operation: str) -> None:
        super().__init__(message)
        self.status = status
        self.operation = operation


# --------------------------------------------------------------------------- transport


def requests_post_json(
    url: str,
    json_body: dict[str, Any],
    headers: dict[str, str],
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_body_bytes: int = MAX_BODY_BYTES,
) -> tuple[int, dict[str, Any], float | None]:
    """Default transport: ``requests.post`` with a JSON body, returning ``(status, json_body, retry_after_s)``.

    Redirects are not followed (a 3xx comes back as its status and the caller
    fails hard); the body is streamed and capped at ``max_body_bytes``
    (``ParseError`` beyond that). A non-object body becomes ``{}``.
    ``retry_after_s`` is the parsed ``Retry-After`` header or None. Network
    failures raise ``TransportError``.
    """
    try:
        resp = requests.post(url, json=json_body, headers=headers, timeout=timeout_s, allow_redirects=False, stream=True)
    except requests.RequestException as exc:
        raise TransportError(f"POST {url} failed: {exc}") from exc
    try:
        raw = read_bounded(resp, max_body_bytes)
    finally:
        resp.close()
    return resp.status_code, json_object(raw), parse_retry_after(resp.headers.get("Retry-After"))


# --------------------------------------------------------------------------- persisted ops


@dataclass(frozen=True)
class PersistedOp:
    """One entry of the persisted-operations file."""

    name: str
    id: str
    document: str
    variable_names: frozenset[str]


def load_persisted_ops(path: Path | str = DEFAULT_OPS_PATH) -> dict[str, list[PersistedOp]]:
    """Load ``{operationName: [entries]}`` preserving file order (order breaks ties in ``select_op``)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ParseError(f"{path}: expected an object keyed by operation name")
    ops: dict[str, list[PersistedOp]] = {}
    for name, entries in raw.items():
        if not isinstance(entries, list):
            raise ParseError(f"{path}: {name!r} must map to a list of entries")
        ops[name] = [
            PersistedOp(
                name=name,
                id=str(entry["id"]),
                document=str(entry.get("document", "")),
                variable_names=frozenset(entry.get("variableNames", [])),
            )
            for entry in entries
        ]
    return ops


def select_op(ops: dict[str, list[PersistedOp]], operation_name: str, variables: dict[str, Any]) -> PersistedOp:
    """Pick the persisted op for ``operation_name`` that accepts every variable we send.

    Candidates are the entries whose ``variableNames`` is a superset of the
    keys of ``variables``. Among candidates the one with the fewest declared
    variables wins (closest match); a remaining tie goes to the *last* entry in
    the file, which is the newest generated document. For ``GetClass`` this is
    the second entry (the one whose ``sessionId`` is required), whose response
    shape matches ``data/fixtures/berkeleytime_getclass_compsci61a_fa26.json``.
    """
    entries = ops.get(operation_name)
    if not entries:
        raise ValueError(f"no persisted operation named {operation_name!r}")
    sent = set(variables)
    candidates = [op for op in entries if sent <= op.variable_names]
    if not candidates:
        declared = [sorted(op.variable_names) for op in entries]
        raise ValueError(f"{operation_name}: no entry accepts variables {sorted(sent)}; declared: {declared}")
    fewest = min(len(op.variable_names) for op in candidates)
    return [op for op in candidates if len(op.variable_names) == fewest][-1]


# --------------------------------------------------------------------------- parsing


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for key in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _to_int(value: Any, what: str) -> int:
    if isinstance(value, bool):
        raise ParseError(f"{what}: expected an integer, got a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise ParseError(f"{what}: expected an integer, got {value!r}")


def _optional_int(latest: dict[str, Any], key: str, what: str) -> int | None:
    value = latest.get(key)
    return None if value is None else _to_int(value, f"{what} {key}")


def _required_int(latest: dict[str, Any], key: str, what: str) -> int:
    value = latest.get(key)
    if value is None:
        raise ParseError(f"{what}: missing {key}")
    return _to_int(value, f"{what} {key}")


def catalog_section_id(subject: str, course_number: str, class_number: str) -> str:
    """The synthetic id used for GetCatalog rows: ``bt:<subject>:<courseNumber>:<number>``."""
    return f"bt:{subject}:{course_number}:{class_number}"


def raise_on_graphql_errors(payload: dict[str, Any], operation: str) -> None:
    """Raise ``ParseError`` when the response carries a non-empty ``errors`` list."""
    errors = payload.get("errors")
    if errors:
        messages = [str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors]
        raise ParseError(f"{operation}: GraphQL errors: {'; '.join(messages)}")


def parse_catalog_class(entry: dict[str, Any], fetched_at: datetime, term: TermSpec) -> SnapshotRow | None:
    """One GetCatalog class → one row for its primary section, or ``None`` when the
    class has no ``primarySection.enrollment.latest`` (nothing to observe).

    Raises ``ParseError`` when ``latest`` is there but the counts are unusable.
    """
    latest = _dig(entry, "primarySection.enrollment.latest")
    if not isinstance(latest, dict):
        return None
    # Berkeleytime spells some subjects with spaces ("EL ENG"); subject, id and
    # course_key strip them ("ELENG", "bt:ELENG:16A:001", "ELENG 16A").
    subject = "".join(str(entry.get("subject") or "").split())
    course_number = str(entry.get("courseNumber") or "").strip()
    class_number = str(entry.get("number") or "").strip()
    if not (subject and course_number and class_number):
        raise ParseError(f"catalog entry lacks subject/courseNumber/number: {entry!r:.200}")
    section_id = catalog_section_id(subject, course_number, class_number)
    primary = entry["primarySection"]
    component = primary.get("component")
    if not component:
        raise ParseError(f"{section_id}: primarySection.component missing")
    status = latest.get("status")
    if not status:
        raise ParseError(f"{section_id}: enrollment.latest.status missing")
    session_id = entry.get("sessionId")
    return SnapshotRow(
        fetched_at=fetched_at,
        term_id=term.sis_term_id,
        section_id=section_id,
        course_key=f"{subject} {course_number}",
        subject=subject,
        catalog_number=course_number,
        class_number=class_number,
        section_number=str(primary.get("number") or class_number),
        component=str(component),
        is_primary=True,
        session_id=str(session_id) if session_id is not None else DEFAULT_SESSION_ID,
        enrolled_count=_required_int(latest, "enrolledCount", section_id),
        enroll_capacity=_required_int(latest, "maxEnroll", section_id),
        waitlist_count=_required_int(latest, "waitlistedCount", section_id),
        waitlist_capacity=_required_int(latest, "maxWaitlist", section_id),
        reserved_count=_optional_int(latest, "reservedCount", section_id),
        open_reserved=_optional_int(latest, "openReserved", section_id),
        status=str(status),
        section_status=None,
        source=SOURCE_NAME,
    )


def _catalog_rows(
    payload: dict[str, Any], fetched_at: datetime, term: TermSpec
) -> tuple[list[SnapshotRow], list[str]]:
    """``(rows, ids of classes whose latest counts could not be parsed)`` for one GetCatalog response."""
    raise_on_graphql_errors(payload, "GetCatalog")
    catalog = _dig(payload, "data.catalog")
    if not isinstance(catalog, list):
        raise ParseError("GetCatalog: payload has no data.catalog list")
    rows: list[SnapshotRow] = []
    failed: list[str] = []
    seen: set[str] = set()
    skipped = 0
    for entry in catalog:
        if not isinstance(entry, dict):
            raise ParseError(f"GetCatalog: catalog entry is {type(entry).__name__}")
        try:
            row = parse_catalog_class(entry, fetched_at, term)
        except ParseError as exc:
            logger.warning("GetCatalog: %s", exc)
            ident = catalog_section_id(
                str(entry.get("subject", "")).replace(" ", ""), str(entry.get("courseNumber", "")), str(entry.get("number", ""))
            )
            if ident not in seen:
                failed.append(ident)
            continue
        if row is None:
            skipped += 1
            continue
        if row["section_id"] in seen:
            logger.warning("GetCatalog: duplicate class %s (multiple sessions?); keeping the first", row["section_id"])
            continue
        seen.add(row["section_id"])
        rows.append(row)
    logger.info("GetCatalog: %d classes, %d rows, %d without enrollment, %d unparseable", len(catalog), len(rows), skipped, len(failed))
    return rows, failed


def parse_catalog(payload: dict[str, Any], fetched_at: datetime, term: TermSpec) -> list[SnapshotRow]:
    """Rows for every class in a GetCatalog response that has ``primarySection.enrollment.latest``."""
    return _catalog_rows(payload, fetched_at, term)[0]


# --------------------------------------------------------------------------- source


class BerkeleytimeSource:
    """Berkeleytime persisted-operations client. Implements the ``Source`` protocol."""

    name = SOURCE_NAME

    def __init__(
        self,
        transport: PostJson | None = None,
        ops_path: Path | str = DEFAULT_OPS_PATH,
        *,
        url: str = GRAPHQL_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        retries: int = 2,
        backoff_base_s: float = 1.0,
        sleep: Sleep = time.sleep,
        clock: Clock = utc_now,
        rng: Rng = random.random,
    ) -> None:
        self.url = url
        self.ops = load_persisted_ops(ops_path)
        self.retries = max(0, retries)
        self.backoff_base_s = backoff_base_s
        self._headers = {
            "User-Agent": config.USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._transport: PostJson = transport or (
            lambda u, body, headers: requests_post_json(u, body, headers, timeout_s=timeout_s)
        )
        self._sleep = sleep
        self._clock = clock
        self._rng = rng

    # ---- one operation

    def op_for(self, operation_name: str, variables: dict[str, Any]) -> PersistedOp:
        """The persisted op that will be sent for ``operation_name`` with these variables."""
        return select_op(self.ops, operation_name, variables)

    def execute(self, operation_name: str, variables: dict[str, Any], *, op: PersistedOp | None = None) -> dict[str, Any]:
        """POST the persisted operation and return the response's ``data`` object.

        GraphQL ``errors`` raise ``ParseError``; a non-200 status without an
        error body is retried on 5xx/429/transport failure (exponential
        backoff with jitter, or ``Retry-After`` when larger) and then raises
        ``BerkeleytimeError``. A 3xx is never followed and raises at once.
        ``op`` overrides the automatic choice among the recorded operations
        (several entries can share a name and variables; the gateway's schema
        may have moved on from some of them).
        """
        op = op or self.op_for(operation_name, variables)
        body = {"id": op.id, "variables": variables}
        status = 0
        payload: dict[str, Any] = {}
        detail = ""
        for attempt in range(1, self.retries + 2):
            try:
                status, payload, retry_after = unpack_transport_result(self._transport(self.url, body, self._headers))
                detail = ""
            except TransportError as exc:
                status, payload, retry_after, detail = 0, {}, None, str(exc)
            raise_on_graphql_errors(payload, operation_name)
            if status == 200:
                break
            if 300 <= status < 400:
                raise BerkeleytimeError(
                    f"{operation_name}: HTTP {status} unexpected redirect, not followed",
                    status=status,
                    operation=operation_name,
                )
            retryable = status == 0 or status == 429 or status >= 500
            if not retryable or attempt > self.retries:
                raise BerkeleytimeError(
                    f"{operation_name}: HTTP {status} after {attempt} attempt(s) {detail}".rstrip(),
                    status=status,
                    operation=operation_name,
                )
            delay = self.backoff_base_s * (2 ** (attempt - 1))
            if retry_after is not None:
                delay = max(delay, retry_after)
            delay += self._rng() * self.backoff_base_s
            logger.warning("%s: HTTP %s on attempt %d, retrying in %.1fs %s", operation_name, status or "transport error", attempt, delay, detail)
            self._sleep(delay)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ParseError(f"{operation_name}: response has no data object")
        return data

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
        """One ``GetCatalog(year, semester)`` request → one row per class with latest counts.

        Always full scope (one request observes everything). ``priority``,
        ``shard`` and ``time_budget_s`` are accepted for protocol compatibility
        and ignored. With ``limit`` the rows are truncated and ``universe_ids``
        is ``None`` (the universe is then deliberately unknown).
        """
        if priority is not None or shard is not None:
            logger.info("berkeleytime ignores priority/shard; GetCatalog is always full scope")
        variables = {"year": term.year, "semester": term.berkeleytime_semester}
        started = time.monotonic()
        data = self.execute("GetCatalog", variables)
        fetched_at = self._clock()
        rows, missing = _catalog_rows({"data": data}, fetched_at, term)
        truncated = limit is not None and len(rows) > limit
        if truncated:
            del rows[limit:]
        universe = None if truncated else {r["section_id"] for r in rows} | set(missing)
        logger.info("berkeleytime %s %d: %d rows in %.1fs", term.semester, term.year, len(rows), time.monotonic() - started)
        return FetchResult(rows=rows, missing_ids=missing, universe_ids=universe, scope="full")

    # ---- cross-check helpers

    def get_class(
        self,
        term: TermSpec,
        subject: str,
        catalog_number: str,
        class_number: str,
        session_id: str = DEFAULT_SESSION_ID,
    ) -> dict[str, Any]:
        """``GetClass`` for one class: the raw ``class`` object, whose ``primarySection``
        and ``sections[]`` carry real SIS ``sectionId`` values and latest counts.

        Sends ``sessionId`` (default ``"1"``), which the gateway requires.
        """
        variables = {
            "year": term.year,
            "semester": term.berkeleytime_semester,
            "sessionId": session_id,
            "subject": subject.replace(" ", ""),
            "courseNumber": catalog_number,
            "number": class_number,
        }
        data = self.execute("GetClass", variables)
        cls = data.get("class")
        if not isinstance(cls, dict):
            raise ParseError(f"GetClass: no class for {subject} {catalog_number} {class_number} ({term.name})")
        return cls

    def get_enrollment_history(
        self,
        term: TermSpec,
        subject: str,
        catalog_number: str,
        section_number: str,
        session_id: str = DEFAULT_SESSION_ID,
    ) -> list[dict[str, Any]]:
        """``GetEnrollment`` for one section: its ``history`` list (15-minute points, oldest first)."""
        variables = {
            "year": term.year,
            "semester": term.berkeleytime_semester,
            "sessionId": session_id,
            "subject": subject.replace(" ", ""),
            "courseNumber": catalog_number,
            "sectionNumber": section_number,
        }
        data = self.execute("GetEnrollment", variables)
        history = _dig(data, "enrollment.history")
        if not isinstance(history, list):
            raise ParseError(f"GetEnrollment: no history for {subject} {catalog_number} {section_number} ({term.name})")
        return history
