# Current frontend API handoff for Sohaib

Audited on 2 November 2026 against merged main
`1f78ad04cb8a2068b16c973b460d0c94042f16bd` (PRs #14, #16 and #15).
This describes repository implementation, not a verified hosted backend deployment.

## Start here

The backend has **22 paths / 24 HTTP operations**. The existing Notes/Tasks learner
journey is connected in the frontend. Account-only evidence feedback is implemented
in the backend but is **not yet called or rendered by the frontend**.

Use these files together:

- [Current full OpenAPI JSON](api/feedback-openapi.json), identical to
  [`backend/openapi.json`](../backend/openapi.json) and `create_app(...).openapi()`.
- [Feedback integration guide](frontend-feedback-api.md): exact new request,
  response states, citations, security rules, limits and TypeScript example.
- [Original API integration guide](frontend-api-integration.md): detailed request/
  response examples, auth, sequencing and setup for the original 23 operations.
  Its 21-path inventory and internal-only feedback classification are historical.
- [`src/lib/api/schema.d.ts`](../src/lib/api/schema.d.ts): current generated types.
  Use `components["schemas"]["PublicFeedbackReply"]` for feedback.
- [Frontend feature requests](frontend-api-requests.md): proposed future contracts,
  **not additional implemented endpoints**.

The original `docs/frontend-api-integration.md` and `docs/api/openapi.json` are
preserved unchanged. The older copies at repository root are also historical;
use the current full export linked above for new integration.

## Every implemented HTTP operation

All paths below include `/api/v1`. The schema column names the actual generated
Pydantic/OpenAPI types. `Contract` means the required JSON body is exactly `{}`.
`Key` means a required UUID `Idempotency-Key` header. Successful POSTs return the
indicated status; other successful operations return 200 unless noted.

Authentication:

- **Public**: no learner principal required. A malformed/invalid Bearer supplied
  to lesson lookup is still rejected by the router's optional-account dependency.
- **Learner**: owned learner principal from a valid guest cookie or account Bearer.
  The current browser UI requires sign-in for real lessons. The backend retains
  guest support for other clients and explicit historical guest claiming.
- **Account**: valid Supabase access-token Bearer required. A guest cookie is
  insufficient. Never retry an invalid Bearer as a guest.

Every non-read browser action must satisfy the allowed Origin and
`X-Trace-Client: learning-web` checks. The server enforces ownership; a foreign
session/checkpoint is not accessible by knowing its UUID.

| Method and exact path | Auth | Request / Key | Success schema | Frontend use / current integration |
| --- | --- | --- | --- | --- |
| `GET /api/v1/health/live` | Public | None | `LivenessResponse` | Process liveness; no learner action. |
| `GET /api/v1/health/ready` | Public | None | `ReadinessResponse` | Dependency/migration readiness; can return 503. |
| `GET /api/v1/account/me` | Account | None | `AccountResponse` | Account gate and explicit guest-history claim decision; connected. |
| `GET /api/v1/account/me/learner` | Account | None | `AccountLearnerResponse` | Existing account/learner lookup; connected client method. |
| `POST /api/v1/account/claim-anonymous` | Account | `Contract`; Key | `ClaimResponse` | Explicit claim before ordinary learner bootstrap; connected. |
| `POST /api/v1/learners/anonymous` | Bootstrap | `Contract` | `IdentityResponse` | With Bearer, resolves/creates account learner; otherwise guest credential. Connected identity bootstrap. |
| `GET /api/v1/learners/me` | Learner | None | `IdentityResponse` | Read identity before bootstrap; connected. |
| `POST /api/v1/learners/me/revoke` | Learner | `Contract` | 204, no body | Explicit guest revoke; connected client method. Account principals get 409 and must use Supabase sign-out. |
| `GET /api/v1/lessons/{lesson_id}` | Public | Optional `version` query | `LessonResponse` | Notes/Tasks public content; connected. A resumed session must retain its pinned version. |
| `GET /api/v1/learners/me/journey` | Learner | None | `JourneyResponse` | Hub, transfer unlock and retrieval checkpoints; connected. |
| `POST /api/v1/sessions` | Learner | `SessionCreate`; Key | 201 `SessionResponse` | Start a pinned lesson; connected. |
| `GET /api/v1/sessions/{session_id}` | Learner | None | `SessionResponse` | Session metadata; UI normally reads combined progress instead. |
| `POST /api/v1/sessions/{session_id}/abandon` | Learner | `Contract` | `SessionResponse` | Abandon non-completed session; connected client method. |
| `GET /api/v1/sessions/{session_id}/prediction` | Learner | None | `PredictionResponse` or null | Saved prediction; also included in progress. |
| `POST /api/v1/sessions/{session_id}/prediction` | Learner | `PredictionCreate`; Key | 201 `PredictionResponse` | Lock prediction before changes; connected. |
| `GET /api/v1/sessions/{session_id}/attempts` | Learner | None | `AttemptResponse[]` | Saved attempts; also included in progress. |
| `POST /api/v1/sessions/{session_id}/attempts` | Learner | `AttemptCreate` or `TransferAttemptCreate`; Key | 201 `AttemptResponse` | Submit a bounded mapping change, not arbitrary code; connected. |
| `POST /api/v1/sessions/{session_id}/attempts/{attempt_id}/verify` | Learner | `Contract`; Key | `RunResponse` | Execute trusted Notes/Tasks runtime and save verification; connected. |
| `GET /api/v1/sessions/{session_id}/verifications` | Learner | None | `RunResponse[]` | Saved runs/checks; also included in progress. |
| `POST /api/v1/sessions/{session_id}/hints` | Learner | `HintCreate`; Key | 201 `HintResponse` | Real persisted fixture guidance, three request slots; connected. `provider` remains `fake`. |
| `GET /api/v1/sessions/{session_id}/progress` | Learner | None | `ProgressResponse` | Authoritative workspace state and post-mutation refresh; connected. |
| `GET /api/v1/retrievals/{checkpoint_id}` | Learner | None | `RetrievalResponse` | Read owned revisit prompt when allowed; connected. |
| `POST /api/v1/retrievals/{checkpoint_id}/attempts` | Learner | `RetrievalAttemptCreate`; Key | 201 `RetrievalAttemptResponse` | Save revisit answer; connected. |
| `POST /api/v1/sessions/{session_id}/feedback` | Account | `Contract`; **no Key** | `PublicFeedbackReply` | **Backend ready; frontend hookup missing.** Explicit feedback action after a saved attempt, including completed-session reflection. |

All 24 operations above are implemented and exposed. Account-dependent features
remain operationally **PARTIAL** until the shared Supabase configuration and hosted
backend origin are verified. Local/CI fixtures prove code behavior, not Google
OAuth, SMTP, production JWKS availability or deployment readiness.

Request validation, HTTP errors, exact enum values and bounds are in the generated
contract and the linked guides. Shared failures include 401 for authentication,
403 for origin/permission, 404 for absent/foreign records, 409 for lifecycle or
idempotency conflicts, 422 for invalid input and 503 for dependencies. Middleware
can also return 413, 500 or 504. Account and feedback operations have admission
limits and may return 429. Do not assume every route shares the feedback limits
or that OpenAPI lists every middleware-generated error.

## Feedback: the immediate remaining integration

1. Keep the existing account/history-claim flow. Use the current Supabase **access
   token**, not the refresh token, a client-supplied learner ID or a provider key.
2. Add a typed `learningApi.feedback(sessionId)` call in `src/lib/api/client.ts`
   using the existing central request helper, the session feedback path from the
   inventory above, `{}` as the body and `Schema["PublicFeedbackReply"]` as the
   return type. This is an integration instruction; that method does not exist yet.
3. Request feedback from an explicit action after reading saved progress. Do not
   send learner text, client-computed evidence, run results or tutor context.
4. Render the returned availability, notice, present sections and response-local
   citations. Respect `not_ready`, `not_supported` and `unavailable` as normal
   states. Preserve the draft and progress while loading or on error.
5. Label available output as deterministic evidence feedback. Do not reshape it
   into the proposed `TutorReply`, claim live AI, fabricate missing sections or
   expose hidden answers through the UI.
6. Handle 401 through the existing refresh/sign-in path; 409 requires a fresh
   progress read; 429 requires waiting, with no retry loop; 503/504 preserve state
   and offer an explicit retry. Feedback is read-only and does not consume hint
   slots, change completion or create an assignment.
7. Add a signed-in Notes/Tasks browser walkthrough covering first-attempt gating,
   failed/passed evidence, completed reflection and empty/unavailable behavior.
   Existing browser tests do **not** exercise this new feedback screen.

Keep the existing labelled tutor/support/daily demos separate. Globally setting
`NEXT_PUBLIC_AI_MODE=real` does not connect those features: their real adapters
currently reject `EndpointNotAvailableError` without sending HTTP requests.

## Frontend requests that still need backend work

These are availability statements, not promises that proposed paths exist.

| Requested capability | Classification | What exists / what is still needed |
| --- | --- | --- |
| Collection `GET /api/v1/lessons` with UI labels | **NOT IMPLEMENTED** | Only lookup by slug/version exists. The frontend uses `src/content/lessons.ts`. Agree public catalog fields, ordering and eligibility before adding the collection. |
| Optional prediction reasoning | **PARTIAL** | Submission exists; `reasoning` remains required, nonblank, 1–2000 characters. Current UI saves `"No reason written."` for blank input. Decide learning-record semantics before changing validation or historical evidence interpretation. |
| Uniform no-store on every legacy API error | **PARTIAL** | Feedback has all-status no-store; selected legacy handlers set it. Global coverage of every legacy status has not been implemented. Browser requests already use `cache: "no-store"`. |
| `Retry-After` on every 429 | **NOT IMPLEMENTED** | Do not depend on that header. Feedback/account limits currently use the existing error envelope; agree retry metadata before changing it. |
| Concept explanation, free-text tutor ask, stored-run explanation and worked solution | **INTERNAL ONLY** | `LessonAssistantService` and provider-neutral contracts exist. There are no public tutor routes. Need owned-session request construction, answer visibility/assistance recording, eligibility, idempotency/admission policy and a reviewed public contract. The UI's proposed hint-count unlock rule is not server authorization. |
| Support question/RAG API | **INTERNAL ONLY** | `SupportService`, allowlisted retrieval and draft readiness checks exist; no HTTP endpoint or approved production corpus is active. Need document approval/owner/freshness, escalation destination, auth/rate and retention decisions. Draft/demo sources cannot be silently activated. |
| Interest vocabulary and saved interests | **NOT IMPLEMENTED** | No approved product taxonomy, profile storage or get/set HTTP API. Frontend demo choices/local storage are not backend learner records. |
| Today list and three-new-assignment enforcement | **INTERNAL ONLY** | Contracts, explicit local-day arithmetic and a deliberately blocked readiness service exist. No authoritative learner timezone, atomic assignment store or public scheduler. Define timezone authority/change behavior, assignment semantics, persistence and release eligibility first. |
| Generated exercise retrieval and delivery | **INTERNAL ONLY** | Strict generation/composition, runtime validation and candidate provenance/lifecycle exist. Unassigned blueprint candidates are not learner catalog entries; `release_eligible` remains false. Approval, release, assignment and owned public retrieval require a separate milestone. |
| Custom lesson creation/status/list | **NOT IMPLEMENTED** as a public product | No public creation job, worker/status API or ready-to-learn custom lesson delivery. The internal candidate pipeline is not that feature. Keep the form disabled until an approved contract and release process exist. |
| Live AI generation, tutoring or support | **NOT IMPLEMENTED** | No approved live provider adapter is active. Provider, exact models, credential variable name and spending cap still need team approval. No frontend credential can enable this. |

Do not create success-shaped placeholder endpoints for these screens. A working
screen can retain an honest labelled demo or unavailable state until its backend
milestone is implemented and validated. Keep the existing +1/+7 retrieval schedule;
it is separate from the proposed new-assignment quota.

## Configuration and sequencing

Use the setup commands and complete variable-name list in the original guide.
The usual local API origin is `http://127.0.0.1:8000`; use the same loopback host
consistently for browser, cookies and CORS. Production needs a separately verified
HTTPS backend origin: a Vercel frontend deployment alone does not deploy FastAPI.
This machine's `NEXT_PUBLIC_API_BASE_URL` currently selects a loopback server.
That is suitable for local development; it does not establish a hosted backend
address for Sohaib or Vercel. The hosted API origin and its CORS allowlist still
need to be confirmed by the team. No configuration values are included here.

Frontend variable names are `NEXT_PUBLIC_API_BASE_URL`,
`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` and
`NEXT_PUBLIC_SITE_URL`; `NEXT_PUBLIC_AI_MODE` controls only the labelled demo
adapters. Never put a Supabase service-role key or provider credential in a
`NEXT_PUBLIC_*` variable.

Backend auth uses `TRACE_SUPABASE_URL`, `TRACE_SUPABASE_ISSUER`,
`TRACE_SUPABASE_JWKS_URL` and `TRACE_SUPABASE_AUDIENCE`, plus
`TRACE_CORS_ORIGINS`. Database/cookie settings and local startup are documented in
the original guide. Feedback's separate `TRACE_FEEDBACK_*` process settings and
their dotenv limitation are documented in the feedback guide. No new frontend
secret or live-provider configuration is needed for deterministic feedback.

Current client timeout is 35 seconds; the default general server request budget
is 30 seconds and verification budget 10 seconds. Feedback is shorter: 8 seconds
total and 2 seconds optional provider wait, bounded by the general settings.
Transport/504 uncertainty on a legacy write requires a fresh progress read and
replay with the **same** key; no new key that might duplicate the action. A timed
out worker may still finish, so a client abort is not proof of rollback.

Order: verify backend origin/auth/CORS and database readiness; preserve claim
choice; exercise signed-in Notes, Tasks and retrieval; integrate feedback through
the existing API client; then agree separate tutor/support/catalog milestones.
Personalization, daily assignment and generated/custom delivery follow their
policy, persistence and release prerequisites.

## CI and audit evidence

PR #15 was merged as `1f78ad04cb8a2068b16c973b460d0c94042f16bd`.
Its earlier PR run passed both backend jobs and failed seven browser tests.
PR #16 (`2c9da1d9ccd5a3d2e1fff9d4c0895ea3e6111bc5`, merge `aceda2130f194510d99c3413b325e9a063685173`)
supplied the repair: Bearer headers on direct protected test requests, separate
guest/account hub expectations and shared fixture-clock cleanup/reset. Production
authentication and JWT-expiry enforcement were not weakened.

The combined-main [quality run](https://github.com/Sohaib7932/trace/actions/runs/41449851907)
completed successfully on 2 November at 13:18 UTC (18:18 PKT). Frontend checks
passed: **134 component/unit tests, 58 browser tests passed and 4 existing browser
tests skipped**. Windows and Ubuntu each passed **3,271 backend tests**, Ruff,
formatting (226 files), mypy (146 source files), migration and schema checks.
Both full-suite coverage results are **97.34%**, with the existing threshold
unchanged. Windows pytest took 712.27 seconds; Ubuntu took 373.26 seconds.
A fresh local Windows run passed **97 focused feedback API/security tests** in
43.07 seconds using disposable fixtures. The application schema was independently
compared with both current full JSON exports; all matched at 22 paths / 24
operations. These full-suite results belong to merged main at the audited commit;
this handoff adds only documentation and the genuine shared session log.
This does not establish a real hosted sign-in or a feedback browser walkthrough.
