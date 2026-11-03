# Support knowledge lifecycle V1

Status: the original V1 file baseline is preserved. A separate durable V2 archive, explicit administrative lifecycle and release-receipt persistence are implemented. No actual developer database, account role, corpus publication or deployment is changed merely by installing this code.

## Durable governance implementation

`app/domain/knowledge.py`, `app/repositories/knowledge.py`, `app/db/knowledge.py` and `app/services/knowledge.py` implement a bounded customer-document workflow. Shared migration `0008_knowledge_archive` adds seven tables: `knowledge_sources`, `knowledge_revisions`, `knowledge_events`, `knowledge_manifests`, `knowledge_publications`, `knowledge_indexes` and `knowledge_receipts`. No learner, lesson, attempt, verification or retrieval-history row is repurposed.

The archive uses immutable typed JSON artifacts plus normalized identity, foreign-key, digest and sequence columns, following the existing candidate-history persistence convention. Original canonical customer text and identity-normalized text are both retained, with their exact digests and pinned parser/normalizer versions. The initial normalizer makes no text changes. Authored passages remain zero-overlap chunks under `authored-passages-v1`, preserving their existing content and chunk identities. Index artifacts and lifecycle events are separate immutable records; every read revalidates fingerprints and their normalized identity columns.

The implemented source lifecycle is `ingested → parsed → normalized → chunked → indexed → validated → reviewed → approved → published`. Each technical step is an explicit idempotent transition; parsing and normalization revalidate the immutable bounded structured-document input. INDEX constructs the existing bounded lexical knowledge preparation and stores a typed artifact binding its algorithm version, exact source/document digest and ordered chunk identities. It does not claim semantic vectors. Review attests the exact document digest; approval requires an explicit future `valid_until`; publication is a separate administrative operation. Technical success never grants human approval. Rejection is terminal. Approved/published revisions can be revoked or explicitly marked expired; eligibility expires at the timestamp even without a scheduled expiry event.

`app/support/archive.py` defines strict `ArchivedSupportSnapshot` V2. Its sources have independent revision identities; it does not relax V1's package-revision invariant. `app/support/contracts.py` provides the shared authoritative snapshot port. `DatabaseSupportKnowledge` reads the latest explicitly published SQL manifest and rehydrates exact source versions. An absent, changed, revoked, expired or corrupt member fences the whole active manifest. Historical copies remain auditable, but an archived row is never serving permission. Publication uses a sequence/predecessor check under the existing write gate; short PostgreSQL reads use a consistent snapshot. No provider call holds this transaction.

The protected router is `app/api/v1/knowledge_admin.py`, under `/api/v1/admin/knowledge`. It reuses configured JWT verification, `current_account`, active database `admin` roles and existing write-origin checks. Ordinary learners, guests, creators without the admin role, expired identities and role claims in JWT user metadata cannot administer knowledge. The database rechecks the active administrator for every mutation. The asynchronous HTTP handlers delegate to the application-owned knowledge operation pool, with its request deadline and bounded admission. The routes accept bounded structured customer copy; they accept no URL, filesystem path, crawler instruction, arbitrary parser or executable content. Existing operator-only role-grant procedures remain separate. No real account is granted a role automatically.

Durable admission is paired with local worker/provider limits. Its leases remain owned until actual work and cleanup finish, even when the HTTP request times out or is canceled. Application-owned `SharedIngressJobs` reserves bounded capacity before scheduling SQL acquisition and retains it through the final durable release; queued work cannot disappear from shutdown accounting. Startup creates a fresh tracker for that application lifespan. Shutdown closes admission and shares one bounded drain grace period across workers, ingress jobs, AI resources and authentication transport. If real work exceeds that period, deferred cleanup retains its database and clients until it finishes. Python threads are not killed, a timed-out caller does not imply canceled provider computation, and unknown durable leases are not automatically refunded or expired.

Explicit import reads only the fixed existing reviewed corpus. By default it ends at VALIDATED. The distinct `adopt_existing_review` option verifies the exact current package, document digests, recorded reviewer and unexpired window, then records `review_origin=imported_record`. It preserves the historical reviewer label/time/proof separately from the actual importing administrator. It never claims that the importer performed the historical review, invents an account UUID for that reviewer or renews the window. Publication still requires a later explicit operation.

Actual semantic `EmbeddingIndex` artifacts are stored separately after approval/publication. They retain the provider/model profile, dimensions, document/query task profiles, rendering/normalization versions, adapter version, observed provider revision when available, input hashes, exact float32 vector hashes and manifest binding. Benchmark/mock artifacts cannot become production candidates. Re-indexing inserts a new immutable artifact; old vectors and receipts remain unchanged. Storage does not activate a semantic retriever, bypass benchmark gates or select an embedding provider. Large vector uploads are not a learner API.

