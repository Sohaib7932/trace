# Supabase account setup

Manual provider configuration is required. Guest learning works with the Supabase
settings blank. Automated tests used a controlled fixture, not a real project,
Google consent or SMTP delivery.

## Provider dashboard

1. Create your own Supabase project. Use Auth only; retain Trace's SQLAlchemy/
   SQLite application data and FastAPI backend. No Data API integration is needed.
2. Enable email/password and **Confirm email**. Set minimum password length to at
   least 12. Do not add phone, anonymous-provider, OTP-entry or magic-link login.
   Trace guests remain its existing local pseudonymous learners.
3. Set Auth Site URL to the exact frontend origin you open. Locally choose either
   `http://localhost:3000` or `http://127.0.0.1:3000` consistently. Add these exact
   redirect URLs to the Auth allowlist and verify dashboard matching:

   - `<APP_ORIGIN>/auth/callback`
   - `<APP_ORIGIN>/auth/callback?type=signup`
   - `<APP_ORIGIN>/auth/callback?type=recovery`

   Public environments need their real HTTPS origin, without broad wildcards.
   Trace pins redirects to `NEXT_PUBLIC_SITE_URL`; arbitrary next/Host values are ignored.
4. Configure confirmation and reset email templates. These provider token-hash
   links can open in another browser without an initiating PKCE verifier:

   Signup confirmation:

   ```html
   <a href="{{ .SiteURL }}/auth/callback?token_hash={{ .TokenHash }}&type=signup">Confirm your email</a>
   ```

   Password recovery:

   ```html
   <a href="{{ .SiteURL }}/auth/callback?token_hash={{ .TokenHash }}&type=recovery">Reset your password</a>
   ```

   SDK `verifyOtp` is used only for these confirmation/recovery links. There is no
   OTP-entry/passwordless login. Standard PKCE code callbacks are also implemented;
   they require the initiating browser's SDK verifier cookie. Validate both email
   templates in your real project.
5. In Google Cloud configure OAuth consent audience/test users and authorized
   domains, then create a Web OAuth client. Use the **Supabase callback URL shown
   in its Google provider settings** as Google's authorized redirect URI. Enter
   Google ID/secret only in the Supabase dashboard and enable Google there. Google
   returns to Supabase; Supabase returns to Trace. No Google secret goes in Trace.
6. Activate an asymmetric JWT signing key: **ES256/P-256** or **RS256**. Follow the
   provider's migration/rotation steps and check matching public kid/algorithm at
   JWKS. HS256-only projects cannot authenticate to FastAPI. Do not add a shared
   secret bypass. Respect the documented standby-key/edge-cache propagation period.
7. Obtain your project URL and **publishable** `sb_publishable_…` key. Never use a
   service-role, `sb_secret_…`, signing private key or Google secret in frontend.
   Frontend URL, backend issuer and JWKS must refer to the same project. The normal
   access-token audience is `authenticated`.
8. Configure custom SMTP in Supabase before production email use. Verify sender,
   domain and deliverability with your provider; SMTP credentials stay in the
   dashboard. Supabase's default service is restricted to authorized team addresses,
   heavily rate-limited and best effort. It does not prove production delivery
   readiness. Configure provider abuse controls and monitor actual failures.

Supabase manages same-verified-email Google/email identity linking. Trace never
merges by email. Different-email manual linking and multi-history merge are outside
this module. Trace roles use its local audited operator CLI.

## Local configuration

Preserve existing files. If absent, copy root `.env.local.example` to `.env.local`
and `backend/.env.example` to `backend/.env`. Fill blank values from your own project.

| Frontend setting | Value |
|---|---|
| NEXT_PUBLIC_API_BASE_URL | Matching-host API origin, normally port 8000 |
| NEXT_PUBLIC_SITE_URL | Exact frontend origin, normally port 3000; pins redirects and cookie protocol |
| NEXT_PUBLIC_SUPABASE_URL | Your project's HTTPS URL |
| NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY | Your project's publishable key |

