# Trace AI platform handoff

This guide describes the implemented local integration. Public hosting has not
been provisioned. It does not certify another developer's machine, an external
OAuth dashboard, production traffic or provider billing.

## Private configuration on each machine

Use a separate clone and local development database on each machine. Do not copy
another learner's SQLite database, tokens, cookies or private environment files.

| Destination relative to the clone | Safe template | Responsibility |
| --- | --- | --- |
| `.env.local` | `.env.local.example` | Frontend API base URL, intended Supabase public project settings, `NEXT_PUBLIC_AI_MODE=real` |
| `backend/.env` | `backend/.env.example` | Local database, matching Supabase issuer/JWKS/audience, allowed frontend origins, local cookie settings |
| `backend/.env.gemini` | `backend/.env.gemini.example` | Server-only `GEMINI_API_KEY`, configured privately |
| Process environment | `backend/ai.env.example` | Explicit AI activation; the example file is not automatically loaded |
| Approved deployment secret manager | `deploy/production.env.example` | Private PostgreSQL TLS URL and production settings; never frontend variables |

On Soorej's machine the clone is
`C:\Users\soore\OneDrive\Dokumen\ChatGPT\Trace-v1`. The correct key file is
`C:\Users\soore\OneDrive\Dokumen\ChatGPT\Trace-v1\backend\.env.gemini`.
`backend/backend/.env.gemini` is a misplaced duplicate and is not the supported
destination. Existing private files have been preserved.

Use the same intended Supabase project in frontend and backend. This frontend's
validator expects the publishable-key format in
`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`. A service-role key, Gemini key or database
password never belongs in a frontend setting.

## Start and diagnose

From the repository root:

```powershell
uv sync --directory backend --locked
npm ci
uv run --directory backend --locked --no-sync python -m scripts.ai_setup_check
./scripts/run-gemini-backend.ps1 -ConfirmFreeTierProject
```

In a second terminal:

```powershell
npm run dev
```

The equivalent portable backend command is:

```sh
uv run --directory backend --locked --no-sync python -m scripts.run_gemini --confirm-free-tier-project
```

`--check` validates the launch configuration without a provider call. Plain
Uvicorn does not activate the Gemini profile. Frontend public variables are read
at dev-server startup/build time; restart after changing them. Use one hostname
consistently, preferably `http://localhost:3000`, with API base
`http://localhost:8000` (the server still binds only to `127.0.0.1`). Configure
CORS for the exact frontend origin. The frontend
must not call a teammate's loopback address as though it were shared hosting.

Readiness: `GET /api/v1/health/ready`; local Swagger: `/docs`; current machine
contract: `backend/openapi.json`; generated frontend types:
`src/lib/api/schema.d.ts`. Historical `docs/api/openapi.json` remains historical.
Apply migrations to each local database using the documented backup/forward
procedure. Do not reset an existing database to resolve an old schema.

## Available learner integration

Use `aiApi` from `src/lib/api/client.ts` for tutor and support calls. It supplies
the configured API base, Bearer authorization and browser headers. AI POSTs are not automatically replayed
after a 401 because another provider request could consume allowance.

The separate feedback route below has an HTTP/OpenAPI contract; it does not yet
have an `aiApi` helper or a learner feedback UI in this change.

| Endpoint | Request | Result |
| --- | --- | --- |
| `POST /api/v1/sessions/{session_id}/tutor/ask` | Existing `{question}` | Existing finite authored-guidance contract |
| Same tutor endpoint | `{mode:"conversation",question,style,code?,history?}` | Natural-language advice, explicit `execution_status:"not_executed"` |
| `POST /api/v1/support/ask` | `{question}` | Exact eligible passage quotations and response-local source references |
| `POST /api/v1/sessions/{session_id}/feedback` | Existing feedback request | Deterministic, privacy-filtered reflection; separate from conversational advice |

Authentication is required for AI calls. Tutor calls also require an owned,
eligible pinned Notes or Tasks session. Guest cookies do not grant AI access.
Both API writes require an allowed Origin and
`X-Trace-Client: learning-web`. Missing/expired tokens produce 401, forbidden
roles/origins 403, foreign and missing sessions 404, stale saved work 409, invalid
input 422, exhausted admission 429, dependency failure 503 and deadline expiry
504. An HTTP 200 with `status:"unavailable"` is also an honest provider failure
state. Do not replace it with a successful demo answer.

```ts
import { aiApi } from "@/lib/api/client";

const reply = await aiApi.conversation(sessionId, {
  mode: "conversation",
  question: "How is an API schema different from a database schema?",
  style: "direct",
  history: [],
});
const help = await aiApi.support("When are follow-up reviews due?");
```

See [the complete conversational contract](open-ended-tutor-contract.md) for
precise bounds and the SDK signature. Conversation history is page/session
memory, not persisted evidence: at most six bounded messages are sent, and it is
cleared on account/session change or explicit clearing. Learner code and prior
assistant messages are untrusted input. The model receives no account identifiers,
hidden checks or tools. Suggested code is never executed by chat.

The existing panel supports adaptive, Socratic and direct styles, optional code,
follow-ups, explicit worked-example requests, loading, cancellation and clearing.
Cancellation stops waiting; actual provider cleanup retains its allowance lease.
The response is rendered as text. Saved verification remains the only authority
over lesson completion. The +1/+7-day review schedule is unchanged.

