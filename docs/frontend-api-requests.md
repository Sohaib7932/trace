# Frontend API requests (for the backend)

For Soorej, from Sohaib (frontend). 2 November 2026.

The frontend now has complete UI for every feature that `frontend-api-integration.md`
marks INTERNAL ONLY or NOT IMPLEMENTED. Each one runs on labelled scripted mocks
(`NEXT_PUBLIC_AI_MODE=mock`) and switches to your API once it is published. This document
lists what the frontend needs from the backend: endpoints, rules and decisions. Shapes
are **proposals**; please change them freely and tell me. The frontend types are in
`src/lib/ai/contracts.ts` and mirror your internal `SupportResponse`,
`LessonAssistantReply` and `AtomicAssignmentReceipt` where possible.

## Product rule: real lessons need an account (frontend, 2 November 2026)

Guests now get only demos: the homepage interactive demo (sample results, nothing saved) and the
`/today` demo steps. `/learn` shows guests the lesson list with sign-in prompts, and lesson pages
show "Sign in to start this lesson". For guests the frontend makes **no** `/learners`, `/sessions`,
`/lessons` or journey request, so no new guest learners are created from the web app.

This is UI only. The backend still accepts guest cookies (`POST /learners/anonymous`). **Questions:**
should the backend also refuse new anonymous learners (and lesson sessions without a Bearer), or
keep them for other clients? Existing guest history can still be claimed after sign-in (the
claim flow is unchanged and still tested, using history created through the API).

## Summary and priorities

| Priority | Request | Why |
|---|---|---|
| **P0** | 1. Optional prediction `reasoning` (or confirm the placeholder is acceptable) | Learners are told reasoning is optional; today the frontend saves "No reason written." |
| **P0** | 2. `Cache-Control: no-store` on every response, including errors | Contract says error responses don't always carry it |
| **P0** | 3. Confirm timeout alignment (client 35s vs server 30s/10s) | Defines when the UI says "uncertain, re-read progress" |
| **P0** | 4. `GET /api/v1/lessons` with labels | Removes the hard-coded lesson registry |
| **P1** | 5. Tutor: concept explanation, ask, why-did-this-fail, worked explanation | Lesson tutor panel is built and waiting |
| **P1** | 6. Support assistant `POST /api/v1/support/ask` + corpus/escalation decisions | Trace Help is on every page |
| **P2** | 7. Interests (taxonomy, get/set) | `/today` and `/account` interest picker |
| **P2** | 8. Today's three exercises, status, completion; "daily" policy | `/today` design preview |
| **P2** | 9. Generated exercise retrieval and its verification contract | Exercise 2 on `/today` |
| **P3** | 10. AI lesson creation (custom lessons): request, status, review, verification | `/learn` has a disabled "Create a custom lesson" card; future feature |

Common to every new endpoint unless stated: base `/api/v1`, JSON, the existing
`ErrorResponse` envelope, `X-Request-ID` on every response, `Cache-Control: no-store`,
POSTs need the allowed `Origin` and `X-Trace-Client: learning-web`, auth is the same
learner principal as today (guest cookie **or** account Bearer, never a fallback from an
invalid Bearer), and IDs in paths are checked against the current learner (404 if foreign).

**Rate limits:** please send `Retry-After` (seconds) with every 429. The frontend shows
"wait a minute" today because no 429 has it.

**Streaming:** optional for every AI endpoint. If you stream, please use Server-Sent Events
(`text/event-stream`) with `event: delta` (`{"text": "..."}`) chunks and a final
`event: done` carrying the complete JSON reply below, so a non-streaming client can just
read `done`. Without streaming, return the JSON reply directly; the UI handles both.

---

## P0: the four open questions

### 1. Optional prediction reasoning
`PredictionCreate.reasoning` is required (1–2000 chars). The UI marks it optional and,
when blank, sends the fixed text `"No reason written."`; the form tells the learner, and
the locked view shows "You didn't write a reason". **Request:** allow empty/absent
`reasoning` (default `""`), or confirm the placeholder is acceptable for the learning record.

### 2. `no-store` on every status
The integration document says generated error responses don't uniformly carry
`Cache-Control: no-store`. **Request:** add it at the middleware level for all statuses
(including 401/404/413/422/429/500/503/504) on `/api/v1/*`.

