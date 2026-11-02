# Engineering evidence source map

This Phase 3.5A audit maps the actual learner implementation for
`fastapi-payload-mismatch` (Notes) and `fastapi-nested-payload-transfer` (Tasks).
It distinguishes persisted observations from missing instrumentation. An
observation is not a competency score, a diagnosis of understanding or proof that
the learner worked without external help.

The six internal competency categories are **prediction**, **investigation**,
**modification**, **debugging**, **verification** and **transfer**. Category
membership describes the observed action; it does not establish mastery.

## Learner workflow and authoritative sources

The public learner routes are in `backend/app/api/v1/learning.py`. Their owner is
the server-resolved `Principal.learner_id` from
`backend/app/api/dependencies.py:current_learner`. Account identities and guest
credentials resolve to this same Trace learner UUID. The account UUID and the
learner UUID are different identities.

`LearningService.create_session` in `backend/app/services/learning.py` resolves an
explicit lesson/version and persists its `LessonVersion.id` in the session.
`owned` checks the owner before reading or changing session records. Prediction,
attempt, hint and verification routes do not accept competency labels, scores or
client assertions that verification passed.

| Record | Available authoritative fields | Meaning and limits |
| --- | --- | --- |
| `LearningSession` | `id`, `learner_id`, `lesson_version_id`, `state`, `idempotency_key`, `created_at`, `completed_at` | Owns the activity and pins a particular legacy lesson version. Completion requires a passed verification; completion alone is not evidence for every competency. |
| `LessonVersion` | `id`, `lesson_id`, `version`, `content_hash`, `public_content`, private `expected_field` and `prediction_answer`, `created_at` | Supplies the pinned identity and deterministic legacy contract. Private values are for trusted extraction, not learner/provider projections. |
| `Prediction` | `id`, `session_id`, `selected_answer`, `reasoning`, `idempotency_key`, `created_at` | The original selected outcome and learner explanation. Correctness is derived from the pinned answer; no correctness column or trusted reasoning evaluation exists. |
| `Attempt` | `id`, `session_id`, `number`, `field_name`, `explanation`, `hints_before`, `idempotency_key`, `created_at` | A bounded mapping submission, not a source-code patch. `hints_before` counts requests, including unsuccessful or still-pending requests. |
| `HintOperation` | `id`, `session_id`, optional `attempt_id`, `sequence`, `idempotency_key`, `created_at`, `deadline_at`, `status`, `completed_at` | A durable reservation supplies an exact request timestamp. Pending or finalized status alone does not establish delivery. |
| `TutorInteraction` | `id`, `session_id`, optional `attempt_id`, `sequence`, `status`, optional `text`, `idempotency_key`, `created_at`, `provider`, `fixture`, `prompt_version`, `interaction_type` | An immutable delivered/error result. For the reservation flow, `created_at` is finalization time. An error result provides no delivered guidance. |
| `VerificationRun` | `id`, `session_id`, `attempt_id`, `status`, `idempotency_key`, `created_at`, `completed_at`, `feedback` | Connects a submission to actual verification. `passed` and `failed` are deterministic outcomes; `error` is unavailable or inconsistent execution evidence, not learner failure. |
| `VerificationCheck` | `id`, `run_id`, `code`, `matched`, `expected`, `observed`, `source`, `created_at` | Immutable evidence produced by trusted runtime verification. Expected/observed details remain internal unless explicitly projected by an existing authorized contract. |
| `RuntimeNote` / `RuntimeTask` | `id`, `run_id`, title and content/priority, `created_at` in SQL | Committed exercise rows associated with a verification run. Fresh readback is distinct from the HTTP response. |
| `LearningEvent` | `id`, `session_id`, `event_type`, optional `reference_id`, `created_at` | Lifecycle references supplement the primary records. Their timestamps use the event writer's UTC clock; they do not replace primary record timestamps. |
| `RetrievalCheckpoint` | `id`, `transfer_session_id`, `ordinal`, `question_id`, `question_hash`, `due_at`, `created_at`, `completed_at` | Pins a retrieval question to a completed Tasks session and preserves its schedule. |
| `RetrievalAttempt` | `id`, `checkpoint_id`, `number`, `selection`, `reasoning`, `correct`, `feedback`, `idempotency_key`, `created_at` | A persisted deterministic retrieval response. Correctness is not a retention or mastery score. |

Detached record definitions are in `backend/app/domain/learning.py`,
`backend/app/domain/tutoring_operations.py` and
`backend/app/domain/retrieval.py`. Concrete fields and constraints are in
`backend/app/db/models.py`; reads and writes are in
`backend/app/db/learning.py` behind `backend/app/repositories/learning.py`.

## Coverage by competency and lesson

