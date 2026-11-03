# Real authentication acceptance

Status: **manual acceptance checklist; unchecked items are not verified**. Existing authenticated UI/JWT use has been exercised in this work block. That does not establish a fresh email registration, real confirmation/reset delivery, Google consent round trip or successful token refresh. Controlled browser fixtures exercise the application protocol without contacting real Supabase, Google or email services.

Use the actual approved environment and two operator-controlled test identities. Keep passwords, tokens, cookies, callback codes, email links, personal addresses and account identifiers out of reports, screenshots, HAR files and shared logs. Record a check ID, environment label, time, pass/fail and sanitized request ID instead. No deployment or provider setting is changed by this document.

## Configuration prerequisites

Choose one exact `<APP_ORIGIN>` and its approved API origin. Local `localhost` and `127.0.0.1` are separate cookie hosts; do not alternate between them. Hosted acceptance requires HTTPS. Public Next configuration is compiled into the build, so changing a running backend does not update the browser bundle.

| Configuration names | Acceptance requirement |
| --- | --- |
| `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_API_BASE_URL` | Exact intended frontend/API origins; correct build selected |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Same real project; browser key is publishable, never a service-role/secret key |
| `TRACE_SUPABASE_URL`, `TRACE_SUPABASE_ISSUER`, `TRACE_SUPABASE_JWKS_URL`, `TRACE_SUPABASE_AUDIENCE` | Same project, issuer and public JWKS; audience matches issued access tokens |
| `TRACE_CORS_ORIGINS` | Includes only intended browser origins, with credentials supported |
| `TRACE_COOKIE_SECURE`, `TRACE_ALLOW_INSECURE_LOCAL_COOKIES`, `TRACE_AUTH_ALLOW_INSECURE_LOOPBACK` | Hosted configuration retains secure cookies and disables insecure loopback opt-ins |

The backend accepts ES256/P-256 or RS256 public signing keys, not an HS256 bypass. Inspect configured project/signing-key compatibility privately; never copy a JWT or private key into the acceptance record. Trace uses its local account status and roles after verified identity; Google profile/user-metadata fields do not grant administrator rights. Source: `backend/app/auth/jwt.py`, `backend/app/core/settings.py`, `backend/app/api/dependencies.py`.

In the Supabase dashboard, confirm email/password and email confirmation are enabled, with password minimum matching Trace's 12-character form requirement. Check the exact Site URL and these allowlisted callbacks: `<APP_ORIGIN>/auth/callback`, the same path with `?type=signup`, and with `?type=recovery`. Use exact hosted redirect paths. Supabase documents the allowlist and recommends exact production paths. [Supabase redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls)

