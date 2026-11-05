# Gemini tutor and support integration

This continues the existing provider-independent architecture. It adds a real
Gemini transport and two protected APIs; it does not change deterministic lesson
verification, learner completion, historical lesson versions or review scheduling.
Implementation is on `codex/gemini-free-tier-integration`, uncommitted for review.

The current full [OpenAPI export](api/gemini-openapi.json) has **24 paths / 26
operations**, matching `backend/openapi.json`. The previous 24 operations and
their public schemas remain unchanged. The separate handoff at `75b41d1` and its
historical exports are preserved. Regenerate types with `npm run api:types`.

## Protected HTTP APIs

Both operations require a valid Supabase **access-token Bearer**, an active local
account with the learner role, the allowed browser Origin and
`X-Trace-Client: learning-web`. Send JSON with `credentials: "include"` and
`cache: "no-store"`. A guest cookie is insufficient; an invalid Bearer never
falls back to a guest. Never send a provider key to either endpoint.

These are read-only POSTs. They do not store exchanges, alter attempts, consume
fixture-hint slots, complete lessons or create assignments. No Idempotency-Key is
required. Repeated questions consume provider/request allowance; saved-reply
replay across processes or restarts is not implemented.

### Lesson tutor

`POST /api/v1/sessions/{session_id}/tutor/ask`

```json
{"question":"What does extra forbid mean in the receiving model?"}
```

`TutorQuestionCreate.question` is a nonblank plain-text string of 1–400 characters.
Unknown properties, invalid UTF-8 and obvious credentials/personal email addresses
are rejected. The UUID session must belong to the signed-in learner. Missing and
foreign sessions both return 404. Abandoned or unsupported pinned versions return
409. The initial pilot supports the existing Notes/Tasks version `1.0.0`.

The server reuses the existing fresh storage authorization, validates the pinned
public lesson, derives the current stage, closes the database read, then calls
the application-owned AI client. It checks current authorization and saved state
again before release. Clients cannot supply evidence, correctness, hint policy,
lesson content, source IDs, model choice or completion decisions.

Example `LessonAssistantReply`:

```json
{
  "status":"answered",
  "text":"With extra='forbid', a receiving Pydantic model rejects keys that are not declared in that model. Intended values must also appear under the right keys and at the right JSON level.",
  "source":"ai",
  "interpretation_only":true,
  "can_complete_lesson":false
}
```

This pilot uses **Gemini to match a question to approved explanatory text**. The
backend renders that text. Gemini cannot create a new observation, supply a full
fix or overrule verification. The finite guidance covers request contracts,
validation ordering, forbidden extra fields, JSON levels, evidence limits and
server-observed run status. This is not unrestricted chat or model-authored grading.

`declined` means none of the approved guidance answers the question; `unavailable`
means no valid provider selection was obtained. Unavailable replies use
`source: "none"`; real selections use `source: "ai"`. Explicit offline test
injections retain `test_fixture` provenance and visible fixture labels.

The existing panel's concept, ask and why-failed actions use this single endpoint.
The backend loads the actual session/run context; it never trusts the client run.
Full worked explanations remain unavailable in real mode. The existing fixture
hints continue through the unchanged `/sessions/{session_id}/hints` endpoint.

### Support RAG

`POST /api/v1/support/ask`

```json
{"question":"When are the follow-up reviews due?"}
```

`SupportAskCreate.question` is nonblank plain text, 1–500 characters. The API
accepts no route, conversation ID, document path, source selection, learner ID or
history payload. The frontend adapter sends only the question. Support uses
account admission without creating a learner history, preserving guest-claim
choices. Account expiry/status/role is checked again after provider work.

An illustrative `SupportResponse` using an actual approved passage:

```json
{
  "status":"answered",
  "message":"Relevant approved documentation is quoted below.",
  "references":[{
    "source_id":"progress-retrieval",
    "source_name":"Saved progress and follow-up reviews",
    "passage_id":"retrieval-one-seven-days",
    "quote":"Completing the Tasks transfer lesson schedules two review checkpoints at one and seven elapsed days after transfer completion. The journey shows upcoming, due and completed checkpoints. A due checkpoint remains available if you missed its original due time."
  }],
  "escalation":null,
  "source":"ai"
}
```

