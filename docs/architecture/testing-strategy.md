# Testing strategy

## Module 4 authentication evidence

Generated local ES256 and RS256 keys test signature, algorithm/kid, issuer/audience,
claim types, expiry/nbf, malformed tokens, unknown keys/rotation, bounded caching and
safe JWKS outages. No production key is used. Injectable sources and clocks avoid
external network/time dependence. Token-bearing request logs are checked for leaks.

Account tests use real SQLite transactions for concurrent first login/learner
creation, role isolation/operator audits, claim replay, conflicting histories,
invalid/missing/expired/revoked guests, competing claims and rollback after writes.
A populated Module 3 history (original/transfer attempts, runtime evidence and a
retrieval response) survives downgrade to 0004, re-upgrade and explicit account claim
with every learning row unchanged. Account-data downgrade refuses before deleting.
Legacy migration tests freeze only the historical credential query while creating
old-schema evidence; post-upgrade assertions use the current owner guard.

Frontend tests cover provider forms, safe errors, pending confirmation/resend,
Google initiation, reset/logout, claim confirmation/conflict/retry and trusted role
display. SDK refresh failures cannot trigger anonymous fallback. Callback tests
check pinned origins, allowed confirmation/recovery types and verified server gates.

Playwright adds a separate loopback Auth protocol fixture with generated public
keys, synthetic in-memory users/mailbox and rotating refresh sessions. The official
SDK makes real HTTP calls to it; FastAPI independently fetches JWKS/verifies JWTs.
Browser tests exercise confirmation, password login/recovery, actual refresh,
authenticated learning/reload, explicit guest claim, second-user rejection and
logout/protected pages on desktop/mobile. Original six guest journeys stay enabled.
Credential-bearing traces are off. No real Google consent, Supabase project or SMTP
delivery is claimed. See [fixture build instructions](account-setup.md).

Current results belong in [Module 4 report](module-4-report.md); older numbers below
are historical. CI uses pinned loopback auth settings for the browser build and
retains Windows/Linux backend checks. Production startup has no fixture bypass.

Tests prove engineering behaviour, not a learner's understanding or improved retention.
Module 1's checks remain, with schema/path inventories extended for real Module 2/3
features rather than removing their assertions. Its historical report stays unchanged.

| Level | What it proves | What it does not prove |
|---|---|---|
| Pure domain | State transitions, completion gate and consistent/contradictory observation handling | Actual HTTP or DB I/O |
| Repository/DB | Commit/rollback, scoped sessions, FKs, immutable records, key/sequence uniqueness | PostgreSQL semantics or backup restore safety |
| Migration | Upgrade/check/downgrade/re-upgrade; populated legacy constraint repair preserves evidence/triggers | Arbitrary future schema changes |
| API | Cookie lifecycle, hashed storage, ownership/CSRF/CORS, typed errors, retry identity and persisted history | Public deployment hardening |
| Verification | Actual private ASGI/FastAPI validation plus committed write and distinct-session readback; failure injection | General Python execution correctness |
| Tutor contract | All three existing fake operations, progressive bounded recorded help and provider error handling | Gemini/Claude calls or teaching quality |
| Frontend component/client | Forms, locking, guidance, feedback/evidence/error rendering, history/resume/progress, cookies and retry headers | Real backend persistence |
| Browser | Real learning journey and reload with no API response mocks, plus preserved marketing demo | Every browser or learning effectiveness |
| Architecture | No domain-to-HTTP/ORM/SDK imports or route-embedded DB implementation; generated-contract boundary | Every possible design flaw |

## Deterministic isolation

Backend tests create fresh app/settings/database resources and temporary SQLite
files. They explicitly migrate and seed fixtures. Never use the development DB.
External connections are blocked with pytest-socket; loopback/Unix sockets remain
allowed for Windows asyncio internals. The real exercise HTTP uses in-process ASGI,
not an external service. No provider keys or SDKs are required. Fault injection
covers actual note INSERT/commit failures, unavailable readback and forged success
responses; these injections are not presented as successful real verification.

Concurrent submissions use real independent SQLAlchemy sessions/transactions.
Migration repair tests populate a completed session before upgrade and compare its
entire saved history afterwards, then verify the immutability triggers still reject
rewrites. Schema checks retain exact model/table and required API inventories.

Component tests use clearly identified fixtures. Browser tests do not mock the
learning API: Playwright starts Uvicorn through an explicit E2E-only bootstrap using
a new temporary DB, applies migrations/seeding, and starts the production Next app.
Each browser context gets a distinct anonymous learner. Credential-bearing traces
are disabled for the learning test, so raw cookies are not exported as test artifacts.
Screenshots show only visible learning content. Stop servers before deleting fixtures.

## Quality gates and execution

Backend: uv locked sync, Ruff check/format, strict mypy, pytest with branch coverage,
Alembic upgrade/check and deterministic OpenAPI export. Frontend: npm ci, ESLint,
Next type generation/TypeScript, Vitest/Testing Library, production build and
Playwright desktop/mobile Chromium. Shared: generated-schema/type drift check and
existing Codex logger regression tests without edits to the logger or trust state.
CI runs backend on Windows/Linux and provisions Python for the browser backend.
Configured CI is distinct from remotely executed CI; actual observed run results
belong to the delivery report. Module 3 explicitly authorizes its feature-branch push.

Coverage is a gap detector, not proof. Aim to preserve the 97.48% Module 1 baseline
without tests that merely mirror constants. The critical Module 2 tests cover original
answer preservation, all ownership states, actual body/422/zero-row evidence,
content/201/exact fresh read, failed/error distinction, replay/no duplicate notes,
old-run isolation, commit/readback faults, hint limits, and server completion rules.
Exact local results and limitations belong in the Module 2 report, never guessed.

## Module 3 transfer and retrieval

The original 95 backend, 14 frontend, four browser and 24 logging tests are retained.
New integration tests cover transfer prerequisite/prediction/investigation enforcement,
independent seed/hash/version pinning, actual flat/nested HTTP and fresh task reads,
separation from notes, idempotent no-duplicate writes, commit/readback/forged-response
failures, and atomic completion/schedule rollback/recovery. The migration test upgrades
real populated Module 2 history and verifies immutability afterwards; downgrade with
transfer history is refused rather than deleting it.

An injected mutable clock checks one microsecond before/exactly at due boundaries,
UTC durations across offset changes, late/missed checkpoints, retry/completion/history,
owner/origin/input protections, question-key nondisclosure and concurrent independent
write transactions for scheduling and response sequences. Credential tests cover
near-expiry renewal without owner/token changes and invalidation between read/write.
Authentication remains on real security time; advancing the retrieval fixture clock
does not silently extend or bypass credentials.

Frontend tests exercise transfer navigation/gating/mapping, factual journey dates,
answer/feedback timing, query failures and stable submission retry keys/drafts.
Desktop/mobile E2E completes original then actual transfer (422/zero, 201/fresh task),
checks both schedules, advances the test-bootstrap-only clock file, submits incorrect
then correct retrieval, completes a missed checkpoint and reloads persisted history.
Successful API responses are never mocked in these browser tests. No public clock
endpoint or production test-time setting exists. One worker serializes the fixture
clock; traces remain off for credential-bearing journeys. Screenshots are inspected
but ignored by Git. All old homepage/lesson browser tests remain active.

Keep Module 1/2 reports historical. Module 3 records fresh counts/coverage, generated
contract drift, actual browser runs, local commands and separately observed remote CI.