`authorize_release` runs after provider work and fresh learner authorization. In a short serialized transaction it rechecks the active learner role, current manifest, exact selected versions, relevant index/vector provenance and expiration before persisting a receipt. A changed or unavailable archive fails closed. Receipt UUIDs are server generated; client request correlation is stored as a nonunique SHA-256, never as an identity or idempotency authority. Receipts contain selected source/chunk/model/index digests, not raw questions, submissions, quotations, tokens or account identifiers. `release_authorized` records the server's release decision; it does not claim proof of network delivery. Retried receipt IDs cannot bypass a later revocation.

SQLite and PostgreSQL migrations install immutable update/delete guards and administrative/state-chain guards. An empty archive can downgrade on a disposable database; any archive history refuses downgrade rather than deleting provenance. Actual database upgrades require the separately documented integrity, backup, staging and record-preservation procedure. The archive survives new service/database instances when the configured database persists across restart and redeployment.

Retention remains deliberately minimal: only approved customer-copy artifacts, necessary administrative provenance and bounded source-release metadata are stored. There is no conversation/question archive or automatic purge. Authorized retention, reviewer/publisher separation, deletion obligations and recovery ownership need an operational decision before hosted use. Immutable guards are not a claim that infinite retention is an approved policy.

## Current authority and implemented boundaries

The original operator-reviewed `backend/app/support/corpus.json` remains nine articles and nineteen authored passages, with the existing document digests, named owner and thirty-day approval window. It is the fixed historical import source and an explicitly selected development baseline; durable mode uses an explicitly published SQL manifest. No article text, passage identity, approved digest or expiry was changed. The existing review in `docs/support-corpus-review.md` remains genuine historical evidence.

`ReviewedSupportKnowledge.snapshot()` revalidates that bounded package and its complete review on every acquisition. It creates an immutable `SupportKnowledgeSnapshot` containing the eligible approved copy, package revision, canonical manifest digest and source-version metadata. All package issues remain a whole-package availability fence. A digest mismatch, expiry, future review, invalid package or source revocation yields no eligible sources. Safe issue codes and source IDs are retained internally; exception details and filesystem paths are excluded.

The new optional, server-owned `revoked_source_ids` field defaults to an empty tuple. It can only name unique sources present in the package. Any revocation fences the whole package, preserving the existing all-or-nothing policy. It removes permission immediately; it does not approve new copy, extend expiry or constitute an automatic review. The actual corpus file has no new revocations or other changes.

Only the `public_customer` audience is supported. Unknown requested audiences fail closed. Every eligible source has the existing `approved_customer_safe` classification. This is not a private-document authorization system: staff, tenant-private and user-uploaded sources require an explicit ACL design before admission.

The original V1 module retains compatible `available`/`retrieve` behavior and the same lexical scorer. Its learner-facing reference fields remain unchanged; the durable archive and protected administration operations are separate additions described above.

## Version and citation identities

Each source version binds its source ID, package revision, exact existing canonical document digest, review owner, review instant and valid-until instant. Each authored passage is one chunk under `authored-passages-v1`, with its original ID and ordinal, an SHA-256 of its exact UTF-8 text, and zero overlap. No normalization, splitting, inferred title or rewriting occurs under an existing approval.

A chunk ID hashes the source ID, source revision, document digest, passage ID and digest, chunker version, ordinal, zero-overlap policy and public audience. Identical text under different sources or revisions retains distinct provenance. Text digest equality can support future storage deduplication; it never merges source permissions or review histories.

The immutable manifest digest binds its versioned schema, package revision, approved sources, source content and review metadata. Its evaluation timestamp is deliberately excluded, so reevaluating unchanged eligible content has the same identity. The original authored-package benchmark digest is separately provided by `support_corpus_digest()` using an explicit projection of the original V1 fields. New revocation defaults do not alter that historical digest; eligibility must always be checked separately.

The release sequence is:

1. Acquire one current immutable snapshot.
2. Retrieve bounded candidates from it.
3. Resolve each candidate through `snapshot.resolve(match)`, checking source ID, title, passage ID, exact text and approval against authoritative copy.
4. Retain the corresponding immutable `ApprovedSupportPassageVersion` identities for the internal response receipt.
5. After provider completion, acquire a fresh snapshot and reconstruct every selected reference with `fresh_snapshot.reconstruct(version)`.
6. Release only exact reconstructed text from still-eligible sources. A revoked, expired, changed, substituted or missing version produces safe abstention/unavailability. An index's stored text cannot become the citation authority.

