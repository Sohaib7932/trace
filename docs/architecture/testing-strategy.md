# Testing strategy

Tests prove engineering behaviour, not a learner's understanding or improved retention.
Module 1's checks remain, with schema/path inventories extended for real Module 2
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
Configured CI is distinct from remotely executed CI; no push is authorized.

Coverage is a gap detector, not proof. Aim to preserve the 97.48% Module 1 baseline
without tests that merely mirror constants. The critical Module 2 tests cover original
answer preservation, all ownership states, actual body/422/zero-row evidence,
content/201/exact fresh read, failed/error distinction, replay/no duplicate notes,
old-run isolation, commit/readback faults, hint limits, and server completion rules.
Exact local results and limitations belong in the Module 2 report, never guessed.
