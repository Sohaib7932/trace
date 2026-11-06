# Backend audit review and ordered rollout

Status: review plan only. The owner authorized the audit commit, feature-branch
push and open PR. Merging, production settings, production migration and deployment
are explicitly excluded from that authorization. PR #41 stays closed and untouched.

## Separate deliverables

| Item | Status at review preparation | Required next evidence |
| --- | --- | --- |
| Backend audit corrections | Implemented; original full run: 5,096 passed, 94.00% coverage; publication rerun recorded below | Reviewed audit PR and fresh CI |
| Original production HTTPS/CORS issue | Unresolved in the running production revision | Approved PR #42 rollout and real transport/auth acceptance |
| Nine-article support corpus | Not published in production at the last read-only audit | Protected admin import, adoption of genuine review and publication; nine sources/19 passages |
| Live Gemini generation | Not verified by this audit | A bounded authenticated provider attempt with successful sanitized provenance |
| Custom lessons in production | Not verified by this audit | One committed lesson request and owned saved-lesson readback |
| Guests across the Vercel/Render domains | Still limited | Reviewed same-site routing/domain solution and real-browser cookie acceptance |
| Migration `0016_guard_search_paths` | Tested on disposable SQLite and PostgreSQL 15/17 only | Verified production backup, approved migration job and integrity checks |
| Audit publication | Authorized; commit/push/PR evidence is recorded in Git/GitHub | Leave the PR open; no automatic merge or release |

Publication validation rerun: **5,096 passed in 1,963.93 seconds (32m43s),
94.00% coverage, process exit 0**. Ruff/format (447 files), configured mypy
(267 source files), PostgreSQL 15/17 (43 tests each), SQLite migration/lineage
(nine), Docker context privacy (one), repository/logging (178) and exact OpenAPI
comparison (54 paths/60 operations) also passed. Fresh remote CI remains a separate
gate; no rollout is authorized by these local results.

The audit is based on PR #42 commit `a87c523025b0346e29bd3d0966bac792b524ec4f`.
At preparation, `origin/main` is `f45428a2aa272e864001e92db624af8763f786da`
and PR #42 is still open. Therefore the audit PR targets
`codex/render-native-https-repair`, isolating the audit changes from the transport
repair. It is a stacked review, not a claim that either change is deployed.

## 1. Finish CI and review before any rollout

1. Review the complete audit diff, including all new tests, the backup-tracking
   removal and the privacy-checked genuine Codex checkpoint. No runtime evidence,
   environment files, database contents or private keys may be added.
2. Require successful Quality jobs on Windows and Ubuntu, frontend checks and both
   PostgreSQL compatibility jobs on the actual audit commit and PR merge ref.
   Confirm the OpenAPI export is still 54 paths/60 operations. A local green run
   does not replace fresh remote CI.
3. Review PR #42's HTTPS trust boundary separately. It defaults to disabled and
   requires an operator decision about all private callers. Do not set its
   acknowledgment merely to make startup pass. Preserve the proxy allowlist.
4. Before an approved merge, inspect main and the Render auto-deploy setting.
   The read-only publication preflight found Render bound to `main`, auto-deploy
   enabled and Render PR previews off. The feature-branch push is not a Render
   release; a later merge into main can initiate a production deployment.
   Arrange the approved deployment window first; do not merge while expecting
   production to stay unchanged automatically.
5. Planned code order: PR #42 first, then the audit PR. After #42 merges, verify
   ancestry and the effective audit diff before retargeting the audit PR to main.
   A squash merge or intervening teammate changes may require a separately
   reviewed integration and renewed tests. Do not force-push or silently drop work.

## 2. Verify the backup and migration target

Before running migration `0016`, obtain separate explicit release authorization.
Privately verify the exact production database, schema `trace`, database version,
current Alembic revision and release commit. Preserve learner/session counts and
existing records. Stop for an unexpected revision or ambiguous target.

