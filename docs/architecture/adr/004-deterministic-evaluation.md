# ADR-004 — Deterministic correctness, AI interpretation

Status: accepted; lesson evaluation is planned.

## Context
A plausible explanation can be wrong. A successful HTTP response can also precede
a failed commit. Grading these with an LLM would confuse interpretation with evidence.

## Decision
Lesson-owned deterministic rules evaluate predictions/allowlisted corrections.
Controlled verification owns actual status/body/database checks. AI receives those
results to explain them and may suggest a possible misconception, never a score or
completion decision. Outcomes distinguish correct, incorrect and infrastructure error.

## Alternatives considered
- LLM grading: flexible for free text but non-repeatable and cannot observe a commit.
- String matching for all correctness: easy but confuses equivalent syntax with
  behaviour and is unsuitable for persistence evidence.
- All-or-nothing end-to-end tests: useful but insufficient to explain which check failed.

## Advantages
Reproducible results, auditable evidence and clear error attribution.

## Disadvantages
Each lesson needs trusted rules and fixtures; interpretation still requires quality review.

## Consequences
Persist expected/observed values and check provenance separately from explanations.
A missing dependency or timeout produces an indeterminate/infrastructure outcome,
not a learner failure. Never infer retention or mastery from a passed example.

## Revisit when
Open-ended explanations require human/AI rubric assessment. Store that as a separate
interpretive assessment with provenance, never as proof that an API or DB write happened.