### 3. Timeouts
Client: 35 s `AbortSignal.timeout`, then treated like a 504 (outcome uncertain: re-read
progress, replay the same Idempotency-Key). Server: 30 s request timeout, 10 s verification
timeout. **Question:** is 35 s right (slightly above the server's 30 s so the server's 504
normally arrives first)? Can a verify call legitimately exceed 30 s, and if so should
the client poll progress instead of waiting?

### 4. Lessons list
`GET /api/v1/lessons` (public, no key) → 200:
```json
{"lessons":[{"id":"fastapi-payload-mismatch","version":"1.0.0","title":"Follow the note: from form to database",
"concept":"Request fields","concept_sentence":"A server only accepts a request when its field names match the schema that receives it.",
"bug_type":"Field name mismatch","stack":"Python · FastAPI","duration_minutes":[5,10],"requires":null,"order":1}]}
```
Errors: 503. Unavailable → the frontend keeps `src/content/lessons.ts`. Learner status stays
in the journey (this list is catalog only).

---

## P1: Tutor (lesson-scoped help)

**Rules the frontend already follows; please enforce them server-side too.** The tutor
explains and guides. It never decides correctness or completion (`interpretation_only:
true`, `can_complete_lesson: false`). It never reveals the full fix before the worked
explanation. It never reads learner-supplied evidence: the server loads stored runs.

Shared reply (`TutorReply`):
```json
{"status":"answered","text":"FastAPI checks the request against NoteCreate before your route runs...","source":"ai","interpretation_only":true,"can_complete_lesson":false}
```
`status`: `answered | declined | unavailable`. `declined` = the question was out of scope or
asked for the answer early (the text says why). `unavailable` = provider off/over budget.

| # | Method and path (suggested) | Request | Notes |
|---|---|---|---|
| 5a | `POST /api/v1/sessions/{session_id}/tutor/explain` | `{}` | Concept for the session's current stage (server reads stage and lesson). |
| 5b | `POST /api/v1/sessions/{session_id}/tutor/ask` | `{"question":"What does extra=forbid do?"}` (1–400 chars) | Lesson-scoped free text. |
| 5c | `POST /api/v1/sessions/{session_id}/verifications/{run_id}/explanation` | `{}` | Only for a stored run with `status: failed` (409 otherwise). Uses that run's checks only. |
| 5d | `POST /api/v1/sessions/{session_id}/tutor/worked-explanation` | `{"confirm":true}` | Full fix. Server decides eligibility (see hint levels); 409 `invalid_state` if not yet allowed. |

- **Auth:** learner principal. **Guest policy (decide):** allow guests, or 401 for guests? The
  UI already has a "Sign in to ask the tutor (fixture hints still work)" state.
- **Idempotency:** a UUID `Idempotency-Key` on all four (same key + body replays the stored
  reply; avoids double spend on retries).
- **Rate limits:** per learner, e.g. 20/min and a daily cap; 429 `rate_limited` + `Retry-After`.
- **Errors:** 401, 403, 404 (foreign session/run), 409 (`invalid_state`: no prediction yet,
  run not failed, worked explanation not unlocked), 422, 429, 503 `dependency_unavailable`
  (provider down), 413.
- **Streaming:** optional (SSE as above).
- **Hint-level ownership:** the server decides the level. Today's fixture hints already
  count slots server-side (`summary.hint_request_count`); please keep that the single
  source of truth and expose `worked_explanation_available: boolean` in `ProgressResponse`
  (the frontend currently unlocks it after 3 hint requests, 2 failed runs, or completion).
- **Solution-leak policy:** 5a/5b/5c must not state the corrected mapping (`content`,
  nested `metadata.priority`); only 5d may. Should 5d's use be recorded as a learning event
  (e.g. `worked_explanation_viewed`) so history stays honest? The frontend would show it.
- **Persistence:** should tutor exchanges be stored with the session? The UI keeps them in
  memory only today.
- **Unavailable in the frontend:** shows "The tutor isn't connected yet. Fixture hints and
  the lesson evidence still work." Hints keep working (`POST /sessions/{id}/hints`).

### Tutor context the frontend sends (added with the lesson-page refinement)

The tutor is now the primary help in every lesson: a docked panel at 1280px and wider
(collapsible), a right-edge drawer at 1024-1279px, and a bottom drawer below that. It shows
a context line, e.g. "Lesson: The Nested Payload Problem. Step: Run the original request".
The adapter's `TutorContext` (`src/lib/ai/client.ts`) carries:

