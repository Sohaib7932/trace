"""Application resource ownership uses explicit offline factories only."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest

from app.ai.client import AITransportError, BoundedAIClient
from app.ai.providers.mock_transport import MockAITransport
from app.ai.resources import AIResourceError, AIResources
from app.core.ai_settings import AIClientSettings
from app.schemas.ai_client import TransportCompletion
from app.schemas.support import SupportQuestion


def settings(mode="mock", **changes):
    return AIClientSettings(_env_file=None, mode=mode, **changes)


def request(client, capability="generation"):
    return client.complete(capability=capability, instructions="Fixture policy", data={})


class ClosingTransport(MockAITransport):
    def __init__(self, *, fail_close=False):
        super().__init__(
            [TransportCompletion(text='{"text":"Fixture guidance"}', cost_microusd=0)] * 3
        )
        self.closed_count = 0
        self.fail_close = fail_close

    def close(self):
        self.closed_count += 1
        if self.fail_close:
            raise RuntimeError("private-credential-cleanup-sentinel")


def test_disabled_never_invokes_a_factory_or_synthesizes_fake_output():
    def forbidden():
        raise AssertionError("Disabled resources must not construct a transport")

    resources = AIResources.create(settings("disabled"), forbidden)
    result = request(resources.client)
    assert (
        result.status == "unavailable" and result.error_code == "disabled" and result.text is None
    )
    assert not resources.client.usage_snapshot()
    resources.close()
    assert resources.client.closed


def test_explicit_mock_requires_an_explicit_transport_factory():
    with pytest.raises(AIResourceError, match="^AI resources are unavailable\\.$"):
        AIResources.create(settings())


def test_all_internal_capabilities_share_one_client_and_separate_usage():
    transport = ClosingTransport()
    resources = AIResources.create(settings(), lambda: transport)
    assert resources.question_generator.client is resources.client
    assert resources.tutor_provider.client is resources.client
    assert resources.lesson_assistant.assistant.client is resources.client
    assert resources.support.assistant.client is resources.client
    assert request(resources.client).status == "success"
    assert request(resources.client, "tutor").status == "success"
    assert {record.capability for record in resources.client.usage_snapshot()} == {
        "generation",
        "tutor",
    }
    assert (
        resources.support.answer(SupportQuestion(question="How do I sign in?")).status
        == "unavailable"
    )
    assert len(transport.calls) == 2
    resources.close()
    resources.close()
    assert transport.closed_count == 1


def test_clients_are_separate_between_resources_and_counters_do_not_leak():
    first = AIResources.create(settings(), ClosingTransport)
    second = AIResources.create(settings(), ClosingTransport)
    assert first.client is not second.client
    request(first.client)
    assert len(first.client.usage_snapshot()) == 1
    assert second.client.usage_snapshot() == ()
    first.close()
    assert not second.client.closed
    second.close()


def test_close_does_not_require_a_new_transport_protocol_method():
    transport = MockAITransport([TransportCompletion(text="fixture", cost_microusd=0)])
    client = BoundedAIClient(settings(), transport)
    client.close()
    client.close()
    result = request(client)
    assert result.error_code == "disabled" and result.text is None and not transport.calls


def test_cleanup_failure_is_sanitized_and_attempted_only_once(capsys, caplog):
    transport = ClosingTransport(fail_close=True)
    resources = AIResources.create(settings(), lambda: transport)
    with pytest.raises(AIResourceError) as exc:
        resources.close()
    assert "private-credential" not in str(exc.value)
    assert resources.client.closed and request(resources.client).error_code == "disabled"
    resources.close()
    assert transport.closed_count == 1
    assert "private-credential" not in caplog.text + capsys.readouterr().err


def test_raw_factory_error_is_not_exposed(capsys, caplog):
    def broken():
        raise RuntimeError("private-credential-startup-sentinel")

    with pytest.raises(AIResourceError) as exc:
        AIResources.create(settings(), broken)
    assert str(exc.value) == "AI resources are unavailable."
    assert "private-credential" not in caplog.text + capsys.readouterr().err


def test_startup_failure_after_transport_allocation_closes_it_once():
    transport = ClosingTransport()
    with (
        patch("app.ai.resources.BoundedTutorProvider", side_effect=RuntimeError("private-startup")),
        pytest.raises(AIResourceError),
    ):
        AIResources.create(settings(), lambda: transport)
    assert transport.closed_count == 1 and not transport.calls


def test_invalid_factory_output_is_closed_without_activation():
    class Wrong:
        source = "ai"
        closed_count = 0

        def close(self):
            self.closed_count += 1

    transport = Wrong()
    with pytest.raises(AIResourceError):
        AIResources.create(settings(), lambda: transport)
    assert transport.closed_count == 1


def test_invalid_allocated_transport_cleanup_failure_preserves_safe_startup_error(capsys, caplog):
    class Wrong:
        source = "ai"
        closed_count = 0

        def close(self):
            self.closed_count += 1
            raise RuntimeError("private-startup-cleanup-credential-sentinel")

    transport = Wrong()
    with (
        patch("app.ai.resources.BoundedAIClient") as client_constructor,
        pytest.raises(AIResourceError) as exc,
    ):
        AIResources.create(settings(), lambda: transport)
    assert str(exc.value) == "AI resources are unavailable."
    assert transport.closed_count == 1
    client_constructor.assert_not_called()
    captured = capsys.readouterr()
    assert "private-startup-cleanup-credential-sentinel" not in (
        str(exc.value) + captured.out + captured.err + caplog.text
    )


def test_invalid_factory_output_without_cleanup_never_constructs_a_client():
    class WrongWithoutCleanup:
        source = "test_fixture"
        complete = None

    with (
        patch("app.ai.resources.BoundedAIClient") as client_constructor,
        pytest.raises(AIResourceError, match="^AI resources are unavailable\\.$"),
    ):
        AIResources.create(settings(), WrongWithoutCleanup)
    client_constructor.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "live"},
        {"max_retries": 100},
        {"credential_env_var": "private-invalid-secret"},
    ],
)
def test_forged_configuration_is_freshly_checked_before_factory_calls(changes):
    calls = []
    forged = settings().model_copy(update=changes)
    with pytest.raises(AIResourceError) as exc:
        AIResources.create(forged, lambda: calls.append(True))
    assert str(exc.value) == "AI resources are unavailable." and not calls


def test_shutdown_during_inflight_work_discards_output_and_prevents_retry():
    entered, release = Event(), Event()

    class Blocking(ClosingTransport):
        def complete(self, transport_request):
            self.calls.append(transport_request)
            entered.set()
            assert release.wait(5)
            return TransportCompletion(text="private-late-output-sentinel", cost_microusd=0)

    transport = Blocking()
    resources = AIResources.create(settings(max_retries=2), lambda: transport)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(request, resources.client)
        try:
            assert entered.wait(5)
            resources.close()
        finally:
            release.set()
        result = future.result(timeout=5)
    assert result.error_code == "disabled" and result.text is None
    assert len(transport.calls) == transport.closed_count == 1
    assert request(resources.client).error_code == "disabled"
    assert len(transport.calls) == 1


def test_shutdown_after_reservation_prevents_the_next_transport_call():
    now = [0.0]
    transport = ClosingTransport()
    client = BoundedAIClient(settings(), transport)
    ticks = [0]

    def clock():
        ticks[0] += 1
        if ticks[0] == 2:
            client.close()
        return now[0]

    client.clock = clock
    assert request(client).error_code == "disabled"
    assert not transport.calls and transport.closed_count == 1


def test_transient_failure_cannot_retry_after_shutdown():
    class ClosingFailure(ClosingTransport):
        client = None

        def complete(self, transport_request):
            self.calls.append(transport_request)
            self.client.close()
            raise AITransportError("transient_error")

    transport = ClosingFailure()
    resources = AIResources.create(settings(max_retries=2), lambda: transport)
    transport.client = resources.client
    assert request(resources.client).error_code == "disabled"
    assert len(transport.calls) == transport.closed_count == 1
