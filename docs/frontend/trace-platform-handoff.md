# Trace AI platform handoff

This guide describes the implemented local integration. Public hosting has not
been provisioned. It does not certify another developer's machine, an external
OAuth dashboard, production traffic or provider billing.

The current generated contract has **46 paths / 50 operations** after the private
guide, durable GitHub authorization and repository-question additions. Historical 21/23, 31/33 and 41/45 inventories describe
earlier milestones. Use `backend/openapi.json` and `src/lib/api/schema.d.ts` for
the current app, and [the acceptance report](../reports/trace-ai-and-github-acceptance.md)
for precise automated, live-provider and external-setup status.

## Private configuration on each machine

Use a separate clone and local development database on each machine. Do not copy
another learner's SQLite database, tokens, cookies or private environment files.

| Destination relative to the clone | Safe template | Responsibility |
| --- | --- | --- |
| `.env.local` | `.env.local.example` | Frontend API base URL, intended Supabase public project settings, `NEXT_PUBLIC_AI_MODE=real` |
| `backend/.env` | `backend/.env.example` | Local database, matching Supabase issuer/JWKS/audience, allowed frontend origins, local cookie settings |
| `backend/.env.gemini` | `backend/.env.gemini.example` | Server-only `GEMINI_API_KEY`, configured privately |
| Process environment | `backend/ai.env.example` | Explicit AI activation; the example file is not automatically loaded |
| Backend process environment | `backend/github.env.example` | Optional GitHub App ID/slug/callback and private App credentials; disabled until owner configuration |
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

The explicit free-tier launcher selects a twenty-second Gemini response budget
only when no tighter response/total deadline was supplied. Tutor and Support
remain bounded to twenty provider seconds within thirty request seconds; token,
rate/concurrency, zero paid allowance and zero retry controls remain. Generic
client and deterministic feedback defaults are unchanged. Plain Uvicorn users
must configure their intended approved profile explicitly.

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
| `POST /api/v1/support/ask` | `{question,history?}` | Exact eligible passage quotations and response-local source references |
| `POST /api/v1/sessions/{session_id}/feedback` | Existing feedback request | Deterministic, privacy-filtered reflection; separate from conversational advice |
| `POST /api/v1/learning-guides` | `GuideCreate` + UUID `Idempotency-Key` | 201 owned `GuideDetail`, including generating/ready/unavailable status |
| `GET /api/v1/learning-guides` | None | Up to fifty owned summaries |
| `GET /api/v1/learning-guides/{guide_id}` | Owned guide UUID | Saved detail/content/provenance; foreign/missing both 404 |

Authentication is required for AI calls. Tutor calls also require an owned,
eligible pinned Notes or Tasks session. Guest cookies do not grant AI access.
API writes require an allowed Origin and
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
const followUp = await aiApi.support("When is that due?", undefined, [
  { role: "user", text: "When are follow-up reviews due?" },
]);
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

Support accepts at most four prior user/assistant messages, each at most 250
characters; the current question remains limited to 500 characters. The server
uses bounded prior dialogue only to resolve conversational references. It is
untrusted data, never source approval or proof of account state. A standalone
unrelated question does not inherit a supported topic. The Help panel sends no
failed assistant replies, keeps history only in panel memory, and clears it with
New chat. Clients cannot provide system messages, source IDs or file paths.

The preserved pilot's `tutor-guidance-limit` paragraph describes its older guided
mode. The exact conversation-capability replacement is a draft under
`backend/app/support/drafts/` and needs human review before production corpus
publication. Treat that older paragraph as legacy-scope documentation, rather
than the contract for the new conversation mode. No production corpus was
published by this task.

Verified executable-lesson generation remains an internal capability. The application-scoped
`CandidateGenerationService` uses the shared `QuestionGenerator` and the
existing trusted composition, runtime validation and candidate lifecycle. There
is no public executable-candidate generation/daily-delivery endpoint to call
from the frontend, and generation does not automatically approve, publish or
assign a candidate. The private guide API below is a distinct instructional
format and does not bypass those rules.

## Private learning guides

The approved broad-topic experience is now wired through the existing `/learn`
custom form, Your lessons list, and `/learn/guides/{guide_id}` reader. It creates
private instructional material with explanations, progressive sections,
unexecuted examples and explicitly ungraded practice. It creates neither an
executable LessonSpec nor a learner assignment/completion decision.

Use `learningGuidesApi` from `src/lib/api/learning-guides.ts`. Its types come from
the generated backend schema. The body includes topic (up to 500 characters),
start/target level (`beginner`, `intermediate`, `advanced`), practical boolean and
optional goals/preferences (up to 600 characters each). Omit empty optional
strings rather than submitting them as valid preferences.