Take an operator-approved production backup without purchasing a service or
writing the backup into the repository. Store it privately outside OneDrive and
Git. Record a private checksum and verify restoration into a disposable database;
a file existing is not sufficient. The restored database contains real data and
must remain private/access-controlled, separate from public synthetic CI fixtures.
Keep the original backup unchanged. Do not
publish dump contents, account IDs or connection strings as evidence.

`0016` changes only seven PostgreSQL function-local search paths; it does not
rewrite function bodies, grants, historical migrations or learner rows. The
application requires its expected Alembic head for readiness. An old application
expecting `0015` may fail readiness once the database moves to `0016`, so coordinate
the migration and image switch in the approved window rather than assuming
uninterrupted rolling readiness. Conversely, the new image is not ready against
`0015`. The current TCP health check does not drain application traffic. Agree on
an owner-approved traffic drain/maintenance method before the migration; stop
if none is available rather than presenting a rolling switch as automatically safe.

## 3. Execute a separately approved migration and deployment

This section is a future operator checklist, not an executed command sequence.

- Pin the reviewed release image/commit. The image must contain `0016` before
  invoking its migration runner. Review any other pending revisions; the existing
  runner upgrades to that image's `head`.
- Use the existing operator-only `python -m scripts.migrate_production` from the
  backend context with privately configured production settings. Never invoke it
  against the original OneDrive database or substitute a new empty database.
- Verify the resulting head, expected schema, unchanged record counts, all seven
  function settings, grants and invoker flags. Repeat integrity/schema checks;
  stop on any mismatch. Workers do not run migrations automatically.
- Deploy the approved image through the existing Render service and Dockerfile.
  Keep `PORT=8000`, the current TCP health check, Supabase/Gemini settings, Vercel
  frontend URL and `TRACE_TRUSTED_PROXY_IPS` unchanged.
