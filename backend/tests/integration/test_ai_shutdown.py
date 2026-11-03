"""Shutdown retains real operation leases before disposing owned resources."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest

from app.core.errors import ApplicationError
from app.db.session import Database
from app.main import create_app
from tests.unit.test_ai_resources import ClosingTransport
from tests.unit.test_ai_resources import settings as ai_settings
from tests.unit.test_feedback_operations import principal


@pytest.mark.parametrize(
    "operation_name",
    [
        "feedback_operations",
        "tutor_operations",
        "support_operations",
    ],
)
@pytest.mark.parametrize("grace", [0.0, 5.0])
def test_owned_database_survives_real_worker_until_finalization(settings, operation_name, grace):
    resource = Database(settings)
    transport = ClosingTransport()
    app = create_app(settings, ai_settings=ai_settings(), ai_transport_factory=lambda: transport)
    entered, release, quiesced, disposed = Event(), Event(), Event(), Event()
    real_dispose = resource.dispose

    def dispose():
        real_dispose()
        disposed.set()

    def operation():
        entered.set()
        assert release.wait(5)
        # Simulates fresh authorization/readback after a slow provider returned.
        assert not disposed.is_set()

    async def scenario(pool):
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        owner = getattr(app.state, operation_name)
        real_close = owner.close

        def close():
            real_close()
            quiesced.set()

        future = pool.submit(owner.run, principal(), operation)
        shutdown = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            with patch.object(owner, "close", side_effect=close):
                shutdown = asyncio.create_task(lifespan.__aexit__(None, None, None))
                assert await asyncio.to_thread(quiesced.wait, 5)
                assert not disposed.is_set() and transport.closed_count == 0
                assert app.state.ai_resources.client.closed
                if grace == 0:
                    await asyncio.wait_for(shutdown, 5)
                    assert not disposed.is_set()
                release.set()
                if grace:
                    await asyncio.wait_for(shutdown, 5)
            assert await asyncio.to_thread(disposed.wait, 5)
            with pytest.raises(ApplicationError) as error:
                future.result(timeout=5)
            assert error.value.status_code == 503
            assert transport.closed_count == 1
        finally:
            release.set()
            if shutdown is not None and not shutdown.done():
                await shutdown

    with (
        patch("app.main.Database", return_value=resource),
        patch.object(resource, "dispose", side_effect=dispose),
        patch("app.main._SHUTDOWN_GRACE_SECONDS", grace),
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        asyncio.run(scenario(pool))
