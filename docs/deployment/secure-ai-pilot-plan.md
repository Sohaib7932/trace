# Secure AI pilot deployment plan

Status: design only. No host, deployment, public tunnel, production environment, new credential, support destination or paid service is approved by this document.

## Current implementation and deployment boundary

The approved local pilot uses the official Google GenAI SDK, the existing shared application-scoped AI client and `gemini-3.1-flash-lite`. Tutor, support and candidate generation share that infrastructure while retaining their separate policies and trusted validation. The existing PowerShell launcher binds the backend to loopback. It must not be exposed by changing its bind address or opening a public tunnel.

The current configuration supports `development` and `test` environments, not a reviewed production profile. `Settings` accepts SQLite through `sqlite+pysqlite` only. There is no hosting manifest, production secret manager, persistent-volume policy, scheduled backup/restore automation, distributed limiter or release/rollback pipeline established by the source. These are deployment prerequisites, not capabilities implied by passing local tests.

The decision owner must first approve hosting, operating owner, budget, persistence, retention and an exact frontend origin. This plan does not select a vendor. A bounded single-process pilot is the compatible starting scope; multiple workers or replicas require a separate quota and persistence design.

## Configuration, authentication and secrets

Before public hosting, review an explicit production configuration profile and reject development-only exceptions. Keep development, disposable tests, staging and any hosted pilot isolated in their databases, secrets, frontend origins and operational access. Do not copy a developer's private environment files or learner database into a hosted artifact.

| Configuration | Required handling |
|---|---|
| `GEMINI_API_KEY` | Server-side secret only, injected by the approved hosting mechanism; never a frontend variable, URL, log field, build argument or committed artifact |
| `TRACE_LLM_*` | Explicit approved Gemini mode/model/capability profile, confirmed unbilled Free Tier project, zero paid budget, no paid fallback and no retries; preserve byte/token/deadline/concurrency bounds |
| `TRACE_SUPABASE_URL`, `TRACE_SUPABASE_ISSUER`, `TRACE_SUPABASE_JWKS_URL`, `TRACE_SUPABASE_AUDIENCE` | Use the shared project's real HTTPS public auth configuration; issuer and JWKS must match the configured project, never token-selected URLs |
| `TRACE_AUTH_ALLOW_INSECURE_LOOPBACK` | Development-only exception; disabled for any hosted environment |
| `TRACE_CORS_ORIGINS` | Exact approved HTTPS frontend origin allowlist; no wildcard, credentials in URLs, paths or unreviewed preview origins |
| `TRACE_COOKIE_SECURE`, `TRACE_ALLOW_INSECURE_LOCAL_COOKIES` | Secure cookies required for hosting; no local HTTP exception |
| `TRACE_DATABASE_URL` | Backend-managed persistent SQLite path, restricted permissions and protected backups; never expose it to browser code or responses |
| `TRACE_TUTOR_*`, `TRACE_SUPPORT_*`, `TRACE_FEEDBACK_*` | Preserve admitted request size, account limits, concurrency and provider/request deadlines; any changed limits need operational review |

The frontend receives the approved backend API origin and its existing public Supabase configuration only. Supabase public project settings are not substitutes for backend JWT verification. The backend verifies configured issuer, audience, signature, expiry, authenticated role and subject, and rejects anonymous identities for the protected AI account routes. Current support/tutor handlers perform fresh authorization before releasing results. Configure actual hosted Supabase callback/redirect allowlists separately through the authorized project owner; no callback values are invented here.

Terminate HTTPS at an approved reverse proxy or hosting edge. Forward only required routes and headers; preserve request size limits, `Authorization`, approved CORS behavior and `Cache-Control: no-store`. Do not let proxy logging capture authorization headers, cookies, request bodies, private learner content or provider output. Document trusted proxy handling and test externally observed scheme, cookie and origin behavior before release.

## Free Tier, quotas and availability

The application validates the approved model IDs, zero configured paid budget, zero retries and explicit Free Tier confirmation. It does not independently prove Google project billing state. The project owner must verify that the configured credential belongs to the approved unbilled project. No automatic billing activation, model substitution or paid fallback is permitted.

The live-request allowance and admission state are process-local. The default twenty-live-request process cap resets on restart and multiplies across multiple workers, replicas or separately started processes. Requests-per-minute and concurrency controls also do not constitute a distributed quota or an invoice guarantee. Keep the pilot single-process unless a shared limiter and Google-side budget/quota controls are separately approved. Restarting to bypass exhausted limits is not an operational policy.

The application stops admission during shutdown and retains ownership of active work until it drains. A timed-out or cancelled HTTP request does not prove its synchronous worker has ended. Deployment shutdown must allow the actual provider/authorization work to finish before destroying AI or database resources. The current lifecycle has a thirty-second initial drain and a sanitized deferred-drain warning for cancellation-resistant work; that warning requires operator attention rather than a claim that all work was cancelled.

