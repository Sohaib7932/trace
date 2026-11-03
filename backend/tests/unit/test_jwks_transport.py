"""Absolute JWKS I/O deadline, cleanup and cache behavior with fake HTTP only."""

import asyncio
import gzip
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx2
import pytest

from app.auth.jwks_http import HttpJwksSource, _SingleResolver
from app.auth.jwt import JwtVerifier
from app.domain.learning import LearningError
from tests.auth_fixtures import AuthClock, SigningFixture, auth_settings


def test_dripping_jwks_body_is_cancelled_and_shared_client_reused():
    closed = Event()
    calls = []

    class Drip(httpx2.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.005)
                yield b" "

        async def aclose(self):
            closed.set()

    async def handle(request):
        calls.append(request)
        return (
            httpx2.Response(200, stream=Drip())
            if len(calls) == 1
            else httpx2.Response(200, json={"keys": []})
        )

    source = HttpJwksSource(
        "https://auth.example.test/keys",
        http_transport=httpx2.MockTransport(handle),
        timeout_seconds=0.08,
    )
    assert source._loop is None and source._client is None
    try:
        began = time.monotonic()
        with pytest.raises(ValueError, match="refresh is unavailable"):
            source.fetch()
        assert closed.is_set() and time.monotonic() - began < 2
        thread, client = source._thread, source._client
        assert source.fetch() == {"keys": []}
        assert source._thread is thread and source._client is client and len(calls) == 2
    finally:
        source.close()
        source.close()
    assert not thread.is_alive() and source._loop.is_closed()


def test_timeout_retains_verifier_lock_until_real_stream_cleanup(settings):
    clock = AuthClock()
    signer = SigningFixture(clock=clock)
    cleaning, release = Event(), Event()
    calls = []

    class Waiting(httpx2.AsyncByteStream):
        async def __aiter__(self):
            try:
                await asyncio.Future()
                yield b"unreachable"
            finally:
                cleaning.set()
                assert await asyncio.to_thread(release.wait, 5)

    async def handle(request):
        calls.append(request)
        return httpx2.Response(200, stream=Waiting())

    source = HttpJwksSource(
        "https://auth.example.test/keys",
        http_transport=httpx2.MockTransport(handle),
        timeout_seconds=0.08,
    )
    verifier = JwtVerifier(auth_settings(settings), source, clock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        verification = pool.submit(verifier.verify, signer.token())
        try:
            assert cleaning.wait(5)
            closing = pool.submit(verifier.close)
            assert not closing.done() and not verification.done()
            assert len(source._pending) == 1 and len(calls) == 1
        finally:
            release.set()
        with pytest.raises(LearningError) as error:
            verification.result(timeout=5)
        assert error.value.code == "dependency_unavailable"
        closing.result(timeout=5)
    assert verifier.closed and not source._thread.is_alive()


def test_timed_out_refresh_never_releases_an_expired_cached_key(settings):
    clock = AuthClock()
    signer = SigningFixture(clock=clock)
    calls = []
    closed = Event()

    class Drip(httpx2.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.005)
                yield b" "

        async def aclose(self):
            closed.set()

    async def handle(request):
        calls.append(request)
        return (
            httpx2.Response(200, json={"keys": [signer.jwk]})
            if len(calls) == 1
            else httpx2.Response(200, stream=Drip())
        )

    source = HttpJwksSource(
        "https://auth.example.test/keys",
        http_transport=httpx2.MockTransport(handle),
        timeout_seconds=0.08,
    )
    verifier = JwtVerifier(
        auth_settings(settings).model_copy(update={"auth_jwks_cache_seconds": 1}), source, clock
    )
    try:
        assert verifier.verify(signer.token()).subject == signer.subject
        clock.advance(6)
        for _ in range(2):
            with pytest.raises(LearningError) as error:
                verifier.verify(signer.token())
            assert error.value.code == "dependency_unavailable"
        assert len(calls) == 2 and closed.is_set()
    finally:
        verifier.close()


@pytest.mark.parametrize("status", [302, 401, 500])
def test_redirects_and_auth_provider_errors_are_not_followed_or_exposed(status, capsys, caplog):
    calls = []

    async def handle(request):
        calls.append(request)
        return httpx2.Response(
            status,
            headers={"location": "https://attacker.invalid/private"},
            json={"error": "private-key-diagnostic-canary"},
        )

    source = HttpJwksSource(
        "https://auth.example.test/keys", http_transport=httpx2.MockTransport(handle)
    )
    try:
        with pytest.raises(ValueError) as error:
            source.fetch()
        assert len(calls) == 1
        assert "private-key" not in str(error.value) + capsys.readouterr().err + caplog.text
    finally:
        source.close()


def test_compressed_jwks_cannot_bypass_decoded_byte_budget():
    source = HttpJwksSource(
        "https://auth.example.test/keys",
        http_transport=httpx2.MockTransport(
            lambda _: httpx2.Response(
                200, headers={"content-encoding": "gzip"}, content=gzip.compress(b" " * 100000)
            )
        ),
    )
    try:
        with pytest.raises(ValueError):
            source.fetch()
    finally:
        source.close()


def test_resolver_permit_is_retained_until_actual_os_job_finishes():
    entered, release = Event(), Event()
    resolver = _SingleResolver()

    def blocked():
        entered.set()
        assert release.wait(5)

    try:
        future = resolver.submit(blocked)
        assert entered.wait(5) and not future.cancel()
        with pytest.raises(RuntimeError, match="resolver is busy"):
            resolver.submit(lambda: None)
        release.set()
        future.result(timeout=5)
        assert resolver.submit(lambda: 1).result(timeout=5) == 1
    finally:
        release.set()
        resolver.shutdown(wait=True)


def test_unused_source_is_lazy_and_closed_source_never_constructs_http(monkeypatch):
    source = HttpJwksSource("https://auth.example.test/keys")
    source.close()
    monkeypatch.setattr(
        httpx2, "AsyncClient", lambda **_: pytest.fail("Closed source allocated HTTP")
    )
    with pytest.raises(ValueError):
        source.fetch()
    assert source._thread is None


def test_source_disposal_retains_actual_resolver_job_ownership():
    source = HttpJwksSource(
        "https://auth.example.test/keys",
        http_transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={"keys": []})),
    )
    assert source.fetch() == {"keys": []}
    entered, release = Event(), Event()

    def blocked_resolver():
        entered.set()
        assert release.wait(5)

    job = source._resolver.submit(blocked_resolver)
    assert entered.wait(5)
    assert not source.wait_for_idle(0.01)
    with ThreadPoolExecutor(max_workers=1) as pool:
        close = pool.submit(source.close)
        try:
            assert not close.done() and not job.done()
            assert source.closed
        finally:
            release.set()
        close.result(timeout=5)
    assert job.done() and source._loop.is_closed() and not source._thread.is_alive()
    assert source.wait_for_idle(0.01)


def test_http_constructor_failure_closes_allocated_loop_and_sanitizes(monkeypatch):
    source = HttpJwksSource("https://auth.example.test/keys")

    def broken(**_):
        raise RuntimeError("private-constructor-diagnostic")

    monkeypatch.setattr(httpx2, "AsyncClient", broken)
    with pytest.raises(ValueError) as error:
        source.fetch()
    assert "private" not in str(error.value)
    assert source.closed and source._loop.is_closed()
