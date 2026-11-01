# Module 4 environment handoff for Sohaib

These are shareable templates containing only blank project fields and suggested
local defaults. No values were copied from an existing private environment file.
They have not been activated, committed or pushed.

## Local inspection result

Inspected checkout: `C:\Users\soore\OneDrive\Dokumen\ChatGPT\Trace-v1`.

| Exact file | Observed state |
|---|---|
| `C:\Users\soore\OneDrive\Dokumen\ChatGPT\Trace-v1\.env.local` | Absent |
| `C:\Users\soore\OneDrive\Dokumen\ChatGPT\Trace-v1\backend\.env` | Present; 12 existing development settings configured; no Supabase settings explicitly supplied |
| `C:\Users\soore\OneDrive\Dokumen\ChatGPT\Trace-v1\.env.local.example` | Present; local app/API URLs supplied, both shared Supabase fields blank |
| `C:\Users\soore\OneDrive\Dokumen\ChatGPT\Trace-v1\backend\.env.example` | Present; shared project URL/issuer/JWKS blank; application defaults supplied |

The existing backend configuration parses successfully. Its database/local-cookie,
Origin, logging, timeout, fake-tutor and credential-lifetime settings are present;
their actual values are withheld. The shared project URL, issuer and JWKS are
missing. Audience/cache/loopback-auth settings are absent from the actual file but
already have application defaults, so their absence is not a separate credential
blocker.

No other standard root Next env files or relevant inherited overrides in the audit
process were found. Authentication is unconfigured in these inspected sources,
rather than pointing at a real hosted project or the loopback test Auth fixture.
This does not establish whether the team's shared project exists elsewhere. Its
dashboard settings and live authentication were not checked.

## What to obtain from the shared project

| Setting | Source | Where it goes |
|---|---|---|
| Project URL | Team's existing Supabase project's connection/API settings | Both `NEXT_PUBLIC_SUPABASE_URL` and `TRACE_SUPABASE_URL` |
| Publishable key | Same project's publishable client key | `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` only |
| JWT issuer | Exact project URL without trailing slash, followed by `/auth/v1` | `TRACE_SUPABASE_ISSUER` |
| Public JWKS URL | Exact issuer followed by `/.well-known/jwks.json` | `TRACE_SUPABASE_JWKS_URL` |

All project fields must agree. Use the shared project, rather than creating another
project just for this checkout. The frontend currently accepts the publishable
`sb_publishable_` format. A service-role key, `sb_secret_` key or legacy JWT-shaped
key is not a substitute for this frontend setting. No actual key is included here.

`authenticated` is the application's configured audience default; `300` seconds is
the JWKS cache default. Neither is a secret to obtain. The local Auth-fixture switch
stays false when using hosted Supabase. The backend needs no Supabase API secret.

## What belongs to Sohaib's machine

- `NEXT_PUBLIC_SITE_URL`: the exact frontend origin he opens. The suggested local
  default is `http://localhost:3000`.
- `NEXT_PUBLIC_API_BASE_URL`: his local FastAPI origin, suggested
  `http://localhost:8000`. It has an automatic hostname/port-8000 fallback if absent.
- `TRACE_CORS_ORIGINS`: explicitly allow his frontend origin. It is not the
  Supabase project URL. If ports change, update the origins accordingly.
- `TRACE_DATABASE_URL`: his own local SQLite database. The supplied relative path
  resolves inside his checkout's `backend` folder; do not copy another person's DB.
- Cookie mode: the supplied non-Secure opt-ins are for loopback HTTP development.
  They are not settings for a public HTTPS environment.

Use matching browser and API hostnames throughout. If choosing `127.0.0.1`, change
both frontend URLs consistently and open that address. The default CORS list allows
both standard loopback origins, but mixing hostnames still breaks cookie behavior.

## Applying the templates on his machine

1. Use a checkout containing Module 4 and migration `0005_account_identity`.
2. If the destinations do not exist, copy `frontend.env.example` to the checkout's
   root `.env.local` and `backend.env.example` to `backend/.env`. If files already
   exist, merge only the needed settings; preserve existing configuration.
3. Fill the blank shared fields from the same project, then review local URLs,
   CORS, database path and cookie mode. Do not enable the automated Auth fixture.
4. Install locked dependencies and apply the explicit migration/seed steps in the
   existing [account setup guide](../account-setup.md), then start frontend and API.
5. Restart the processes after environment changes. Rebuild if using a production
   Next build, because public environment settings are compiled into that build.
6. Test signup/confirmation, password login, Google, recovery, logout and an explicit
   guest-history claim. These templates do not prove those live flows passed.

## Shared dashboard prerequisites

The project owner must confirm email/password with required email confirmation,
Google OAuth configuration, ES256 or RS256 signing/JWKS, confirmation/recovery email
templates, and usable email delivery/SMTP. Google and SMTP secrets stay in their
provider dashboards; they are not values Sohaib needs to paste into these files.

The shared Auth redirect allowlist must permit his exact app origin's
`/auth/callback`, `/auth/callback?type=signup` and
`/auth/callback?type=recovery`. The current email templates use the shared Auth
Site URL, so agree on that URL with teammates. If using a different frontend origin,
coordinate the shared Site URL/templates as well as the allowlist; changing a
global project setting can affect other testers. The exact setup and manual
verification steps remain in [the setup guide](../account-setup.md).

Neither the actual environment files nor the existing example files were modified
by this inspection. No authentication code was changed and no commit/push was made.
