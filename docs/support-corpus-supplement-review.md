# Draft support corpus supplement — review required

Status: **DRAFT. Not approved, imported, indexed, published or serving.**
Prepared 4 November 2026. Technical implementation approval does not approve
changed customer-support copy or transfer the original corpus review to it.

The active nine-article/nineteen-passage pilot remains unchanged. Its
`hints-explanations / tutor-guidance-limit` passage accurately describes the
legacy guided path, but not the separate conversational tutor. The active
corpus does not yet explain the new private-guide or GitHub App workflows.
Support may abstain on those topics or return older guided-mode information;
the successful review-schedule acceptance does not certify these newer topics.

## Exact proposals

Review the full quoted text in these bounded JSON document proposals:

1. [Existing conversational-tutor replacement](../backend/app/support/drafts/hints-explanations-conversation-v1.json)
   replaces the tutor paragraph and preserves the fixture-hint paragraph.
2. [Private learning guides](../backend/app/support/drafts/private-learning-guides-v1.json)
   adds two passages covering private saved guides, generation failure and
   ungraded/unexecuted boundaries.
3. [GitHub Project Learning](../backend/app/support/drafts/github-project-learning-v1.json)
   adds two passages covering required owner setup, selected read-only access,
   partial pinned snapshots, provider data sharing and reauthorization.

These files contain no approval record, reviewer identity, review date, validity
window or publication permission. The fixed pilot loader reads only its active
corpus file; it does not discover the drafts directory. Nothing here activates
these articles. The existing daily-preview passage remains accurate: private
guides do not create automatic daily exercise assignments.

## Source checks

- Tutor modes and permitted owned context: tutor router, conversation service
  and existing conversational-tutor contract.
- Guide privacy, persistence, failure and reader behavior:
  [private-guide contract](private-guides-contract.md) and its schema/service/UI.
- GitHub selected permissions, user proof, partial ingestion and generated-path
  limitations: [GitHub App contract](frontend/github-app-project-learning.md).

## Approval and activation

A human must review the exact document text and canonical digests, select the
intended deployment and specify reviewer/validity. For the durable knowledge
archive, use new immutable revisions and the existing parse, normalize, chunk,
index, validate, review and approve gates, followed by separate authorized
publication. Do not reuse historical approval or overwrite archived revisions.
Any semantic index needs a newly validated manifest-bound build. For the local
pilot bundle, an explicitly authorized reviewed revision must update the
manifest and digests together; this draft performs no such update.

No support contact, billing promise, deployment claim, mastery score or new
automatic-assignment policy is proposed.
