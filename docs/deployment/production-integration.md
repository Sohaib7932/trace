# Production integration fixes and release gates

This change is a review candidate, not a production rollout. It is based on
`d9606f40aa7c44c1c337e33d253babf4c948a96b` and targets
`codex/backend-error-audit` so the new integration changes can be reviewed apart
from audit PR #43. PR #42 has since merged into main; its presence in a live
image does not mean its operator-gated HTTPS profile has been enabled safely.
PR #43 was merged into `codex/render-native-https-repair`, not main. The verified
main revision `2b211418816ea55aa84dca02ebea306f0a461576` still lacks the audit
changes and `0016`. They need a separately reviewed integration into main;
merging a PR into an already-merged feature branch does not update main.
No migration, production setting, corpus publication or provider request is
performed by committing or pushing this branch.

## Current evidence

| Item | Implemented in this change | Production evidence and remaining gate |
| --- | --- | --- |
| HTTPS/CORS | Repeatable, bounded, read-only transport check; preserve the existing HTTPS enforcement and proxy allowlist | A real 68-request probe found two `https_required` failures among 60 preflights. Production transport acceptance **fails**. |
| Nine-article support corpus | Guarded operator for importing the exact existing review and making an initial publication through protected admin APIs | No production writes executed. Publication and active knowledge availability remain unverified. |
| Gemini/custom lesson | A bounded operator that checks one owned lesson job, committed readback and durable provider accounting | No live generation executed. Actual provider and saved-lesson acceptance remain unverified. |
| Cross-domain guests | Fixed-destination same-origin Next.js relay and real-browser/disposable-backend cookie tests | Not deployed by this task. Real Vercel acceptance remains required; old Render-origin cookies are not migrated. |
| Migration `0016` | No new or modified migration in this change; use the audit PR's existing migration and rollout plan | Not applied to production by this task. Backup, maintenance and explicit rollout approval remain required. |

The probe made 30 OPTIONS requests to each of `/api/v1/account/me` and
`/api/v1/custom-lessons`: **29/30 passed on each route**, with one HTTP 400
`https_required` on each. Both failures included the correct allowed-origin and
credentials CORS headers; error-CORS decoration works, but a failed preflight
still blocks the browser. The other eight checks passed: GET liveness/readiness,
unauthenticated account/custom-lesson denial, HEAD liveness behavior, foreign
origin denial, plaintext redirect and HTTPS forwarding-spoof authentication denial.
No authenticated request, provider call, learner write or environment change was
made. Every failed result was retained; later successes did not replace it.

## Same-origin frontend transport

For a non-loopback browser in a production build, `src/lib/api/client.ts` uses
relative `/api/v1` requests. The server-only Route Handler forwards them to the
fixed `https://trace-backend-1lio.onrender.com` origin. The production frontend
remains `https://trace-ten-mu.vercel.app`; local development keeps its existing
direct backend configuration. This is a transport relay, not a new learner API
or a workload-authentication substitute.