| Competency | Notes | Tasks | Evidence source | Limitations |
| --- | --- | --- | --- | --- |
| Prediction | Direct submitted outcome and deterministic correctness | Direct submitted outcome and deterministic correctness | Immutable prediction joined through its owned session to the pinned lesson answer | Selecting the correct option does not establish conceptual mastery. Reasoning is learner-authored, not a trusted diagnosis. |
| Investigation | Unavailable: no captured investigation action | Unavailable: no captured investigation action | Authored scenario and code are available, but no investigation submission or selected code-reference record exists | No inference from elapsed time, page views, completion or the presence of investigation content in an unpublished specification. |
| Modification | Partial: direct `body` / `content` mapping submission; outcome available after verification | Partial: direct `flat` / `nested` mapping submission; outcome available after verification | Numbered attempt plus its actual verification runs | No initial/final source diff or arbitrary code submission. A correct mapping alone does not establish independent authorship. |
| Debugging | Partial: indirect observable failed run followed by a changed submission and passed run | Partial: indirect observable failed flat run followed by nested correction and passed run | Ordered attempts and finalized verification outcomes | Shows recovery chronology, not proven diagnosis. Cannot distinguish understanding from blind retries. Infrastructure errors are not the initial learner failure. |
| Verification | Direct actual runtime checks and final status | Direct actual runtime checks and final status | Verification run, check records, ASGI response and independent database readback | An unavailable run may contain only an execution check. Do not manufacture missing evidence categories or infer all checks from session completion. |
| Transfer | Unavailable in this session: Notes completion is the recorded prerequisite, with no outgoing transfer-performance observation | Partial: direct successful completion of the related Tasks exercise | Owned Tasks session's pinned version and its passed run; prerequisite enforcement | No exact source Notes session/version relationship is persisted. Performance on one related task does not establish general transfer ability. |

`LearningService.attempt` requires a failed flat Tasks run before accepting a
nested correction. This proves the application recorded the baseline failure
before the correction. It does not prove that the learner investigated the
schema or correctly diagnosed the error.

There is no authoritative persisted learner misconception diagnosis. Authored
misconception definitions in lesson specifications are educational configuration,
not observations about a learner. `FakeTutorProvider.analyse_misconception`
returns no diagnosis; the learner workflow does not persist such analysis.

The internal batch represents these distinctions explicitly in six validated
`EvidenceCoverage` descriptors. Their direct/partial/unavailable values describe
instrumentation, not learner ability. `observed_in_window` means a real competency
observation exists in the requested cohort; an empty cohort retains all six
descriptors with false presence flags and its exact lesson pin. Missing
instrumentation is therefore distinguishable from absent observations without
creating synthetic learner events or scores.

## Actual verification evidence

`backend/app/services/verification.py:VerificationService` reserves a run, calls
the trusted verifier outside the learner write transaction, then persists checks
and the final deterministic outcome. Notes checks are constructed in `_checks`;
Tasks checks are constructed in `backend/app/services/task_evidence.py:task_checks`.

| Check | Trusted observation | Recorded source |
| --- | --- | --- |
| `http_status` | Actual request status compared with expected `201` | `asgi_http` |
| `api_response` | Actual response matches the receiving contract, trusted fixture values and response identity | `asgi_http` |
| `validation` | Actual receiving-schema acceptance and observed validation codes | `asgi_http` |
| `row_count` | Separate fresh read returns exactly one committed exercise row | `fresh_database_read` |
| `stored_values` | Fresh row values and identity match the trusted request/response expectations | `fresh_database_read` |

`backend/app/verification/asgi_notes.py` and `asgi_tasks.py` run controlled real
FastAPI exercise applications using an in-process ASGI transport, not a public
TCP self-call. The exercise services commit the write through their repository.
A separate read context obtains saved rows. Unavailable readback is represented
as unavailable, never as an invented zero-row result.

The deterministic evaluators are `evaluate` in
`backend/app/domain/learning.py` and `evaluate_transfer` in
`backend/app/domain/transfer.py`. Rejection of the original invalid mapping can
produce a genuine `failed` result. Missing execution, unavailable readback or
inconsistent response/database evidence produces `error`, with no learner grade.
If no runtime observation exists, verification records a separate `execution`
check from `verifier`; interrupted-run recovery may record `execution` from
`server_lifecycle`. Neither case proves the five runtime categories were observed.

## Assistance provenance and historical limits

The learner hint route currently uses the deterministic `FakeTutorProvider`.
The application-scoped internal AI adapters do not change that route. Current
delivery records are fixture guidance; there is no authoritative authored-hint
delivery event or live-provider tutoring record in this learner flow.

The reservation/finalization implementation in
`backend/app/services/learning.py` separates these facts:

1. A committed `HintOperation` proves a request was reserved at its `created_at`.
2. A matching `TutorInteraction(status="delivered")` proves guidance was finalized
   at the interaction's `created_at`. The reservation and result share the ID,
   session, optional attempt, sequence and idempotency key.
3. A pending reservation or `status="error"` result does not prove delivery.
4. Guidance finalized after an attempt was submitted does not prove assistance
   before that submission. A requested hint is not automatically delivered help.
5. Earlier delivered guidance remains part of the available session history for
   later attempts. Starting another attempt without another request does not
   establish independent activity or erase earlier assistance.

