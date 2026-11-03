# Phase 3.8 implementation and validation

Baseline: merged PR #17, `b117773eb26c07914196ccf5d126e01f8bc182f0`.
Implementation branch: `codex/phase-3-8-llm-rag-infrastructure`.
Evidence date: 3 November 2026. No merge or deployment is authorized here.

## Capability status

| Scope | Implemented | Evidence / remaining boundary |
| --- | --- | --- |
| Provider hardening | Async cancellable network I/O behind the existing sync port; shared admission; safe failure/usage metadata; validated free profile; diagnostics; shutdown drain | Offline regression and two real Gemini service calls. Not hard CPU/process cancellation or distributed billing enforcement |
| RAG evaluation | Versioned 94-case dataset, corpus/time/digest pins, passage-level ranking and deterministic oracle/adversarial metrics | Reproducible offline reports; engineering reference labels await independent review; oracle scores are not Gemini semantic scores |
| Hybrid decision | Existing lexical port/fallback retained; fixed binary-BM25 candidate evaluated offline | Candidate regressed heldout recall; not activated. No embeddings/provider/vector database selected |
| Knowledge governance | Immutable eligible source/chunk manifests, exact reconstruction, revision/freshness/revocation fences, safe release receipts | Historical durable archive, receipt retention and document-management workflow remain proposed |
| Contextual tutor | Pinned lesson/hash/stage filtering; finite authored guiding questions; existing observed-run choices and fresh authorization | No unrestricted prose, hidden answers, grading, competency claim, progress mutation or new progressive-hint ladder |
| Support | Version-bound exact quotations and fresh post-provider reconstruction; protected route logs only source-version metadata after authorization/admission release | Semantic sufficiency still requires provider selection; valid quotation alone cannot prove question relevance |
| Frontend | Existing request/response contracts and adapters preserved; updated handoff | Browser validation result is recorded below; no frontend implementation changes |
| Deployment | Separate secure pilot plan | No host chosen, production profile, public exposure, migration, deploy or merge |

## Final backend regression

Command: existing Python 3.13 environment, `python -B -m pytest -q`, sockets
disabled except loopback test fixtures, coverage and JUnit saved outside the
repository. Existing migration fixtures ran only on disposable databases.

**3,610 passed in 604.72 seconds; zero failures, errors or skips.**
Branch-inclusive coverage: **96.61938098747237% (96.62%)**.

Compared with the reported merged baseline of 3,387 / 96.93%, this adds 223
passing cases and reduces coverage by 0.31 percentage points. Added async
constructor/stream/shutdown defenses have unexercised exceptional branches; the
Gemini module is 82% covered in this run. The percentage is not claimed preserved.
No assertions, skips, test selection or coverage thresholds were weakened; the
existing 85% threshold remains unchanged. One earlier full run was deliberately
interrupted after the late-timeout accounting repair, then the complete suite
was rerun against the frozen final source. The result above is that final run.

The full run includes existing migration upgrade/downgrade/integrity, identity,
ownership, evidence/privacy, tutor transaction/concurrency, Notes/Tasks runtime,
retrieval, generation/candidate validation and public contract tests.

New focused checks cover refusal/truncation and rejected-output accounting,
network error classification, profile bounds, shared cross-capability admission,
dripping-body timeout and actual cancellation cleanup, shutdown before database
disposal, source-version substitution/revocation/expiry, forged nested values,
receipt privacy, wrong-stage/wrong-lesson guidance selection and unchanged
learning progress/hint slots. Individual agent focus groups overlap and must not
be added to the final suite count.

- Provider/generation focus: 207 passed; provider/API focus: 64 passed.
- Final provider/lifecycle focus: 98 passed; final hardening module: 28 passed.
- Knowledge/corpus/readiness/support focus: 164 passed.
- Retrieval evaluator focus: 137 passed.
- New contextual-tutor/versioned-support HTTP modules: 8 passed.
- New receipt integrity unit module: 5 passed.

## Static and contract checks

- Ruff: passed.
- Formatting: 260 Python files already formatted.
- Mypy: 168 source files passed.
- Frontend unit suite: 140 passed in 11 files.
- Frontend `npm run typecheck`: passed.
- Frontend `npm run lint`: passed.
- Actual application OpenAPI equals the baseline JSON object: **24 paths / 26
  operations**, with no public schema or operation change.
