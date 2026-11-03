# PostgreSQL compatibility and shared AI controls

Status: implemented, with verification evidence recorded in the platform report.
This decision does not authorize a public deployment, paid hosting, production
data transfer or a provider budget change.

## Persistence and migration decision

Keep synchronous SQLAlchemy and the existing repository/service boundaries.
SQLite remains the local/disposable default. Production requires the explicit
`postgresql+psycopg` driver, a private application schema and `sslmode=verify-full`.
The driver is locked; existing dependency versions were retained.

The historical SQLite revisions 0001–0007 are unchanged. They contain SQLite
trigger syntax and table rebuilding and cannot be honestly replayed on
PostgreSQL. Two explicit Alembic configurations load separate baseline paths:

| Configuration | Baseline location | Shared additions |
| --- | --- | --- |
| `backend/alembic.ini` | `alembic/versions`, original SQLite history | `alembic/shared_versions` |
| `backend/alembic-postgresql.ini` | `alembic/postgresql_versions/pg_0007_baseline.py` | `alembic/shared_versions` |

Each configuration loads exactly one revision named
`0007_tutor_reservations`. On SQLite it has its original predecessor. On
PostgreSQL it is the independently rooted, frozen equivalent schema: 25 legacy
tables, the write-gate seed and 54 equivalent row-level guards. It checks that
the intended application schema is empty and refuses to overwrite existing
tables. There is no runtime `create_all` bootstrap or Alembic stamp. PostgreSQL
cannot downgrade below that baseline. Subsequent shared revisions have the same
identities and expected head in both lineages.

PostgreSQL guards use null-safe comparisons, native Boolean predicates and
SQLSTATE 23514, preserving the repository's existing integrity-conflict handling.
Functions pin their application-schema search path. The pending-hint unique
index remains partial on both dialects; a PostgreSQL-only unrestricted unique
index would wrongly forbid later finalized hints. Portable ORM Boolean checks
preserve the SQLite meaning.

This creates a supported schema for a new PostgreSQL application database. It
does not migrate a developer's existing SQLite learner history into PostgreSQL.
Any such transfer needs a separately reviewed data-copy and reconciliation plan
that preserves identities, relationships, hashes, schedules and all records.

## Transaction and connection semantics

Keep the existing short write-gate transactions initially. On PostgreSQL the
singleton UPDATE acquires a row lock and serializes repository writes across
processes. This is deliberately conservative and can limit throughput. Provider
I/O never runs while holding that transaction.

Writes use READ COMMITTED. Multi-query authorization/evidence reads explicitly
use short read-only REPEATABLE READ transactions on PostgreSQL; SQLite retains
its existing consistent snapshot. Provider work occurs after the read context
closes, and result release uses a fresh context. PostgreSQL's default READ
COMMITTED alone would permit different snapshots between successive SELECTs.
See [PostgreSQL isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
and [row locking](https://www.postgresql.org/docs/current/explicit-locking.html).

The engine has explicit pool size, overflow, acquisition timeout, recycle and
pre-ping controls. Connection, statement and lock timeouts are bounded. Each
worker owns its engine/lifespan. Budget total connections across replicas,
migration jobs and operator access; a per-worker pool is not a project-wide
connection cap. Psycopg prepared statements are disabled for compatibility with
transaction poolers. The selected managed provider's pooling behavior still
needs validation. See [SQLAlchemy PostgreSQL](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html)
and [pool ownership](https://docs.sqlalchemy.org/en/20/core/pooling.html).

## Durable provider accounting

`AIUsageLedger` is an internal provider-neutral port. `SqlAIControls` implements
it with append-only policy, attempt and usage records. Generation and embedding
clients share an explicitly configured allowance scope.

The scope has an immutable policy. Restarting a worker does not reset it, and
changing the policy under the same scope fails closed. A different scope is an
explicit operator allowance decision, not an automatically generated startup ID
or a daily reset. The default configured allowance is 20 reservations and the
paid budget remains zero.

Before an actual provider attempt, trusted code generates a fresh UUID and
reserves under a short database transaction. It stores only capability, pinned
model, trusted subject hash, bounded input-byte estimate, batch item count and
UTC database timestamps. A batch is one RPC reservation with its separate item
count. An estimate is never presented as measured tokens. No prompt, question,
code submission, model output, authentication token or provider key is stored.

Duplicate reservations cannot authorize another provider call. Depletion,
saturation, policy mismatch and unavailable storage are distinct safe internal
outcomes. If reservation fails, no provider call starts. Known reported cost
above the zero allowance is retained as a violation and blocks subsequent
reservations; retaining that observation does not approve paid usage.

After actual transport cancellation/cleanup, finalization records nullable
measured tokens, safe outcome/error, accounted cost and bounded monotonic
provider duration. Duration excludes database reservation/finalization. Unknown
usage remains unknown. Finalization is idempotent; conflicting repeats fail.
If finalization fails, valid AI text is withheld, the reservation remains
consumed and no provider retry begins. Shared-client in-flight ownership lasts
through finalization. The existing local caps remain additional defenses.

## Shared HTTP/worker admission

`SharedAdmission` uses the same short transactional serialization to enforce
global and subject rate windows and active leases across application instances.
Scopes distinguish ingress/route/worker policies. Subjects are trusted hashes,
not request IDs, IP headers or raw account information.

UTC minute windows use database time. Releasing a lease records that actual work
ended and does not remove its rate-window consumption. HTTP cancellation alone
is not proof that an abandoned worker finished. Local cheap ingress and worker
bounds remain useful alongside the shared admission authority.

There is no automatic crash-lease expiry: it could permit replacement work while
the original request still runs. Crashed/unknown reservations remain charged
and active until an operator verifies the work stopped. The explicit recovery
CLI requires a verified Trace administrator and `--confirm-stopped`, records an
immutable reconciliation event and releases the lease without refunding the
cumulative allowance. It does not reset a budget or invent the lost outcome.

The global write gate and growing append-only admission history suit a bounded
pilot. Higher throughput and retention/partitioning require measured follow-up;
no distributed invoice guarantee or unlimited-scale claim follows from this
implementation. Actual provider billing remains external to app accounting.

## Deployment boundary

Build a portable nonroot OCI image and use an approved HTTPS edge plus private
managed PostgreSQL. Existing Supabase authentication does not by itself select
or authorize its database for application storage. The operator must confirm
project ownership, schema/role isolation, region, connection limits, retention,
backups, costs and the frontend origin before hosting.

Migrations run as a separate controlled job with a migration role. The runtime
role must not have DDL or TRUNCATE permission. Row DELETE triggers do not protect
against TRUNCATE. Application-schema access must not become an unintended public
Data API. No public document-management, metrics or quota-reset endpoint is added
by this decision.
