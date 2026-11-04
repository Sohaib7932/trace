# Trace AI and GitHub acceptance audit

Updated 4 November 2026 (Asia/Calcutta). Branch:
`codex/github-oauth-ai-chatbots`.

## Current critical completion sprint

The owner explicitly authorized publishing the previously validated work before
starting this sprint. It was committed and pushed normally as
`8595466b9e05626f1d587a83cca463f015756dbd` —
`feat(ai): add private guides and GitHub project learning`.
The remote source branch was verified at that exact SHA and the working tree
was clean immediately afterward. All five reviewed shared-log files were
included under the repository policy; the review found no actual credential or
personal-email publication blocker. This does not certify the small prompt-only
logs as genuine automatic conversation capture.

**New sprint changes remain uncommitted and unpushed.** No PR, merge, public
deployment, paid service or billing activation was performed in this sprint.
The original architecture guard and deterministic learner verification remain.

### Implemented sprint extensions

- GitHub user authorization is now encrypted durably with an independent
  backend-only Fernet key. Owner, installation, GitHub user and expiry are bound
  inside the encrypted payload. Access respects provider expiry up to eight
  hours and survives process/worker replacement. GitHub access tokens never enter public
  schemas, browser storage, model context or diagnostic output. Refresh tokens
  are not retained; expiration requires explicit reconnect.
- Owner-only installation and repository disconnect operations are idempotent.
  Installation disconnect wipes the stored encrypted user credential. Local
  disconnect preserves history and does not uninstall the App or globally revoke
  its GitHub grant. Authorization/connection revision fences reject stale work,
  including disconnect during source fetch, persistence or AI explanation.
- A separate immutable V2 knowledge artifact preserves the historical V1
  schemas and canonical digests. It records pinned repository metadata, safe
  file catalog, actual code excerpts with exact line ranges and digests,
  documentation, API/schema/database/migration categories, bounded commit
  metadata and native prompt/final attribution where available.
- Repository questions select source excerpts deterministically on the backend.
  Gemini can explain or abstain. Every delivered section has existing reference
  IDs and exact source quotations; the server computes citation paths and line
  numbers. Recognized unsupported path/filename/endpoint forms, invalid quotes
  and model-written line claims reject the whole response. Every citation is
  checked mechanically. Exact quotes establish citation
  integrity; semantic truth of every natural-language interpretation is not
  mathematically proved. Nothing executes repository code or grades a learner.
- The existing `/projects` design now supports ingestion, source preview,
  questions/follow-ups, explicit insufficient/unavailable states and disconnect.
  Account changes remount private state; repository/SHA changes clear pending
  questions and replies. Model context excludes unnecessary agent session/turn
  identifiers. Native logs remain untrusted source claims, with prompt-to-file
  relationships explicitly unproven.
  HTTP sign-in, missing-repository, rate-limit and deadline failures have distinct
  sanitized messages; private upstream errors are withheld and writes are not
  automatically replayed.
- Dependency/build/generated/secret/binary exclusions apply to new ingestion
  and legacy commit sync. Unsafe old receipts are withheld without rewriting
  their immutable content or digest. Ignore rules now also cover local
  `backend/*.db.*` backups; this does not remove already tracked upstream data.