- Fresh OpenAPI TypeScript generation into a temporary artifact matches the
  existing `src/lib/api/schema.d.ts` after newline normalization.
- `git diff --check`: passed.

The historical original API handoff/export, current OpenAPI exports, frontend,
existing lesson definitions/hashes, deterministic runtimes, database models,
migrations and dependency lockfiles have no implementation diff.

## Controlled live verification

Exactly **two** real provider calls were made through the shared client and
existing internal services using synthetic public questions. No credentials,
learner identifiers, raw submissions or private lesson configuration were sent
as test content. Both requested and returned `gemini-3.5-flash-lite`.

| Call | Result | Usage supplied by Gemini |
| --- | --- | --- |
| Tutor | `answered`, source `ai`, exact allowed authored guidance, completion authority false | Input 705 tokens; output 16 |
| Support | `answered`, source `ai`, exact `progress-retrieval` / `retrieval-one-seven-days` quotation with current version receipt | Input 306 tokens; output 35 |

Both attempts had complete supplied usage metadata. The test client allowed at
most two process attempts, zero retries, zero paid budget and no fallback. The
configured project remains the owner's approved unbilled Free Tier project;
application zero-cost accounting is not an independent Google Billing check.
Shared resources closed cleanly after both calls.

These are live provider/service checks, **not a fresh authenticated HTTP/browser
walkthrough**. The existing in-app browser control connection reported unavailable.
The prior Phase 3.7 real-account acceptance remains historical evidence only.

## Retrieval and source evidence

The actual nine-document/nineteen-passage approved corpus and its thirty-day
review window were preserved. At k=3, baseline Recall is 0.934783, MRR 0.925121,
and sufficient evidence 65/69 answerable cases. The fixed offline binary-BM25
candidate supplies 64/69 and regresses heldout Recall from 0.951613 to 0.903226;
production ranking remains unchanged. The remaining four baseline misses are
listed in `../support-retrieval-evaluation-v1.md`.

Oracle citation accuracy, support and abstention figures test deterministic
contracts, not live model reasoning. Adversarial controls deliberately show
that a retrieved exact quote can still be irrelevant. Do not infer guaranteed
semantic abstention or injection resistance from those oracle scores.

## Preservation and privacy

The actual local database was opened read-only for integrity/head inspection:
`PRAGMA integrity_check` returned `ok`; head remains
`0007_tutor_reservations`. No real database migration or write was performed by
this implementation/validation. Existing disposable test migrations are included
in the full suite.

Private environment files, the local database and unrelated work remain ignored
and unmodified by this task. The genuine native cohort log was preserved and
reviewed for authorized inclusion. Four unrelated app-injected suggestion logs
remain untracked and unpublished; no history was fabricated or rewritten.
Privacy review found no credentials, tokens, cookies, real email/account literal
or additional private-content publication blocker in the reviewed changes.
Safe support receipts contain source/revision/digest/chunk metadata and request
correlation only; no question, quotation, account identity or review-owner data.

## Browser validation and publication

The unchanged AI browser suite passed **4/4 in 45.5 seconds**, across desktop
and mobile Chromium. It exercises actual frontend adapters against synthetic
authenticated HTTP fixtures, labelled mock providers and disposable databases;
it is not a live Gemini browser test. It covers owned tutor/support requests,
exact sourced support presentation, fixture provenance, provider timeout and
guest-access rejection. The normal production frontend build also passed.

An initial isolated validation workspace failed before browser execution due
to Next/Turbopack external-dependency-root diagnostics and a React Compiler
path-resolution panic. The successful run used the normal project layout,
without changing compiler flags, app source, assertions or configuration.
One normal-layout attempt was stopped after a partially successful cache move
encountered OneDrive read-only attributes; the next complete run is the 4/4
result above. Generated metadata was restored, remaining development cache and
archived generated output retained, and historical test outputs preserved by
using a new external output directory. No recursive deletion was used.

Publication uses separate provider, support/evaluation and tutor/handoff
milestone commits. Exact commit/push/PR outcomes are reported after Git completes;
this document does not infer remote CI success. No merge or deployment was done.

The existing frontend preview remains reachable at localhost:3000. The prior
task-owned backend was restarted with the unchanged approved launcher and the
current source on loopback:8000; SQL readiness returned HTTP 200. Startup did not
perform a provider probe or migration. The two isolated live service checks
remain the only Phase 3.8 real provider calls.
