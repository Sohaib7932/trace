# Support RAG local integration acceptance

Date: 3 November 2026. Repository: `Sohaib7932/trace`.

## Scope and result

**IMPLEMENTED AND VERIFIED on the accessible local checkout:** real signed-in
support answered with an exact approved quotation; the conversational tutor
separately answered through Gemini. An unsupported support question abstained,
and an unauthenticated support request returned HTTP 401.

This is evidence from Soorej's Windows checkout, not remote access to Sohaib's
computer. Sohaib must repeat the commands and acceptance sequence below in his
own clone. His original response alone cannot establish his process environment
or distinguish a provider failure from an unpublished SQL archive.

No credentials, bearer tokens, cookies, account identifiers, private question
history or raw provider errors are recorded here. Only synthetic/public
questions were submitted for this acceptance.

## Exact findings

1. The private Gemini credential was present in the supported
   `backend/.env.gemini` location. Frontend real mode, matching Supabase project,
   local service origins and CORS configuration passed the safe preflight.
   A preserved nested duplicate credential-file location was detected; it is
   not the supported launcher path and was neither displayed nor modified.
2. Neither local server was initially running. The approved launcher started
   the actual application in `gemini_free`, `memory` accounting, `lexical`
   retrieval and `reviewed_file` knowledge mode. Readiness returned HTTP 200.
3. **The reproduced unavailable response failed after retrieval, during Gemini
   execution.** The instrumented request found three eligible passages, invoked
   the provider, then reported `provider/timeout`; it returned HTTP 200 with
   `status: unavailable` and no references. This was not a missing-key diagnosis
   and was not caused by the inactive empty SQL archive.
4. A separate content-handoff defect was established: lexical ranking uses
   reviewed article titles and passage text, but the model received only passage
   IDs and text. For "How do follow-ups work?", the matching article title
   supplied relevant vocabulary that was absent from the passage text. A real
   selection abstained despite retrieval including the relevant article.
   The adapter now supplies the validated public title as untrusted reference
   data. It still cannot generate quotations, approve sources or invent IDs.
5. The Help UI retained its unavailable panel after a later successful response.
   A regression test failed before the correction and passed after the one-line
   state-recovery fix.
6. The old operator diagnostic always reported SQL knowledge state, even when
   development used the reviewed file package. It now explicitly distinguishes
   the configured source from the SQL archive and labels its configuration as
   belonging to the diagnostic process, not an already-running server.

Provider latency remains an external variable. No timeout, rate limit, retry,
paid-budget, model or concurrency policy was loosened to obtain success. One
isolated diagnostic completion also reported `invalid_response`; subsequent
instrumentation confirmed a parsed response, matching approved model and valid
metadata, followed by an exact sourced answer. The isolated error's internal
cause was not established and is not attributed to credentials or invented
metadata incompatibility.

## Configuration and knowledge state

| Check | Observed result |
| --- | --- |
| Frontend configuration | Real mode; public auth configuration valid; project/origins match |
| Credential | Available and validly loaded; value never displayed |
| Actual backend startup | `gemini_free`; `memory`; `lexical`; `reviewed_file` |
| SQL migration | `0009_durable_ai_controls`, current |
| SQLite integrity | `ok`; zero foreign-key violations |
| Active reviewed package | 9 sources, 19 passages, valid digests, no eligibility issues |
| Package review | Existing approval; expires 2 December 2026 at 15:34:07 UTC |
| SQL archive | 0 sources, revisions, events, manifests, publications, indexes and receipts |
| SQL archive snapshot | Unavailable, `missing_review`; inactive in this development profile |
| Embeddings / semantic retrieval | Disabled / not activated |

No real database migration, archive import, source approval, publication,
expiration change, revocation or administrator grant was performed. Existing
learner data and environment files were preserved. Normal signed-in application
requests used the existing authentication and ownership rules.

Production or durable-accounting mode selects the SQL archive and must fail
closed when no eligible publication exists. The working reviewed-file
development path does not establish SQL production readiness. An answer's
structured provenance log is also distinct from a persisted SQL release receipt;
this memory-mode acceptance created no durable release receipt.

## Corrections