## Health and operator readiness

`GET /api/v1/health/live` proves the process responds. `GET /api/v1/health/ready` checks database connectivity and Alembic heads against the code's expected heads. Neither is a live Gemini request, a billing check, an approved-corpus check or proof of a usable signed-in learner flow.

Operator-only readiness should separately inspect safe provider diagnostics, disabled/closing/closed state, configured limits, sanitized outcome counts, remaining process allowance, corpus readiness issue codes and review expiration. Do not expose private configuration or a raw diagnostic endpoint publicly. Do not make a provider call on each health probe. A successful earlier live request is historical evidence, not continuous availability monitoring.

The reviewed support corpus currently has nine articles and nineteen passages, with an owner-approved thirty-day validity window. Expiry is not automatically renewed. Changed, expired, revoked or incompletely reviewed sources fail closed. Monitor the approved expiration and arrange explicit re-review before it; do not extend it to keep a demo available. A source revocation must remove eligibility before any asynchronous index cleanup. No support contact or SLA is invented.

## Persistence, backup and migration staging

Use persistent storage with access limited to the backend operator. SQLite is the current supported database; do not assume an ephemeral filesystem, arbitrary shared network volume, concurrent independent replicas or PostgreSQL compatibility. The current database layer enables foreign keys, owns short SQLAlchemy transactions and uses a bounded SQLite lock timeout.

Before any hosted data migration or release:

1. Identify the exact database path and Alembic heads without printing private configuration or record content.
2. Create a consistent SQLite backup through an approved SQLite-aware backup procedure, or after a controlled drain. Copying only a live database file is not sufficient when related journal state may exist.
3. Record backup integrity, timestamp, schema heads and protected access. Retention, encryption and recovery targets require operator decisions.
4. Restore the backup to isolated staging storage and verify `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, expected schema heads and representative record preservation without exposing learner data.
5. Run upgrade and applicable downgrade/re-upgrade compatibility checks against disposable or staging copies. Never test a downgrade on the active learner database.
6. Validate authenticated ownership, Notes/Tasks runtimes, verification, retrieval schedules and candidate publication restrictions against the staged release.

Startup does not authorize an automatic schema rewrite. Run any required production migration only as a separate approved release step after a verified backup. Preserve pinned lesson identities, existing learner records, historical schedules and authored runtime contracts.

## Release, drain and rollback

The approved release order should be: reviewed artifact and configuration validation; secret-presence checks without output; verified backup/restore evidence; staging migrations and regression checks; stop new traffic/admission; drain active work; approved database changes if required; start the new artifact; check SQL readiness and corpus/provider diagnostics; authenticated API/ownership/citation smoke tests; minimum separately authorized live checks; monitor sanitized outcomes.

Rollback needs an explicitly tested compatibility boundary between application version, schema heads and knowledge manifest. Retain the prior artifact and approved configuration privately. Roll back code or a knowledge manifest only when the current schema and content remain compatible. An old corpus must still be approved, unexpired and unrevoked; rollback cannot restore permission that was removed.

Restoring an old database over new learner activity can lose records and is not a routine rollback. Stop writes, assess the impact and obtain a recovery decision before any data restoration. Do not silently drop new learner history, reset the database or force a migration downgrade to make an older binary start.

## Historical knowledge archive and receipt retention

Immutable in-memory manifest and passage identities now permit each supported release to name the exact approved source version. Safe structured answer receipts contain only source-version metadata and a request correlation ID; they exclude questions, quotations, account IDs, credentials and review-owner details. This is not yet a durable historical document archive or a retention policy.

A minimal future archive can store a content-addressed, canonical approved-manifest artifact keyed by its existing manifest SHA-256, plus exact approved public documents and version metadata. Preserve it before activating the manifest. Keep an independently controlled active-manifest pointer and append-only approval/revocation events; an archived object is historical evidence, not permission to serve it. Verify the digest when reading, never infer a filesystem path from client/model text, and never allow support retrieval to select arbitrary archive entries.

Archive the exact payload hashed by `SupportKnowledgeSnapshot.content_digest()`: schema version, package revision and ordered source-version records, serialized with the established canonical JSON rules. The complete runtime snapshot also contains evaluation time and availability diagnostics; hashing that outer envelope would produce a different identity. Historical verification and current serving eligibility are separate operations.

Safe receipts can refer to that manifest digest and selected chunk identities, with operator-controlled retention and restricted access. The team must decide storage ownership, archive immutability, authorized reviewer/publisher roles, audit retention, deletion obligations, atomic publication, receipt-write failure policy and recovery behavior before implementation. Local log capture alone is not durable archival, and digest metadata alone cannot reconstruct text after its only copy is replaced.

This plan does not add that archive, receipt persistence, a document-management API, new sources, migrations, a vector store, a new support destination or a deployment.
