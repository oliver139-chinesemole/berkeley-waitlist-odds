"""HTTP client for the scrapers. See docs/DESIGN_A2.md section 4.

Built on ``urllib.request`` because classes.berkeley.edu rejects the TLS
fingerprint of ``requests``/urllib3 (docs/PHASE0.md). Provides:

* a TLS context from the certifi CA bundle,
* the project User-Agent (``scraper.config.USER_AGENT``) and gzip decoding,
* retries with exponential backoff plus jitter on 429, 5xx, connection
  errors and timeouts; no retry on 404 or any other 4xx. ``Retry-After``
  (delay-seconds or HTTP-date) is honoured up to ``RETRY_AFTER_MAX_S``; the
  computed exponential part is capped at ``MAX_BACKOFF_S``,
* a process-wide rate limiter shared by every thread so that request
  *starts* are spaced at least ``min_interval_s`` apart. A 429, or a 5xx
  that carries ``Retry-After``, pushes the limiter forward so *every* worker
  pauses, not only the one that saw the error,
* a body size limit (``max_body_bytes``, compressed and inflated) so a
  runaway or hostile response cannot exhaust memory,
* ``get_many``: a small thread pool with a wall-clock budget that also stops
  in-flight retries once the budget has passed.

The sleep function, the clocks, the URL opener and the random source are
injectable so the behaviour is testable without the network or real waiting.
"""
from __future__ import annotations

import email.utils
import http.client
import logging
import math
import random
import ssl
import threading
import time
import urllib.error
import urllib.request
import zlib
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol

import certifi

from scraper import config

logger = logging.getLogger(__name__)

GZIP_MAGIC = b"\x1f\x8b"
MAX_BACKOFF_S = 60.0  # cap on the computed exponential part of a backoff
RETRY_AFTER_MAX_S = 600.0  # cap on a server-supplied Retry-After
DEFAULT_TIMEOUT_S = 20.0  # per-attempt socket timeout; section pages answer in ~1 s
DEFAULT_MAX_BODY_BYTES = 4 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
BUDGET_EXHAUSTED = "budget exhausted"
BODY_TOO_LARGE = "response body exceeds"


