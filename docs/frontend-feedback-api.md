# Trace feedback API: MVP integration addendum

This adds the authenticated feedback experience to the unchanged, historical
[frontend API handoff](frontend-api-integration.md). The published handoff and
`docs/api/openapi.json` remain byte-for-byte unchanged. The current full contract
is [feedback OpenAPI](api/feedback-openapi.json), also exported to
`backend/openapi.json`: **22 paths / 24 operations**. Only one operation was added;
the existing 23 operations retain their contracts.

## For Sohaib: the available integration

`POST /api/v1/sessions/{session_id}/feedback`

- Signed-in accounts only: use the existing Supabase access-token Bearer flow.
  A guest cookie alone returns 401. Local learner role and session ownership are
  required; a foreign/missing session returns the same 404 response.
- Keep the existing guest-history claim decision **before** authenticated
  learner bootstrap/journey calls. This endpoint does not merge histories.
- Required JSON body is exactly `{}`. There is no client evidence, prompt,
  correctness, provider, answer, policy, time-window or learner-ID input.
- Use the allowed browser Origin, `X-Trace-Client: learning-web`,
  `Content-Type: application/json`, `Authorization: Bearer <SDK access token>`,
  `credentials: "include"` and `cache: "no-store"`.
- An Idempotency-Key is not required: this operation recomputes a read-only
  projection and does not create or alter learning history. Avoid automatic
  retry loops; every request counts toward admission limits.
- Existing API-origin configuration still applies. No provider key or new
  frontend credential is needed.

Call from an explicit **View feedback / Refresh feedback** action after a saved
attempt or after completion. Read progress after attempt/verification first.
Do not request on every render, on every keystroke or from a polling interval.
Preserve the current lesson panel/draft while loading. Cancel obsolete browser
waits, but do not assume cancellation stopped server work.

The server reuses C1/C2: current account/learner mapping, ownership, pinned
lesson, first-attempt visibility, exact evidence cohort/source fences, final
storage authorization, public claim filtering and response-local citations.
Completed-session reflection is approved. Abandoned sessions are excluded
before evidence/provider evaluation. Guests, recall claims, generic next actions
and repair hints are not enabled by this route.

## Successful HTTP response states

All successful responses use `PublicFeedbackReply` with schema version
`evidence-feedback-public-v1` and policy version
`evidence-feedback-visibility-v1`. Use the generated OpenAPI schema for every
field and bound; do not treat internal evidence schemas as response contracts.

| Field | Frontend meaning |
| --- | --- |
| `availability` | `available`, `not_ready`, `not_supported` or `unavailable`. |
| `feedback_state` | `supported`, `partially_supported`, `insufficient_evidence`, `unavailable` or null for an unevaluated closed gate. This is evidence coverage, not a score. |
| `delivery_state` | This public MVP emits `deterministic` for available feedback, otherwise `unavailable`. The shared schema also describes mock output for internal uses; the HTTP policy never enables mock delivery. |
| `session_id` | The authorized requested session reference. |
| `lesson` | Public lesson slug/version/public-content SHA-256, or null when closed/unavailable. No private lesson hash or database version UUID. |
| `as_of` | Server evidence cutoff, or null when closed/unavailable. |
| `sections` | Optional sections with `kind` and `items`; render only those present. Kinds are demonstrated, needs_improvement, why, next; this policy does not emit next actions. |
| Statement | `role`, `text`, `evidence_aliases`, `lesson_aliases`. Treat text as text, never HTML. |
| `evidence_citations` | Local alias, friendly description, event time and category/matched checks. No expected/observed values, source UUIDs or raw runtime payload. |
| `lesson_citations` | Local alias, public lesson identity, public field/label and digest. No arbitrary document paths or URLs. |
| `notice` | Display the supplied finite public notice, including the deterministic-delivery label. |

Normal empty states:

