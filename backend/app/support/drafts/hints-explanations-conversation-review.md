# DRAFT: conversational tutor support-copy review

Status: **DRAFT — human review pending. Not approved, imported, indexed, published or serving.**

The adjacent `hints-explanations-conversation-v1.json` is an exact bounded `CorpusDocument` proposal. It contains no approval record, reviewer identity, review timestamp, expiry, publication instruction or inherited authorization. The fixed corpus loader reads only `corpus.json`; it does not discover this directory. Preparing this proposal does not change the active corpus or database.

## Why the existing passage needs review

The approved `hints-explanations` article's `tutor-guidance-limit` passage describes Gemini selecting supplied explanatory text and says the pilot does not provide arbitrary code or full worked solutions. That remains an accurate description of the legacy question-only guided-explanation path. It no longer describes the separately requested conversational mode, which permits engineering explanations, optional learner code and unexecuted worked educational examples.

The proposal keeps the fixture-hint paragraph unchanged and replaces only the tutor paragraph. It distinguishes the two modes, names the conversational data sent to Gemini, and retains the boundary between generated advice and trusted verification. It does not claim every deployment has enabled conversational tutoring or that a provider request will succeed.

## Source-based checks for the reviewer

| Proposed fact | Implementation to inspect |
| --- | --- |
| Both modes use the existing signed-in, owned-session tutor API | `app/api/v1/tutoring.py`, `app/services/lesson_tutoring.py` |
| Conversation is selected explicitly with `mode: "conversation"`; the question-only contract retains guided explanations | `app/api/v1/tutoring.py`, `app/schemas/conversation_tutor.py` |
| Conversation accepts engineering questions, optional code, four teaching styles and bounded recent history | `app/schemas/conversation_tutor.py`, `app/ai/providers/conversation_tutor.py` |
| The provider receives permitted pinned lesson context and untrusted dialogue, with fresh authorization before and after its call | `app/services/conversation_tutoring.py` |
| Worked examples are allowed as advice; submitted code is not executed and the reply cannot complete a lesson | `app/ai/providers/conversation_tutor.py`, `app/schemas/conversation_tutor.py` |
| The current frontend identifies real-mode Gemini data use, keeps history in its page-session dialogue and renders replies as text | `src/components/learning/tutor/tutor-panel.tsx`, `src/lib/ai/` |
| Provider errors and deadlines produce unavailable responses without changing saved attempts/results | `app/services/conversation_tutoring.py`, `app/services/feedback_operations.py` |
| Fixture hint slots remain separate from both tutor modes | `app/api/v1/tutoring.py`, existing learning hint service/tests |

## Review and activation gates

1. A human reviewer must approve the exact proposed text and its canonical document digest. No prior approval transfers to changed text.
2. If adopted through durable administration, create a separate immutable source revision and pass the explicit parse, normalize, chunk, index, validate, review and approve gates. Set the approved validity window explicitly. Do not use `adopt_existing_review` for this changed content.
3. Publication requires a separate authorized operation over an eligible manifest. Any semantic index needs a new exact manifest-bound build and validation; the old document/vector identities cannot authorize the changed paragraph.
4. Keep the original approved `corpus.json`, historical review and digests unchanged. This proposal changes no serving permissions by itself.

No new support contact, service-level commitment, billing promise, account role or operational policy is proposed. Acceptance of this article is distinct from technical validation of its JSON shape and from live-provider acceptance testing.
