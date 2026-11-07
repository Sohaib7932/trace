"""Wires custom-lesson generation onto the EXISTING AI resources without changing them.

A separate BoundedAIClient (same settings class, same transport, same usage ledger) is used
only so lesson generation can have its own provider timeout and a lower per-process call
ceiling. The tutor and Trace Help keep their own client and limits untouched. The shared
transport is owned (and closed) by the main client, never by this one.
"""

import logging
import time
from dataclasses import dataclass
from typing import Literal

from app.ai.client import AITransport, BoundedAIClient
from app.ai.resources import AIResources
from app.core.ai_settings import AIClientSettings
from app.core.custom_lesson_settings import CustomLessonSettings
from app.db.custom_lessons import SqlCustomLessonRepository
from app.db.session import Database
from app.domain.clock import Clock
from app.schemas.ai_client import TransportCompletion, TransportRequest
from app.services.custom_lesson_generation import CustomLessonGenerator
from app.services.custom_lessons import CustomLessonRunner, CustomLessonService

LESSON_RESPONSE_BYTES = 32768


class SharedTransport:
    """Delegates calls to the main client's transport; deliberately has no close()."""

    def __init__(self, inner: AITransport) -> None:
        self._inner = inner
        self.source: Literal["test_fixture", "ai"] = inner.source

    def complete(self, request: TransportRequest) -> TransportCompletion:
        return self._inner.complete(request)


@dataclass
class CustomLessonRuntime:
    service: CustomLessonService
    runner: CustomLessonRunner
    client: BoundedAIClient

    def stop_admission(self) -> None:
        self.client.stop_admission()
        self.runner.stop_admission()

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        deadline = time.monotonic() + timeout if timeout is not None else None
        # A provider may be idle while its job is still committing a lesson or
        # failure. Keep the database and shared transport until the WHOLE job ends.
        if not self.runner.wait_for_idle(timeout):
            return False
        remaining = max(0, deadline - time.monotonic()) if deadline is not None else None
        return self.client.wait_for_idle(remaining)

    def close(self, timeout: float = 30.0) -> None:
        self.stop_admission()
        self.wait_for_idle(timeout)
        self.client.close()


def lesson_client_settings(
    base: AIClientSettings, settings: CustomLessonSettings
) -> AIClientSettings:
    timeout = settings.provider_timeout_seconds
    return AIClientSettings.model_validate(
        {
            **base.model_dump(warnings=False),
            "response_timeout_seconds": timeout,
            "total_timeout_seconds": min(60.0, max(base.total_timeout_seconds, timeout + 5)),
            "max_response_bytes": max(base.max_response_bytes, LESSON_RESPONSE_BYTES),
            "max_live_requests_per_process": min(
                base.max_live_requests_per_process, settings.max_live_calls_per_process
            ),
            "max_retries": 0,
        }
    )


def build_custom_lessons(
    database: Database,
    ai: AIResources,
    settings: CustomLessonSettings,
    clock: Clock,
    logger: logging.Logger,
) -> CustomLessonRuntime:
    transport = ai.client.transport
    available = settings.enabled and ai.settings.mode != "disabled" and transport is not None
    try:
        config = lesson_client_settings(ai.settings, settings)
    except Exception:
        config, available = AIClientSettings(_env_file=None), False  # disabled, never invented
    client = BoundedAIClient(
        config,
        SharedTransport(transport) if available and transport is not None else None,
        ledger=ai.client.ledger,
        allowance_policy=ai.client.allowance_policy,
    )
    generator = CustomLessonGenerator(client, timeout_seconds=settings.provider_timeout_seconds)
    repository = SqlCustomLessonRepository(database)
    service = CustomLessonService(repository, settings, clock, available=available)
    service.recover_interrupted()
    runner = CustomLessonRunner(repository, generator, clock, logger)
    return CustomLessonRuntime(service, runner, client)
