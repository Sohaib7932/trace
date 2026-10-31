# Module 3 — transfer learning and spaced retrieval delivery

Date: 2026-10-31. This report records implemented behaviour and fresh local checks.
The final delivery chat records the actual commit SHA, push verification, compare URL
and separately observed remote CI outcome after publication.

## 1. Git preflight and compatibility audit

Actual root: `C:\Users\soore\OneDrive\Dokumen\ChatGPT\Trace-v1`.
Before implementation, `gh pr view 1 --repo Sohaib7932/trace --json
state,mergedAt,baseRefName,headRefName,url` returned MERGED, mergedAt
2026-10-31T11:05:19Z, head feat/trace-module-1-2, base main.
Remote fetch showed merge commit fd74d00005cd1d7370bde7f6f40ec927b0bdfafb.
Its tree matches the completed Module 1/2 branch.

Local main was safely fast-forwarded to that merged commit before checkout because
the old local main predated the modified genuine Codex log. Then main was checked
out, `git merge --ff-only origin/main` confirmed up-to-date, and the previously
absent feat/trace-module-3-transfer-retention branch was created. No stash, reset,
clean, force-update or discarded work. Existing log additions and four deliberately
excluded app-generated files were preserved.

Read AGENTS, README, architecture overview/data/API/testing, Module 1/2 reports,
all seven prior ADRs, actual models/repository/services/state machine, publication,
verification/progress, frontend and tests. Read installed Next page, Link,
server/client and Playwright guidance before Next changes. The installed Next
build remains 16.4.3; no dependencies or lockfiles were upgraded. Marketing,
CodeLens, existing migrations, Module 1/2 reports, agent rules/hooks/extractors and
trust state are preserved. The original PUBLIC_CONTENT and lesson_hash ASTs were
compared with merged main and are unchanged.

## 2. Implemented transfer challenge

fastapi-nested-payload-transfer / 1.0.0, title The Nested Payload Problem, has its
own immutable published version/hash and idempotent seed. This is a task-management
context with a structurally nested receiving model, rather than the original notes
field-name correction. Both title and priority can be present yet fail because
priority is at the wrong JSON level. TaskMetadata rejects extras and validates
low/normal/high; TaskCreate requires title and metadata.

An owned completed original lesson unlocks transfer in the service and DB guard.
The established immutable prediction and append-only attempts are reused. The
new constrained request variant is nest_payload_field, field_name flat/nested.
The existing rename_payload_field/body/content variant remains unchanged. Unknown
properties, arbitrary fields/code/URLs/SQL and client success/state flags are rejected.
The nested correction is unavailable until a saved prediction and actual failed
flat-request verification exist. Its completed builder is not shown beforehand.

Published transfer hash:
`c4aefadd5f468da2505db0d14cd4d12bdc1f707282d241a10118cae39c49db0d`.
Original hash remains:
`c3231631019829efe5cd1882b361cf22b8bdcdd51caca2a67a60dd73b326707e`.

## 3. Real controlled verification

The existing reservation/replay/recovery/check/finalization orchestration selects a
trusted adapter by pinned lesson identity, independently of the expected answer.
A private FastAPI /tasks application uses HTTPX2 ASGI transport, Pydantic validation,
an injected task service and explicit SQLAlchemy commit. It is not public code execution.

- Flat fixture: {title: Prepare the product demo, priority: high}. Actual HTTP 422,
  missing:metadata and extra_forbidden:priority, with zero tasks in a fresh read.
- Nested fixture: {title: Prepare the product demo, metadata: {priority: high}}.
  Actual HTTP 201, committed row, independent session read matching ID/title/priority.

The five individual checks retain HTTP/body/validation/row-count/value observations
and sources. A success response without correct fresh readback is error, not passed.
Real insert failure, readback outage, forged success and verifier exception tests
all prevent completion/scheduling. Replays cannot duplicate writes. A strengthened
test verifies that an earlier successful task does not affect a later failed flat
request in another run. runtime_tasks never substitutes for runtime_notes.

## 4. Phase and retrieval design

Original and transfer lesson IDs plus existing owned, version-pinned sessions already
represent the two phases. Their state/completion is projected in an explicit typed
journey response, not duplicated in another mutable phase table. The original state
machine and terminal guards remain. Each actual completed transfer session is a
distinct source for two retrieval activities.

