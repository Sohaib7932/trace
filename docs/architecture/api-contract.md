# API contracts — Modules 2–4

## Account API and unified principals

| Method/path (relative to `/api/v1`) | Request | Result |
|---|---|---|
| GET /account/me | Verified Supabase Bearer | Internal UUID, created/status, trusted roles, nullable learner, valid guest availability |
| GET /account/me/learner | Verified Bearer | Nullable learner; inspection never allocates one |
| POST /account/claim-anonymous | Bearer + guest cookie + `{}` + UUID Idempotency-Key + exact Origin/client | Atomic receipt, clears guest cookie; 409 for other account history |

These are application ownership operations, not duplicate provider login/signup/
reset endpoints. The backend verifies ES256/RS256 JWT signature/kid/issuer/audience/
time/subject/structure. First verified requests bootstrap the internal user/subject/
default learner role atomically. Email/metadata never decide identity or permission.

Valid Bearer accounts take priority on learning requests. Without Authorization,
the guest flow remains. Invalid supplied headers return 401, never guest fallback;
unavailable keys/config return 503. Authenticated learning creates/resolves an
account learner without issuing a guest cookie. Identity response expiry is the
access-token expiry for accounts and credential expiry for guests. Guest revoke
rejects account sessions with 409; sign out through the provider SDK. Catalog stays
public but rejects invalid supplied Authorization. IDs never authorize resources.

Claim derives its guest from the cookie, never submitted IDs/hashes. An exact-key
same-user receipt can replay after cookie deletion; new transfers require a valid
unexpired/unrevoked credential. Conflicts never merge histories. Account inspect
and claim each enforce a per-user 30/minute fixed window and return 429 on excess;
failed claims count. CORS adds Authorization while retaining exact Origin/client
and credentials controls. Account responses are no-store. No public role-grant API.

FastAPI-generated `backend/openapi.json` and `src/lib/api/schema.d.ts` describe the
implemented API. Regenerate with `npm run api:generate`; a second generation must
produce identical bytes. No planned endpoints are inserted into OpenAPI as stubs.

## Identity, authorization and writes

`POST /api/v1/learners/anonymous` accepts `{}` and creates/reuses an anonymous identity.
It returns learner ID/expiry, never the credential. A valid credential in the latter
half of its configured lifetime is renewed under the write gate and reissued only
as the HttpOnly cookie; it is rechecked for expiry/revocation before renewal. Default
life is 30 days so a +7-day checkpoint can be revisited. The host-only HttpOnly cookie
`trace_learner` at `/api/v1` contains the random credential; only its hash is stored.
Secure is default; non-Secure cookies require explicit loopback development mode.
SameSite=Lax and matching browser/API hostnames are required locally.

Every state-changing learning endpoint validates an exact configured Origin and
`X-Trace-Client: learning-web`. Browser requests use `credentials: include` and CORS
permits only explicit origins/headers with credentials. Session/attempt IDs never
provide authorization: dependencies resolve the credential and services scope every
resource to its owner. Another owner's resource and a missing resource both return
404. Catalog content is intentionally public and explicitly excludes evaluator data.
Learning responses use `Cache-Control: no-store`.

Prediction, attempt, hint, verification and session creation require a UUID
`Idempotency-Key` header. Repeating a key with the same logical payload returns the
same record; changing its payload conflicts. A second prediction with a new key
also conflicts. Verification final passed/failed results are canonical per attempt;
replays do not execute another note write. Same-key errors replay the error; a new
key deliberately starts a new run after an error. Active pending runs conflict;
stale ones can be recorded as interrupted errors before a new run starts.

## Implemented endpoints

All paths below are relative to `/api/v1`.

| Method/path | Request and ownership | Result |
|---|---|---|
| GET /health/live | No credential | 200 alive, independent of DB |
| GET /health/ready | No credential | 200 ready or 503 dependency error; migration head required |
| POST /learners/anonymous | Empty object, write protection | 200 identity; Set-Cookie only for a new credential |
| GET /learners/me | Valid credential | 200 owner ID/expiry, otherwise 401 |
| POST /learners/me/revoke | Credential, empty object, write protection | 204; revoke digest and clear cookie |
| GET /lessons/{lesson_id} | Public; optional exact version query | Current published version or requested version; no hidden evaluator fields |
| POST /sessions | Owner, lesson_id/version, retry key | 201 pinned session in awaiting_prediction |
| GET /sessions/{session_id} | Owner | Saved server state/version reference |
| POST /sessions/{session_id}/abandon | Owner, empty object | Terminal abandoned state; history retained |
| POST /sessions/{session_id}/prediction | Owner, selected_answer/reasoning, key | 201 immutable original; conflicting second answer 409 |
| GET /sessions/{session_id}/prediction | Owner | Original or null before submission |
| POST /sessions/{session_id}/attempts | Owner, structured change/explanation, key | 201 independent numbered attempt |
| GET /sessions/{session_id}/attempts | Owner | Ordered preserved attempts |
| POST /sessions/{session_id}/hints | Owner, optional same-session attempt_id, key | 201 recorded fixture interaction, delivered or explicit error |
| POST /sessions/{session_id}/attempts/{attempt_id}/verify | Owner, empty object, key | Real verification run and checks; passed/failed/error |
| GET /sessions/{session_id}/verifications | Owner | Stored runs/checks, including any pending/interrupted state |
| GET /sessions/{session_id}/progress | Owner | Pinned lesson, state, original, attempts, guidance, runs/checks, events and factual summary |
| GET /learners/me/journey | Owner | Explicit original/transfer phase projections, counts, saved session links, checkpoints, server time and last completed activity |
| GET /retrievals/{checkpoint_id} | Owner | Server-derived status, history and a question only when due/completed; no answer key |
| POST /retrievals/{checkpoint_id}/attempts | Owner, selection a/b/c, optional reasoning, retry key | 201 preserved response/outcome/feedback; first correct response completes once |

