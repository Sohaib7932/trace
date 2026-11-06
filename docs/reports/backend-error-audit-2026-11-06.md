# Backend error audit — 6 November 2026

Audit branch: `codex/backend-error-audit`, based on tested PR #42 commit
`a87c523025b0346e29bd3d0966bac792b524ec4f`. This report records the completed
audit before its separately authorized commit/push/PR preparation. The
[review and ordered rollout plan](backend-audit-review-and-release.md) keeps
publication separate from migration, merging and production activation.
No claim is made that an audit can eliminate every possible defect.

## Confirmed defects and implemented corrections

| Finding | Reproduction and correction | Implementation |
| --- | --- | --- |
| Queued lesson cancellation leaks the runner's active count | A cancelled queued future never enters `_run`, so its original `finally` never decremented the count. The future's completion callback now owns that decrement for completion, failure and cancellation. | `backend/app/services/custom_lessons.py` |
| Shutdown disposes resources while a lesson worker is committing | Failure injection showed database disposal while the custom worker remained active after provider work. The application now captures each runtime, stops admission, drains the complete worker and retains the database/shared transport through deferred cleanup. | `backend/app/main.py`, `backend/app/api/custom_lessons_runtime.py` |
| Starting another instance interrupts fresh generation | A second application against the same disposable database changed both fresh queued and generating requests to failed. Startup recovery now uses the existing configured strict staleness cutoff, identical to request status reads. | `backend/app/db/custom_lessons.py`, `backend/app/services/custom_lessons.py`, `backend/app/repositories/custom_lessons.py` |
| Service-level fence for recovered verification | Existing SQL guards already rejected a stale original worker with the intended 409 and prevented false grading. The service-level fence preserves that response while rejecting late checks, events, progress and retrieval changes before attempting finalization writes; an explicit idempotency-key replay still returns the saved record. Tests allow only the existing transaction lock-gate update. This is guard hardening, not an observed false-grade defect. | `backend/app/services/verification.py` |
| Support input passes HTTP validation but fails internally with 500 | Standalone and composed-history questions could pass the HTTP model but fail `SupportQuestion` inside an admitted worker. The HTTP model now validates the exact rendered context, returning sanitized 422 before admission/provider work. | `backend/app/schemas/support_http.py` |
| Approved-reference screening misses known credential forms | A synthetic key-shaped reference passed one layer but failed the shared privacy policy. Customer references now share credential-only screening, retaining public-contact handling, source review and original generic validation messages. | `backend/app/core/ai_privacy.py`, `backend/app/schemas/support.py` |
| Error responses lose cache protection | Headers on the injected success response do not transfer to exception responses. Shared `error_response` now supplies `Cache-Control: no-store`, preserving schemas, statuses, CORS and request IDs. | `backend/app/core/errors.py` |
| Cross-site guest bootstrap creates unusable identities | An isolated real Chromium test reproduced cross-site Lax-cookie bootstrap 200 followed by identity 401, while a same-site control succeeded. Exact browser cross-site requests without a valid existing identity now receive nonretrying `409 guest_sign_in_required` before identity creation. Existing valid cookies authenticate read-only; signed-in Bearer and normal same-site flows remain intact. | `backend/app/api/v1/learning.py` |
| PostgreSQL guard search paths are caller-mutable | Supabase reported seven unpinned trigger functions. A disposable old-head PostgreSQL reproduction proved that a direct SQL writer with TEMP privileges could shadow admin tables. Additive migration `0016_guard_search_paths` pins `pg_catalog, <quoted application schema>, pg_temp`. This is a database-writer hardening issue, not an unauthenticated HTTP exploit. | `backend/alembic/shared_versions/0016_guard_search_paths.py` |
| A learner-data database backup is tracked and insufficiently excluded from Docker context | Read-only inspection confirmed local learner/account/session records. The backup is removed from the pending Git index while preserved byte-for-byte locally. A filename-only Git guard prevents recurrence. Docker exclusions now cover dotted database backups, private keys and named env files, verified with synthetic files through Docker's real context filtering. | `.dockerignore`, `scripts/tests/test_repository_private_files.py`, `backend/infrastructure_tests/test_build_context_privacy.py` |

Startup recovery does not retry provider calls. A fresh job whose old process
really crashed waits for the already configured stale interval (default 600
seconds) instead of being blanket-failed when any process starts. Verification
correctness and the existing +1/+7 retrieval schedule remain deterministic.
Expiration is evaluated on a later status read or startup; no background recovery
timer or provider-job replay was added.

The guest guard is an availability correction, not a new authentication mechanism.
`Sec-Fetch-Site` never authenticates a client, and SameSite=Lax, HttpOnly and Secure
cookie rules remain unchanged. Full cross-site anonymous continuity still needs
a reviewed same-site architecture; this change reports that limitation honestly.

The backup remains ignored on disk. Its contents were not published in this
report, and no original database/backup was altered. Pattern checks found no
known credential format in that backup, but that is not a guarantee that all
content is public. Removing a file from the next snapshot does not purge older
Git objects or the already-published history. Historical cleanup requires a
separate coordinated decision; no force-push/history rewrite was performed.

