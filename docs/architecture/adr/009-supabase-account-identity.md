# ADR 009: Supabase Auth, permanent Trace accounts and exclusive learner ownership

Status: accepted, Module 4. Builds on ADRs 002, 006, 007 and 008.

## Decision and boundary

Supabase Auth is the only credential authority for Google OAuth, confirmed
email/password authentication, recovery, refresh and logout. The official
JavaScript and SSR SDKs use PKCE and shared session cookies. Next 16.4.3 uses
`src/proxy.ts` to refresh cookies and verified `getClaims()` in protected server
components. Trace's central browser API client obtains the access token from the
SDK solely for transport. FastAPI independently verifies it.

Trace continues to own application data through SQLAlchemy/SQLite. There is no
Supabase Data API, application Postgres database, provider admin SDK, service-role
key, password table, local password verifier, custom OAuth protocol or separate
refresh-token system. New dependencies are limited to Supabase JS/SSR and
PyJWT with cryptography. Existing framework versions remain pinned.

## Identity and authorization

`users.id` is the permanent Trace UUID. A unique immutable `(issuer, subject)`
mapping in `auth_subjects` resolves it, independently of displayed email. Multiple
provider-managed authentication methods may share the same verified subject.
Trace never merges users by email or reads roles from mutable user metadata.

New accounts receive only `learner`. `user_roles` supports multiple learner,
creator and admin grants. Account services enforce active status and required
roles. An operator with local database access can explicitly grant creator/admin
using `scripts.grant_role`, recording OS operator name, target, reason and time in
append-only `role_grant_events`. There is no public grant endpoint or creator UI.
An OS operator name is an audit attribution, not independent proof of human identity.

## Ownership without rewriting history

One `account_learners` row maps a unique internal user to a unique existing learner.
This is smaller and safer than rebuilding learners or rewriting immutable session
owners. Existing digest-only credentials stay as revoked historical records;
account learners require no guest credential. Database guards reject attaching an
account while any guest credential remains unrevoked, attaching a mismatched claim
receipt, adding/reactivating/moving account credentials, or changing/deleting an
ownership mapping. Foreign keys and uniqueness back the service checks.

Bootstrap of users, subjects and the default role happens under the existing
SQLite write gate. Account inspection deliberately does **not** create a learner,
so viewing `/account` cannot obstruct a later guest claim. First authenticated
learning access creates the account learner idempotently. An account that already
has any other learner identity receives a conflict when trying to claim; even an
empty identity is not replaced automatically. A user can choose to start separate
account learning, but then cannot combine that history with a guest in this module.

Claim requires independently verified Bearer identity and a valid unexpired guest
cookie, an empty JSON object, exact Origin, Trace client header and UUID retry key.
The server derives both identities. Under one write transaction it rechecks the
credential, revokes **all** its learner's guest credentials, and inserts ownership
with a claim receipt. The response clears the HttpOnly guest cookie. No lesson,
session, prediction, attempt, check, task/note or retrieval row is changed.

Same-user exact-key replay returns the stored receipt after the cookie is cleared;
it does not perform a new transfer or revive a revoked credential. A different key
needs a valid guest credential. A different user cannot replay the receipt or use
the revoked cookie. Competing claims serialize before reads; failure rolls back
both revocation and attachment. In-flight requests already authorized before a
claim can finish against the same learner, but new guest authentication fails.
No lost, revoked or expired guest credential can establish a new claim.

## JWT verification and operational limits

FastAPI accepts only ES256/P-256 and RS256/RSA >=2048 public keys, from the explicitly
configured same-project issuer's JWKS endpoint. It checks signature, algorithm,
kid, exact issuer, audience, required subject UUID, integer exp/iat and optional
nbf, authenticated role and non-anonymous provider status. Untrusted `jku`, metadata
or displayed email never select an authority. Invalid supplied Authorization never
falls through to guest access, including on catalog requests.

The injectable source and clock permit deterministic tests. HTTP fetches have a
3-second timeout, no redirects, 64 KiB/16-key bounds, a 300-second default cache
(maximum 600), and a 5-second minimum refresh interval for unknown-kid/outage
storms. Unknown keys refresh after that interval. An expired cache or failed key
refresh fails closed; a failed refresh invalidates the cache and does not use stale
keys. Rotation may need a brief retry inside the cooldown, and must respect the
provider's documented edge-cache/standby-key propagation period. No JWT is logged.

The browser SDK requires JS-readable provider cookies; claiming they are HttpOnly
would be false. They are host-only, SameSite=Lax, path `/`, Secure on an HTTPS app
origin. The separate anonymous credential remains HttpOnly. Callback redirects are
pinned to `NEXT_PUBLIC_SITE_URL`, not incoming/forwarded Host or `next` parameters;
auth responses are private/no-store and use no-referrer. Proxy copies SDK cookies
into both request and response, including SDK cache headers. Protected server
rendering sits under Suspense for Next Cache Components.

Provider logout revokes refresh sessions and clears SDK cookies. An already issued
access token can still pass independent signature verification until exp. Account
disable status is checked in Trace on every authenticated request, but this is not
a full token denylist. Keep access-token lifetime short and never claim immediate
global JWT revocation. No production deployment/hardening is part of Module 4.

Provider-owned authentication operations use Supabase rate limits. Trace-owned
account inspection and claim operations have transactional per-user/action
30-per-minute fixed-window limits; failed claims consume quota. This is not an
edge/global DDoS limiter. SQLite remains the current single application database.

## Migration and alternatives

`0005_account_identity` adds six tables and guards without rebuilding existing
tables or touching learning rows. Empty account schemas can downgrade. Any user
data causes downgrade to refuse before deleting tables, preserving account and
learning ownership. Startup still never creates/migrates schemas.

Rejected: email-based local identity merging, copying history to a new learner,
automatic guest claims, custom refresh/password storage, and accepting HS256 just
to accommodate an unconfigured provider. Supabase handles same-verified-email
identity linking; manual different-email linking and multi-history merging remain
out of scope. The choice adds an external authentication dependency and dashboard
setup; all existing guest learning remains available without provider config.

## Evidence

See `authentication.md`, `account-setup.md`, `testing-strategy.md` and the Module 4
report. Generated-key tests prove independent crypto verification and transactions;
browser tests use the official SDK against a separate ephemeral loopback fixture.
Neither proves real Google consent, Supabase project configuration or SMTP delivery.
