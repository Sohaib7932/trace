# Phase 3.8 architecture audit

Audit baseline: PR #17 merge `b117773eb26c07914196ccf5d126e01f8bc182f0`.
Work continues on `codex/phase-3-8-llm-rag-infrastructure`, created directly
from the verified `origin/main`. No learner database, private environment file,
historical report or frontend implementation was changed for this audit.

## Existing system and verified boundaries

| Responsibility | Actual implementation |
| --- | --- |
| Settings and free-tier activation | `backend/app/core/ai_settings.py`, `scripts/run-gemini-backend.ps1` |
| Provider-neutral bounds/accounting | `backend/app/ai/client.py`, `backend/app/schemas/ai_client.py` |
| Official Google SDK adapter | `backend/app/ai/providers/gemini.py` |
| Application-owned resources | `backend/app/ai/resources.py`, `backend/app/main.py` |
| HTTP admission and retained worker leases | `backend/app/services/feedback_operations.py` |
| Owned, freshly authorized tutor | `backend/app/services/lesson_tutoring.py`, `backend/app/api/v1/tutoring.py` |
| Finite tutor selection | `backend/app/ai/providers/guided_lesson_assistant.py` |
| Support retrieval and selection | `backend/app/repositories/support_knowledge.py`, `backend/app/services/support.py`, `backend/app/ai/providers/bounded_support.py` |
| Reviewed customer-safe sources | `backend/app/support/knowledge.py`, `backend/app/support/corpus.json`, `docs/support-corpus-review.md` |
| Trusted generation | `backend/app/ai/providers/bounded_question_generator.py`, `backend/app/services/candidate_generation.py` |
| Deterministic learner correctness | Existing learning/verification services and Notes/Tasks runtimes; provider adapters have no authority to change their decisions |

The approved model is `gemini-3.5-flash-lite`; the server credential variable is
`GEMINI_API_KEY`. Free-tier confirmation, zero paid budget, zero retries and no
paid/provider/model fallback remain mandatory. Configuration presence is not
proof of Google billing state or provider availability.

The initial focused audit executed 349 offline provider/client/resource/support/
tutor tests: **349 passed in 45.95 seconds**, with sockets disabled except test
loopback. The earlier Phase 3.7 two real-account requests remain historical
acceptance evidence; they are not fresh Phase 3.8 verification.

## Findings before implementation

1. Synchronous SDK/HTTPX read timeouts were inactivity bounds. Checking elapsed
   time after return, or between chunks, did not impose an absolute network
   deadline. An HTTP timeout correctly discarded late results while retaining
   actual worker permits, but did not cancel a blocked synchronous provider.
2. Refusal and output-truncation branches returned before copying SDK usage
   metadata. An offline real-SDK/MockTransport probe reproduced missing input,
   output, response-ID and model metadata despite their presence in the reply.
3. A connection failure was classified as an invalid response. Separate route
   admission limits did not provide a common cross-capability provider limit.
4. Shutdown could close provider/database resources before an abandoned worker
   finished its fresh authorization read. Lifecycle ownership needed a drain.
5. The support retriever used token-set overlap, lexical tie ordering and top
   three passages. Exact quote validation proved quotation integrity, not
   question relevance or evidence sufficiency.
6. Existing source-level tests covered eight production-corpus questions. All
   hit the expected source, but source hits could hide a wrong passage ranking.
   The old eleven-case retrieval fixture was a controlled security fixture,
   not a passage-labelled relevance benchmark.
7. Review metadata and document digests existed, but retrieved/public references
   discarded revision/digest identity. Identical text under a different revision
   was indistinguishable to the post-provider check.
8. Corpus ingestion, review-management APIs, durable historical snapshot storage
   and semantic indexing did not exist. No embedding provider/cost was approved.
9. Tutor selection was bounded to authored concepts and observed run status,
   but all concepts were offered at every stage. No raw attempt explanation,
   private evaluator or prediction answer was sent to Gemini.
10. Deployment remained local. Settings support development/test and SQLite;
    PostgreSQL/pgvector and distributed quotas cannot be assumed available.

## Benchmark and implementation order presented before edits

1. Freeze an offline, passage-labelled lexical baseline with corpus digest,
   evaluation time and intent-family dev/heldout splits. Separate ranking,
   sufficient evidence, citation validity, abstention and provider availability.
2. Correct provider metadata, failure categories, validated capability profile,
   shared admission and shutdown ownership. Preserve the synchronous public
   transport port while bounding the underlying async network operation.
3. Introduce immutable internal approved source/chunk snapshots. Reconstruct
   selected citations against a fresh manifest after slow provider work.
4. Add finite public-material questions filtered by pinned lesson/stage before
   Gemini selection. Keep reserved authored hints and grading unchanged.
5. Compare a declared lexical candidate offline. Require measured benefit and
   review before activation; do not choose embeddings or add infrastructure.
6. Preserve HTTP schemas and frontend adapters, document operator readiness and
   deployment decisions, then run regression/security/browser validation.

See the accompanying provider report, retrieval benchmark, knowledge lifecycle,
frontend handoff and final validation report for implementation evidence and
remaining decisions. Passing tests alone does not establish production readiness.