Old interactions that predate reservations retain their persisted delivery/error
status, but do not supply an authoritative request timestamp. The historical
`hint_requested` event references an optional attempt ID rather than an individual
hint operation, so it cannot supply an exact request-to-result join. No synthetic
reservation or historical request time should be backfilled.

Absence of a delivered hint is not sufficient to infer independent work. The
system does not capture external assistance, all authored material consumption
or the learner's reasoning process. Unknown assistance must remain unknown.
Assistance facts should describe what Trace actually recorded and at what time,
without claiming that delivered text was read, understood or causally responsible
for a later result.

## Pinned identity, transfer and retrieval provenance

`backend/app/services/catalog.py` defines the two legacy `1.0.0` lessons and their
legacy hashing functions. A session's `lesson_version_id` identifies the exact
immutable version. Evidence extraction must validate that record and its digest;
it must not resolve the latest version or substitute a Phase 3.2 blueprint.
Unpublished LessonSpec candidates are not the source of existing learner records.

The legacy transfer prerequisite checks for any completed same-owner Notes
session, both in `LearningService.create_session` and the
`0004_transfer_retrieval.py` database guard. The Tasks session does not store an
exact parent Notes session ID, parent version or cross-session digest pin.
Choosing the earliest/latest Notes completion would invent provenance. The
source prerequisite is known; the exact originating source-session relationship
is unavailable.

Retrieval linkage is more explicit. `schedule_checkpoints` in
`backend/app/services/retrieval.py` records the completed Tasks session ID and
the question ID/hash. `question_for` in `backend/app/domain/retrieval.py` verifies
the hash before deterministic grading. The schedule remains **+1/+7 elapsed UTC
days from Tasks completion**. Retrieval attempts remain separate from new daily
exercise assignments and are not evidence that a learner inspected or modified
code during the retrieval question.

The actual retrieval prompts disclose an observed rejection or ask which mapping
satisfies a contract. A selected recall answer does not prove an original
before-result prediction, a captured investigation or an executed modification.
Extraction preserves it as auxiliary `RetrievalEvidence`, with answer/checkpoint
references, the pinned question digest and factual correctness. It receives no
competency label and does not change competency coverage-presence flags. Its
assistance remains unknown because retrieval-specific help delivery is not
recorded.

Guest history claiming in `backend/app/services/accounts.py` associates the
account with the existing learner UUID. It does not rewrite historical session
owners or create a second set of learner records. Evidence ownership should
follow the resolved learner UUID through this existing identity mapping.

## Existing integrity and read-only projection rationale

The existing database already preserves the primary historical observations:

- `0002_learning_learning_engine.py` protects lesson versions, predictions,
  attempts, tutor interactions, verification checks, events and runtime notes
  against update/delete. It pins session identity, permits only valid session
  transitions, preserves finalized runs, requires checks before finalization,
  requires all five matched categories for a passed run and a passed run for
  session completion.
- `0004_transfer_retrieval.py` scopes attempts and runtime records to their
  lesson family, enforces the transfer prerequisite, preserves runtime Tasks and
  retrieval attempts, and protects checkpoint source, identity, schedule and
  completion.
- `0007_tutor_reservations.py` preserves reservation identity and request history,
  permits one-way finalization and requires the exact matching result.
- SQL foreign keys and compound attempt/session keys protect child-record scope;
  record/key uniqueness supports idempotent learner operations.
- `UTCDateTime` in `backend/app/db/models.py` requires aware values and normalizes
  persistence/readback to UTC.

A deterministic read-only projection can retain immutable source references
without duplicating raw records or introducing an evidence table. Extraction
must still authorize the owner, validate session/child relationships, verify
pinned identity/digest and reject forged source links. Existing SQL guards do
not justify trusting arbitrary objects supplied by a caller.

Stable evidence identity should distinguish the source record and observed event
type/schema. A request observation and a later finalized result are separate
events; a pending record must not become a different historical fact under the
same event identity. Later attempts do not overwrite earlier observations.
Out-of-order source reads must be ordered deterministically using source time
and stable identity. Missing records or unknown assistance remain explicit gaps,
not manufactured success/failure observations.

The previous `backend/app/schemas/learner_evidence.py` and
`backend/app/services/learner_evidence.py` implement bounded selected facts and
eight factual counts. They do not prove database authorization or source
completeness. Their existing contracts should remain compatible; counts alone
do not provide the richer provenance required by engineering observations.

## Remaining instrumentation and product decisions

- Explicit investigation submissions and trusted code-reference selection do not
  exist in the current learner workflow.
- Submitted source patches, code-diff provenance and independently assessed
  debugging diagnoses are unavailable.
- An exact source Notes-session link for a Tasks transfer session is unavailable.
- Authored-hint viewing/delivery and external assistance are not captured.
- Historical reservation-free hint request times cannot be reconstructed exactly.
- No competency scoring, skill-level policy, mastery thresholds, interest
  taxonomy or AI grading is established by these records.

Adding those observations or policies requires a separate milestone. The source
map does not authorize learner API changes, changes to runtime rules, new daily
quota semantics, publication of candidates or changes to retrieval scheduling.
