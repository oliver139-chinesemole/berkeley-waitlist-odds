"""Offline tests for scraper.http (fake opener, fake clock, no sleeping)."""
from __future__ import annotations

import email.message
import email.utils
import gzip
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

import scraper.http
from scraper import config
from scraper.http import (
    MAX_BACKOFF_S,
    READ_CHUNK_BYTES,
    RETRY_AFTER_MAX_S,
    HttpClient,
    HttpError,
    parse_retry_after,
)


class FakeClock:
    """Monotonic clock whose ``sleep`` advances time instead of waiting."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self.t

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.sleeps.append(seconds)
            self.t += seconds

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.t += seconds


class FakeResponse:
    """Response whose ``read`` takes an optional size, like ``HTTPResponse.read``.

    ``reads`` counts read calls; the cursor resets on ``__enter__`` so one
    instance can be served repeatedly by ``FakeOpener``.
    """

    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}
        self.reads = 0
        self._pos = 0

    def __enter__(self) -> "FakeResponse":
        self._pos = 0
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, amt: int | None = None) -> bytes:
        self.reads += 1
        end = len(self.body) if amt is None else self._pos + amt
        chunk = self.body[self._pos:end]
        self._pos += len(chunk)
        return chunk


def http_error(url: str, code: int, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    msg = email.message.Message()
    for key, value in (headers or {}).items():
        msg[key] = value
    return urllib.error.HTTPError(url, code, f"status {code}", msg, None)


class FakeOpener:
    """Maps a URL to a queue of outcomes: a FakeResponse, an exception to
    raise, or a zero-arg callable producing either. The last outcome repeats.
    Records the clock reading at every open when a clock is given."""

    def __init__(self, routes: dict[str, list], clock: FakeClock | None = None) -> None:
        self.routes = {url: list(queue) for url, queue in routes.items()}
        self.clock = clock
        self.calls: list[str] = []
        self.starts: list[float] = []
        self.timeouts: list[float | None] = []
        self._lock = threading.Lock()

    def start_of(self, url: str) -> float:
        """Clock reading at the first open of ``url`` (needs a clock)."""
        return self.starts[self.calls.index(url)]

    def open(self, request: urllib.request.Request, timeout: float | None = None) -> FakeResponse:
        url = request.full_url
        with self._lock:
            self.calls.append(url)
            self.timeouts.append(timeout)
            if self.clock is not None:
                self.starts.append(self.clock.now())
            queue = self.routes.get(url)
            if not queue:
                raise AssertionError(f"unexpected url {url}")
            outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(outcome):
            outcome = outcome()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def make_client(opener: FakeOpener, clock: FakeClock, **kwargs) -> HttpClient:
    defaults = dict(
        user_agent="test-agent/0",
        min_interval_s=1.0,
        max_concurrency=1,
        retries=3,
        backoff_base_s=1.0,
        sleep=clock.sleep,
        clock=clock.now,
        opener=opener,
        rng=lambda: 0.5,
    )
    defaults.update(kwargs)
    return HttpClient(**defaults)


URL = "https://example.test/page"


def test_retry_on_500_then_success() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [http_error(URL, 500), FakeResponse(b"ok")]})
    client = make_client(opener, clock)

    assert client.get(URL) == b"ok"
    assert opener.calls == [URL, URL]
    # one backoff sleep: base * 2**0 + jitter(0.5 * base) = 1.5
    assert 1.5 in clock.sleeps


def test_retry_on_429_honours_retry_after() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [http_error(URL, 429, {"Retry-After": "7"}), FakeResponse(b"ok")]})
    client = make_client(opener, clock)

    assert client.get(URL) == b"ok"
    assert max(clock.sleeps) == 7.0


def test_retry_on_urlerror_and_timeout() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [urllib.error.URLError("dns"), TimeoutError("slow"), FakeResponse(b"ok")]})
    client = make_client(opener, clock)

    assert client.get(URL) == b"ok"
    assert opener.calls == [URL] * 3


def test_no_retry_on_404() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [http_error(URL, 404), FakeResponse(b"never")]})
    client = make_client(opener, clock)

    with pytest.raises(HttpError) as info:
        client.get(URL)
    assert info.value.status == 404
    assert info.value.url == URL
    assert not info.value.retryable
    assert opener.calls == [URL]
    assert clock.sleeps == []


def test_no_retry_on_other_4xx() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [http_error(URL, 403)]})
    client = make_client(opener, clock)

    with pytest.raises(HttpError) as info:
        client.get(URL)
    assert info.value.status == 403
    assert opener.calls == [URL]


def test_gives_up_after_retries() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [http_error(URL, 503)]})
    client = make_client(opener, clock, retries=2)

    with pytest.raises(HttpError) as info:
        client.get(URL)
    assert info.value.status == 503
    assert len(opener.calls) == 3  # first attempt + 2 retries
    assert len([s for s in clock.sleeps if s >= 1.0]) == 2  # two backoff sleeps


def test_error_status_returned_by_opener_is_mapped() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [FakeResponse(b"", status=500), FakeResponse(b"ok", status=200)]})
    client = make_client(opener, clock)

    assert client.get(URL) == b"ok"
    assert opener.calls == [URL, URL]


def test_sends_user_agent_and_accept_encoding() -> None:
    clock = FakeClock()
    seen: dict[str, str] = {}

    class RecordingOpener(FakeOpener):
        def open(self, request: urllib.request.Request, timeout: float | None = None) -> FakeResponse:
            seen.update({k.lower(): v for k, v in request.header_items()})
            return super().open(request, timeout)

    opener = RecordingOpener({URL: [FakeResponse(b"ok")]})
    client = make_client(opener, clock)
    client.get(URL, headers={"X-Extra": "1"})
    assert seen["user-agent"] == "test-agent/0"
    assert seen["accept-encoding"] == "gzip"
    assert seen["x-extra"] == "1"


def test_gzip_decoding() -> None:
    clock = FakeClock()
    payload = b"<html>hello</html>"
    opener = FakeOpener(
        {
            "https://example.test/gz": [FakeResponse(gzip.compress(payload), headers={"Content-Encoding": "gzip"})],
            "https://example.test/magic": [FakeResponse(gzip.compress(payload))],
            "https://example.test/plain": [FakeResponse(payload)],
        }
    )
    client = make_client(opener, clock)
    assert client.get("https://example.test/gz") == payload
    assert client.get("https://example.test/magic") == payload
    assert client.get("https://example.test/plain") == payload


def test_corrupt_gzip_is_retried() -> None:
    clock = FakeClock()
    opener = FakeOpener(
        {
            URL: [
                FakeResponse(b"\x1f\x8bgarbage", headers={"Content-Encoding": "gzip"}),
                FakeResponse(b"ok"),
            ]
        }
    )
    client = make_client(opener, clock)
    assert client.get(URL) == b"ok"
    assert opener.calls == [URL, URL]


def test_rate_limiter_spacing_sequential() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [FakeResponse(b"ok")]}, clock=clock)
    client = make_client(opener, clock, min_interval_s=2.0)

    for _ in range(3):
        client.get(URL)
    assert opener.starts == [0.0, 2.0, 4.0]


class FrozenClock(FakeClock):
    """Records sleeps without advancing time, so every reservation is computed
    against the same "now" and the requested waits are deterministic across
    thread interleavings."""

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.sleeps.append(seconds)


def test_rate_limiter_spacing_across_threads() -> None:
    clock = FrozenClock()
    urls = [f"https://example.test/{i}" for i in range(6)]
    opener = FakeOpener({u: [FakeResponse(b"ok")] for u in urls}, clock=clock)
    client = make_client(opener, clock, min_interval_s=1.0, max_concurrency=3)

    results: dict[str, bytes | HttpError] = {}
    lock = threading.Lock()

    def on_result(url: str, payload: bytes | HttpError) -> None:
        with lock:
            results[url] = payload

    client.get_many(urls, on_result)
    assert set(results) == set(urls)
    assert all(payload == b"ok" for payload in results.values())
    assert len(opener.starts) == 6
    # Six reservations against a frozen now=0 must be slots 0,1,2,3,4,5: the
    # first waits nothing, the others wait until their own slot.
    assert sorted(clock.sleeps) == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_rate_limiter_applies_to_retries() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [http_error(URL, 500), FakeResponse(b"ok")]}, clock=clock)
    client = make_client(opener, clock, min_interval_s=1.0, backoff_base_s=0.0)

    client.get(URL)
    assert opener.starts == [0.0, 1.0]


def test_get_many_reports_errors_and_continues() -> None:
    clock = FakeClock()
    good = "https://example.test/good"
    bad = "https://example.test/bad"
    opener = FakeOpener({good: [FakeResponse(b"ok")], bad: [http_error(bad, 404)]})
    client = make_client(opener, clock, min_interval_s=0.0)
    results: dict[str, bytes | HttpError] = {}

    client.get_many([bad, good], lambda url, payload: results.__setitem__(url, payload))
    assert results[good] == b"ok"
    assert isinstance(results[bad], HttpError)
    assert results[bad].status == 404


def test_get_many_time_budget_cutoff() -> None:
    clock = FakeClock()
    urls = [f"https://example.test/{i}" for i in range(4)]

    def slow_ok() -> FakeResponse:
        clock.advance(10.0)
        return FakeResponse(b"ok")

    opener = FakeOpener({u: [slow_ok] for u in urls})
    client = make_client(opener, clock, min_interval_s=0.0, max_concurrency=1)
    results: dict[str, bytes | HttpError] = {}

    client.get_many(urls, lambda url, payload: results.__setitem__(url, payload), time_budget_s=25.0)

    # t=0 start #0 (ends 10), t=10 start #1 (ends 20), t=20 start #2 (ends 30), t=30 >= 25: stop.
    assert opener.calls == urls[:3]
    assert [results[u] for u in urls[:3]] == [b"ok"] * 3
    skipped = results[urls[3]]
    assert isinstance(skipped, HttpError)
    assert skipped.status == 0
    assert skipped.url == urls[3]
    assert "budget exhausted" in str(skipped)
    assert skipped.budget_exhausted


def test_get_many_zero_budget_attempts_nothing() -> None:
    clock = FakeClock()
    urls = ["https://example.test/a", "https://example.test/b"]
    opener = FakeOpener({u: [FakeResponse(b"ok")] for u in urls})
    client = make_client(opener, clock)
    results: dict[str, bytes | HttpError] = {}

    client.get_many(urls, lambda url, payload: results.__setitem__(url, payload), time_budget_s=0.0)
    assert opener.calls == []
    assert all(isinstance(results[u], HttpError) and results[u].budget_exhausted for u in urls)


def test_constructor_validation() -> None:
    with pytest.raises(ValueError):
        HttpClient("ua", min_interval_s=-1, opener=FakeOpener({}))
    with pytest.raises(ValueError):
        HttpClient("ua", max_concurrency=0, opener=FakeOpener({}))
    with pytest.raises(ValueError):
        HttpClient("ua", retries=-1, opener=FakeOpener({}))


# -- Retry-After parsing and caps (review finding B) -------------------------


def test_parse_retry_after_numeric_http_date_and_garbage() -> None:
    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
    later = email.utils.format_datetime(now + timedelta(seconds=90), usegmt=True)
    earlier = email.utils.format_datetime(now - timedelta(seconds=90), usegmt=True)

    assert parse_retry_after("7") == 7.0
    assert parse_retry_after(" 0 ") == 0.0
    assert parse_retry_after("2.5") == 2.5
    assert parse_retry_after(later, now=now) == 90.0
    assert parse_retry_after(earlier, now=now) == 0.0  # a date in the past: wait no longer
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("soon") is None
    assert parse_retry_after("-3") is None
    assert parse_retry_after("nan") is None
    assert parse_retry_after("inf") is None


def test_retry_after_http_date_is_honoured() -> None:
    clock = FakeClock()
    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
    when = email.utils.format_datetime(now + timedelta(seconds=90), usegmt=True)
    opener = FakeOpener({URL: [http_error(URL, 429, {"Retry-After": when}), FakeResponse(b"ok")]})
    client = make_client(opener, clock, utc_now=lambda: now)

    assert client.get(URL) == b"ok"
    assert max(clock.sleeps) == 90.0


def test_retry_after_date_in_the_past_falls_back_to_backoff() -> None:
    clock = FakeClock()
    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
    when = email.utils.format_datetime(now - timedelta(seconds=90), usegmt=True)
    opener = FakeOpener({URL: [http_error(URL, 429, {"Retry-After": when}), FakeResponse(b"ok")]})
    client = make_client(opener, clock, utc_now=lambda: now)

    assert client.get(URL) == b"ok"
    assert clock.sleeps == [1.5]  # base 1.0 * 2**0 + jitter 0.5


def test_retry_after_is_honoured_above_the_exponential_cap() -> None:
    assert RETRY_AFTER_MAX_S > MAX_BACKOFF_S
    for header, expected in (("120", 120.0), ("3600", RETRY_AFTER_MAX_S)):
        clock = FakeClock()
        opener = FakeOpener({URL: [http_error(URL, 429, {"Retry-After": header}), FakeResponse(b"ok")]})
        client = make_client(opener, clock)
        assert client.get(URL) == b"ok"
        assert max(clock.sleeps) == expected, header


def test_exponential_part_stays_capped_at_max_backoff() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [http_error(URL, 503)]})
    client = make_client(opener, clock, retries=6, backoff_base_s=10.0, min_interval_s=0.0, rng=lambda: 0.0)

    with pytest.raises(HttpError):
        client.get(URL)
    assert clock.sleeps == [10.0, 20.0, 40.0, 60.0, 60.0, 60.0]


# -- a 429 pauses every worker through the shared limiter (finding B) --------

A_URL = "https://example.test/a"
B_URL = "https://example.test/b"


def test_429_pushes_the_shared_limiter_even_without_a_retry() -> None:
    clock = FrozenClock()
    opener = FakeOpener({A_URL: [http_error(A_URL, 429, {"Retry-After": "30"})], B_URL: [FakeResponse(b"ok")]})
    client = make_client(opener, clock, retries=0, min_interval_s=0.0)

    with pytest.raises(HttpError):
        client.get(A_URL)
    assert clock.sleeps == []  # no retry of A, so no backoff sleep of its own
    assert client.get(B_URL) == b"ok"
    assert clock.sleeps == [30.0]  # B waited for the deadline A's 429 set


def test_5xx_pushes_the_limiter_only_when_it_carries_retry_after() -> None:
    for headers, expected in (({"Retry-After": "45"}, [45.0]), ({}, [])):
        clock = FrozenClock()
        opener = FakeOpener({A_URL: [http_error(A_URL, 503, headers)], B_URL: [FakeResponse(b"ok")]})
        client = make_client(opener, clock, retries=0, min_interval_s=0.0)
        with pytest.raises(HttpError):
            client.get(A_URL)
        assert client.get(B_URL) == b"ok"
        assert clock.sleeps == expected, headers


def test_429_backoff_pauses_another_worker_mid_flight() -> None:
    """Worker A hits a 429; a request B started during A's backoff waits for the same deadline."""
    clock = FakeClock()
    opener = FakeOpener(
        {A_URL: [http_error(A_URL, 429, {"Retry-After": "30"}), FakeResponse(b"ok")], B_URL: [FakeResponse(b"ok")]},
        clock=clock,
    )
    paused = threading.Event()  # A is inside its backoff sleep
    proceed = threading.Event()  # main thread lets A finish
    worker: list[threading.Thread] = []

    def sleep(seconds: float) -> None:
        if worker and threading.current_thread() is worker[0] and not paused.is_set():
            paused.set()
            proceed.wait(timeout=5)
        clock.sleep(seconds)

    client = make_client(opener, clock, min_interval_s=0.0, max_concurrency=2, sleep=sleep)
    outcome: list[bytes | HttpError] = []

    def run_a() -> None:
        try:
            outcome.append(client.get(A_URL))
        except HttpError as exc:
            outcome.append(exc)

    worker.append(threading.Thread(target=run_a))
    worker[0].start()
    assert paused.wait(timeout=5)
    assert client.get(B_URL) == b"ok"  # started while A is backing off
    proceed.set()
    worker[0].join(timeout=5)

    assert outcome == [b"ok"]
    assert opener.start_of(A_URL) == 0.0
    assert opener.start_of(B_URL) == 30.0  # not 0: the shared limiter was pushed by A's 429


