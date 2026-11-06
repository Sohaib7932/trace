# Trace frontend API integration handoff

> **Production transport review candidate:** the current backend export is
> **54 paths / 60 operations**. The proposed production browser client uses
> same-origin `/api/v1` through a fixed-destination server-only relay; local
> development keeps its existing direct API configuration. It is not yet
> production-accepted. Preview deployments fail closed and do not call Render.
> See [production integration and release gates](deployment/production-integration.md)
> for cookie behavior, runtime requirements and the still-failing HTTPS probe.
> The dated handoff below is retained as historical documentation.

> **Current PR #26 integration contract (4 November 2026):** the combined application
> exposes **53 paths / 58 operations**, including Custom Lessons, Private Learning
> Guides and GitHub Project Learning. The authoritative current exports are
> [backend/openapi.json](../backend/openapi.json) and
> [generated TypeScript declarations](../src/lib/api/schema.d.ts).
> Sections 1–11 and `docs/api/openapi.json` below are the explicitly dated original
> 21-path handoff, not the current API inventory. Section 12 documents the added
> Custom Lessons APIs; see the [GitHub App guide](frontend/github-app-project-learning.md)
> for owner configuration and the Project Learning flow. See the
> [PR #26 repair evidence](reports/pr-26-integration-repair.md) for compatibility
> validation and remaining live-authorization requirements.

For Sohaib. Audited against commit `fc5b1d1e44fc4030db289bbfe17f4bec559ecc8a` on
`feat/phase-3-5a-engineering-evidence`, 2 November 2026. This is the backend
contract at that commit, not a claim about what is deployed on a remote server.

## 1. What can be integrated now

The actual FastAPI application exposes **21 API paths and 23 operations**:
18 learner operations, three account operations and two health operations.
The generated [OpenAPI export](api/openapi.json) exactly matches both
`create_app(...).openapi()` and the existing `backend/openapi.json`.
The export was generated without starting the lifespan, opening a learner
database or contacting Supabase or an AI provider.

Availability terms used throughout this document:

| Classification | Meaning |
| --- | --- |
| READY | Implemented, exposed through HTTP and usable by the frontend once the documented local database/configuration prerequisites are met. |
| PARTIAL | HTTP functionality exists, but a named operational dependency or capability is unavailable or unverified. |
| INTERNAL ONLY | Backend implementation exists, but no public HTTP endpoint exposes it. |
| NOT IMPLEMENTED | No working implementation of the named feature exists. |

| Feature | Classification | Actual boundary |
| --- | --- | --- |
| Guest learning, Notes, Tasks transfer, verification, persisted progress | READY | Real deterministic runtimes; requires migrated/seeded SQLite. |
| Journey and retrieval/revisit | READY | Existing +1/+7-day checkpoints after Tasks completion. |
| Fixture hints | READY | Three request slots per session; explicitly `provider: "fake"`. |
| Account inspection and explicit guest-history claim | PARTIAL | HTTP implementation exists; needs matching Supabase asymmetric JWT configuration. Real shared-project authentication has not been verified in this audit. |
| Google sign-in, confirmed-email registration and recovery | PARTIAL | Existing frontend Supabase flows; external provider, redirects and email delivery must be configured and verified. These are not Trace backend login endpoints. |
| Live model tutoring or explanations | NOT IMPLEMENTED | No approved live transport or provider SDK is active. Fixture hints are not live AI. |
| Typed lesson specification, trusted blueprints, generation/admission/composition/validation and candidate lifecycle | INTERNAL ONLY | Do not create frontend requests to these services. Technical validation does not imply production approval or learner assignment. |
| Engineering Evidence V1 and evidence-grounded feedback | INTERNAL ONLY | Backend evidence/feedback services; no public evidence-feedback or grading endpoint. |
| Phase 3.5C.1 release authorization and Phase 3.5C.2 public projection/facade | INTERNAL ONLY | Fresh authorization, source fences and safe public-shaped data are implemented internally. Production visibility remains disabled. A public-shaped schema does not make it an HTTP API. |
| LessonAssistant and SupportAssistant | INTERNAL ONLY | Shared disabled/mock infrastructure exists. Support has no approved production corpus/escalation destination and is unavailable by default. |
| Daily challenge assignment, three-new-exercises quota enforcement | NOT IMPLEMENTED | Readiness contracts exist; no active assignment HTTP API, authoritative timezone policy or quota enforcement. |
| Personalized generation, competency scoring, mastery/adaptive progression | NOT IMPLEMENTED | Evidence/readiness proposals do not enable these product features. |
| General lesson collection, arbitrary source-code upload/run, creator/publication UI APIs | NOT IMPLEMENTED | Use the two existing lesson IDs and bounded mapping contracts below. |

## 2. Local setup and configuration

Requirements from the locked project: Python 3.13.x, uv, Node 24.x/npm.
Use the existing lockfiles. From the repository root, the frontend uses
`npm ci` and `npm run dev`.

In a separate terminal, from `backend/`:

```powershell
uv sync --locked
# Create .env from .env.example only if .env does not already exist.
# Inspect and preserve existing configuration; never overwrite it blindly.
uv run --locked alembic upgrade head
uv run --locked python -m scripts.seed
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload --no-access-log
```

These are developer setup instructions; this audit did not execute migrations,
seeding, dependency installation or database writes. Startup does not create
tables, migrate or seed. Readiness checks database connectivity and exact Alembic
heads; it does not prove lessons are seeded or Supabase/Google/AI is available.
Seeding publishes the two existing legacy lessons idempotently and rejects
changed published content.

Default local frontend origins are `http://localhost:3000` and
`http://127.0.0.1:3000`. Use the **same hostname** for frontend and API:

- Frontend `http://localhost:3000` -> API `http://localhost:8000`.
- Frontend `http://127.0.0.1:3000` -> API `http://127.0.0.1:8000`.

The base URL is the API origin, without `/api/v1`. The existing client adds that
prefix. No verified production/backend deployment URL is supplied by this audit.
Cross-site deployments need a separate cookie/deployment review: CORS alone does
not override `SameSite=Lax` or browser third-party-cookie restrictions.

### Configuration names, never project credentials

Root `.env.local` is frontend configuration. `backend/.env` is backend
configuration. Do not put private keys in `NEXT_PUBLIC_*` variables.

| Variable names | Requirement/purpose |
| --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | Optional API-origin override; otherwise the browser client uses its current hostname on port 8000 over HTTP. Set deliberately for any hosted deployment. |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_SITE_URL` | Required together for existing account UI. Use the approved project's public publishable key, not a service-role/private key or a legacy JWT key. Site origin must agree with the browser/callback origin. |
| `TRACE_DATABASE_URL` | Backend SQLite SQLAlchemy URL; relative database paths resolve from `backend/`, independently of shell cwd. Never send this to the frontend. |
| `TRACE_COOKIE_SECURE`, `TRACE_ALLOW_INSECURE_LOCAL_COOKIES` | Secure cookies are the default. Local plain HTTP requires the explicit non-Secure-cookie opt-in shown in `backend/.env.example`; that mode permits loopback frontend origins only. Keep Secure cookies for public HTTPS. |
| `TRACE_CORS_ORIGINS` | Explicit JSON array of allowed origins, without paths or wildcards. Default local origins are listed above. Both CORS and write-origin enforcement use it. |
| `TRACE_SUPABASE_URL`, `TRACE_SUPABASE_ISSUER`, `TRACE_SUPABASE_JWKS_URL` | Optional for guest-only use; all three must be configured together for accounts, for the same approved project. Issuer must be the configured root plus `/auth/v1`; JWKS must be issuer plus `/.well-known/jwks.json`. Hosted projects require HTTPS. |
| `TRACE_SUPABASE_AUDIENCE`, `TRACE_AUTH_JWKS_CACHE_SECONDS`, `TRACE_AUTH_ALLOW_INSECURE_LOOPBACK` | Auth audience, bounded public-JWKS cache and explicit test/local HTTP exception. Do not enable an insecure exception for hosted auth. |
| `TRACE_CREDENTIAL_LIFETIME_SECONDS` | Guest credential lifetime, default 30 days; relevant to +7-day return access. |
| `TRACE_ENVIRONMENT`, `TRACE_LOG_LEVEL` | Supported environment modes are development/test; this is not a production-hardening switch. |
| `TRACE_DATABASE_TIMEOUT_SECONDS`, `TRACE_REQUEST_TIMEOUT_SECONDS`, `TRACE_MAX_REQUEST_BYTES`, `TRACE_VERIFICATION_TIMEOUT_SECONDS` | Bounded backend database/request/runtime limits. Default request limit is 65,536 bytes, request timeout 30 seconds, verification timeout 10 seconds. |
| `TRACE_AI_PROVIDER` | Existing learner hint selection supports fake only. No live provider credentials are required. |
| `TRACE_LLM_MODE` | Separate internal shared AI infrastructure defaults to disabled. Mock mode requires an injected test transport; changing an environment variable alone does not activate a provider and can fail startup. Leave it disabled for normal integration. |

Defaults and relationships above are public code facts, not values read from
either developer's real environment files. Other bounded `TRACE_LLM_*` settings
are internal configuration, not frontend requirements. No provider/model selection
or credential should be invented to start the learner application.

### Documentation URLs

At the chosen API origin:

| Method/path | Purpose, auth and response |
| --- | --- |
| `GET /openapi.json` | READY; unauthenticated generated OpenAPI JSON. |
| `GET /docs` | READY; unauthenticated Swagger HTML. |
| `GET /redoc` | READY; unauthenticated ReDoc HTML. |
| `GET /docs/oauth2-redirect` | READY; framework Swagger redirect HTML, **not** the application's Supabase callback. |

These four framework documentation routes also accept `HEAD`; they are excluded
from OpenAPI and the 21-path/23-operation API count. CORS preflight `OPTIONS` is
middleware, not another business operation. Documentation GETs have no request
body/parameters, are retryable and may encounter the common middleware failures
below. Swagger writes still need the allowed Origin and Trace client header;
the schema does not declare every header enforced by dependencies. The actual
Supabase callback is the existing **Next.js** `/auth/callback` route.

## 3. Authentication and identity

### Guest flow

1. `POST /api/v1/learners/anonymous` with `{}` and browser credentials enabled.
2. The backend sets opaque `trace_learner`: HttpOnly, `SameSite=Lax`, path
   `/api/v1`, Secure by default. JavaScript must not read or store the credential.
3. `GET /api/v1/learners/me` confirms identity; call bootstrap on return as well
   to renew a still-valid credential in the latter half of its lifetime.
4. Session/journey/retrieval calls use the cookie with `credentials: "include"`.

Only a digest is stored server-side; the raw guest token is never a JSON field.
Learner/session UUIDs are references, not credentials. Bootstrap with a valid
cookie reuses the learner. An expired/revoked/missing credential creates a **new**
guest on bootstrap; it does not recover old history. A missing/expired credential
on protected reads returns 401. Expiry/revocation does not delete stored records.

`POST /api/v1/learners/me/revoke` revokes a guest and clears the cookie, returning
204 with no JSON. Account sign-out instead uses Supabase's existing frontend
sign-out flow; the guest revoke endpoint returns 409 for an account principal.

### Signed-in flow

Use the existing `src/lib/supabase/` integration and Supabase SDK for Google OAuth,
email/password registration/sign-in, confirmation, recovery and token refresh.
Trace has no signup, login, refresh, Google-exchange or account logout endpoint.
Send the Supabase **access token**, not an ID/refresh token:

```http
Authorization: Bearer <access_token supplied by the configured Supabase SDK>
```

The backend verifies ES256/P-256 or RS256/RSA public-JWKS signatures, exact issuer
and audience, canonical UUID subject, expiry/issued-at/not-before rules, and
`role: authenticated`. Anonymous-provider tokens are rejected. HS256/shared-secret
tokens are not supported. Local account identity and roles are authoritative;
email or caller-supplied role metadata cannot grant permissions. A newly trusted
subject receives a local learner role. Disabled accounts or missing learner
permission return 403.

A supplied malformed, expired or invalid Bearer token returns 401; it never
silently falls back to the guest cookie, including on lesson lookup/bootstrap.
Blank account auth configuration or an unavailable JWKS dependency returns 503.
Incomplete/inconsistent URL, issuer or JWKS configuration fails application
startup validation instead of producing a working HTTP service. A request cannot
carry multiple Authorization headers. A valid Bearer
takes precedence over a guest cookie. Use SDK refresh/sign-in after 401 rather
than removing the header and accidentally acting as a different guest.

JWT verification uses bounded cached public keys; it does not make an online
provider revocation check on every request. Do not promise instantaneous remote
session revocation. Do not log tokens, cookie headers or auth response payloads.

### Critical guest-history claim sequence

After sign-in, **inspect the account before calling authenticated learner APIs**:

1. `GET /api/v1/account/me` with Bearer **and** browser cookie included.
2. If `anonymous_history_available` is true and `learner_id` is null, offer
   explicit history claiming before learner bootstrap/journey/session calls.
3. On acceptance, `POST /api/v1/account/claim-anonymous` with `{}`, the same cookie,
   Bearer and one stable UUID idempotency key. Success returns the claimed
   `learner_id`, revokes guest credentials and clears the cookie.
4. Refresh account and journey after claim. If the user declines, only then begin
   a new permanent learner through the ordinary authenticated learner flow.

`GET /account/me` and `/account/me/learner` inspect without creating a learner
mapping. Conversely, authenticated `current_learner` resolution calls
`accounts.learner()` and may create one. Creating a new account learner first can
make later claiming a different guest learner conflict. There is **no automatic
history merge**, email-based linking or recovery from a lost/expired guest cookie.
If an account already owns different learner history, claim returns 409 and
preserves both histories. Repeating a successful claim with the same key returns
its receipt even after the cookie was cleared.

## 4. Shared wire contract and error handling

All application routes below start with `/api/v1`. All bodies use
`Content-Type: application/json`; requests reject unknown fields. Send `{}` where
the required body is `Contract`, even if no business fields are needed.

Authentication abbreviations in the inventory:

- **Public**: no learner credential required. Supplying invalid Authorization on
  learning/catalog routes still fails; health routes do not process it.
- **Learner**: valid guest cookie OR valid account Bearer with local learner role.
- **Account**: valid account Bearer; guest cookie alone is insufficient.

All learner session/attempt/checkpoint IDs are checked against the current
learner; a foreign or missing resource returns 404. UUID path/header values are
validated; bad formatting is 422. Authenticated learner routes may create the
account's learner mapping as described above. Role grants have no public API.

### Required headers and CORS

Every learning/account **POST**, including Bearer-only requests, requires:

- Browser `Origin` exactly in `TRACE_CORS_ORIGINS` (browser sets it; do not try to
  forge it in frontend JavaScript).
- `X-Trace-Client: learning-web`.
- JSON body and content type.
- A UUID `Idempotency-Key` for operations marked **Key** in the inventory.

Use `credentials: "include"` on guest and account calls, especially claim. CORS
allows GET/POST and `Content-Type`, `Authorization`, `X-Request-ID`,
`X-Trace-Client`, `Idempotency-Key`; credentials are allowed and `X-Request-ID` is
exposed. All responses receive a safe request ID. Preserve that ID for debugging
without recording private payloads. Write-origin enforcement also protects
non-browser calls; a CLI must supply an approved Origin deliberately.

Use `cache: "no-store"` and avoid persistence/shared caching of owned responses.
The dependency marks successful learning/account responses no-store, but generated
error responses do not uniformly retain that header. Do not assume every HTTP
status has a backend no-store guarantee; all-status ingress hardening is future work.

### Common errors (apply to every inventory row)

All application errors use `ErrorResponse`:

<!-- schema: ErrorResponse -->
```json
{"error":{"code":"validation_error","message":"Request validation failed.","request_id":"frontend-example-1","details":[{"location":["body","unexpected"],"code":"extra_forbidden","message":"Invalid value."}]}}
```

| HTTP | Code(s) | Frontend action |
| --- | --- | --- |
| 401 | `unauthenticated` | Refresh/sign in, or explicitly restart guest identity; preserve drafts and do not pretend old history belongs to a new guest. |
| 403 | `unsafe_request`, `forbidden` | Check Origin/client header or account status/roles. Do not loop retries. |
| 404 | `not_found` | Resource absent or not owned. Hide inaccessible data and offer journey navigation. |
| 409 | `conflict`, `invalid_state`, `hint_limit` | Refresh persisted progress; resolve sequencing/idempotency/quota conflict. Do not generate new keys blindly. |
| 422 | `validation_error`, `unsupported_change` | Correct request/header/path fields; use `details[].location/code`, not raw submitted values. |
| 429 | `rate_limited` | Account inspection/claim limit; stop retry bursts. No `Retry-After` header is implemented. |
| 503 | `dependency_unavailable` | Database/auth dependency unavailable; preserve drafts and retry deliberately. A write may have partially completed. |
| 413 | `request_too_large` | Reduce request body; do not retry unchanged. |
| 504 | `request_timeout` | Outcome may be uncertain; read saved progress then replay the same logical operation/key. |
| 500 | `internal_error` or generic internal failure | Show a generic recoverable error and request ID; never treat as learner failure. |
| 405 | `method_not_allowed` | Wrong HTTP method. |

The 413/504/500 middleware cases can affect all routes even where OpenAPI does not
list them. Router-level error listings are broad, not proof that each endpoint
uses every listed status. In particular there is no active general learner rate
limiter or daily exercise quota. The **account** service enforces 30 inspections
per account per aligned UTC minute (both GETs share `inspect`) and 30 claims per
account per aligned UTC minute, including failed claim requests.

### Mutation/retry rules

Generate a UUID once per logical user action and retain it with that pending
request. Reuse both key and body after transport uncertainty. Changing content
under a saved key is a 409. A deliberate new correction uses a new key.

| Operation | Retry contract |
| --- | --- |
| GETs | Safe to retry; account inspection retries still count toward its rate limit. |
| Guest bootstrap | Reuses a valid cookie. A lost initial response/cookie may produce a new guest; it has no idempotency key. |
| Create session | Same learner/key/version returns the original session, even if its state advanced. A fresh key creates a distinct session; inspect journey before starting another. |
| Prediction | Immutable; exact same key/selection/reasoning replays. Another submission conflicts. |
| Attempt | Exact same key/field/explanation replays. No new attempt while verification is pending. |
| Hint | Same key/context replays a finalized result. Pending/concurrent work may return 409; inspect progress and retry that same operation. An error result consumes a slot and is not rerun by replaying its key. |
| Verify | Same key replays the saved run. A passed/failed result is reused even with a new key. To retry an infrastructure `error`, inspect progress then use a new key deliberately. Pending work can return 409. |
| Retrieval answer | Exact replay works even after completion; new answers are allowed only while due. |
| Claim | Same successful key replays the saved receipt after cookie clearing. Different history/key conflicts are not merges. |
| Abandon | Already abandoned is safe; completed sessions reject abandonment. |
| Guest revoke | After success, a repeat may return 401 because the credential is now revoked; handle as signed out. |

## 5. TypeScript client contract

The repository already has generated types in `src/lib/api/schema.d.ts` and most
helpers in `src/lib/api/client.ts`. Reuse these rather than duplicating interfaces.
Some fields with backend defaults are required by the existing generated
TypeScript declarations; explicitly supplying defaults such as an empty attempt
`explanation` keeps calls compatible with both the backend and those declarations.
`npm run api:types` regenerates types from the existing backend export; it modifies
the generated frontend declaration, so only run it as part of an authorized
frontend integration change. This documentation task did not run it.

The following **illustrative helper** supports every operation, including 204.
`apiBaseUrl` is an API origin and `accessToken` comes from the existing Supabase
session integration, or is absent for a guest. Do not store or print either token
or cookies in diagnostics. Browser Origin is automatic.

```typescript
import type { components } from "@/lib/api/schema";
type S = components["schemas"];

async function traceRequest<T>(
  apiBaseUrl: string,
  path: string,
  options: { body?: object; key?: string; accessToken?: string } = {},
): Promise<T> {
  const response = await fetch(`${apiBaseUrl.replace(/\/$/, "")}/api/v1${path}`, {
    method: options.body === undefined ? "GET" : "POST",
    credentials: "include",
    cache: "no-store",
    signal: AbortSignal.timeout(35_000),
    headers: {
      "Content-Type": "application/json",
      "X-Trace-Client": "learning-web",
      ...(options.accessToken ? { Authorization: `Bearer ${options.accessToken}` } : {}),
      ...(options.key ? { "Idempotency-Key": options.key } : {}),
    },
    ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
  });
  if (!response.ok) {
    const failure = await response.json().catch(() => null) as S["ErrorResponse"] | null;
    throw Object.assign(new Error(failure?.error.message ?? "Request failed."), {
      status: response.status,
      code: failure?.error.code,
      requestId: response.headers.get("X-Request-ID"),
    });
  }
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}
```

This helper's generic type is a compile-time contract, not a runtime validator.
Manage cancellation, draft preservation and operation keys in the UI. The
existing client always calls `response.json()` on success, so a future revoke
wrapper must add the 204 handling above. Existing helpers do not wrap every
exposed endpoint (such as abandon and the separate history reads); their absence
does not imply the backend endpoint is missing.

## 6. Complete API inventory

Every application operation is READY unless explicitly marked PARTIAL below.
Common errors/headers/permissions in section 4 apply to every row; the final
column adds operation-specific cases. All POST bodies are required; all GETs
have no body. Only lesson lookup has a query parameter. All other parameters
are the UUID path values and UUID Key headers shown.

| # | Method and exact path | Auth / Key | Input -> success schema | Additional behavior/errors |
| --- | --- | --- | --- | --- |
| 1 | `GET /api/v1/health/live` | Public / no | None -> 200 `LivenessResponse` | Process alive only. |
| 2 | `GET /api/v1/health/ready` | Public / no | None -> 200 `ReadinessResponse` | 503 database disconnected/migration heads wrong. |
| 3 | `POST /api/v1/learners/anonymous` | Public or account / no | `{}` -> 200 `IdentityResponse` | Guest bootstrap; Bearer branch needs configured account auth/learner role. |
| 4 | `GET /api/v1/learners/me` | Learner / no | None -> 200 `IdentityResponse` | 401 missing/expired guest; no renewal. |
| 5 | `POST /api/v1/learners/me/revoke` | Guest learner / no | `{}` -> 204, empty | 409 account principal. |
| 6 | `GET /api/v1/lessons/{lesson_id}` | Public / no | Slug; optional `version` -> 200 `LessonResponse` | 404 unknown version/lesson; 422 malformed version. |
| 7 | `POST /api/v1/sessions` | Learner / Key | `SessionCreate` -> 201 `SessionResponse` | 404 lesson; 409 Tasks prerequisite/key reuse. |
| 8 | `GET /api/v1/sessions/{session_id}` | Learner / no | Session UUID -> 200 `SessionResponse` | 404 foreign/missing. |
| 9 | `POST /api/v1/sessions/{session_id}/abandon` | Learner / no | Session UUID; `{}` -> 200 `SessionResponse` | 409 completed session. |
| 10 | `POST /api/v1/sessions/{session_id}/prediction` | Learner / Key | Session UUID; `PredictionCreate` -> 201 `PredictionResponse` | 409 locked prediction/invalid state. |
| 11 | `GET /api/v1/sessions/{session_id}/prediction` | Learner / no | Session UUID -> 200 `PredictionResponse` or JSON `null` | Null means none submitted. |
| 12 | `POST /api/v1/sessions/{session_id}/attempts` | Learner / Key | Session UUID; `AttemptCreate` OR `TransferAttemptCreate` -> 201 `AttemptResponse` | 409 sequencing; 422 wrong family/mapping. |
| 13 | `GET /api/v1/sessions/{session_id}/attempts` | Learner / no | Session UUID -> 200 `AttemptResponse[]` | Empty before first attempt. |
| 14 | `POST /api/v1/sessions/{session_id}/hints` | Learner / Key | Session UUID; `HintCreate` -> 201 `HintResponse` | 409 hint limit/pending/state; 404 invalid attempt; 201 error result is possible. |
| 15 | `POST /api/v1/sessions/{session_id}/attempts/{attempt_id}/verify` | Learner / Key | Two UUIDs; `{}` -> 200 `RunResponse` | 404 foreign attempt; 409 pending/noncurrent/state. `failed`/`error` are result statuses, not HTTP errors. |
| 16 | `GET /api/v1/sessions/{session_id}/verifications` | Learner / no | Session UUID -> 200 `RunResponse[]` | Empty before verification. |
| 17 | `GET /api/v1/sessions/{session_id}/progress` | Learner / no | Session UUID -> 200 `ProgressResponse` | Canonical pinned lesson/history/summary. |
| 18 | `GET /api/v1/learners/me/journey` | Learner / no | None -> 200 `JourneyResponse` | Learner-wide phases, sessions and retrieval checkpoints. |
| 19 | `GET /api/v1/retrievals/{checkpoint_id}` | Learner / no | Checkpoint UUID -> 200 `RetrievalResponse` | 404 foreign checkpoint; upcoming question is null. |
| 20 | `POST /api/v1/retrievals/{checkpoint_id}/attempts` | Learner / Key | Checkpoint UUID; `RetrievalAttemptCreate` -> 201 `RetrievalAttemptResponse` | 409 upcoming/completed or changed replay. |
| 21 | `GET /api/v1/account/me` | Account / no | None -> 200 `AccountResponse` | PARTIAL external auth readiness; 429 inspect limit. |
| 22 | `GET /api/v1/account/me/learner` | Account / no | None -> 200 `AccountLearnerResponse` | PARTIAL external auth readiness; null learner legitimate; 429 inspect limit. |
| 23 | `POST /api/v1/account/claim-anonymous` | Account with learner role + valid guest cookie / Key | `{}` -> 200 `ClaimResponse` | PARTIAL external auth readiness; 401 invalid guest; 403 missing learner role; 409 incompatible history/key; 429 claim limit. Successful receipt replay no longer needs guest cookie. |

OpenAPI declares `HTTPBearer` on learning routes, including public catalog and
guest routes, because it sees the optional dependency. It does not encode the
guest-cookie alternative or the optional public nature accurately. Apply the
actual auth rules above, not an assumption that every security-tagged route
requires a Bearer token. No export changes were made to disguise this limitation.

### Screen/action, loading, success and empty states

All mutations should disable duplicate submission while pending and preserve the
draft/key on network failure. All reads should show a loading state, distinguish
HTTP errors from legitimate empty data, and provide a retry action according to
section 4. Specific endpoint actions follow; row numbers match the inventory.

| # | Frontend screen/action and when | Scope, success and empty state |
| --- | --- | --- |
| 1 | Developer/connectivity diagnostic | Global; alive is not proof lessons/auth work. No empty success. |
| 2 | Setup/dependency diagnostic | Global; ready means DB/schema current. Show 503 as setup/service unavailable, not learner error. |
| 3 | Guest entry and return bootstrap; account learning only after claim decision | Identity-wide; wait for cookie before owned calls. No empty success. |
| 4 | Validate current identity on boot | Identity-wide; 401 means authentication needed, not an empty history list. |
| 5 | Explicit guest sign-out/revoke action | Identity-wide; on 204 clear owned UI/cache and do not parse JSON. |
| 6 | Open Notes/Tasks lesson introduction or show its source snippets | Lesson/version-specific, not session-specific; render all public fields. 404 is unavailable content. |
| 7 | Explicit Start/New exercise after reading journey | Creates a pinned session; keep returned ID and use progress. Do not create automatically on every render. |
| 8 | Resume/status-only view | Session-specific; use returned state. Progress can replace this read if full history is needed. |
| 9 | Explicit Leave/Abandon confirmation | Session-specific; render abandoned and refresh journey. Completed cannot be abandoned. |
| 10 | Submit the initial prediction once | Session-specific; lock answer on success and refresh progress. Do not infer correctness from submission. |
| 11 | Restore prediction-only panel | Session-specific; JSON null means no saved prediction, not an error. Enable editing only in awaiting_prediction; an abandoned session with no prediction remains read-only. |
| 12 | Submit a bounded mapping and explanation | Session-specific; display numbered saved attempt then verify it. Saving alone does not execute code. |
| 13 | Attempt history panel/resume | Session-specific; [] means no attempts. Ordering/number come from backend. |
| 14 | Explicit Request hint button | Session-specific with optional attempt link; label fixture. `delivered` renders text; `error` renders unavailable and counts a consumed request. Refresh progress/counts. |
| 15 | Explicit Run/Verify saved attempt | Session/attempt-specific; show running until response, then inspect result status and refresh progress/journey. Checks may be [] while pending; infrastructure errors may contain an execution check instead of the normal five. |
| 16 | Evidence history or reconcile an uncertain verify call | Session-specific; [] means never verified. Inspect saved run before intentional retry. |
| 17 | Main learner screen on resume and after every mutation | Session-specific; render nested null/empty histories normally. This is authoritative persisted progress, not AI grading. |
| 18 | Learning home/dashboard and after Notes/Tasks completion | Learner-wide; Notes phase is available, Tasks unlocks after Notes. Empty session/checkpoint lists are normal. Resume existing sessions here. |
| 19 | Open a journey checkpoint card | Checkpoint-specific; upcoming means schedule card with no question yet; due/completed exposes question and saved attempts. |
| 20 | Submit a due retrieval option/reasoning | Checkpoint-specific; display explicit correct/feedback, refresh checkpoint/journey. Incorrect stays due; correct completes. |
| 21 | Account page/sign-in completion, **before** learner calls | Account-wide; show claim option based on history flag. Null learner is an intentional decision point. |
| 22 | Account learner-status check if full account view is unnecessary | Account-wide; null means unmapped, not a failed request. Same inspect quota as row 21. |
| 23 | Explicit Claim guest history action | Account/guest relationship, not a session call; after success refresh account/journey and use returned learner. Never silently auto-claim/merge. |

## 7. Request and response schemas with examples

Examples use fabricated reference UUIDs and timestamps, never real account or
learner data. Lesson strings, field names, fixture hints and runtime facts come
from the actual implementation. They are illustrative **schema-validated**
examples, not claims that a live HTTP transaction was performed in this audit.
The same schema/example applies wherever the inventory references it (for
example GET/POST prediction). Actual IDs/timestamps always come from responses.
All date-time strings are server UTC instants; parse for display, never use the
browser timezone to rewrite scheduling decisions.

### Health and identity: operations 1-5

<!-- schema: LivenessResponse -->
```json
{"status":"alive"}
```

<!-- schema: ReadinessResponse -->
```json
{"status":"ready"}
```

`IdentityResponse` (bootstrap and current identity):

<!-- schema: IdentityResponse -->
```json
{"learner_id":"10000000-0000-4000-8000-000000000001","expires_at":"2026-12-02T09:00:00Z"}
```

Bootstrap/revoke request is exactly `{}` (`Contract`); revoke has an empty 204
response, not `{}` or `null`. `expires_at` is the guest credential deadline or
account JWT deadline, not a lesson/session expiration timestamp.

### Lesson and session: operations 6-9

`lesson_id` is a slug, not `version_id`. Seeded families are
`fastapi-payload-mismatch` (Notes) and `fastapi-nested-payload-transfer` (Tasks),
both version `1.0.0`. GET lesson `version` is optional; without it repository
lookup chooses the latest stored version. Its supplied format is digits.digits.digits
and at most 32 characters. There is no `GET /api/v1/lessons` collection endpoint.
Journey phase IDs provide discovery for the two existing families.

`LessonResponse`:

<!-- schema: LessonResponse -->
```json
{
  "id":"fastapi-payload-mismatch",
  "version_id":"20000000-0000-4000-8000-000000000001",
  "version":"1.0.0",
  "title":"Follow the note: from form to database",
  "objective":"Trace a form value through an outgoing request and the receiving schema, then verify a real save.",
  "scenario":"The notes form says a note was submitted, but nothing is saved. Inspect the request builder and the receiving FastAPI schema. Predict the outcome before changing the outgoing mapping.",
  "outgoing_code":"payload = {\n    \"title\": note.title,\n    \"body\": note.content,\n}\nresponse = client.post(\"/notes\", json=payload)",
  "schema_code":"from pydantic import BaseModel, ConfigDict\n\nclass NoteCreate(BaseModel):\n    model_config = ConfigDict(extra=\"forbid\")\n    title: str\n    content: str"
}
```

`SessionCreate`: `lesson_id` is required, 1-80 lowercase letters/digits/hyphens;
`version` defaults to `1.0.0` with the same version-format bound.

<!-- schema: SessionCreate -->
```json
{"lesson_id":"fastapi-payload-mismatch","version":"1.0.0"}
```

`SessionResponse` (create, inspect, abandon and nested journey/progress):

<!-- schema: SessionResponse -->
```json
{"id":"30000000-0000-4000-8000-000000000001","lesson_version_id":"20000000-0000-4000-8000-000000000001","state":"awaiting_prediction","created_at":"2026-11-02T09:00:00Z","completed_at":null}
```

Possible states: `awaiting_prediction`, `ready_for_attempt`,
`verification_pending`, `needs_revision`, `completed`, `abandoned`.
An abandon success has `state: "abandoned"`; completion has `state: "completed"`
and a server completion timestamp. Existing sessions pin `lesson_version_id`;
render `progress.lesson` rather than replacing historical content with latest
catalog content. Session responses do not contain an expiry field.

### Prediction: operations 10-11

`PredictionCreate`: selection is exactly `rejected | saved | server_error`;
reasoning is required, nonblank and 1-2,000 characters. These are outcome choices,
not the retrieval option IDs. This legacy HTTP lesson response does not ship a
generic prediction-choice specification; use these actual enums for both families.

<!-- schema: PredictionCreate -->
```json
{"selected_answer":"rejected","reasoning":"The outgoing request does not match the receiving schema."}
```

`PredictionResponse`:

<!-- schema: PredictionResponse -->
```json
{"id":"40000000-0000-4000-8000-000000000001","selected_answer":"rejected","reasoning":"The outgoing request does not match the receiving schema.","created_at":"2026-11-02T09:01:00Z"}
```

GET returns the object above or JSON `null`. The immutable prediction has no
`correct` field. The existing progress summary exposes `prediction_correct` only
after a prediction **and at least one attempt** exist; until then it is null.

### Bounded attempts: operations 12-13

The request is a discriminated union by `change_type`. Do not send an arbitrary
code patch, request JSON, answer key, executable command or evaluator settings.
`explanation` is optional, defaults to an empty string and is at most 2,000 chars.

Notes (`AttemptCreate`):

<!-- schema: AttemptCreate -->
```json
{"change_type":"rename_payload_field","field_name":"body","explanation":"First inspect the current outgoing mapping."}
```

Allowed Notes fields are `body | content`. Tasks (`TransferAttemptCreate`):

<!-- schema: TransferAttemptCreate -->
```json
{"change_type":"nest_payload_field","field_name":"flat","explanation":"Inspect the original flat request before proposing a nested mapping."}
```

Allowed Tasks fields are `flat | nested`. Always send the discriminator/field
pair for the pinned lesson family. The HTTP union validates those pairs; the
service additionally checks the permitted field for that family. It does not
offer a free-form code-editing API.

`AttemptResponse`:

<!-- schema: AttemptResponse -->
```json
{"id":"50000000-0000-4000-8000-000000000001","number":1,"change_type":"rename_payload_field","field_name":"body","explanation":"First inspect the current outgoing mapping.","hints_before":0,"created_at":"2026-11-02T09:02:00Z"}
```

GET attempts returns a JSON array of those objects, or `[]`. `hints_before`
records request history, not proof that help was successfully delivered.
Submitting stores a numbered mapping and changes state to verification_pending;
it does not itself execute or prove a correction.

### Hints: operation 14

`HintCreate` is `{}` or has one nullable attempt UUID:

<!-- schema: HintCreate -->
```json
{"attempt_id":null}
```

`HintResponse`:

<!-- schema: HintResponse -->
```json
{"id":"60000000-0000-4000-8000-000000000001","attempt_id":null,"sequence":1,"text":"Follow the request data from the sender to the receiver.","status":"delivered","provider":"fake","fixture":"fake-v1","prompt_version":"payload-mismatch-v1","interaction_type":"hint","created_at":"2026-11-02T09:03:00Z"}
```

`status: "error"` has `text: null`, still returns 201 and consumes one of three
session guidance request slots. Pending operations also reserve slots. Hints
require a submitted prediction and a nonterminal session; do not infer unlimited
retry capacity from `hints.length` alone. Use `summary.hint_request_count` and
`hints_delivered`. The current route always uses FakeTutorProvider, independently
of disabled/mock shared internal AI resources. Hint text is authored fixture
guidance, not AI-generated feedback or a guarantee of learner understanding.

### Execute/verify and verification history: operations 15-16

Required body: `{}`. Execute the saved attempt through the verify route; `/notes`
and `/tasks` shown in lesson snippets are private exercise application routes,
**not** public routes on the main API.

`RunResponse` example for the uncorrected Notes mapping:

<!-- schema: RunResponse -->
```json
{
  "id":"70000000-0000-4000-8000-000000000001",
  "attempt_id":"50000000-0000-4000-8000-000000000001",
  "status":"failed",
  "feedback":"The receiving schema rejected the payload. No note was saved.",
  "created_at":"2026-11-02T09:04:00Z",
  "completed_at":"2026-11-02T09:04:01Z",
  "checks":[
    {"code":"http_status","matched":false,"expected":"201","observed":"422","source":"asgi_http","created_at":"2026-11-02T09:04:01Z"},
    {"code":"api_response","matched":false,"expected":"validated note response","observed":"{\"detail\":[{\"type\":\"missing\",\"loc\":[\"body\",\"content\"],\"msg\":\"Field required\",\"input\":{\"title\":\"Trace verification note\",\"body\":\"Understanding request validation\"}},{\"type\":\"extra_forbidden\",\"loc\":[\"body\",\"body\"],\"msg\":\"Extra inputs are not permitted\",\"input\":\"Understanding request validation\"}]}","source":"asgi_http","created_at":"2026-11-02T09:04:01Z"},
    {"code":"validation","matched":false,"expected":"request accepted by receiving schema","observed":"[\"missing:content\", \"extra_forbidden:body\"]","source":"asgi_http","created_at":"2026-11-02T09:04:01Z"},
    {"code":"row_count","matched":false,"expected":"1","observed":"0","source":"fresh_database_read","created_at":"2026-11-02T09:04:01Z"},
    {"code":"stored_values","matched":false,"expected":"{\"content\": \"Understanding request validation\", \"title\": \"Trace verification note\"}","observed":"[]","source":"fresh_database_read","created_at":"2026-11-02T09:04:01Z"}
  ]
}
```

Exact serialized validation-detail formatting can vary with locked dependency
versions; the example shows the structure, not a string equality to assert in
the frontend. `CheckResponse` always has `code`, `matched`, `expected`, `observed`,
`source`, `created_at`. Expected/observed are **strings**; some contain encoded
JSON. Render as text/code, never HTML or executable content. Normal runs expose
five checks: `http_status`, `api_response`, `validation`, `row_count`,
`stored_values`. Execution infrastructure failure may instead expose an
`execution` check; do not assume exactly five on every response.

| Run status | HTTP / session consequence | UI meaning |
| --- | --- | --- |
| `pending` | Persisted in-flight run; completed_at null | Await/reconcile persisted state. A competing verify can return 409. |
| `failed` | HTTP 200; normally session becomes needs_revision | Observed learner mapping failure; allow a new attempt. |
| `passed` | HTTP 200; normally session becomes completed | Trusted runtime and independent database read agree. Tasks also schedules retrieval. |
| `error` | HTTP 200; normally session remains verification_pending | Infrastructure/inconsistent evidence, **not a learner failure**; offer deliberate verification retry. |

History GET returns `RunResponse[]`, initially `[]`. Verification normally waits
for trusted execution rather than returning an asynchronous job handle. A
persisted pending run can survive interruption; stale recovery is server-owned
after `max(60 seconds, 3 * verification timeout)`. Do not invent a job endpoint,
poll aggressively or classify a network timeout as a failed exercise. A final
database failure may return 503 with pending state left behind. Refresh progress
before retrying. If abandonment races execution, saved run evidence can still
arrive while the session remains abandoned.

Legacy verification/progress **already expose** expected/observed/source strings.
The newer feedback projection intentionally excludes such raw details, but it
does not retroactively change these existing learner HTTP contracts. Do not
claim that those legacy responses use response-local aliases or new feedback
privacy rules.

### Progress: operation 17

`ProgressResponse` includes all of the following fields; nested schemas are the
objects above. The following is a newly created session before prediction:

<!-- schema: ProgressResponse -->
```json
{
  "session":{"id":"30000000-0000-4000-8000-000000000001","lesson_version_id":"20000000-0000-4000-8000-000000000001","state":"awaiting_prediction","created_at":"2026-11-02T09:00:00Z","completed_at":null},
  "lesson":{"id":"fastapi-payload-mismatch","version_id":"20000000-0000-4000-8000-000000000001","version":"1.0.0","title":"Follow the note: from form to database","objective":"Trace a form value through an outgoing request and the receiving schema, then verify a real save.","scenario":"The notes form says a note was submitted, but nothing is saved. Inspect the request builder and the receiving FastAPI schema. Predict the outcome before changing the outgoing mapping.","outgoing_code":"payload = {\n    \"title\": note.title,\n    \"body\": note.content,\n}\nresponse = client.post(\"/notes\", json=payload)","schema_code":"from pydantic import BaseModel, ConfigDict\n\nclass NoteCreate(BaseModel):\n    model_config = ConfigDict(extra=\"forbid\")\n    title: str\n    content: str"},
  "prediction":null,
  "attempts":[],
  "hints":[],
  "verifications":[],
  "events":[{"event_type":"session_created","reference_id":null,"created_at":"2026-11-02T09:00:00Z"}],
  "summary":{"attempt_count":0,"hint_request_count":0,"hints_delivered":0,"verification_errors":0,"prediction_correct":null,"correct_after_revision":false,"hint_assisted_correction":false}
}
```

`EventResponse` is `{event_type: string, reference_id: UUID | null, created_at}`.
Event type is a string, not a newly closed frontend enum. Summary flags are
observational/chronological: `correct_after_revision` means passing attempt number
exceeds one; `hint_assisted_correction` means delivered help preceded success.
They are not competency scores, proof of diagnosis or proof of independent work.
No captured investigation actions or code patches are available from these fields.

### Journey and retrieval: operations 18-20

`JourneyResponse` on a new learner:

<!-- schema: JourneyResponse -->
```json
{"server_time":"2026-11-02T09:00:00Z","phases":[{"lesson_id":"fastapi-payload-mismatch","available":true,"completed":false,"sessions":[],"attempt_count":0},{"lesson_id":"fastapi-nested-payload-transfer","available":false,"completed":false,"sessions":[],"attempt_count":0}],"checkpoints":[],"last_completed_at":null}
```

Use `PhaseResponse.sessions` to resume; no separate general session-list endpoint
exists. Notes completion unlocks Tasks for the same learner. Every successful
Tasks transfer session schedules two checkpoints atomically at **+24 and +168 UTC
hours from transfer completion**; not from account creation, Notes completion or
learner-local midnight. Existing pinned question identity and +1/+7 schedules
remain unchanged. Missed due checkpoints stay available. Retrieval is separate
from proposed new-assignment quota policy.

`CheckpointSummary` fields appear in journey and retrieval: `id`,
`transfer_session_id`, `ordinal`, `due_at`, nullable `completed_at`,
`status: upcoming | due | completed`, `attempt_count`.

`RetrievalResponse` for a due first checkpoint:

<!-- schema: RetrievalResponse -->
```json
{
  "checkpoint":{"id":"80000000-0000-4000-8000-000000000001","transfer_session_id":"30000000-0000-4000-8000-000000000002","ordinal":1,"due_at":"2026-11-03T09:00:00Z","completed_at":null,"status":"due","attempt_count":0},
  "server_time":"2026-11-03T09:00:00Z",
  "question":{"id":"shipping-contract-v1","title":"Recall the shipment contract","prompt":"The shipment request contains all the intended values but is rejected. Which diagnosis fits the receiving contract?","payload":"{\"reference\":\"PKG-42\",\"zone\":\"east\"}","schema_code":"class Destination(BaseModel):\n    zone: str\n\nclass ShipmentCreate(BaseModel):\n    reference: str\n    destination: Destination","options":[{"id":"a","label":"Any request containing zone must be accepted."},{"id":"b","label":"The zone value is at a different JSON level than the schema expects."},{"id":"c","label":"A rejected request proves that the database is down."}]},
  "attempts":[]
}
```

Upcoming: same response shape with `status: "upcoming"`, `question: null` and no
answers yet. Completed: question remains visible and attempt history remains.
Question includes no answer key/explanation. Always use backend `server_time`
and `status` for enablement; a client countdown is display only.

`RetrievalAttemptCreate`: selection `a | b | c`, optional reasoning defaults to
empty and is at most 2,000 characters.

<!-- schema: RetrievalAttemptCreate -->
```json
{"selection":"b","reasoning":"Compare the JSON nesting level with the receiving contract."}
```

`RetrievalAttemptResponse`:

<!-- schema: RetrievalAttemptResponse -->
```json
{"id":"90000000-0000-4000-8000-000000000001","number":1,"selection":"b","reasoning":"Compare the JSON nesting level with the receiving contract.","correct":true,"feedback":"Correct. Values and structure both matter. The receiving contract places zone inside destination; a flat zone does not satisfy that nested object.","created_at":"2026-11-03T09:01:00Z"}
```

Incorrect responses persist with `correct: false` and deterministic feedback;
the checkpoint remains due. A correct response completes it. New submissions to
upcoming/completed checkpoints return 409, except exact idempotent replay of an
already accepted response. Explicit correctness here is the established
retrieval contract, not new AI feedback.

### Account inspection and claim: operations 21-23

`AccountResponse` is Trace account identity, not the provider subject or learner
identity. `status` and `roles` are strings in the HTTP schema, not caller-editable
claims. A pre-claim account example:

<!-- schema: AccountResponse -->
```json
{"user_id":"a0000000-0000-4000-8000-000000000001","created_at":"2026-11-02T09:10:00Z","status":"active","roles":["learner"],"learner_id":null,"anonymous_history_available":true}
```

`AccountLearnerResponse` is inspection only:

<!-- schema: AccountLearnerResponse -->
```json
{"learner_id":null}
```

Claim body is `{}`; current cookie supplies the guest identity. Do not send an
account, guest or learner ID in the body. `ClaimResponse`:

<!-- schema: ClaimResponse -->
```json
{"learner_id":"10000000-0000-4000-8000-000000000001","claimed":true}
```

## 8. Typed calls for every operation

These short examples use `traceRequest`/`S` from section 5 and the real generated
schemas. Each call belongs to its corresponding screen/action in section 6;
this is a reference of independent calls, **not a script to execute all in order**.
`base` is the configured API origin, `token` is SDK-managed, and IDs are values
returned by previous responses. Reuse each saved key if retrying that operation.

```typescript
async function operationExamples(
  base: string, token: string | undefined,
  sessionId: string, attemptId: string, checkpointId: string,
  keys: { session: string; prediction: string; attempt: string; hint: string;
          verify: string; retrieval: string; claim: string },
) {
  const auth = { accessToken: token };
  const sessionPath = `/sessions/${encodeURIComponent(sessionId)}`;
  const checkpointPath = `/retrievals/${encodeURIComponent(checkpointId)}`;
  // 1-2: diagnostics; no auth needed.
  const live = await traceRequest<S["LivenessResponse"]>(base, "/health/live");
  const ready = await traceRequest<S["ReadinessResponse"]>(base, "/health/ready");
  // 3-5: bootstrap, inspect, explicit guest revoke (204).
  const identity = await traceRequest<S["IdentityResponse"]>(base, "/learners/anonymous", { ...auth, body: {} });
  const me = await traceRequest<S["IdentityResponse"]>(base, "/learners/me", auth);
  await traceRequest<void>(base, "/learners/me/revoke", { body: {} });
  // 6-9: catalog, start, inspect, explicit abandonment.
  const lesson = await traceRequest<S["LessonResponse"]>(base, "/lessons/fastapi-payload-mismatch?version=1.0.0", auth);
  const sessionBody = { lesson_id: lesson.id, version: lesson.version } satisfies S["SessionCreate"];
  const session = await traceRequest<S["SessionResponse"]>(base, "/sessions", { ...auth, body: sessionBody, key: keys.session });
  const savedSession = await traceRequest<S["SessionResponse"]>(base, sessionPath, auth);
  const abandoned = await traceRequest<S["SessionResponse"]>(base, `${sessionPath}/abandon`, { ...auth, body: {} });
  // 10-11: one immutable prediction and its nullable read.
  const predictionBody = { selected_answer: "rejected", reasoning: "Compare the sender and receiver." } satisfies S["PredictionCreate"];
  const prediction = await traceRequest<S["PredictionResponse"]>(base, `${sessionPath}/prediction`, { ...auth, body: predictionBody, key: keys.prediction });
  const original = await traceRequest<S["PredictionResponse"] | null>(base, `${sessionPath}/prediction`, auth);
  // 12-13: choose the appropriate family body; no arbitrary source code.
  const notesChange = { change_type: "rename_payload_field", field_name: "body", explanation: "Inspect the existing mapping." } satisfies S["AttemptCreate"];
  const tasksChange = { change_type: "nest_payload_field", field_name: "flat", explanation: "" } satisfies S["TransferAttemptCreate"];
  const attempt = await traceRequest<S["AttemptResponse"]>(base, `${sessionPath}/attempts`, { ...auth, body: notesChange, key: keys.attempt });
  const attempts = await traceRequest<S["AttemptResponse"][]>(base, `${sessionPath}/attempts`, auth);
  // 14: hint status may be error even when HTTP is 201.
  const hintBody = { attempt_id: attemptId } satisfies S["HintCreate"];
  const hint = await traceRequest<S["HintResponse"]>(base, `${sessionPath}/hints`, { ...auth, body: hintBody, key: keys.hint });
  // 15-17: run, saved evidence and canonical progress.
  const run = await traceRequest<S["RunResponse"]>(base, `${sessionPath}/attempts/${encodeURIComponent(attemptId)}/verify`, { ...auth, body: {}, key: keys.verify });
  const runs = await traceRequest<S["RunResponse"][]>(base, `${sessionPath}/verifications`, auth);
  const progress = await traceRequest<S["ProgressResponse"]>(base, `${sessionPath}/progress`, auth);
  // 18-20: only after the signed-in guest-history decision.
  const journey = await traceRequest<S["JourneyResponse"]>(base, "/learners/me/journey", auth);
  const retrieval = await traceRequest<S["RetrievalResponse"]>(base, checkpointPath, auth);
  const retrievalBody = { selection: "b", reasoning: "Compare nesting levels." } satisfies S["RetrievalAttemptCreate"];
  const answer = await traceRequest<S["RetrievalAttemptResponse"]>(base, `${checkpointPath}/attempts`, { ...auth, body: retrievalBody, key: keys.retrieval });
  // 21-23: inspect before learner calls; claim only with explicit user consent.
  const account = await traceRequest<S["AccountResponse"]>(base, "/account/me", auth);
  const accountLearner = await traceRequest<S["AccountLearnerResponse"]>(base, "/account/me/learner", auth);
  const claimed = await traceRequest<S["ClaimResponse"]>(base, "/account/claim-anonymous", { ...auth, body: {}, key: keys.claim });
}
```

Use `crypto.randomUUID()` when initially creating an operation key, not on every
automatic retry/render. The account calls above require a token; the generic
helper deliberately does not manufacture one or downgrade a rejected account
request to guest mode. Do not run the illustrative revoke/abandon/claim calls
as side effects of mounting a screen.

## 9. Required Notes and Tasks sequencing

For Notes:

1. Establish identity (resolve account claim first if signed in).
2. Read journey; resume a suitable existing session or explicitly create one.
3. Render pinned progress/lesson and submit the original prediction once.
4. Save the chosen bounded mapping; verify the returned attempt ID.
5. If failed, inspect real validation/HTTP/database checks and save a revision.
6. If passed, render completion and refresh journey to unlock Tasks.

For Tasks:

1. Same learner must already have completed Notes; session creation enforces it.
2. Start/resume the separate `fastapi-nested-payload-transfer` session and predict.
3. Submit `nest_payload_field` / `flat`, then verify to capture the original
   failed request's evidence.
4. Only after that failure, offer a `nested` correction and verification.
5. A passing run completes Tasks and creates the two retrieval checkpoints.

No request can set completion, correctness, expected values or runtime results.
Investigation is a learner activity supported by displayed source/evidence; no
independent investigation-action capture endpoint exists. A modified mapping
alone does not establish implementation success. The success/failure facts come
from trusted runtime execution and independent DB readback, never an LLM.

## 10. Integration priorities and coordination blockers

1. **Guest Notes first:** matched origins/cookies, bootstrap, journey, pinned
   progress, prediction, finite attempt/verify, reload/resume and clear errors.
2. **Tasks transfer:** Notes prerequisite, mandatory failed flat run, nested
   correction, real evidence display and retrieval scheduling confirmation.
3. **History and retrieval:** resume from journey, upcoming/due/completed states,
   submit/replay answers using server timing. Never silently switch +1 to +3.
4. **Fixture hint UX:** explicit fixture labeling, three request slots, error
   versus delivered, no promise of live model conversation.
5. **Accounts with Soorej:** shared Supabase project/signing keys, publishable
   frontend key, matching backend issuer/JWKS/audience, Google provider and exact
   callback/site allowlists, email confirmation/recovery delivery. Test guest
   claim **before** adding eager authenticated journey queries.
6. **Deployment with Soorej:** agree actual backend origin, hosting/TLS/cookie
   topology, CORS, local versus hosted configuration and operational hardening.
   Readiness alone is not production/security approval.
7. **Later feedback integration only after separate authorization:** agree
   public endpoint/contract and audience, terminal reflection/next-action policy,
   ingress/no-store/rate/concurrency behavior, then frontend presentation.

There is no frontend-ready URL for evidence feedback, generation, support chat,
daily assignments or mastery. Do not infer URLs from service class names or
schema names. The Phase 3.5C implementation does not activate any of these.

## 11. Inspection evidence and verification limits

Authoritative implementation inspected:

- App/router/DI: `backend/app/main.py`, `api/v1/router.py`, `api/v1/learning.py`,
  `api/v1/accounts.py`, `api/dependencies.py`.
- Wire schemas/projection: `backend/app/schemas/{learning,retrieval,accounts,errors}.py`,
  `api/presentation.py`, `api/retrieval_presentation.py`.
- Auth/config: `backend/app/auth/jwt.py`, `services/{identity,accounts}.py`,
  `db/accounts.py`, `core/{settings,errors,middleware,ai_settings}.py`.
- Learning/runtime: `services/{catalog,learning,verification,task_evidence,retrieval}.py`,
  `domain/{learning,transfer,retrieval}.py`, `verification/{asgi_notes,asgi_tasks}.py`,
  `db/health.py`.
- Internal boundaries: `ai/resources.py`, `services/{feedback_release,learner_feedback,public_feedback_projection}.py`.
- Frontend cross-check: `src/lib/api/{client.ts,schema.d.ts}`, `src/lib/supabase/`,
  `src/components/account/account-dashboard.tsx`, auth form and frontend callback.
- Startup/export: `README.md`, `backend/pyproject.toml`, `.env.local.example`,
  `backend/.env.example`, `backend/scripts/export_openapi.py`.

Relevant tests inspected (not a claim of executing them in this documentation
task): `backend/tests/integration/test_{learning,learning_failures,accounts,api,transfer_retrieval,tutor_transactions}.py`,
`backend/tests/unit/test_{jwt,settings,health}.py`, existing legacy API fixture
contracts and feedback integration/privacy tests. They establish the intended
ownership, state, idempotency, disclosure and runtime behavior. The previous
Phase 3.5C report records its own executed 3,174-test validation; this task does
not represent that earlier result as a newly executed full suite.

This handoff separately verifies the live application's **schema construction**,
the unchanged OpenAPI export, example model validity and inventory completeness.
It does not contact a hosted API, verify real Supabase keys/Google/SMTP delivery,
test browser cookie behavior on a deployment, or read real environment values.
Those operational details remain coordination work. No application code,
migration, database, environment file, existing report or frontend implementation
was changed to produce this document. The two handoff files remain uncommitted.

Executed documentation checks:

- Generated `docs/api/openapi.json` directly from `create_app(...).openapi()` with
  environment-file loading disabled and without entering the app lifespan.
- Confirmed structural equality with the existing backend export: 21 paths,
  23 operations, all 23 documented in the inventory.
- Validated all 23 annotated JSON examples using their actual Pydantic models;
  compared lesson public content and retrieval question text/options to source.
- Compiled both TypeScript blocks together in an isolated artifact against the
  existing generated frontend types with strict `tsc --noEmit`; passed. An
  initially omitted defaulted Tasks explanation was supplied explicitly to meet
  the generated declaration; no frontend or backend schema was changed.
- Reviewed account and learner contracts independently against implementation
  and tests; reviewed both new files for accidental credential/private-value
  exposure. No such values were found.
- No backend pytest suite was rerun, and no browser or live-provider smoke test
  was performed. Those are explicit limits, not unreported passing checks.

## 12. Learner-requested (custom) lessons

Added on branch `feat/custom-lesson-creation` (additive; existing contracts unchanged). A
signed-in learner describes what they want to learn; Trace drafts a short lesson set with the
shared Gemini setup, validates it, stores it privately and lets the learner study it.

**Auth and transport (all endpoints):** account Bearer token with the `learner` role (guest
cookies are refused), `X-Trace-Client: learning-web` and an allowed `Origin` on writes,
`Cache-Control: no-store`, the standard `ErrorResponse` envelope. Every resource is private to
the requesting account: another account gets **404**.

| Method and path | Purpose | Notes |
|---|---|---|
| `GET /api/v1/custom-lessons/languages` | Suggested languages and how answers are checked | `generation_available: false` when AI is disabled. Every language is `answer_key`; generated code is never run. |
| `POST /api/v1/custom-lessons/requests` | Queue generation | **202** with the request. `Idempotency-Key` (UUID) required: same key + same body replays; same key + different body is **409** `idempotency_conflict`. Body: `topic` (10–1000), `language` (1–40), `framework?`, `level`, `goal`, `lesson_count` 1–3, `practice_styles` (≥1 of `predict_output`, `find_bug`, `multiple_choice`, `explain`). |
| `GET /api/v1/custom-lessons/requests/{id}` | Status | `queued`, `generating`, `ready`, `failed`, `cancelled`, `rejected`; `error_code`, learner-safe `message`, `lessons_ready`, `lesson_ids`, timestamps. |
| `POST /api/v1/custom-lessons/requests/{id}/cancel` | Cancel while queued/generating | Final states are returned unchanged. |
| `GET /api/v1/custom-lessons` | The learner's lessons | Newest first, with progress counts. |
| `GET /api/v1/custom-lessons/{id}` | One lesson | **No answer keys.** `explanation` appears per challenge only after it was answered. `next_lesson_id` links a set. |
| `DELETE /api/v1/custom-lessons/{id}` | Delete a lesson and its answers | **204**. |
| `POST /api/v1/custom-lessons/{id}/challenges/{challengeId}/answers` | Check an answer on the server | `Idempotency-Key` required. `answer_key` challenges take `selected_option` and return `correct` true/false + explanation; `practice_only` (explain) take `text` and return `correct: null`, an example answer and the explanation. The key itself is never returned. |

**Errors:** 401 not signed in; 403 role/origin; 404 missing or foreign; 409
`idempotency_conflict`; 422 validation, `custom_lesson_sensitive_input` (secrets/emails),
`custom_lesson_policy_rejected` (clearly unsafe topics, with a rewrite hint),
`invalid_answer`; 429 `custom_lesson_rate_limited` (per minute) and
`custom_lesson_quota_reached` (per day); 503 `custom_lessons_unavailable`.

**Request `error_code` values (failed/rejected):** `provider_rate_limited`, `quota_exhausted`,
`provider_timeout`, `provider_unavailable`, `provider_error`, `invalid_output`, `interrupted`
(restart or stale job), validation codes (`answer_leak`, `missing_correct_option`,
`invalid_options`, `invalid_python`, `unsafe_output`, `language_mismatch`,
`unrequested_style`, `invalid_structure`, `code_too_long`), and for `rejected`:
`off_topic`, `unsafe`, `unclear`.

**Generation:** one background worker per process (the HTTP request returns at once). Each
lesson is one provider call through a separate bounded client that shares the Gemini
transport, settings class and usage ledger with the tutor and Trace Help. One retry only for
malformed output; none for rate limits or quota. Output is validated (schema, a unique
correct option, no answer text in prompts or hints, Python parsed with `ast` and never
executed, no URLs or secret-like strings, language matches) before anything is stored. No
prompts or model output are stored or logged. At startup, unfinished jobs are marked
`failed` / `interrupted`; a job not updated for `stale_after_seconds` is marked the same.

**Limits (process variables, safe defaults; `TRACE_CUSTOM_LESSONS_` prefix):**
`ENABLED` (true), `PROVIDER_TIMEOUT_SECONDS` (20, the Gemini adapter maximum; the tutor stays
at 10), `REQUESTS_PER_MINUTE` (2), `DAILY_REQUESTS_PER_ACCOUNT` (5),
`MAX_LIVE_CALLS_PER_PROCESS` (15, never above the shared `TRACE_LLM_MAX_LIVE_REQUESTS_PER_PROCESS`),
`STALE_AFTER_SECONDS` (600). Spend and token caps come from the shared `TRACE_LLM_*` settings.
