# Draft support knowledge package

Every document in `manifest.json` is **draft and unapproved**. No application
resource loads these files. No document selection or filesystem loader is exposed
to clients or to the model. The production support corpus and escalation remain
empty; `AIResources.support` still constructs the existing unavailable default.

The ten documents are preparation for human review. Their facts were checked
against the current learner/account routes, `docs/architecture/authentication.md`,
existing catalog/session/retrieval services and unchanged public guidance labels.
They do not certify live Google authentication, email delivery, deployment,
learning outcomes, daily allocation, billing or a support SLA.

The manifest lists exact local review files, proposed document revision, raw draft
file hashes and unresolved approval/freshness information. It is a human review
index, not an approved-source ingestion format. Private blueprint definitions,
operator instructions, environment files, logs and learner records are outside
this package and must not be ingested as customer support sources.

## Inactive readiness helper

`prepare_support_knowledge` accepts only explicitly supplied typed support documents
and separate server-owned review metadata. It never opens a path or selects files.
Review metadata binds to a digest of the complete typed `SupportDocument`, including
source/passages and approval label. This differs from the manifest's raw Markdown
file hash; approving Markdown alone does not silently create an approved RAG source.

Missing reviews, drafts, unknown approval, content changes, future reviews, missing
expiry, expired reviews and explicitly declared conflicts exclude a source. The
caller supplies aware server time and an owner-approved `valid_until`; there is no
default TTL, automatic version precedence or semantic contradiction detector.
Explicit conflict metadata must identify all affected sources. Other unaffected
reviewed documents may still be prepared. A metadata label is not proof that a
human actually reviewed the material.

Test fixtures require explicit fixture mode and keep `test_fixture` provenance.
The prepared result always says `production_activated=False`. Application wiring,
source approval and human escalation are separate prerequisites.

Readiness is evaluated at the explicit supplied timestamp. The returned knowledge
object is a point-in-time preparation result, not a self-expiring production
resource. A future caller must re-evaluate review metadata before use when time or
content changes; caching it indefinitely would not enforce freshness.

## Deterministic evaluation

`backend/tests/fixtures/support_retrieval_cases.json` is explicitly fixture-only.
It covers exact and relevant sources, unsupported questions, declared conflicts,
missing/stale documents, reference integrity and instruction attacks. Tests use
the existing bounded retriever, strict selector and shared mock transport.

Conflict and staleness cases use explicit fixture review flags/timestamps. They do
not claim that lexical retrieval discovers contradictions or that a model's
semantic safety was tested. Quoted source membership, strict output validation
and separation of trusted instructions from untrusted data remain enforced.

## Decisions required before production use

Approve customer wording and public source/passages, choose a source-review owner,
define revision/freshness and conflict-review procedures, approve the human support
destination and resolve deployment-specific authentication/troubleshooting facts.
The documents retain draft status until that review is complete.
