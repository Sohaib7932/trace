# Trace production infrastructure review package

Selected architecture and limitations: [hosting ADR](../../docs/architecture/adr-production-hosting.md).
These files have not provisioned anything. Paid hosting, project, region, owner,
budget and deployment remain unapproved external inputs. Do not apply this
module during the current local implementation task.

## Contents and bootstrap boundary

- `versions.tf`: Terraform >=1.10,<2, Google provider 7.30.0 and an external GCS state backend.
- `main.tf`: isolated VPC/private services access, private PostgreSQL 17, backups/PITR,
  Secret Manager containers, workload identities and disabled-by-default service/job resources.
- `release-identity.tf`: scoped protected-main OIDC release identities and request-URL log exclusion.
- `registry.tf`: private same-project regional DOCKER repository, immutable tags,
  no automatic cleanup and read-only repository access for the release identities.
- `monitoring.tf`: disabled-by-default native availability alerts and bounded
  application-status counters; requires operator-supplied notification channels.
- `bootstrap-roles.sql.example`: unexecuted private-schema/least-privilege operator example.
- `outputs.tf`: non-secret IDs needed for reviewed operator configuration.
- `../../.github/workflows/deploy-production.yml`: separate explicit candidate, migration,
  promotion and traffic-rollback operations. It never runs Terraform.

The initial infrastructure bootstrap and application activation are separate.
`enable_application=false` and `enable_migration_job=false` are the defaults so missing private secret versions and
unverified proxy trust cannot silently start the backend. Infrastructure-only
bootstrap still creates billable database/storage resources if an operator
applies it; false is **not a no-spend switch**.

Terraform creates no database users/passwords, secret versions or provider keys.
Never put those values into `.tfvars`, state, GitHub inputs, terminal commands or
logs. Supply only non-secret approved settings through private local inputs.
Use an existing restricted/versioned GCS state bucket supplied at `terraform init`.
No state bucket or billing account is created or linked by this module.

## Required operator inputs

Record the following before an authorized plan/apply:

| Input | Source / requirement |
| --- | --- |
| `project_id`, `billing_account_id`, `region` | Existing approved hosting account/project; region and residency decision |
| `release_owner`, `hosting_approval_reference`, `monthly_budget_usd` | Accountable team/role and separately approved paid-hosting record; alerts are not a spending cap |
| `accounting_scope` | Stable approved durable allowance/admission identity, at most 78 characters to leave room for derived namespaces; preserve across every replica/restart/release and never change it to refill quota |
| `frontend_origin`, `supabase_url` | Exact current HTTPS frontend origin and public identity-project URL |
| `github_repository_id`, `github_owner_id` | Immutable numeric GitHub IDs; repository name remains `Sohaib7932/trace` |
| `image` | Verified OCI image digest built from the exact reviewed main commit; Dockerfile runs UID/GID 10001 |
| `trusted_proxy_ips`, `proxy_acceptance_reference` | Verified actual inbound peer contract and HTTPS/spoofing test evidence; never guess a CIDR |
| `tls_acceptance_reference` | Verified private TLS, actual CA/SAN identity and negative certificate tests |
| `cookie_topology_acceptance_reference` | Real-browser same-site HTTPS guest bootstrap/reload/history-claim evidence; default Vercel and Run domains are cross-site |
| `approved_registrable_domain`, `api_hostname`, `domain_mapping_acceptance_reference` | Approved owned domain, distinct HTTPS frontend/API subdomains, DNS/TLS owner and tested custom-host routing |
| `secret_versions` | Private immutable numeric Secret Manager versions, not payloads |
| `enable_live_gemini`, `gemini_unbilled_project_confirmed`, `gemini_activation_approval_reference`, `gemini_secret_version` | Optional, separately approved runtime-only Free Tier activation; disabled and unattested by default; no actual key value is a Terraform input |

The source uses a fresh VPC and `10.40.0.0/24` Run subnet. Review network/address
overlap, organization policies, quotas, custom-role IAM conditions and the exact
provider plan before approval. No region, billing account or cloud identity is
inferred from this machine.

