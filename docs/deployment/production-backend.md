# Production backend artifact and release procedure

The repository now provides a production container and PostgreSQL migration
lineage. These artifacts are not a deployed service. No hosting account,
production credentials, public endpoint, paid plan or real learner data transfer
has been created by this work.

## Operator inputs required before deployment

- Approved container host, project owner, operating owner, region and spending limit.
- Approved HTTPS backend hostname and exact HTTPS frontend origin.
- Existing Supabase project's matching public URL, issuer and JWKS configuration.
- Private PostgreSQL database/application schema, verified TLS hostname and CA,
  distinct migration/runtime roles and an approved connection budget.
- Explicit trusted HTTPS-edge peer IPs/CIDRs; no wildcard or all-address subnet.
- Backup retention, restore target, RPO/RTO, monitoring owner and rollback decision.
- Stable durable AI allowance scope and review of the existing zero-paid profile.

`deploy/production.env.example` contains names/placeholders. Supply real values
privately through the approved host secret mechanism. It is not a working
configuration. Docker `--env-file` populates process variables; do not copy this
mixed-runtime example into the strict local `backend/.env` file.

Production validates PostgreSQL with `sslmode=verify-full`, a private application
schema, secure cookies, complete HTTPS Supabase configuration, HTTPS CORS and
disabled local/debug exceptions. If a custom CA is needed, mount the public CA
file read-only and set `sslrootcert` in the private database URL. Do not disable
certificate/hostname verification. The server-only Gemini key stays in the host
secret manager; it never belongs in a Docker build argument, frontend variable,
Git file or log.

## Build and startup

From the repository root:

```sh
docker build --tag trace-backend:review .
```

The base image is digest-pinned. Runtime dependencies come from `uv.lock` with
development dependencies excluded. The runtime UID/GID is 10001. Docker context
excludes private environment files, agent logs, local databases, Git metadata,
test fixtures and frontend output. No developer environment file or database is
packaged.

The default entry point runs `python -m scripts.run_production`. It refuses an
incomplete production profile, missing durable accounting scope or absent/unsafe
`TRACE_TRUSTED_PROXY_IPS`. It uses
one Uvicorn worker, disabled access logging and only the explicitly configured
trusted proxy peers for forwarded scheme handling. Configure the approved edge
to terminate HTTPS and restrict direct application access; never expose an
unprotected host port or reuse the local Gemini launcher for public hosting.

The container healthcheck calls loopback HTTP liveness. External readiness should
call the HTTPS backend readiness path. `/api/v1/health/ready` checks database
connectivity/schema heads; it does not prove live Gemini, billing state, corpus
approval or real Supabase login. Operator diagnostics must inspect those
separately without making an LLM request on every probe.

## Migration job

Create the intended private application schema with the migration role before
the first release. The PostgreSQL baseline refuses a missing/unintended or
nonempty application schema. Use the explicit PostgreSQL configuration, never
the SQLite historical lineage:

```sh
python -m scripts.migrate_production
```

Run this once as an approved release job using its private migration-role
configuration. Workers never migrate automatically. The equivalent explicit
Alembic configuration is `backend/alembic-postgresql.ini`. Do not load both
baseline directories in one Alembic configuration or stamp a database to pretend
that SQLite migrations ran on PostgreSQL.

The runtime role needs the required SELECT/INSERT and narrowly scoped UPDATE
permissions, plus schema usage. It must lack CREATE/ALTER/DROP/TRUNCATE. Keep
administrative access and database credentials out of the frontend and ordinary
learner APIs. The application schema must remain outside any unintended public
database/Data API exposure.

Budget connections as workers × (pool size + overflow), plus migration/operator
reserve and any other project services. Defaults are pool size four and zero
overflow per worker. Validate the selected provider's direct/session/transaction
pooler behavior and use its documented TLS connection method.

## Durable limits and recovery

Every production profile, including disabled AI, requires
`TRACE_ACCOUNTING_MODE=durable` and a stable operator-approved
`TRACE_ACCOUNTING_SCOPE` for shared route admission. Additional names are
`TRACE_ACCOUNTING_MAX_ATTEMPTS`, `TRACE_ACCOUNTING_MAX_IN_FLIGHT`,
`TRACE_ACCOUNTING_MAX_SUBJECT_IN_FLIGHT` and
`TRACE_ACCOUNTING_REQUESTS_PER_MINUTE`. The default allowance is 20 reservations;
the zero-paid profile and no automatic retry/fallback remain in force.