```json
{"lessonId":"fastapi-nested-payload-transfer","stage":"changing","sessionId":"<uuid>",
 "lessonTitle":"The Nested Payload Problem","step":"Run the original request",
 "latestRun":{"id":"<run uuid>","status":"failed"},"hintsUsed":1}
```

Only ids of **stored** evidence are sent; the server should load the run itself and ignore
anything else. `step` and `lessonTitle` are display hints, not trusted input. Requests to
confirm or change:

- **Ask:** 5b request body could accept an optional `"step"` so answers match what the
  learner sees; the server should still derive the stage from the session.
- **Why it failed:** 5c only for the latest stored run with `status: failed`; 409 otherwise.
  The frontend shows the button only in that case.
- **Hint levels:** the server owns them. The frontend reads `summary.hint_request_count` /
  `hints_delivered` for the "n of 3 used" label and never changes them from tutor output.
- **Guest access:** still undecided (see above). The UI has a guest-not-allowed state.
- **Solution leak:** unchanged: only 5d (after a confirm) may state the corrected mapping.
- **Streaming, 429 + `Retry-After`, `no-store`, error envelope:** as in the common rules.
- **History:** the frontend keeps tutor messages in memory for the page session only (they
  survive collapsing the panel or closing the drawer, not a reload).

## P1: Support assistant ("Trace Help")

`POST /api/v1/support/ask`
```json
{"question":"I can't sign in with Google","route":"/sign-in","conversation_id":null}
```
→ 200
```json
{"status":"answered","answer":"If Google sign-in is cancelled or the callback fails, start a fresh sign-in...",
"sources":[{"id":"google-sign-in","title":"Problems signing in with Google","link":"/sign-in","snippet":"If Google sign-in is cancelled..."}],
"escalation":null,"source":"ai"}
```
- `status`: `answered | unsupported | unavailable`. `unsupported` = no approved source
  matched ("I'm not sure"); `unavailable` = support is switched off (your current default).
- `sources`: 0–3, only from the approved corpus; `link` is an internal app route.
- `escalation`: `{"label":"Email Trace support","url":"mailto:... or https://..."}` or `null`.
  The UI shows "Talk to a human" **only** when this is present (or when the frontend has
  `NEXT_PUBLIC_SUPPORT_EMAIL` set).
- **Auth:** public (guests and anonymous visitors on the marketing site use it). Accept
  but don't require a Bearer. No learner data is ever retrieved.
- **Idempotency:** optional key; please accept it if you want replay protection.
- **Rate limits:** per IP/guest, e.g. 10/min; 429 + `Retry-After`.
- **Errors:** 413 (question > 500 chars), 422, 429, 503.
- **Streaming:** optional (SSE).
- **Decisions needed:** stateless vs `conversation_id`; whether questions are stored and for
  how long (the UI says "This chat isn't saved"); who owns and approves the corpus
  (`docs/support-drafts` are drafts); the escalation destination (email, form or ticket
  system); PII handling (the UI blocks text that looks like a password/key, but please
  redact on the server too).

## P2: Interests and daily exercises

- `GET /api/v1/interests` (public) → `{"interests":[{"id":"fitness","label":"Fitness tracking"}]}`
- `GET /api/v1/learners/me/interests` → `{"interest_ids":["fitness","music"]}`
- `PUT /api/v1/learners/me/interests` `{"interest_ids":[...]}` (0–5; 422 if more or unknown;
  Idempotency-Key not needed for a full replace) → same shape.
- `GET /api/v1/learners/me/today` →
```json
{"local_date":"2026-11-02","timezone":"Europe/London","server_time":"2026-11-02T09:00:00Z","maximum_new_assignments":3,
"exercises":[{"id":"...","ordinal":1,"kind":"theory","title":"...","summary":"...","lesson_id":null,"generated_exercise_id":"...","status":"available"}]}
```
- `POST /api/v1/learners/me/today/{exercise_id}/complete` `{}` + Key → `{"exercise_id":"...","status":"completed","completed_at":"..."}`.
  Only for theory items; coding items complete through verification, never this call.
- **Quota:** 409 `quota_exhausted` (or 429 with `Retry-After` until the local-day reset)
  when a fourth new assignment is requested.
- **Decisions needed (from `daily-assignment-readiness.md`):** what "daily" means (learner-local
  calendar day? which timezone source: a learner/account `timezone` field set by the browser
  or by the user?); reset time (local midnight?); does a guest get a timezone; do retries,
  hints and follow-ups stay outside the quota (the frontend assumes yes); what counts as
  "assigned" vs "started".

