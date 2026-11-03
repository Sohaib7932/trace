"""Bounded conversational advice, explicitly separate from verified learner results."""

import re
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from app.core.ai_privacy import public_ai_question
from app.domain.lesson_spec.fields import Digest, Items, No, Value, Yes
from app.schemas.lesson_assistant import LessonAssistantContext


def chat_text(value: str) -> str:
    public_ai_question(value)
    if not value.strip() or any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError("Use nonblank UTF-8 text without control characters")
    # This is plain text, including code examples, never trusted HTML or an instruction
    # to execute anything. The frontend renders text nodes, not an HTML/Markdown engine.
    return value


type ChatText = Annotated[str, Field(min_length=1, max_length=6000), AfterValidator(chat_text)]
type TutorStyle = Literal["adaptive", "socratic", "direct", "worked_example"]


class TutorHistoryMessage(Value):
    role: Literal["user", "assistant"]
    text: Annotated[str, Field(min_length=1, max_length=1600), AfterValidator(chat_text)] = Field(
        repr=False
    )


class TutorConversationCreate(Value):
    mode: Literal["conversation"]
    question: Annotated[str, Field(min_length=1, max_length=2000), AfterValidator(chat_text)] = (
        Field(repr=False)
    )
    style: TutorStyle = "adaptive"
    code: ChatText | None = Field(default=None, repr=False)
    history: Items[TutorHistoryMessage] = Field(default=(), max_length=6, repr=False)

    @model_validator(mode="after")
    def total_input_bound(self) -> Self:
        if len(self.model_dump_json().encode("utf-8")) > 10000:
            raise ValueError("Conversation input exceeds 10000 UTF-8 bytes")
        return self


class ConversationTutorContext(Value):
    policy_version: Literal["engineering-conversation-v1"] = "engineering-conversation-v1"
    lesson_version: Literal["1.0.0"] = "1.0.0"
    lesson_digest: Digest
    public: LessonAssistantContext = Field(repr=False)
    latest_saved_verification: Literal["passed", "failed", "unknown"]
    # This context deliberately does not claim raw execution/check details that the
    # existing authorized context capture does not supply.
    detailed_runtime_checks_supplied: No = False
    learner_code_execution: Literal["not_executed"] = "not_executed"


class ConversationTutorRequest(Value):
    trusted_context: ConversationTutorContext = Field(repr=False)
    untrusted_dialogue: TutorConversationCreate = Field(repr=False)


class ConversationTutorReply(Value):
    mode: Literal["conversation"] = "conversation"
    status: Literal["answered", "declined", "unavailable"]
    text: ChatText = Field(repr=False)
    source: Literal["ai", "test_fixture", "none"]
    interpretation_only: Yes = True
    can_complete_lesson: No = False
    execution_status: Literal["not_executed"] = "not_executed"
    history_scope: Literal["client_page_session"] = "client_page_session"

    @model_validator(mode="after")
    def provenance(self) -> Self:
        if (self.status == "unavailable") != (self.source == "none"):
            raise ValueError("Unavailable advice cannot claim a provider answer")
        return self


_UNSUPPORTED_AUTHORITY = re.compile(
    r"\bI (?:have |successfully )?(?:executed|ran|tested|verified|compiled)\b|"
    r"\b(?:all|your) tests (?:have )?pass(?:ed)?\b|"
    r"\byou (?:have |successfully )?(?:passed|completed) (?:the |this |your )?(?:lesson|task)\b|"
    r"\b(?:mark|set) (?:this |the |your )?(?:lesson|task) (?:as )?complete\b|"
    r"\b(?:expected_field|prediction_answer|GEMINI_API_KEY|private_evaluator)\s*[:=]",
    re.I,
)


def explanatory_text(value: str) -> str:
    chat_text(value)
    if _UNSUPPORTED_AUTHORITY.search(value):
        raise ValueError("Advice cannot assert execution, completion or private configuration")
    return value


class ConversationWording(Value):
    status: Literal["answered", "declined"]
    text: Annotated[str, Field(min_length=1, max_length=6000), AfterValidator(explanatory_text)] = (
        Field(repr=False)
    )


def unavailable_conversation() -> ConversationTutorReply:
    return ConversationTutorReply(
        status="unavailable",
        text="The engineering tutor is unavailable. Your saved attempts and results are unchanged.",
        source="none",
    )
