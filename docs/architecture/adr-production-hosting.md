# ADR: selected production hosting architecture

Decision: 2026-11-03. Status: **selected architecture and reviewable artifacts;
no cloud resources provisioned and no deployment authorized**. This decision
does not approve spending, billing activation, a region, a project, an operator,
or an availability commitment.

## Selection

Keep the existing Vercel frontend and Supabase identity integration. Run the
Trace OCI backend image on Google Cloud Run, with a same-region Cloud SQL
PostgreSQL 17 instance on private services access. Use Direct VPC egress for
database traffic, Secret Manager for private connection material, and GitHub
OIDC federation for explicitly approved manual releases. This fits the existing
FastAPI application, synchronous PostgreSQL/SQLAlchemy port, bounded provider
clients and separate migration command without replacing the learning runtime.

The initial artifact uses a zonal Enterprise database, one bounded backend
instance, 1 vCPU / 1 GiB container limits and a 20 GiB database disk with a 100 GiB
growth ceiling. These are conservative engineering starting values, **not load
test results or a production capacity guarantee**. Zonal placement does not
provide a regional failover commitment. The owner must approve sizing, region,
residency, restore objectives and any regional HA upgrade before provisioning.

Cloud Run supports immutable revisions and traffic rollback. Its free allowance
does not make Cloud SQL, storage, backups, logs, Artifact Registry or egress free.
Cloud SQL is separately metered by edition, compute, storage and related usage.
No amount is quoted as a team budget or guaranteed total cost. Generate a
region-specific estimate and obtain explicit paid-hosting approval first.
[Cloud Run pricing](https://cloud.google.com/run/pricing),
[Cloud SQL pricing](https://cloud.google.com/sql/pricing),
[revision traffic management](https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration)

The artifact now includes a private regional Artifact Registry DOCKER repository
and an exact image-prefix output. Commit tags are immutable, destruction is
prevented and no automatic cleanup is configured. Separate release identities
receive repository-scoped Reader; an independently approved publisher must
perform the documented manual build/push and record the digest/provenance.
Cloud Run uses its managed same-project service-agent access for image import.
No public repository grant, image upload or writer permission for an application
workload is introduced. [Cloud Run private registry integration](https://docs.cloud.google.com/artifact-registry/docs/integrate-cloud-run)

This hosting approval is separate from the Gemini project's existing unbilled
Free Tier authorization. Do not activate billing on that Gemini project, move
its key to a billed project, or enable paid fallback as part of hosting setup.

## Alternatives considered

| Option | Private database / TLS | Recovery and release considerations | Decision |
| --- | --- | --- | --- |
| Cloud Run + Cloud SQL | Private services access and Direct VPC egress; explicit hostname-verified TLS and separate workload identities | Reviewable Terraform, managed backups/PITR and immutable service revisions; more operator setup and paid database resources | Selected for explicit networking, lifecycle and identity control |
| Render web service + Render Postgres | Same-region private network and internal connection URL; application `verify-full` identity still requires verification | Paid Postgres includes PITR; free database has no managed recovery. Simpler service operations | Valid alternative if the team prefers fewer cloud components; not selected for this artifact |
| Railway service + PostgreSQL | Environment-isolated encrypted WireGuard network; PostgreSQL template is SSL-enabled and private by default | Optional HA, backups/PITR and usage charges require explicit configuration; template defaults do not establish the required certificate identity | Fast pilot alternative, with a separate TLS/restore acceptance exercise required |
| Fly Machines + Managed Postgres | Managed Postgres and application use Fly's private network; platform encryption alone does not prove libpq hostname verification | Managed offering includes HA, backups and pooling; distinguish it from self-managed Fly Postgres and volume snapshots | Possible alternative; avoid assuming self-managed database recovery is managed |
| Supabase-hosted application database | TLS enforcement available; PrivateLink requires Team/Enterprise and an AWS VPC in the same region | Paid plans have daily backups; PITR is a separate paid add-on. This would couple application storage to the identity platform and require cross-cloud/private-network decisions | Retain Supabase for existing identity; do not move Trace data in this milestone |

The table summarizes current platform documentation, not measured performance or
an SLA comparison. Private connectivity and certificate verification are
different requirements. No provider's marketing claim substitutes for the
application's `sslmode=verify-full` acceptance tests.
[Render private networking](https://render.com/docs/private-network),
[Render recovery](https://render.com/docs/postgresql-backups),
[Railway private networking](https://docs.railway.com/networking/private-networking),
[Railway PostgreSQL](https://docs.railway.com/databases/postgresql),
[Railway backups](https://docs.railway.com/volumes/backups),
[Fly pricing and managed features](https://fly.io/pricing/),
[Supabase PrivateLink](https://supabase.com/docs/guides/platform/privatelink),
[Supabase backups](https://supabase.com/docs/guides/platform/backups),
[Supabase SSL enforcement](https://supabase.com/features/ssl-enforcement)

## Database network and TLS identity

`infra/gcp/` disables the Cloud SQL public IPv4 endpoint. The backend uses Direct
VPC egress with `PRIVATE_RANGES_ONLY`; no Serverless VPC Access connector, public
database allowlist, or Cloud SQL Auth Proxy is introduced. HTTPS provider calls
can still use normal external egress when separately approved application
configuration permits them. [Cloud SQL connection choices](https://docs.cloud.google.com/sql/docs/postgres/connection-options),
[Cloud Run Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)

The instance explicitly uses `GOOGLE_MANAGED_CAS_CA`, not the per-instance CA
default. Shared-CA instance certificates include a DNS subject alternative name
that can be verified for private-services-access connections. The operator must
obtain the actual certificate DNS identity and trusted CA bundle from that
instance, create private DNS resolution or supply a separate libpq `hostaddr`,
and verify the hostname against the certificate. A private IP is not assumed to
appear in the certificate. Per-instance CA DNS verification has different
restrictions and must not silently replace this selection.
[Cloud SQL certificate identities](https://docs.cloud.google.com/sql/docs/postgres/configure-ssl-instance),
[CA choices](https://docs.cloud.google.com/sql/docs/postgres/authorize-ssl)

The **private** runtime and migrator URL secrets must contain independently
restricted database roles and `sslmode=verify-full`. Set `sslrootcert` to
`/var/run/trace-db-tls/server-ca.pem`. If using `hostaddr`, keep the actual
certificate hostname as the URL host and use the private IP only as the routing
address. Encode password and query components correctly without logging the
result. Do not use `sslmode=require`, disable verification, or paste the URL
into Terraform or GitHub inputs. [libpq connection parameters](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-PARAMKEYWORDS),
[libpq TLS verification](https://www.postgresql.org/docs/current/libpq-ssl.html)

## HTTPS proxy trust is a release blocker until verified

Frontend/API host topology is a separate release blocker. Existing learner
bootstrap and history claiming use an HttpOnly `SameSite=Lax` cookie. A default
`*.vercel.app` frontend calling a `*.run.app` API is cross-site; HTTPS and CORS
do not make that cookie available to cross-site `fetch` requests. Prefer verified
same-site HTTPS frontend/API custom subdomains under the team's approved owned
registrable domain. This is the required topology for the selected deployment,
not an optional assumption: both the frontend and API custom hosts need approved
DNS ownership and valid HTTPS certificates, and the frontend API base URL must
use that custom API host. A different proxy/cookie architecture requires separate
review. No domain ownership, DNS,
certificate routing or cookie-policy change is invented here. Verify guest
bootstrap, reload and guest-to-account claiming in a real browser before
activation; signed-in Bearer-token success alone does not establish that the
guest flow works. The Terraform activation gate requires the corresponding
`cookie_topology_acceptance_reference` audit record.
`approved_registrable_domain`, `api_hostname` and a DNS/TLS owner acceptance
reference are also required to activate the Terraform service. Shared hosting
suffixes are not team-owned registrable domains. The module checks hostname
shape and suffix relationships; only the operator can establish ownership and
the correct public-suffix boundary. It deliberately does not create a regional
Cloud Run domain mapping without an approved region and supported routing plan.
Custom-domain routing remains an external release prerequisite.
[Browser cookie semantics](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie)

Cloud Run terminates external TLS and forwards cleartext HTTP to the container.
Trace's production ASGI security guard requires the resulting trusted scheme to
be HTTPS. The startup command accepts only explicit trusted proxy IPs/CIDRs and
rejects wildcard/all-address trust. Disabling forwarding trust would reject
non-health application requests; it is not a working deployment configuration.
[Cloud Run container TLS contract](https://docs.cloud.google.com/run/docs/container-contract),
[Cloud Run HTTPS forwarding](https://docs.cloud.google.com/run/docs/triggering/https-request)

The reviewed primary documentation does **not establish a stable inbound socket
peer allowlist** suitable for this application. Metadata-server addresses and
outbound proxy exceptions are not evidence of an inbound peer guarantee. Before
activation, the operator must verify the actual Cloud Run peer contract and
record tests for correct HTTPS propagation, rejected spoofed forwarding headers
and exact peer matching. `enable_application` is false by default; a nonempty
explicit list plus an acceptance evidence reference is required to enable the
service. Supplying a plausible CIDR is not proof. If a supported stable trust
boundary cannot be established, stop activation and review a trusted adapter or
hosting change; do not broaden trust to make a demo pass.

## Identities, secrets and migrations

The runtime and one-shot migrator have different service accounts and different
database URL secrets. By default runtime can read only its own URL and the CA
bundle; migrator can read only its URL and the same CA bundle. No secret payload,
database password, Gemini key or user credential is created by Terraform.
Secret containers are provisioned first; an authorized operator privately adds
immutable numbered versions. Numeric versions are pinned in the service/job.
[Cloud Run secret integration](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

The optional `enable_live_gemini` artifact is false by default. It requires
separate hosted-provider approval, explicit attestation that the existing key
project is unbilled, application activation and an immutable numeric secret
version. Only then does the runtime receive secret-scoped access and a private
`GEMINI_API_KEY` reference. The exact approved `gemini-free-text-v1` profile pins
`gemini-3.5-flash-lite`, zero paid allowance and retries, existing request/token
bounds and deadlines, plus unchanged durable allowance/admission. The migrator
never receives the key or live settings. Embeddings remain disabled and ranking
remains lexical. Terraform prepares only an empty key container; it cannot
inspect or guarantee provider billing status, quota or successful delivery.
The [infrastructure handoff](../../infra/gcp/README.md#optional-approved-free-tier-text-activation)
specifies private setup, zero-traffic acceptance and old-revision revocation
limits. This closes the source-configuration gap without provisioning or
activating a provider. Paid hosting and the separate Gemini project's zero-paid
policy remain different approval boundaries.

`bootstrap-roles.sql.example` is an unexecuted operator review artifact for a new
database. The migrator owns private schema `trace`; runtime never owns it and
has SELECT/INSERT plus a reviewed narrow UPDATE list. Default privileges grant
no broad UPDATE/DELETE/DDL. Apply existing reviewed PostgreSQL migrations using
`scripts.migrate_production` in the separate job, then apply the reviewed current
object grants. Startup does not migrate. There is no automatic downgrade,
developer SQLite upload, learner-record rewrite or database reset.

Production Terraform uses an existing restricted, versioned GCS state backend.
State and local inputs are private artifacts. A project-filtered billing alert
requires an approved positive amount; **alerts do not cap spending**. The owner
must supply the alert recipients/response procedure and independently monitor
usage. [Budget behavior](https://docs.cloud.google.com/billing/docs/how-to/budgets)

Production always uses the database-backed shared allowance/admission port,
including when generation and embedding are disabled. The operator supplies a
stable `TRACE_ACCOUNTING_SCOPE` that survives replicas, restarts and releases.
The initial provider allowance is cumulative 20 attempts with 4 global / 1
per-subject in flight and 10 requests per minute. No day/reset policy or scope
rotation is invented; unknown usage and stranded leases require explicit
reconciliation. This is separate from the cloud-hosting billing alert.

## Release artifacts and operator acceptance

The manual `deploy-production.yml` has no push, pull-request or scheduled
trigger. It uses a protected `production` environment, main-only OIDC trust,
immutable repository/owner IDs and pinned action commits. No long-lived service
account key is used. GitHub environment required reviewers and deployment branch
protection must be configured externally; the YAML cannot establish them.
[Google OIDC action](https://github.com/google-github-actions/auth),
[Google deployment-pipeline federation](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines),
[GitHub deployment protection](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-deployments/managing-environments-for-deployment)

Operations are separate manual invocations: deploy an approved digest with zero
production traffic, run a specifically approved migration, promote a tested
revision, or roll traffic back to a compatible existing revision. Migration and
rollback require a recoverable backup reference. Release input references are
audit pointers, not an automated proof that approval, CI, backup quality or image
provenance exists. The protected reviewer must verify those records, the exact
image/commit provenance and compatibility before approving the job.

Before any production action, complete all of these acceptance checks:

1. Approve project, region/residency, owner, paid-hosting budget, alert response,
   recovery objectives and initial zonal/capacity limits.
2. Review Terraform plan and state-backend access. Bootstrap private networking,
   database and secret containers through a separately approved operator run.
3. Verify private SQL routing, trusted CA/SAN hostname, valid login, wrong-host
   rejection, missing/untrusted CA rejection and absence of public SQL access.
4. Review schema grants and migration identity; take a backup and perform a
   disposable restore drill before transferring or migrating learner data.
5. Establish the verified explicit HTTPS proxy trust boundary and same-site
   guest-cookie host topology described above, including real-browser history
   claiming and reload checks, with approved frontend/API custom-domain mapping
   and DNS/TLS ownership.
6. Configure protected environment/OIDC and test scoped release IAM in staging.
   Terraform schema validation cannot prove IAM conditions or cloud permissions.
7. Validate signed-in ownership, tutor/support unavailable states, secure cookies,
   CORS, rate/concurrency limits, readiness, graceful termination and log privacy
   on the tagged candidate before a separate production traffic promotion.
8. Exercise image rollback against the forward-compatible schema. Database
   restoration is a separate incident procedure; do not run automatic Alembic
   downgrades as application rollback.

Current artifacts keep generation and embedding modes disabled. They do not
approve a production support corpus, semantic index, live model, spending policy
or feature release. Local acceptance and deployment artifacts are distinct from
an observed successful cloud deployment.
