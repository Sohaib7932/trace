# Phase 3.8A provider readiness

Status: implemented and tested offline. This report does not assert new live
Gemini acceptance, deployment readiness or distributed billing enforcement. The
Phase 3.7 live acceptance remains historical evidence. No new public endpoint or
learner API contract is introduced here.

## Architecture and changes

The existing `AIResources` owns one `BoundedAIClient`, shared by generation,
lesson tutoring and customer support. Those responsibilities remain separate.
The approved provider remains the official Google GenAI SDK with the exact
`gemini-3.5-flash-lite` model. Free-project confirmation, a zero paid budget,
zero application retries, one SDK attempt and no provider/model fallback remain
mandatory. This work neither selects another model nor installs another SDK.

`backend/app/ai/providers/gemini.py` keeps the synchronous `AITransport.complete`
interface used by existing services. Internally it owns one event-loop thread,
one SDK client and one HTTPX asynchronous client. The SDK's explicit
`httpx_async_client` option selects the asynchronous HTTPX path. No request
creates a new client or event loop. The only permitted wire operation remains
POST to the pinned HTTPS Gemini model endpoint; redirects, proxies, tools,
function calling and executable content remain disabled.

The source inspection behind this decision checked the installed SDK's
`BaseApiClient._async_request_once`/`AsyncClient.aclose`, HTTPcore's asynchronous
connection-pool cancellation cleanup and its AnyIO network streams. No private
SDK transport internals are patched by the implementation.

## Deadline and cancellation guarantees

The prior synchronous transport reused a per-read timeout and checked elapsed
time only after return. Progressing response bodies could therefore outlive
the intended attempt budget.

An `asyncio.timeout_at` scope now covers queueing and the actual asynchronous
SDK attempt, including connection/write/read waits and a dripping body. An
expired queued attempt is rejected before SDK/HTTP work. The synchronous caller
waits for the real coroutine to finalize, including stream cleanup. It does not
cancel a concurrent Future and prematurely release the shared admission permit.
Late output is still rejected by the shared client. The byte-stream wrapper
closes its source in `finally`.

This is cooperative asynchronous I/O cancellation, not process isolation. It
cannot preempt CPU-bound code, an event loop that cannot run, a custom transport
that suppresses cancellation, or underlying operating-system resolver work.
Bounded input/response sizes reduce parsing work but do not establish an
arbitrary hard process deadline. Diagnostics explicitly retain
`absolute_deadline_enforced=false`; the native Gemini transport separately
reports `network_deadline_enforced=true`. An injected transport does not acquire
that claim automatically.

## Effective limits

| Setting | Default | Approved free-profile ceiling/meaning |
| --- | ---: | --- |
| `TRACE_LLM_MAX_REQUEST_BYTES` | 32768 | 65536, policy + JSON data + output schema |
| `TRACE_LLM_MAX_INPUT_TOKENS` | 16384 | 65536; conservative UTF-8 byte admission, not a tokenizer |
| `TRACE_LLM_MAX_RESPONSE_BYTES` | 16384 | 65536, returned text checked independently |
| `TRACE_LLM_MAX_OUTPUT_TOKENS` | 4096 | 4096, including supplied thought-token usage |
| `TRACE_LLM_CONNECT_TIMEOUT_SECONDS` | 3 | 10, also clamped to remaining call budget |
| `TRACE_LLM_RESPONSE_TIMEOUT_SECONDS` | 10 | 20, absolute async attempt budget and per-I/O bound |
| `TRACE_LLM_TOTAL_TIMEOUT_SECONDS` | 20 | 60, shared-client overall deadline/late-output rejection |
| `TRACE_LLM_MAX_IN_FLIGHT` | 4 | 4, common admission across capabilities |
| `TRACE_LLM_REQUESTS_PER_MINUTE` | 10 | 60 per subject/capability in this client |
| `TRACE_LLM_MAX_SUBJECTS` | 1000 | 10000 tracked rate-window keys |
| `TRACE_LLM_MAX_LIVE_REQUESTS_PER_PROCESS` | 20 | 100 attempts; retained client counter, not a Google quota |
| `TRACE_LLM_MAX_RETRIES` | 0 | Exactly zero in free mode |
| `TRACE_LLM_SPEND_LIMIT_MICROUSD` | 0 | Exactly zero in free mode |
| `TRACE_LLM_MAX_COST_PER_ATTEMPT_MICROUSD` | 0 | Exactly zero in free mode |

The transport additionally caps the entire wire body at 131072 bytes and
requests identity encoding. A nonidentity Content-Encoding is rejected before
HTTPX can inflate a compressed response beyond the wire-byte bound. Free-mode
configuration above the approved output/response/concurrency profile fails
validation instead of being silently clamped. Native returned model metadata
must match the approved model; missing live model metadata also fails closed.