## Validation evidence

Starting baseline was verified remotely on both operating systems: 5,020 passing
backend tests and 93.96% coverage at `a87c523`; all 12 PR #42 checks passed.
That remains evidence for PR #42, not for these uncommitted changes.

Focused checks completed before the final full-suite run:

- Custom lesson lifecycle/recovery/HTTP/concurrency: 52 passed; a broader 270-case
  deterministic AI regression also passed before the recovery extension, whose
  affected tests were rerun afterward.
- Verification authority plus existing Phase 0/Notes/Tasks learning/retrieval:
  72 passed in 120.32 seconds after the compatibility correction below.
- Support validation/archive/release/citation contracts: 189 passed, including
  29 new regressions. The approved nine articles/19 passages and digests are unchanged.
- Guest bootstrap and shared error privacy: 15 passed.
- Full local PostgreSQL suite: 43 passed on pinned PostgreSQL 17 and 43 on 15.
- SQLite hardening/merged-lineage migration checks: nine passed.
- Docker build-context privacy test: one passed using synthetic canaries only.
- Repository/logging tests: 178 passed.
- Final full Ruff/format: passed across 447 backend Python files; configured
  full mypy passed across 267 source files after the compatibility correction.
- Actual in-memory OpenAPI remains exactly equal to the checked-in contract:
  54 paths and 60 operations. No frontend API type regeneration is required.

The first full-suite attempt exposed four unchanged Phase 0 stale-worker
regressions: the proposed service fence returned 200 where the existing contract
intentionally requires 409. That attempt was stopped, its evidence retained,
and the existing assertions are preserved. The correction keeps the 409 and
adds an earlier domain-write fence instead.

The fresh complete Windows backend run then exited successfully with code 0:
**5,096 passed in 1,633.89 seconds (27 minutes 13 seconds), 94.00% coverage**.
That is 76 additional tests versus the 5,020-test baseline and a coverage increase
of 0.04 percentage points from 93.96%. Existing assertions and the configured
85% minimum were not weakened. The run used the existing Python 3.13.5 environment,
with external sockets disabled and application/provider credentials removed
from its child-process environment. No live provider request was made.

Temporary generated test databases use pytest's failed-only retention to bound
local disk use; failed
evidence and private logs are retained. This does not change assertions,
coverage thresholds or test selection.

Frontend checks were not rerun for this backend-only audit. The prior green
PR #42 frontend checks are baseline evidence. At the original audit checkpoint,
the audit changes had not been through a new GitHub Actions run. Fresh remote CI
status belongs to the subsequently opened audit PR; local success is not a claim
that those remote jobs have passed.

The first Docker context test used Docker Desktop's local filesystem exporter,
which failed with `context canceled`. Verification switched to building a
tiny scratch image and inspecting an unstarted, uniquely labelled container's
tar export without extraction. The same privacy assertions passed. Cleanup
touches only the exact test ID/tag after label verification; no force/prune or
unrelated container removal occurs.

## Migration and preservation

Only `0016_guard_search_paths` is added; all 17 historical migration files are
unchanged. PostgreSQL tests cover upgrade/downgrade/reupgrade, all existing rows,
function bodies, ownership, grants, security-invoker flags, governance release,
immutability and both implicit/explicit temporary-schema shadow attempts.
SQLite is a no-op apart from its Alembic version and passes integrity/FK checks.

This audit branch expects head `0016_guard_search_paths`. Production was last
observed at the old deployed code and must not receive this candidate without
an approved, backed-up migration/release procedure. Application workers do not
run migrations automatically. No hosted database DDL was executed.

No frontend source, provider SDK/version, lesson definition/hash, verification
runtime, completion policy, daily-assignment policy or retrieval schedule changed.
All AI tests use controlled providers; no live Gemini requests, credentials,
paid resources, production environment changes, commits, pushes, merges or
deployments were performed in this audit.

## Production findings still requiring release/configuration work

1. **HTTPS/CORS rollout:** PR #42 is green but its Render profile has not been
   activated. The existing transport failures remain a production release gate.
   The explicit private-perimeter review and unchanged proxy allowlist still apply.
2. **Support corpus:** read-only production counts show zero sources, revisions,
   manifests and publications. Help cannot produce approved-source answers until
   the previously approved corpus is imported/published through the protected
   admin API after transport is reliable. No direct SQL import or review bypass
   was performed.
3. **Live AI acceptance:** production provider-attempt/custom-request/lesson
   counts were zero at the audit check. Offline tests do not prove real Gemini
   or lesson creation; verify those through bounded authenticated production
   requests after the reviewed rollout.
4. **Anonymous browser topology:** the cross-site cookie limitation is confirmed.
   Signed-in account flows remain the supported current deployment path; a full
   guest experience needs a separately reviewed same-site routing/domain solution.
5. **Supabase password advisory:** leaked-password protection is disabled.
   [Supabase documents that this feature requires Pro or above](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection).
   No plan upgrade, spending or Auth setting change is authorized by this audit.