Support references contain `source_id`, `source_name`, `passage_id` and exact
`quote`; render those fields without inventing source URLs. No support-source
selection, file path or document upload is accepted from a learner. Production
requires published database knowledge and a committed minimal release receipt.
Missing, changed, expired or revoked knowledge withholds quotations.

The preserved pilot's `tutor-guidance-limit` paragraph describes its older guided
mode. The exact conversation-capability replacement is a draft under
`backend/app/support/drafts/` and needs human review before production corpus
publication. Treat that older paragraph as legacy-scope documentation, rather
than the contract for the new conversation mode. No production corpus was
published by this task.

Question generation remains an internal capability. The application-scoped
`CandidateGenerationService` uses the shared `QuestionGenerator` and the
existing trusted composition, runtime validation and candidate lifecycle. There
is no public generation/daily-delivery endpoint to call from the frontend, and
generation does not automatically approve, publish or assign a candidate. This
block did not perform a new live generation attempt.

## Administrative knowledge operations

These are backend administration APIs, not learner UI integration. Each requires
current Supabase authentication, a fresh database-admin role, allowed browser
origin, no-store responses and bounded admission. Token metadata cannot grant
the admin role.

| Method/path beneath `/api/v1/admin/knowledge` | Purpose |
| --- | --- |
| `POST /revisions` | Ingest explicit bounded customer-facing document content |
| `GET /revisions/{revision_id}` | Read immutable revision and lifecycle history |
| `POST /revisions/{revision_id}/transitions` | Advance the permitted lifecycle with expected sequence and operation key |
| `POST /import-reviewed-corpus` | Import the exact existing corpus; review adoption must be explicit |
| `POST /publications` | Explicitly publish eligible reviewed revisions |
| `GET /receipts/{receipt_id}` | Read a minimal historical release receipt |
| `POST /indexes/build` | Embed the server-selected published corpus and archive a derived index |

Index-building accepts only `operation_key`; clients cannot supply models,
vectors, paths or publication flags. Building a candidate index never activates
retrieval. Repeating a completed key reuses the archived result without another
RPC. Concurrent conflicting keys/operations may fail and must not be blindly
retried. No actual local user has been silently granted an admin role.

An approved database operator can use the existing controlled-checkout
`python -m scripts.grant_role --user-id <approved-existing-user-uuid> --role admin
--reason <approved-audit-reason>` procedure from `backend/`. This records a role
grant audit event; it is not a self-service learner action and was not executed
by this task. Never grant a role merely to bypass an acceptance failure.

For a new revision, the explicit transitions are `parse`, `normalize`, `chunk`,
`index`, `validate`, `review`, `approve`, then the separate publication operation.
Read the latest history and use `events[events.length - 1].sequence` as
`expected_sequence`; a stale sequence returns a conflict. Review must attest the
exact normalized document digest and approval must supply the approved future
validity. No generated timestamp or operation key substitutes for human review.

## Semantic retrieval and operating limits

The provider-neutral embedding layer supports real `gemini-embedding-001`
document/query vectors, exact 768-dimension validation, immutable versioned index
metadata and lexical/semantic/hybrid ranking. It uses the standard embedding RPC,
not the paid asynchronous Batch API. Paid budget and automatic retries remain
zero. Embeddings are disabled by default.

The live benchmark attempt was rate-limited; it produced no usable quality
comparison. The 94 reference labels also require independent review. Production
vector activation is therefore rejected explicitly. Local/internal experiments
require an explicit experiment setting, enabled embedding profile and matching
archived index digest. Production lexical retrieval remains active when its
published corpus is available.

Every production profile requires `TRACE_ACCOUNTING_MODE=durable` and an explicit
stable `TRACE_ACCOUNTING_SCOPE`. Provider attempts and admission are shared across
processes. A scope is a cumulative allowance, not a promised daily quota or
provider billing measurement. Restarting a process does not refund it. Missing
usage is recorded as unknown. Crashed leases need explicit authenticated operator
reconciliation after proof the worker stopped; there is no automatic refund or
paid fallback. Use a short stable scope name so per-capability namespaces fit.

The read-only `python -m scripts.platform_status` reports schema health, corpus
eligibility and aggregate durable usage without making a live AI probe. It does
not print secrets, questions, answers or learner identities. See
[production operations](../deployment/production-backend.md) and
[hosting decision](../architecture/adr-production-hosting.md) for TLS, backup,
rollback, monitoring and approval prerequisites.

## Acceptance owned by each developer

Follow [Sohaib's setup acceptance](sohaib-gemini-setup.md) on each machine. Sign in
privately, open an owned Notes/Tasks session, ask a natural-language tutor question
and a follow-up, then ask Help a supported public-document question. Confirm AI
provenance, exact sources, no demo-success substitution, no completion mutation,
and unavailable behavior when the provider is disabled. Do not paste credentials
into chat or screenshots.

External Supabase email delivery, Google provider enablement, consent-screen
configuration, redirect allowlists, session revocation and production-domain
cookies require the project owner's dashboard and real-account acceptance. The
automated fixture suite does not certify those external settings. Public hosting,
paid resources and production promotion remain subject to separate approval.
