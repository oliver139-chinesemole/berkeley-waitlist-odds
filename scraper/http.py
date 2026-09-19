"""HTTP client for the scrapers. See docs/DESIGN_A2.md section 4.

Built on ``urllib.request`` because classes.berkeley.edu rejects the TLS
fingerprint of ``requests``/urllib3 (docs/PHASE0.md). Provides:

* a TLS context from the certifi CA bundle,
* an honest User-Agent and gzip content decoding,
* retries with exponential backoff plus jitter on 429, 5xx, connection
  errors and timeouts; no retry on 404 or any other 4xx,
* a process-wide rate limiter shared by every thread so that request
  *starts* are spaced at least ``min_interval_s`` apart,
* ``get_many``: a small thread pool with a wall-clock budget.

The sleep function, the clock and the URL opener are injectable so the
behaviour is testable without the network or real waiting.
"""
from __future__ import annotations

import gzip
import http.client
import logging
import random
import ssl
import threading
import time
import urllib.error
import urllib.request
import zlib
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Callable, Mapping, Protocol

import certifi

logger = logging.getLogger(__name__)

VERSION = "0.1.0"
# The repo owner is not known at build time; scraper.fetch passes the final
# User-Agent explicitly. This default exists so ad-hoc callers still send an
# honest, contactable identity.
REPO_OWNER = "<owner>"
REPO_URL = f"https://github.com/{REPO_OWNER}/berkeley-waitlist-odds"
CONTACT = "mailto:oliver139@berkeley.edu"
DEFAULT_USER_AGENT = f"berkeley-waitlist-odds/{VERSION} (+{REPO_URL}; {CONTACT})"

GZIP_MAGIC = b"\x1f\x8b"
MAX_BACKOFF_S = 60.0
BUDGET_EXHAUSTED = "budget exhausted"


class HttpError(Exception):
    """A request failed for good (after retries, or without a retry).

    ``status`` is the HTTP status code, or 0 when no HTTP response was
    received (DNS, connection, TLS, timeout) or the request was never
    attempted (``get_many`` budget exhausted). ``url`` is the requested URL.
    ``str(exc)`` always contains the status, the url and the message.
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
        """True when ``get_many`` never attempted this URL."""
        return self.status == 0 and BUDGET_EXHAUSTED in self.message


class _ResponseLike(Protocol):
    """What ``HttpClient`` needs from an opened response (real or fake)."""

    status: int
    headers: Mapping[str, str] | Any

    def read(self) -> bytes: ...

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


def _retry_after_seconds(headers: Any) -> float | None:
    """Parse an integer ``Retry-After`` header; None when absent or not a number."""
    if headers is None:
        return None
    try:
        raw = headers.get("Retry-After")
    except AttributeError:
        return None
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except ValueError:
        return None
    return value if value >= 0 else None


class HttpClient:
    """Rate-limited, retrying GET client shared by all sources.

    ``sleep``, ``clock`` (monotonic seconds), ``opener`` and ``rng`` (uniform
    [0, 1)) are injectable for tests. The rate limiter is global to the
    instance: every ``get`` (including each retry attempt and every worker in
    ``get_many``) reserves the next start slot under one lock.
    """

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval_s: float = 1.0,
        max_concurrency: int = 2,
        timeout_s: float = 40,
        retries: int = 3,
        backoff_base_s: float = 1.0,
        ca_file: str | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
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
        self._user_agent = user_agent
        self._min_interval = float(min_interval_s)
        self._max_concurrency = int(max_concurrency)
        self._timeout_s = float(timeout_s)
        self._retries = int(retries)
        self._backoff_base = float(backoff_base_s)
        self._sleep = sleep
        self._clock = clock
        self._rng = rng
        self._opener: _OpenerLike = opener if opener is not None else build_opener(ca_file)
        self._lock = threading.Lock()
        self._next_start = self._clock()

    # -- rate limiting -----------------------------------------------------

    def _acquire_slot(self) -> float:
        """Reserve the next request start and sleep until it.

        Returns the reserved start time (in ``clock`` units). Reservation
        happens under the lock; the sleep happens outside it so several
        threads can queue up on consecutive slots.
        """
        with self._lock:
            now = self._clock()
            start = max(now, self._next_start)
            self._next_start = start + self._min_interval
        delay = start - now
        if delay > 0:
            self._sleep(delay)
        return start

    def _backoff_delay(self, attempt: int, error: HttpError) -> float:
        """Exponential backoff with jitter; honours a larger Retry-After."""
        base = min(self._backoff_base * (2**attempt), MAX_BACKOFF_S)
        delay = base + self._rng() * self._backoff_base
        if error.retry_after_s is not None:
            delay = max(delay, min(error.retry_after_s, MAX_BACKOFF_S))
        return delay

    # -- single request ----------------------------------------------------

    def get(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        """GET ``url`` and return the decoded body.

        Retries transient failures (429, 5xx, no response) up to ``retries``
        times with exponential backoff plus jitter. 404 and every other 4xx
        raise ``HttpError`` immediately. Raises ``HttpError`` once retries
        are exhausted.
        """
        attempt = 0
        while True:
            self._acquire_slot()
            try:
                return self._request_once(url, headers)
            except HttpError as exc:
                if not exc.retryable or attempt >= self._retries:
                    raise
                delay = self._backoff_delay(attempt, exc)
                logger.warning(
                    "retrying %s after %s (attempt %d of %d, backoff %.1fs)",
                    url,
                    exc,
                    attempt + 1,
                    self._retries,
                    delay,
                )
                self._sleep(delay)
                attempt += 1

    def _request_once(self, url: str, headers: dict[str, str] | None) -> bytes:
        """One attempt: open, read, decode. Maps every failure to HttpError."""
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
                body = response.read()
                encoding = str(response.headers.get("Content-Encoding", "") or "")
        except urllib.error.HTTPError as exc:
            raise HttpError(
                exc.code, url, exc.reason if isinstance(exc.reason, str) else str(exc.reason),
                retry_after_s=_retry_after_seconds(exc.headers),
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            raise HttpError(0, url, f"{type(exc).__name__}: {exc}") from exc
        if status >= 400:
            raise HttpError(status, url, "error status returned by opener")
        return self._decode_body(body, encoding, url)

    @staticmethod
    def _decode_body(body: bytes, content_encoding: str, url: str) -> bytes:
        """Gunzip when the response says gzip (or carries the gzip magic)."""
        if "gzip" not in content_encoding.lower() and not body.startswith(GZIP_MAGIC):
            return body
        try:
            return gzip.decompress(body)
        except (OSError, EOFError, zlib.error) as exc:
            # A truncated or corrupt body is transient: let get() retry it.
            raise HttpError(0, url, f"bad gzip body: {exc}", retryable=True) from exc

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
        (measured from the call); URLs that were never attempted are reported
        from the calling thread with ``HttpError(0, url, "budget exhausted")``.
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
                    in_flight.add(pool.submit(self._fetch_and_report, url, on_result))
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

    def _fetch_and_report(self, url: str, on_result: Callable[[str, bytes | HttpError], None]) -> None:
        payload: bytes | HttpError
        try:
            payload = self.get(url)
        except HttpError as exc:
            payload = exc
        on_result(url, payload)