# -- body size limits (finding D) --------------------------------------------


def test_body_over_the_limit_is_a_hard_error() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [FakeResponse(b"x" * 101), FakeResponse(b"never")]})
    client = make_client(opener, clock, max_body_bytes=100)

    with pytest.raises(HttpError) as info:
        client.get(URL)
    assert info.value.status == 0
    assert not info.value.retryable
    assert info.value.body_too_large
    assert not info.value.budget_exhausted
    assert opener.calls == [URL]
    assert clock.sleeps == []


def test_body_at_the_limit_is_read_in_chunks() -> None:
    clock = FakeClock()
    body = b"y" * (READ_CHUNK_BYTES * 3 + 5)
    response = FakeResponse(body)
    client = make_client(FakeOpener({URL: [response]}), clock, max_body_bytes=len(body))

    assert client.get(URL) == body
    assert response.reads >= 4


def test_content_length_over_the_limit_fails_before_reading() -> None:
    clock = FakeClock()
    response = FakeResponse(b"x" * 10, headers={"Content-Length": "10000000"})
    client = make_client(FakeOpener({URL: [response]}), clock, max_body_bytes=100)

    with pytest.raises(HttpError) as info:
        client.get(URL)
    assert info.value.body_too_large
    assert response.reads == 0


def test_gzip_inflating_past_the_limit_is_rejected() -> None:
    clock = FakeClock()
    compressed = gzip.compress(b"z" * 100_000)
    assert len(compressed) < 1000
    opener = FakeOpener({URL: [FakeResponse(compressed, headers={"Content-Encoding": "gzip"}), FakeResponse(b"never")]})
    client = make_client(opener, clock, max_body_bytes=50_000)

    with pytest.raises(HttpError) as info:
        client.get(URL)
    assert info.value.body_too_large
    assert not info.value.retryable
    assert opener.calls == [URL]


