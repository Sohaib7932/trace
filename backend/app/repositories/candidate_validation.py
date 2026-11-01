"""Execution port for the internal candidate-validation gate."""

from typing import Protocol

from app.domain.lesson_spec import LessonSpecV1
from app.schemas.candidate_validation import RuntimeValidationReport


class CandidateRuntime(Protocol):
    def validate(self, definition: LessonSpecV1) -> RuntimeValidationReport: ...
