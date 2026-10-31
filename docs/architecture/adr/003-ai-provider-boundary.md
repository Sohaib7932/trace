# ADR-003 — Gemini and Claude behind a bounded provider interface

Status: accepted; only the fake adapter is implemented.

## Context
Provider prose can help explain code but is not proof of execution or learning.
The product must support Gemini and Claude without leaking provider SDK types into
services, requiring keys in tests, or turning into an unrestricted chatbot.

## Decision
Define three typed operations: generate a progressive hint, explain an already
evaluated attempt, and analyse a possible misconception. Pydantic validates bounded
inputs/outputs. Inject a provider through FastAPI dependencies. Ship a deterministic
fake labelled `test_fixture`; no public hint endpoint or live-provider activation yet.

When implemented, Gemini uses official `google-genai`, Claude uses official
`anthropic`. Add the SDK with its adapter, not as an unused dependency. Select one
live provider through backend settings only; no automatic paid fallback.

## Alternatives considered
- Vendor SDK directly in routes: convenient but couples transport, lesson policy,
  costs and errors; difficult to contract-test without network access.
- LLM orchestration framework: more abstractions than three bounded operations need.
- Both live providers immediately: doubles validation and billing paths without
  helping prove the first learning loop.

## Advantages
Deterministic offline tests and vendor-neutral application schemas. No frontend keys.
Provider interpretations cannot change deterministic outcomes or verification evidence.

## Disadvantages
One internal contract needs adapting to different provider capabilities. Fake output
proves wiring/validation only, not provider quality, safety, token usage or pedagogy.

## Consequences
Future live adapters must set explicit model, timeouts, max tokens, retry limits
and output-length limits; redact unnecessary learner data; reject malformed output;
record model/prompt version and help timing. Provider errors are infrastructure
errors. Live consent, cost control and evaluation are required before activation.

## Revisit when
A tested provider capability cannot fit the small interface. Add an operation only
for a learning use case, not to mirror every vendor API.

References: [Google SDK](https://googleapis.github.io/python-genai/),
[Anthropic SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python).