| Backend setting | Value |
|---|---|
| TRACE_SUPABASE_URL | Same project URL |
| TRACE_SUPABASE_ISSUER | Project URL + `/auth/v1` |
| TRACE_SUPABASE_JWKS_URL | Issuer + `/.well-known/jwks.json` |
| TRACE_SUPABASE_AUDIENCE | `authenticated` |
| TRACE_AUTH_JWKS_CACHE_SECONDS | Default 300, maximum 600 |
| TRACE_AUTH_ALLOW_INSECURE_LOOPBACK | False for hosted Supabase; true only for explicit loopback test Auth |

All three backend project fields must be set together or all blank. Issuer/JWKS
must belong to the same configured project. No backend service secret is required.
Guest cookies retain explicit local `TRACE_COOKIE_SECURE=false` and
`TRACE_ALLOW_INSECURE_LOCAL_COOKIES=true` opt-ins. SDK cookie Secure follows the
**app** origin, not the provider's URL. Use HTTPS for public environments and matching
browser/API hostnames. Do not mix localhost and 127.0.0.1.

From root run `npm ci`. From backend:

```sh
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked python -m scripts.seed
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload --no-access-log
```

Start `npm run dev` from root. Public Next settings are compiled into production
builds, so rebuild after changes. Missing frontend config shows a notice. A supplied
Bearer to an unconfigured backend fails with 503, never guest fallback.

## Real provider checks still required

Verify signup/confirmation delivery, expired/resend links, password login, reset
delivery/change, Google consent/cancellation, refresh and logout using your actual
project. Start a guest lesson, sign in, explicitly claim it, and resume on another
device. Check a conflicting account/guest history without merging. Verify stable
subject under supported provider-managed same-email linking.

Do not claim these checks passed until performed. Automated tests do not prove
Google credentials/consent publication, SMTP delivery or deployment readiness.
Issued access tokens can remain usable until expiry after logout; see
[authentication/security notes](authentication.md).

## Controlled-auth browser tests

The isolated test-only Auth fixture runs on loopback 8001, learning on 8000 and
production Next on 3100. Keys are generated at startup; synthetic users, links and
refresh sessions exist only in memory. No fixture/time route exists in the normal
app. No real Google, Supabase or email service is called.

Use this **test-only process environment**, then build/run browsers. Do not save it
as your normal provider configuration:

```powershell
$env:NEXT_PUBLIC_API_BASE_URL='http://127.0.0.1:8000'
$env:NEXT_PUBLIC_SITE_URL='http://127.0.0.1:3100'
$env:NEXT_PUBLIC_SUPABASE_URL='http://127.0.0.1:8001'
$env:NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='sb_publishable_controlled_test_fixture'
npm run build
npm run test:e2e
```

POSIX shells can set the same environment variables before building. Playwright
starts/stops all three servers, refuses existing servers and migrates/seeds a new
temporary Trace DB. Browser calls use the official SDK and real FastAPI; account
traces are disabled. CI supplies these fixture values explicitly. Restore normal
process settings and rebuild before real provider use.

## Official references checked

- [Auth](https://supabase.com/docs/guides/auth), [passwords](https://supabase.com/docs/guides/auth/passwords), [Google](https://supabase.com/docs/guides/auth/social-sign-in/auth-google)
- [SSR clients/proxy](https://supabase.com/docs/guides/auth/server-side/creating-a-client), [SSR details](https://supabase.com/docs/guides/auth/server-side/advanced-guide)
- [JWT/JWKS](https://supabase.com/docs/guides/auth/jwts), [identity linking](https://supabase.com/docs/guides/auth/auth-identity-linking)
- [Email templates](https://supabase.com/docs/guides/auth/auth-email-templates), [SMTP](https://supabase.com/docs/guides/auth/auth-smtp), [sessions](https://supabase.com/docs/guides/auth/sessions)
- [PyJWT crypto validation](https://pyjwt.readthedocs.io/en/stable/usage.html)

Installed Next 16.4.3 proxy, cookies, route handler, useRouter and connection guides
were read locally before framework changes. No framework upgrade was made.
