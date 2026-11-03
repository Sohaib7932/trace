"""Abandoned authentication cannot dispose resources beneath actual JWKS cleanup."""

import asyncio
from contextlib import suppress
from threading import Event
from unittest.mock import patch

import httpx2
import pytest

from app.auth.jwks_http import HttpJwksSource
from app.auth.jwt import JwtVerifier
from app.core.accounting_settings import AccountingSettings
from app.db.session import Database
from app.main import create_app
from tests.auth_fixtures import SigningFixture, auth_settings
from tests.unit.test_ai_resources import ClosingTransport
from tests.unit.test_ai_resources import settings as ai_settings


@pytest.mark.parametrize("blocked_stage", ["refresh_cleanup", "resolver"])
def test_shutdown_retains_owned_authentication_until_actual_io_cleanup(settings, blocked_stage):
    config = auth_settings(settings).model_copy(update={"request_timeout_seconds": 5})
    signer = SigningFixture()
    cleanup_entered, resolver_entered, resolver_release = Event(), Event(), Event()
    resolver_finished, deferred_wait, disposed = Event(), Event(), Event()
    cleanup_waiters = []
    disposal_observations = []

    class ControlledCleanup(httpx2.AsyncByteStream):
        async def __aiter__(self):
            try:
                await asyncio.Future()
                yield b"unreachable"
            finally:
                waiter = asyncio.get_running_loop().create_future()
                cleanup_waiters.append(waiter)
                cleanup_entered.set()
                await waiter

    def resolver_work():
        resolver_entered.set()
        try:
            assert resolver_release.wait(5)
        finally:
            resolver_finished.set()

    async def handle(request):
        if blocked_stage == "refresh_cleanup":
            return httpx2.Response(200, stream=ControlledCleanup())
        # The I/O deadline cancels this await, not the already-running OS job.
        await asyncio.get_running_loop().run_in_executor(None, resolver_work)
        return httpx2.Response(200, json={"keys": []})

    source = HttpJwksSource(
        config.supabase_jwks_url,
        http_transport=httpx2.MockTransport(handle),
        timeout_seconds=1,
    )
    verifier = JwtVerifier(config, source)
    resource = Database(config)
    transport = ClosingTransport()
    real_wait, real_dispose = source.wait_for_idle, resource.dispose

    def wait_for_idle(timeout=None):
        if timeout is None:
            deferred_wait.set()
        return real_wait(timeout)

    def dispose():
        disposal_observations.append(
            {
                "verifier_closed": verifier.closed,
                "source_closed": source.closed,
                "source_loop_closed": source._loop.is_closed(),
                "source_thread_stopped": not source._thread.is_alive(),
                "source_idle": real_wait(0),
                "transport_closes": transport.closed_count,
            }
        )
        real_dispose()
        disposed.set()

    def release_actual_work():
        resolver_release.set()
        for waiter in cleanup_waiters:
            if not waiter.done():
                with suppress(RuntimeError):
                    source._loop.call_soon_threadsafe(waiter.set_result, None)

    async def scenario():
        app = create_app(
            config,
            ai_settings=ai_settings(),
            ai_transport_factory=lambda: transport,
            accounting_settings=AccountingSettings(
                _env_file=None, mode="durable", scope="jwks-shutdown-fixture"
            ),
        )
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        request = None
        shutdown_complete = False
        try:
            assert app.state.jwt_verifier is verifier
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app), base_url="http://127.0.0.1"
            ) as client:
                request = asyncio.create_task(
                    client.get(
                        "/api/v1/account/me",
                        headers={"Authorization": "Bearer " + signer.token()},
                    )
                )
                if blocked_stage == "refresh_cleanup":
                    assert await asyncio.to_thread(cleanup_entered.wait, 5)
                    request.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await request
                    assert len(source._pending) == 1
                else:
                    assert await asyncio.to_thread(resolver_entered.wait, 5)
                    response = await asyncio.wait_for(request, 5)
                    assert response.status_code == 503
                    assert not source._pending and not resolver_finished.is_set()
                # The HTTP request has ended, but actual authentication I/O has not.
                assert not verifier.wait_for_idle(0)
                await lifespan.__aexit__(None, None, None)
                shutdown_complete = True
                assert await asyncio.to_thread(deferred_wait.wait, 5)
                assert not disposed.is_set() and transport.closed_count == 0
                assert not verifier.closed and not source.closed
                assert source._thread.is_alive() and not source._loop.is_closed()
                release_actual_work()
                assert await asyncio.to_thread(disposed.wait, 5)
                assert disposal_observations == [
                    {
                        "verifier_closed": True,
                        "source_closed": True,
                        "source_loop_closed": True,
                        "source_thread_stopped": True,
                        "source_idle": True,
                        "transport_closes": 1,
                    }
                ]
                if blocked_stage == "resolver":
                    assert resolver_finished.is_set()
        finally:
            release_actual_work()
            if request is not None and not request.done():
                request.cancel()
                with suppress(asyncio.CancelledError):
                    await request
            if not shutdown_complete:
                await lifespan.__aexit__(None, None, None)
            assert await asyncio.to_thread(disposed.wait, 5)

    with (
        patch("app.main.Database", return_value=resource),
        patch("app.main.JwtVerifier", return_value=verifier),
        patch("app.main._SHUTDOWN_GRACE_SECONDS", 0),
        patch.object(source, "wait_for_idle", side_effect=wait_for_idle),
        patch.object(resource, "dispose", side_effect=dispose),
    ):
        asyncio.run(scenario())
