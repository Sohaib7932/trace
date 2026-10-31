# ADR-005 — Controlled exercises without arbitrary execution

Status: accepted; verifier implementation belongs to Module 2.

## Context
Running learner Python inside an API process would grant filesystem, network,
credential and process access. The first field-mismatch lesson requires none of that.

## Decision
Accept a small structured edit (for example an allowlisted request-field choice),
not executable Python. Map it through a trusted lesson adapter to a real in-process
FastAPI exercise route and isolated exercise database. Verify HTTP validation,
transaction completion and a fresh database session read. Separate exercise notes
from the learning-history store and isolate every run/session.

Never use `eval`, `exec`, shell commands, learner imports, dynamic SQL, learner URLs
or arbitrary filesystem paths. Formatting/snippets may illustrate an edit; execution
uses a known implementation and explicit parameters only.

## Alternatives considered
- Local subprocess/container per submission: powerful but requires real sandboxing,
  quotas and egress controls; out of scope and unnecessary for this lesson.
- Simulated success JSON: easy but does not establish application behaviour.
- Unrestricted remote URL verification: adds SSRF risk and untrusted evidence.

## Advantages
Small attack surface and real reproducible request/DB evidence for a narrow concept.

## Disadvantages
The lesson does not teach unrestricted coding. Every accepted edit must be designed
and its scope explained; passing one controlled fixture is not general program correctness.

## Consequences
No live verification is advertised in Module 1. Module 2 needs tests for bad `body`
(422/no row), corrected `content` (201/committed row), rollback, stale/fabricated
response, unavailable DB and two-session isolation before connecting the UI.

## Revisit when
A lesson genuinely needs broader execution. Require a separate threat model,
resource/egress limits and independent sandbox validation before expanding inputs.
