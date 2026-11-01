# Auth setup checklist (manual steps)

Code can't do these steps. They configure Supabase, Google and email delivery for a
real project. Use placeholders as written: `<APP_ORIGIN>` is the exact address you
open Trace at (for example `http://localhost:3000` locally, `https://<your-domain>`
in production), and `<project-ref>` is your Supabase project reference.

Never put secrets in the frontend. The only Supabase key the browser uses is the
**publishable** key (`sb_publishable_…`).

See also: [account setup](architecture/account-setup.md) (full detail, email templates)
and [authentication](architecture/authentication.md) (security model).

## 1. Supabase URL configuration

Supabase dashboard → Authentication → URL Configuration.

- [ ] **Site URL**: `<APP_ORIGIN>`. Locally pick one of `http://localhost:3000` or
      `http://127.0.0.1:3000` and always open Trace at that exact address; cookies and
      sign-in links don't carry over between the two.
- [ ] **Redirect URLs**: add, for every origin you use (local and production):
  - `<APP_ORIGIN>/auth/callback`
  - `<APP_ORIGIN>/auth/callback?type=signup`
  - `<APP_ORIGIN>/auth/callback?type=recovery`
- [ ] No broad wildcards in production.

Why this matters: if a `redirectTo` isn't on this list, Supabase silently sends the
user to the Site URL instead, and the sign-in never completes. Trace builds every
redirect from `NEXT_PUBLIC_SITE_URL`, so that value must equal the Site URL's origin.
Trace keeps the post-sign-in destination in its own short-lived cookie, so no extra
redirect entries (no `?next=` wildcards) are needed.

## 2. Email and password

Authentication → Providers → Email (and Authentication → Policies / Password settings).

- [ ] Email provider enabled.
- [ ] **Confirm email** on.
- [ ] Minimum password length **12** (the sign-up form tells learners "at least 12
      characters" and checks it before sending; keep the two in step).
- [ ] Email templates use the token-hash links shown in
      [account setup](architecture/account-setup.md#provider-dashboard) step 4.

## 3. Google provider

### 3a. Google Cloud console

- [ ] Create or choose a Google Cloud project.
- [ ] **OAuth consent screen**: app name, support email, authorized domain
      (`<your-domain>`), developer contact. Add test users while in "Testing", or publish.
- [ ] **Credentials → Create credentials → OAuth client ID → Web application.**
- [ ] **Authorized JavaScript origins**: `<APP_ORIGIN>` for each origin you use.
- [ ] **Authorized redirect URIs**: exactly
      `https://<project-ref>.supabase.co/auth/v1/callback`
      (copy it from Supabase → Authentication → Providers → Google; Google redirects to
      Supabase, never directly to Trace).
- [ ] Copy the **Client ID** and **Client secret**.

### 3b. Supabase

- [ ] Authentication → Providers → **Google → Enable**.
- [ ] Paste the Client ID and Client secret. They stay in the Supabase dashboard only.
- [ ] Save.

How Trace behaves: before redirecting, the sign-in page asks Supabase whether Google
is enabled. While it isn't, learners see "Google sign-in isn't set up on this site
yet" instead of a blank error. As soon as you enable it, the same button works; no
code change or rebuild is needed.

Common errors:

| Symptom | Fix |
|---|---|
| "Google sign-in isn't set up on this site yet" | Step 3b not done or not saved |
| Google shows `redirect_uri_mismatch` | The redirect URI in 3a isn't exactly the Supabase callback URL |
| Returns to the homepage without signing in | `<APP_ORIGIN>/auth/callback` missing from the Supabase redirect list (step 1) |
| "Open Trace at … to sign in with Google" | You opened a different host than `NEXT_PUBLIC_SITE_URL` (e.g. 127.0.0.1 vs localhost) |

## 4. Custom SMTP (before real users)

Authentication → Emails → SMTP Settings.

- [ ] Enable custom SMTP with your provider's host, port, username and password.
- [ ] Verify the sender domain (SPF, DKIM, DMARC) with your email provider.
- [ ] Send yourself a sign-up confirmation and a password reset; check both arrive and
      the links open `<APP_ORIGIN>/auth/callback…`.

Supabase's built-in email is heavily rate-limited and only for team addresses; it's
fine for a first local check, not for learners.

## 5. Asymmetric JWT signing keys

Project Settings → JWT Keys (Signing keys).

- [ ] Create and activate an **ES256 (P-256)** or **RS256** signing key.
- [ ] Wait for the standby/rotation period the dashboard shows.
- [ ] Check `https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json` lists the
      key. The FastAPI backend verifies tokens with this public key set; HS256-only
      projects can't sign in to Trace.

## 6. Environment variables (names only)

Frontend (`.env.local`, public values, rebuild after changing):

| Variable | Meaning |
|---|---|
| `NEXT_PUBLIC_SITE_URL` | `<APP_ORIGIN>`, must match the Supabase Site URL |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | The project's publishable key |
| `NEXT_PUBLIC_API_BASE_URL` | FastAPI origin (same hostname as `<APP_ORIGIN>`) |

Backend (`backend/.env`):

| Variable | Meaning |
|---|---|
| `TRACE_SUPABASE_URL` | Same project URL |
| `TRACE_SUPABASE_ISSUER` | Project URL + `/auth/v1` |
| `TRACE_SUPABASE_JWKS_URL` | Issuer + `/.well-known/jwks.json` |
| `TRACE_SUPABASE_AUDIENCE` | `authenticated` |
| `TRACE_CORS_ORIGINS` | Must include `<APP_ORIGIN>` |

Never add a service-role key, `sb_secret_…` key, JWT private key, Google client
secret or SMTP password to either file.

## 7. Check it end to end

- [ ] Sign up → "Check your inbox" → confirmation link → lands on `/account`.
- [ ] Sign out → sign in with email and password → lands on `/learn`.
- [ ] Forgot password → reset link → new password → sign in.
- [ ] Continue with Google → consent → lands on `/learn`; cancel on the consent screen →
      back on sign-in with "Sign-in was cancelled".
- [ ] As a guest, start a lesson; then sign in with a new account → `/account` offers to
      keep the guest progress → claim → it appears under "How you learned".