After a separately approved infrastructure bootstrap:

1. Privately establish the reviewed roles/schema using the example SQL against
   the new PostgreSQL database. Roles start NOLOGIN; enable login and set
   different strong passwords through an approved private administrative path.
2. Obtain the real shared-CA certificate chain and certificate DNS SAN hostname.
   Arrange private DNS or use `hostaddr` separately from the verified hostname.
3. Populate `trace-runtime-database-url`, `trace-migrator-database-url` and
   `trace-database-ca` privately. If `name` differs, use the corresponding prefix.
   URLs must use `postgresql+psycopg`, schema `trace`, `sslmode=verify-full` and
   `sslrootcert=/var/run/trace-db-tls/server-ca.pem`. Passwords are URL-encoded.
4. Verify valid TLS, wrong-host/untrusted-CA rejection, private reachability and
   no public SQL endpoint. Verify exact trusted proxy behavior before setting
   `enable_application=true`; application HTTPS enforcement must stay enabled.
5. Review a second plan with the pinned image, numbered secrets and
   `enable_migration_job=true`. Keep `enable_application=false` while preparing
   the schema. Creating the job does not execute it.
6. Run the one-shot migration job only after a verified recoverable backup/restore
   procedure exists; then apply the reviewed post-migration runtime grants.
   Verify those grants using the actual runtime role. Configure the approved
   same-site frontend/API custom-domain mapping and HTTPS certificates; set
   `NEXT_PUBLIC_API_BASE_URL` to the approved custom API origin, not the Run URL.
   Verify guest-cookie bootstrap, reload and claiming in a real browser before reviewing a separate
   plan with `enable_application=true`. Initial application creation is itself a
   release requiring operator approval. No startup migration or automatic
   database downgrade is performed.

## Protected manual release configuration

Create a GitHub environment named `production` with required reviewers and
main-only deployment branches. Set these **non-secret** environment variables
from reviewed Terraform outputs/operator decisions:

```text
GCP_PROJECT_ID
GCP_REGION
GCP_IMAGE_PREFIX
GCP_SDK_VERSION
GCP_WORKLOAD_IDENTITY_PROVIDER
GCP_RELEASE_SERVICE_ACCOUNT
GCP_MIGRATION_RELEASE_SERVICE_ACCOUNT
TRACE_CLOUD_RUN_SERVICE
TRACE_MIGRATION_JOB
```

`GCP_IMAGE_PREFIX` must equal the Terraform `backend_image_prefix` output without
tag/digest. `GCP_SDK_VERSION` is an explicitly reviewed exact numeric SDK version.
Terraform defines the private repository; it does not build or upload an image.
Image build/provenance, protected GitHub environment settings, approved
custom-domain routing/DNS/TLS and state-backend bootstrap remain explicit
operator prerequisites. The service and migrator require a digest from the
selected same-project repository, preserving a single reviewed private-pull
contract instead of silently accepting a different public or cross-project image.

Use OIDC only; do not upload a service-account JSON private key. The workflow
validates input shape and main ancestry; required reviewers must still verify
successful CI, matching image/commit provenance, owner/budget approvals, backup
quality and schema compatibility. References are audit pointers, not proof.

`deploy_candidate` creates a tagged revision with zero production traffic.
Test its HTTPS URL, readiness, signed-in ownership, security and unavailable
states before a separate `promote`. `migrate` uses the isolated job/identity.
`rollback` changes only application traffic to a compatible existing revision;
it does not restore or downgrade the database. Reconcile approved image/revision
changes back into the reviewed Terraform inputs before the next infrastructure
plan to avoid accidental drift reversal.

## Private OCI repository and reviewed manual upload

`registry.tf` defines one same-region standard DOCKER repository named
`<name>-backend` in the approved hosting project. There is no public repository
IAM grant, remote registry, cleanup policy or automatic upload. Tags are
immutable and Terraform destruction is prevented; keep released images and
rollback digests. Storage still costs money when images exist. Any eventual
retention/deletion change requires a separate owner decision, not an automatic
cleanup job added to satisfy a budget alert.

