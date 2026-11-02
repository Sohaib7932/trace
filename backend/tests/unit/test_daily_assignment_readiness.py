"""Local-day math is explicit; production assignment execution remains blocked."""

from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.blueprints.candidates import tasks_blueprint_candidate
from app.domain.daily_assignments import (
    MAX_NEW_ASSIGNMENTS_PER_LOCAL_DAY,
    LocalDayWindow,
    local_day_window,
)
from app.schemas.daily_assignments import (
    REQUIREMENTS,
    ApprovedAssignmentSemantics,
    AtomicAssignmentReceipt,
    AtomicAssignmentRequest,
    DailyAssignmentBlocked,
    NewAssignmentRequest,
)
from app.services.daily_assignments import DailyAssignmentService

AT = datetime(2026, 11, 1, 18, 30, tzinfo=UTC)


def request(**changes):
    values = dict(
        learner_id=str(uuid4()),
        candidate=tasks_blueprint_candidate().trusted_blueprint().reference(),
        idempotency_key=str(uuid4()),
        requested_at=AT,
    )
    values.update(changes)
    return NewAssignmentRequest.model_validate(values)


def test_current_service_is_strictly_blocked_with_no_availability_or_assignment_claim():
    service = DailyAssignmentService()
    result = service.request_new(request())
    assert result == service.readiness()
    assert MAX_NEW_ASSIGNMENTS_PER_LOCAL_DAY == result.maximum_new_assignments == 3
    assert result.requirements == REQUIREMENTS and result.status == "blocked"
    assert result.assignment_created is result.quota_enforced is False
    assert result.assignment_id is None and not hasattr(result, "remaining_slots")


def test_supplied_unapproved_ports_are_not_invoked_and_no_record_is_created():
    class Trap:
        calls = 0

        def resolve(self, *args):
            self.calls += 1
            raise AssertionError("Unapproved policy must not run")

        def try_assign(self, *args):
            self.calls += 1
            raise AssertionError("Assignment persistence is not implemented")

    trap = Trap()
    service = DailyAssignmentService(trap, trap, trap)
    assert service.request_new(request()).status == "blocked"
    assert trap.calls == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "assigned"},
        {"assignment_created": True},
        {"quota_enforced": True},
        {"assignment_id": str(uuid4())},
        {"remaining_slots": 3},
        {"maximum_new_assignments": 4},
        {"maximum_new_assignments": 3.0},
        {"requirements": []},
    ],
)
def test_blocked_receipt_cannot_invent_availability_or_claim_execution(changes):
    values = DailyAssignmentBlocked().model_dump()
    values.update(changes)
    with pytest.raises(ValidationError):
        DailyAssignmentBlocked.model_validate(values)


@pytest.mark.parametrize(
    "activity", ["hint", "explanation", "retry", "review", "retrieval", "session_create"]
)
def test_nonassignment_activities_cannot_enter_the_new_assignment_contract(activity):
    with pytest.raises(ValidationError):
        request(classification=activity)


