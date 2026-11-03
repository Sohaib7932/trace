"""Genuine teaching uses bounded network budgets without changing feedback policy."""

import pytest
from pydantic import ValidationError

from app.core.feedback_settings import FeedbackSettings
from app.core.settings import Settings
from app.core.support_settings import SupportSettings
from app.core.tutor_settings import TutorSettings
from app.main import create_app
from app.services.feedback_operations import FeedbackOperations


@pytest.mark.parametrize("schema", [TutorSettings, SupportSettings])
def test_teaching_deadline_fits_transport_and_request_and_preserves_concurrency(schema):
    settings = schema(_env_file=None)
    assert settings.provider_timeout_seconds == 20
    assert settings.request_timeout_seconds == 30
    operations = FeedbackOperations(settings)
    try:
        assert type(operations.settings) is schema
        assert operations.settings.max_global_in_flight == 2
        assert operations.settings.max_subject_in_flight == 1
    finally:
        operations.close()
    for changes in (
        {"provider_timeout_seconds": 20.01},
        {"request_timeout_seconds": 31},
        {"provider_timeout_seconds": 20, "request_timeout_seconds": 19},
    ):
        with pytest.raises(ValidationError):
            schema(_env_file=None, **changes)


def test_tighter_http_deadline_still_caps_all_teaching_and_feedback_unchanged():
    app = create_app(Settings(_env_file=None, request_timeout_seconds=0.5))
    assert app.state.tutor_settings.provider_timeout_seconds == 0.5
    assert app.state.support_settings.provider_timeout_seconds == 0.5
    assert FeedbackSettings(_env_file=None).provider_timeout_seconds == 2


def test_unvalidated_tutor_copy_cannot_disable_operation_bounds():
    forged = TutorSettings(_env_file=None).model_copy(update={"max_global_in_flight": 0})
    with pytest.raises(ValidationError):
        FeedbackOperations(forged)