Snapshots are valid for their evaluation instant; retaining an old snapshot is not permission to bypass the final freshness check. Internal receipts record manifest and passage identities without exposing review owner, internal data or private paths in learner HTTP responses. The original V1 values remain in-memory identities; the separate V2 archive and release-receipt repository provide the durable storage described above.

## Broader ingestion workflow

The bounded structured-document lifecycle above is implemented. The following broader stages retain design guidance for future file formats and source channels. Their external parsing, normalization and ingestion capabilities are not implied by the implemented identity-normalized customer-copy workflow.

| Stage | Required input and output | Eligibility consequence |
|---|---|---|
| Ingest | Explicit operator allowlist and immutable source snapshot; bounded raw bytes and origin metadata | Candidate only; arbitrary URLs, filesystem traversal, logs, environment files and learner records are forbidden |
| Parse | Approved parser/version and bounded extracted text; record raw-content digest and parsing diagnostics | Parsing never grants approval |
| Normalize | Explicit normalizer/version and documented reversible mapping where needed | A changed canonical digest creates a new version; old approval cannot transfer |
| Chunk | Explicit chunker/version, size and overlap bounds, stable ordinals/spans and text digests | Existing authored passages remain zero-overlap chunks; future rechunking requires review |
| Index | Derived, replaceable index tied to candidate/manifest identities | Indexed content is not answerable until publication; scorer output contains bounded candidate identities |
| Validate | Schema, references, public-copy safety, digest and reconstruction checks; deterministic evaluation | Technical success is separate from human review and approval |
| Human review | Authorized owner reviews exact immutable content, permissions, conflict declarations and expiration | A review decision must bind the immutable digest; no model approval |
| Approve | Explicit accountable approval and review window | Approved but unpublished content remains unavailable |
| Publish | Atomically activate a fully eligible manifest | Keep whole-package fail-closed behavior until a separate availability policy is approved |
| Version | Preserve immutable prior identity and its decision history; new content gets a new candidate | Existing answers remain traceable; a new version never overwrites historical content under an old digest |
| Expire/re-review | Fence sources at the approved expiration; explicit re-review of the pinned version | No automatic renewal or grace period |
| Revoke/remove | Remove eligibility before asynchronous deletion/reindexing | Stale index entries cannot bypass the authoritative fence |
| Re-index/rollback | Build from eligible authoritative versions; atomically replace derived index manifest | Rollback cannot reactivate expired, revoked or unapproved content |

Candidate provenance should eventually include immutable candidate identity, source/revision, origin snapshot digest, parser/normalizer/chunker versions, content digests, validation identity, review decision, publisher identity, active manifest and replacement/revocation links. None of those fields may be supplied by an untrusted support question. Human role definitions, durable retention, conflict-resolution procedure, review/publisher separation and rollback ownership remain product/operational decisions.

The Git-reviewed corpus remains the bounded historical import source. Durable storage is now additive and separate; historical source snapshots and exact release references are retained without repurposing learner sessions, generation candidates or private lesson configuration. Retention and additional source formats still need explicit operating policy.

## Index and infrastructure decision

The lexical retriever remains the baseline for nineteen passages. A future semantic or hybrid adapter must consume the same immutable eligible manifest and return bounded identities that are hydrated through it. Permission, version and freshness gates apply before ranking and again before releasing a response. Lexical fallback is allowed only over currently eligible copy.

The text-model integration does not implicitly approve embedding recipients or costs. The separate semantic retrieval decision documents the selected embedding profile and evaluation; the archive itself chooses no provider. It stores validated derived artifacts portably in SQLite or PostgreSQL and introduces no pgvector requirement.

## Validation evidence and limitations

Deterministic V1 tests cover original document/passages and digest preservation, canonical package identity, immutable snapshots, exact citation reconstruction, forged/substituted IDs and text, changed content/revisions, expiry during provider work, explicit revocation, unknown audiences and sanitized readiness failures. Durable V2 tests additionally use disposable SQLite databases and isolated PostgreSQL schemas to exercise migration compatibility, lifecycle gates, administrative authorization, publication races, restart/readback, receipt expiry rollback, immutable history and shared admission across two HTTP applications. None of these tests modifies the real corpus, real account roles or the user's database.

Automatic semantic contradiction detection, arbitrary-source parsing/crawling, private-source ACLs, retention automation and unprotected management remain absent. Durable source history, guarded administrative operations and release receipts now exist. Actual human account acceptance, an approved production corpus publication, hosting and operational recovery must still be verified independently of disposable-database and mock-provider tests.
