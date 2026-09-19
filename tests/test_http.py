"""Offline tests for scraper.http (fake opener, fake clock, no sleeping)."""
from __future__ import annotations

import email.message
import gzip
import threading
import urllib.error
import urllib.request

import pytest

from scraper.http import HttpClient, HttpError


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
    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


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
        self._lock = threading.Lock()

    def open(self, request: urllib.request.Request, timeout: float | None = None) -> FakeResponse:
        url = request.full_url
        with self._lock:
            self.calls.append(url)
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