class HttpError(Exception):
    """A request failed for good (after retries, or without a retry).

    ``status`` is the HTTP status code, or 0 when no HTTP response was
    received (DNS, connection, TLS, timeout), the body was rejected
    (``body_too_large``) or the request was never attempted
    (``budget_exhausted``). ``url`` is the requested URL. ``str(exc)`` always
    contains the status, the url and the message.
    """

    def __init__(
        self,
        status: int,
        url: str,
        message: str = "",
        *,
        retryable: bool | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        self.status = int(status)
        self.url = url
        self.message = message
        self.retry_after_s = retry_after_s
        self._retryable = retryable
        text = f"HTTP {self.status} for {url}"
        super().__init__(f"{text}: {message}" if message else text)

    @property
    def retryable(self) -> bool:
        """True for transient failures: no response (0), 429, or any 5xx."""
        if self._retryable is not None:
            return self._retryable
        return self.status == 0 or self.status == 429 or self.status >= 500

    @property
    def budget_exhausted(self) -> bool:
        """True when ``get_many`` (or a deadline) never let this URL start."""
        return self.status == 0 and BUDGET_EXHAUSTED in self.message

    @property
    def body_too_large(self) -> bool:
        """True when the response body exceeded ``max_body_bytes`` (never retried)."""
        return self.status == 0 and BODY_TOO_LARGE in self.message


class _ResponseLike(Protocol):
    """What ``HttpClient`` needs from an opened response (real or fake).

    ``read`` should accept a size like ``http.client.HTTPResponse.read``; a
    fake whose ``read()`` takes no argument is tolerated (read whole).
    """

    status: int
    headers: Mapping[str, str] | Any

    def read(self, amt: int | None = None) -> bytes: ...

    def __enter__(self) -> "_ResponseLike": ...

    def __exit__(self, *exc: object) -> object: ...


class _OpenerLike(Protocol):
    """What ``HttpClient`` needs from a URL opener (real or fake)."""

    def open(self, request: urllib.request.Request, timeout: float | None = None) -> _ResponseLike: ...


def build_ssl_context(ca_file: str | None = None) -> ssl.SSLContext:
    """Default TLS context verifying against certifi (or ``ca_file``)."""
    return ssl.create_default_context(cafile=ca_file or certifi.where())


def build_opener(ca_file: str | None = None) -> urllib.request.OpenerDirector:
    """A urllib opener whose HTTPS handler uses the certifi context."""
    handler = urllib.request.HTTPSHandler(context=build_ssl_context(ca_file))
    return urllib.request.build_opener(handler)


def utc_now() -> datetime:
    """Wall-clock UTC now; the reference point for an HTTP-date ``Retry-After``."""
    return datetime.now(timezone.utc)


def parse_retry_after(value: Any, now: datetime | None = None) -> float | None:
    """Seconds to wait for a ``Retry-After`` header value; None when absent or unparseable.

    Accepts both forms of RFC 7231 section 7.1.3: a non-negative number of
    seconds, or an HTTP-date (parsed with ``email.utils.parsedate_to_datetime``)
    measured from ``now`` (wall clock UTC by default). A date in the past
    yields 0.0; a negative or non-finite number is treated as absent.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - (now or utc_now())).total_seconds()
        return max(0.0, seconds)
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _retry_after_seconds(headers: Any, now: datetime | None = None) -> float | None:
    """``Retry-After`` of a response/error header mapping as seconds, or None."""
    if headers is None:
        return None
    try:
        raw = headers.get("Retry-After")
    except AttributeError:
        return None
    return parse_retry_after(raw, now)


def _content_length(headers: Any) -> int | None:
    if headers is None:
        return None
    try:
        raw = headers.get("Content-Length")
    except AttributeError:
        return None
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


class HttpClient:
    """Rate-limited, retrying GET client shared by all sources.

    ``sleep``, ``clock`` (monotonic seconds), ``utc_now`` (wall clock, for an
    HTTP-date Retry-After), ``opener`` and ``rng`` (uniform [0, 1)) are
    injectable for tests. The rate limiter is global to the instance: every
    ``get`` (including each retry attempt and every worker in ``get_many``)
    reserves the next start slot under one lock, and a 429 (or a 5xx with
    Retry-After) pushes that slot forward for everyone.
    """

    def __init__(
        self,
        user_agent: str = config.USER_AGENT,
        min_interval_s: float = 1.0,
        max_concurrency: int = 2,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        retries: int = 3,
        backoff_base_s: float = 1.0,
        ca_file: str | None = None,
        *,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = utc_now,
        opener: _OpenerLike | None = None,
        rng: Callable[[], float] = random.random,
    ) -> None:
        if min_interval_s < 0:
            raise ValueError("min_interval_s must be >= 0")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if retries < 0:
            raise ValueError("retries must be >= 0")
        if backoff_base_s < 0:
            raise ValueError("backoff_base_s must be >= 0")
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be >= 1")
        self._user_agent = user_agent
        self._min_interval = float(min_interval_s)
        self._max_concurrency = int(max_concurrency)
        self._timeout_s = float(timeout_s)
        self._retries = int(retries)
        self._backoff_base = float(backoff_base_s)
        self._max_body_bytes = int(max_body_bytes)
        self._sleep = sleep
        self._clock = clock
        self._utc_now = utc_now
        self._rng = rng
        self._opener: _OpenerLike = opener if opener is not None else build_opener(ca_file)
        self._lock = threading.Lock()
        self._next_start = self._clock()

    # -- rate limiting -----------------------------------------------------

    def _acquire_slot(self, deadline: float | None = None) -> float | None:
        """Reserve the next request start and sleep until it.

        Returns the reserved start time (in ``clock`` units), or None without
        reserving when that start would fall at or after ``deadline``.
        Reservation happens under the lock; the sleep happens outside it so
        several threads can queue up on consecutive slots.
        """
        with self._lock:
            now = self._clock()
            start = max(now, self._next_start)
            if deadline is not None and start >= deadline:
                return None
            self._next_start = start + self._min_interval
        delay = start - now
        if delay > 0:
            self._sleep(delay)
        return start

    def _pause_all(self, delay: float) -> None:
        """Push the shared limiter forward so no worker starts a request for ``delay`` seconds."""
        with self._lock:
            self._next_start = max(self._next_start, self._clock() + delay)

    def _backoff_delay(self, attempt: int, error: HttpError) -> float:
        """Exponential backoff (capped) with jitter; a larger Retry-After wins (capped separately)."""
        base = min(self._backoff_base * (2**attempt), MAX_BACKOFF_S)
        delay = base + self._rng() * self._backoff_base
        if error.retry_after_s is not None:
            delay = max(delay, min(error.retry_after_s, RETRY_AFTER_MAX_S))
        return delay

    @staticmethod
    def _pauses_everyone(error: HttpError) -> bool:
        """429 always; a 5xx only when the server said how long to wait."""
        return error.status == 429 or (error.status >= 500 and error.retry_after_s is not None)

    # -- single request ----------------------------------------------------

    def get(self, url: str, headers: dict[str, str] | None = None, *, deadline: float | None = None) -> bytes:
        """GET ``url`` and return the decoded body.

        Retries transient failures (429, 5xx, no response) up to ``retries``
        times with exponential backoff plus jitter. 404 and every other 4xx
        raise ``HttpError`` immediately, as does a body over ``max_body_bytes``.
        Raises ``HttpError`` once retries are exhausted.

        ``deadline`` (in ``clock`` units, i.e. monotonic seconds) bounds the
        retries: once it has passed, or when a backoff sleep would end past
        it, the last error is raised instead of retrying. The first attempt
        is skipped too (``HttpError.budget_exhausted``) when the shared
        limiter cannot start it before the deadline.
        """
        attempt = 0
        last: HttpError | None = None
        while True:
            if self._acquire_slot(deadline) is None:
                if last is None:
                    raise HttpError(0, url, f"{BUDGET_EXHAUSTED} before the request could start")
                logger.warning("deadline passed; not retrying %s after %s", url, last)
                raise last
            try:
                return self._request_once(url, headers)
            except HttpError as exc:
                last = exc
                pause = self._pauses_everyone(exc)
                will_retry = exc.retryable and attempt < self._retries
                if not (pause or will_retry):
                    raise
                delay = self._backoff_delay(attempt, exc)
                if pause:
                    self._pause_all(delay)
                if not will_retry:
                    raise
                if deadline is not None and self._clock() + delay >= deadline:
                    logger.warning("not retrying %s after %s: a %.1fs backoff would pass the deadline", url, exc, delay)
                    raise
                logger.warning(
                    "retrying %s after %s (attempt %d of %d, backoff %.1fs%s)",
                    url,
                    exc,
                    attempt + 1,
                    self._retries,
                    delay,
                    ", all workers paused" if pause else "",
                )
                self._sleep(delay)
                attempt += 1

    def _request_once(self, url: str, headers: dict[str, str] | None) -> bytes:
        """One attempt: open, read (bounded), decode. Maps every failure to HttpError."""
        request_headers = {
            "User-Agent": self._user_agent,
            "Accept-Encoding": "gzip",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        }
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, headers=request_headers, method="GET")
        try:
            with self._opener.open(request, timeout=self._timeout_s) as response:
                status = int(getattr(response, "status", 200) or 200)
                if status >= 400:
                    raise HttpError(
                        status,
                        url,
                        "error status returned by opener",
                        retry_after_s=_retry_after_seconds(response.headers, self._utc_now()),
                    )
                encoding = str(response.headers.get("Content-Encoding", "") or "")
                body = self._read_body(response, url)
        except urllib.error.HTTPError as exc:
            raise HttpError(
                exc.code,
                url,
                exc.reason if isinstance(exc.reason, str) else str(exc.reason),
                retry_after_s=_retry_after_seconds(exc.headers, self._utc_now()),
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            raise HttpError(0, url, f"{type(exc).__name__}: {exc}") from exc
        return self._decode_body(body, encoding, url, self._max_body_bytes)

    def _read_body(self, response: _ResponseLike, url: str) -> bytes:
        """Read the (still compressed) body in chunks, failing hard past ``max_body_bytes``."""
        limit = self._max_body_bytes
        declared = _content_length(response.headers)
        if declared is not None and declared > limit:
            raise self._too_large(url, f"Content-Length {declared}")
        try:
            chunk = response.read(READ_CHUNK_BYTES)
        except TypeError:
            # A fake whose read() takes no size argument: read it whole, still bounded.
            body = response.read()
            if len(body) > limit:
                raise self._too_large(url, f"{len(body)} bytes") from None
            return body
        chunks: list[bytes] = []
        total = 0
        while chunk:
            total += len(chunk)
            if total > limit:
                raise self._too_large(url, f"more than {total - len(chunk)} bytes")
            chunks.append(chunk)
            chunk = response.read(READ_CHUNK_BYTES)
        return b"".join(chunks)

    @staticmethod
    def _too_large(url: str, detail: str) -> HttpError:
        return HttpError(0, url, f"{BODY_TOO_LARGE} the limit ({detail})", retryable=False)

    @staticmethod
    def _decode_body(body: bytes, content_encoding: str, url: str, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> bytes:
        """Gunzip when the response says gzip (or carries the gzip magic), capping the inflated size."""
        if not body or ("gzip" not in content_encoding.lower() and not body.startswith(GZIP_MAGIC)):
            return body
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            out = inflater.decompress(body, max_bytes + 1)
        except zlib.error as exc:
            # A corrupt body is transient: let get() retry it.
            raise HttpError(0, url, f"bad gzip body: {exc}", retryable=True) from exc
        if len(out) > max_bytes:
            raise HttpClient._too_large(url, f"more than {max_bytes} bytes after gzip decoding")
        if not inflater.eof:
            # Truncated stream (the whole input was consumed without reaching the trailer).
            raise HttpError(0, url, "bad gzip body: truncated stream", retryable=True)
        return out

    # -- many requests -----------------------------------------------------

    def get_many(
        self,
        urls: list[str],
        on_result: Callable[[str, bytes | HttpError], None],
        time_budget_s: float | None = None,
    ) -> None:
        """Fetch ``urls`` with up to ``max_concurrency`` workers.

        ``on_result(url, payload)`` is called from a worker thread with the
        body or the final ``HttpError`` of each attempted URL, so it must be
        thread-safe. Scheduling stops once ``time_budget_s`` has elapsed
        (measured from the call) and in-flight requests stop retrying at the
        same deadline; URLs that were never attempted are reported from the
        calling thread with ``HttpError(0, url, "budget exhausted")``.
        Exceptions raised by ``on_result`` propagate to the caller.
        """
        started = self._clock()
        deadline = None if time_budget_s is None else started + float(time_budget_s)
        pending: deque[str] = deque(urls)
        in_flight: set[Future[None]] = set()
        n_attempted = 0
        with ThreadPoolExecutor(max_workers=self._max_concurrency, thread_name_prefix="http") as pool:
            while pending or in_flight:
                while pending and len(in_flight) < self._max_concurrency and not self._past(deadline):
                    url = pending.popleft()
                    in_flight.add(pool.submit(self._fetch_and_report, url, on_result, deadline))
                    n_attempted += 1
                if not in_flight:
                    break
                done, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in done:
                    future.result()
        if pending:
            logger.warning(
                "time budget of %.0fs exhausted: %d of %d urls never attempted",
                time_budget_s or 0.0,
                len(pending),
                len(urls),
            )
        for url in pending:
            on_result(url, HttpError(0, url, BUDGET_EXHAUSTED))
        logger.debug(
            "get_many: %d attempted, %d skipped, %.1fs elapsed",
            n_attempted,
            len(pending),
            self._clock() - started,
        )

    def _past(self, deadline: float | None) -> bool:
        return deadline is not None and self._clock() >= deadline

    def _fetch_and_report(
        self,
        url: str,
        on_result: Callable[[str, bytes | HttpError], None],
        deadline: float | None = None,
    ) -> None:
        payload: bytes | HttpError
        try:
            payload = self.get(url, deadline=deadline)
        except HttpError as exc:
            payload = exc
        on_result(url, payload)
