# Conversational tutor contract

This additive contract extends the existing protected endpoint:
`POST /api/v1/sessions/{session_id}/tutor/ask`. Question-only requests retain the
existing finite-guidance response. Clients opt into natural engineering advice
using `mode: "conversation"`; no duplicate endpoint or grading route is added.

```json
{
  "mode":"conversation",
  "question":"Why does an async function return a coroutine?",
  "style":"direct",
  "code":"async def example():\n    return 1",
  "history":[
    {"role":"user","text":"What does await do?"},
    {"role":"assistant","text":"It can suspend the current coroutine."}
  ]
}
```

Styles: `adaptive`, `socratic`, `direct`, `worked_example`. A worked example is an
explicit learner request for an educational example; it does not run code or
complete a lesson. Question maximum: 2000 characters; code maximum: 6000;
history maximum: six user/assistant messages of 1600 characters each. The entire
validated request is additionally limited to 10000 UTF-8 bytes. System/tool roles,
credentials, private email identifiers, extra properties and client-supplied
runtime/ownership/evaluator claims are rejected. HTTP ingress remains bounded.

The response adds fixed conversational provenance:

```json
{
  "mode":"conversation",
  "status":"answered",
  "text":"Calling an async function creates a coroutine object. Awaiting it lets the event loop drive its execution. This is an explanation, not an executed test result.",
  "source":"ai",
  "interpretation_only":true,
  "can_complete_lesson":false,
  "execution_status":"not_executed",
  "history_scope":"client_page_session"
}
```

`answered`/`declined` may have real `ai` or explicit `test_fixture` provenance.
`unavailable` always has `source: "none"`. The provider supplies only bounded
status/text; trusted server code supplies authority/provenance flags. No tools,
execution, database access, hidden tests, private evaluator or answer-key data
are provided to the model. Free-form advice is not verification evidence.

Authentication, active learner role, session ownership, exact pinned lesson,
fresh post-provider authorization, no-store, deadlines and admission controls
remain mandatory. Trusted context comes from the existing owned capture. It
includes the current stage and observed latest saved verification status where
known; detailed check payloads are not supplied. Missing evidence stays unknown.

History is bounded page-session dialogue, not a server-authenticated event log.
The server treats history and code as untrusted, never as evidence that a task
passed. The frontend retains at most twenty entries in component memory, clears
them when the account or owned session changes, and sends only the bounded recent exchange. No server
conversation persistence or new permanent retention policy is introduced.

Render answers as escaped plain text, including code fences. Do not use raw HTML
insertion. Show an unexecuted-advice label, actual source provenance, loading and
explicit unavailable states. Manual cancellation stops waiting; actual provider
cleanup retains its permit until it ends. Do not automatically replay an AI POST
after token refresh, network failure or timeout. A learner may retry explicitly.

The real adapter can now implement concept, ask, failure discussion and worked
example actions through this contract. Existing deterministic hint-slot APIs and
progress/verification behavior remain unchanged. Generated OpenAPI and TypeScript
types are the contract authority; this document describes their intended use.
