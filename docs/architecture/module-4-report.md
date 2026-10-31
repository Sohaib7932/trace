# Module 4 delivery: identity, authentication and account ownership

Local implementation/validation record, 2026-10-31. Remote delivery is recorded
below after the authorized feature-branch push. No production deployment is included.

## Git preflight

Module 3 [PR #2](https://github.com/Sohaib7932/trace/pull/2) was **MERGED** at
`2026-10-31T12:36:44Z`, base `main`, head
`feat/trace-module-3-transfer-retention`. The previous implementation commit was
`f24cacaaa55f7cbc2da85125bd4562cc7cfdea82`; its tree matched fetched merged main.
Local main was safely fast-forwarded to
`54a8dbffe1e3415062c374a3d4d19cd205402cb2` before creating
`feat/trace-module-4-account-auth`.

Existing genuine log changes and four untracked app-generated suggestion records
were preserved. The index was initially empty. No stash, reset, clean, force push,
history rewrite, main commit or PR creation is used for this delivery.

## Implemented architecture

- Supabase Auth is the only credential authority. Official `@supabase/supabase-js`
  **2.118.0** and `@supabase/ssr` **0.12.7** manage Google PKCE OAuth, confirmed
  email/password, resend, recovery/update, cookies, refresh and logout.
- Next **16.4.3**, React and every existing npm package version are unchanged.
  Installed proxy/cookies/route/useRouter/connection documentation was checked.
- Browser, per-request server client and Next 16 `src/proxy.ts` have separate
  boundaries. Proxy updates request/response cookies/cache headers; server pages
  use verified claims under Suspense and wait for a request before SDK clock reads.
- Central API transport retrieves SDK access tokens, never copies them to custom
  storage, and fails closed on refresh errors. FastAPI verifies authentication
  independently. Original exact Origin/client protections and guest credentials stay.
- `PyJWT[crypto]` **2.15.1** / cryptography **50.0.2** verify ES256/P-256 and RS256
  signatures, permitted algorithm/kid, issuer/audience, required claims/UUID subject,
  integer exp/iat and optional nbf, authenticated role and non-anonymous status.
- Configured same-project public JWKS only: no redirects, three-second timeout,
  64 KiB/16-key bounds, default 300-second cache (maximum 600), five-second refresh
  cooldown for unknown kids/outages. Rotation is tested. Expired/unavailable cache
  fails closed. No token/header/body/query value is added to request logs.
- Trace's SQLAlchemy/SQLite application DB remains the sole application store.
  There is no Supabase Data API, local password table, custom OAuth protocol,
  parallel refresh store, service-role key or new production service.

## Identity, roles and ownership

`0005_account_identity` adds six tables: `users`, `auth_subjects`, `user_roles`,
`role_grant_events`, `account_learners`, `account_action_limits`. There are 22
product/infrastructure tables plus Alembic. Permanent Trace UUIDs are distinct from
provider subject IDs. Unique immutable issuer/subject mappings never merge by
email, and user metadata never grants roles. Concurrent first requests bootstrap
one user/mapping/default learner role under the existing write gate.

Learner/creator/admin roles can coexist. Default is learner only. Service role
guards enforce permissions. Local `scripts.grant_role` requires explicit target,
elevated role and reason, attributes the OS operator and records an immutable audit.
There is no public grant endpoint or Creator Studio.

Inspection does not create a learner. First authenticated learning creates or
resolves its permanent learner without a guest cookie; this leaves an opportunity
to claim existing guest work first. Claim requires Bearer, a current valid guest
cookie, exact Origin, Trace client header, empty JSON and a UUID retry key. Both
identities are server-resolved. One transaction rechecks validity, revokes every
guest credential for the learner and attaches one account owner. The cookie clears
on success. No session/evidence/transfer/retrieval owner or history row is rewritten.

Exact same-user/key receipts replay after cookie deletion. A fresh transfer still
requires valid unrevoked/unexpired guest proof. Second-user claims fail; conflicting
account learners preserve both histories instead of merging. Database uniqueness,
FKs and triggers prevent conflicting ownership, credential reactivation and ownership
rewrites. Rollback and competing transactions are tested. Lost credentials are not
claimed as recoverable. Downgrade refuses before deletion if any user data exists.

## Pages and contracts

`/sign-in`, `/sign-up`, `/forgot-password`, `/reset-password`, `/auth/callback` and
`/account` use Trace's existing visual system. The homepage gets a small auth
control; lesson navigation offers saving progress. Guest completion remains open.
Forms include labelled fields, keyboard controls, pending/error messages, password
confirmation, email confirmation/resend and generic recovery results. Account UI
shows verified provider information, Trace UUID/roles/creation, explicit claim,
safe conflict and logout. Mobile layouts have no horizontal overflow.

Callback redirects use the configured app origin rather than incoming/forwarded
host or arbitrary next values. Only signup/recovery token-hash links are accepted;
no OTP or magic-link login is exposed. Invalid/cancelled/expired callbacks and
transport failures show safe guidance. OAuth code exchange is delegated to the SDK.

New owner-scoped operations:

| Method | Path |
|---|---|
| GET | `/api/v1/account/me` |
| GET | `/api/v1/account/me/learner` |
| POST | `/api/v1/account/claim-anonymous` |

OpenAPI now describes **21 paths / 23 operations**. Generated TypeScript contracts
were regenerated twice with identical bytes. Supplied invalid Authorization is
rejected even on public catalog/bootstrap requests; no silent guest fallback.
Account inspect and claim each enforce 30/user/minute limits; failed claims count.

## Actual local results

| Check | Result |
|---|---|
| Full backend suite | **211 passed**, **98.94%** branch-aware coverage, 87.46 seconds |
| Backend static checks | Ruff passed; 90 Python files formatted; strict mypy 72 sources passed |
| Frontend full suite | **51 passed**, six test files, 27.12 seconds |
| Callback outage follow-up | 11 boundary tests passed after safe transport-error handling |
| Frontend static checks | ESLint and Next/TypeScript checks passed |
| Production build | Controlled-auth build passed; ordinary unconfigured build also checked |
| Full browser suite | **12 passed**, desktop/mobile Chromium, 1.7 minutes |
| Visual/overflow follow-up | Two registration/learning/refresh/logout journeys passed, 57.8 seconds; account/sign-in screenshots inspected |
| Shared native logger | **24 passed**, 2.688 seconds; hooks/logger/Claude adapter unchanged |
| Migrations | Upgrade/check/downgrade/re-upgrade, zero drift, FK/integrity checks passed on a temporary DB |
| Populated migration/claim | Real original/transfer history and retrieval attempt preserved row-for-row, including rollback/concurrency coverage |
| Seeds | Both lessons seeded twice with unchanged published hashes |
| API generation | Repeated OpenAPI and TypeScript generation produced identical bytes |

The original hashes remain
`c3231631019829efe5cd1882b361cf22b8bdcdd51caca2a67a60dd73b326707e`
and `c4aefadd5f468da2505db0d14cd4d12bdc1f707282d241a10118cae39c49db0d`.

Backend tests cover generated-key signature/claim attacks, malformed/unsupported
tokens, unknown/rotated keys, outages/cache bounds and no raw JWT logging. Account
tests cover bootstrap concurrency, same-email separate subjects, metadata/role
isolation, operator grants, guest claim replay/conflict/revocation/expiry/missing
proof, rollback, competing users, authenticated learning and second-device resume.

Browser tests use the real official SDK against `scripts.auth_fixture` on loopback,
then real FastAPI/JWKS/SQLite. Generated keys and synthetic users/links/refresh
sessions exist only in memory; there is no production auth bypass. They cover
registration/confirmation, password login, refresh, authenticated learning/reload,
explicit real guest-session claim, second-user rejection, recovery and logout.
The six original homepage/guest learning/transfer/retrieval journeys remain passing.
Account traces are off to avoid retaining raw cookies/tokens.

Validation found and fixed local callback hostname normalization, SDK clock access
during Next partial prefetch, and a transient Windows lock when atomically replacing
the test clock file. Historical migration fixtures still exercise the old schema;
only their old credential lookup is frozen before upgrading to current ownership.

## Review, logs and remaining work

Environment examples contain only blank project fields and safe local settings.
Credential-pattern review found no private keys, service/GitHub/OpenAI/Google tokens
or literal access JWTs among delivery candidates. Test credentials/keys are generated
or clearly synthetic; no real provider configuration was added. Npm audit reports
18 moderate tooling advisories, zero high/critical; affected existing locked package
versions are unchanged. No unrelated audit-force or dependency upgrade was applied.

Canonical native logging contains eight genuine prompts and seven emitted final
answers at pre-commit inspection; the eighth final is correctly pending until this
turn finishes. Native attachment references are preserved without fabricated body
expansion. No commentary, reasoning, tools or injected instructions were added.
Four pre-existing app-generated suggestion logs remain untouched and untracked.
Git whitespace attributes allow native trailing blank lines and Markdown hard
breaks in log files, preserving exact captured content rather than trimming it.

Implemented and tested locally: account/UI/SDK/JWT/roles/transaction foundation.
Tested with controlled Auth fixture: email links, sessions/refresh/logout and
authenticated ownership. **Not tested with a real Supabase project, real Google
OAuth or real SMTP delivery.** The user must configure the project, required email
confirmation/templates, Google credentials/allowlists, asymmetric signing keys,
publishable frontend config, issuer/JWKS/audience and custom SMTP. See
[setup guide](account-setup.md) for exact steps and actual-provider smoke checks.

SDK session cookies are JS-readable by design; only the separate guest cookie is
HttpOnly. HTTPS Secure follows the app origin. Logout revokes provider refresh
sessions, while already issued access tokens can remain valid until exp. Local
account disable status is checked per request; no full JWT denylist is implemented.
JWKS rotation has provider propagation/cache windows and a short refresh cooldown.
The application limits are not a global DDoS control. Public deployment, account
deletion/export, multi-history/different-email merge and Creator Studio remain out
of scope. None of these tests establish empirical learning effectiveness.

## Remote delivery

Feature branch: `feat/trace-module-4-account-auth`.
Implementation commit, push verification and actual CI results are recorded after
the authorized push; no remote CI success is assumed from local tests.

[Compare against main](https://github.com/Sohaib7932/trace/compare/main...feat/trace-module-4-account-auth).
No PR is created or merged automatically.
