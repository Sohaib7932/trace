# Production hosting artifact validation — 2026-11-03

Status: review artifacts validated locally; no infrastructure provisioned,
credentials supplied, cloud plan/apply, migration, release or deployment run.

The selected architecture is documented in
[the hosting ADR](../architecture/adr-production-hosting.md). Operator inputs,
approval boundaries and bootstrap order are in
[the infrastructure README](../../infra/gcp/README.md).

## Executed checks

- Official `hashicorp/terraform:1.13.5` image, resolved digest
  `sha256:6bbb82d575aa7bd4f0a2c6e3a0838ab9590426c08a71d7a2783643f01004d356`.
  Only `infra/gcp` was mounted; no cloud credentials were mounted.
- `terraform init -backend=false -input=false`: passed; downloaded the signed
  HashiCorp Google provider 7.30.0 and recorded its dependency lock file.
- `terraform fmt -check -diff`: passed after correcting formatting.
- `terraform validate -no-color`: passed against the pinned provider schema.
- Manual release YAML parsed using the existing local `js-yaml` package.
  Assertions verified workflow-dispatch-only triggers, protected environment,
  main-only condition, read-content/OIDC permissions, immutable action commits
  and noncancelling release concurrency.
- Executed the workflow's actual Python input-validation block against **17
  deterministic cases** with Git ancestry mocked and cloud operations absent:
  valid candidate/migration/promotion/rollback, missing approvals or backup,
  invalid action/version/revision/commit, wrong image repository, mutable image,
  command-injection-shaped input, invalid region, ancestry rejection and
  sanitized rejection without echoing the synthetic sensitive marker. All
  expected accept/reject outcomes passed.
- `git diff --check`: passed. The semantic unavailable-attempt report parsed as
  JSON and retained unknown observed RPC counts and null quality metrics.

Initial Terraform validation caught a malformed nested block and missing
explicit `project` arguments on IAM bindings; both were corrected before the
final passing checks. No failed gate was hidden or skipped.

## Unverified external acceptance

Schema validation does not verify real cloud IAM conditions, organization
policies, provider quotas, costs, actual certificate SAN/CA identities, exact
Cloud Run trusted socket peers, same-site frontend/API guest-cookie behavior,
protected-environment configuration, image
provenance, backup restoration or workload behavior. Those require a separately
approved staging/production project and operator run. The explicit proxy trust,
TLS, same-site cookie topology, paid-hosting budget and ownership decisions remain activation blockers.

The application and migration-job activation flags remain false by default;
LLM and embedding modes remain disabled in the production artifact. No successful
deployment or production-readiness claim follows from these local checks.

The subsequent monitoring artifact adds disabled-by-default native 5xx, HTTPS
readiness and Cloud SQL-up policies plus bounded auth/status and AI-unavailable
log counters. Notification channels and monitoring-cost/owner approval remain
external inputs. Metric selection, received incidents and restoration have not
been exercised against a cloud project. The Terraform accounting scope now
allows at most 78 characters so derived capability/ingress namespaces fit the
backend's 96-character contract.
The final monitoring-inclusive module passed `terraform fmt -check -diff` and
`terraform validate -no-color` against the same pinned 7.30.0 provider. A focused
whitespace check over the owned infrastructure/report/startup-test changes also
passed. These remain local schema checks, not observed cloud alert incidents.

A subsequent completeness review replaced the external repository prerequisite
with an explicit private regional DOCKER repository artifact, immutable tags,
deletion prevention and exact image-prefix output. Repository-scoped Reader was
added to the release identities, keeping publisher/workload permissions
separate. The README supplies an unexecuted reviewed manual build/upload/digest
procedure. No image build, upload, repository provisioning or private-pull test
was performed by that artifact review.
The registry-inclusive module passed the pinned tool's `fmt -check -diff` and
`validate -no-color` checks. Real IAM, image provenance and private pull remain
unverified until the separately approved operator release.

The credential-free `Infrastructure artifacts` CI workflow now repeats these
checks for infrastructure changes using the same immutable Terraform image.
Its exact `fmt -check -diff`, `init -backend=false -input=false -lockfile=readonly`
and `validate -no-color` commands passed locally. YAML parsing confirmed only
those operations, read-only repository permission and no plan/apply/destroy.
This validation workflow has no cloud identity or release credentials. A remote
run is reported separately after publication.

