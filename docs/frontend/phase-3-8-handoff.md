# Phase 3.8 frontend handoff

Sohaib owns frontend integration. The subsequent AI-platform implementation adds
an explicit conversational mode to the existing tutor endpoint; see
[the conversational contract](open-ended-tutor-contract.md) and
[private Gemini setup](sohaib-gemini-setup.md). Question-only requests retain
their original response. New learner conversation requests contain bounded,
untrusted dialogue rather than client-selected evidence or document scope.

The current contracts are `backend/openapi.json`,
`docs/api/gemini-openapi.json` and `src/lib/api/schema.d.ts`: 31 paths and 33
operations, including seven protected knowledge-administration operations.
The 24 existing learner/health paths remain. See the
[current complete team handoff](trace-platform-handoff.md) for onboarding,
conversation, durable governance, quota semantics and deployment prerequisites.
The historical `docs/api/openapi.json` and original frontend
integration handoff are intentionally preserved historical exports.

## Existing protected calls

Both calls require an active signed-in learner account, a valid Supabase access
token in `Authorization: Bearer <access-token>`, allowed browser Origin and
`X-Trace-Client: learning-web`. Guest cookies alone do not authorize AI access.
Use the existing `aiApi.tutor` and `aiApi.support` methods in
`src/lib/api/client.ts`; they already handle configured API base URLs and auth.

```ts
import { aiApi } from "@/lib/api/client";

const help = await aiApi.tutor(sessionId, "What should I compare before predicting?");
const support = await aiApi.support("When are follow-up reviews due?");
```

`POST /api/v1/sessions/{session_id}/tutor/ask`

```json
{"question":"What should I compare before predicting?"}
```

Question: nonblank plain text, 1–400 characters. Send no evidence, attempt body,
lesson content, model ID or hidden answer. Only the session owner can call it.
Foreign and missing sessions are indistinguishable (404); unsupported/abandoned
pinned sessions or changed saved work can produce 409.

```json
{
  "status":"answered",
  "text":"Before choosing a prediction, compare the outgoing JSON with the receiving model. Which fields and object levels must the request satisfy before the route can run? Record your own prediction before changing the mapping.",
  "source":"ai",
  "interpretation_only":true,
  "can_complete_lesson":false
}
```

This question-only compatibility example is an authored allowed choice, not a promise that Gemini chooses it
for every question. Existing concept guidance remains available. New guiding
questions are filtered server-side by the owned pinned Notes/Tasks lesson and
current stage. They cannot unlock later stages. Actual run-status observations
remain separate from conceptual questions. This compatibility mode remains
finite. The explicit `mode: "conversation"` contract allows free-form
explanations, unexecuted code examples and follow-up questions, with no grading,
competence score or completion authority. The real panel's Ask, failure
discussion and explicit worked-example actions use that additive contract;
the concept button and legacy client methods retain their guided behavior.

`declined` means no approved choice answered the question. `unavailable` means
the provider/selection could not be used and has `source: "none"`. Do not replace
either with invented success. The legacy `/sessions/{session_id}/hints` contract
and its reserved hint ladder remain separate and unchanged; chat does not consume
or advance those hint slots.

`POST /api/v1/support/ask`

```json
{"question":"When are follow-up reviews due?"}
```

Question: nonblank plain text, 1–500 characters. Send only the question. Support
does not inspect learner history, execute actions or accept client-selected files.

```json
{
  "status":"answered",
  "message":"Relevant approved documentation is quoted below.",
  "references":[{
    "source_id":"progress-retrieval",
    "source_name":"Saved progress and follow-up reviews",
    "passage_id":"retrieval-one-seven-days",
    "quote":"Completing the Tasks transfer lesson schedules two review checkpoints at one and seven elapsed days after transfer completion. The journey shows upcoming, due and completed checkpoints. A due checkpoint remains available if you missed its original due time."
  }],
  "escalation":null,
  "source":"ai"
}
```

Render response-local source names, IDs and exact quoted text. There is no source
lookup URL to invent. Source version/digest receipts are internal operator
metadata linked to `X-Request-ID`; they are not added to public response objects.
After provider work, the backend checks exact source versions and current review
eligibility. Changed, expired or revoked sources return unavailable.

| Support state | UI behavior |
| --- | --- |
| `answered` | Show exact quotes and response-local attribution |
| `no_sources` | Say no relevant approved documentation was found; no citations |
| `unsupported` | Explain that available documentation does not establish an answer |
| `unavailable` | Honest temporary unavailable state; preserve the question for a manual retry |

`source: "ai"` means real provider selection; `test_fixture` remains visibly a
test fixture. `source: "unavailable"` does not imply a live answer. No approved
human escalation destination or SLA exists; `escalation` remains null.

## Loading, failures and configuration

Disable duplicate submit while pending. These read-only POSTs do not change
learning progress, but repeated requests consume route/provider allowance; do
not automatically retry them. Keep `Cache-Control: no-store` behavior. Use the
existing sanitized error envelope and `X-Request-ID` for support diagnostics.

401 requires sign-in/token refresh; 403 indicates role/origin/access rejection;
413/422 require correcting the request; 429 requires waiting rather than a retry
loop; 503/504 indicate unavailable dependencies/request timeout. HTTP 200 can
still carry a typed `declined`, `unsupported` or `unavailable` result.

Frontend configuration remains `NEXT_PUBLIC_API_BASE_URL`,
`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` and
`NEXT_PUBLIC_SITE_URL`, and `NEXT_PUBLIC_AI_MODE`. Use existing project examples for placeholders. Never
introduce `NEXT_PUBLIC_GEMINI_API_KEY` or send `GEMINI_API_KEY` to a browser.
The approved model and key configuration belong exclusively to the backend.

Local loopback is accessible only on its host machine. Sohaib needs an approved
HTTPS backend deployment before using it remotely. See
`../deployment/secure-ai-pilot-plan.md`; this phase does not deploy or expose a
development server. Semantic retrieval, generated exercise delivery, new daily
assignment systems and unrestricted tutor prose remain outside this handoff.