## P2: Generated exercises

`GET /api/v1/exercises/{generated_exercise_id}` → a `GeneratedExercise` (same public fields
as `LessonResponse` plus `change_type` and `field_choices`). Sessions, predictions,
attempts and verification should reuse the existing session endpoints (pinned version,
bounded `change_type`), so the workspace works unchanged. **Questions:** is verification
for generated exercises the same deterministic runtime (private ASGI app + fresh read)?
Are only human-approved candidates assignable? How does the frontend tell a generated
exercise from a seeded lesson in the journey (a `phase.kind`)?

## P3: AI lesson creation (custom lessons). IMPLEMENTED on `feat/custom-lesson-creation`

**Status 4 November 2026:** built end to end on branch `feat/custom-lesson-creation` (backend
endpoints, migration `0010_custom_lessons`, frontend composer, tracker and viewer). Contract:
`backend/openapi.json` and section 12 of `docs/frontend-api-integration.md`. Needs review by
the AI-backend owner before merging (it reuses the shared Gemini transport, settings class
and usage ledger through a separate bounded client; the tutor and Trace Help are unchanged).

| Earlier question | Answer in the implementation |
|---|---|
| 1. Create | `POST /api/v1/custom-lessons/requests`, 202, Idempotency-Key, account learner only |
| 2. Status | `GET .../requests/{id}`: queued, generating, ready, failed, cancelled, rejected; no estimate field (the UI shows a rough range) |
| 3. Plan review | Not implemented: no outline step. Open question below |
| 4. Cancel / retry | Cancel while queued/generating; retry = a new request |
| 5. List | `GET /api/v1/custom-lessons` |
| 6. Get a lesson | `GET /api/v1/custom-lessons/{id}` (no answer keys) + server-side answers endpoint |
| 7. Languages | `GET .../languages`; every generated lesson is `answer_key` or `practice_only`, never `server_verified` |
| 8. Verification mode | Per challenge: `answer_key` (options) or `practice_only` (explain) |
| 9. Errors | Typed codes, see section 12 |
| 10. Report a problem | No endpoint; the viewer uses `NEXT_PUBLIC_SUPPORT_EMAIL` when set |
| 11. Privacy | Prompt fields are stored with the request (needed to generate); no raw prompts/model output stored or logged; sent to Gemini under the free-tier terms. Retention: open question |

### Still open (for the AI-backend owner)

- Who reviews generated lessons, and should any review happen before learners see them?
- How long are requests, lessons and answers kept? Deletion today is per lesson only.
- Should the per-process call ceiling and daily limit move to the durable accounting tables?
- Plan review (outline approval) and a tutor for custom lessons: the tutor endpoint needs a
  Trace learning session, so the custom-lesson viewer has no tutor panel yet.
- Should "explain" answers ever be graded (by AI or rubric), or stay practice only?

### Original questions (kept for history)

1. **Create:** path, request body (the frontend sends only `{"prompt": "..."}`, the learner's
   own message; language, level and length are for the backend to infer, see
   `CustomLessonRequest`), Idempotency-Key rules, auth (account only?), and the response
   (job id + status?). Should the response echo the language/level it understood, so the
   tracker can show it?
2. **Status:** path, the exact status values (the UI is designed for queued, outlining,
   awaiting approval, generating, needs review, ready, failed, rejected, cancelled), a polling
   interval or `Retry-After`, and whether an estimated wait is available.
3. **Plan review:** does generation return an outline the learner approves (edit titles,
   remove lessons, change level)? Path and body for "approve" and for edits.
4. **Cancel and retry:** are they allowed, and in which states?
5. **List:** `GET` for the learner's lessons with status, language, level and
   `verification_mode`, for "My lessons".
6. **Get a ready lesson:** does it reuse `GET /lessons/{lesson_id}` and the existing
   session/attempt/verify endpoints, or a new viewer contract? Which challenge types exist?
7. **Supported languages:** an endpoint, or is the frontend table the source? Which
   language + framework pairs can be `server_verified` today (we assume only Python + FastAPI
   request lessons, and say so as "Expected" in the composer)?
8. **Verification mode per lesson:** confirm the values `server_verified`, `answer_key`,
   `practice_only` and that the UI may say "Checked on a real server" only for
   `server_verified`.
