# Sohaib: configure and verify real Trace AI locally

Use your own clone of the current shared branch. `<TRACE_ROOT>` means that
clone's repository root, the directory containing `package.json`, `backend/`
and `scripts/`. It is not a nested `backend/backend` directory.

## Exact files and ownership

| File | Exact destination | Purpose |
| --- | --- | --- |
| `.env.local` | `<TRACE_ROOT>/.env.local` | Frontend real/demo mode, public Supabase project settings, browser/API origins |
| `.env` | `<TRACE_ROOT>/backend/.env` | Strict backend database/authentication/CORS settings |
| `.env.gemini` | `<TRACE_ROOT>/backend/.env.gemini` | Private server-only Gemini credential |
| `.env.gemini.example` | `<TRACE_ROOT>/backend/.env.gemini.example` | Blank credential template, safe to share |
| `.env.local.example` | `<TRACE_ROOT>/.env.local.example` | Safe frontend template |
| `.env.example` | `<TRACE_ROOT>/backend/.env.example` | Safe backend template |
| `ai.env.example` | `<TRACE_ROOT>/backend/ai.env.example` | AI settings reference only; application does not automatically load it |

No real environment file should be sent to a teammate or committed. Each
developer obtains the approved project configuration and sets it privately.
Use the shared Supabase project for frontend and backend; Gemini must remain
the approved unbilled Free Tier project. No additional spending is approved.

Create missing files from their corresponding examples. Preserve existing files;
do not copy over them. For example, from the repository root in PowerShell:

```powershell
if (-not (Test-Path .env.local)) { Copy-Item .env.local.example .env.local }
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
if (-not (Test-Path backend/.env.gemini)) {
    Copy-Item backend/.env.gemini.example backend/.env.gemini
}
```

Use an editor privately to fill missing values. If your shell is already inside
`backend`, the key destination is `.env.gemini`, not `backend/.env.gemini`.
Back up any existing private file before an intentional manual edit; keep the
backup outside Git and never paste its contents into a report or chat.

## Frontend configuration

`<TRACE_ROOT>/.env.local` needs these names:

```dotenv
NEXT_PUBLIC_AI_MODE=real
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
NEXT_PUBLIC_SUPABASE_URL=<shared-project-public-url>
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<shared-project-publishable-key>
```

Replace placeholders privately. The current auth client expects the Supabase
publishable-key format, and requires `NEXT_PUBLIC_SITE_URL`. Never put a service
role, Gemini key or private signing key in frontend configuration. There is no
`NEXT_PUBLIC_GEMINI_API_KEY` setting.

Next reads `NEXT_PUBLIC_*` values at start/build time. A running preview/build
will not adopt a file change automatically in every configuration: restart the
dev process, or rebuild and restart a production preview. Mock mode is an
intentional demo mode; its response labels must remain visible.

## Backend authentication and private Gemini setup

In `<TRACE_ROOT>/backend/.env`, configure the same shared project's
`TRACE_SUPABASE_URL`, `TRACE_SUPABASE_ISSUER`, `TRACE_SUPABASE_JWKS_URL` and
`TRACE_SUPABASE_AUDIENCE`. Issuer is the project's Auth issuer and JWKS is its
public well-known signing-key endpoint. Obtain these from the approved project;
do not use token-selected URLs or substitute a service-role key.

Keep `TRACE_CORS_ORIGINS` consistent with the exact browser origin, and use
matching browser/API hostnames for local cookie behavior. The supplied local
example explicitly permits insecure cookies only for loopback HTTP. Hosted
origins require HTTPS and Secure cookies.

Put only the private credential in `<TRACE_ROOT>/backend/.env.gemini`:

```dotenv
GEMINI_API_KEY=<configure-privately>
```

Do not put `TRACE_LLM_*` settings in `backend/.env`: that file is parsed by
strict general application settings. `backend/ai.env.example` is a reference,
not an automatically loaded activation file. Plain Uvicorn does not activate
Gemini. The approved launcher supplies the process activation profile.

## Install and launch

Use the repository's Node/Python versions and locks: Node 24 and Python 3.13.
From `<TRACE_ROOT>`, install the existing locked environments:

```text
npm ci
uv sync --directory backend --locked
```

Do not reset the database if readiness reports missing migrations. Follow the
documented backup and forward migration procedure, using a consistent SQLite
backup and integrity/foreign-key checks. A credential file does not initialize
or migrate a database.

Windows PowerShell, from the repository root:

```powershell
./scripts/run-gemini-backend.ps1 -ConfirmFreeTierProject
```

Portable startup, on Windows/macOS/Linux with the locked environment installed:

```text
uv run --directory backend --locked --no-sync python -m scripts.run_gemini --confirm-free-tier-project
```