```ts
import { learningGuidesApi } from "@/lib/api/learning-guides";

const requestKey = crypto.randomUUID();
const guide = await learningGuidesApi.create({
  topic: "Python variables",
  start_level: "beginner",
  target_level: "intermediate",
  practical: true,
  goals: "Understand reassignment through small examples",
}, requestKey);
const saved = await learningGuidesApi.get(guide.id);
const mine = await learningGuidesApi.list();
```

Keep the same key and exact body after an uncertain write; that replay returns
the same resource without another generation call. Changing the body under the
same key returns 409. A new deliberate generation uses a new key. Show loading
and the server's generating/ready/unavailable state. Read-only polling can observe
pending status; respect admission limits and never spin on 429. No failed real
request may be replaced with a successful demo guide. Content is rendered as
text, not executed or trusted HTML.

The server owns account identity, version, generation provenance, content digest
and reservation transitions. Provider work runs outside the database write
transaction. It rechecks authorization before finalizing and reading. Foreign
and missing guide IDs both return 404. The additive 0010 migration preserves
history and refuses a populated downgrade. See [the full private-guide contract](../private-guides-contract.md)
for bounds, expiry, concurrency, provenance and error semantics. Automated
fixtures do not establish genuine Gemini guide acceptance.

## GitHub App Project Learning

GitHub repository connection is separate from optional Supabase GitHub social
login. A signed-in learner opens `/projects`, installs the owner-configured App
on selected repositories, then explicitly authorizes that App as a GitHub user.
The `/projects/github/callback` flow strips sensitive query parameters before
completing the protected backend exchange. Supabase GitHub sign-in alone grants
no repository access.

Use `githubProjectsApi` from `src/lib/api/github-projects.ts`. All endpoints below
share `/api/v1/projects/github`, require authenticated learner ownership and
return no-store responses. Writes additionally require an allowed Origin and
`X-Trace-Client: learning-web`; GET authentication does not require those write
headers. There is no client-selected file loader, source allowlist or provider.

| Method/path beneath the prefix | Request | Result |
| --- | --- | --- |
| POST `/installations/start` | No body | Fixed GitHub installation/user-authorization URLs, state and expiry |
| POST `/installations/complete` | `{installation_id,code,state}` | Owned installation summary, authorization expiry/status; no tokens |
| GET `/installations` | None | Owned installation summaries |
| POST `/installations/{installation_id}/disconnect` | No body | Disconnected installation; saved encrypted credential removed |
| GET `/installations/{installation_id}/repositories` | None | Currently user/App-authorized selected repositories |
| POST `/repositories` | `{installation_id,repository_id}` | Explicit owned connection with connected/disconnected status |
| GET `/repositories` | None | Owned connection metadata |
| POST `/repositories/{connection_id}/disconnect` | No body | Inactive connection; history retained |
| POST `/repositories/{connection_id}/ingest` | `{commit_sha}` | Canonical V2 repository knowledge, catalog, exact sources and coverage |
| GET `/repositories/{connection_id}/knowledge?commit_sha=...` | Exact SHA query | Saved V2 artifact after current access checks |
| POST `/repositories/{connection_id}/ask` | `{commit_sha,question,history?}` | Grounded answer, exact quotations and server-created path/line citations |
| POST `/repositories/{connection_id}/sync` | `{commit_sha}` | Existing V1 changed-file snapshot |
| GET `/repositories/{connection_id}/snapshot?commit_sha=...` | Exact SHA query | Stored V1 snapshot after access recheck |
| POST `/repositories/{connection_id}/learning-path` | `{commit_sha}` | Existing ungraded V1 path/questions |

The current `/projects` journey uses V2 ingest/ask. Its knowledge and answer
types come from the generated backend schema. After explicit authorization and
repository selection:

```ts
import { githubProjectsApi } from "@/lib/api/github-projects";

const connection = await githubProjectsApi.connect(installationId, repositoryId);
const knowledge = await githubProjectsApi.ingest(connection.id, exactCommitSha);
const saved = await githubProjectsApi.knowledge(connection.id, knowledge.commit_sha);
const answer = await githubProjectsApi.ask(connection.id, {
  commit_sha: saved.commit_sha,
  question: "Teach me how authentication works in this project.",
  history: [],
});
// Render status, limitations, explanations, citation quotes and exact line spans.
await githubProjectsApi.disconnect(connection.id);
```

`commit_sha` is forty lowercase hexadecimal characters. `question` is at most
2,000 characters; history is at most four user/assistant entries of 1,600
characters each, with a 9,000-byte overall question payload. Keep history in the
current connection/commit context; clear it when switching sources. It is
untrusted conversational context, not evidence or a source-selection authority.

