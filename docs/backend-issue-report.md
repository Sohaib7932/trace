# Custom lessons: backend gaps for the full learning loop

Status: open · Frontend: `feat/custom-lesson-loop` · Contract checked: `backend/openapi.json` (custom-lesson paths and schemas below)

AI-created lessons now run as a **Read → Predict → Change → Verify** loop in the UI, using only the real
endpoints. The answer check is real (server-side answer key). Some parts of the loop still have no
backend contract, so the UI keeps them in the learner's browser or builds them from lesson data.
Nothing below asks to change existing endpoints: every proposal is additive.

## What the contract provides today

| Loop step | In the contract | Where |
|---|---|---|
| Read (explanation, code) | Yes | `CustomLessonView.sections`, `ChallengeView.code`, `prompt` |
| Predict (choices) | Partial: options yes, no prediction record | `ChallengeView.options` |
| Change (in-code edit) | No edit data | no field |
| Verify (answer-key check) | Yes | `POST /custom-lessons/{id}/challenges/{cid}/answers` → `AnswerResult` |
| Revise (numbered attempts, history) | Partial: count only | `ChallengeView.attempts`, `AnswerResult.attempts` |
| Hints (3 slots) | Partial: text yes, no accounting | `ChallengeView.hints` (all three sent up front) |
| Completion | Yes, derived | `answered_correctly`, `completed_challenges` |
| Tutor | No | tutor endpoint only accepts Trace sessions (`/sessions/{id}/tutor/ask`) |

## Gaps

### 1. Prediction record (immutable)
- **Missing:** a way to save the learner's prediction before checking, and read it back.
- **Evidence:** `ChallengeView` has no prediction field; no prediction endpoint under `/api/v1/custom-lessons`.
- **UI meanwhile:** the prediction is locked in the UI and kept in this browser per account (`localStorage`). It doesn't follow the learner to another device.
- **Proposal:** `POST /custom-lessons/{id}/challenges/{cid}/prediction` (Idempotency-Key; `{selected_option?, text?, reasoning?}`; 409 `prediction_locked` on a second, different prediction). Add `prediction: {selected_option, text, reasoning, created_at} | null` to `ChallengeView`.

### 2. Edit data for the Change step
- **Missing:** which line is meant to change, the allowed values, and the rendered edited code.
- **Evidence:** `ChallengeView` has `code` only; the generator schema (`OUTPUT_SCHEMA` in `services/custom_lesson_generation.py`) has no edit fields.
- **UI meanwhile:** the learner can rewrite any line in the code window (shown as a diff, never sent or run). The answer that is checked is the option they choose.
- **Proposal:** per challenge `edit: {line: int, token: str, options: [str], rendered: [str]} | null` (no key), and server-side `edit_correct`. Generator validates `token` is in `line` and Python parses with the correct option (parse only).

### 3. Expected result per option
- **Missing:** what happens for each option (so Verify can show "what the lesson says happens" for the learner's choice).
- **Evidence:** `AnswerResult` returns `correct` and one `explanation` (for the right answer) only.
- **UI meanwhile:** shows matched / didn't match; the explanation is held back until the learner asks or gets it right.
- **Proposal:** stored `outcomes: [{result, feedback}]` per option; `AnswerResult.outcome: {result, feedback}` for the **chosen** option only.

### 4. Attempt history
- **Missing:** per-attempt details (number, selected option, correct, time).
- **Evidence:** `ChallengeView.attempts` and `AnswerResult.attempts` are counts.
- **UI meanwhile:** details of attempts made on this device are kept locally; earlier ones show as "N earlier attempts on another device".
- **Proposal:** `ChallengeView.attempt_history: [{number, selected_option, correct, created_at}]`; `AnswerResult.number` and `AnswerResult.selected_option`.

### 5. Hint accounting
- **Missing:** server-side hint slots.
- **Evidence:** all hints arrive in `ChallengeView.hints`; nothing records use.
- **UI meanwhile:** reveals one hint at a time and counts locally (3 slots).
- **Proposal:** `POST /custom-lessons/{id}/challenges/{cid}/hints` (Idempotency-Key) returning the next hint; `ChallengeView.hints_used: int` and only the delivered hints in `hints`.

### 6. Tutor for custom lessons
- **Missing:** a tutor endpoint that accepts an owned custom lesson.
- **Evidence:** only `POST /api/v1/sessions/{session_id}/tutor/ask` exists, scoped to Trace lesson sessions.
- **UI meanwhile:** the tutor drawer works from the lesson's own material (explain the concept, hints, "why it didn't match" guidance). Free-text questions show labelled demo replies only in demo mode.
- **Proposal:** `POST /api/v1/custom-lessons/{id}/tutor/ask` with the same body and reply as the conversation tutor (`TutorConversationCreate` → `ConversationTutorReply`), behind the existing tutor middleware and rate limits. Context: lesson text, code, current step, the learner's prediction and attempts. Never the answer key, outcomes, unearned hints or explanation.

## Message for the backend owner

> Hi! Custom lessons now run as a Read → Predict → Change → Verify loop in the frontend, using the existing answer endpoint (thanks, the answer-key check works well). To make the loop complete and keep it on the server instead of the browser, could we add, all additive: (1) a locked prediction per challenge, (2) edit data per challenge (line, token, allowed values), (3) the outcome for the chosen option in `AnswerResult`, (4) attempt history, (5) a hint endpoint with accounting, and (6) a tutor endpoint for custom lessons that never sees the answer key. Details, evidence and proposed fields are in `docs/backend-issue-report.md`. Happy to adjust the shapes to fit your design.