Request objects reject unknown fields. Predictions use one of rejected/saved/server_error
and bounded original reasoning. The correction schema accepts only:

```json
{"change_type":"rename_payload_field","field_name":"body","explanation":"My proposal"}
```

The original field choices remain body/content. Transfer uses a discriminated
`nest_payload_field` request with field_name flat/nested and optional explanation.
Each variant rejects fields from the other lesson. The service checks the pinned
lesson and requires a saved prediction and observed failed flat verification before
the nested correction; transfer creation requires an owned completed original.
There is no source-code, URL, SQL or arbitrary
payload execution endpoint. A client-supplied success flag or session state is rejected.

## Actual verification boundary

The verifier constructs a fixed note payload from the saved attempt and calls a
private FastAPI `/notes` application through HTTPX2 ASGI transport. This real route
executes NoteCreate validation (`extra=forbid`), dependency injection and committed
SQLAlchemy persistence. It is not publicly mounted on the main server. Public clients
can request only owner-scoped verification, not arbitrary runtime writes.

The run returns expected/observed check records with explicit sources:
http_status, api_response, validation, row_count and stored_values. DB evidence comes
from an independent fresh session. A missing readback is `unavailable`, not zero.
Actual body/422/zero-row evidence is failed correction feedback; content/201/exact
fresh-read evidence passes. API/commit/readback failure or contradictory evidence is
error and does not classify the learner as incorrect. Completion is server-controlled.

The transfer adapter is selected by the pinned lesson identity, separately from its
expected answer. It calls a private real /tasks route with TaskCreate and nested
TaskMetadata (`extra=forbid`, bounded title, allowlisted priority). Flat priority
produces actual 422/missing metadata/extra priority and a fresh zero-task read;
nested metadata.priority produces actual 201 and a committed row with matching
ID/title/priority. The five evidence codes and infrastructure-error distinction are
shared. runtime_tasks and runtime_notes are isolated, each linked to its exact run.

## Retrieval contract

Completion schedules two records atomically, due +24/+168 UTC hours from that
transfer session's completion. Source/ordinal is unique and schedule/question identity
is immutable. There are no client-supplied due dates or completion flags. GET responses
return server_time and a status of upcoming, due or completed. A missed checkpoint
stays due. A pre-due read returns question=null; pre-due submission conflicts. A due
question contains new payload/schema/options, not previous hints or an answer key.
Feedback appears only in stored submitted responses. Upcoming question content is
not prefetched by the UI.

Submission uses the same UUID Idempotency-Key header and origin/client protections.
Same key/payload replays the original response, including after completion; changed
payload conflicts. New responses append with unique sequence numbers while due;
new-key submissions after completion conflict. Foreign/missing checkpoints both 404.
Journey phase completion is derived from persisted sessions, not editable phase flags.
The public schema now contains 18 paths / 20 operations; neither /notes nor /tasks
nor any production clock-control endpoint is exposed.

## Errors

Application errors retain Module 1's envelope:

```json
{"error":{"code":"conflict","message":"The original prediction is locked and cannot be replaced.","request_id":"opaque-id","details":[]}}
```

401 invalid credential; 403 unsafe write origin/header; 404 inaccessible/absent
resource; 409 retry/state/history conflict or hint limit; 422 schema violation;
503 unavailable persistence. Unexpected errors remain generic. Validation errors
omit submitted values/exception context. Correlation IDs are not credentials.
CORS preflight rejections retain Starlette's standard access-policy response.

## Not implemented

External reminder delivery, adaptive scheduling, live providers,
accounts/recovery, export/deletion and deployment endpoints remain future work. The current progress
summary describes stored events, not mastery, retention or learning improvement.
