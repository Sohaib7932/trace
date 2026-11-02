"""Effective feedback budgets cannot exceed the surrounding HTTP limits."""

import pytest
from pydantic import ValidationError

from app.core.feedback_settings import FeedbackSettings
from app.core.settings import Settings
from app.main import create_app


def test_feedback_budgets_are_capped_by_existing_http_deadline_and_body_bound():
    app = create_app(
        Settings(_env_file=None, request_timeout_seconds=0.25, max_request_bytes=1024),
        feedback_settings=FeedbackSettings(_env_file=None),
    )
    effective = app.state.feedback_settings
    assert effective.request_timeout_seconds == 0.25
    assert effective.provider_timeout_seconds == 0.25
    assert effective.max_request_bytes == 1024


def test_tighter_feedback_budgets_remain_tighter_than_global_http_limits():
    limits = FeedbackSettings(
        _env_file=None,
        request_timeout_seconds=0.1,
        provider_timeout_seconds=0.05,
        max_request_bytes=512,
    )
    app = create_app(Settings(_env_file=None), feedback_settings=limits)
    assert app.state.feedback_settings == limits


def test_unvalidated_feedback_settings_cannot_disable_concurrency_bounds():
    forged = FeedbackSettings(_env_file=None).model_copy(update={"max_global_in_flight": 0})
    with pytest.raises(ValidationError):
        create_app(Settings(_env_file=None), feedback_settings=forged)
