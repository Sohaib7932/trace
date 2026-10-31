# ADR-006 — Preserve attempts and assistance as evidence

Status: accepted; relational learner schema is planned.

## Context
Rewriting an initial prediction after showing a hint erases independent performance.
A single JSON history blob makes ownership, ordering and auditability harder to enforce.
The initial product should work without collecting names, emails or account passwords.

## Decision
Use pseudonymous learner ownership, sessions pinned to immutable lesson versions,
one immutable initial prediction and separate append-only attempts, tutor interactions,
verification runs/checks and factual learning events. Distinguish original, transfer
and revisit contexts explicitly. Store only genuinely variable versioned content and
provider metadata in bounded JSON. Use relational foreign keys for associations.

## Alternatives considered
- Update-in-place answers: simpler, but destroys evidence of assistance and revision.
- Full event sourcing: can reconstruct everything, but adds projection/versioning
  complexity beyond this team's needs.
- Anonymous session IDs as authorization: IDs may leak; ownership needs a separate
  high-entropy credential and server-side scope checks.

## Advantages
Independent and assisted work remain distinguishable; evidence can be reviewed.
Pseudonyms reduce personal data while allowing cross-session ownership checks.

## Disadvantages
More rows and explicit deletion handling. Lost pseudonymous credentials cannot be
recovered through an email account that does not exist.

## Consequences
Append-only means immutable during normal use, not undeletable forever. Define
expiry, learner-request deletion/export and backup retention before collecting
real learner data. Logs must not contain credentials or learner bodies. Agent
development logs in `.claude-logs/` are separate and never learner telemetry.
Server-side transactions/constraints enforce completion and one prediction per session.

## Revisit when
Cross-device recovery, verified accounts, minors' data, collaboration or retention
obligations become actual requirements. Do not add authentication roles speculatively.