Keep the same scope across restarts and replicas. Do not rotate it to bypass
depletion. A changed policy under an existing scope is rejected. Shared route
admission and provider reservations persist through restarts. Missing usage is
explicitly unknown; application counters are not Google Billing measurements.

If an operation crashed, first establish that it really stopped. A verified
Trace administrator can then run:

```sh
python -m scripts.reconcile_ai_controls provider OPERATION_UUID --confirm-stopped
python -m scripts.reconcile_ai_controls admission LEASE_UUID --confirm-stopped
```

The command prompts privately for the administrator token. Never pass that token
on the command line or paste it into logs. Recovery records an audit event and
does not refund/reset the cumulative allowance. Do not reconcile while the old
worker/provider may still be running. There is no automatic lease expiry.

## Backup, restore and rollback

Before changing a populated production database, obtain a consistent backup,
record schema heads and protected row counts, and test restoration in isolated
storage. Managed point-in-time recovery availability/cost must be confirmed with
the operator; it is not assumed to be included in a free plan.

Use private PostgreSQL service/password configuration for `pg_dump --format=custom`
and `pg_restore --exit-on-error --no-owner`; never put a credential-bearing URL in
shell history. Restore into an empty isolated target. Verify expected heads,
validated foreign keys, table counts, lesson identity/hash preservation,
ownership, runtime checks, +1/+7 retrieval schedules and archived source/receipt
integrity before declaring recovery usable. Do not run restore/downgrade tests
against active learner data.

Release order: reviewed image/configuration; tested backup/restore; drain old
workers; approved migration job; new worker readiness; authenticated/citation
smoke tests; separately bounded live provider checks; safe monitoring. Preserve
the prior image digest and compatible configuration.

Prefer a compatible code rollback with additive schemas retained. PostgreSQL's
0007 baseline is a downgrade floor; populated knowledge/AI histories also refuse
destructive downgrade. Restoring an older database over newer learner activity
can lose records and requires an explicit recovery decision. No automatic
database reset, history deletion or forced downgrade is part of startup.

## Reproducible local infrastructure tests

`deploy/compose.postgresql-test.yml` is a disposable test target with an
ephemeral loopback-only PostgreSQL port and test-only credentials. It is not a
production manifest. Inspect its published port, then set the documented
`TRACE_TEST_POSTGRES_URL` for the explicit `backend/production_tests` suite.
That suite rejects non-loopback or non-test database/user targets and creates
isolated, verified test schemas.

After building the current image, set `TRACE_TEST_BACKEND_IMAGE` to its local tag
and run `pytest infrastructure_tests --no-cov --disable-socket` from `backend/`.
An explicit `TRACE_TEST_POSTGRES_IMAGE` override may select another reviewed
PostgreSQL major only with the exact
`docker.io/library/postgres@sha256:64-lowercase-hex-digest` form. Mutable tags,
other repositories and other registries are rejected. The historical default
remains PostgreSQL 15. Containers have one CPU, 512 MiB memory, bounded processes
and temporary database storage; only generated test certificates are mounted.
The suite generates synthetic certificates outside Git, starts its own labeled
PostgreSQL TLS container and verifies correct CA/hostname acceptance, wrong
CA/hostname rejection, controlled migration, nonroot startup and SQL readiness.
Only exact labeled test containers are stopped. The synthetic Supabase settings
and disabled AI mode in this smoke test do not establish real authentication,
public HTTPS availability or live provider acceptance.

The current reviewed local image
`sha256:bc82a15a186b9a426cf198760311c10a0f413b2b2a10ab3a2a8bf422e4b6ff31`
passed all four explicit infrastructure tests against actual PostgreSQL 17.11 in
21.50 seconds on 2026-11-03. The full PostgreSQL suite also passed all 36 tests
against that major in 80.10 seconds. Exact database image and isolation evidence
are in `docs/reports/postgresql-17-compatibility-2026-11-03.md`.
The smoke profile included durable admission even though AI was disabled.
The image includes the read-only `python -m scripts.platform_status` operator
command; its schema/admission summary was exercised without provider probes.
This identifies a tested local artifact, not a published registry image or a
completed deployment.

The CI PostgreSQL matrix runs these on pinned official 15.19 and 17.11 images,
separately from the existing Windows/Ubuntu SQLite quality gates. A Vercel
frontend preview alone is not backend deployment
evidence. Cross-site guest-cookie behavior also needs validation: current guest
cookies use SameSite=Lax, so choose a reviewed same-site backend/proxy/domain
arrangement rather than silently weakening cookie policy. Signed-in bearer
authentication still requires correct CORS/project configuration.