## Optional runtime-only Gemini artifact

A final configuration review identified that the disabled production profile
could not yet opt into the already approved hosted free-text provider without a
source edit. The module now prepares an empty `gemini-api-key` secret container
and an optional `enable_live_gemini=false` switch. Enabling it requires separate
provider activation approval, explicit attestation that the key's project is
unbilled, application activation and a pinned positive numeric secret version.
Only runtime receives conditional secret access and an environment secret
reference. Migrator remains text-disabled with no Gemini key/access grant.
The exact approved model, zero paid allowance/retries, request/token/deadline
bounds and existing cumulative durable controls are fixed. Embeddings remain
disabled and retrieval remains lexical. No key payload or real project setting
was read, created or changed for this artifact work.

Executed the **10 credential-free mocked Google plan cases** in
`infra/gcp/tests/live_gemini.tftest.hcl`: disabled defaults; disabled runtime and
migrator; approved runtime profile/key/IAM isolation; rejected missing unbilled
attestation, missing provider approval, activation without the application,
mutable secret alias, zero secret version, malformed approval and an allowance
scope too long for derived namespaces. All **10 passed**. Initial runs required
fixing synthetic plan-time computed identity fixtures; no application assertion
or provider policy was weakened. These are Terraform's in-memory mocked plans,
not actual cloud plans, IAM checks or provisioning.

The literal 20-field Terraform text environment also passed the repository's
actual `AIClientSettings` using its existing backend virtual environment and a
cleared synthetic process environment. Assertions checked exact approved model,
credential variable **name**, zero spending/retries, bounded output/deadline and
process caps. The same check verified disabled embedding and lexical settings;
no key was present or loaded, and no SDK client/network call was constructed.
This verifies configuration compatibility, not key-project billing status or
provider availability. The infrastructure CI workflow now includes the same
mock-provider suite and recursively formats its test configuration. No cloud
identity or credentials are added to validation CI.

The final Gemini-inclusive module passed all four exact local infrastructure CI
commands with the same pinned image/provider: `fmt -check -recursive -diff`,
`init -backend=false -input=false -lockfile=readonly`, `validate -no-color` and
`test -no-color -test-directory=tests` (**10 passed, 0 failed**). YAML parsing
verified the four bounded commands, read-only repository permission and no
cloud-authentication step. Scoped `git diff --check` also passed. No actual
cloud plan/apply, secret version creation, provider call or deployment occurred.

## Bounded storage-capacity follow-up

The existing monitoring module checked managed database server-up state but did
not monitor storage pressure. Added one disabled-by-default Cloud SQL capacity
policy under the same application/monitoring-owner/verified-notification-channel
gate. Google's [PostgreSQL metric reference](https://docs.cloud.google.com/sql/docs/postgres/admin-api/metrics),
checked 2026-11-03, identifies
`cloudsql.googleapis.com/database/disk/utilization` as a `GAUGE`/`DOUBLE`
disk-quota fraction, sampled every 60 seconds with up to 165 seconds of
visibility delay.

The initial engineering threshold is **above 0.80 for 300 seconds**, with
60-second `ALIGN_MAX`, per-instance filtering and missing-data `NO_OP`.
`database_disk_utilization_threshold` accepts only fractions from 0.50 through
0.95. This is a capacity-review warning, not a measured SLO or a guarantee that
an exhaustion incident will be prevented. It does not delete data, reset the
database, raise the existing auto-resize ceiling or authorize additional spend.
It monitors the future Cloud SQL volume, **not** the developer workstation,
Docker build storage or container filesystem involved in a local ENOSPC event.
Actual notification/restoration, time-series availability and safe staging
acceptance remain external release checks.

The final capacity-inclusive module passed the same exact formatting, locked
backend-free initialization, provider-schema validation and mock-test commands.
The suite now reports **16 passed, 0 failed**, including absent-by-default
capacity policy, exact approved metric/instance/fraction/sustained-condition
selection, missing owner/channel rejection, percentage-as-fraction rejection
and both threshold bounds. All inputs and identities were synthetic and the
Google provider was mocked. No cloud resource, notification, actual cloud plan
or provisioning operation was executed.