6. **Published database history:** the local backup is preserved and excluded
   from the next snapshot, but historical removal remains a separate privacy action.

The Supabase health advisor returned no findings. Its seven search-path warnings
will remain in the hosted project until an approved application of `0016`; local
PostgreSQL success must not be presented as a production advisory clearance.

## Changed-file inventory

Application changes:

- `backend/app/api/custom_lessons_runtime.py`
- `backend/app/api/v1/learning.py`
- `backend/app/core/ai_privacy.py`
- `backend/app/core/errors.py`
- `backend/app/db/custom_lessons.py`
- `backend/app/main.py`
- `backend/app/repositories/custom_lessons.py`
- `backend/app/schemas/support.py`
- `backend/app/schemas/support_http.py`
- `backend/app/services/custom_lessons.py`
- `backend/app/services/verification.py`

New regression tests:

- `backend/tests/integration/test_custom_lesson_lifecycle.py`
- `backend/tests/integration/test_custom_lesson_recovery.py`
- `backend/tests/integration/test_guard_search_path_migration.py`
- `backend/tests/integration/test_guest_bootstrap_readiness.py`
- `backend/tests/integration/test_support_input_boundary.py`
- `backend/tests/integration/test_verification_completion_authority.py`
- `backend/tests/unit/test_custom_lesson_runner_lifecycle.py`
- `backend/tests/unit/test_support_contract_validation.py`
- `backend/production_tests/test_guard_search_paths.py`
- `backend/infrastructure_tests/test_build_context_privacy.py`
- `scripts/tests/test_repository_private_files.py`

Existing tests updated for the recovery cutoff/new migration head:

- `backend/tests/integration/test_custom_lessons.py`
- `backend/tests/integration/test_merged_learning_migrations.py`

Migration, packaging and documentation:

- New `backend/alembic/shared_versions/0016_guard_search_paths.py`.
- `.dockerignore` gains private-file exclusions.
- `backend/trace.db.before-0010.bak` is removed from the pending Git index only;
  its ignored local file remains intact.
- `docs/deployment/render-native-https.md` distinguishes PR #42's rollout from
  this separate migration-bearing candidate.
- This report: `docs/reports/backend-error-audit-2026-11-06.md`.

At the original audit checkpoint, only the database-backup tracking removal was
staged and no commit or push had been made. The owner subsequently authorized
publication of the reviewed audit changes, an authentic privacy-checked activity
checkpoint and the separate rollout plan. Git/GitHub provide the resulting commit
and open-PR status; that authorization does not permit production activation.

The publication adds `docs/reports/backend-audit-review-and-release.md` to the
inventory above and updates the existing primary conversation file
`.claude-logs/2026-10-31_10-25-36_01a18c8a-4fc7-70a0-bf35-3113cfa88f29.md`.
The rollout remains a review-only artifact.

The bounded, explicitly labelled transcript-recovery checkpoint has 170 genuine
prompts and 123 actual emitted final records. All 276 prior records, including two
native-only records, are preserved exactly; 17 verified primary records are added.
Strict parsing, numbering, statistics, source fidelity and repeat-render
idempotence pass. No pending final is invented and recovery is not described as
automatic capture. One archived worktree scope is explicitly mapped to its
verified current registration rather than falsely claimed to exist at its old path.

Delegated-record limitation: the three audit agents' parent ancestry is verified,
but their brief bodies are encrypted in both child records and parent dispatch
arguments. Complete brief/final pairs cannot be verified from recoverable plaintext.
No child entries are fabricated, no decryption is attempted and the original
records/private metadata receipts remain preserved. This is a disclosed logging
gap, not proof of missing implementation or a reason to invent activity.

## Publication validation rerun

After the owner reviewed the initial audit and authorized commit/push/PR only,
the frozen application and test sources were validated again:

| Check | Fresh result |
| --- | --- |
| Complete Windows backend pytest/coverage | 5,096 passed in 1,963.93 seconds (32m43s); 94.00%; process exit 0 |
| Ruff / formatting | Passed; 447 Python files |
| Configured strict mypy | Passed; 267 source files |
| PostgreSQL 15 production tests | 43 passed in 94.67 seconds |
| PostgreSQL 17 production tests | 43 passed in 75.78 seconds |
| SQLite migration and lineage | Nine passed in 7.52 seconds |
| Real Docker context privacy test | One passed in 4.20 seconds |
| Repository/logging tests after the checkpoint update | 178 passed in 11.774 seconds |
| Actual in-memory OpenAPI | Exact match; 54 paths / 60 operations |

The rerun used isolated fixtures, blocked external provider calls and retained
the original coverage threshold. PostgreSQL test resources were temporary,
loopback-only and removed only after ownership verification. No hosted migration,
production configuration change, deployment, live Gemini request or merge was
performed. The original local backup remains intact and ignored; only its Git
tracking is removed. Publication uses the existing developer's verified GitHub
identity with a commit-only no-reply address, without changing global Git settings.
