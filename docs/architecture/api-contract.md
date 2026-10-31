# API contracts — Module 2

FastAPI-generated `backend/openapi.json` and `src/lib/api/schema.d.ts` describe the
implemented API. Regenerate with `npm run api:generate`; a second generation must
produce identical bytes. No planned endpoints are inserted into OpenAPI as stubs.

## Identity, authorization and writes

`POST /api/v1/learners/anonymous` accepts `{}` and creates/reuses an anonymous identity.
It returns learner ID/expiry, never the credential. The host-only HttpOnly cookie
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

Request objects reject unknown fields. Predictions use one of rejected/saved/server_error
and bounded original reasoning. The correction schema accepts only:

```json
{"change_type":"rename_payload_field","field_name":"body","explanation":"My proposal"}
```

The only field choices are body/content. There is no source-code, URL, SQL or arbitrary
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

Transfer/revisit/follow-up scheduling, aggregate course progress, live providers,
accounts/recovery and deployment endpoints remain future work. The current progress
summary describes stored events, not mastery, retention or learning improvement.