The existing bounded lexical retriever selects at most three passages. Gemini
selects only from those passage IDs; the server returns exact source quotations.
It cannot invent prose, policies, account actions, references or links. Invalid
or unretrieved citations reject the entire answer. Sources are rechecked after
the call, so stale, changed or newly unavailable content is not released.

`no_sources` means retrieval found no matching approved information. `unsupported`
means the retrieved passages did not establish an answer. Both have empty
references. `unavailable` covers missing configuration, provider failure, invalid
output or unavailable review metadata. There is no model or mock fallback.

The UI renders quotes and response-local source anchors; it does not invent a
documentation lookup API. Conversation text remains in the page session only.
Trace does not persist exchanges, but Gemini processes submitted questions under
Google's API terms. Do not submit private information or credentials. Pattern
guards are supplementary, not a complete personal-data detector.

## Approved support corpus

The owner approved the exact [corpus](../backend/app/support/corpus.json) and
[review record](support-corpus-review.md): nine customer articles / 19 passages,
reviewed by Soorej on 2 November 2026 at 15:34:07 UTC, valid until
2 December 2026 at 15:34:07 UTC. Per-document canonical digests bind the wording.

Sources: `trace-overview`, `registration-authentication`, `google-authentication`,
`learning-navigation`, `prediction-attempts-verification`, `hints-explanations`,
`progress-retrieval`, `daily-availability`, `technical-problems`.

Only the fixed corpus file is loaded. There is no repository crawl, client/model
file selection, log ingestion, embedding service or learner-record retrieval.
Review, expiry and digest checks run on use. Missing/expired/changed reviews close
the corpus. The old `docs/support-drafts/` remain historical drafts, not sources
loaded by the application. No escalation contact or SLA has been invented.

## Configuration: backend only

Approved pilot: `gemini-3.1-flash-lite`, credential variable `GEMINI_API_KEY`,
Free Tier project **with no billing**, no paid fallback. The official
`google-genai` SDK is locked at `2.34.0`; services still use Trace's existing
provider-neutral interfaces and shared, application-owned bounded client.

1. Open `backend/.env.gemini` privately. If it does not exist, copy the blank
   [credential example](../backend/.env.gemini.example) to that filename first.
   Fill the `GEMINI_API_KEY` value in your editor and save. The real file is ignored
   by Git. Do not overwrite an existing credential file with the example.
2. Alternatively set the same variable in the backend process environment. The
   startup helper can inherit a Windows User environment variable. There is no
   `GOOGLE_API_KEY` fallback. Never put the key in `.env.local`, `NEXT_PUBLIC_*`,
   source, chat, command-line arguments or Git.
3. Keep the existing backend `.env` for its existing database/auth settings.
   Its strict settings loader does not accept arbitrary AI/provider variables.
4. Start the backend explicitly from the repository root:

```powershell
.\scripts\run-gemini-backend.ps1 -ConfirmFreeTierProject
```

The helper selects only the approved model, zero paid budget, no retries and a
20-call per-process pilot ceiling. It does not migrate or seed the database.
Stop the previous listener on port 8000 before starting another server.

To configure another launch method, set process variables:

```dotenv
TRACE_LLM_MODE=gemini_free
TRACE_LLM_PROVIDER_ID=gemini
TRACE_LLM_GENERATION_MODEL_ID=gemini-3.1-flash-lite
TRACE_LLM_CONVERSATIONAL_MODEL_ID=gemini-3.1-flash-lite
TRACE_LLM_CREDENTIAL_ENV_VAR=GEMINI_API_KEY
TRACE_LLM_FREE_TIER_PROJECT_CONFIRMED=true
TRACE_LLM_SPEND_LIMIT_MICROUSD=0
TRACE_LLM_MAX_COST_PER_ATTEMPT_MICROUSD=0
TRACE_LLM_MAX_RETRIES=0
TRACE_LLM_MAX_LIVE_REQUESTS_PER_PROCESS=20
```

