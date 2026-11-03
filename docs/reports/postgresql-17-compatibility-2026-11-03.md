# PostgreSQL 17 compatibility evidence

The selected hosting architecture targets PostgreSQL 17. This report records
local isolated compatibility tests, not a Cloud SQL instance, public deployment,
production credential, real learner-data migration or provider call.

## Database artifact and isolation

The [Docker Official Image](https://hub.docker.com/_/postgres) lists PostgreSQL
17 Alpine among its supported images. PostgreSQL's
[versioning policy](https://www.postgresql.org/support/versioning/) lists 17 as
supported and 17.11 as the current minor version on the verification date.

An explicit pull of `docker.io/library/postgres:17-alpine` resolved to:

`docker.io/library/postgres@sha256:266d3c257594e195b309ae9d1805e54c788f1d7b375f56bf6c367aac6c917e7b`

Docker image inspection reported `linux/amd64`. Actual SQL reported
`PostgreSQL 17.11 on x86_64-pc-linux-musl` and `server_version_num = 170011`.
The tests ran against the immutable digest, rather than assuming the mutable
tag proved a particular version.

The new explicitly labeled container had one CPU, 512 MiB memory, 128 processes,
128 MiB shared memory and a 256 MiB temporary database filesystem. Its only
published port used an ephemeral `127.0.0.1` binding. It had no host data mounts.
Credentials were synthetic, test-only values. The fixture rejects nonloopback
targets or a different database/user and creates verified disposable schemas.

The complete `backend/production_tests` suite passed: **36 tests in 80.10s**.
This covers the PostgreSQL migration baseline and shared additive lineage,
legacy Notes/Tasks execution, independent readback, constraints/triggers,
snapshot/write-gate behavior, durable accounting/admission, knowledge archive
persistence, ownership and preserved +1/+7 retrieval behavior. No SQL
source change was needed for PostgreSQL 17.

Afterward, the exact new container ID, name and ownership label were checked
before stopping it. The pre-existing PostgreSQL 15 test container was preserved.

## Pinned continuous-integration matrix

The PostgreSQL CI workflow now has independent PostgreSQL 15.19 and 17.11 jobs
with fail-fast disabled. Both the service container and TLS fixture receive the
same fully pinned official image. The existing Windows/Ubuntu SQLite gates are
unchanged. GitHub's documented matrix/service contexts are used; YAML parsing
and the two explicit pinned-image entries were checked locally. This is not a
claim that a remote GitHub run has completed.

The cached historical PostgreSQL 15 container reported 15.17. It was preserved.
For the new matrix, a fresh official 15 tag was pulled and resolved to:

`docker.io/library/postgres@sha256:54e0dd8e8cddcdbb9156c2486eed5a43eccb7214d7c6828097d41ce049fb3984`

Actual SQL in a separate equally bounded temporary container reported 15.19 and
`server_version_num = 150019`. Its complete PostgreSQL suite passed:
**36 tests in 53.76s**. The exact new container identity and ownership label were
verified before stopping it. No historical or user-owned container was changed.

## TLS and production container acceptance

The TLS fixture now permits an operator override only in the exact fully pinned
`docker.io/library/postgres@sha256:...` form. Mutable tags, invalid digests,
unrelated repositories and registries are rejected. Seven deterministic tests
passed for this restriction. Its historical PostgreSQL 15 default is unchanged.

The four infrastructure tests passed against the pinned PostgreSQL 17.11 image:
**4 passed in 21.50s**. They used newly generated synthetic certificates and
separate exact-labeled temporary containers. Correct CA/hostname succeeded;
incorrect CA and hostname failed. The application migrated a fresh private
schema, started as UID10001, passed SQL readiness, enforced the HTTP/trusted-proxy
boundary and retained durable shared admission with AI disabled.

The application artifact was built locally from the reviewed tree:

`sha256:bc82a15a186b9a426cf198760311c10a0f413b2b2a10ab3a2a8bf422e4b6ff31`

This final acceptance was repeated after the application dependency-injection,
default UTC authentication clock, endpoint metadata and semantic-retrieval
documentation corrections were frozen.

The image includes `scripts.platform_status`. Its read-only command reported
current schema, reachable database, durable accounting, disabled text/embedding
modes and provider availability `not_probed`, with zero provider attempts.
The packaging check found no private environment files, shared logs or developer
database. All new TLS/application containers were cleaned by exact ownership
checks. Scoped Ruff and formatting passed for the infrastructure changes.

## Remaining release boundaries

This verifies PostgreSQL 17 compatibility and local certificate/hostname
behavior. It does not prove an intended Cloud SQL CA bundle, private DNS/SAN,
Cloud Run trusted peer, IAM/network permission, backup/restore plan, actual
Supabase authentication or public HTTPS deployment. Those remain operator
acceptance requirements. No image was pushed, no paid cloud resource was created
and no production service was changed by this validation.
