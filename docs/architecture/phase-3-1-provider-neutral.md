# Phase 3.1 — provider-neutral AI infrastructure

## Scope and repository lineage

This is the provider-neutral subset authorized after the Phase 3.1 preflight.
The team has not approved a provider, generation model, conversational model,
credential variable or spending cap. No vendor adapter, SDK or live request is
included. This milestone does not complete the original live-AI definition of done.

Starting branch: `feat/phase-2-4-candidate-validation`, commit
`8e3fca3d9721be875c383ef5ab2113a685220a0f` (pushed and merged through PR #7).
PR #6 is also merged. Work branch `feat/phase-3-1-live-ai-integration` starts at
updated `origin/main`, merge commit `3a60a64a109c09125446e0ff124ffe7fa7420366`.
The user explicitly authorized preserving the pre-existing log-only dirty tree.
No logs were removed, committed or rewritten by this implementation.

The Next.js frontend, FastAPI modular monolith, SQLAlchemy/SQLite repositories,
Alembic history, authentication/ownership, learning lifecycle and deterministic
verification remain unchanged. There is no application dependency wiring for the
new internal operations. No real environment file or learner database is used.

## Components

| Responsibility | Source | Boundary |
| --- | --- | --- |
| Configuration | `backend/app/core/ai_settings.py` | Frozen `AIClientSettings`; only disabled/mock modes |
| Shared transport | `backend/app/ai/client.py` | `BoundedAIClient` and injected `AITransport`; no HTTP or credential capability |
| Typed transport results | `backend/app/schemas/ai_client.py` | Safe status/metadata/usage, with raw content omitted from repr |
| Explicit mock transport | `backend/app/ai/providers/mock_transport.py` | Scripted fixture outcomes; never automatic fallback |
| Generation | `backend/app/ai/providers/bounded_question_generator.py` | Existing `QuestionGenerator` protocol, unchanged request/completion contracts |
| Existing tutoring | `backend/app/ai/providers/bounded_tutor.py` | All three existing `TutorProvider` methods |
| Free-form lesson help | `backend/app/ai/lesson_assistant.py`, `backend/app/services/lesson_assistant.py` | Separate stateless `LessonAssistant` and public-context builder |
| Support | `backend/app/ai/support_assistant.py`, `backend/app/services/support.py` | Separate `SupportAssistant`; no lesson/account operation capability |
| Support retrieval | `backend/app/repositories/support_knowledge.py` | Bounded lexical retrieval over explicitly injected approved documents |

The shared conversational JSON parser is used by tutoring and support only.
Generation continues to use the existing admission parser, preserving original
raw JSON, duplicate-property evidence and rejection codes.

## Configuration and usage controls

`backend/ai.env.example` is a separate, inactive example. Existing `.env.local`,
`backend/.env`, and their examples are unchanged. `AIClientSettings` reads
`TRACE_LLM_*` process variables or an explicitly selected AI-only env file; it
does not load that example automatically. Do not merge these variables into the
existing strict application `.env` schema. The running application does not yet
construct an AI client from this configuration.

The example contains disabled mode, blank provider/model/credential-variable
fields, and zero spending/reservation limits. The credential field accepts a
variable NAME only; no credential value is read, stored or printed. There is no
live mode to activate by changing an environment variable.

Defaults and configurable upper bounds:

| Control | Default | Maximum |
| --- | --- | --- |
| Request bytes (instructions + JSON data + schema) | 32,768 | 65,536 |
| Response UTF-8 bytes | 16,384 | 65,536 |
| Input token budget | 16,384 | 65,536 |
| Output token budget | 4,096 | 16,384 |
| Connection timeout | 3 seconds | 10 seconds |
| Response timeout | 10 seconds | 30 seconds |
| Total deadline | 20 seconds | 60 seconds |
| Extra retries | 0 | 2 |
| Requests per subject/capability/minute | 10 | 60 |
| Active subject/capability buckets | 1,000 | 10,000 |
| Process spending cap and per-attempt reservation | 0 micro-USD | Explicit bounded configuration |

Without an approved tokenizer, input budgeting conservatively counts UTF-8 bytes
as token units. Missing output token metadata uses the same conservative byte
bound. An approved live transport must enforce token limits and connection/read
timeouts during I/O. The neutral synchronous wrapper passes deadlines and rejects
late responses; it cannot interrupt a transport that ignores its timeout contract.

Only timeout, rate-limit and declared transient errors may retry, on the same
transport/model and within the deadline. Authentication, invalid-request,
malformed-output and unknown errors do not retry. There is no provider/model
fallback and no automatic paid top-up.

The client reserves a configured maximum cost before each attempt. Unknown cost
retains the reservation, including failed calls. Known cost is reconciled; a
reported overrun rejects the result and blocks subsequent requests at the cap.
These are mock-tested process-local controls, not a distributed production
billing ledger. Live activation needs approved prices, worst-case reservations,
provider-side caps and multi-process enforcement. Zero cost reservations are
safe here because only the explicitly injected fixture transport is permitted.

Usage snapshots aggregate attempts, known input/output tokens, accounted cost and
missing-usage counts by capability and requested model. They contain no subject
identifiers, prompts, completions or learner history. The explicit mock transport
retains calls in memory for tests; application logging remains unchanged.

## Generation and release

```text
GenerationRequest
  -> BoundedQuestionGenerator -> BoundedAIClient -> explicit mock transport
  -> original GenerationCompletion (raw text preserved)
  -> existing ChallengeContentAdmission
  -> existing compose_lesson_spec with server-owned blueprint and identity
  -> existing CandidateValidationService and isolated trusted runtime
  -> release_eligible = False
```

The adapter sends only the freshly validated existing generation brief and its
educational output schema. No full lesson definition, evaluator, fixture, expected
stored value or database credential is available to it. Generated copy cannot
provide structure, identities, outcomes, private mappings, digest, completion,
provenance, assignment or release authority. Admission/composition/candidate
validation remain separate; the adapter does not invoke or duplicate those gates.

The existing brief includes optional factual count summaries. It has no interests,
raw attempt history or learner-profile instructions. Phase 3.4 needs separately
reviewed interest vocabulary, evidence-window selection, difficulty policy,
provenance/privacy and template-specific framing parameters; no contract fields
are added here to simulate these future features.

There are still no approved complete production blueprints. Test blueprints remain
test-only. No generation endpoint, persistence, publication or learner assignment
is added. A valid mock completion is not a learner-ready generated challenge.

## Tutoring and frontend integration contract

`BoundedTutorProvider` preserves `generate_hint`, `explain_attempt` and
`analyse_misconception`. Model output supplies bounded text only; source and
interpretation-only flags are server-controlled. Instructions separate public
context from policy, retain progressive hints, and forbid grading/execution.
Strict output parsing and syntax checks do not prove the semantic absence of a
solution or a hallucination; an approved provider still needs pedagogical evals.

`LessonAssistantRequest` contains one of the two actual legacy lesson IDs, stage,
the exact five-field public catalog projection, bounded visible attempt/evidence,
up to three previous hints, a question and optional hint level. Unknown/private
keys are rejected. `LessonAssistantReply` has answered/declined/unavailable status,
bounded text, server source, `interpretation_only=True`, `can_complete_lesson=False`.
The service has no repository and makes no progress changes. Its future caller
must authorize the owned session and construct context from its pinned public
content, rather than accept arbitrary client-supplied context.

The existing learner HTTP contract remains:

- `POST /api/v1/sessions/{session_id}/hints`, JSON
  `{"attempt_id":null}` (or the owned attempt UUID; `{}` is also accepted).
- Existing UUID `Idempotency-Key`, learner cookie or verified account identity,
  permitted Origin and `X-Trace-Client: learning-web` protections remain required.
- Response `201` uses unchanged `HintResponse`: interaction UUID, optional attempt,
  sequence, text/null, delivered/error status, `provider="fake"`, fixture,
  prompt_version, interaction_type and creation time.
- Session ownership, prediction-first requirement, terminal-session restrictions,
  exact retries and the three-request guidance budget remain unchanged.

**The new adapters are not wired into that route.** Its service deliberately
rejects non-fixture output; its public provider field is fake-only. Future live
wiring requires a reviewed compatible provenance/API change. Phase 1.1
`TutorPolicy.mode="authored_only"` remains unchanged. The free-form assistant has
an internal typed contract, not a currently callable frontend HTTP endpoint.

## Separate support retrieval

There are zero approved production support sources and no approved human support
contact. `SupportService()` therefore returns unavailable without calling an AI
provider. No repository file is automatically indexed. README and internal
architecture/operator instructions are not treated as approved customer content.

`ApprovedSupportKnowledge` accepts at most 32 explicitly reviewed documents, each
with up to eight bounded passages, globally unique public IDs, title and approval
label. Fixture documents require explicit fixture mode. Retrieval returns at most
three lexical matches. This is document RAG, separate from spaced-learning
retrieval; it does not require embeddings, a vector database or new dependencies.

The conversational adapter can select retrieved passage IDs or report unsupported.
It cannot author factual prose or citations. The server returns exact passage
quotations with source ID/name and passage ID. Unknown or duplicate references,
extra fields, malformed output and provider failures fail closed. Question and
passages remain untrusted data, separate from support instructions. Source review
remains necessary: lexical credential/injection guards are defense in depth,
not a proof that arbitrary content is safe or relevant.

Internal contract for later frontend work:

- `SupportService.answer(SupportQuestion(question=...), subject=<server-owned-id>)`
  returns `SupportResponse`.
- Status: answered/no_sources/unsupported/unavailable; constant status-specific
  message; up to three `{source_id, source_name, passage_id, quote}` references;
  optional explicitly approved `{label, url}` escalation; server source.
- No transcript persistence, account lookup, account changes or private retrieval.
- No HTTP route is added while both live provider and production corpus are absent.
  A future route needs required account authentication, existing write-origin/no-store
  protections, bounded input and per-account support rate limiting. Do not expose
  the internal context/document parameters as a public request body.

Documents requiring approval: customer product overview; supported login/Google
troubleshooting; learning navigation and cycle; progress and hint behavior; common
technical issues; accurate daily-exercise availability; human escalation destination.
Do not invent billing policies, daily scheduling or account actions.

## Deferred work and acceptance evidence

Before provider-specific work: approve one provider, exact two model IDs, credential
environment variable and usage/spending cap. Then implement one replaceable
official-SDK/existing-HTTP adapter with mocked I/O contract tests. A bounded real
smoke test needs separate explicit approval; none is performed here.

Before Phase 3.2: review this neutral milestone and provider completion, approve
authoritative production blueprints, then separately authorize generated-definition
persistence/provenance and migrations. Reuse canonical identities/digests and the
existing four-stage candidate gate. Keep validated candidates unreleased until a
separately authorized publication/assignment process exists.

Daily shared generation and the maximum three new assignments per learner/local
day belong to Phase 3.3. Tutor questions, hints, theory, explanations, retries,
reviews and support consume no new-exercise assignment slots. Interest-based
personalization is Phase 3.4. Existing +1/+7-day retrieval behavior is unchanged.
Creator workflows, frontend integration and multi-language support remain deferred.

## Executed validation

All tests used existing installed dependencies and deterministic/mock boundaries,
with no paid API calls or live credentials. The full suite ran in the existing
isolated validation copy, which contains neither the real `.env` nor `trace.db`.
Only existing disposable test-fixture migrations ran. The final new Python files
and AI example were verified byte-for-byte against the workspace.

| Check | Executed result |
| --- | --- |
| Unchanged Phase 2.4 full baseline | 1,343 passed; 96.99% coverage; 268.14 seconds |
| Shared client/configuration/JSON tests | 63 passed |
| Generation adapter/admission tests | 36 passed |
| Tutor and LessonAssistant tests | 91 passed |
| Support RAG tests | 67 passed |
| Cross-capability isolation test | 1 passed |
| Final focused new tests | 258 passed; 2.86 seconds |
| Final full backend suite | 1,601 passed; 96.86% statement/branch coverage; 227.14 seconds |
| Ruff lint and format | Passed; 150 Python files formatted correctly |
| Mypy | Passed; 107 source files |
| In-memory OpenAPI comparison | Exact equality; 21 paths, 23 operations |
| Protected pre-existing files | All 280 unchanged in content, size and modification time |
| Git index | No staged changes |

The first baseline runner attempt had missing temporary-parent-directory setup
errors; creating that artifact directory reproduced the unchanged passing baseline
without application changes. An intermediate full snapshot also passed 1,589 tests;
the final run above includes the later configuration and sanitization regression
cases and is the authoritative final result. Reports are in the isolated copy's
`phase3-1-results/` directory (`baseline.xml`, `focused.xml`,
`verified-backend.xml`, `verified-backend-output.txt`).

The preserved inventory includes legacy lesson definitions/hashes, Phase 2.3/2.4
implementations, public API schema/types, frontend, migration files, real database
and environment files. Genuine shared logs and the four pre-existing untracked
log artifacts remain in place; the native hook manages actual conversation capture.
No reasoning, tool results or fabricated responses were added to those logs.

No generated challenge or learner history was persisted or assigned by the new
operations. No real-provider connectivity, model teaching quality or production
readiness is claimed. No commit, push, PR, merge or deployment was performed.