These are public configuration values, not credentials. The confirmation flag
records operator attestation; the application cannot independently prove the
Google project's billing state. Keep billing disabled at Google. Free quotas
and availability depend on Google; errors stay honest unavailable responses.
See [Google model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite)
and [pricing/data-use information](https://ai.google.dev/gemini-api/docs/pricing).

Without explicit configuration, AI remains disabled. Startup validates complete
free-tier configuration, never silently activates a provider and never chooses
another model. Backend health readiness checks database readiness, not Gemini
availability. A key alone does not activate these application paths.

## Frontend setup and calls

Use the existing Supabase/account configuration and API origin. There is no new
frontend credential.
The existing [frontend environment example](../.env.local.example) supplies the
API, shared Supabase public settings and callback-origin variable names. Select
real adapter mode before starting/building Next:

```powershell
$env:NEXT_PUBLIC_AI_MODE = 'real'
npm run dev
```

The default remains labelled demo mode. Real mode enables tutor/support API calls;
it does not make interests, daily assignments or custom generation available.
The existing typed API client adds auth, performs one SDK token refresh on 401,
preserves Origin/client headers and maps errors. Do not create a second fetch stack.

```typescript
import { aiApi } from '@/lib/api/client';
const guidance = await aiApi.tutor(sessionId, 'How does request validation work?');
const support = await aiApi.support('When are review checkpoints due?');
```

Use `Schema['LessonAssistantReply']` and `Schema['SupportResponse']` from the
generated contract. Keep drafts during requests. Render unavailable/declined and
empty-source states explicitly. Text is text, never HTML. Do not claim that a
provider reply is execution evidence, a grade or a lesson-completion decision.

## Operational behavior

Defaults, separately per tutor/support operation: five requests per rolling
minute per authenticated account; one in-flight worker per account and two
globally; bounded ingress before auth; a 20-second request deadline capped by the
general HTTP limit. The operation's 10-second provider cap is also forwarded to
the shared client and transport; a smaller configured cap cannot be enlarged by
the adapter. Body/response buffering and no-store apply across statuses,
including validation, rate, timeout and error responses. User-facing errors are
sanitized and contain no raw provider diagnostics.

The shared provider client bounds requests, schemas, tokens, response bytes,
timeouts and usage. Google requests are pinned to the approved HTTPS model
endpoint; redirects, proxies, tools, code execution, alternate models, SDK retries
and paid fallback are disabled. Request/provider resources are application-scoped.
No database write transaction is held while waiting on Gemini.

Limits/counters are process-local, not distributed billing enforcement. The
20-call pilot ceiling resets on restart; it is not a learner daily-assignment
quota. Running synchronous work keeps its permit after HTTP cancellation until
it actually exits. A Python thread cannot be forcibly cancelled safely.

HTTP errors: 401 auth/expiry; 403 origin/account/role; tutor 404 absent/foreign
session; tutor 409 abandoned/unsupported/changed saved state; 413 body bound;
422 invalid/sensitive question; 429 admission; 500 sanitized unexpected failure;
503 unavailable dependencies; 504 request deadline. Provider selection failures
normally return a typed HTTP 200 `unavailable` result without invented guidance.

## Generation and release boundary

The internal `CandidateGenerationService` connects the shared QuestionGenerator
to existing content admission, trusted composition, canonical provenance,
candidate persistence and automatic runtime validation. Its brief builder derives
copy slots/wording references from a validated server blueprint. It does not send
private evaluator/runtime configuration to Gemini.

Exact local retries reuse the candidate without another provider call. Changed
inputs conflict. Database constraints remain authoritative across processes;
cross-process provider-call deduplication is not claimed. Runtime validation uses
the unchanged Notes/Tasks adapters and independent database readback.

Technical success ends at a `validated` candidate with pending review and
`release_eligible=false`. No generation job HTTP endpoint, human-review workflow,
production registry, learner delivery or assignment system is enabled here.
Malformed generation is rejected without substituting fake copy. Existing seeded
lessons/hashes and +1/+7 retrieval scheduling remain unchanged.

## Validation commands

Offline suites never need a real key. Run backend pytest, Ruff, formatting and
mypy, then frontend unit/lint/type/build and the existing browser suite. The
dedicated `playwright.ai.config.ts` exercises the real frontend adapter over
protected HTTP with explicitly labelled fixture providers on ports 3200/8100/8101.
It is not a live-Gemini quality claim.

For the approved minimal real check, from `backend/`:

```powershell
.venv\Scripts\python.exe -m scripts.check_gemini --live --confirm-free-project --generation
```

This makes at most three provider attempts over public/synthetic content, reports
only safe metadata and source IDs, and uses a disposable database for a generated
candidate. It neither modifies development learner history nor publishes content.
Without credentials or explicit flags it makes no live requests. A partial or
unavailable result is a failed/partial check, not a passing live integration.
