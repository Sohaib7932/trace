# ADR-008 — Transfer verification and UTC retrieval checkpoints

Status: accepted for Module 3.

PR #1 was verified merged before work began. Module 3 starts from merged main
fd74d00 on feat/trace-module-3-transfer-retention, preserving existing session logs.

## Decision

Reuse immutable lesson versions and the existing owned session state machine for
original and transfer phases. Their lesson IDs distinguish phase identity; phase
availability and completion are read projections of persisted sessions, not another
mutable phase-status table. Transfer requires an owned completed original lesson.
Existing original lesson content, hash and evaluation semantics stay unchanged.

Publish fastapi-nested-payload-transfer 1.0.0. Accept only flat/nested task mapping
choices. Reuse verification reservation, retry, evidence and completion orchestration;
a private real FastAPI /tasks adapter validates nested Pydantic models and commits
to runtime_tasks. Readback uses a separate SQLAlchemy session scoped by run ID.
Task and note runtime data stay separate. No learner code or public runtime route.

In the same transaction as transfer completion, insert two checkpoints uniquely
identified by transfer session and ordinal, due at completion +1 and +7 UTC days.
Intervals and versioned deterministic questions are centralized. Checkpoint identity,
question hash and schedule are immutable; responses are append-only, numbered and
idempotent. The first correct response sets completion exactly once. A DB gate and
constraints serialize concurrent decisions. Existing sessions and terminal guards
remain authoritative. Missed checkpoints remain due indefinitely.

An injectable aware clock controls learning/scheduling time; production uses UTC now.
UTC durations mean 24/168 hours, not local calendar arithmetic across DST. Identity
credential expiry continues to use real security time. Tests control the domain clock
without changing credentials or exposing a production time-control endpoint.

The former seven-day cookie default could expire before a checkpoint due seven
days after transfer. The default becomes 30 days. On the existing protected anonymous
bootstrap operation, a still-valid credential in the latter half of its configured
lifetime is renewed to that lifetime and its HttpOnly cookie reissued. Expired or
revoked credentials never regain access; explicit shorter TTLs remain configurable
and may prevent a later return. Previously issued valid seven-day cookies can renew
when returning after this update. No account or recovery feature is introduced.

Questions appear only when due or completed, contain new contexts/field names, and
never serialize their answer key. Feedback is revealed after a saved response.
No original hints or completed payload solution is shown before that response.

## Tradeoffs and boundaries

Each completed transfer session gets its own two checkpoints. Repeated HTTP completion
replays cannot duplicate them. Multiple genuine completed sessions remain distinct
learning histories. There is no reminder delivery, scheduler, notification, score or
retention percentage. The in-app journey shows stored facts and server-derived status.

Data introduced: isolated task fixtures, checkpoint source/due/question identity and
append-only selected answers, explanations, outcomes and timestamps. These support
inspection of transfer/retrieval behaviour, not evidence of learning improvement.
Expiry/revocation removes credential access, not saved data. Retention/export/deletion
and credential recovery remain unimplemented; no indefinite-retention/deletion promise.

The forward SQLite migration widens the existing constrained mapping set while
preserving populated history, foreign keys and existing triggers. A populated-data
regression and down/up tests are required. Downgrade must refuse a populated transfer
history rather than silently discard evidence incompatible with Module 2.

Revisit this design for actual participant retention requirements, further exercise
types, external reminders or production deployment; do not add that infrastructure now.

References: [FastAPI nested bodies](https://fastapi.tiangolo.com/tutorial/body-nested-models/),
[Python 3.13 datetime/UTC durations](https://docs.python.org/3.13/library/datetime.html).
