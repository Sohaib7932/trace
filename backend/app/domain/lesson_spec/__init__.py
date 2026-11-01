"""Lesson Specification V1: pure typed validation, without runtime integration."""

from .definition import (
    MAX_DEFINITION_BYTES,
    InitialLearnerLesson,
    LessonSpecV1,
    initial_learner_projection,
    validate_lesson_spec,
)

__all__ = [
    "MAX_DEFINITION_BYTES",
    "InitialLearnerLesson",
    "LessonSpecV1",
    "initial_learner_projection",
    "validate_lesson_spec",
]