The existing [account setup](../architecture/account-setup.md#provider-dashboard) specifies confirmation/recovery token-hash email templates for Trace's callback. Standard PKCE code exchange is also implemented and needs the initiating browser's verifier cookie. Do not treat a callback URL as shareable evidence. [Supabase email templates](https://supabase.com/docs/guides/auth/auth-email-templates)

Real delivery requires an approved mail configuration. Supabase's default sender is restricted to project-team addresses and is best effort; success with that sender is not evidence of public-user delivery readiness. Configure/verify the authorized SMTP provider privately before broader email acceptance. [Supabase SMTP requirements](https://supabase.com/docs/guides/auth/auth-smtp)

## Email/password and recovery

| ID | Manual action | Required observation | Result |
| --- | --- | --- | --- |
| EMAIL-01 | In a fresh browser context, open `/sign-up` and register an authorized test identity | Confirmation notice; no authenticated account is established before confirmation | Not run |
| EMAIL-02 | Open the received confirmation link privately | Correct configured origin; `/account` after success; backend `/api/v1/account/me` succeeds with the verified account | Not run |
| EMAIL-03 | Try an unconfirmed account, an incorrect password and an expired/used confirmation link | Fixed safe error; no provider description, token or submitted password reflected; no account/session crossover | Not run |
| EMAIL-04 | Use resend once subject to displayed cooldown/provider limits; open only the intended new link | Real mail arrives and the verified account is usable; missing delivery is reported as blocked | Not run |
| EMAIL-05 | Sign out, sign in with the confirmed email/password, then reload `/account` and `/learn` | Same account and saved learner history, not a replacement guest identity | Not run |
| RESET-01 | Use `/forgot-password`, receive the real recovery email and open it privately | Generic send notice; callback reaches protected `/reset-password` with a valid recovery session | Not run |
| RESET-02 | Set a valid new password and complete sign-out | `/sign-in`; new password works; old password fails; saved work survives | Not run |
| RESET-03 | Open a used/expired recovery link or reset page without a session | Safe error/sign-in boundary, not an unauthenticated password-change capability | Not run |

Trace calls `signUp`, `signInWithPassword`, `resetPasswordForEmail`, `verifyOtp`/`exchangeCodeForSession`, and `updateUser` through the official SDK. The callback allows only its own validated destination cookie, not an external query-string `next` destination. Sources: `src/components/auth/auth-form.tsx`, `src/app/auth/callback/route.ts`, `src/app/reset-password/page.tsx`, `src/lib/auth/next-path.ts`. Supabase's documented email/password and recovery flow is the external reference; actual mail receipt must still be observed. [Supabase password authentication](https://supabase.com/docs/guides/auth/passwords)

## Google OAuth

Privately verify the intended Google consent audience/test users and Web OAuth client. Google's authorized redirect URI is the **Supabase callback shown by that project's Google provider settings**; Supabase then redirects to Trace's allowlisted callback. Put the Google client secret only in provider configuration. Trace does not need Google credentials in its frontend or FastAPI environment. [Supabase Google setup](https://supabase.com/docs/guides/auth/social-sign-in/auth-google)

| ID | Manual action | Required observation | Result |
| --- | --- | --- | --- |
| GOOGLE-01 | Open the exact configured app origin and choose Continue with Google | Intended Google consent screen/account; no redirect mismatch or unapproved client | Not run |
| GOOGLE-02 | Complete the consent round trip | Supabase-to-Trace callback succeeds; account API and `/learn` work for that identity | Not run |
| GOOGLE-03 | Cancel consent and retry | Fixed cancellation message, no raw provider error; a later successful retry works | Not run |
| GOOGLE-04 | Check supported same-verified-email linking if the product will rely on it | Identity mapping is provider-managed and observed; Trace does not merge histories merely by matching email | Not run |

An enabled button or successful email login does not verify OAuth. A disabled provider, consent-testing restriction, missing allowlist or blocked popup/redirect remains an acceptance blocker. Do not enable arbitrary account linking or change consent/publication settings as a test workaround.

## Refresh, cookies and logout

The retry policy below applies to ordinary account/learning calls. Tutor and
support AI POSTs deliberately disable automatic refresh/replay because another
provider attempt can consume allowance. Refresh identity explicitly and let the
learner choose whether to submit a new AI request; do not show a fixture answer
as a substitute.

Trace's SSR proxy calls `getClaims()` and propagates refresh cookies to both the request and response. Rendering does not trust `getSession().user` for authorization. The browser API client obtains the access token and, after an authenticated 401, attempts one SDK refresh/replay using the same write idempotency key. It never sends the refresh token to FastAPI or silently drops an invalid bearer to become a guest. Sources: `src/proxy.ts`, `src/lib/supabase/server.ts`, `src/lib/api/client.ts`. These roles agree with the official SSR guidance. [Supabase SSR clients](https://supabase.com/docs/guides/auth/server-side/creating-a-client?framework=nextjs&router=app)

| ID | Manual action | Required observation | Result |
| --- | --- | --- | --- |
| SESSION-01 | Wait for the approved project's normal token-refresh boundary, then navigate/reload and read progress | Refresh succeeds and preserves identity/history; no unauthorized response loop | Not run |
| SESSION-02 | Inspect cookie **attributes only** privately on HTTPS | SDK cookies: Secure, SameSite=Lax, Path=/, host isolation; readable by the browser SDK by design. Do not report their values or incorrectly expect them all to be HttpOnly | Not run |
| SESSION-03 | Inspect authenticated refresh/page/API response cache headers | Private/no-store behavior; no authenticated page or Set-Cookie response shared across contexts/CDN | Not run |
| SESSION-04 | Sign out from account details, then revisit protected pages and perform a protected action | Sign-in boundary; account convenience links cleared; no newly obtained authenticated API access | Not run |
| SESSION-05 | With two prearranged test sessions, verify current logout scope | Current code calls SDK `signOut()` without a scope, whose documented default is global; observe refresh revocation on the other session and record actual timing | Not run |

JWT access tokens already issued can remain valid until their expiration after sign-out. Trace's public-key verification is not a remote per-request revocation lookup. Do not claim immediate JWT revocation from cookie clearing alone or expose a retained token to demonstrate it. Supabase documents access/refresh token behavior and logout scope. [Supabase sessions](https://supabase.com/docs/guides/auth/sessions), [Supabase sign-out](https://supabase.com/docs/guides/auth/signout)

## Ownership and browser isolation

| ID | Manual action | Required observation | Result |
| --- | --- | --- | --- |
| ISOLATION-01 | Use separate browser contexts for authorized identities A and B; save a learning session as A | B never sees A's history or private lesson-session data | Not run |
| ISOLATION-02 | As B, request A's progress/tutor/feedback using the known test-session reference through the normal client | Ownership denial; no evidence, raw submissions, private configuration or answers from A | Not run |
| ISOLATION-03 | Clear/sign out A's browser session and revisit browser history/back navigation | No usable authenticated account state or cached private page crosses the sign-out boundary | Not run |
| ISOLATION-04 | If a genuine pre-existing guest history is available, use explicit account history claiming | Preview and explicit confirmation preserve sessions; another account cannot claim the same history. Do not invent a guest-learning UI or merge histories by email | Not run |
| ISOLATION-05 | Use a deliberately unallowed browser origin and a missing/invalid bearer on protected actions in a controlled test | Existing CORS/origin/authentication checks reject access; no fallback to a less privileged identity | Not run |

The existing deterministic browser suite uses the official SDK against loopback Auth and a disposable learning database. It covers registration/confirmation, refresh, logout, recovery, ownership/history claiming and hostile callback handling on desktop/mobile. Its result must be reported separately from this real-provider checklist. Sources: `tests/e2e/accounts.spec.ts`, `tests/e2e/api-contract.spec.ts`, `backend/scripts/auth_fixture.py`, `playwright.config.ts`.

Release sign-off requires each applicable manual row to have a sanitized observed result, with any blocker left explicit. This document makes no fresh signup, email delivery, Google OAuth, refresh, deployment or production-readiness claim.
