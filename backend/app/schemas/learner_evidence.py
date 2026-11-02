"""Internal selected facts, not a learner profile, grading engine or history query."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, Field, StrictBool, StrictInt, model_validator

from app.domain.clock import as_utc
from app.domain.lesson_spec.fields import Items, Value

type UTCInstant = Annotated[AwareDatetime, AfterValidator(as_utc)]
type RecordLimit = Annotated[StrictInt, Field(ge=1, le=10000)]


class LearnerEvidenceWindow(Value):
    """The trusted caller chooses all bounds; this contract chooses no product policy."""

    owner_learner_id: UUID = Field(repr=False)
    start_at: UTCInstant
    end_at: UTCInstant
    as_of: UTCInstant
    max_records: RecordLimit

    @model_validator(mode="after")
    def ordered_window(self) -> Self:
        if not self.start_at < self.end_at <= self.as_of:
            raise ValueError("Require an increasing evidence window ending no later than as_of")
        return self


class EvidenceFact(Value):
    id: UUID = Field(repr=False)
    owner_learner_id: UUID = Field(repr=False)
    occurred_at: UTCInstant


class PredictionFact(EvidenceFact):
    kind: Literal["prediction"]
    correct: StrictBool


class ModificationFact(EvidenceFact):
    kind: Literal["modification"]


class HintFact(EvidenceFact):
    """One request identity, joined to its optional outcome by trusted server code.

    occurred_at is the reservation's exact request time, not the final guidance
    timestamp. A historical result alone cannot satisfy this contract.
    """

    kind: Literal["hint"]
    request_time_source: Literal["reservation"]
    status: Literal["pending", "delivered", "error"]
    completed_at: UTCInstant | None

    @model_validator(mode="after")
    def consistent_delivery(self) -> Self:
        if (self.status == "pending") != (self.completed_at is None):
            raise ValueError("Only pending hint requests have no completion timestamp")
        if self.completed_at is not None and self.completed_at < self.occurred_at:
            raise ValueError("Guidance cannot finish before its request")
        return self


class RetrievalAnswerFact(EvidenceFact):
    kind: Literal["retrieval_answer"]
    correct: StrictBool


class VerificationErrorFact(EvidenceFact):
    """The trusted selector supplies a recorded infrastructure-error completion.

    A failed learner verification is not this fact. No evaluator values, private
    observations or mastery interpretation are represented here.
    """

    kind: Literal["verification_error"]


type SelectedEvidenceFact = Annotated[
    PredictionFact | ModificationFact | HintFact | RetrievalAnswerFact | VerificationErrorFact,
    Field(discriminator="kind"),
]


class LearnerEvidenceBatch(Value):
    """Validated selected facts; does not prove database authorization or completeness."""

    window: LearnerEvidenceWindow = Field(repr=False)
    facts: Items[SelectedEvidenceFact] = Field(max_length=10000, repr=False)

    @model_validator(mode="after")
    def bounded_owner_cohort(self) -> Self:
        if len(self.facts) > self.window.max_records:
            raise ValueError("Selected evidence exceeds the explicit record limit")
        identities = [(fact.kind, fact.id) for fact in self.facts]
        if len(identities) != len(set(identities)):
            raise ValueError("A recorded fact may appear only once in its category")
        for fact in self.facts:
            if fact.owner_learner_id != self.window.owner_learner_id:
                raise ValueError("Every selected fact must belong to the authorized learner")
            if not self.window.start_at <= fact.occurred_at < self.window.end_at:
                raise ValueError("Every selected fact must fall in the explicit event cohort")
            if isinstance(fact, HintFact) and (
                fact.completed_at is not None and fact.completed_at > self.window.as_of
            ):
                raise ValueError("Hint completion cannot contain knowledge after as_of")
        return self
