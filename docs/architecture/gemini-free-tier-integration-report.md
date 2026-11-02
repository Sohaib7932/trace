# Gemini integration: implementation and validation

Date: 2 November 2026. Branch: `codex/gemini-free-tier-integration`.
Starting commit: `75b41d1968ea06d880be1726ae2e0a0bcbaf0ed2`.
Implementation was validated before publication. The owner subsequently authorized
commit and push on this feature branch. No merge or deployment is authorized.

## Implementation and availability

| Capability | Implemented boundary | Availability |
| --- | --- | --- |
| Gemini transport | Official `google-genai` 2.34.0; application-owned shared bounded client; exact approved model | Real provider exercised with public/synthetic inputs |
| Lesson tutor | Account-only owned-session question API; fresh authorization before/after provider; approved explanatory text selection | Exposed and connected to existing frontend panel |
| Support RAG | Protected account API; reviewed fixed corpus; bounded lexical retrieval; exact source quotations | Exposed and connected to existing Trace Help panel |
| Challenge generation | QuestionGenerator -> admission -> trusted composition -> candidate persistence -> runtime validation | Internal only; real Tasks candidate validated in a disposable database |
| Evidence feedback | Existing endpoint, policies and projections preserved | Live Gemini feedback remains disabled |
| Generated lesson delivery | No new public generation/review/publication/assignment endpoint | Not implemented by this block |

The provider does not grade, create verification evidence, change completion,
release solutions or alter session progress. The pilot tutor selects a finite
approved guidance identifier; trusted code supplies the text. Support selects
retrieved passage identifiers and returns exact quotations. Neither is unrestricted
model-authored chat. Full worked solutions stay disabled in real frontend mode.

## Actual APIs and handoff

- `POST /api/v1/sessions/{session_id}/tutor/ask`, body `{"question":"..."}`,
  1–400 characters. Valid account access-token Bearer, active learner role,
  owned pinned Notes/Tasks session; foreign/missing sessions return the same 404.
- `POST /api/v1/support/ask`, body `{"question":"..."}`, 1–500 characters.
  Valid account access-token Bearer and learner role. No learner-history bootstrap,
  private account retrieval, client-selected documents or conversation persistence.

Both enforce allowed browser Origin, `X-Trace-Client: learning-web`, bounded
input/output, account admission, concurrency, HTTP deadlines, sanitized errors and
`Cache-Control: no-store`. Responses include honest unavailable states; no provider
failure is replaced by a fixture answer. Existing fixture hints remain separate.

The [frontend guide](../frontend-gemini-integration.md) contains complete examples,
error meanings, call sequencing, configuration names and internal-only boundaries.
The [new OpenAPI export](../api/gemini-openapi.json) matches `backend/openapi.json`:
24 paths / 26 operations. All previous 24 operations and public schemas are
unchanged. Generated TypeScript types and API-client adapters are updated.
The four documented JSON examples were validated against the actual schemas.

## RAG sources and approval

The owner approved the exact nine articles / 19 passages and a 30-day pilot review
window. Review: 2 November 2026 15:34:07 UTC; expiry: 2 December 2026 15:34:07 UTC.
The [review record](../support-corpus-review.md) lists every source and scope.

Source IDs: `trace-overview`, `registration-authentication`,
`google-authentication`, `learning-navigation`, `prediction-attempts-verification`,
`hints-explanations`, `progress-retrieval`, `daily-availability`, `technical-problems`.

Only `backend/app/support/corpus.json` is loaded. Source review, canonical digests,
expiry, identifier integrity and customer-safe text are rechecked on use and after
the provider call. No filesystem crawl, agent logs, environment files, private
implementation documents, learner submissions or model-selected paths are allowed.
The old support drafts remain unapproved historical documents. There is no approved
human escalation contact; no contact or SLA was invented.

## Live Gemini evidence

Eight bounded provider attempts were made, using the approved
`gemini-3.5-flash-lite` and privately loaded `GEMINI_API_KEY`:

1. Three-attempt CLI check: tutor answered with approved text; initial support
   returned unavailable; generation produced a technically validated Tasks
   candidate with pending review and `release_eligible=false`.
2. One explicit bounded support diagnostic retry succeeded and cited
   `progress-retrieval`. The initial failure's category was not retained; it is
   not asserted to be a specific infrastructure or quota error.
3. Two real-provider calls through actual protected FastAPI handlers succeeded:
   tutor and support HTTP 200, `source: "ai"`, no-store. Support quotations exactly
   matched approved source passages. Foreign-session access returned 404 and
   unauthenticated support returned 401 without additional provider calls.
4. After the final provider-timeout and run-order repairs, the same two-call
   protected HTTP check passed again with exact source quotations and the same
   404/401 ownership/authentication outcomes.

