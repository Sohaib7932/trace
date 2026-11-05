"""Run the same request-contention contract against the PostgreSQL profile."""

from tests.integration.test_custom_lesson_concurrency import (
    requests as requests,
)
from tests.integration.test_custom_lesson_concurrency import (
    test_creation_preserves_quota_and_idempotency as test_creation_preserves_quota_and_idempotency,
)
from tests.integration.test_custom_lesson_concurrency import (
    test_creation_waits_for_writer as test_creation_waits_for_writer,
)