def test_gzip_within_the_limit_still_decodes() -> None:
    clock = FakeClock()
    payload = b"<html>" + b"a" * 5000 + b"</html>"
    opener = FakeOpener({URL: [FakeResponse(gzip.compress(payload), headers={"Content-Encoding": "gzip"})]})
    client = make_client(opener, clock, max_body_bytes=len(payload))

    assert client.get(URL) == payload


def test_truncated_gzip_is_retried() -> None:
    clock = FakeClock()
    compressed = gzip.compress(b"q" * 50_000)
    opener = FakeOpener(
        {URL: [FakeResponse(compressed[: len(compressed) // 2], headers={"Content-Encoding": "gzip"}), FakeResponse(b"ok")]}
    )
    client = make_client(opener, clock)

    assert client.get(URL) == b"ok"
    assert opener.calls == [URL, URL]


def test_response_whose_read_takes_no_size_is_still_accepted() -> None:
    """Other test modules fake ``read()`` without a size argument; the limit still applies."""

    class LegacyResponse(FakeResponse):
        def read(self) -> bytes:  # type: ignore[override]
            self.reads += 1
            return self.body

    clock = FakeClock()
    ok, big = "https://example.test/ok", "https://example.test/big"
    opener = FakeOpener({ok: [LegacyResponse(b"legacy")], big: [LegacyResponse(b"x" * 101)]})
    client = make_client(opener, clock, max_body_bytes=100)

    assert client.get(ok) == b"legacy"
    with pytest.raises(HttpError) as info:
        client.get(big)
    assert info.value.body_too_large


# -- deadline (finding F) ----------------------------------------------------


def test_get_stops_retrying_once_the_deadline_would_pass() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [http_error(URL, 500)]})
    client = make_client(opener, clock, retries=3, min_interval_s=0.0)

    with pytest.raises(HttpError) as info:
        client.get(URL, deadline=5.0)
    # t=0 fail, backoff 1.5 ends at 1.5 (ok); t=1.5 fail, backoff 2.5 ends at 4.0 (ok);
    # t=4.0 fail, backoff 4.5 would end at 8.5 >= 5: stop with the last error.
    assert info.value.status == 500
    assert opener.calls == [URL] * 3
    assert clock.sleeps == [1.5, 2.5]


def test_get_without_a_deadline_retries_in_full() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [http_error(URL, 500)]})
    client = make_client(opener, clock, retries=3, min_interval_s=0.0)

    with pytest.raises(HttpError):
        client.get(URL)
    assert opener.calls == [URL] * 4