The completion transaction inserts checkpoints unique by source session/ordinal,
anchored at the saved completion timestamp +1 and +7 UTC days (24/168 hours).
RETRIEVAL_DAYS and versioned question definitions are centralized. Scheduling is
idempotent; it shares completion's transaction. An injected failure on checkpoint
INSERT proves completion/result writes roll back, pending work can be retired as
an infrastructure error, and a deliberate retry creates exactly two checkpoints.

Due status uses an injected aware server clock. Production uses UTC now. Boundary
tests cover one microsecond before/exactly at due time and UTC durations across
offset/DST changes. Missed checkpoints remain due. No frontend clock controls
availability and no background scheduler or external notification is introduced.

Checkpoint 1 uses a shipping/destination.zone example; checkpoint 2 uses report
output.format. Question IDs/hashes are persisted and immutable. Upcoming reads omit
question content; due questions contain choices but no authoritative answer key or
old hints. After submission, deterministic feedback is stored. Responses append with
sequence, key, optional reasoning, outcome and timestamp. Same-key identical retries
replay; changed payloads conflict. The first correct response completes once;
new responses after completion conflict while legitimate replays still work.

## 5. Database and APIs

Migration 0004_transfer_retrieval adds runtime_tasks, retrieval_checkpoints and
retrieval_attempts, bringing the existing model to 16 tables plus Alembic metadata.
It widens the mapping check using a data-preserving SQLite batch operation, restores
the original guards and checks FK integrity. New guards enforce transfer prerequisite,
mapping/runtime lesson scope, append-only task/response history and protected
checkpoint schedule/completion. Populated Module 2 history survives actual down-to-0003
and up-to-head unchanged, with prediction immutability intact. A populated transfer
history refuses destructive downgrade. Empty database down/up remains supported.

No startup DDL/seeding. Explicit migration and seed CLI now publish both lessons.
The local ignored development DB was migrated and seeded twice successfully.

Three new owner-scoped API operations:

| Method/path under /api/v1 | Behaviour |
|---|---|
| GET /learners/me/journey | Phase availability/completion, sessions, factual counts, checkpoints, server time, last completed activity |
| GET /retrievals/{checkpoint_id} | Server status, due/completed question and preserved response history |
| POST /retrievals/{checkpoint_id}/attempts | Constrained deterministic response with UUID retry identity |

Generated OpenAPI now has 18 paths / 20 operations. Neither runtime app nor any
production clock-control endpoint is exposed. Existing cookie/Origin/client/CORS,
owner scoping, no-store responses, safe errors and SQLite coordination are reused.
Foreign and missing checkpoints have identical 404 semantics.

## 6. Frontend experience

/learn/fastapi-payload-mismatch continues to work. Completion exposes the transfer
CTA. /learn/fastapi-nested-payload-transfer reuses the workspace, prediction, evidence,
guidance and attempt history with a bounded nested-mapping form. Both routes include
a small factual original → transfer → revisit panel, due dates/status, question
responses/feedback, refresh and retry states. Generated types and TanStack Query
remain the client/server boundary. Reload restores owned server history, including
when the optional browser session link is absent. The homepage design is unchanged.

No completion is decided in the client. Native labelled controls, keyboard choices,
live feedback, responsive panels and existing code windows are reused. Retrieval
submission failures retain the draft and logical retry key. Desktop/mobile saved
screenshots were visually inspected and remain ignored artifacts.

## 7. Credential-return adjustment and privacy

The old seven-day cookie lifetime could end before a checkpoint due seven days
after transfer. Default lifetime and the safe environment example become 30 days.
The protected anonymous bootstrap renews a still-valid credential in the latter half
of its configured life and reissues the same opaque value only as an HttpOnly cookie.
Expiry/revocation is rechecked inside the write transaction; invalidation races are
tested. The browser invokes this protected bootstrap on return. Existing expiry,
revocation, digest-only storage, explicit secure/local modes and ownership remain.
Explicit shorter TTLs remain allowed; lost/expired credentials cannot recover history.
The existing ignored local .env's exact old seven-day default was updated to 30 days;
other local configuration was preserved and the env file is not committed.

New learner data consists of controlled task fixtures, source-linked schedules and
question IDs/hashes, selected options, optional explanations, outcomes and timestamps.
These facts support later inspection of transfer/retrieval activity. No additional
profile, name, email, raw credential, retention score or external reminder data is
collected. Retention/export/deletion and backup expiry remain unimplemented. Revoking
access does not erase evidence; no deletion or indefinite-retention guarantee is made.

## 8. Fresh local validation

Backend commands run from backend/ using the locked environment; sandbox-only uv
commands used `--cache-dir .venv/.uv-cache`. Windows TestClient/browser processes
needed loopback permission. External test network isolation remains enabled.