9. **Errors:** codes for rate limit (with retry hint), daily quota reached, content-policy
   rejection (with a safe rewrite hint), provider unavailable, not signed in.
10. **Reporting a problem** with a generated lesson: an endpoint, or a support email?
11. **Privacy:** is the prompt or pasted code stored, for how long, and is it sent to Gemini
    under free-tier data-use terms? Proposed types: `CustomLessonRequest`, `CustomLessonStatus`,
`CustomLessonSummary`, `GeneratedLesson`, `GeneratedChallenge` in `src/lib/ai/contracts.ts`.
The UI reads lessons through `src/lib/learning/lesson-source.ts` (`catalogSource`,
`generatedSource`); only `generatedSource` changes when this ships.

| # | Method and path (suggested) | Request / response | Notes |
|---|---|---|---|
| 10a | `POST /api/v1/lessons/custom` | `{"topic":"FastAPI authentication","start_level":"beginner","target_level":"intermediate","practical":true}` → 202 `CustomLessonSummary` (`status: queued`) | `Idempotency-Key` required. Topic 1-500 chars. Python/FastAPI only. |
| 10b | `GET /api/v1/lessons/custom/{id}` | → `CustomLessonSummary` | Poll; or SSE. |
| 10c | `GET /api/v1/lessons/custom` | → `{"items":[CustomLessonSummary]}` | Fills "Your lessons". Newest first, learner-scoped. |
| 10d | `GET /api/v1/lessons/{lesson_id}` | existing `LessonResponse` | Once `ready`, a custom lesson should open in the existing workspace. |

- **Async status:** `queued → generating → needs_review → ready`, or `failed` with a safe
  `failure_reason`. Only `ready` lessons can be opened.
- **Generated lesson structure:** explanations, challenges (outgoing code, schema code,
  bounded `change_type` + `field_choices`), and `verification_criteria` per challenge, so the
  existing deterministic verification can run it. No free-form learner code execution.
- **Verification of generated challenges:** the backend must run every challenge (correct
  and incorrect mapping) before `ready`; a challenge that does not verify is dropped or the
  lesson fails. `GeneratedLesson.verified` is true only after that.
- **Review/approval:** human review before learners see it? (`needs_review` exists for this.)
- **Quotas and cost caps:** per learner (e.g. 3 lessons/day), global spend cap; 429 with
  `Retry-After`; 503 when over budget.
- **Safety:** topic moderation; reject non-programming or unsafe topics with a clear 422;
  prompt-injection defences as for the RAG backend; no personal data in prompts.
- **Journey:** do custom lessons appear in `GET /learners/me/journey` (a `phase.kind`), and
  do they get follow-up checkpoints?
- **Auth:** accounts only, or guests too?

---

## Leaderboard and account (PROPOSED, nothing below exists in openapi.json)

Frontend status: `/leaderboard` and the "Your rank" card on `/account` are built against the proposed contract in `src/lib/leaderboard/contracts.ts`. The real client throws `EndpointNotAvailableError` until the endpoint exists, so the page shows "The leaderboard isn't open yet". Fictional demo data exists only behind `NEXT_PUBLIC_LEADERBOARD_DEMO=1` (labelled "Demo data") and in tests. The frontend never computes, sorts or sends a score, rank or count.

### V1 rules (from the team)
Global all-time board of all registered users. Metric: number of DISTINCT server-verified problems completed. Only verified completions count (attempts, drafts, unfinished and unverified never count). Completing the same problem again counts once. Sorted by count descending; equal counts share a rank; show rank, avatar, display name and count; highlight the signed-in user; empty state when nobody has a verified completion.

### Proposed endpoint
`GET /api/v1/leaderboard?cursor=<opaque>&limit=<1..50>`, signed-in learners only (Bearer, same as the other learner endpoints; `no-store` is NOT wanted: a short `Cache-Control: private, max-age=60` is fine).