| Files | Change |
| --- | --- |
| `backend/app/ai/providers/bounded_support.py` | Include validated public source titles in bounded untrusted reference data; preserve strict selected-ID validation |
| `backend/app/ai/support_diagnostics.py` | New finite, independently validated stage/runtime observations; no content or identity fields |
| `backend/app/ai/client.py` | Optional exception-safe request-local callback immediately before transport invocation |
| `backend/app/services/support.py` | Observe eligibility, retrieval, provider, citation and source-revalidation exits without changing public responses |
| `backend/app/api/dependencies.py` | Bind observers to the current HTTP request and existing correlation ID |
| `backend/app/api/v1/support.py` | Observe durable release authorization outcomes while retaining fresh authorization |
| `backend/app/main.py` | Emit actual startup mode/source state without probing Gemini |
| `backend/app/core/logging.py` | Independently allowlist categorical diagnostics before JSON serialization |
| `backend/scripts/platform_status.py` | Distinguish configured source / archive; aggregate lifecycle state; add explicit offline launcher-profile flags |
| `src/components/support/trace-help.tsx` | Clear stale unavailable state after a later available response |
| `backend/tests/unit/test_support_diagnostics.py` | New privacy, failure-stage, concurrency and observer-isolation tests |
| `backend/tests/unit/test_support.py` | Reviewed-title context and malicious-title rejection tests; exact quotation preservation |
| `backend/tests/integration/test_live_ai_http.py` | Assert exact approved title and strict public reference-data keys |
| `backend/tests/integration/test_platform_status.py` | Source-mode, read-only, lifecycle, profile and privacy regressions |
| `backend/tests/integration/test_support_archive_delivery.py` | Actual startup configuration diagnostic tests |
| `tests/components/ai-surfaces.test.tsx` | Real-adapter unavailable-to-answered recovery regression with exact citations |
| `docs/frontend/sohaib-gemini-setup.md` | Source-mode diagnostics and explicit authorized SQL publication procedure |
| This report | Reproducible acceptance, evidence and remaining limits |

Public HTTP schemas, routes, deterministic learner verification, lesson hashes,
migrations, approved corpus contents and private configuration files were not
changed. No arbitrary retrieval paths or model-selected files were introduced.

## Genuine browser and provider evidence

The learner signed in privately through the existing real Supabase project.
Tests did not substitute an authentication fixture for this browser session.

| Acceptance | Evidence and classification |
| --- | --- |
| Gemini configuration | Approved launcher offline preflight passed. **IMPLEMENTED AND VERIFIED** |
| Backend readiness | `GET /api/v1/health/ready` returned 200. **IMPLEMENTED AND VERIFIED** |
| Supported public question | Real browser `POST /api/v1/support/ask` returned 200, `answered`, `source: ai`, after 3915.18 ms. **IMPLEMENTED AND VERIFIED** |
| Original starter question | After the title-context correction, "How do follow-ups work?" also returned 200 / `answered` / `source: ai` through the real browser in 1958.23 ms. **IMPLEMENTED AND VERIFIED** |
| Source integrity | Same request logged retrieval of 3 passages, actual transport invocation, provider success, fresh source verification and answer release. Exact approved quote displayed in Help. **IMPLEMENTED AND VERIFIED** |
| Unsupported question | "What is the weather forecast for Jupiter?" returned 200 / `no_sources`; zero eligible passages, no provider invocation and no references. **IMPLEMENTED AND VERIFIED** |
| Unauthorized request | No bearer credential: 401 / `unauthenticated`, `Cache-Control: no-store`. **IMPLEMENTED AND VERIFIED** |
| Conversational tutor | Separate real browser `POST /api/v1/sessions/{session_id}/tutor/ask`: 200 / `answered`, `source: ai`, 4886.63 ms. **IMPLEMENTED AND VERIFIED** |
| Expired/revoked sources | Disposable-database and controlled-clock regressions withhold quotes, including revocation during provider work. **IMPLEMENTED AND VERIFIED in deterministic tests**, not by altering real approved sources |
| Disabled/provider failure/timeout | Deterministic tests preserve honest unavailable responses; a real timeout was also reproduced. **IMPLEMENTED AND VERIFIED** |
| SQL published-corpus delivery | Disposable-database tests cover publication and persisted release authorization. **IMPLEMENTED AND VERIFIED in tests**; this real database has no publication |
| Sohaib's separate computer | Requires his own startup/runtime diagnostics and authenticated walkthrough. **BLOCKED BY EXTERNAL DEPENDENCY: no access to that machine** |
| Production SQL publication | Requires an explicitly authorized existing administrator and publication operation. **IMPLEMENTED, NOT LIVE-VERIFIED** |

Public supported request:

```json
{"question":"When are retrieval reviews due after transfer completion?"}
```

Actual selected reference:

```json
{
  "source_id": "progress-retrieval",
  "source_name": "Saved progress and follow-up reviews",
  "passage_id": "retrieval-one-seven-days",
  "quote": "Completing the Tasks transfer lesson schedules two review checkpoints at one and seven elapsed days after transfer completion. The journey shows upcoming, due and completed checkpoints. A due checkpoint remains available if you missed its original due time."
}
```

The server's source-version receipt pinned revision `1.0.0`, the authored
chunker, manifest, document, passage and chunk digests. The model selected the
passage ID; trusted server code supplied the exact quoted text and revalidated
its eligibility after the provider call. Neither the model nor the browser
supplied a fabricated citation. Screenshots of the actual support source and
separate tutor response were inspected during acceptance; mocked screenshots
were not used as evidence.

Nine bounded real-provider attempts were made across diagnosis and acceptance,
including initial failures, isolated public-content probes and the final two
browser successes and the original starter-question check. One probe's diagnostic
serialization failed after its provider operation; its provider result is not
counted as successful evidence.
There were no automatic retries, paid fallbacks, embedding requests or billing
changes. The existing approved unbilled-project configuration was retained;
this is not an independent Google Billing audit.

## Validation commands and results

Commands ran from the repository root unless otherwise indicated. Every
provider-backed request above was separate from deterministic regression tests.