`answered` includes bounded cited sections and actual `ai`/`test_fixture`
provenance. `insufficient_information` and `unavailable` contain no invented
answer or citations. No relevant sources means abstention without a model call.
HTTP 200 with unavailable is a failure state, not a successful response to hide
behind demo text. Handle 401/403/404, expired/replayed authorization 409, input
422, admission/upstream rate limit 429, dependency 503 and deadline 504 honestly.
Project operations admit ten calls per account/minute, one active per account
and two globally. Do not automatically repeat AI/OAuth POSTs or spin on 429.

V2 ingestion inspects metadata and a safe commit-pinned file tree across
frontend/backend, routes/schemas, models/migrations and documentation. Bounds:
twenty directory calls, 2,000 inspected tree entries, 240 catalog entries,
eighteen source blobs of at most 32 KiB, forty source references of at most
1,800 characters, 48,000 aggregate source bytes, thirty history commits and
seventy-five pinned changed files. The saved artifact is at most 96 KiB.
Numeric pagination and coverage flags expose truncation and omitted files; the
receipt always says `complete_repository:false`. This is not a full repository
or PR discussion/diff archive. Exclusions cover environment/secret/key files,
node_modules, build/generated assets, binaries, unsupported/oversized content
and symlinks; repository code is never executed.

Question retrieval uses at most twelve owned source references. Exact quotations
must occur in the cited source. Paths and line spans are supplied/computed by
the server; fabricated citations, filenames, endpoints and free-text line claims
reject the answer. These controls verify source/quotation integrity, not the
semantic truth of every model sentence. Omitted behavior stays unknown. All
advice remains ungraded/unexecuted and cannot complete verified Notes/Tasks.

Native `.claude-logs/*.md` counted prompt/final entries may include original
session/turn/model/timestamp metadata only when present and valid. Hidden
reasoning, tools, frontmatter and unknown formats are withheld. Correlation is
`same_pinned_snapshot_only`; prompt-to-file causation remains `unproven`.
Existing V1 receipts/hashes stay unchanged; V1 releases now also reject newly
excluded paths. Generated answers/path wording is ephemeral; saved V2 source
artifacts are immutable. Private guides use their separate persistence.

App settings are backend-only process variables:
`TRACE_GITHUB_APP_MODE`, `TRACE_GITHUB_APP_ID`, `TRACE_GITHUB_APP_SLUG`,
`TRACE_GITHUB_APP_CLIENT_ID`, `TRACE_GITHUB_APP_CLIENT_SECRET`,
`TRACE_GITHUB_APP_PRIVATE_KEY`, `TRACE_GITHUB_APP_STATE_SIGNING_SECRET`,
`TRACE_GITHUB_APP_TOKEN_ENCRYPTION_KEY`, `TRACE_GITHUB_APP_CALLBACK_URL`.
The safe template is `backend/github.env.example`, not an automatically loaded
file. Do not add these to strict `backend/.env` or frontend `.env.local`.
The independent encryption key is a stable private Fernet key: URL-safe base64
encoding of 32 random bytes. Encrypted owner-bound user authorization survives
workers/restarts with the same database/key, obeys provider expiry and is capped
at eight hours. Expiry/key loss requires explicit reconnect; refresh tokens are
not persisted or used. Installation tokens remain server-memory-only, fresh and
restricted to one selected repository.

Local disconnect invalidates in-flight authorization revisions and preserves
history; installation disconnect also wipes its encrypted credential. It does
not uninstall the GitHub App or globally revoke the user's GitHub authorization.
Those actions remain in GitHub settings. Current user/installation access is
rechecked before source/answer release. Owned connection metadata remains
listable after disconnect; source content does not.

Owner configuration is still required before live authorization can be accepted.
Use read-only Contents/Pull requests/Metadata and selected repositories. Local
frontend/backend URLs are `http://localhost:3000` / `http://localhost:8000`, with
both App callback and installation setup URL exactly
`http://localhost:3000/projects/github/callback`. Disable automatic OAuth during
installation for Trace's two-stage flow; webhooks stay disabled, with no webhook
URL or secret. Use approved HTTPS addresses for deployment. Migration 0012 adds
encrypted authorization/disconnect revisions; 0013 archives V2 knowledge without
rewriting historical V1 receipts. Back up and forward-upgrade each machine's own
database; populated downgrade is refused. See [App owner setup, contracts and
manual live acceptance](github-app-project-learning.md) for the exact procedure
and [the acceptance report](../reports/trace-ai-and-github-acceptance.md) for actual
validation status. Do not infer live acceptance from fixture tests.

Optional [GitHub social sign-in](github-oauth-setup.md) remains separate and is
not required for App repository access.

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