- Installation tokens accept the current longer GitHub format as opaque strings,
  with a 4,096-character visible-ASCII safety bound and no format-override fallback.
  User OAuth and vault bounds remain separate. This fixes the old 512-character
  incompatibility documented in [GitHub's token-format notice](https://github.blog/changelog/2026-05-15-github-app-installation-tokens-per-request-override-header/).
- Secret screening covers filenames, repository/branch metadata and native
  session/turn/model attribution as well as source bodies. Known credential-shaped
  metadata is withheld even when the accompanying prompt/final body is harmless.

### Current public contract

The actual generated OpenAPI and frontend declarations now describe **46 paths
/ 50 operations**. The five new paths are:

| Method and path | Purpose |
| --- | --- |
| POST `/api/v1/projects/github/installations/{installation_id}/disconnect` | Stop this owner's Trace installation access |
| POST `/api/v1/projects/github/repositories/{connection_id}/disconnect` | Disconnect one owned repository locally |
| POST `/api/v1/projects/github/repositories/{connection_id}/ingest` | Archive bounded repository knowledge at `{commit_sha}` |
| GET `/api/v1/projects/github/repositories/{connection_id}/knowledge?commit_sha=...` | Read the pinned artifact after current access checks |
| POST `/api/v1/projects/github/repositories/{connection_id}/ask` | Ask `{commit_sha,question,history?}` using server-selected sources |

Signed-in learner authentication is required. Writes additionally require an
allowed Origin and `X-Trace-Client: learning-web`. Responses are no-store.
Existing GitHub ingress, per-account rate and concurrency limits and request
deadlines cover these paths. There is no automatic AI/OAuth write replay.
See [the integration handoff](../frontend/trace-platform-handoff.md) and
[GitHub owner setup](../frontend/github-app-project-learning.md).

### Explicit ingestion scope

Limits are twenty nonrecursive tree requests, 2,000 encountered entries, 240
catalog entries, eighteen fetched files of at most 32 KiB, four selected
excerpts per file, forty references, 48,000 UTF-8 source bytes and a 96 KiB
artifact. Sources are bounded architecture excerpts, not all lines of every
file. Line endings normalize to LF while physical line numbering is retained.
Traversal and selection may omit relevant code; unsupported behavior must remain
unknown. Receipts always report partial coverage.

History contains up to thirty titles/timestamps through three numeric pages.
Only the pinned commit has changed paths, capped at seventy-five; other history
commits do not have complete changed-file details. PR titles are available in
legacy V1, not a complete PR history/diff archive. Excluded directories are
counted as encountered omissions, not expanded to invent unseen-file counts.

### Configuration and external acceptance

The approved Gemini model remains `gemini-3.5-flash-lite`, loaded through the
existing explicit free-tier launcher and private `backend/.env.gemini`.
`GEMINI_API_KEY` stays backend-only. No paid fallback, provider retry or extra
SDK/provider was introduced. The generic AI mode remains disabled unless
explicitly activated; frontend fixture modes are labelled and separate.

At the sprint preflight the App was disabled and its process configuration was
absent. The owner subsequently confirmed setup is underway. Required names:
`TRACE_GITHUB_APP_MODE`, `TRACE_GITHUB_APP_ID`, `TRACE_GITHUB_APP_SLUG`,
`TRACE_GITHUB_APP_CLIENT_ID`, `TRACE_GITHUB_APP_CLIENT_SECRET`,
`TRACE_GITHUB_APP_PRIVATE_KEY`, `TRACE_GITHUB_APP_STATE_SIGNING_SECRET`,
`TRACE_GITHUB_APP_TOKEN_ENCRYPTION_KEY`, `TRACE_GITHUB_APP_CALLBACK_URL`.
Configure privately in the backend process/secret manager, not general
`backend/.env`, frontend settings, Git or chat. The encryption key must remain
stable across workers/restarts; changing it requires reconnecting old grants.

The owner chooses an App name such as Trace Project Learning. Local callback
and installation setup URL are both
`http://localhost:3000/projects/github/callback`; frontend is
`http://localhost:3000`, backend `http://localhost:8000`. Keep automatic user
authorization during installation disabled for the explicit two-step flow.
Use selected repositories and read-only Contents, Pull requests and Metadata.
Webhooks are disabled; this implementation uses polling/read-time revalidation
and has no webhook endpoint. Genuine authorization remains unverified until
the owner-configured App round trip and actual repository ingestion are tested.

### Database and preservation

Additive migrations `0012_github_authorization` and
`0013_repository_knowledge` preserve V1 receipts and historical learner records.
After verifying the local backup
`backend/trace-before-github-sprint-20261103T230810646809.sqlite3`, the development
database was upgraded from 0011 to 0013. All pre-existing column/row fingerprints
across 43 tables were preserved; integrity was `ok` and foreign-key violations
were zero. The private backup is ignored and is not included in Git. No hosted
PostgreSQL or production migration was performed by this sprint.

### Fresh sprint verification

| Verification | Result |
| --- | --- |
| Provider/configuration/production safeguards | Existing focused provider cases passed; the concurrently stale OpenAPI assertion was corrected through regeneration, not relaxed |
| Combined new backend functionality/security/architecture | 240 passed before the final metadata-screen additions |
| Authorization, persistence, legacy GitHub and unchanged architecture guard | 71 passed, plus twenty isolated concurrency checks |
| Final bounded ingestion/provider/metadata privacy plus architecture | 140 passed |
| Project-question policy and final exact API guards | 43 passed after final metadata schema regeneration; exact API/export equality preserved |
| New protected repository-question HTTP suite | 10 passed |
| Legacy exclusion and exact API/export regressions | 14 passed |
| Final frontend suite | 176 passed across fourteen files in 118.31 seconds, exit 0; Project Learning module 19 passed |
| Final frontend lint/type checking | Both passed, exit 0, after final type regeneration and safe HTTP error-message updates |
| Full frozen backend/coverage | 4,617 passed in 1,281.69 seconds (21:21), exit 0; aggregate coverage 94.11% |
| Ordinary desktop/mobile browser suite | 58 passed; four pre-existing mobile/keyboard exclusions; production build passed with seventeen routes |
| Final protected AI desktop/mobile browser suite | 16 passed in 1.2 minutes, exit 0; external transports explicitly fixtures, including the GitHub authorization shortcut |
| Fresh real Gemini tutor/support/guide journeys | Five bounded calls succeeded: actual Notes schema explanation and follow-up, cited Help answer and follow-up, Python list-indexing guide generation |
| Live provider repository-question contract | One additional bounded call passed using only synthetic frontend/backend authentication sources; two sections, exact citations, no live GitHub authorization claim |
| Local logging/release guard unit tests | 43 passed |
| Fresh disposable SQLite upgrade and Alembic metadata comparison | Passed; no new upgrade operations detected |
| Final Ruff/format/mypy | Passed: 397 Python files formatted, 243 source files type checked |

The initial full attempts exposed stale exact route/export expectations;
all existing paths, hint checks and disabled-feedback expectations remain, with
the five actual new paths added explicitly. One run stopped at 294 passed/one
stale inventory failure. Clean partial runs were also stopped for targeted
traversal, metadata privacy and contention fixes. No interrupted run is
represented as a full pass. Source was frozen before the final full execution.
The final full run completed successfully; its persistent output is
`backend/.pytest_cache/sprint-frozen-full-20261104.log`. A recorded SHA-256
manifest of 372 backend app/migration/test Python files remained unchanged
during that run. The current aggregate coverage is **94.11%, down 0.74
percentage points from 94.85%**. The measured statement count grew from 12,988
to 14,058 and branch count from 3,342 to 3,712. The existing 85% gate, baseline
assertions and security cases were not lowered or skipped. New failure branches
are not exhaustively covered; no claim that the previous percentage was
preserved is made.
The first ordinary browser build mistakenly selected the real AI profile for
tests that require labelled mocks; it produced fifty passes/eight failures/four
existing exclusions. It was rebuilt with the intended fixture profile without weakening tests.
The corrected ordinary run passed. The first protected browser run exposed an
inaccurate label locator in the new tests, corrected to the actual combobox role.
A later run had thirteen passes/one timeout in the existing fixture-reset hook;
the unchanged full rerun passed all fourteen without increasing timeouts or
weakening assertions.
After the final UI error-message improvement, another run returned twelve
passes/two failures: the post-disconnect access assertion received 429 before it
could reach the expected 404 check. Rate and concurrency admission both use 429;
the response alone did not establish which limit won. The browser tests now use
independent accounts for the long question and disconnect/ownership scenarios,
and wait for the real UI operation/refresh to finish before the readback. Every
exact 404 and privacy assertion is retained; no limits, sleeps or skips were
introduced. The final sixteen-test run passed in 1.2 minutes; its persistent
output is `coverage/acceptance/sprint-ai-release-20261104.log`. These are real
frontend-to-backend HTTP contract checks with fixture external transports,
not live GitHub authorization evidence.

### Genuine provider and persistence evidence

The actual signed-in browser and explicit real Gemini launcher were used with
public/synthetic questions. No fixture transport was injected. The Notes tutor
correctly explained `NoteCreate(BaseModel)` and `ConfigDict(extra="forbid")`,
then distinguished this from an ordinary Python class. Help returned the exact
approved `retrieval-one-seven-days` passage and retained it when asked about the
second checkpoint. The first checkpoint remains one elapsed day after transfer,
the second seven; no schedule was changed.

The new Python List Indexing Learning Guide passed the strict private-guide
schema, saved, opened and reloaded through the authenticated reader. Independent
database readback confirmed `source: ai`, version 1.0.0, two sections, a matching
canonical digest, `ungraded: true` and `execution_status: not_executed`. No example
was executed or graded. Generated educational prose/examples still require
review; schema validity is not a claim of universal pedagogical or code accuracy.
The screenshot evidence is private/ignored local material:
`coverage/acceptance/sprint-live-tutor-support.jpg`,
`coverage/acceptance/sprint-live-private-guide.jpg` and
`coverage/acceptance/sprint-live-private-guide-viewport.jpg`.

One additional actual Gemini call exercised `ProjectKnowledgeService.ask` using
only synthetic frontend/backend authentication code and synthetic authorization
ports. The strict proposal and release validators accepted two sections, citing
`frontend/api.ts` lines 1–3 and `backend/auth.py` lines 1–7 with exact quotations.
It explained bearer transport and JWT signature/audience validation while
acknowledging absent route-binding/token-creation evidence. The client allowed
one live attempt, zero retries and zero paid allowance. This is a **live provider
contract check with synthetic sources**, not real GitHub authorization,
repository ingestion or a substitute for the required owner round trip.

### Published baseline CI investigation

The initial authorized push triggered repository-managed Actions and a Vercel
preview check; no production release was performed. Quality
[run 41733060041](https://github.com/Sohaib7932/trace/actions/runs/41733060041)
passed frontend but failed Ubuntu with 4,408 passes/one failure:
`test_concurrent_callback_consumes_state_exactly_once`, SQLite
`OperationalError: database is locked` while inserting the installation grant.
The matrix cancelled Windows after Ubuntu failed. The separate PostgreSQL
[run 41733060053](https://github.com/Sohaib7932/trace/actions/runs/41733060053)
passed. These are results for 8595466, not the unpushed sprint changes.

The sprint grant binder now starts with a conditional UPDATE before reading or
inserting, avoiding the SQLite read-lock upgrade cycle. A controlled writer
contention regression passes this implementation and deterministically fails
with the old SELECT-first method in a process-only negative control. Twenty
concurrency checks passed across ten isolated processes, with no sleeps,
blanket retries, skipped assertions or published-history edits. The repair is
part of the uncommitted sprint; **new GitHub CI has not verified it yet**.

### Upstream integration and privacy blockers

Fetched `origin/main` is `73e80f7`, including PRs 23–25. It was inspected
read-only, not merged. PR 25 adds a separate `0010_custom_lessons` migration
branch, overlapping hub/API/type changes and an AI-answer-key grading flow that
requires a separate trust classification from verified lessons and private
ungraded guides. Its private UI also needs account-switch cache review before
adoption. Do not treat this branch's successful tests as validation of that
unmerged combination; migration and semantic merge work remains separate.

Upstream also tracks `backend/trace.db.before-0010.bak`. A read-only aggregate
inspection confirmed private identity, credential-hash and learner-history
records, with no raw credential found in that inspection. No row values or
identities were printed. The backup is absent from this branch and was not
copied or republished. The repository owner must arrange removal from tracked
source and review Git-history exposure separately; this sprint does not rewrite
published history or delete user data.

### Submission status and remaining owner actions

| Capability | Status | Evidence and remaining work |
| --- | --- | --- |
| LLM provider | **COMPLETE for the three requested local journeys** | Real Gemini tutor/follow-up, approved-source Help/follow-up and private guide save/reopen succeeded. Automated failure and ownership checks passed. This is not deployment or universal answer-quality certification. |
| GitHub App authorization | **INCOMPLETE** | Durable authorization, selected-repository checks, disconnect and expiry are implemented and locally tested. The owner is still configuring the real App; no genuine installation/user authorization round trip has been accepted. |
| Repository ingestion | **INCOMPLETE** | Bounded, pinned V2 ingestion, source exclusion, immutable persistence and protected HTTP/browser flows are implemented and tested. Actual ingestion through the owner-authorized App remains unverified. |
| Grounded Project Learning | **INCOMPLETE** | Source selection, exact citations, bounded follow-ups and safe abstention are implemented. Fixture HTTP/browser checks and one synthetic-source live Gemini call passed. A real authorized repository question remains unverified. |

The next owner action is to finish the private App configuration described in
[the GitHub setup guide](../frontend/github-app-project-learning.md). The current
real backend on port 8000 cannot inherit environment variables configured in a
different terminal. Stop that server before starting the explicit Gemini
launcher from the privately configured owner terminal, then perform the
documented installation, selection, ingestion, question and disconnect checks.
Do not send secrets in chat. No additional broad product decision is needed.

Before integrating current `origin/main`, resolve its migration branch and
overlapping API/UI changes deliberately and address the separately reported
tracked database backup. New support copy remains draft until approved; the
existing approved corpus is the only active support source. Hosted PostgreSQL
with migrations 0012/0013, production deployment and fresh remote CI for these
unpublished changes have not been verified. The coverage decrease and remaining
uncovered failure branches are recorded above.

Final branch is `codex/github-oauth-ai-chatbots`; HEAD and the published source
branch remain `8595466b9e05626f1d587a83cca463f015756dbd`. The 47 sprint source,
test, schema and documentation paths listed at the end of this report remain
local and unstaged. Existing work, shared logs, environment files and database
backups were preserved. Only the explicitly authorized pre-sprint commit was
pushed; no sprint commit, PR, merge or deployment was performed.
Final read-only checks reconfirmed the remote branch SHA, an empty Git index,
47 local changed/untracked paths, no changed shared logs, and a passing normal
`git diff --check`. All 372 frozen backend Python digests still match. The
running application's OpenAPI exactly matches the exported 46-path/50-operation
schema. The local database remains at 0013 with integrity `ok`, zero foreign-key
violations and its verified backup present.
The final read-only review of all 47 sprint paths found no actual credential,
token or private-email leak. Sensitive-looking test cases use explicit synthetic
fixtures. No environment/database/log files are included in the sprint diff;
published migrations 0010/0011 and logging configuration remain unchanged.

## Historical acceptance record published in 8595466

The sections below preserve the pre-sprint implementation and measured evidence.
Their 41/45 inventory, process-memory GitHub proof and pre-sprint Git status
describe that earlier commit, not the superseding sprint implementation above.

## Scope and initial findings

The owner clarified that the required GitHub feature is **GitHub App repository
connection for Project Learning**. Supabase GitHub social sign-in is a separate,
optional feature. A social login button does not authorize repository access.

The owner approved a separate private learning-guide format for broader topics:
AI explanations, unexecuted examples and explicitly ungraded practice. Existing
verified Notes/Tasks lessons, private evaluator authority, candidate review and
publication restrictions and the +1/+7-day retrieval schedule remain intact.

Initially, GitHub social sign-in was absent; Help sent no prior dialogue; custom
lesson creation was disabled; and generation was internal to trusted Notes/Tasks
candidates. Conversational tutoring already captured an owned pinned lesson and
its actual public code. This work extends those boundaries.

## Acceptance status

| Capability | Status and evidence |
| --- | --- |
| GitHub App connection, read-only ingestion and Project Learning | IMPLEMENTED; AUTOMATED TEST PASSED. Owner configuration and genuine repository authorization remain EXTERNAL CONFIGURATION REQUIRED. |
| Optional Supabase GitHub sign-in | IMPLEMENTED; AUTOMATED TEST PASSED (22 auth component tests). Hosted provider was disabled at inspection; genuine social login remains EXTERNAL CONFIGURATION REQUIRED. |
| Support Assistant with bounded follow-up context | IMPLEMENTED; AUTOMATED TEST PASSED; LIVE GEMINI VERIFIED; BROWSER VERIFIED. Exact review-schedule citation, contextual follow-up and unsupported-topic abstention observed. |
| Tutor grounded in actual pinned Notes/Tasks source | IMPLEMENTED; AUTOMATED TEST PASSED; LIVE GEMINI VERIFIED; BROWSER VERIFIED for owned Notes explanation and follow-up. Tasks source switching is automated, not a fresh live Tasks claim. |
| Private learning guides, persistence and frontend reader | IMPLEMENTED; AUTOMATED TEST PASSED; LIVE GEMINI VERIFIED; BROWSER VERIFIED. Real generated guide saved, opened and reloaded; independent database readback confirmed strict digest and AI provenance. |
| Shared Gemini transport and bounded teaching deadlines | IMPLEMENTED; AUTOMATED TEST PASSED; LIVE GEMINI VERIFIED for the concrete product journeys below. |
| Complete current backend regression/coverage | AUTOMATED TEST PASSED: 4,409 tests, 94.85% coverage in 1,353.78 seconds (22:33), exit 0, after the dependency-boundary repair. |
| Complete live release acceptance | BLOCKED on GitHub owner configuration/real repository authorization; updated Help copy also requires human review before activation. Local regression gates passed. Not deployed or declared production-ready. |

HTTP 200 with an unavailable status is not a successful AI answer. Fixture
responses remain explicitly labelled. Synthetic connectivity does not prove
useful source-grounded tutoring, support or guide creation. Browser evidence
must be recorded separately when the actual journey succeeds.

## Shared Gemini integration and observed failures

The existing app-owned BoundedAIClient and approved gemini-3.5-flash-lite
transport remain shared. GEMINI_API_KEY is configured privately in
backend/.env.gemini; no value is printed here or placed in the frontend. Paid
allowance and retries remain zero. No new provider SDK or alternative provider
was introduced by this task.

Initial signed-in Help requests reached eligible source retrieval and Gemini,
but returned a transient error and a timeout. The Notes line-by-line tutor
request also returned honest unavailable. A minimal synthetic request timed out
under ten seconds; a separately bounded synthetic request subsequently succeeded
with a twenty-second budget and AI provenance. An unauthenticated HTTPS probe
reached Google; that probe does not establish credential/model readiness.

The explicit free-tier launcher now chooses the existing twenty-second transport
ceiling only when no tighter operator response/total cap was supplied. Explicit
tighter caps remain authoritative. Generic client defaults stay ten seconds;
deterministic feedback policy is unchanged. Tutor/Support families allow twenty
provider seconds within thirty request seconds. Operation settings are
revalidated using the actual server-selected family schema. Rate/concurrency,
token/response bounds, transport cancellation, authorization freshness, spending
and retry controls remain enforced. Plain Uvicorn does not activate this profile.

### Genuine signed-in browser acceptance

The real local Gemini launcher and the existing real signed-in account were
used, with the private configured credential and public/synthetic questions.
No fixture transport or fallback was injected into these requests.

- Notes: asked for three short points explaining the actual `schemas.py`.
  The response correctly described the Pydantic import, `NoteCreate(BaseModel)`,
  extra-field policy and string fields. A follow-up about inheritance explained
  automatic validation/parsing rather than an ordinary Python class. Delivery
  logs recorded `tutor / answered / ai`; no learner attempt or completion changed.
- Help: “How do follow-ups work?” returned the approved exact quotation stating
  one and seven elapsed days after Tasks completion, with the
  `retrieval-one-seven-days` passage under the saved-progress source. “When is
  the first of those checkpoints due?” retained that source context. A later
  standalone Jupiter-weather question returned no relevant approved documentation;
  the previous supported topic did not turn it into a fabricated answer.
- Guide: generated Python variables/assignment material from beginner to
  intermediate, practical preference and bounded goals. The first live output
  was withheld because its schema version was invalid. A bounded diagnostic
  confirmed a successful provider response with only that literal validation
  error; the prompt now explicitly distinguishes the required hyphenated schema
  version from the underscored routing label. The next owned request produced a
  valid two-section guide with names/values, assignment and reassignment, tiny
  examples and ungraded practice. The reader displayed it after reload.
  Independent database readback validated the canonical digest, `source: ai`,
  version 1.0.0, two sections, `ungraded: true` and `not_executed`.
- Project Learning: the signed-in page showed no connected repositories and
  the real start request returned sanitized 503 because the App is unconfigured.
  No installation was invented or external authorization attempted. A synthetic
  callback HTTP probe returned `Cache-Control: no-store` and
  `Referrer-Policy: no-referrer`; callback query logging is excluded in Next dev.

These successful runs do not erase the earlier observed failures or guarantee
provider availability. Source/citation checks and strict rejection remain active.

Provider compatibility investigation also found that the supported Gemini
`responseJsonSchema` keywords include `enum`, while Pydantic's single-string
literal emits `const` and the SDK's raw-schema path passes that through. The
transport now converts string constants to equivalent singleton enums only at
actual schema nodes, without mutating the original request or domain models.
Contradictions and unsupported non-string constants fail closed. Wire-level
tests verify the payload and unchanged original schema; server-side strict
validation still rejects the wrong version. The live guide above preceded this
last normalization patch. A subsequent bounded genuine Gemini check using the
normalized schema produced a strictly validated, AI-sourced two-section Python
dictionaries guide with the exact required schema version. No fixture or relaxed
domain validator was used for that check.

Primary references: [GenerateContent schema keywords](https://ai.google.dev/api/generate-content)
and [official SDK schema transformations](https://github.com/googleapis/python-genai/blob/main/google/genai/_transformers.py).

## GitHub App Project Learning

The signed-in /projects UI uses the protected /api/v1/projects/github API family.
Start creates a durable single-use nonce and signed, owner-bound ten-minute
state. The browser completes App installation and explicit GitHub user
authorization. Complete exchanges the code server-side, identifies the GitHub
user, and proves that user's access to the selected installation's repositories.
An installation ID alone never grants access.

The backend independently checks the configured App, selected-repository mode,
read-only Contents/Pull requests/Metadata permissions and suspension status.
Every source read rechecks user access and uses a short-lived installation token
restricted to one repository. Tokens never enter database rows or frontend
responses. The callback strips code/state queries, applies no-store/no-referrer,
and callback requests are excluded from framework incoming-request logs.

Durable owned connections and immutable snapshots pin the exact forty-hex commit
SHA, canonical SHA-256 digest and reference IDs. Ingestion covers the commit
title, up to twelve changed files and five associated PR titles. Source blobs
come from hashes supplied by that commit, avoiding symlink dereferencing.
Files are bounded to 32 KiB; excerpts to 1,000 characters. Oversized,
unsupported-encoding and binary blobs are explicit omissions. Network,
authentication and integrity failures abort rather than becoming omissions.
The transport pins GitHub hosts, rejects redirects and compressed responses
before decompression, and enforces aggregate deadlines and wire bounds.

The shared .claude-logs exception accepts counted native PROMPT/RESPONSE blocks
matching the project format. Frontmatter, capture metadata, tools, reasoning,
uncounted tails, oversized blocks and unknown formats are omitted. Obvious
credentials/emails are withheld. Logs remain untrusted claims, never execution
or competence evidence. Filters do not certify arbitrary repository content as
free of every secret: repository selection must be approved for processing.

Project Learning sends the safe pinned bundle to the shared generation client.
Every step must cite existing IDs. Strict output rejects invalid citations,
links, private data and execution/completion/competency/score claims. Citation
membership is mechanically checked; it does not prove every sentence's semantic
correctness. Paths remain ungraded/unexecuted and cannot publish or complete a
verified lesson.

Explicit limitations: GitHub user proof lasts at most five minutes in bounded
process memory. Expiry, restart or another worker requires reauthorization; this
is not distributed durable OAuth-session storage. Snapshots are partial
changed-file evidence, not complete repository indexing or PR diff/history
retrieval. Generated Project Learning wording is a response, not persisted
course/progress history; snapshots themselves are durable.
Renamed/transferred or differently installed repositories are refused rather
than silently repointed. An automatic connection-remapping/disconnection UI is
not implemented; do not promise that reauthorization alone repairs those cases.

See [GitHub App configuration and contracts](../frontend/github-app-project-learning.md)
and [safe variable template](../../backend/github.env.example). External owner
setup and genuine authorization are pending. No live GitHub connection is claimed.

## Optional GitHub social sign-in

The auth form offers GitHub on sign-in/sign-up through the existing Supabase
SDK, configured-origin check, safe remembered destination and PKCE callback.
Email/reset and Google remain. Supabase controls identity linking; Trace uses
verified issuer/subject rather than client-supplied email. Social login requests
no repository scopes.

The hosted provider reported GitHub disabled and Google enabled during inspection.
Its optional setup is documented in [GitHub social sign-in](../frontend/github-oauth-setup.md).
The Supabase-displayed OAuth callback differs from the GitHub App Trace callback.
Enabling social login is not a prerequisite for App repository connection.

## Support Assistant

POST /api/v1/support/ask accepts an additive optional history: at most four
user/assistant messages of 250 characters each. The current question remains
limited to 500 characters. Only the last two messages are used for explicit
conversational references, labelled as untrusted data. Standalone unrelated
questions do not inherit a supported topic. Unknown fields, system roles,
obvious credentials and personal emails are rejected.

The Help panel sends successful dialogue, excludes unavailable assistant turns,
and clears history with New chat. No persisted support conversation or client
source/file selection was added. Existing approved retrieval, exact quotations,
source references, digest/freshness/revocation and release checks remain authoritative.

The unchanged pilot has nine articles/nineteen passages, revision 1.0.0,
approved 2 November and expiring 2 December 2026. It covers overview,
registration, Google auth, navigation, predictions/attempts/verification,
hints, progress/reviews, daily availability and technical problems. Drafts,
logs, environments and private implementation material are excluded. No corpus
or new retrieval profile was silently approved. Draft conversational-tutor copy
still requires review before corpus publication.

Fresh source-grounded answers, exact citations, a contextual follow-up and a
standalone unsupported-topic abstention were observed in the real signed-in
browser as recorded above. The earlier unavailable outcomes remain part of the
failure evidence. New feature copy is prepared for human review in the
[draft corpus supplement](../support-corpus-supplement-review.md); neither
technical validation nor these successful answers approves changed source text.

## Lesson Tutor

POST /api/v1/sessions/{session_id}/tutor/ask preserves authored guidance and
explicit conversation mode. Context is captured from fresh owned sessions,
pinned lesson identity and allowed public material. Added instructions require
the actual supplied outgoing/schema snippets, identify the snippet and prohibit
invented files or execution results.

Tests compare real catalog snippets, including Notes-to-Tasks context switching
despite earlier Notes dialogue. Private answer keys and raw runtime payloads
remain excluded. Missing auth, foreign/missing sessions, hostile history,
invalid requests, saved failed-check categories, safe provider failures and the
legacy question-only response remain covered. Chat cannot execute code, change
hints/attempts, grade competence or complete a lesson.

Fresh genuine Notes code explanation and follow-up were observed in the
signed-in browser. This run did not execute a new live Tasks journey, edit code
through chat or establish live diagnosis of an unseen code patch. Automated
tests separately cover Tasks context switching and saved verification failures.

## Private learning guides

The approved private-learning-guide-v1 format supports topic, current/target
levels, practical preference and optional goals/preferences. It contains
objectives, progressive sections, explanations, unexecuted examples, optional
ungraded practice and expected learning outcomes. Strict schema/text/byte
bounds, unique IDs, privacy and unsupported-authority guards apply. This is a
separate format from executable LessonSpecV1.

The service reserves an owner/idempotency-key row in a short transaction, calls
the shared generation client outside the write transaction, rechecks fresh auth,
then finalizes ready or unavailable with version, digest and server provenance.
Same-key/body replay does not generate again; changed-body replay is 409.
Concurrent reservations, expiration and late finalization are tested. Terminal
history is preserved. List/read return only the authenticated owner's guides.

The existing /learn custom form and Your lessons section now create/list real
private guides and open /learn/guides/{guide_id}. Loading, empty, pending,
unavailable, retry and signed-out states are explicit. Failed live requests are
not replaced with successful demo content. Genuine guide acceptance succeeded:
the reader opened the AI-generated guide after reload, and independent database
readback confirmed its digest, version, two sections and AI provenance. The
fixture browser tests separately establish cross-account rejection and timeout
behavior without pretending to be genuine provider calls.

The existing CandidateGenerationService remains an internal trusted Notes/Tasks
pipeline. Technical validation still does not approve, publish or assign a
candidate. No arbitrary evaluator/runtime or broad-topic executable lesson was
introduced. See [the complete guide contract](../private-guides-contract.md).

## Current API inventory and frontend handoff

The current generated OpenAPI has **41 paths / 45 operations**, up from the
pre-task 31/33. The historical original 21/23 export is not today's contract.
backend/openapi.json and generated src/lib/api/schema.d.ts are current.
Historical docs/api/openapi.json was not silently overwritten.

| New method/path | Purpose |
| --- | --- |
| POST /api/v1/learning-guides | Create an owned guide; UUID Idempotency-Key required |
| GET /api/v1/learning-guides | List up to fifty owned summaries |
| GET /api/v1/learning-guides/{guide_id} | Read owned guide/content/provenance |
| POST /api/v1/projects/github/installations/start | Start owner-bound App authorization |
| POST /api/v1/projects/github/installations/complete | Prove GitHub user access and bind installation |
| GET /api/v1/projects/github/installations | List owned installation summaries |
| GET /api/v1/projects/github/installations/{installation_id}/repositories | List currently authorized selected repositories |
| POST /api/v1/projects/github/repositories | Explicitly connect one authorized repository |
| GET /api/v1/projects/github/repositories | List owned connections |
| POST /api/v1/projects/github/repositories/{connection_id}/sync | Ingest exact commit's bounded safe sources |
| GET /api/v1/projects/github/repositories/{connection_id}/snapshot | Read pinned snapshot after current access recheck |
| POST /api/v1/projects/github/repositories/{connection_id}/learning-path | Generate ungraded cited path/questions |

These require signed-in learner authorization; writes additionally require an
allowed Origin and X-Trace-Client: learning-web. Responses are no-store. Tutor additionally needs
an owned eligible session. Adapters reuse the existing protected client without
automatic AI-write replay on 401. See [platform handoff](../frontend/trace-platform-handoff.md)
for helpers, request examples and setup.

## Database preservation

Additive shared SQLite/PostgreSQL migrations 0010_private_learning_guides and
0011_github_projects add owned guide history, GitHub authorization
states/grants/connections and immutable snapshots. They do not rewrite old
learner records, lesson definitions or schedules. Populated history downgrade
refuses to erase those records.

Root verified the private local backup
backend/trace-before-guides-projects-20261103T182954769070.sqlite3 before the
authorized development upgrade from 0009 to 0011. Data fingerprints of all 38
pre-existing tables were preserved; integrity and foreign-key checks passed.
The backup/database are private local artifacts, not files to stage or share.
No production database was modified. PostgreSQL migration artifacts do not
constitute acceptance on an actual hosted PostgreSQL service.

## Validation record

| Scope/command | Result |
| --- | --- |
| Auth component module | 22 passed |
| Support history plus relevant HTTP/release/tutor regression | 66 passed before later source-context tests |
| Notes/Tasks conversational tutor HTTP module | 14 passed |
| Private-guide focused backend suite | 42 passed |
| GitHub service/HTTP/provider/security/migration suite | 55 passed before final compression regression; final provider unit suite 20 passed including that regression; all included in the successful final full suite |
| Privacy regressions | 13 passed |
| Deadline/activation/operations/relevant HTTP suite | 134 passed |
| Current full frontend npm test -- --maxWorkers=1 | 167 passed across fourteen files |
| Current npm run lint, typecheck and production build | Passed |
| Protected AI HTTP browser-fixture suite | 10 passed; deterministic transports explicitly labelled test_fixture |
| Earlier ordinary desktop/mobile Playwright suite | 58 passed; four pre-existing mobile/keyboard exclusions; run preceded final guide/Project Learning implementation |
| Fresh final ordinary Playwright suite | 58 passed, four pre-existing mobile/keyboard exclusions, 62 collected; final build passed with 17 routes |
| Ruff/formatting | Passed across 379 Python files after the dependency-boundary repair |
| Mypy | Passed across 231 source files after the dependency-boundary repair |
| Fresh full backend pytest and coverage | 4,409 passed in 1,353.78 seconds (22:33); coverage 94.85%; exit 0 |
| Current OpenAPI | 41 paths / 45 operations, generated from actual app |
| Local backup, upgrade, preservation and integrity | Passed as described above |

Focused backend commands use uv run --directory backend --locked --no-sync
pytest -q --no-cov with the relevant modules; the full suite retains its
configured coverage gate. Static commands use ruff check ., ruff format --check .
and mypy through the same environment. Frontend uses npm test -- --maxWorkers=1,
npm run lint, npm run typecheck, npm run build, npm run test:e2e and the separate
playwright.ai.config.ts fixture suite.

The first ordinary browser run used local real-service build settings rather
than the workflow's isolated fixture settings. It was stopped, rebuilt with
process-only CI fixture values and then passed; private environment files were
not rewritten. Development failures in strict-list conversion, icon import,
line limits, sanitized-error expectations and a six-call flow against a
five/minute fixture gate were corrected. Project Learning now has a dedicated
bounded ten/minute admission policy rather than inheriting tutor's five.
Assertions/coverage gates were not weakened and no new skips were introduced.

The first completed full backend run returned **4,408 passed / one failed**, with
94.85% coverage. Its failure was the existing architecture guard: the new
services depended directly on SQL/database and provider implementations. This
was a code defect, not grounds to change the test. Persistence now lives in SQL
repository adapters, with provider-neutral and repository protocols injected by
the application composition root. The guard is unchanged and all four
architecture tests passed. All 102 focused architecture/guide/GitHub tests
passed after the repair. The ten desktop/mobile AI HTTP browser tests and their
production build passed again against the repaired application wiring. The
saved genuine guide was also reopened through the corrected backend.

The fresh full rerun completed successfully: **4,409 passed, zero failed, 94.85%
coverage**, exit 0. It includes migration, ownership, security, tutor transaction,
runtime and AI suites. The existing 85% repository coverage threshold and
assertions were not lowered. This is the current checkout's measured result;
historical milestone percentages are not presented as freshly reproduced
pre-change measurements. The initial failed full run and final successful run
are retained separately in the ignored local artifacts
`backend/.pytest_cache/final-acceptance-20261104.log` and
`backend/.pytest_cache/final-acceptance-20261104-v2.log`.

## Implementation file map

| Area | Relevant created/modified source paths |
| --- | --- |
| Support/tutor | backend/app/schemas/support_http.py; backend/app/api/v1/support.py; backend/app/ai/providers/conversation_tutor.py; src/components/support/trace-help.tsx; src/lib/ai/client.ts; src/lib/ai/contracts.ts; src/lib/api/client.ts |
| Shared activation/security/lifecycle | backend/app/core/ai_activation.py; backend/app/core/ai_privacy.py; backend/app/core/tutor_settings.py; backend/app/services/feedback_operations.py; backend/app/main.py; backend/app/ai/providers/gemini.py |
| New dependency ports and adapters | backend/app/ai/private_guides.py; backend/app/ai/github_projects.py; backend/app/repositories/private_guides.py; backend/app/repositories/github_projects.py; backend/app/db/github_projects.py; backend/app/core/github_errors.py |
| Private guides | backend/app/schemas/private_guides.py; backend/app/ai/providers/private_guides.py; backend/app/db/guide_models.py; backend/app/db/private_guides.py; backend/app/services/private_guides.py; backend/app/api/v1/private_guides.py |
| Guide frontend | src/components/learning/hub/private-guide-hub.tsx; src/components/learning/hub/custom-lessons.tsx; src/components/learning/guides/; src/app/learn/guides/; src/lib/api/learning-guides.ts; src/lib/learning/lesson-source.ts; src/app/learn/page.tsx |
| GitHub App | backend/app/core/github_settings.py; backend/app/schemas/github_projects.py; backend/app/ai/providers/github_app.py; backend/app/db/github_models.py; backend/app/services/github_projects.py; backend/app/api/v1/github_projects.py; backend/github.env.example |
| GitHub frontend/callback | src/app/projects/; src/components/projects/; src/lib/api/github-projects.ts; src/lib/auth/next-path.ts; next.config.ts; src/app/layout.tsx |
| Optional social login | src/components/auth/auth-form.tsx; tests/components/auth.test.tsx; docs/frontend/github-oauth-setup.md |
| Persistence/schema | backend/alembic/shared_versions/0010_private_learning_guides.py; backend/alembic/shared_versions/0011_github_projects.py; backend/alembic/env.py; backend/openapi.json; src/lib/api/schema.d.ts |
| New backend tests | backend/tests/integration/test_private_guides.py, test_private_guides_http.py, test_github_projects.py; backend/tests/unit/test_private_guide_contract.py, test_github_app_client.py, test_gemini_json_schema.py, test_project_secret_privacy.py, test_support_conversation.py, test_teaching_deadlines.py |
| Frontend/contract tests | tests/components/private-guides.test.tsx, github-projects.test.tsx; existing auth/AI/hub/lesson-refinement modules; tests/ai-e2e/live-ai.spec.ts; tests/e2e/lesson-refinement.spec.ts; backend/tests/fixtures/live_ai_e2e_server.py |
| Documentation | This report; docs/private-guides-contract.md; docs/frontend/github-app-project-learning.md; docs/frontend/github-oauth-setup.md; docs/frontend/trace-platform-handoff.md; docs/support-corpus-supplement-review.md; two new inactive support draft JSON documents |

Existing lifecycle/OpenAPI expectation tests reflect the actual new resources
while retaining full schema/lifecycle checks. Shared logs and unrelated
untracked work remain preserved. No automatic-capture claim is made from
manually reconstructed history.

Final preservation checks: HEAD remains
`0eb1aad733defc398140d14ea4e9584192420e68` on
`codex/github-oauth-ai-chatbots`; the index is empty. The working tree contains
38 modified and 48 new non-log files, plus five preserved shared-log files.
The file map above groups the implementation, contract, test and documentation
changes. `git diff --check` passed. Existing private environment files,
dependency lockfiles, the architecture guard and historical API documentation
are unchanged. A fresh comparison confirmed the exported OpenAPI exactly
matches the actual application schema (41 paths / 45 operations). Backend
readiness and the frontend `/learn` page both returned HTTP 200; these health
checks are separate from the genuine AI-answer acceptance described above.

## Sohaib handoff and remaining acceptance

1. Configure matching public Supabase/API settings in root .env.local, general
   settings in backend/.env, and GEMINI_API_KEY privately in backend/.env.gemini.
   Start through the explicit free-tier launcher. Do not place private keys in
   frontend settings or use another machine's loopback address as shared hosting.
2. Back up and forward-upgrade each machine's own database; do not copy another
   learner's database or reset history.
3. Use learningGuidesApi for /learn private creation, owned listing and reader.
   Preserve idempotency keys for uncertain writes and pending/unavailable states.
   Practice and examples stay ungraded/unexecuted.
4. The owner privately configures the GitHub App using the exact setup guide.
   Use githubProjectsApi and the /projects callback; selected repositories and
   read-only permissions are mandatory. Social-login enablement is optional.
5. Repeat the recorded genuine support/tutor/guide acceptance on Sohaib's own
   machine: citations, follow-ups, actual source and guide save/reopen. Account
   isolation has fixture coverage; no second real external account was used in
   this run. Review the proposed corpus copy before activating new Help articles.
6. Full local backend/coverage and browser regressions have passed as recorded
   above. Complete live GitHub authorization before claiming repository acceptance.
   Distributed token lifecycle, full-repository/PR history ingestion and persisted
   Project Learning progress remain explicit follow-up work.

No public hosting, production approval, new administrator role, paid usage or
automatic candidate publication/learner assignment was activated. The feature
branch remains uncommitted for review.

<!-- SPRINT_FILES_BEGIN -->

## Exact files changed since 8595466

The following 47 paths are local sprint changes, not a second commit.

- .gitignore
- backend/alembic/env.py
- backend/alembic/shared_versions/0012_github_authorization.py
- backend/alembic/shared_versions/0013_repository_knowledge.py
- backend/app/ai/github_projects.py
- backend/app/ai/providers/github_app.py
- backend/app/api/v1/github_projects.py
- backend/app/api/v1/project_knowledge.py
- backend/app/core/github_credentials.py
- backend/app/core/github_settings.py
- backend/app/db/github_models.py
- backend/app/db/github_projects.py
- backend/app/db/project_knowledge.py
- backend/app/db/project_knowledge_models.py
- backend/app/main.py
- backend/app/repositories/github_projects.py
- backend/app/repositories/project_knowledge.py
- backend/app/schemas/github_projects.py
- backend/app/schemas/project_knowledge.py
- backend/app/schemas/project_questions.py
- backend/app/services/github_authorization.py
- backend/app/services/github_projects.py
- backend/app/services/project_ingestion.py
- backend/app/services/project_knowledge.py
- backend/github.env.example
- backend/openapi.json
- backend/tests/fixtures/live_ai_e2e_server.py
- backend/tests/integration/test_ai_lifecycle.py
- backend/tests/integration/test_api.py
- backend/tests/integration/test_evidence_feedback_lifecycle.py
- backend/tests/integration/test_github_authorization.py
- backend/tests/integration/test_github_projects.py
- backend/tests/integration/test_learner_feedback.py
- backend/tests/integration/test_legacy_project_source_policy.py
- backend/tests/integration/test_project_knowledge_http.py
- backend/tests/integration/test_repository_knowledge_persistence.py
- backend/tests/unit/test_github_app_client.py
- backend/tests/unit/test_project_ingestion.py
- backend/tests/unit/test_project_questions.py
- docs/frontend/github-app-project-learning.md
- docs/frontend/trace-platform-handoff.md
- docs/reports/trace-ai-and-github-acceptance.md
- src/components/projects/github-projects.tsx
- src/lib/api/github-projects.ts
- src/lib/api/schema.d.ts
- tests/ai-e2e/live-ai.spec.ts
- tests/components/github-projects.test.tsx

<!-- SPRINT_FILES_END -->
