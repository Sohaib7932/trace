# Trace

Trace helps AI-assisted builders read, diagnose, change and verify code themselves.
Modules 2 and 3 implement a connected journey: a Python/FastAPI field-name mismatch,
a different nested-payload transfer problem, then retrieval checkpoints at +1/+7 days.

The existing marketing homepage and Express sample demo are preserved and still
labelled sample output. The real learning journey is separate:
**http://localhost:3000/learn/fastapi-payload-mismatch**.
After completing it, continue to
**http://localhost:3000/learn/fastapi-nested-payload-transfer**.
Both routes show persisted original/transfer progress and upcoming/due/completed
retrieval checkpoints when this anonymous learner returns.

## Requirements

Node 24.x/npm, Python 3.13.x, uv and Git. Use the existing npm and uv lockfiles.
Next remains 16.4.3; no framework upgrade. No Gemini/Claude key or SDK is needed.
Existing agent logs also require GitHub CLI and individually trusted hooks; see
`scripts/CODEX_LOGGING.md`. Module 2 does not modify their adapter or trust state.

## Start locally

From root:

```sh
npm ci
npm run dev
```

In another terminal:

```sh
cd backend
uv sync --locked
```

For local HTTP, copy `.env.example` to `.env` if it does not exist (PowerShell:
`Copy-Item .env.example .env`; POSIX: `cp .env.example .env`). Preserve existing
configuration and add the documented settings as needed. The example explicitly
sets `TRACE_COOKIE_SECURE=false` and `TRACE_ALLOW_INSECURE_LOCAL_COOKIES=true`;
without that local opt-in cookies default to Secure. Never use non-Secure cookies
for a public HTTPS deployment. Non-Secure mode rejects non-loopback frontend origins.

```sh
uv run --locked alembic upgrade head
uv run --locked python -m scripts.seed
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload --no-access-log
```

Seeding publishes both lessons idempotently and refuses changed published content;
use a new version instead of overwriting either 1.0.0. Startup never creates tables
or seeds implicitly. Module 3 adds migration `0004_transfer_retrieval`, which preserves
existing history and refuses downgrade if transfer history would be lost.
The local `backend/trace.db` file is ignored by Git. Relative DB paths resolve from
backend independently of shell cwd.

Open the learning route. The client uses the browser hostname on port 8000 unless
`NEXT_PUBLIC_API_BASE_URL` is set. Keep hostnames matched: localhost frontend with
localhost API, or 127.0.0.1 with 127.0.0.1. Ports may differ. `.env.local.example`
shows an optional frontend override; ownership credentials and AI keys never belong
there. Default CORS permits only localhost:3000 and 127.0.0.1:3000, with credentials.

## What actually works

- An anonymous HttpOnly cookie identifies the learner; only a SHA-256 digest is stored.
- A session pins the published lesson version. Initial predictions cannot be replaced.
- Separate numbered corrections and recorded fixture hints preserve the history.
- The body mapping actually reaches a private FastAPI route and produces HTTP 422,
  missing/extra-field validation errors, and a fresh zero-row read.
- The content mapping actually produces HTTP 201, commits a row, and reads the same
  ID/title/content through an independent SQLAlchemy session.
- Individual checks, deterministic feedback and completion are saved on the server.
  Infrastructure/readback failures are errors, not learner mistakes.
- Reload restores the owned session, original prediction, both corrections and hints.
- Original completion unlocks a separate task exercise: flat `priority` actually
  produces HTTP 422/zero tasks; nested `metadata.priority` produces 201 and an exact
  fresh-session read of the committed task. Task fixtures never count as notes.
- Transfer requires predicting and investigating the original flat request's real
  validation evidence before a nested correction. The original lesson is unchanged.
- Transfer completion atomically schedules two checkpoints at +24/+168 UTC hours.
  New shipping/report questions use deterministic choices, retain every response,
  and reveal feedback only after submission. Missed checkpoints remain available.