- `not_ready`: no legitimate attempt yet; render the notice and keep the existing
  learning controls. No correctness, lesson, sections or citations are returned.
- `not_supported`: abandoned session or unsupported pinned lesson/version;
  render the notice without inventing feedback.
- `unavailable`: source/output could not be validated; show the notice and an
  explicit retry action. Do not substitute fabricated model feedback.
- `available` with `insufficient_evidence`: render only the supplied limited
  facts/limitations. Missing evidence is not a failed competency.

An example before an attempt, with a fabricated session UUID:

```json
{
  "schema_version":"evidence-feedback-public-v1",
  "policy_version":"evidence-feedback-visibility-v1",
  "availability":"not_ready",
  "feedback_state":null,
  "delivery_state":"unavailable",
  "session_id":"30000000-0000-4000-8000-000000000001",
  "lesson":null,
  "as_of":null,
  "sections":[],
  "evidence_citations":[],
  "lesson_citations":[],
  "notice":"Feedback is not ready until an attempt has been submitted."
}
```

For available feedback the notice is normally
`This feedback uses deterministic evidence rules.` This is a working backend
feature, **not live model-generated assessment**. The provider only has a future
optional explanatory role; trusted code already determines all substantive facts.

Citation aliases such as `e1`/`l1` mean something only inside that response. They
are not stable history IDs, resource URLs or credentials. Build citation display
from that same response; there is no citation lookup endpoint. Filtered claims
and their orphan/dependent citations are removed together by the backend. Never
reconstruct omitted claims or a hidden correct mapping on the frontend.

## TypeScript wiring

The checked-in generated declaration `src/lib/api/schema.d.ts` is refreshed
from the backend export because CI enforces exact contract generation. No
handwritten frontend client or screen source is changed. Sohaib can now use
`components["schemas"]["PublicFeedbackReply"]`; `npm run api:types` remains the
command for regenerating it after future backend contract updates.

```typescript
import type { components } from "@/lib/api/schema";
type Feedback = components["schemas"]["PublicFeedbackReply"];

async function loadFeedback(
  apiOrigin: string, sessionId: string, accessToken: string, signal?: AbortSignal,
): Promise<Feedback> {
  const response = await fetch(
    `${apiOrigin.replace(/\/$/, "")}/api/v1/sessions/${encodeURIComponent(sessionId)}/feedback`,
    {
      method: "POST", credentials: "include", cache: "no-store",
      signal: signal ?? AbortSignal.timeout(12_000),
      headers: {
        "Authorization": `Bearer ${accessToken}`,
        "Content-Type": "application/json",
        "X-Trace-Client": "learning-web",
      },
      body: JSON.stringify({}),
    },
  );
  if (!response.ok) {
    const failure = await response.json().catch(() => null);
    throw Object.assign(new Error(failure?.error?.message ?? "Feedback unavailable."), {
      status: response.status,
      code: failure?.error?.code,
      requestId: response.headers.get("X-Request-ID"),
    });
  }
  return response.json() as Promise<Feedback>;
}
```

Do not print the token, response evidence or raw drafts in application logs.
Refresh the SDK session after 401; do not silently remove Bearer and act as a
guest. On 409 refresh progress before asking for feedback again. On 429 stop
automatic retries and let the user retry later. Preserve UI state on 503/504 or
transport failure. A cancelled/expired request may have finished read-only work
but cannot change a prediction, attempt, completion or retrieval schedule.

## HTTP errors and operational limits

Feedback responses, including validation/authentication/authorization/rate-limit,
timeout/error responses, OPTIONS and redirects, carry `Cache-Control: no-store`,
`Pragma: no-cache` and `Expires: 0`. Allowed-origin CORS and `X-Request-ID`
exposure are preserved on replacement errors. Error responses use the existing
`ErrorResponse` envelope with fixed messages and empty details, so submitted
field names, private exception messages and provider diagnostics cannot leak.

