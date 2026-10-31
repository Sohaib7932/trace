# ADR-007 — Pseudonymous cookie ownership and serialized SQLite writes

Status: accepted for Module 2.

## Context
Learner/session IDs identify resources, not their owners. The local browser and API
run on separate ports. Immutable predictions, numbered attempts and bounded hints
must also survive concurrent requests through independent SQLAlchemy sessions.

## Decision
Issue 32 random bytes using `secrets.token_urlsafe`; store only the SHA-256 digest
in a separate credential row, with UTC expiry/revocation. Return the raw value only
as a host-only HttpOnly, SameSite=Lax cookie scoped to `/api/v1`. Secure cookies are
the default; the explicit local-HTTP setting permits non-Secure cookies only with
loopback frontend origins. Credentials never enter JSON, application logs or JS storage.
Authenticated dependencies resolve the owner; scoped services return the same 404
for another owner's session and a missing session. Reuse valid identities; revoke
credentials explicitly. Lost/expired credentials do not recover old histories.

Every state-changing learner endpoint requires both an exact allowed Origin and
`X-Trace-Client: learning-web`. Credential-aware CORS allows only configured origins.
Use the same hostname in browser/API URLs (localhost with localhost, or 127.0.0.1
with 127.0.0.1) so SameSite works without weakening browser security.

SQLite writes acquire a singleton write-gate row via UPDATE as the first statement
of an explicit transaction. This reserves SQLite's writer before reading counters
or idempotency keys, avoiding read-then-upgrade races under Python 3.13's existing
transaction configuration. Unique constraints remain the final consistency guard.
No in-memory/process lock is relied upon. Busy infrastructure returns a retryable
dependency error rather than classifying learner work as wrong.

Verification uses a private FastAPI application with a mounted `/notes` route via
an in-process ASGI transport. It is not a public execution endpoint. Runtime notes
use a dedicated table in the same local database, scoped by unique verification-run
FK, rather than a second database: this gives relational ownership and cleanup
without cross-database commits. Each HTTP write and independent readback uses a new
session. No submitted code, URL, path or SQL is executed.

## Alternatives
Bearer tokens in localStorage expose credentials to JS; UUID-as-auth has no separate
secret. Full accounts/OAuth add recovery complexity outside scope. SameSite=None
would require cross-site HTTPS and is unnecessary locally. Process-only locks fail
across workers. BEGIN IMMEDIATE requires changing Module 1's sqlite3 transaction
handling; the explicit database write gate preserves it. A second exercise DB would
complicate run/row consistency for this bounded lesson without improving isolation.

## Consequences and tradeoffs
The local monolith serializes writes; this fits SQLite, not high-throughput hosting.
One database contains distinct learning-history/runtime tables, never a whole-history
JSON blob. Sensitive identifiers are excluded from raw-path logs. Append-only DB
triggers protect finalized evidence; planned retention/deletion needs a deliberate
maintenance workflow, not ordinary application UPDATE/DELETE. Production collection,
account recovery, deployment hardening and live providers remain out of scope.

## Revisit when
Cross-device recovery, actual deployment, higher write concurrency or broader code
execution is required. Revisit ownership transport/CSRF and migrate/test PostgreSQL
before changing these guarantees.

References: [Python secrets](https://docs.python.org/3.13/library/secrets.html),
[FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/),
[cookie attributes](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie).