This is a controlled field-mapping exercise: no arbitrary Python is executed. Hints
are labelled fixtures, not live model output. Factual progress is not a mastery or
retention score. No claim of learner improvement follows from these engineering tests.

## Inspect evidence

The learning screen shows expected/observed API status, validation, row count and
stored values with sources. The browser Network response for
`GET /api/v1/sessions/{session_id}/progress` contains the same stored history.
The session ID is not a credential. Do not copy/export raw cookies to inspect data.
OpenAPI/docs: http://localhost:8000/docs; schema inspection/read endpoints are useful
there, but protected writes require the allowed frontend Origin and Trace client
header. Liveness/readiness remain at `/api/v1/health/live` and `/health/ready`.

The credential lifetime now defaults to 30 days (`TRACE_CREDENTIAL_LIFETIME_SECONDS=2592000`),
so the +7-day return does not exceed the old seven-day default. On return, the protected
anonymous bootstrap renews a still-valid credential in the latter half of its configured
lifetime and reissues its HttpOnly cookie. Existing local configs using 604800 should
be changed deliberately if seven days would prevent return access. Explicit shorter
lifetimes remain supported. Expired/revoked credentials are never renewed.

No cookie/account recovery is provided. Expiry or revocation prevents access; it
does not erase history. Explicit retention/deletion/export and production hardening
are future work. Production environment mode remains disabled in this local module.

## Quality checks

From backend:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
uv run --locked alembic upgrade head
uv run --locked alembic check
```

Tests use migrated/seeded temporary DBs, not development records. External socket
connections are blocked; Windows asyncio's internal loopback sockets remain allowed.
A restricted tool sandbox may need a writable `UV_CACHE_DIR`, e.g.
`backend/.venv/.uv-cache`, and permission for Windows loopback internals.

From root:

```sh
npm run api:generate
npm run lint
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run test:e2e
python -B -m unittest discover -s scripts/tests -v
```

For E2E, leave the API-base override unset when building, or build with
`NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`. Playwright uses frontend
127.0.0.1:3100 and starts an explicitly isolated temporary backend on port 8000.
It refuses existing servers and aborts learning API requests outside the fixture
origin rather than touching participant data. Credential-bearing test traces are
disabled. No successful API response is mocked. The production build can fetch
existing Google fonts. GitHub Actions runs on push/PR; observed remote results are
reported separately from local checks in delivery reports.

OpenAPI export requires no DB/network access. The generated TS declaration is the
shared contract; check a second generation for drift. No live SDK is installed.

## Architecture and collaboration

- [Overview](docs/architecture/overview.md)
- [Data model](docs/architecture/data-model.md)
- [API contracts](docs/architecture/api-contract.md)
- [Testing strategy](docs/architecture/testing-strategy.md)
- [Ownership ADR](docs/architecture/adr/007-pseudonymous-ownership.md)
- [Historical Module 1 report](docs/architecture/module-1-report.md)
- [Module 2 delivery report](docs/architecture/module-2-report.md)
- [Module 3 delivery report](docs/architecture/module-3-report.md)
- [Transfer/retrieval ADR](docs/architecture/adr/008-transfer-and-retrieval.md)

The monolith keeps HTTP, services, domain rules and repository/provider adapters
separate. SQLite writes use explicit transactions and DB-backed coordination.
Transfer/revisit uses the same owned session/evidence boundaries. Public deployment,
PostgreSQL, live providers, accounts/recovery and empirical learning-effectiveness
evaluation remain future work.

Sohaib owns the existing UI/design; Soorej owns backend/lesson engineering. Agent
transcripts use only the tracked shared `.claude-logs/`, separate from learner data.
Include logs with user-authorized commits. Do not stage, commit or push without
explicit approval. Genuine logs accompany authorized commits; app-generated suggestion
records are excluded and preserved without being presented as human prompts.
