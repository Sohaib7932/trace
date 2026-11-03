# Authentication security validation

This is source and deterministic-test evidence, not a claim that a production
Supabase deployment or real OAuth/email delivery was exercised. Real-account
acceptance and hosted configuration remain separately reported.

## Existing protections retained

`backend/app/auth/jwt.py` verifies asymmetric ES256/P-256 or RS256/RSA-2048+
signatures using the configured project's public JWKS. It validates configured
issuer/audience, required claims, integer timestamps, expiry/not-before/issued-at,
canonical UUID subject, authenticated role and nonanonymous identity. HS256,
unsigned tokens, algorithm mismatch, critical/invalid headers and oversized
tokens remain rejected. Token-selected URLs and embedded keys never replace the
configured JWKS source. App roles and ownership come from Trace's database.

The existing tests already cover missing/invalid/expired tokens, wrong issuer,
wrong audience, bad signatures, asymmetric algorithms, JWKS rotation and cooldown,
expired-cache outage rejection, invalid/private/duplicate keys, account isolation,
guest-history claim and replay, roles, CORS/write origins, secure/HttpOnly/SameSite
cookie behavior, token privacy and database/provider failures. These tests were
inspected before adding regressions; passing counts are recorded separately
from this coverage inventory.

## Narrow public-key boundary fix

The previous private-key filter rejected `d`, `p`, `q` and `k` but accepted RSA
private CRT members `dp`, `dq`, `qi` and `oth` attached to an otherwise valid
public JWK. Four new synthetic regressions reproduced the acceptance. The filter
now rejects every one of those private members. No signature, issuer, ownership
or role check was weakened. These members are classified as private RSA
parameters by [RFC 7518 section 6.3.2](https://www.rfc-editor.org/rfc/rfc7518.html#section-6.3.2).

Additional regressions cover unsupported RSA strength/EC curve, ignored token
key URLs/embedded keys, concurrent refresh coalescing, usable unexpired cache
during an outage, closed-verifier rejection and sanitized cleanup failures.

## Bounded JWKS refresh

The prior HTTP source used a three-second timeout per I/O operation, which did
not bound a slowly progressing response's total lifetime. The synchronous
`JwksSource.fetch` port remains unchanged. `app/auth/jwks_http.py` now lazily owns
one asynchronous HTTPX2 client and one event-loop worker, with a three-second
absolute asynchronous I/O deadline including queueing and body reads. The
client is reused across cache refreshes. OpenAPI/configuration inspection does
not create a loop, thread, client or network request.

Requests use the fixed configured URL, GET, no redirects, no environment proxies,
no authorization headers and identity content encoding. Nonidentity responses
are rejected before decompression can bypass the 65536-byte body limit. Errors
remain constant and sanitized. No JWK, token or raw network diagnostic is logged.

The cache lock remains held until actual HTTP cancellation/stream cleanup
finishes. Timed-out refreshes do not release expired cached keys. The resolver
executor admits one job and retains its permit until the real job ends; another
refresh cannot create an unbounded resolver thread/queue storm. Close prevents
new refreshes, discards late results, drains actual work and clears cached keys.
Application-owned default verifier lifecycle is distinct from caller-injected
verifiers.

This is cooperative asynchronous I/O cancellation. CPU/event-loop stalls,
cancellation-resistant custom transports and underlying OS resolver calls
cannot be forcibly killed in Python. The resolver's concurrency is bounded.
The source and verifier expose `wait_for_idle(timeout)`; actual resolver work
retains ownership through disposal. Application shutdown shares a grace period,
then retains a deferred cleanup owner if necessary instead of detaching old
resolver threads or destroying resources beneath them. No hard process-shutdown
guarantee is implied. No alternate authentication SDK,
signing secret, permissive fallback or token-derived endpoint was introduced.

## Acceptance boundaries

The PostgreSQL suite also executes the existing signed-in Notes history,
cross-account rejection and concurrent guest-claim contracts using synthetic
signed identities and disposable schemas. The infrastructure suite validates
real PostgreSQL TLS certificate/hostname behavior and the nonroot production
container's HTTP/trusted-proxy boundary using synthetic HTTPS auth settings
with AI disabled. These are not real Supabase login or public HTTPS acceptance.

Email confirmation, recovery mail, Google OAuth callbacks, refresh/sign-out and
browser cookie behavior against the intended hosted Supabase project require
real project configuration, approved redirect URLs and a test account. A frontend
publishable API key is neither a JWT signing secret nor a Gemini credential.
Legacy HS256-only projects require an explicit project signing-key migration;
the backend does not guess or accept a private shared signing secret.

No production authentication configuration, real secret or active learner
database was changed by this security validation.

## Executed focused validation

- JWT verifier, new public-key/concurrency regressions and absolute-refresh
  transport tests: **88 passed in 3.12s**. This includes eleven transport tests,
  with slow progressing bodies, real asynchronous stream cancellation and
  delayed resolver cleanup represented by deterministic fake I/O.
- Full existing account integration module plus PostgreSQL/production settings
  tests: **41 passed in 12.05s**, including the nested-client ownership regression
  repaired in application-owned verifier lifecycle.
- Authentication/launcher scoped Ruff: passed; formatting: eight files already
  formatted; scoped mypy: three source files passed.
- Rebuilt production artifact
  `sha256:bc82a15a186b9a426cf198760311c10a0f413b2b2a10ab3a2a8bf422e4b6ff31`:
  **4 infrastructure tests passed in 21.50s** against actual PostgreSQL 17.11.
  Actual disposable PostgreSQL
  verified-TLS acceptance, wrong-CA/hostname rejection, additive migration,
  UID10001 startup, durable shared-admission configuration and trusted-peer
  HTTPS behavior were exercised. AI was disabled and authentication URLs were
  synthetic; no public deployment or live login was claimed.
- Operator reconciliation cleanup: **4 tests passed in 0.44s**, covering success,
  verification failure, reconciliation failure and verifier-cleanup failure.
  The owned verifier closes before database disposal without exposing the token
  or exception diagnostics. Scoped Ruff/format and mypy passed.
- Actual deferred authentication shutdown acceptance: two additional ASGI cases
  cover a canceled request during real asynchronous stream cleanup and an HTTP
  503 while a timed-out await leaves its actual resolver job running. Both
  outlive a deterministically zero shutdown grace. Events prove that the owned
  database, verifier, HTTP loop and mock AI resources remain retained until real
  work ends, then close completely. Durable ingress draining is included.
  These cases plus existing JWKS/AI shutdown tests passed **19 tests in 3.05s**;
  scoped Ruff and formatting passed. Only test code changed for this acceptance.

Full backend, frontend, live-account and release-wide results are recorded by
the coordinating validation report separately.