| HTTP | Meaning |
| --- | --- |
| 401 | A valid signed-in account is required, or authorization expired. |
| 403 | Origin/client header denied, account disabled or learner permission missing. |
| 404 | Session absent or owned by another learner. |
| 409 | Saved session/evidence changed while feedback was being prepared. Refresh progress. |
| 413 | Request body exceeds its feedback bound. |
| 422 | Body/path schema invalid; only `{}` and a UUID session path are accepted. |
| 429 | Feedback rate/admission/concurrency capacity exhausted. |
| 500 | Sanitized unexpected/output failure; no raw internal error content. |
| 503 | Dependency/application resources unavailable. |
| 504 | Feedback request deadline expired; no partial feedback is emitted. |

Defaults are **per application process**, not distributed production quotas:

- Global ingress: 120 requests per rolling minute and 16 in flight, before auth.
- Per authenticated account: 10 requests per rolling minute and one worker in
  flight; up to four evaluation workers globally. Subject state is bounded at 1,000.
- Total request deadline: 8 seconds; optional provider wait: 2 seconds, also
  bounded by the remaining request deadline.
- Feedback body: 4,096 bytes; response buffer: 65,536 bytes. Output is buffered
  and validated before sending, with no partial internal response on failure.

The effective feedback request/body limits are capped by the existing global
HTTP limits, and the provider budget cannot exceed that effective request
deadline. Shortening a global timeout cannot leave a longer feedback budget.

Configuration is `FeedbackSettings`, supplied through application injection or
process environment variables named `TRACE_FEEDBACK_REQUESTS_PER_MINUTE`,
`TRACE_FEEDBACK_MAX_SUBJECTS`, `TRACE_FEEDBACK_MAX_SUBJECT_IN_FLIGHT`,
`TRACE_FEEDBACK_MAX_GLOBAL_IN_FLIGHT`, `TRACE_FEEDBACK_INGRESS_REQUESTS_PER_MINUTE`,
`TRACE_FEEDBACK_MAX_INGRESS_IN_FLIGHT`, `TRACE_FEEDBACK_REQUEST_TIMEOUT_SECONDS`,
`TRACE_FEEDBACK_PROVIDER_TIMEOUT_SECONDS`, `TRACE_FEEDBACK_MAX_REQUEST_BYTES` and
`TRACE_FEEDBACK_MAX_RESPONSE_BYTES`. No secrets are involved. These separate
settings intentionally do not load `backend/.env`; do not add these names to that
strict existing dotenv file without a separate configuration change.

The optional provider wrapper performs a bounded wait and falls back to newly
rendered trusted deterministic text on timeout, exception or invalid output.
Fresh authorization/source fencing still runs before release. A synchronous
provider that ignores cancellation cannot be killed safely: its provider lease
remains occupied until it actually exits, preventing oversubscription; request
workers likewise retain permits through actual completion after HTTP cancellation.
Repeated requests cannot manufacture unbounded provider jobs. Future live
adapters must enforce transport deadlines; hung Python threads may delay process
shutdown. No live provider is enabled in this MVP.

## Meeting demo and release boundaries

Use the real signed-in Notes journey, inspect an initial prediction and saved
attempt, run verification, then request feedback. Complete Notes and Tasks and
show completed reflection with actual verification-category outcomes. The
trusted evidence explains observed actions; it does not prove investigation,
independent diagnosis, exact submitted code changes or a historical Notes parent
for a Tasks session. There are no competency scores or mastery claims.

Sohaib owns the actual browser screen/client hookup. Backend tests use controlled
JWT keys and disposable SQLite; they do not prove Google sign-in, hosted
deployment, shared-project JWKS reachability or the final browser journey. Verify
those separately before presenting a full end-to-end release as complete. No
guest audience, live AI, support corpus, assignment policy or retrieval reschedule
is activated. Existing learner routes and +1/+7 behavior remain intact.
