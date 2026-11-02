# Feedback HTTP MVP: C3/C4/C6 engineering and release evidence

Date: 2 November 2026. Branch: `codex/phase-3-5c-feedback-mvp`.
The user approved signed-in accounts including completed-session reflection,
and an ordinary commit/push after validation, with no merge. No live provider,
guest audience, next-action hints or repair solutions were approved or enabled.

## Milestone status

| Stage | Status and evidence |
| --- | --- |
| C1/C2 | Previously completed and merged in PR #12; reused, with an optional narrowing of eligible session states. Existing internal defaults remain disabled. |
| C3 operational security | Implemented and tested: application-scoped admission/provider resources, process-local rolling rate/concurrency limits, real provider wait bounds, HTTP deadlines, sanitized errors and all-status no-store. |
| C4 authenticated feedback API | Implemented and tested through the actual ASGI application: `POST /api/v1/sessions/{session_id}/feedback`, strict `{}` body, existing account authentication/learner ownership, C1 freshness and C2 projection. |
| C5 frontend integration | Additive handoff and generated TypeScript contract supplied. No handwritten client/screen integration exists in this checkout. Sohaib owns that work; his branch and browser walkthrough remain unconfirmed. |
| C6 backend release validation | Focused and relevant regression checks passed. Full browser/deployment/Supabase end-to-end release validation remains pending; this is not a production-readiness claim. |

The feature branch starts from published documentation commit `871c5d4`, which
is directly above merged main `cf9c764`. The documentation branch itself is not
recreated or modified. The two published handoff files remain byte-for-byte
unchanged. This additive report records implemented engineering; the final
delivery message records the resulting commit/push/CI status. No PR is merged.

## Implemented request path

1. Feedback-only ingress bounds requests before authentication, without trusting
   a client-provided quota identity or forwarded IP.
2. Existing allowed-Origin/Trace client checks and `current_account` authenticate
   the request. Existing `current_learner` resolves the role/learner identity.
   A guest cookie alone cannot access this operation.
3. The application-owned controller admits work under the trusted account UUID,
   with a monotonic request deadline and bounded active/history state.
4. Existing C1 reads current identity/mapping, session ownership and the exact
   legacy lesson pin. It excludes abandoned sessions and applies the existing
   first-attempt gate before correctness extraction or provider invocation.
5. Trusted repositories and EngineeringEvidenceService construct the same
   deterministic evidence plan used by C1/C2. No client claims or runtime data are
   accepted. Feedback evaluation writes no learner evidence/history. Existing
   authentication bootstrap may update identity metadata or create the account's
   learner mapping; the prior guest-claim sequencing rules still apply.
6. The public dependency uses an explicit disabled explanatory provider through
   the bounded provider interface. Existing feedback policy renders trusted
   deterministic text. Internal shared mock selection cannot activate public AI.
7. C1 reauthorizes and checks both source-history and evaluated-cohort fences,
   including after provider failure/fallback. A changed source returns 409;
   current authorization failure takes priority.
8. Existing C2 projects only supported public claims and response-local aliases,
   then validates the exact projection. Next-action, recall and repair guidance
   remain filtered. Known credential expiry is checked at handoff.
9. Feedback middleware buffers the bounded response, adds no-store headers and
   replaces error content with fixed safe messages and empty details. No raw
   submitted fields, provider diagnostics or partial internal response is emitted.

Default limits and frontend usage are specified in
[the integration addendum](../frontend-feedback-api.md). They are process-local:
10 requests/minute/account, one account worker, four global workers; 120 ingress
requests/minute, 16 ingress requests in flight, 1,000 tracked subjects; eight
seconds/request and two seconds/provider wait; 4,096 request bytes and 65,536
response bytes. Effective request/body limits cannot exceed existing global HTTP
limits, and the provider wait cannot exceed the effective request deadline.

The manager owns one bounded provider executor for its application lifespan.
Admission precedes executor submission. HTTP cancellation does not release the
actual worker's lease; provider timeout does not release a running provider's
lease. Shutdown stops new admissions and cancels queued futures. Python cannot
kill an uncooperative running provider thread; that thread may delay process
shutdown. Future live adapters must enforce transport timeouts. No such adapter
is selected here.

## Executed checks

All backend tests ran on Windows/Python 3.13.5 using the existing locked
environment and disposable test databases. The real environment files and
learner database were not copied into the isolated validation checkout.

