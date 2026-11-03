"""One request/provider budget across multiple sequential internal AI operations."""

import pytest

from app.core.errors import ApplicationError
from app.services.feedback_operations import FeedbackOperations
from tests.unit.test_feedback_operations import principal, settings


def test_provider_budget_is_anchored_once_and_does_not_reset_after_first_operation():
    now = [0.0]
    operations = FeedbackOperations(settings(provider_timeout_seconds=3), clock=lambda: now[0])
    try:

        def work():
            now[0] = 2
            assert operations.remaining_seconds(provider=False) == 6
            assert operations.remaining_seconds() == 3
            now[0] = 4
            assert operations.remaining_seconds() == 1
            assert operations.remaining_seconds(provider=False) == 4
            now[0] = 5
            with pytest.raises(TimeoutError):
                operations.remaining_seconds()
            return "budget_checked"

        assert operations.run(principal(), work) == "budget_checked"
        with pytest.raises(ApplicationError) as error:
            operations.remaining_seconds()
        assert error.value.status_code == 503
    finally:
        operations.close()


def test_original_request_deadline_caps_provider_budget():
    now = [0.0]
    operations = FeedbackOperations(settings(provider_timeout_seconds=3), clock=lambda: now[0])
    try:

        def work():
            assert operations.remaining_seconds() == 2
            now[0] = 1
            assert operations.remaining_seconds() == 1

        operations.run(principal(), work, deadline=2)
    finally:
        operations.close()


def test_closed_operations_cannot_supply_more_provider_budget():
    operations = FeedbackOperations(settings())
    operations.close()
    with pytest.raises(ApplicationError) as error:
        operations.remaining_seconds()
    assert error.value.status_code == 503
