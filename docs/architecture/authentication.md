# Authentication and account ownership

Supabase Auth manages credentials and sessions; Trace owns users, roles and learning
records. [ADR 009](adr/009-supabase-account-identity.md) specifies the boundary and
tradeoffs. [Account setup](account-setup.md) lists the manual provider steps.

## Implemented flows

- `/sign-up`: email, password and confirmation; Google SDK OAuth button. Successful
  email registration shows a pending state, not a verified account. Resend uses
  provider rate limits. An unexpected immediate signup session is signed out and
  reported as missing required provider email-confirmation configuration.
- `/sign-in`: email/password, Google, resend confirmation, registration and recovery
  links. Credential errors are safe; unconfirmed email gets specific guidance.
- `/auth/callback`: SDK PKCE code exchange, or confirmation/recovery token-hash
  verification restricted to `signup` and `recovery`. There is no OTP-entry or
  passwordless login flow. Callback failures/cancellation go to safe guidance;
  arbitrary next/Host/error descriptions are never reflected as destinations.
- `/forgot-password`: provider reset request, with a generic result regardless of
  account existence. `/reset-password` requires verified server claims and calls
  provider password update, then sign-out. Invalid/expired links need a new link.
- `/account`: verified server gate, fresh provider identity display, internal Trace
  UUID/roles/creation, explicit guest claim and SDK logout. Claim conflict preserves
  both histories. Starting authenticated learning without claiming creates a
  separate permanent learner; histories cannot later be combined in Module 4.

Provider `getUser()` supplies displayed confirmed email/sign-in methods. Authorization
always uses independently verified claims and Trace database roles. Account pages
never display provider tokens or credential hashes. Homepage gets a small sign-in/
account link; lessons offer “Save progress”. No registration gate is added to guests.

## Request resolution

| Request | Principal |
|---|---|
| No Authorization, valid guest cookie | Anonymous learner |
| Valid Supabase Bearer | Active internal account, trusted DB roles; learner resolved when needed |
| Invalid/malformed/expired supplied Authorization | 401, no guest fallback |
| Signing key/config/database unavailable | Safe 503, no invented identity |
| Account-only endpoint without Bearer | 401 even with a guest cookie |
| Creator/admin role missing | Service role guard rejects with 403 |

Only the verified `(issuer, sub)` mapping bootstraps accounts, atomically and
idempotently. Email and `user_metadata` are not identity keys/role sources. An
account inspection does not allocate a learner; this leaves room for explicit guest
claim. Authenticated learning works with no guest cookie and across devices.

`GET /api/v1/account/me`, `GET /account/me/learner` and `POST /account/claim-anonymous`
are relative to the API v1 prefix (the first path is written in full). Claim's body
is `{}`; no learner IDs, raw credentials or hashes are accepted. A UUID
`Idempotency-Key` identifies retries. Exact same-user receipt replays work after
cookie deletion; a fresh transfer always requires a current valid guest cookie.

## Operator roles

From backend, with the intended database configured and already migrated:

```sh
uv run --locked python -m scripts.grant_role --user-id <TRACE_USER_UUID> --role creator --reason "Approved creator access"
```

`admin` is the other supported elevated role. OS operator name, explicit target,
role, reason and timestamp are persisted in append-only audit records. Re-granting
an existing role makes no duplicate grant. This CLI requires local DB access and is
not a public web operation. Creator Studio and administrator product actions are
future work; the current service guard is the reusable enforcement boundary.

## Session and security notes

Supabase browser/SSR clients share SDK cookies and refresh; Trace never copies
tokens into arbitrary localStorage. `getSession()` in the browser supplies transport
only, `getClaims()` protects Next server pages, and FastAPI verifies JWTs itself.
JS-readable SDK cookies are required by that architecture; the guest credential
alone is HttpOnly. Secure follows the configured app origin, SameSite=Lax, no Domain.
Local HTTP is allowed only for loopback; use the same browser/API hostname.

All learning/account writes keep exact Origin and `X-Trace-Client: learning-web`.
CORS explicitly includes Authorization; no wildcard is added. Provider operations
retain provider controls. Trace account inspect/claim each allow 30 requests per
user per UTC minute in the database; failed claims count. Bootstrapping uses the
existing transaction gate; role/user status comes from Trace on each request.

JWT public keys cache for 300 seconds by default, maximum 600. Unknown kid and
outages have a five-second refresh cooldown; fetches time out in three seconds and
are bounded to 64 KiB/16 keys. Expired/unavailable keys fail closed. Configure ES256
or RS256; HS256/none are refused. The configured issuer owns the only permitted
JWKS URL. Logger allowlists exclude tokens, request bodies/headers and query values.
Run servers with access logging disabled so confirmation URLs are not logged.

SDK logout clears browser cookies and revokes refresh sessions; already issued
access tokens remain cryptographically usable until expiry. This module does not
query provider session revocation on each request or maintain a JWT denylist.
XSS prevention matters because SDK cookies are readable; never render untrusted
HTML or ship service keys. HTTPS, SMTP, provider monitoring, broader abuse controls,
backup/restore and public deployment review remain operational responsibilities.

Supabase handles same-verified-email Google/email identity linking. A different
external subject creates a different Trace account even if email display matches.
Different-email manual linking, account deletion/export, multi-history merge,
phone/SMS, passwordless/OTP login and organizations are excluded.
