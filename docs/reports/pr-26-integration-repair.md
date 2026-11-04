# PR #26 integration repair

This report covers integration of `codex/github-oauth-ai-chatbots` at
`6eaf1e14a0b7f9513cccbfe4f97b1f3eb259af6c` with `origin/main` at
`2bee8ffa2784f2ef7f49b65aa7e2a9f087238609`. It records local and CI evidence;
it is not a production or live GitHub authorization acceptance claim.

## Changes

- Retained both learner-requested Custom Lessons from main and Private Learning
  Guides/GitHub Project Learning from the feature branch. Verified Notes/Tasks,
  answer-key/practice-only custom lessons, and ungraded guides remain distinct.
- Combined application configuration, service lifecycle and routers; regenerated
  the actual FastAPI OpenAPI export and frontend declarations: **53 paths,
  58 operations**. Exact API regression assertions retain all existing routes.
- Fixed the OAuth token exchange to omit Authorization only on the fixed-host
  OAuth POST. JSON client ID/secret/code/redirect parameters and Accept remain;
  ordinary GitHub REST requests retain Bearer authentication. State, ownership,
  expiry, single use, installation checks and encrypted persistence are unchanged.
- Added an HTTPX-to-h11 serialization regression and sanitized failed-exchange
  cases. These use the installed HTTP stack without making a network request.
- Added `0014_merge_learning_heads`, joining the two published migration heads.
  Every published migration remains unchanged. The merge upgrade changes no
  table/data itself; Alembic applies the missing lineage before recording it.
  The merge downgrade refuses while custom-lesson history exists, preventing
  entry into the existing destructive custom-table rollback.
- Preserved both lesson creation flows in the hub and cleared private frontend
  state on account changes. Resource views are also keyed by account and ID.
- Removed only two redundant EOF blank lines in incoming custom-lesson modules
  to satisfy the unchanged formatter gate.

## Preservation

Work ran in an isolated managed worktree. The original checkout, dirty activity
log, metadata audit, private settings, running services and real development
DB were not edited. No migrations were applied to the real development DB.
All 64 activity-log Git blobs inherited from main are unchanged. Four historical
suggestion-only logs already on the feature branch are retained, not counted as
new human activity. No new logs or transcript reconstruction were fabricated.

No new environment, credential, key, user database or backup appears in the PR
against main. An already tracked database backup is inherited byte-for-byte from
main and is not newly published by this feature diff; it remains a separate
owner privacy-cleanup issue. Untracked validation output and dependency artifacts
are excluded from the commit.

## Verification

At repair-commit creation, the full **4,658-test** Windows backend run and fresh
remote CI are **pending**. Their final outcomes must be read from the PR's checks
and completion report; the collected count is not a passing-test claim.

Executed local gates:

- Full frontend suite: **213 tests / 17 files passed**; ESLint and final frontend
  typecheck passed.
- Backend Ruff passed; **411 Python files** passed formatting and **254 source
  files** passed mypy. No thresholds/checks were lowered.
- Production `npm run build` passed with only the validation process pinned to
  two CPUs. The initial outside-worktree dependency junction was replaced with
  worktree-local installed-package hardlinks; no app configuration changed.
  An unconstrained build had compiled/typechecked but exhausted this machine's
  memory while prerendering with 11 workers.
- Standard local browser startup is **blocked** by occupied port 8000; existing
  services were not stopped/reused. A protected AI-browser attempt failed during
  its build with resource OOM before tests started. These are not passing browser
  results; fresh CI and/or a resource-cleared retry is required.

Focused backend gates:

- 143 GitHub client/authorization/ownership/persistence/architecture tests passed,
  with sockets disabled; 62 are in the provider-client module.
- 26 migration/database tests passed across two focused invocations, including
  populated upgrades from both published heads, snapshot preservation of every
  existing table, schema drift, SQLite integrity/foreign keys, immutable evidence,
  empty round-trip downgrade/re-upgrade and populated downgrade refusal.
- Both SQLite and PostgreSQL migration graphs have one merged head. A local
  PostgreSQL server has not been used; real-server compatibility belongs to CI.
- 43 project logging/release-workflow unit tests passed.

## Live acceptance and inherited limitations

Before live acceptance, verify all nine documented GitHub App variables are
privately loaded in the actual backend process, then start a fresh account-bound
authorization flow.
Do not reuse an expired or already consumed callback. The callback/setup route
is `/projects/github/callback`; its exact origin must match the App configuration,
frontend API base and allowed CORS origin. See
[the setup and acceptance procedure](../frontend/github-app-project-learning.md).

A real installation, OAuth exchange, selected-repository ingestion and cited
Gemini response still require the owner's authorized live round trip. Passing
mock/serialization tests does not establish any of these outcomes. This repair
makes no live provider calls, changes no credentials and performs no deployment.

Pre-existing custom-generation runtime constraints from main remain separate
follow-up work, rather than a new architecture rewrite in this repair:

- Startup recovery marks queued/generating requests failed without a worker
  ownership lease; use one worker until restart/recovery semantics are reviewed.
- A separate custom client shares the transport and durable ledger, but has its
  own local call counter and feature limits. A local in-memory counter alone is
  not a combined application allowance; durable production accounting is shared.
- Cancelled queued jobs and slow custom workers need stronger drain accounting;
  nested lifespans currently obtain custom-runtime shutdown ownership through
  application state. These limits do not establish multiworker production safety.

No PR was merged automatically. External live acceptance remains explicit.