def test_request_rejects_unknown_authority_flags_and_naive_time():
    with pytest.raises(ValidationError):
        request(requested_at=AT.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        request(release_eligible=True)
    with pytest.raises(ValidationError):
        request(learner_id="unknown")


def test_request_timestamp_normalizes_an_explicit_offset_to_utc():
    other = AT.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert request(requested_at=other).requested_at == AT
    assert request(requested_at=other).requested_at.tzinfo == UTC


@pytest.mark.parametrize(
    "offset,at,expected_day,start",
    [
        (
            timedelta(0),
            datetime(2026, 11, 2, tzinfo=UTC),
            date(2026, 11, 2),
            datetime(2026, 11, 2, tzinfo=UTC),
        ),
        (timedelta(hours=5, minutes=30), AT, date(2026, 11, 2), AT),
        (
            timedelta(hours=5, minutes=30),
            AT - timedelta(microseconds=1),
            date(2026, 11, 1),
            AT - timedelta(days=1),
        ),
        (
            timedelta(hours=-5),
            datetime(2026, 11, 2, 5, tzinfo=UTC),
            date(2026, 11, 2),
            datetime(2026, 11, 2, 5, tzinfo=UTC),
        ),
        (
            timedelta(hours=14),
            datetime(2026, 12, 31, 10, tzinfo=UTC),
            date(2027, 1, 1),
            datetime(2026, 12, 31, 10, tzinfo=UTC),
        ),
        (
            timedelta(hours=-12),
            datetime(2026, 11, 2, 11, 59, tzinfo=UTC),
            date(2026, 11, 1),
            datetime(2026, 11, 1, 12, tzinfo=UTC),
        ),
    ],
)
def test_explicit_timezone_windows_respect_midnight_and_utc_boundaries(
    offset, at, expected_day, start
):
    result = local_day_window(at, timezone(offset))
    assert result.local_date == expected_day and result.utc_start == start
    assert result.utc_end == start + timedelta(days=1)
    assert result.utc_start <= at < result.utc_end
    assert result.utc_start.tzinfo == result.utc_end.tzinfo == UTC


def test_same_instant_can_belong_to_different_learner_local_days():
    assert local_day_window(AT, timezone(timedelta(hours=5, minutes=30))).local_date == date(
        2026, 11, 2
    )
    assert local_day_window(AT, timezone(timedelta(hours=-5))).local_date == date(2026, 11, 1)


def test_leap_day_and_host_timezone_environment_do_not_supply_policy(monkeypatch):
    instant = datetime(2024, 2, 29, 12, tzinfo=UTC)
    expected = local_day_window(instant, UTC)
    for label in ["UTC", "Pacific/Honolulu", "Asia/Kolkata"]:
        monkeypatch.setenv("TZ", label)
        assert local_day_window(instant, UTC) == expected
    assert expected.local_date == date(2024, 2, 29)


@pytest.mark.parametrize(
    "at,zone",
    [
        (AT.replace(tzinfo=None), UTC),
        (AT, None),
        (AT, "UTC"),
        (None, UTC),
    ],
)
def test_missing_or_naive_inputs_never_fall_back_to_the_server_timezone(at, zone):
    with pytest.raises(ValueError):
        local_day_window(at, zone)


def test_timezone_is_required_and_ambiguous_midnight_is_not_silently_resolved():
    with pytest.raises(TypeError):
        local_day_window(AT)

    class AmbiguousMidnight(tzinfo):
        def utcoffset(self, value):
            return (
                timedelta(hours=value.fold)
                if value is not None and value.hour == 0
                else timedelta(0)
            )

        def dst(self, value):
            return timedelta(0)

    with pytest.raises(ValueError, match="unambiguous"):
        local_day_window(AT, AmbiguousMidnight())


@pytest.mark.parametrize(
    "start,end",
    [
        (AT, AT),
        (AT, AT - timedelta(seconds=1)),
        (AT.replace(tzinfo=None), AT + timedelta(days=1)),
        (AT.astimezone(timezone(timedelta(hours=1))), AT + timedelta(days=1)),
    ],
)
def test_windows_require_positive_explicit_utc_boundaries(start, end):
    with pytest.raises(ValueError):
        LocalDayWindow(date(2026, 11, 2), start, end)


@pytest.mark.parametrize("status,consumes", [("assigned", True), ("existing", False)])
def test_future_atomic_receipts_distinguish_new_assignment_from_exact_retry(status, consumes):
    window = local_day_window(AT, timezone(timedelta(hours=5, minutes=30)))
    receipt = AtomicAssignmentReceipt(
        status=status,
        assignment_id=str(uuid4()),
        assigned_at=AT,
        local_day=window,
        quota_consumed=consumes,
    )
    assert receipt.quota_consumed is consumes
    assert not hasattr(receipt, "remaining_slots")


@pytest.mark.parametrize("status", ["quota_exhausted", "ineligible", "conflict"])
def test_future_negative_receipts_do_not_invent_assignment_identity(status):
    receipt = AtomicAssignmentReceipt(
        status=status,
        assignment_id=None,
        assigned_at=None,
        local_day=None,
        quota_consumed=False,
    )
    with pytest.raises(ValidationError):
        AtomicAssignmentReceipt.model_validate(
            {**receipt.model_dump(), "assignment_id": str(uuid4())}
        )


def test_future_receipt_rejects_wrong_quota_or_timestamp_outside_local_day():
    window = local_day_window(AT, timezone(timedelta(hours=5, minutes=30)))
    values = dict(
        status="assigned",
        assignment_id=str(uuid4()),
        assigned_at=AT,
        local_day=window,
        quota_consumed=True,
    )
    with pytest.raises(ValidationError):
        AtomicAssignmentReceipt.model_validate({**values, "quota_consumed": False})
    with pytest.raises(ValidationError):
        AtomicAssignmentReceipt.model_validate({**values, "assigned_at": window.utc_end})


def test_forged_request_is_refreshed_before_readiness_response():
    malformed = request().model_copy(update={"classification": "hint"})
    with pytest.raises(ValidationError):
        DailyAssignmentService().request_new(malformed)


def test_future_atomic_request_requires_explicit_policy_and_matching_captured_day():
    values = dict(
        request=request(),
        local_day=local_day_window(AT, timezone(timedelta(hours=5, minutes=30))),
        timezone_key="fixture-explicit-offset",
        timezone_authority_revision="fixture-revision",
        semantics=ApprovedAssignmentSemantics(
            policy_id="fixture-policy", revision="fixture-v1", approved=True
        ),
    )
    prepared = AtomicAssignmentRequest.model_validate(values)
    assert prepared.maximum_new_assignments == 3
    with pytest.raises(ValidationError):
        AtomicAssignmentRequest.model_validate({**values, "maximum_new_assignments": 4})
    with pytest.raises(ValidationError):
        AtomicAssignmentRequest.model_validate(
            {
                **values,
                "local_day": local_day_window(AT + timedelta(days=1), UTC),
            }
        )


def test_future_policy_reference_cannot_claim_unapproved_semantics_are_approved():
    with pytest.raises(ValidationError):
        ApprovedAssignmentSemantics(
            policy_id="fixture-policy", revision="fixture-v1", approved=False
        )


def test_calendar_identity_cannot_be_replaced_by_an_instant():
    with pytest.raises(ValueError, match="calendar date"):
        LocalDayWindow(AT, AT, AT + timedelta(days=1))


def test_blocked_receipt_cannot_hide_release_requirement_by_repeating_another_requirement():
    requirements = list(REQUIREMENTS)
    requirements[-1] = requirements[0]
    with pytest.raises(ValidationError, match="declared requirements"):
        DailyAssignmentBlocked(requirements=tuple(requirements))


@pytest.mark.parametrize(
    "status,identity,time,consumed",
    [
        ("assigned", None, AT, True),
        ("existing", "present", None, False),
        ("quota_exhausted", "present", AT, False),
    ],
)
def test_future_receipt_cannot_claim_assignment_without_consistent_record_metadata(
    status, identity, time, consumed
):
    with pytest.raises(ValidationError, match="actual assignment receipt"):
        AtomicAssignmentReceipt(
            status=status,
            assignment_id=str(uuid4()) if identity else None,
            assigned_at=time,
            local_day=local_day_window(AT, UTC),
            quota_consumed=consumed,
        )


def test_nonexistent_midnight_requires_explicit_resolution_instead_of_normalization():
    class SkippedMidnight(tzinfo):
        def utcoffset(self, value):
            return timedelta(0)

        def dst(self, value):
            return timedelta(0)

        def fromutc(self, value):
            return value + timedelta(hours=1) if value.hour == 0 else value

    with pytest.raises(ValueError, match="unambiguous resolved timezone"):
        local_day_window(AT, SkippedMidnight())


def test_inconsistent_resolver_calendar_cannot_choose_a_day_excluding_the_actual_instant():
    class InconsistentCalendar(tzinfo):
        def utcoffset(self, value):
            return timedelta(0)

        def dst(self, value):
            return timedelta(0)

        def fromutc(self, value):
            return value + timedelta(days=1) if value.hour == 18 else value

    with pytest.raises(ValueError, match="unambiguous resolved timezone"):
        local_day_window(AT, InconsistentCalendar())