The outputs `backend_artifact_repository_id` and `backend_image_prefix` supply
the actual reviewable destination. Both OIDC release identities receive only
repository-scoped Artifact Registry Reader. They cannot publish a new image.
The runtime and migrator workload identities keep their separate database-secret
permissions; no writer role or registry credential is added to them.

Cloud Run's platform service agent has preconfigured access to same-project
repositories through its managed role. Image import is performed by the platform,
not by exposing a registry password to the application. Verify that the managed
service-agent grant exists and organization policy permits it before deployment.
Do not grant service-agent roles to a human/workload identity. A cross-project
registry would require a separate explicit reader/IAM review and is outside this
selected artifact. [Cloud Run registry integration](https://docs.cloud.google.com/artifact-registry/docs/integrate-cloud-run),
[same-project runtime access](https://docs.cloud.google.com/artifact-registry/docs/deploy),
[required deployer roles](https://docs.cloud.google.com/run/docs/reference/iam/roles)

The following is a **future operator procedure, not an executed upload**:

1. Obtain hosting/storage budget approval, an approved private publisher identity
   and repository-scoped Artifact Registry Writer permission. The identity and
   its grant are external owner inputs; no human account is invented here.
   Do not grant a project-wide editor/admin role for upload convenience.
2. Use a clean reviewed release checkout at the exact successful main commit.
   Confirm `.dockerignore` excludes environment files, databases, logs, local
   state/values and credentials before building. Do not build private uncommitted
   work into the release image. Record the source commit, build toolchain,
   Dockerfile/dependency lock identity and review evidence.
3. Authenticate privately using the approved human/federated identity and the
   Google credential helper. Never use a service-account JSON key or print an
   access token. Replace every placeholder below with the approved non-secret
   output/commit; these commands have not been run by this implementation:

   ```sh
   TRACE_RELEASE_IMAGE_PREFIX="APPROVED_backend_image_prefix_OUTPUT"
   TRACE_RELEASE_COMMIT="FULL_REVIEWED_MAIN_COMMIT_SHA"
   gcloud auth configure-docker APPROVED_REGION-docker.pkg.dev
   docker build --platform linux/amd64 --file Dockerfile \
     --label "org.opencontainers.image.revision=$TRACE_RELEASE_COMMIT" \
     --tag "$TRACE_RELEASE_IMAGE_PREFIX:$TRACE_RELEASE_COMMIT" .
   docker image inspect "$TRACE_RELEASE_IMAGE_PREFIX:$TRACE_RELEASE_COMMIT" \
     --format '{{.Config.User}}'
   ```

4. Verify UID/GID `10001:10001`, the exact reviewed image content and approved
   container smoke/security gates locally. A source label alone is not proof of
   provenance. After explicit publisher/reviewer approval, upload that immutable
   commit tag and read its remote digest:

   ```sh
   docker push "$TRACE_RELEASE_IMAGE_PREFIX:$TRACE_RELEASE_COMMIT"
   gcloud artifacts docker images describe \
     "$TRACE_RELEASE_IMAGE_PREFIX:$TRACE_RELEASE_COMMIT" \
     --format 'value(image_summary.digest)'
   ```

5. Preserve the returned `sha256` with the commit/build/review evidence. Use
   `<backend_image_prefix>@sha256:<returned_digest>` as Terraform `image` and the
   protected manual workflow input. Verify private pull using the scoped release
   identity, then deploy a zero-production-traffic candidate for acceptance.
   Do not retag `latest`, overwrite an immutable commit tag, delete rollback
   artifacts or elevate the runtime identity to fix a pull error. Publisher
   grant retention/revocation is a separately approved operator procedure.

The module does not claim a built image, uploaded digest, signed attestation,
received approval or successful private pull. Those are release evidence still
required from the actual operator run.
[Artifact Registry access control](https://docs.cloud.google.com/artifact-registry/docs/access-control),
[Docker credential helper](https://docs.cloud.google.com/artifact-registry/docs/docker/authentication),
[push/pull procedure](https://docs.cloud.google.com/artifact-registry/docs/docker/pushing-and-pulling),
[digest lookup](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/about-container-images)

## Local validation boundary

Offline formatting/schema validation can use the official
`hashicorp/terraform:1.13.5` image with only this directory mounted and no cloud
credentials. `terraform init -backend=false` downloads the pinned provider and
does not initialize state or provision resources; `terraform validate` does not
test cloud IAM, certificate identity, billing, actual proxy peers or a deployment.
The dependency lock file is retained for reproducible provider selection. Never
run plan/apply from an unreviewed developer environment or mount private keys
into the validation container.

Current production AI/embedding modes remain disabled by default. The optional
runtime-only free-text activation below is prepared but has not been applied.
Embedding remains disabled and retrieval remains lexical in both profiles; no
backend secret is sent to Vercel or embedded into frontend build variables.

Every production profile uses durable shared accounting/admission even when
both provider modes are disabled. Initial provider policy is cumulative 20
attempts, 4 global in-flight / 1 per subject and 10 requests per minute. It does
not reset automatically each day or restart. Scope/policy changes and stranded
lease reconciliation require a separate explicit operator decision; do not
rotate the scope, refund unknown work or weaken shared controls during release.

## Optional approved Free Tier text activation

`enable_live_gemini=false` is the default. Terraform prepares an **empty**
`<name>-gemini-api-key` Secret Manager container, without a secret version or
payload. It grants no Gemini secret access while the flag is false. Hosting
billing approval never authorizes billing on the separate existing unbilled
Gemini key project. A zero provider budget and an attestation cannot inspect or
prove Google project billing status: the accountable operator must privately
verify that the exact key project remains Free Tier with billing disabled.

After infrastructure/application release prerequisites and a separate hosted
provider activation approval are satisfied, the operator can review these
**non-secret** inputs, without changing application or Terraform source:

```hcl
enable_application                   = true
enable_live_gemini                   = true
gemini_unbilled_project_confirmed     = true
gemini_activation_approval_reference = "APPROVED_PROVIDER_REVIEW_RECORD"
gemini_secret_version                = "IMMUTABLE_POSITIVE_NUMERIC_VERSION"
```

The last two lines are placeholders, not valid applied configuration. Obtain the
actual approval record and immutable numeric version privately; never put the
key itself in `.tfvars`, state, shell arguments, GitHub inputs, documentation or
frontend variables. Before reviewing the activation plan, an approved operator
privately populates the empty container using the approved secret-management
procedure. No secret-version/payload resource exists in this module. Version
aliases such as `latest`, a missing attestation, a missing provider approval or
activation without the application are rejected.

Only the **runtime** service account receives secret-scoped Accessor when
enabled; the runtime container receives `GEMINI_API_KEY` by numbered secret
reference. The migrator always retains `TRACE_LLM_MODE=disabled`, receives no
key and has no key-access IAM grant, even during runtime AI activation. Release
identities receive no key-access grant either. Verify actual IAM and key-project
billing privately before release; mock tests establish only artifact behavior.

The runtime uses the exact existing `gemini-free-text-v1` profile:

| Setting | Fixed value |
| --- | --- |
| Mode / provider | `gemini_free` / `gemini` |
| Generation / conversational model | `gemini-3.1-flash-lite` for both |
| Credential name | `GEMINI_API_KEY`, runtime secret reference only |
| Paid allowance / per-attempt reservation / retries | `0` / `0` / `0`; no fallback |
| Request / response bytes | 32,768 / 16,384 |
| Input / output token bounds | 16,384 / 4,096 |
| Connect / response / total deadlines | 3 / 10 / 20 seconds |
| Process attempts / in-flight / requests per minute | 20 / 4 / 10, with the existing stricter durable subject/global admission |
| Production provider allowance | Same stable cumulative durable scope and 20-attempt cap; activation does not reset it |
| Embedding / retrieval | `disabled` / `lexical`, unchanged |

These settings are not operator-selectable model or spending overrides. The
non-secret `runtime_ai_profile` output describes configured intent, not a
successful provider call. Live tutor/support delivery still requires the
approved application/knowledge state, valid authentication, working provider
quota and current source authorization. Generation remains constrained by the
existing trusted validation and unpublished candidate rules; this flag does not
publish or assign exercises. Exhausted quota or provider failure remains honest
unavailability, not a mock success.

Review a zero-traffic candidate first and collect bounded real provider,
sanitized error, durable allowance and answer/source visibility evidence before
promotion. Disabling the flag removes the runtime key reference/access grant and
restores text-disabled configuration in the reviewed next revision. Traffic
rollback to an older live-enabled revision can still use its pinned key version;
emergency key revocation/rotation and old-revision traffic review are separate
operator actions. Never change the stable allowance scope to refill quota.

`tests/live_gemini.tftest.hcl` runs only credential-free mocked Google **plans**.
It verifies disabled defaults, runtime/migrator isolation, the fixed zero-paid
profile and rejected incomplete approval/version/scope inputs. CI repeats these
tests using the pinned Terraform image without a cloud identity; this is not a
real cloud plan, deployment, key availability check or provider billing check.
[Terraform provider mocking](https://developer.hashicorp.com/terraform/language/tests/mocking),
[Cloud Run Secret Manager references](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

## Monitoring artifacts and acceptance

`enable_monitoring=false` is the default. No monitoring resource or contact has
been provisioned. Activation requires the approved application/custom host,
existing **verified** `monitoring_notification_channels` resource IDs and a
`monitoring_approval_reference` recording the operator, initial thresholds,
notification test, polling ownership and cost review. Supply channel IDs, never
email addresses, webhook credentials or invented contacts. The module does not
create a notification destination or claim that an alert was received.

| Prepared signal | Exact source and initial condition | Limits |
| --- | --- | --- |
| Backend 5xx | Native `run.googleapis.com/request_count`, class `5xx`, sum over 300 seconds, above 4 | Five or more errors; container-reaching requests only, not an SLO |
| HTTPS readiness | Certificate-verified fixed `GET /api/v1/health/ready`, HTTP 200 and JSON `status=ready`; three public checker regions, every 60 seconds; at least two failures sustained 120 seconds | Needs approved custom API DNS/TLS and proxy trust; does not probe Gemini or source eligibility |
| PostgreSQL server down | Native `cloudsql.googleapis.com/database/up` below 1 for 180 seconds | Server-up signal, not schema/role/restore proof; sampled every 60 seconds with documented ingestion delay |
| PostgreSQL capacity pressure | Native `cloudsql.googleapis.com/database/disk/utilization` above fraction `0.80` for 300 seconds, per-instance 60-second `ALIGN_MAX` | Initial engineering warning, not an SLO; 60-second sampling and up to 165-second visibility delay; missing data is not free-space proof |
| Auth/admission burst | `request_complete` logs, only status 401/403/429; per-status count over 300 seconds above 19 | Twenty or more; legitimate guest bootstrap can produce 401; not proof of an attack |
| AI delivery unavailable | Validated `ai_delivery` events with `ai_outcome=unavailable/error`; per-family count over 300 seconds above 4 | Includes HTTP 200 unavailable states; not a semantic-quality score or proof of provider billing |

Counts 4/19/4 are configurable engineering starting thresholds, **not measured
production baselines or approved SLOs**. The owner must review them against
expected traffic and deliberately disabled feature modes. Policies never
increase quota, retry a provider call, enable paid fallback or change a model.

The log counters extract only three-valued `status_code` or bounded
`ai_family`, `ai_status`, `ai_source`. They do not extract request/session/account
IDs, questions, outputs, raw URLs, arbitrary error messages, tokens or vectors.
The current AI helper supports tutor/support/generation/embedding families;
only actual instrumented paths emit events. Tutor/support HTTP delivery is
instrumented after final authorization and source-release checks. Do not infer
generation/embedding delivery coverage solely from the metric's allowlist.
The formatter uses JSON `level`, not a verified native Cloud Logging severity
mapping; the AI metric deliberately filters the validated outcome instead.

The existing platform request-URL logging exclusion stays in place. Native
request counters do not require retaining raw request URLs. Missing metric data
is not treated as a passing availability check; the configured threshold
policies do not prove that a missing telemetry pipeline is healthy. New metrics
need actual traffic and an operator time-series/incident test before reliance.

Source expiry/revocation, schema currency, cumulative allowances, missing usage,
aggregate provider tokens and observed provider durations are inspected using
the existing read-only operator command in the approved private environment:

```sh
python -m scripts.platform_status
```

This reports current knowledge availability/issues, the nearest eligible source
expiry with a 24-hour warning, and aggregate durable usage. It sends no live AI
probe and prints no learner identity or raw conversation. It does not send a
background expiry notification, guarantee provider availability or calculate
a model-quality score. Before activation, the operator must approve a polling
cadence, owner and escalation procedure and test expired/revoked sources,
depleted allowances, unknown token usage, delayed provider completion and CLI
failure. No polling daemon, scheduled cloud job, auto-refund or escalation
contact is silently installed here. Review-window reminders and advance-expiry
notification remain an explicit operational decision.

Before relying on these artifacts in an approved staging project:

1. Verify notification-channel ownership/verification and receive a test alert.
2. Verify metric descriptors and actual time-series labels, including Cloud SQL
   `database_id` (`project:instance`) and the returned readiness `check_id`.
   Check both failed and restored conditions; do not accept an empty chart as a
   passing test.
   Verify the disk-utilization signal uses fraction units (`0.80` means 80%),
   not `80`, and validate capacity-pressure notification/restoration safely in
   approved staging without filling a production disk. The configurable
   `database_disk_utilization_threshold` is bounded to `0.50`–`0.95` and requires
   the same monitoring-owner/verified-channel approval. Review storage growth,
   the existing 100-GiB auto-resize ceiling, budget and backup/recovery procedure;
   this alert does not delete data or change capacity automatically. It monitors
   Cloud SQL storage, **not** developer workstation, Docker build or container
   filesystem space. Local disk monitoring remains the operator's responsibility.
3. Prove readiness rejects wrong status/body, TLS failures and unavailable DB
   schema/permissions, while the restored exact response passes.
4. Exercise synthetic 401/403/429 bursts and an honest HTTP 200 AI unavailable
   response. Verify only allowlisted labels reach the counters and notifications.
5. Test source invalidation and durable usage/status polling independently of
   public readiness. Preserve the publication, review and paid-provider gates.
6. Review monitoring/Logging/uptime-check costs and retention with the hosting
   owner. Published allowances are not a promise of zero total hosting spend.

Primary references checked 2026-11-03:
[Cloud Run metrics](https://docs.cloud.google.com/monitoring/api/metrics_gcp_p_z),
[Cloud SQL metrics](https://docs.cloud.google.com/monitoring/api/metrics_gcp_c),
[PostgreSQL disk-utilization descriptor](https://docs.cloud.google.com/sql/docs/postgres/admin-api/metrics),
[Monitoring filter syntax](https://docs.cloud.google.com/monitoring/api/v3/filters),
[Cloud SQL resource label example](https://docs.cloud.google.com/sql/docs/postgres/upgrade-major-db-version-inplace),
[public uptime checks](https://docs.cloud.google.com/monitoring/uptime-checks),
[uptime metrics](https://docs.cloud.google.com/monitoring/charts/uptime-charts),
[log metric labels](https://docs.cloud.google.com/logging/docs/logs-based-metrics/labels),
[log metric behavior](https://docs.cloud.google.com/logging/docs/logs-based-metrics),
[current Observability pricing](https://cloud.google.com/products/observability/pricing),
[pinned uptime-check provider schema](https://registry.terraform.io/providers/hashicorp/google/7.30.0/docs/resources/monitoring_uptime_check_config).