| Executed command | Actual result |
|---|---|
| uv run --locked pytest --tb=short -o faulthandler_timeout=25 | 128 passed in 86.52s; statement/branch coverage 98.98% |
| Focused strengthened run-isolation regression, --no-cov | 1 passed in 2.06s; earlier saved task cannot rescue later flat failure |
| uv run --locked ruff check . | All checks passed |
| uv run --locked ruff format --check . | 76 files already formatted |
| uv run --locked mypy | No issues in 61 source files |
| uv run --locked alembic upgrade head / current | Success; 0004_transfer_retrieval (head) |
| uv run --locked alembic check | No new upgrade operations detected |
| uv run --locked python -m scripts.seed, twice | Both versions/hashes preserved, no overwrite |
| npm run lint | Passed |
| npm run typecheck | Route type generation / tsc passed |
| npm test | 4 files / 21 passed, 40.69s |
| npm run build | Passed; original and transfer routes generated |
| npm run test:e2e | 6 passed (1.3m), desktop/mobile Chromium |
| python -B -m unittest discover -s scripts/tests -v | 24 passed in 2.011s; adapter unchanged |
| OpenAPI export + npm run api:types, two passes | Identical hashes to reviewed artifacts |
| git diff --check | Passed before staging; repeated staged check required before commit |

OpenAPI SHA-256:
`b6b3942627a6ba574bd7e0c9a436adcbe778d5a58c40bb17b77c225bd8aaa55d`.
TypeScript SHA-256:
`ec9c5424dd3a1e2ea2d7309c30056b3fe4df5fa3179f8fe412d3fdc00b50fe06`.
Original 95 backend / 14 frontend / four browser / 24 logging regressions remain.
New domain rules have 100% measured coverage. Test coverage is not empirical evidence
of learner understanding. Early constraint-name normalization failure was resolved
with the existing Alembic naming convention; no assertion/security guard was weakened.
Later literal wrapping was checked for AST equivalence, preserving published hashes.
The existing unrelated external-lockfile Next warning required no product change;
there were no new meaningful Next-specific feedback candidates.

## 9. Browser proof and CI distinction

Both full new journeys use genuine backend responses, real task persistence and
independent readback. They complete the original, unlock transfer, lock prediction,
observe flat/422/zero tasks, verify nested/201/one task, inspect two schedules,
check the pre-due boundary, complete checkpoint 1 after a failed response, complete
the missed second checkpoint, then reload both completions and response history.
The old homepage/notes journeys also pass on desktop and mobile, with no page errors.

The test bootstrap injects time from an atomic local fixture file; there is no
production HTTP clock override. One Playwright worker serializes that shared clock.
All runs use temporary migrated/seeded DBs and abort requests outside the fixture API
origin. Credential-bearing traces are off. The unchanged CI workflow runs backend
on Windows/Linux and frontend/browser checks on Linux; configured CI is distinct
from the actual post-push run recorded in the final delivery chat.

## 10. Inclusion audit and limitations

The candidate-file pattern/manual audit found only the four previously reviewed dummy
credential values in tests, not real secrets. No dedicated secret scanner executable
was installed. Safe env examples are included; env files, DBs, caches, virtualenvs,
node_modules and browser output remain ignored. This is a bounded audit, not proof
against all possible secret encodings.

The genuine shared Codex log has seven submitted prompts/six emitted final answers
at review, including the prior delivery and this Module 3 request. All previously
committed entry text is unchanged, attribution is SoorejS, and tool/reasoning/context
content is excluded. The four previously identified app-generated suggestion files
remain untouched/untracked and are excluded again. No logs are fabricated or backfilled;
this turn's final answer cannot be committed before it is emitted. Hooks/trust and the
historical Claude record are unchanged. No competing log directory is introduced.

Implemented/tested locally: the full bounded transfer/retrieval journey above.
Not implemented: live AI, creator publishing, arbitrary code execution, accounts or
recovery, adaptive intervals, external notifications, export/deletion, production
deployment and empirical learner studies. No mastery, expert status, retention
percentage, reminder delivery or measured learning improvement is claimed.
SQLite remains a local single-writer design. An ASGI timeout cannot undo an already
committed worker side effect; unique runs/readback and explicit error recovery remain
necessary. Next work should evaluate real learner usability with consent, clarify
retention/export/deletion and recovery, and assess checkpoint question quality before
broadening content or deploying publicly. No unresolved Module 3 implementation blocker.