| Check | Actual result |
| --- | --- |
| Initial combined C4/C6 run | 44 passed, two new test assumptions failed; corrected against canonical wording and append-only database rules. |
| C3/C4/C6 focused | 94 passed in 39.75 seconds. |
| Final focused, effective-budget and network isolation | 98 passed in 38.84 seconds, zero failures/errors/skips; includes 97 new cases plus the existing external-network-blocking test. External connections blocked; Windows loopback internals allowed. |
| Relevant backend regression | 1,721 passed in 491.44 seconds, zero failures/errors/skips; includes all new tests, C1/C2, evidence/feedback, authentication, ownership, Notes/Tasks, retrieval, tutoring/concurrency and selected migration/legacy checks. |
| Additional AI lifecycle/configuration | 15 passed in 4.59 seconds; three configuration cases overlap the regression run. |
| Coverage of the five new HTTP/security modules | 91.40%, including branches; unchanged 85% coverage gate passed. This is scoped coverage, not whole-backend coverage or a comparison with 97.62%. |
| Ruff / formatting | Passed across 226 Python files. |
| Mypy | Passed across 146 source files. |
| Frontend contract generation | `npm run api:types` passed; only the generated declaration changed. |
| Frontend TypeScript | `tsc --noEmit --incremental false` passed. |
| Handoff examples | Public JSON validates against PublicFeedbackReply; TypeScript example compiles against the generated current API contract. |
| OpenAPI comparison | Exactly one new path/operation: 22 paths/24 operations. All previous 23 operations and 33 public schema components remain structurally identical. |

The relevant regression JUnit report contains 24 migration/upgrade/downgrade-named
cases. No migration is introduced or run against the user's real database.
The longest reported individual test phase was 3.53 seconds; these are ordinary
test durations, not a performance benchmark.

An early broad run found a stale 21-path assertion, then was stopped for repair
and the effective-budget change. All four existing inventory assertions were
updated to the intentional additive API count; no legacy wire snapshot,
security assertion or coverage threshold was weakened. The complete selected
set was rerun successfully afterward, with the separate AI lifecycle module
also verified. A full local backend suite and global coverage were not rerun.
Remote CI results must be reported separately from these local results.

## Exact source and documentation inventory

New application modules:

- `backend/app/ai/providers/disabled_evidence_feedback.py`
- `backend/app/api/v1/feedback.py`
- `backend/app/core/feedback_middleware.py`
- `backend/app/core/feedback_settings.py`
- `backend/app/services/feedback_operations.py`

Modified application modules:

- `backend/app/api/dependencies.py`
- `backend/app/core/errors.py`
- `backend/app/main.py`
- `backend/app/services/feedback_release.py`
- `backend/app/services/learner_feedback.py`

New test modules:

- `backend/tests/integration/test_feedback_http_contract.py`
- `backend/tests/integration/test_feedback_http_security.py`
- `backend/tests/unit/test_feedback_application.py`
- `backend/tests/unit/test_feedback_middleware.py`
- `backend/tests/unit/test_feedback_operations.py`

Existing tests with intentional API inventory updates:

- `backend/tests/integration/test_ai_lifecycle.py`
- `backend/tests/integration/test_api.py`
- `backend/tests/integration/test_evidence_feedback_lifecycle.py`
- `backend/tests/integration/test_learner_feedback.py`

Contracts and documentation:

- Updated `backend/openapi.json`.
- Updated generated `src/lib/api/schema.d.ts`, required by the existing CI drift
  check. No handwritten frontend client or UI change.
- Added `docs/api/feedback-openapi.json`.
- Added `docs/frontend-feedback-api.md`.
- Added this report, `docs/architecture/feedback-http-mvp-release.md`.

The genuine existing shared Codex log accompanies the authorized commit. The
four pre-existing app-generated suggestion artifacts are preserved and excluded.
No native final answer is fabricated or manually reconstructed.

## Preservation and remaining release work

No database model, migration, environment file, dependency/lockfile, lesson
definition/hash, evaluator, trusted runtime or retrieval schedule is changed.
The real database and the previously published handoff/reports are preserved.
No live provider, credentials, paid call, support corpus, production publishing,
assignment, competency score or adaptive learning is activated.

Outstanding before calling the complete meeting MVP verified:

1. Sohaib connects the real feedback API on the signed-in learner screen and
   confirms Notes and Tasks reflection in the browser. No such UI call is present
   in this checkout at validation time.
2. Verify the actual shared Supabase/JWKS/Google flow and browser/deployment
   origins. Configured external auth URLs alone do not prove those services work.
3. Review/merge/deploy the feature branch through the team's release process.
   No merge or deployment is performed by this task.

Existing limitations remain: no captured investigation or submitted code patch;
recovery proves chronology rather than diagnosis; unknown assistance remains
unknown; no exact historical Notes parent for Tasks. Cached JWT verification
does not prove instantaneous remote revocation. A final storage snapshot cannot
retroactively revoke bytes after the later CPU/network handoff. Multiple
application processes require separate distributed/edge admission policy.

These are explicit boundaries; they are not silently replaced with mock grading,
invented evidence or claims of production readiness.
