from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.ai.lesson_assistant import LessonAssistant
from app.ai.providers.fake_lesson_assistant import FakeLessonAssistant
from app.schemas.lesson_assistant import (
    LessonAssistantReply,
    LessonAssistantRequest,
    VisibleEvidence,
)
from app.services.catalog import PUBLIC_CONTENT, TRANSFER_CONTENT
from app.services.lesson_assistant import (
    LessonAssistantService,
    build_lesson_assistant_request,
)


def assistant_request(lesson_id="fastapi-payload-mismatch", **changes):
    content = PUBLIC_CONTENT if lesson_id == "fastapi-payload-mismatch" else TRANSFER_CONTENT
    data = {
        "lesson_id": lesson_id,
        "stage": "investigate",
        "public_content": content,
        "question": "Why can FastAPI reject a request before storing it?",
        "visible_attempt": "The form sent a field at the top level.",
        "evidence": (VisibleEvidence(category="http_status", feedback="HTTP 422"),),
        "previous_hints": ("Trace the outgoing request.",),
    }
    data.update(changes)
    return build_lesson_assistant_request(**data)


@pytest.mark.parametrize(
    "lesson_id", ["fastapi-payload-mismatch", "fastapi-nested-payload-transfer"]
)
def test_public_context_uses_actual_catalog_projection_without_private_siblings(lesson_id):
    request = assistant_request(lesson_id)
    assert request.context.lesson_id == lesson_id
    assert request.context.lesson.model_dump() == (
        PUBLIC_CONTENT if lesson_id == "fastapi-payload-mismatch" else TRANSFER_CONTENT
    )
    encoded = request.model_dump_json()
    for private_key in ("expected_field", "prediction_answer", "private", "verification_inputs"):
        assert private_key not in encoded
    assert "Trace verification note" not in encoded
    assert "Prepare the product demo" not in encoded


@pytest.mark.parametrize("level", [1, 2, 3])
def test_explicit_fake_is_deterministic_and_interpretation_only(level):
    provider: LessonAssistant = FakeLessonAssistant()
    request = assistant_request(hint_level=level)
    first = provider.answer(request)
    assert first == provider.answer(request)
    assert first.status == "answered" and first.source == "test_fixture"
    assert first.interpretation_only and not first.can_complete_lesson


def test_fake_hints_progress_without_returning_a_corrected_payload():
    provider = FakeLessonAssistant()
    hints = [provider.answer(assistant_request(hint_level=level)).text for level in (1, 2, 3)]
    assert len(set(hints)) == 3
    assert all("payload =" not in hint and "content" not in hint for hint in hints)


@pytest.mark.parametrize(
    "changes",
    [
        {"lesson_id": "unapproved-lesson"},
        {"stage": "complete"},
        {"question": ""},
        {"question": "q" * 2401},
        {"question": "bad\x00input"},
        {"question": "\ud800"},
        {"hint_level": 0},
        {"hint_level": 4},
        {"hint_level": True},
        {"visible_attempt": "a" * 2401},
        {"previous_hints": ("x",) * 4},
        {"previous_hints": ("x" * 601,)},
        {
            "evidence": (
                VisibleEvidence(category="http_status", feedback="HTTP 422"),
                VisibleEvidence(category="http_status", feedback="HTTP 201"),
            )
        },
    ],
)
def test_context_rejects_unsupported_and_unbounded_input(changes):
    with pytest.raises(ValidationError):
        assistant_request(**changes)


@pytest.mark.parametrize("private_key", ["private", "answer_key", "expected_field", "token"])
def test_context_builder_rejects_extra_fields_in_public_projection(private_key):
    content = {**PUBLIC_CONTENT, private_key: "sensitive sentinel"}
    with pytest.raises(ValidationError) as error:
        assistant_request(public_content=content)
    assert "sensitive sentinel" not in str(error.value)


def test_service_copies_public_values_and_does_not_mutate_caller_data():
    content = dict(PUBLIC_CONTENT)
    request = assistant_request(public_content=content)
    before = deepcopy(request.model_dump())
    content["scenario"] = "changed externally"
    reply = LessonAssistantService(FakeLessonAssistant()).answer(request)
    assert reply.status == "answered"
    assert request.model_dump() == before
    with pytest.raises(ValidationError):
        request.context.lesson.scenario = "mutated"


@pytest.mark.parametrize("field", ["private", "account_id", "completion", "evaluator"])
def test_request_has_no_state_or_private_configuration_capability(field):
    data = assistant_request().model_dump(mode="json")
    data[field] = "secret sentinel"
    with pytest.raises(ValidationError):
        LessonAssistantRequest.model_validate(data)


def test_overall_utf8_budget_is_checked_independently_of_character_limits():
    content = {
        "title": "課" * 120,
        "objective": "課" * 1000,
        "scenario": "課" * 2400,
        "outgoing_code": "課" * 2400,
        "schema_code": "課" * 2400,
    }
    with pytest.raises(ValidationError):
        assistant_request(public_content=content)


def test_provider_failure_is_unavailable_without_fabricated_guidance_or_diagnostics():
    class FailingAssistant:
        def answer(self, request):
            raise RuntimeError("secret credential sentinel")

    result = LessonAssistantService(FailingAssistant()).answer(assistant_request())
    assert result.status == "unavailable" and result.source == "none"
    assert "secret credential sentinel" not in result.model_dump_json()


def test_malformed_provider_result_is_not_returned_as_an_answer():
    class InvalidAssistant:
        def answer(self, request):
            return LessonAssistantReply.model_construct(
                status="answered", text="secret sentinel", source="none"
            )

    assert (
        LessonAssistantService(InvalidAssistant()).answer(assistant_request()).status
        == "unavailable"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"can_complete_lesson": True},
        {"interpretation_only": False},
        {"status": "passed"},
        {"status": "unavailable", "source": "ai"},
        {"source": "none"},
        {"answer_key": "content"},
    ],
)
def test_reply_cannot_establish_correctness_or_misrepresent_an_error(changes):
    data = {
        "status": "answered",
        "text": "Inspect the receiving schema.",
        "source": "test_fixture",
    }
    data.update(changes)
    with pytest.raises(ValidationError):
        LessonAssistantReply.model_validate(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"hint_level": 99},
        {"question": "private learner credential sentinel" + "x" * 2401},
        {"context": {"private": "private learner credential sentinel"}},
    ],
)
def test_internal_service_revalidates_forged_requests_before_calling_provider(changes, recwarn):
    class RecordingAssistant:
        called = False

        def answer(self, request):
            self.called = True
            return FakeLessonAssistant().answer(request)

    assistant = RecordingAssistant()
    forged = assistant_request().model_copy(update=changes)
    result = LessonAssistantService(assistant).answer(forged)
    assert result.status == "unavailable" and result.source == "none"
    assert "private learner credential sentinel" not in result.model_dump_json()
    assert not assistant.called and not recwarn
