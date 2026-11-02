"""Canonical evidence fixtures using production catalog and verification builders."""

from datetime import timedelta

from app.domain.accounts import Principal
from app.domain.learning import Observation
from app.schemas.engineering_evidence import EvidenceQuery
from app.schemas.evidence_feedback import FeedbackQuery
from app.schemas.lesson_assistant import PublicLessonContent
from app.services.catalog import PUBLIC_CONTENT
from app.services.engineering_evidence import EngineeringEvidenceService
from app.services.evidence_feedback_policy import build_feedback_request
from app.services.verification import VerificationService
from tests.unit.test_engineering_evidence_sources import (
    START,
    ReadOnlyRepository,
    SourceStore,
    at,
    identity,
)


def feedback_source():
    source = SourceStore()
    VerificationService._checks(
        source,
        identity("run"),
        "body",
        "content",
        Observation(
            422,
            '{"detail":"validation rejected the request"}',
            ("missing:content", "extra_forbidden:body"),
            (),
            None,
        ),
        at(5),
    )
    return source


def feedback_query(source, **changes):
    return FeedbackQuery.model_validate(
        {
            "request_id": identity("feedback-request"),
            "session_id": source.session.id,
            "start_at": START,
            "end_at": at(100),
            "as_of": at(100),
            "max_records": 64,
            **changes,
        }
    )


def feedback_principal(source):
    return Principal(source.session.learner_id, START + timedelta(days=1))


def feedback_request(source=None, **query_changes):
    source = source or feedback_source()
    query = feedback_query(source, **query_changes)
    batch = EngineeringEvidenceService(ReadOnlyRepository(source)).extract(
        EvidenceQuery(
            owner_learner_id=source.session.learner_id,
            session_id=query.session_id,
            start_at=query.start_at,
            end_at=query.end_at,
            as_of=query.as_of,
            max_records=query.max_records,
        )
    )
    return build_feedback_request(
        query.request_id, batch, PublicLessonContent.model_validate(PUBLIC_CONTENT)
    )