def test_get_many_passes_its_deadline_to_in_flight_retries() -> None:
    clock = FakeClock()
    opener = FakeOpener({URL: [http_error(URL, 500)]})
    client = make_client(opener, clock, retries=3, min_interval_s=0.0, max_concurrency=1)
    results: dict[str, bytes | HttpError] = {}

    client.get_many([URL], lambda url, payload: results.__setitem__(url, payload), time_budget_s=2.0)

    # t=0 fail, backoff 1.5 ends at 1.5 < 2 (retry); t=1.5 fail, backoff 2.5 would end at 4.0 >= 2: stop.
    assert opener.calls == [URL] * 2
    assert isinstance(results[URL], HttpError)
    assert results[URL].status == 500
    assert not results[URL].budget_exhausted


def test_first_attempt_is_abandoned_when_the_limiter_slot_is_past_the_deadline() -> None:
    clock = FakeClock()
    opener = FakeOpener({A_URL: [http_error(A_URL, 429, {"Retry-After": "100"})], B_URL: [FakeResponse(b"ok")]})
    client = make_client(opener, clock, retries=0, min_interval_s=0.0)

    with pytest.raises(HttpError):
        client.get(A_URL)  # 429 with no retries; the shared limiter now says "not before t=100"
    with pytest.raises(HttpError) as info:
        client.get(B_URL, deadline=50.0)
    assert info.value.budget_exhausted
    assert B_URL not in opener.calls
    assert clock.sleeps == []  # it did not sleep 100 s past the deadline