```text
git status --short
git branch --show-current
git log -3 --oneline
git remote -v
git fetch origin main
uv run --directory backend --locked --no-sync python -m scripts.ai_setup_check --check-backend
uv run --directory backend --locked --no-sync python -m scripts.run_gemini --confirm-free-tier-project --check
uv run --directory backend --locked --no-sync python -m scripts.platform_status
uv run --directory backend --locked --no-sync python -m scripts.platform_status --gemini-profile --confirm-free-tier-project
npm test
npm exec -- vitest run --maxWorkers=1
npm run typecheck
npm run lint
```

Final directly affected backend command, from `backend/`:

```text
uv run --locked --no-sync pytest -q --no-cov tests/unit/test_support.py tests/unit/test_support_diagnostics.py tests/unit/test_support_corpus.py tests/unit/test_support_receipts.py tests/unit/test_gemini_transport.py tests/integration/test_platform_status.py tests/integration/test_live_ai_http.py tests/integration/test_versioned_support_http.py tests/integration/test_support_archive_delivery.py tests/integration/test_support_release_authorization.py tests/integration/test_conversation_tutor_http.py tests/integration/test_knowledge_admin_http.py
uv run --locked --no-sync ruff check app scripts tests
uv run --locked --no-sync ruff format --check app scripts tests
uv run --locked --no-sync mypy
```

- Final affected backend suite: **278 passed in 193.57 seconds**, on the final
  implementation. It includes the exact transport contract, source freshness,
  release authorization, disabled/failure/timeout behavior, diagnostics,
  knowledge administration and conversational-tutor regressions.
- Additional focused runs passed: 144 support/diagnostic/HTTP tests after title
  correction; 20 platform-status tests; 93 diagnostic/archive-delivery regressions.
  These runs overlap and must not be added into a unique-test total.
- Frontend: initial parallel full run had 144 passes and two existing 5-second
  test timeouts during concurrent development compilation. Unchanged full suite
  rerun with one worker passed **146/146**, retaining original assertions and
  timeouts. The new recovery test was also verified to fail before the fix.
- Frontend TypeScript and ESLint passed.
- Backend Ruff passed; **329 files** already formatted; mypy passed across
  **211 source files**.
- Actual application OpenAPI equals the saved contract exactly: **31 paths /
  33 operations**. No schema export or generated frontend type change is needed.
- A full backend sweep was started and stopped before completion while still
  progressing, to finish the directly affected regression suite for urgent
  acceptance. No full-suite pass or refreshed global coverage is claimed.
  Coverage thresholds and test configuration were not changed.
- No additional build or isolated Playwright suite was run in this task. The
  affected frontend passed unit/static checks and real signed-in browser
  acceptance against the running development application.

## Start the working application on Sohaib's machine

From his own repository root, privately configure the existing templates at
`.env.local`, `backend/.env` and `backend/.env.gemini`. Never copy another
developer's real credential files or put Gemini credentials into frontend
variables. Verify `NEXT_PUBLIC_AI_MODE=real` and matching shared Supabase/local
origins. Do not overwrite existing files.

```powershell
uv run --directory backend --locked --no-sync python -m scripts.run_gemini --confirm-free-tier-project --check
uv run --directory backend --locked --no-sync python -m scripts.platform_status --gemini-profile --confirm-free-tier-project
./scripts/run-gemini-backend.ps1 -ConfirmFreeTierProject
```

In another terminal at that same root:

```powershell
npm run dev
```

Open `http://localhost:3000`. Confirm readiness at
`http://localhost:8000/api/v1/health/ready`. Use the same local hostnames as his
private frontend/backend/CORS configuration. Stop obsolete processes only from
their owning terminals; do not kill unrelated processes or reset a database to
free a port. A plain Uvicorn launch does not activate Gemini simply because the
key file exists. The approved launcher preserves stricter existing limits.

For durable/production mode, follow the exact two-step authenticated import and
publication procedure in [the setup guide](../frontend/sohaib-gemini-setup.md).
Do not auto-grant admin, auto-publish, renew a review or substitute the bundled
file when the active SQL archive is unavailable. Obtain explicit administrator
authorization before the real operations.

For the recording: sign in; open an owned lesson; use Help for the supported
review question above; show the exact source; ask the unsupported Jupiter
question; open the separate Lesson tutor; ask the public FastAPI question.
Confirm genuine server provenance and the absence of demo labels. A timeout or
unavailable result must remain visible rather than being edited into success.

## Preservation and limits

At acceptance, the working branch was `codex/trace-ai-platform-completion`, HEAD `4ea54dc`.
Fetched `origin/main` is `6181acf`, the merge of PR #21; application content
matched before these repairs. No branch switch, stash, reset, clean, staging,
commit, push or merge was performed during that acceptance task. The existing modified and four untracked
shared log files remain preserved. No hooks were changed or history fabricated.

This is a local development acceptance, not a production-readiness claim.
Unreviewed corpus updates, real SQL publication, production authentication
dashboard acceptance, semantic-retrieval activation and public deployment
remain separate gates. There is no approved human escalation destination.