- If the separately reviewed Render profile is authorized, use only the three
  settings documented in [the transport rollout guide](../deployment/render-native-https.md).
  Private callers can forge X-Forwarded-Proto; a hostname or operator acknowledgment
  does not authenticate them. Do not enable it with an untrusted private path.
  [Render documents which services share this network](https://render.com/docs/private-network).
- Confirm the deployed commit and startup/readiness. Do not infer application,
  authentication, knowledge or AI success from health alone.

Do not automatically downgrade production or restore a backup over subsequent
learner writes. On failure, stop rollout and inspect privately. Application image
rollback, database head/readiness compatibility and possible data restoration need
an explicit coordinated decision. Local downgrade success is not production
rollback authorization.

## 4. Prove HTTPS, CORS and authentication first

On the unchanged frontend and backend domains, run at least 30 consecutive
unauthenticated OPTIONS requests for **each** of `/api/v1/account/me` and
`/api/v1/custom-lessons`, using the exact allowed frontend Origin and required
headers. Retain every status and value-free error category. Require correct ACAO
and credentials headers on every allowed preflight; investigate every
`https_required` instead of retrying until a successful sample replaces it.

Check liveness/readiness, unauthenticated 401s, disallowed origins, spoofed
forwarding headers over HTTP and HTTPS, and error CORS/cache headers. Keep TCP
health until a separately reviewed HTTP check is proven; investigate HEAD behavior
separately instead of treating it as a supported GET operation.

Then sign in privately through the existing Vercel UI. Verify `/api/v1/account/me`,
owned lessons, cross-account denial, claim behavior where a valid guest cookie
exists, and actual Notes/Tasks verification. Do not export access tokens or callback
parameters. A fresh cross-site guest without a usable Lax cookie is expected to
receive `409 guest_sign_in_required`; this audit does not solve cross-domain guest
continuity or weaken SameSite/HttpOnly/Secure.

## 5. Publish the genuine reviewed support corpus

Only after transport/authentication pass and production writes are authorized:

Protected writes retain the allowed frontend `Origin`,
`X-Trace-Client: learning-web` and the genuine account's Supabase Bearer
authorization. Configure/use credentials privately; do not export a token into
the report, repository or shared command history.

1. Use the owner's real authenticated Trace admin account and fresh authorization.
   Reconfirm ownership/role privately; do not grant additional accounts admin or
   manufacture a JWT, approval or reviewer identity.
2. Verify the unchanged `backend/app/support/corpus.json`: nine articles,
   19 passages, original document/package digests, review attribution and validity.
   If expired or changed, obtain a new genuine review; never extend dates silently.
3. Call `POST /api/v1/admin/knowledge/import-reviewed-corpus` with a retained
   operation key and `adopt_existing_review: true`. The existing workflow preserves
   imported reviewer/time/digest provenance. Read back each returned revision via
   the protected `/api/v1/admin/knowledge/revisions/{revision_id}` route.
4. Call `POST /api/v1/admin/knowledge/publications` with the exact approved revision
   IDs, a distinct operation key and the verified current publication sequence
   (`-1` only when absence is confirmed), plus the required truthful operation
   `reason`. Do not guess the sequence, seed via SQL, bypass intermediate states
   or treat technical validation as a new approval.
5. Verify nine published sources and 19 passages using the protected results and
   the existing read-only operator `python -m scripts.platform_status`. Require
   knowledge availability. Verify the sequence/manifest digest in the publication
   response or a separately authorized private metadata read; the status command
   does not expose those fields, and no GET-publication API is implied here.
6. Make one bounded authenticated `POST /api/v1/support/ask` using a public help
   question. Require an actual provider success, an answered response grounded in
   approved passages, accurate source references and a durable release receipt.
   Unsupported questions must abstain. Do not activate unvalidated semantic
   retrieval or call a lexical index an embedding implementation.

## 6. Verify live generation and custom lesson persistence

Confirm the approved unbilled Gemini project, deployed model configuration, zero
retries, zero paid budget and no paid fallback privately. Make no live request
until separately authorized.

Use a signed-in owner to submit exactly one small request through
`POST /api/v1/custom-lessons/requests`, retaining its UUID `Idempotency-Key`.
Poll `GET /api/v1/custom-lessons/requests/{request_id}`; status reads do not
generate again. A 202 queue receipt is not generation success.

Require a real successful provider attempt, committed ready request and saved
lesson; read it through `GET /api/v1/custom-lessons/{lesson_id}` and the list
endpoint. Check ownership denial with another account, stable pinned provenance,
safe answer/explanation visibility, and no extra provider call on reload. Preserve
deterministic Notes/Tasks grading. On unavailable/quota/auth/timeout/validation
failure, stop and report the sanitized stage without retries or paid fallback.

## Historical database exposure: separate coordinated cleanup

The proposed tree removes the tracked backup while retaining its ignored local
copy. No database payload is added. However, old commits and the deletion's parent
still refer to its blob; a clean new snapshot is **not** a history purge.

Because the earlier audit confirmed real learner records, privacy remediation is
recommended. Rewriting history is not required to run Trace, and is not authorized
by this audit publication. A coordinated operation would require:

1. Owner approval, a team push freeze and private preservation of both developers'
   unpublished work. Inventory all affected paths/renames, branches, tags, forks,
   PR refs and artifacts without sharing record contents. Rotate credentials only
   if genuine credentials are identified; the prior pattern scan was not proof of
   their universal absence.
2. In a separate fresh clone, use a current `git-filter-repo` sensitive-data-removal
   workflow covering every historical path. Validate the resulting refs before an
   explicitly approved history replacement. Commit hashes/signatures and PR diffs
   can change; this must not be attempted in either developer's working checkout.
3. Coordinate branch protections and the authorized remote replacement with the
   owner. Reconcile open reviews and pin mappings; do not automatically merge or
   close PR #41 or any other PR as a cleanup side effect.
4. After privately preserving unpublished work, use fresh collaborator clones and
   separately approved fork/old-clone cleanup so old history is not reintroduced.
   Ask GitHub Support about sensitive cached/PR references where applicable.
   Remote rewriting cannot erase copies already downloaded by other people.
5. Verify affected refs/artifacts and retain the filename/content-review guards.

See [GitHub's sensitive-data guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
and the [git-filter-repo manual](https://github.com/newren/git-filter-repo#how-do-i-use-it).
No history rewrite, force push, deletion of local data or external message is
performed by this plan.