```json
{
  "entries": [{ "rank": 1, "user_id": "opaque-stable-id", "display_name": "Mina", "avatar_id": "sage-leaf", "avatar_url": null, "verified_count": 2, "is_me": false }],
  "next_cursor": "opaque-or-null",
  "me": { "rank": 7, "verified_count": 1, "passable_with_one_more": 12 },
  "generated_at": "2026-11-04T10:00:00Z",
  "total_ranked": 143
}
```
- `me` is `null` when the learner has no verified completion. `passable_with_one_more` and `total_ranked` are optional; the UI shows the "pass N people" nudge only if the number is present.
- `user_id` is an opaque board id, not the account id. `avatar_url` (if ever used) must be HTTPS; the UI loads it with `referrerPolicy="no-referrer"` and falls back to a drawn avatar.
- Errors: the standard envelope. 401 sign in again, 429 with a retry hint (UI says "wait a minute"), 503 unavailable, 5xx with `request_id` (shown under "Support details").
- Rate limit: refetch on focus and every ~3 minutes while visible; please allow about 20 requests per minute per account.

### Open questions
1. **Ranking type:** competition (1, 1, 3) or dense (1, 1, 2)? The UI shows whatever rank the server sends and labels ties "Rank 3, tied".
2. **Stable tiebreak:** equal counts need a deterministic secondary order (for example first verification time, then board id) so cursor pages never skip or repeat a person.
3. **`me` object:** is it OK that it is returned separately from `entries` (needed when you are off the loaded page)?
4. **Privacy:** can a learner opt out of the board? Default display name for people who never set one? Where does the avatar come from (stored `avatar_id`, provider photo, none) and what is the URL allowlist? Is the display name moderated (length, profanity, impersonation)?
5. **Signed-out visitors:** may they view the board, or is it signed-in only (current frontend assumption)?
6. **What counts as one "problem":** a Trace lesson (today there are two) or a challenge inside one? Do AI-created (custom) lessons ever count? The frontend assumes never, because they are answer-key or practice-only and not server-verified.
7. **Page size, total count and freshness:** default page size (UI asks for 20), is `total_ranked` available, how stale may `generated_at` be?
8. **Avatar and display name fields:** to show other people's chosen avatars the backend needs to store `avatar_id` (the frontend currently saves it only in Supabase user metadata and localStorage) and a display name (the frontend reads the provider profile name, falling back to "Trace learner").
9. **Display-name editing and leaderboard opt-out:** not built in the UI because the contract has neither; tell us if you want them.

### Flag for the team
With only two server-verified Trace lessons, scores will be 0, 1 or 2 and most users will tie until more verified problems exist. The first screen will mostly be one large tied group; the UI handles this (highlighted rows instead of a podium when a rank has more than three people), but the board will feel flat until there are more problems.

## What the RAG backend needs (recommendation, not an implementation)

- **Corpus format:** Markdown articles with front matter: `id`, `title`, `tags`,
  `route` (internal link), `last_reviewed` (date), `owner`, `status` (draft/approved).
  Start from `docs/support-drafts/` and the frontend's demo set `src/content/support/articles.ts`.
- **Chunking:** by heading/paragraph, ~80–200 words, keep `id#chunk` ids so citations
  point at an article and a passage (matches your `SupportReference.passage_id`).
- **Retrieval:** SQLite FTS5 (BM25) first, top 5 passages, minimum score threshold;
  add embeddings later only if the evaluation set shows misses.
- **Answer only from sources:** the model may only use retrieved passages; every answer
  cites 1–3 of them; no passage → `unsupported` with "I'm not sure" (no guess).
- **"I'm not sure" threshold:** below the score threshold, or if the model's selected
  passages fail validation.
- **Prompt-injection defences:** retrieved text and learner text are data, never
  instructions (separate message roles, quoted/escaped); ignore instructions inside
  articles; strict JSON output validation; no tools; no account actions.
- **Privacy:** never retrieve learner records or account data; redact secrets/emails
  from questions before logging; decide retention.
- **Cost and rate controls:** per-IP/learner limits, max tokens, daily spend cap
  (your `TRACE_LLM_SPEND_LIMIT_MICROUSD`), cache identical questions per corpus version.
- **Evaluation set:** 30 sample questions with expected sources are in
  `src/content/support/eval-questions.ts` (28 answerable, 2 that must be "I'm not sure"; the
  frontend demo retriever passes all 30). Topics: sign-up/confirmation (3),
  sign-in/reset (3), Google (3), guest history (3), progress (2), lessons (2),
  verification (2), verification errors (2), fixture hints (2), follow-ups (2),
  daily exercises (2), local setup (1), safety (1), out of scope (2).
- **Updates:** articles change by PR with a reviewer; bump `last_reviewed`; re-run the
  evaluation set in CI; re-index on deploy.

## Frontend adapter swap checklist (when an endpoint ships)

