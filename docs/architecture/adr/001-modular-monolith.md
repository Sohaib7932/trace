# ADR-001 — Modular monolith

Status: accepted for Module 1.

## Context
Two developers must ship one trustworthy prediction-to-verification loop. Attempts,
hints and completion need consistent ordering, while the existing frontend already
has a stable design. Independent deployment of domain modules has no demonstrated value.

## Decision
Add one FastAPI application alongside the root Next.js app. Use inward-facing
interfaces, cohesive application services and one relational transaction boundary.
Keep modules distinguishable without creating empty packages for future features.

## Alternatives considered
- Microservices: separate scaling, but distributed transactions/retries would make
  original-attempt and completion guarantees harder to enforce.
- Next.js-only backend: fewer runtimes, but the target Python exercise and planned
  deterministic FastAPI/Pydantic behaviour are clearer in a Python backend.
- One large backend file: initially fast, but mixes HTTP, grading and persistence.

## Advantages
Local debugging, atomic relational writes and independent unit tests are practical.
UI work stays in its existing structure; API contracts define collaboration.

## Disadvantages
Two language toolchains; backend modules share deployment and failure scope.
Boundaries need tests and review rather than network separation.

## Consequences
The composition root wires adapters; domain modules cannot import routers, ORM or
SDKs. Separate the verifier into a process only if future trusted execution needs
require it; do not introduce arbitrary execution in this application.

## Revisit when
A measured workload or security boundary requires independent scaling/isolation,
or ownership grows beyond a small team. Extract one demonstrated boundary, not all.