HTTP validation used a synthetic signed account, injected trusted test JWKS and a
disposable database. It does not prove hosted Supabase/Google OAuth operation.
Browser journeys used deterministic, visibly labelled fixture providers, not a
live model. These are separate forms of evidence.

No billing was activated or paid fallback configured. Free-project status is the
owner's attestation, not independently queried Google Billing information. Local
accounting records zero cost and never claims to prove Google's billing state.
SDK and application automatic retries are disabled; no other model was selected.

## Database readiness and preservation

The authorized existing migrations 0005–0007 upgraded the real local development
database from `0004_transfer_retrieval` to `0007_tutor_reservations`. The previous
backup was confirmed first, and a fresh SQLite backup was made before upgrade:

`<local Codex artifact directory>/trace-authorized-upgrade-2ulwo98o/before.sqlite`

Existing row fingerprints/counts were preserved, `PRAGMA integrity_check` returned
`ok`, the foreign-key check was empty, Alembic's model check passed, and backend
readiness returned HTTP 200. Integrity and head were checked again after tests.
No new migrations, migration edits, reset, database recreation or learner deletion
were introduced. Test migrations and generated candidates used disposable databases.

## Validation

Final complete backend run: **3,387 passed in 688.19 seconds**, with **96.93%**
branch-inclusive coverage. External network was disabled except loopback fixtures.
Compared with merged main's recorded 3,271 tests / 97.34% coverage, this adds 116
tests and reduces the coverage percentage by 0.41 points. New defensive adapter
and HTTP paths are not yet exhaustively covered; coverage preservation is not
claimed. The existing 85% gate and security assertions were not lowered.

- Final combined transport/client/API/lifecycle/architecture focus: 167 passed.
  Transport security covers exact destination/model pinning,
  redirect rejection, no tools/executable output, bounds, timeouts and safe failures.
- Protected tutor/support final focus: 38 passed, including the actual
  Notes-to-Tasks completion journey and deterministic cancellation/worker ownership.
- Candidate generation focus: 7 passed over both production blueprint families,
  all five runtime evidence checks, persistence, idempotency and local concurrency.
- Initial transport/client/resources focus: 106 passed.
- Support-source and API/lifecycle focus: 85 passed.
- Frontend standard `npm test`: 140 passed. A serial full run also passed 140.
- Existing learner/auth Playwright suite: 58 passed, four pre-existing skips.
- New desktop/mobile real-adapter HTTP suite: four passed with labelled fixtures.
- Production frontend build passed; ESLint and `npm run typecheck` passed.
- Ruff and formatting passed across 245 Python files; mypy passed 160 source files.
- OpenAPI legacy-operation/schema comparison and whitespace checks passed.

The final full suite includes all 50 Gemini transport tests, 38 protected API
tests, 21 corpus tests and seven candidate pipeline tests. Existing migration,
ownership, evidence integrity, tutor concurrency and Notes/Tasks runtime suites
were included, without new skips. Test XML and coverage JSON are retained in the
local `gemini-final-verified-20261102` validation artifact directory.

The first full backend attempt exposed a service importing a concrete provider
and a timing-dependent timeout test. Dependency injection now constructs the
adapter. Separate deadline and event-gated cancellation tests preserve both
guarantees. A frontend loading assertion now uses a controlled provider gate
instead of racing a short timer. Accessibility assertions select the visual alert
instead of ambiguously matching its screen-reader announcement too.

Final review also wired per-operation provider-timeout caps into the shared client
without changing the existing internal support dependency. The Tasks journey
exposed an actual tied-timestamp ordering defect: random UUID order could select
an older failed attempt. Tutor context now uses trusted attempt numbers and omits
a latest-outcome claim if tied records remain ambiguous. The regression fixes run
UUIDs in the opposite order and verifies failed then successful guidance.

A Windows generated-build cleanup failed with EPERM. Existing output was preserved,
then a fresh build and all browser tests passed. No application configuration was
changed to work around it. The CI workflow now includes the dedicated AI adapter
browser suite; remote CI was not part of the local validation recorded here.
The repository-authorized Next.js feedback lookup failed even after its requested
network retry, so no feedback was submitted. This did not block application checks.

## Local configuration and handoff

The key was privately supplied in a nested `backend/backend/.env.gemini`. It was
copied into the expected `backend/.env.gemini` after confirming the destination
contained only this task's blank placeholder. The original was preserved. Both
files are ignored by Git; neither key nor environment contents are reproduced here.
Actual backend `.env` and frontend `.env.local` were not changed.

Use the blank `backend/.env.gemini.example` on another machine; configure the real
key privately. Start from the repository root:

```powershell
.\scripts\run-gemini-backend.ps1 -ConfirmFreeTierProject
```

