# Trace AI and GitHub acceptance audit

Updated 4 November 2026 (Asia/Calcutta); work began 3 November. Branch:
codex/github-oauth-ai-chatbots. Starting implementation commit:
0eb1aad733defc398140d14ea4e9584192420e68. Fetched origin/main includes merged
PR #22 (1aea8b8). Existing user work, logs and historical records were preserved.
This task has not staged, committed, pushed, merged, deployed or provisioned a
paid resource.

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