This confirmation attests that the key belongs to the approved unbilled project.
The launcher pins the approved text model, zero paid budget, no retries and
loopback binding. It preserves stricter configured bounds and restores changed
process settings after shutdown. It does not activate billing or migrate data.

In a separate terminal at the repository root:

```text
npm run dev
```

Open `http://localhost:3000`. Backend SQL readiness is
`http://localhost:8000/api/v1/health/ready`; Swagger is at
`http://localhost:8000/docs`. Do not expose the development server through a
public bind or tunnel.

## Safe diagnostics

Run the offline configuration check from the repository root:

```text
uv run --directory backend --locked --no-sync python -m scripts.ai_setup_check
```

To include only the bounded local SQL-readiness HTTP check:

```text
uv run --directory backend --locked --no-sync python -m scripts.ai_setup_check --check-backend
```

To inspect the same activation context the approved launcher will use, without
starting a server or making a Gemini request:

```text
uv run --directory backend --locked --no-sync python -m scripts.run_gemini --confirm-free-tier-project --check
```

Diagnostics expose boolean/enum state, never keys, URLs, database credentials,
JWTs, cookies or full environment contents. A diagnostic terminal's environment
is not the environment of an already-running Uvicorn process. SQL readiness does
not prove Gemini mode, Supabase login, source approval or provider availability.
An environment-file check cannot prove what a previously built browser bundle
contains; verify mode in the actual UI too.
The launcher's `--check` exit status means its configuration check executed;
inspect `ready_for_real_ai` and the individual states. It is not a live-provider,
browser-login or production certificate. A blank process key is treated as
missing by the explicit launcher, which then loads the fixed private key file;
a nonblank process key takes precedence.

## Repeatable local acceptance

1. Check the frontend file is configured for real mode and the actual UI does
   not label the exchange as a demo. Confirm the complete public auth settings.
2. Run the launcher preflight; verify key presence, approved model, Free Tier
   confirmation and zero-paid/no-retry profile. Never display the key.
3. Start the approved launcher and confirm SQL readiness. Stop an obsolete plain
   Uvicorn instance through its owning terminal first; do not kill unrelated
   processes or reset the database to free a port.
4. Sign in privately using the real shared Supabase project. Do not paste a
   password, access token, callback code or request headers into screenshots/logs.
5. Open an owned Notes/Tasks session. Ask a public engineering question through
   the existing tutor panel. Inspect response status and server-set provenance;
   `source: "ai"` establishes a provider-backed response. A typed unavailable
   response, even with HTTP 200, is not successful AI acceptance.
6. Ask Help when follow-up reviews occur. Verify source attribution and exact
   quotations from the approved corpus; no invented policy or contact should
   appear. Support remains separate from lesson tutoring.
7. Verify a guest cannot access the protected APIs and another account cannot
   access the owned session. Use disposable test identities for these checks.
8. Verify the browser request contains no provider key, evaluator data, hidden
   answers or arbitrary source selection. Confirm demo fixtures remain labelled
   when deliberately selecting mock mode.
9. Inspect sanitized status/error/request-ID diagnostics only. Do not export
   private logs or browser storage. Provider failures must remain unavailable,
   without paid/model fallback or fabricated success.
10. Record exact results on your own machine. Tests or working configuration on
    another developer's computer do not prove your local acceptance or hosted
    production authentication.

## Configuration problems and owners

| Symptom | Check / responsible action |
| --- | --- |
| Demo responses | Frontend owner sets real mode in root `.env.local` and restarts/rebuilds Next |
| Real UI, unavailable tutor/support | Backend owner uses approved launcher; checks safe profile/key/source diagnostics |
| Strict backend settings error | Remove misplaced AI keys from general `.env` only after backing up; retain them privately in their correct scope |
| Key saved but missing | Check exact `backend/.env.gemini` destination, saved nonblank value and process override precedence |
| 401 | Sign in/refresh privately; backend and frontend must target the same Supabase project |
| 403 | Check active learner role, Origin and `X-Trace-Client`; never weaken authorization |
| 404 tutor | Missing or foreign session; use the signed-in learner's actual session |
| 409 tutor | Refresh saved state/pinned session; do not bypass fresh authorization |
| 429 | Wait for allowed capacity; no retry loops or restarts to evade a cap |
| 503/504 or typed unavailable | Check provider, database, request deadlines and approved source freshness separately |
| No support sources | The question may be unsupported; do not invent an answer or activate unreviewed sources |
| OAuth/email callback issue | Shared Supabase project owner checks approved origins, redirects, provider/email configuration; no new project or credential is invented |

The frontend owner integrates the real adapter and keeps provenance visible.
The backend owner supplies validated code/configuration and safe diagnostics.
The Supabase/Gemini project owner supplies private project access and approves
dashboard changes. Hosted deployment and additional spending require separate
authorization; this local procedure does not provision either.