For the frontend, retain the shared Supabase public settings and matching local
origins; start/build with `NEXT_PUBLIC_AI_MODE=real`. The provider key belongs only
on the backend. The launch helper sets the approved model, zero paid budget,
no retries and a 20-attempt process ceiling. Default application mode remains
disabled; default frontend mode remains explicitly labelled mock.

At handoff, the validated Gemini backend is running on `http://127.0.0.1:8000`
and the existing frontend is running in real-adapter mode on
`http://127.0.0.1:3000`. Backend readiness and frontend sign-in both returned 200.
The running OpenAPI matched the export exactly; unauthenticated support returned
401 with no-store. Frontend auth fields are present and match the backend's
Supabase project, without printing their values. Hosted sign-in/OAuth was not
exercised with a real person's account.

Limits are process-local, not distributed usage/billing enforcement. They reset
on restart. The backend cannot prove billing state. Synchronous provider work
retains its worker permit after a cancelled HTTP request until it actually exits.
Pattern-based secret/PII guards are supplementary, not complete detection.

## Remaining work and release boundary

- Generated candidates still need separately authorized human review/approval,
  delivery and assignment integration. Technical validation never publishes them.
- The tutor is a bounded approved-guidance pilot, not unrestricted tutoring.
- Support retrieval is bounded lexical retrieval, not an embedding/vector service.
- Support review must be renewed before expiry; human escalation has no destination.
- No hosted deployment, production load validation, distributed quota or billing
  verification was performed. Real hosted auth/OAuth operation was not tested here.
- Daily assignments, interests, competency scores, leaderboard, GitHub integration
  and UI redesign remain outside this block. +1/+7 retrieval behavior is unchanged.
- At validation completion no commit or push had been performed; the owner later
  authorized feature-branch publication. No PR creation, merge or deployment is
  included in that authorization. Shared logs and
  unrelated user work remain intact. The separate handoff commits `e70aefd` and
  `75b41d1`, and merged PRs #15/#16, were preserved.

## Working-tree file inventory

This includes the resumed Gemini work and the changes completed in this block.
This inventory was captured before staging. Private ignored credentials/databases and generated build/test
artifacts are excluded from this shareable inventory.

Modified tracked implementation/documentation files:

- `.github/workflows/quality.yml`
- `.gitignore`
- `backend/app/ai/client.py`
- `backend/app/ai/providers/bounded_support.py`
- `backend/app/ai/resources.py`
- `backend/app/api/dependencies.py`
- `backend/app/core/ai_settings.py`
- `backend/app/core/feedback_middleware.py`
- `backend/app/main.py`
- `backend/app/services/feedback_operations.py`
- `backend/app/services/support.py`
- `backend/openapi.json`
- `backend/pyproject.toml`
- `backend/tests/integration/test_ai_lifecycle.py`
- `backend/tests/integration/test_api.py`
- `backend/tests/integration/test_evidence_feedback_lifecycle.py`
- `backend/tests/integration/test_learner_feedback.py`
- `backend/uv.lock`
- `src/components/learning/tutor/tutor-panel.tsx`
- `src/components/support/trace-help.tsx`
- `src/lib/ai/client.ts`
- `src/lib/ai/contracts.ts`
- `src/lib/api/client.ts`
- `src/lib/api/schema.d.ts`
- `tests/components/ai-surfaces.test.tsx`

New implementation/documentation files:

- `backend/.env.gemini.example`
- `backend/app/ai/providers/gemini.py`
- `backend/app/ai/providers/guided_lesson_assistant.py`
- `backend/app/api/v1/support.py`
- `backend/app/api/v1/tutoring.py`
- `backend/app/core/ai_privacy.py`
- `backend/app/core/support_settings.py`
- `backend/app/core/tutor_settings.py`
- `backend/app/schemas/lesson_tutoring.py`
- `backend/app/schemas/support_http.py`
- `backend/app/services/candidate_generation.py`
- `backend/app/services/lesson_tutoring.py`
- `backend/app/support/__init__.py`
- `backend/app/support/corpus.json`
- `backend/app/support/knowledge.py`
- `backend/scripts/check_gemini.py`
- `backend/tests/fixtures/live_ai_e2e_server.py`
- `backend/tests/integration/test_gemini_candidate_pipeline.py`
- `backend/tests/integration/test_live_ai_http.py`
- `backend/tests/unit/test_gemini_transport.py`
- `backend/tests/unit/test_support_corpus.py`
- `docs/api/gemini-openapi.json`
- `docs/architecture/gemini-free-tier-integration-report.md`
- `docs/frontend-gemini-integration.md`
- `docs/support-corpus-review.md`
- `playwright.ai.config.ts`
- `scripts/run-gemini-backend.ps1`
- `tests/ai-e2e/live-ai.spec.ts`
- `tests/components/live-ai-adapters.test.ts`

Shared logs preserved separately: 5 existing modified/untracked files.