These counters and limits belong to the shared application client. Multiple
worker processes, multiple client instances and restarts do not share them.
They are not a project-wide spending lock. Free Tier/no-billing status remains
an operator attestation rather than a Google Billing measurement.

## Accounting and safe errors

Supplied usage, model and response identifiers are extracted before interpreting
finish reasons. No-candidate refusals, safety refusals, MAX_TOKENS truncations
and typed content rejections preserve valid supplied accounting metadata.
Rejected text cannot escape through the error envelope. Missing token fields
remain unknown and increment `missing_usage_count`; they are not fabricated as
measured zeroes. A malformed/unreadable response can still have unknown usage.

Connection/read/write infrastructure and remote-protocol failures now map to
the existing sanitized `transient_error` code. Timeouts, authentication,
rate-limit and request errors retain their existing safe classifications.
Free mode never retries these errors. Raw exception text, headers, prompt
content and credentials are never added to these diagnostics.

## Admission and shutdown

`BoundedAIClient` admits at most four simultaneous free-provider attempts across
tutor, support and generation. Existing account/route limits remain in force.
Saturation makes no transport call and consumes no live attempt. A permit is
retained until actual transport completion/cancellation cleanup.

`FeedbackOperations.wait_for_idle` tracks both service workers and provider
workers, including work abandoned by an HTTP cancellation. App shutdown stops
admission for all operation groups and the AI client, then drains actual leases
before closing AI and disposing an owned database. Waiting runs off the app
event loop and is shielded from lifespan cancellation.

The normal shutdown grace period is 30 seconds. If a cancellation-resistant
implementation outlives it, a constant sanitized warning is emitted and resource
ownership is retained in a deferred cleanup worker until actual completion.
The database is not destroyed under final authorization/readback. This path
does not claim to kill an arbitrary Python thread; a permanently stuck custom
operation can retain resources until process termination. Provider async
resource cleanup has a five-second cooperative deadline.

## Internal diagnostics

`BoundedAIClient.diagnostics_snapshot()` returns frozen internal aggregate data:
version, mode, configured/disabled/closed state, approved profile identifier,
enabled capabilities, in-flight count/limit, attempt count, allowlisted outcome
counters, deadline scope and cleanup-failure flag. It contains no learner or
subject identity, request/response identifiers, raw errors, prompts, submitted
code, provider credentials or private lesson data. `usage_snapshot()` remains
the existing aggregate accounting interface.

A configured client is not a live availability check. Snapshots make no network
request and explicitly report `live_availability_verified=false`. No public
diagnostic endpoint or automatic paid/live probe was added.

## Configuration and private setup

Existing activation names remain `TRACE_LLM_MODE`, `TRACE_LLM_PROVIDER_ID`,
`TRACE_LLM_GENERATION_MODEL_ID`, `TRACE_LLM_CONVERSATIONAL_MODEL_ID`,
`TRACE_LLM_CREDENTIAL_ENV_VAR` and `TRACE_LLM_FREE_TIER_PROJECT_CONFIRMED`.
The server-only credential name remains `GEMINI_API_KEY`. Existing private
configuration files are unchanged. Never place the credential in frontend
variables, request bodies, logs or Git. `TRACE_LLM_MAX_IN_FLIGHT` is the new
optional concurrency setting and defaults to four.

## Verification evidence

All provider tests used an explicit synthetic key and fake HTTP transport.
External sockets were disabled. Database integration fixtures used disposable
databases; no local development database or migration was changed.

- Initial combined focused gate: 196 passed in 95.59 seconds.
- Expanded focused gate including the trusted Gemini candidate pipeline:
  207 passed in 78.55 seconds.
- New hardening cases plus authenticated tutor/support HTTP compatibility:
  64 passed in 27.57 seconds (including 38 existing HTTP cases).
- Scoped Ruff passed; scoped mypy passed for six source files.
- Gate after the last constructor-safety case: 98 passed
  in 35.78 seconds across provider hardening, Gemini transport, application
  lifecycle and shutdown tests.
- After preserving already-received metadata through late timeout delivery:
  28 provider-hardening tests passed in 11.03 seconds; the final deterministic
  exact-branch regression passed independently in 1.18 seconds.
- Final scoped Ruff passed, formatting passed for nine files and mypy passed
  for six source files after the final accounting correction.

The new cases cover refusal/truncation/invalid-content accounting, missing model
metadata, effective profile rejection, cross-capability admission, diagnostics
privacy, progressing-body cancellation, retained permits during cleanup,
constructor failure, stopped loops, expired queued work, compressed responses,
and database preservation through normal/deferred shutdown. The unchanged
OpenAPI export comparison passed in the lifecycle tests.

Full backend coverage/regression, frontend/browser checks and any new controlled
live acceptance belong to the final milestone report. They are not inferred
from these focused offline results.