The handler requires the server's `VERCEL_ENV` to be exactly `production` and
the fixed frontend origin. Preview, development and a missing runtime variable
fail closed. Vercel's automatic system-environment-variable exposure must be
enabled by its owner; its actual project setting was not verified here. No
additional public secret or user-configurable upstream is introduced. See
[Vercel's system environment documentation](https://vercel.com/docs/environment-variables/system-environment-variables).

The relay permits only existing OpenAPI paths, methods and query parameters.
It bounds request bodies to 64 KiB, responses to 1 MiB and the complete relay
operation to 35 seconds, with a 40-second function limit. It never follows
redirects or retries. A dispatched write whose result is lost returns an
explicit unknown-outcome error; clients must not invent a fresh idempotency key
to hide uncertainty. Backend status codes are retained except for unusable
transport responses, including a safe unavailable response for `https_required`.

The user's Supabase Bearer token is forwarded without replacement. Only the
`trace_learner` browser cookie is forwarded. Creation/renewal accepts only the
corresponding bounded, host-only HttpOnly/Secure/SameSite=Lax `/api/v1` Set-Cookie;
revocation accepts the backend's canonical same-path Max-Age=0 deletion. Cookie
creation, renewal, guest claiming and revocation use the backend's existing
logic. Other frontend cookies, provider keys, incoming forwarding headers and
workload claims are not forwarded. Writes still require the fixed allowed
Origin and `X-Trace-Client: learning-web`; backend authentication, ownership and
CSRF checks remain authoritative. Responses are not cached.

This does **not** fix Render ingress trust. Render still must satisfy the
separately reviewed [HTTPS profile](render-native-https.md). No address is added
to `TRACE_TRUSTED_PROXY_IPS`, and the relay invents no client-IP attestation.
Render sees Vercel's egress address for IP rate limits, so guests can share a
stricter IP bucket. Account-level limits remain unchanged. Existing HttpOnly
Render-origin guest cookies cannot be copied by frontend JavaScript or linked by
an untrusted learner ID; historical records are preserved, and a fresh first-party
guest can be created after rollout. Signed-in history claiming requires a valid
cookie in that first-party session.

## Offline operator plans

From the backend context, the following commands are offline by default:

```powershell
python -m scripts.check_deployed_transport
python -m scripts.publish_reviewed_corpus --plan
python -m scripts.accept_deployed_ai
```

They make no production request or database connection. Tests inject disposable
HTTP/database implementations; importing these modules does not activate AI.
The transport command alone accepts `--probe` for 68 read-only public requests.
It sends no token or cookie, follows no redirects, performs no retries and emits
only allowlisted status/category/CORS metadata. It retains all failures.

The two mutation operators require a genuine short-lived owner JWT in the
**process-only** `TRACE_OPERATOR_ACCESS_TOKEN` variable. Configure it privately;
never place it in a command argument, shared terminal history, log, repository
or frontend variable. They verify the actual protected account endpoint rather
than minting a JWT or assigning roles. Their shared HTTPS client has fixed
destinations/paths, normal certificate validation, no proxy-environment trust,
no redirects/retries, bounded JSON and safe error categories. The elapsed/IO
budgets are cooperative network bounds, not an OS-level hard DNS deadline.

## Future approved corpus publication

The pinned package is the existing **nine-article, 19-passage** corpus, SHA-256
`1fa44fda7549fcac866926c07c56c9778deaa8e29955309b1f8bab80c24f5063`.
The operator verifies original reviewer attribution, review timestamp, validity,
document/package digests, history and sealed publication manifest. It does not
rewrite the corpus or fabricate/extend a review. An expired or changed package
requires a genuine new review.

The following are **future write commands, not executed by this task**. First
obtain rollout authorization, verify transport/authentication and the owner's
existing admin role, then retain one operation UUID privately:

```powershell
python -m scripts.publish_reviewed_corpus --import-reviewed --operation-id <retained-UUID> --confirm-production-write
python -m scripts.publish_reviewed_corpus --publish-initial --operation-id <same-UUID> --confirm-production-write
```

Import adopts the genuine historical review through the protected API. Publish
replays that same idempotent import key to obtain verified histories, then uses
compare-and-swap sequence `-1` for an **initial** publication. It will not replace
an existing publication or guess a sequence. A lost response stops the command;
an operator may deliberately resume with the same key after checking the result.

These modes use three knowledge-admin requests in total, below the existing
five-per-minute admin limit; they do not fire nine revision GETs immediately.
A 429 stops the operation, without raising limits or an automatic retry. A
publication receipt is historical evidence, so the report explicitly leaves
`active_manifest_status` as `not_checked`. Afterwards use the existing read-only
`python -m scripts.platform_status` privately to confirm the current active
source/passage counts and knowledge availability. Then perform one separately
approved authenticated `/api/v1/support/ask` request and verify approved citations
and its release receipt. This change does not itself prove live Trace Help or
activate an unvalidated semantic retrieval strategy.

The first import may need more than 10 seconds to finish its governance
checkpoints. The operator allows up to 40 seconds for that response within its
overall deadline. After an uncertain response, check the archive before
resuming with the same operation UUID. A fully committed import replays its
verified histories from a read-only snapshot. An incomplete import resumes
through the original checkpoints.

## Future approved Gemini/custom-lesson acceptance

The acceptance tool requires explicit production PostgreSQL configuration,
`TRACE_ENVIRONMENT=production`, the existing durable accounting policy, database
head `0016` and an active owning learner. SQLite is rejected before engine
creation in the production factory. Evidence reads use short read-only consistent
transactions, released before HTTP/provider work. No migrations are run by it.

Use the approved server configuration privately in the operator process:
`TRACE_DATABASE_URL`, `TRACE_DATABASE_SCHEMA`, the complete `TRACE_SUPABASE_URL` /
`TRACE_SUPABASE_ISSUER` / `TRACE_SUPABASE_JWKS_URL` profile, HTTPS
`TRACE_CORS_ORIGINS`, and `TRACE_ACCOUNTING_MODE=durable`. Match
`TRACE_ACCOUNTING_SCOPE`, `TRACE_ACCOUNTING_MAX_ATTEMPTS`,
`TRACE_ACCOUNTING_MAX_IN_FLIGHT`, `TRACE_ACCOUNTING_MAX_SUBJECT_IN_FLIGHT` and
`TRACE_ACCOUNTING_REQUESTS_PER_MINUTE` to the existing server policy. Do not
create a fresh scope or reset allowances to make acceptance pass. Normal
production TLS, private-schema and secure-cookie validation still applies.

An owner must privately confirm the unbilled free-tier project, deployed approved
model, zero paid budget, zero transport retries and no paid fallback. The existing
custom-lesson generator may make a second schema-repair call; therefore a strict
single-provider-call acceptance also needs the **separately approved running-server**
`TRACE_CUSTOM_LESSONS_MAX_LIVE_CALLS_PER_PROCESS=1` setting. The CLI confirmation
is an operator attestation, not remote observation or permission to change it.

Only after separate live-test authorization:

```powershell
python -m scripts.accept_deployed_ai --apply --confirm-free-tier-project --confirm-server-call-cap-one --idempotency-key <retained-UUID>
```

This submits exactly one fixed synthetic Python lesson request. It never retries
the POST or refreshes a token. It polls at most 24 times, then reads the saved
owned lesson and checks committed request/lesson/challenge relationships and
durable usage. Unavailable, pending, ambiguous delivery, malformed readback or
missing proof stops with an unverified outcome. An existing operation key cannot
silently establish a new baseline.

Provider proof requires exactly one new finalized successful durable attempt,
the approved requested model, known token usage and zero recorded cost in the
unique account/custom-job window, with no competing work. There is no direct
request-to-provider foreign key, so this is bounded window attribution, not a
cryptographic linkage. The ledger does not retain the provider's returned model
identifier; it is reported as `not_retained`. `billing_verified` remains false:
local accounting and an operator's free-tier confirmation cannot prove Google's
billing state. A ready HTTP response alone is never accepted as real-provider
proof. This checks generation, persistence and provider metadata, not semantic
answer-key correctness; existing deterministic learner verification/completion
code is unchanged.

## Ordered release, not executed

1. Require CI and review on this stacked PR and a separate main integration of
   the audited changes. PR #43's successful checks and feature-branch merge do
   not put its code on main. Preserve teammate work; retarget only after verifying
   the effective diff when prerequisites reach main.
2. Coordinate the exact image, verified private database backup/restoration,
   maintenance window, migration `0016` and application readiness using the
   [audit rollout plan](../reports/backend-audit-review-and-release.md). Do not
   apply `0016` or merge while assuming main auto-deployment will stay idle.
3. Obtain an operator decision about the HTTPS profile's private-network trust
   assumptions. Keep the seven-entry proxy allowlist and TCP health check.
   Deploy only an approved configuration and require all 60 preflights to pass;
   investigate every `https_required` result.
4. Deploy the reviewed frontend relay to the existing Vercel project, verify its
   real runtime gate and test signed-in account/ownership plus a fresh guest's
   create/reload/renew/claim/revoke journey and deterministic Notes verification.
   Local fixtures are not Vercel identity/deployment evidence.
5. Run the guarded corpus publication, confirm active nine/19 counts, then verify
   one real authenticated Help answer and citation/release integrity.
6. Run one separately approved Gemini lesson acceptance and owned saved readback.
   Stop on any failure; do not enable paid fallback or retry until something passes.

No new backend HTTP operation, database model, migration, provider dependency or
production credential is introduced. The backend contract remains **54 paths /
60 operations**; the same-origin handler transports that existing contract.

The Quality frontend job now also runs `node --test
tests/integration/api-relay-browser.mjs` after installing Chromium. This test
intercepts all browser traffic and uses the real relay core with a disposable
FastAPI database; it makes no production or provider request. The existing
Playwright suites and all other quality gates remain enabled.

## Local validation on the review candidate

| Gate | Actual result |
| --- | --- |
| Full backend regression, network sockets disabled | 5,208 passed in 2,324.69 seconds; process exit 0 |
| Coverage | 94.00%, unchanged from the audited baseline; existing 85% threshold retained |
| New focused backend tests | 112 passed: 52 corpus/HTTP, 44 lesson/provider-evidence, 16 transport checks |
| Full frontend suite after the route correction | 405 passed across 29 files |
| Focused relay/client tests | 116 passed across six files |
| Offline Chromium + real disposable FastAPI | One cookie-lifecycle test passed; no production/provider traffic |
| Default production build | Turbopack passed; catchall dynamic, not prerendered or Edge; function duration 40 seconds |
| Backend static checks | Ruff and formatting passed across 461 Python files; mypy passed across 274 source files |
| Frontend static checks | Full ESLint and typecheck passed |
| Contract | Actual OpenAPI exactly matches 54 paths/60 operations; generated types unchanged after checkout newline normalization |
| Repository/logging guards | 178 passed; reviewed canonical checkpoint contains genuine recovered records, not a claim of automatic capture |

The full backend run emitted one SQLite `ResourceWarning` during an existing
startup-failure test. The unchanged nine-test startup-cleanup module then passed
with `ResourceWarning` treated as an error; the warning did not reproduce there.
Its allocation source was not established, so it is recorded rather than hidden
or attributed to the test where garbage collection happened. No warning filter,
assertion or threshold was weakened. Existing full Playwright journeys and
PostgreSQL compatibility are fresh remote-CI gates; local cookie proof and a
successful build do not replace them or production acceptance.
