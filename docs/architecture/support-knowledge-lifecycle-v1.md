# Support knowledge lifecycle V1

Status: internal immutable-manifest foundation implemented; document-management workflow proposed. This does not authorize ingestion, publication, a new corpus, an embedding provider or deployment.

## Current authority and implemented boundaries

The customer-support source of truth remains the operator-reviewed `backend/app/support/corpus.json`: nine articles, nineteen authored passages, the existing document digests, named owner and explicit thirty-day approval window. No article text, passage identity, approved digest or expiry was changed for this foundation. The existing review recorded in `docs/support-corpus-review.md` remains authoritative.

`ReviewedSupportKnowledge.snapshot()` revalidates that bounded package and its complete review on every acquisition. It creates an immutable `SupportKnowledgeSnapshot` containing the eligible approved copy, package revision, canonical manifest digest and source-version metadata. All package issues remain a whole-package availability fence. A digest mismatch, expiry, future review, invalid package or source revocation yields no eligible sources. Safe issue codes and source IDs are retained internally; exception details and filesystem paths are excluded.

The new optional, server-owned `revoked_source_ids` field defaults to an empty tuple. It can only name unique sources present in the package. Any revocation fences the whole package, preserving the existing all-or-nothing policy. It removes permission immediately; it does not approve new copy, extend expiry or constitute an automatic review. The actual corpus file has no new revocations or other changes.

Only the `public_customer` audience is supported. Unknown requested audiences fail closed. Every eligible source has the existing `approved_customer_safe` classification. This is not a private-document authorization system: staff, tenant-private and user-uploaded sources require an explicit ACL design before admission.

Existing `available` and `retrieve` calls retain their public behavior and use the same lexical scorer. No public response fields, endpoint, database model or migration are introduced by this module.

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

Snapshots are valid for their evaluation instant; retaining an old snapshot is not permission to bypass the final freshness check. Internal receipts may record manifest and passage identities without exposing review owner, internal data or private paths in HTTP responses. These immutable values do not themselves provide durable receipt storage or a historical content archive.

## Proposed operator-controlled lifecycle

The following stages are a design for a future reviewed workflow. They are not an implemented ingestion pipeline, publication state machine or management API.

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

The current Git-reviewed corpus is sufficient for the bounded pilot. Durable workflow storage, historical source snapshots and receipt retention require a separate additive persistence design and migration validation. Learner sessions, generation candidates and private lesson configuration must not be repurposed as support-document storage.

## Index and infrastructure decision

The lexical retriever remains the baseline for nineteen passages. A future semantic or hybrid adapter must consume the same immutable eligible manifest and return bounded identities that are hydrated through it. Permission, version and freshness gates apply before ranking and again before releasing a response. Lexical fallback is allowed only over currently eligible copy.

No embedding model/provider, vector dimensions, embedding cost, data recipient or vector database is approved by the Gemini text-model integration. Selection requires a separate architecture and cost decision supported by the reproducible benchmark. PostgreSQL/pgvector is not introduced here; SQLite remains the current persistence architecture.

## Validation evidence and limitations

Deterministic tests cover original document/passages and digest preservation, canonical package identity, immutable snapshots, exact citation reconstruction, forged/substituted IDs and text, changed content/revisions, expiry during provider work, explicit revocation, unknown audiences and sanitized readiness failures. They use in-memory copies of the reviewed package and do not modify the real corpus or a database.

The manifest foundation does not implement automatic semantic contradiction detection, arbitrary-source parsing, source-management HTTP APIs, persistent audit receipts, historical archive retrieval, private-source ACLs, distributed publication coordination or an embedding index. Those capabilities remain explicitly pending rather than implied by a passing schema or retrieval test.
