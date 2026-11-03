"""Finite, stage-scoped questions derived from the two pinned public lessons.

These are authored educational choices, never model-authored diagnoses or a
second evidence extractor. Runtime claims remain in LessonTutoringService's
fresh owned read. Chat neither delivers nor advances the reserved hint ladder.
"""

from dataclasses import dataclass
from typing import Literal

from app.schemas.lesson_assistant import LessonStage, SupportedLesson

type MaterialField = Literal["objective", "scenario", "outgoing_code", "schema_code"]


@dataclass(frozen=True)
class AuthoredGuidance:
    identity: str
    lessons: frozenset[SupportedLesson]
    stages: frozenset[LessonStage]
    material: tuple[MaterialField, ...]
    text: str


_BOTH: frozenset[SupportedLesson] = frozenset(
    {"fastapi-payload-mismatch", "fastapi-nested-payload-transfer"}
)
_ALL: frozenset[LessonStage] = frozenset(
    {"predict", "investigate", "modify", "verify", "transfer", "revisit"}
)
GUIDANCE_VERSION = "public-stage-guidance-v1"
AUTHORED_GUIDANCE = (
    AuthoredGuidance(
        "prediction-question",
        _BOTH,
        frozenset({"predict"}),
        ("scenario", "outgoing_code", "schema_code"),
        "Before choosing a prediction, compare the outgoing JSON with the receiving model. "
        "Which fields and object levels must the request satisfy before the route can run? "
        "Record your own prediction before changing the mapping.",
    ),
    AuthoredGuidance(
        "modification-question",
        _BOTH,
        frozenset({"modify"}),
        ("objective", "outgoing_code", "schema_code"),
        "Compare one part of the outgoing mapping with the corresponding part of the "
        "receiving schema. What single change would you investigate next, and what result "
        "would you expect? Submitting a change does not prove that it works.",
    ),
    AuthoredGuidance(
        "verification-question",
        _BOTH,
        frozenset({"verify"}),
        ("objective",),
        "Review the saved verification checks separately: HTTP status, API response, "
        "validation, row count and stored values. Which observations concern the request, "
        "and which come from an independent database read? Only the trusted verifier "
        "establishes the result; this question does not establish a new result.",
    ),
    AuthoredGuidance(
        "notes-trace-question",
        frozenset({"fastapi-payload-mismatch"}),
        _ALL,
        ("objective", "outgoing_code", "schema_code"),
        "Follow the note value through the visible request builder and receiving model. "
        "Is the form value placed under a key that the receiving model declares? "
        "Use the two code panels to explain your reasoning before testing a change.",
    ),
    AuthoredGuidance(
        "tasks-level-question",
        frozenset({"fastapi-nested-payload-transfer"}),
        _ALL,
        ("objective", "outgoing_code", "schema_code"),
        "For the Tasks lesson, compare object boundaries as well as field names. "
        "At which JSON level does each receiving model declare its fields? "
        "A value's presence somewhere in a request does not establish that its shape "
        "matches the nested contract.",
    ),
)


def stage_guidance(lesson_id: SupportedLesson, stage: LessonStage) -> dict[str, str]:
    """Server filters before provider selection; no client can unlock a choice."""
    return {
        item.identity: item.text
        for item in AUTHORED_GUIDANCE
        if lesson_id in item.lessons and stage in item.stages
    }