# -- defaults (findings E and F) ---------------------------------------------


def test_default_user_agent_comes_from_config_and_default_timeout_is_20s() -> None:
    clock = FakeClock()
    seen: dict[str, str] = {}

    class RecordingOpener(FakeOpener):
        def open(self, request: urllib.request.Request, timeout: float | None = None) -> FakeResponse:
            seen.update({k.lower(): v for k, v in request.header_items()})
            return super().open(request, timeout)

    opener = RecordingOpener({URL: [FakeResponse(b"ok")]})
    client = HttpClient(opener=opener, sleep=clock.sleep, clock=clock.now)

    assert client.get(URL) == b"ok"
    assert seen["user-agent"] == config.USER_AGENT
    assert "<owner>" not in seen["user-agent"]
    assert opener.timeouts == [20.0]
    assert not hasattr(scraper.http, "DEFAULT_USER_AGENT")
    assert not hasattr(scraper.http, "REPO_OWNER")


def test_get_many_holds_max_concurrency_requests_open_at_once() -> None:
    """Four workers must overlap when pages are slower than the start spacing.

    The 2026-09-23 request policy (scrape.yml: 0.5 s spacing, 4 in flight)
    rests on this: throughput is min(1/min_interval_s, max_concurrency/latency),
    so a pool that serialised requests would recreate the 2026-09-21 slowdown
    (docs/DATA_LOG.md) whatever --max-concurrency says. Every open waits at a
    barrier only four simultaneous opens can pass; a serialised pool times out
    there and the test fails with BrokenBarrierError.
    """
    urls = [f"https://example.test/{i}" for i in range(4)]
    barrier = threading.Barrier(4, timeout=5.0)

    def held_open() -> FakeResponse:
        barrier.wait()
        return FakeResponse(b"ok")

    clock = FakeClock()
    opener = FakeOpener({u: [held_open] for u in urls}, clock=clock)
    client = make_client(opener, clock, min_interval_s=0.5, max_concurrency=4)
    results: dict[str, bytes | HttpError] = {}
    lock = threading.Lock()

    def on_result(url: str, payload: bytes | HttpError) -> None:
        with lock:
            results[url] = payload

    client.get_many(urls, on_result)

    assert [results[u] for u in urls] == [b"ok"] * 4
    assert sorted(opener.calls) == urls