1. Regenerate types: `npm run api:types` (from the new `backend/openapi.json`) and commit
   `src/lib/api/schema.d.ts`.
2. Add the call to `src/lib/api/client.ts` (existing `request()` helper, so headers, keys,
   timeouts and error mapping stay central).
3. In `src/lib/ai/client.ts`, replace that capability's `notAvailable(...)` body in
   `realClients` with the new call; map the response to the type in `contracts.ts`, then
   swap those hand-written types for the generated ones.
4. Set `NEXT_PUBLIC_AI_MODE=real` (build-time) for environments that have the endpoint.
5. Remove the feature's `<DemoLabel />` once it is no longer mock-driven (search for
   `DemoLabel`).
6. Update tests in `tests/components/ai-surfaces.test.tsx` and `tests/e2e/ai-surfaces.spec.ts`
   (real-mode tests against the test backend instead of the mock).
7. **Tutor:** map `TutorContext` (`lessonTitle`, `step`, `latestRun.id`, `hintsUsed`) to the
   agreed request; keep hints on `POST /sessions/{id}/hints`; check the context line and
   "Why did this fail?" still appear only after a stored failed run.
8. **Custom lessons:** in `src/lib/learning/lesson-source.ts`, give `generatedSource`
   `status: "available"` and a `list()` backed by 10c (through TanStack Query); enable the
   submit button in `src/components/learning/hub/custom-lessons.tsx` and post 10a with an
   `Idempotency-Key`; render statuses (queued, generating, needs review, ready, failed).
   Remove the "Coming soon" line. Update `tests/components/lesson-refinement.test.tsx`.

## Projects (GitHub): what the screens need that the contract does not have yet

The Projects screens (`/projects`, `/projects/connect`, `/projects/import`, `/projects/[connectionId]`,
`.../path`, `.../manage`) use only the 13 `/api/v1/projects/github/*` endpoints in
`backend/openapi.json`. Each item below is shown in the UI as an honest unavailable or manual state,
never as fake data. When an endpoint ships, replace the manual step with the call (see the file named
in each item).

1. **Latest commit for a repository.** Today a learner must paste a full 40-character commit SHA, because
   no endpoint returns the default branch's head. Request: `GET /projects/github/repositories/{connection_id}/head`
   returning `{ default_branch, commit_sha, committed_at }`. UI: `src/components/projects/project-view.tsx`
   (the "Choose the commit" card) would become a one-click "Use the latest commit" plus the manual field.
2. **Delete stored project data.** Disconnect keeps private history; nothing deletes snapshots, knowledge or
   learning paths. Request: `DELETE /projects/github/repositories/{connection_id}/data` (idempotent, returns counts
   deleted). UI: `manage-view.tsx` shows an unavailable note where a typed-confirmation delete belongs.
3. **Import status for long reads.** `POST .../ingest` is one synchronous call (it can return 504, which the UI
   treats as "unconfirmed, check state"). Request: an operation resource (`POST .../ingest` returning `202` with an
   id, `GET .../operations/{id}` with `queued | fetching | indexing | failed | ready` and a reason code) so the
   pipeline tracker can show real stages and poll. Until then the tracker shows the stage in flight on the client
   and re-reads saved results (`GET .../snapshot`, `GET .../knowledge`, `GET .../learning-path`).
4. **Outdated detection.** There is no way to know a pinned commit is behind the default branch (needs item 1).
5. **Plan review and approval; lessons list; answers and progress.** The backend produces one learning path per
   commit (`project-learning-v1`: title, steps with a question and cited sources). There is no plan to approve, no
   per-step progress, and `can_complete_lesson` is always `false`. The UI therefore shows the path as practice only:
   no completion, nothing on the leaderboard. Request, if wanted: step-level progress (`POST .../learning-path/{id}/steps/{n}/response`)
   and a completion rule the server owns.
6. **Languages.** `RepositoryView` has no language or size. Language chips come from the file extensions in the
   read catalog (only after a repository is read). Request: `language` and `size_kb` on `RepositoryView`.
7. **Batch connect.** Repositories are connected one request at a time (the server allows one active GitHub request
   per account). The picker caps one batch at 10 (`MAX_SELECTION` in `src/lib/projects/format.ts`). Request: a
   documented per-request limit, or a batch endpoint.
8. **Idempotency.** None of these endpoints takes an `Idempotency-Key`. Repeats are safe by design (connect,
   ingest and sync are keyed by repository and commit), so the UI sends none.
