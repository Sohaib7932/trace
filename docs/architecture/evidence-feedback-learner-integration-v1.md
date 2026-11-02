# Evidence feedback learner integration V1 — architecture and security review

Status: **Phase 3.5C design for human review; public integration is not implemented
or approved.** Audited on 2026-11-02 against
`e82bbd737246dbd347e370f4668bde2003b044c4`, on
`feat/phase-3-5a-engineering-evidence`.

## 1. Executive summary

Keep `EvidenceFeedbackService.feedback(principal, query)` internal until a public
visibility policy, fresh release-time authorization and a dedicated public
projection are implemented and tested. Do not return `FeedbackReply` directly.
Its factual grounding is strong, but grounding is different from permission to
disclose a fact at a particular point in a lesson.

Three confirmed integration gaps determine the design:

1. The internal policy reports prediction accuracy immediately after prediction.
   Existing progress hides that accuracy until **at least one attempt has been
   submitted**, not until execution or successful verification.
2. Internal replies preserve source kinds and source-row UUIDs, stable derived
   evidence IDs, lesson-version UUIDs and internal fallback diagnostics. These
   fields need an explicit public allowlist and response-local citation aliases.
3. Post-provider authorization checks recheck a detached principal's expiry and
   snapshots. They do not reread credential revocation, guest-history claiming,
   account status/roles or account-to-learner ownership from storage.

The smallest recommended future integration is a separate authenticated,
read-only POST operation. Clients select only a session; the server selects the
evidence cohort, pin, policy and provider. Preserve existing progress/hint/run
contracts. No endpoint, frontend, source changes, new persistence, migration,
provider activation or competency progression is implemented in this milestone.

All proposals below remain subject to explicit approval. In particular, the
first-attempt visibility threshold, guest eligibility, next-action visibility,
rate limits and credential-revalidation policy are not new product policy yet.

## 2. Repository audit and preservation

The attached review brief assumed Phase 3.5B was still uncommitted and prohibited
publishing during the review. The accompanying direct instruction explicitly
requested **commit and push code, then do Phase 3.5C**. Accordingly, publication
was completed as a separate prerequisite before this architecture-only review.
No review document was included in that prerequisite commit.

| Audit item | Verified state |
| --- | --- |
| Branch throughout | `feat/phase-3-5a-engineering-evidence`; no switch, rebase or new branch |
| Initial local HEAD | `e319f1e159e6b7297cd7863ae7cf2d6bec529361` |
| Initial remote branch HEAD | Same `e319f1e`, verified with `git ls-remote` |
| Initial tracked diff | Four Phase 3.5B integration files and one genuine shared log; nothing staged |
| Initial untracked files | 18 Phase 3.5B deliverables and four pre-existing suggestion artifacts |
| Phase 3.5A inventory | Two application modules, three tests and two architecture reports, plus its genuine log change in its existing commit |
| Phase 3.5B inventory | Seven new application modules, nine Python test/helper files, one JSON fixture, one report; four modified integration files |
| Snapshot consistency | All 21 executable Phase 3.5B source/test/fixture files matched the previously validated isolated snapshot byte for byte |
| Published prerequisite | `e82bbd737246dbd347e370f4668bde2003b044c4`, ordinary commit and ordinary push; 23 files including the genuine shared log |
| Remote verification | `git ls-remote` and local remote-tracking ref both matched `e82bbd7` after push |
| Preserved ancestry | Phase 3.5A `e319f1e` remains an ancestor; no amend or history rewrite |
| Review deliverable | Only this new local Markdown proposal; no Phase 3.5C staging, commit, push, PR or merge |

Ordinary `git diff` initially showed only five tracked files. The 18 new files
were separately enumerated with `git ls-files --others --exclude-standard` and
compared with the Phase 3.5B report. There is no inventory discrepancy. The old
reports' uncommitted status statements describe their delivery-time snapshots;
this table records the subsequent authorized publication.

The four suggestion-only artifacts remain local and untouched. No shared log was
deleted or manually reconstructed. A scoped prepublication review found no
credential/token/key/email candidates in the intended changes or added genuine
log content; existing identity metadata was unchanged. This is not a claim that
arbitrary historical conversations are suitable for publication.

## 3. Verified architecture and source map

Paths below are repository-relative. Function/test names identify concrete
inspection targets; an existing test proves only its stated scope. Tests marked
future are not implemented by this review.

| Layer and actual source | Implemented behavior | Relevant existing test evidence / qualification |
| --- | --- | --- |
| `backend/app/api/dependencies.py`: `optional_account`, `current_learner`, `current_account` | Supplied Bearer authentication is verified; account ownership or a valid guest credential supplies learner UUID. Invalid supplied Bearer does not downgrade to guest. | `tests/integration/test_accounts.py::test_supplied_invalid_auth_never_downgrades_even_on_public_lesson`; server Principal construction is implemented. |
| `backend/app/auth/jwt.py`: `JwtVerifier.verify`, `authorization`, `_key` | Configured issuer/audience, asymmetric key/algorithm/signature, required claims, canonical subject and timing checks; bounded configured JWKS source and cache. | `tests/unit/test_jwt.py::test_asymmetric_valid_signature_and_required_claims`, `test_invalid_claims_rejected`, `test_signature_and_header_constraints`, `test_cache_rotation_unknown_kid_outage_and_refresh_cooldown`. No online token-revocation/introspection guarantee. |
| `backend/app/services/identity.py`: `IdentityService.authenticate`; `backend/app/db/learning.py`: `SqlLearningStore.credential` | Current hashed guest credential must be unexpired/unrevoked; claimed learner credentials are excluded by the storage lookup. | `tests/integration/test_accounts.py::test_claim_rejects_unusable_guest_credentials`; `tests/integration/test_transfer_retrieval.py::test_bootstrap_cannot_renew_a_credential_invalidated_between_read_and_write`. |
| `backend/app/services/accounts.py`: `bootstrap`, `learner`, `claim`; `backend/app/db/accounts.py`: `SqlAccountStore.bootstrap`, `ownership`, `claim` | Request-entry status/roles and learner ownership are resolved server-side; claiming maps the account to the existing learner UUID and revokes guest credentials. Short transactions also perform bootstrap metadata/first-login writes. | `tests/integration/test_accounts.py::test_populated_module_3_upgrade_claim_preserves_every_history_row`, `test_existing_account_history_conflict_leaves_both_histories_untouched`, `test_concurrent_claims_have_one_owner`, `test_disabled_account_and_subject_identity_cannot_be_reassigned`. |
| `backend/app/domain/accounts.py`: `Principal`, `Account.require_role` | Frozen internal identity snapshots. A Principal object itself is not authentication proof. | `tests/unit/test_evidence_feedback_service.py::test_invalid_authorization_never_reads_history_or_invokes_provider`, `test_inactive_or_malformed_accounts_cannot_request_feedback`. A bare internal Principal can be accepted; never deserialize one from a client. |
| `backend/app/db/learning.py`: `SqlLearningStore.owned_session`; `backend/app/services/learning.py`: `owned`, `progress` | Session lookup filters by learner and session before learner child data is returned. | `tests/integration/test_engineering_evidence.py::test_ownership_gate_treats_foreign_and_missing_sessions_equally`; feedback cross-owner tests below. |
| `backend/app/services/engineering_evidence.py`: `EngineeringEvidenceService.extract`, `_Projection.__init__`, `_pin`, `project` | Strict query refresh, owned consistent read, exact legacy lesson/digest, source integrity and bounded canonical projection. No writes or new grading execution. | `tests/unit/test_engineering_evidence_sources.py`; `tests/integration/test_engineering_evidence.py`; definitions/limits in `backend/app/schemas/engineering_evidence.py`. The record guard follows materialization, not SQL pagination. |
| `backend/app/services/evidence_feedback.py`: `feedback`, `_authorize`, `_public_lesson` | Initial snapshot/expiry checks; evidence extraction; second fresh exact owned-session/pin/public-catalog read; policy; detached provider request; whole-output validation or deterministic fallback; expiry checked again. | `tests/unit/test_evidence_feedback_service.py::test_public_lesson_is_reread_with_exact_pin_and_catalog_content`, `test_second_public_read_cannot_cross_owner_or_session_scope`, `test_expired_authorization_during_provider_call_never_returns_feedback`. No fresh credential/account/owner read after provider. |
| `backend/app/services/evidence_feedback_policy.py`: `build_feedback_request` | Backend owns all facts, uncertainty and wording variants. No learner score, causal diagnosis or inferred independence. Internal prediction accuracy has no public stage gate. | `tests/unit/test_evidence_feedback_policy.py::test_correct_prediction_without_change_confirms_prediction_only`, `test_mapping_without_finished_execution_is_partial_not_failure`, `test_changed_failed_then_passed_sequence_is_recovery_not_diagnosis`. |
| `backend/app/services/catalog.py`: `PUBLIC_CONTENT`, `TRANSFER_CONTENT`, `lesson_hash`, `transfer_hash`; `backend/app/schemas/evidence_feedback.py`: `LessonReference`, `FeedbackRequest` | Only five exact public lesson fields enter bounded context, with per-field UTF-8 digests; legacy version/private hash is checked internally. | Policy tests `test_modified_or_injected_public_material_is_rejected`, `test_other_family_public_material_is_rejected`, `test_wrong_digest_is_rejected_even_when_all_syntactic_pins_are_consistent`. |
| `backend/app/ai/providers/bounded_evidence_feedback.py`: `explain`, `_lesson` | Explicit transport allowlist; excludes owner/session/account IDs, raw source-row IDs, raw learner reasoning/submissions and hint text. Includes derived evidence IDs, lesson-version UUID, digest and correctness-bearing approved wording. | `tests/unit/test_evidence_feedback_providers.py::test_bounded_adapter_projects_only_authorized_public_fields_and_no_raw_history`. Identifier minimization is partial, not identifier-free transport. |
| `backend/app/services/evidence_feedback_validation.py`: `validate_feedback_selection`, `render_feedback`, `_sources`, `unavailable_feedback` | Exact request/policy/pin/state/all-claims/wording/per-claim references. Original server wording is rendered. Invalid whole output is rejected, never repaired around retained conclusions. Internal raw provenance is preserved. | `tests/unit/test_evidence_feedback_validation.py::test_whole_selection_rejected_for_unsupported_or_conflicting_content`, `test_malformed_duplicate_nonfinite_and_oversized_output_is_not_presented`, `test_failed_selection_never_survives_as_repaired_claims`. |
| `backend/app/ai/resources.py`: `AIResources`; `backend/app/api/dependencies.py`: `get_evidence_feedback_service`, `get_tutor_provider`; `backend/app/main.py` | Cached feedback adapter uses one application-owned shared client. Learner hint provider remains `FakeTutorProvider`. No public feedback endpoint. | `tests/unit/test_evidence_feedback_providers.py::test_resources_cache_feedback_adapter_and_share_one_client_with_other_capabilities`, `test_distinct_resources_isolate_feedback_usage_and_shutdown`; `tests/integration/test_evidence_feedback_lifecycle.py`. |
| `backend/app/api/presentation.py`: `present_progress`, `present_lesson`, `present_run`; `backend/app/schemas/learning.py` | Existing public fields are explicitly projected, but run checks already include expected/observed/source and hints include fixture metadata. Prediction correctness is hidden until an attempt exists. | `tests/integration/test_legacy_contracts.py::test_real_legacy_responses_and_errors_keep_the_frozen_contract`; `test_learning.py::test_complete_real_journey_preserves_prediction_attempts_and_fresh_evidence`. Dedicated pre-attempt null-correctness regression is still needed. |
| `backend/app/services/learning.py`: `hint`, `_hint_allowed`, `_reserve_hint`, `_finalize_hint` | Prediction first, maximum three hint requests, exact retries, one pending operation, session/attempt ownership and finalization deadline/expiry/terminal checks. Tutor runs outside write transaction. | `tests/integration/test_tutor_transactions.py::test_blocked_provider_allows_independent_write_and_truthful_attempt_history`, `test_concurrent_retries_do_not_call_provider_or_consume_another_slot`, `test_session_terminal_during_provider_work_never_receives_guidance`, `test_authorization_expiry_is_checked_before_and_after_provider`. |
| `backend/app/services/retrieval.py`: `_owned`, `submit`, `schedule_checkpoints`; `backend/app/api/retrieval_presentation.py`: `present_retrieval` | Owned checkpoint, due-time and idempotency checks, pinned question; upcoming question hidden; recorded recall answers expose their own correctness. Unchanged +1/+7 UTC elapsed-day schedule. | `tests/integration/test_transfer_retrieval.py::test_exact_boundaries_hidden_initial_answer_and_missed_checkpoints`, `test_retrieval_owner_origin_and_input_protection`, `test_retrieval_history_idempotency_completion_and_database_guards`. |
| `backend/app/core/errors.py`: `register_error_handlers`; `backend/app/core/middleware.py`: `RequestContextMiddleware`, `RequestLimitsMiddleware`; dependencies: `require_write_origin` | Sanitized validation/errors, bounded bodies/deadline, metadata-only route logging; explicit modifying-request Origin/client-header checks. Success no-store does not prove error no-store. | `tests/integration/test_api.py::test_http_errors_use_envelope_and_request_id`, `test_unexpected_error_is_generic_and_cors_is_preserved`, `test_request_logs_do_not_leak_unknown_paths_queries_or_bodies`; `test_accounts.py::test_bearer_tokens_and_provider_errors_never_logged`. |

Actual internal flow:

```mermaid
sequenceDiagram
    participant C as Internal caller
    participant F as EvidenceFeedbackService
    participant D as Existing repositories
    participant P as Deterministic policy
    participant M as Application mock/disabled adapter
    C->>F: feedback(server Principal, strict query)
    F->>F: snapshot and expiry validation
    F->>D: evidence read: owner, pin, source integrity
    D-->>F: immutable canonical evidence
    F->>D: separate owned public lesson/pin read
    D-->>F: exact approved public fields
    F->>P: build authorized facts, wording and citations
    P-->>F: bounded feedback request
    Note over F,D: All read scopes close before provider work
    F->>M: detached wording-selection request if evidence sufficient
    M-->>F: selection or failure
    F->>F: exact validation; snapshot expiry recheck
    F-->>C: internal reply or complete deterministic fallback
```

No diagram step implies a live provider or public authorization boundary.

## 4. Current public API and visibility analysis

All listed learner routes are in `backend/app/api/v1/learning.py`; retrieval is
in this same router, not a separate `api/v1/retrieval.py` module.

| Existing surface | Current visibility | Compatibility consequence |
| --- | --- | --- |
| `GET /api/v1/lessons/{lesson_id}` | Public catalog fields and lesson-version UUID, no private answer field. The optional auth dependency still rejects supplied invalid authentication. | Reuse only approved field content. Do not claim the lesson-version UUID has never been public. |
| POST/GET session prediction | Own selected option, reasoning, record ID/time; no correctness property. | Feedback cannot make correctness visible earlier through text, labels, state or fallback. |
| Session progress | Own attempts/hints/runs/events; `summary.prediction_correct` is null until a submitted attempt exists. | First submitted attempt is today's disclosure threshold. It is not a verified-execution gate. |
| Attempts and verifications | Own finite mapping submissions; actual finalized/error checks once generated. `CheckResponse` includes `expected`, `observed`, `source`. | Existing responses can contain trusted fixture expectations, response/row details and runtime UUIDs. New feedback must be stricter. Revising these legacy fields is a separate compatibility/privacy task. |
| Hints | Delivered/error fixture guidance, sequence and metadata; policy restricts new requests. Exact saved retries can replay after terminal state. | Feedback is not a way to mint more tutor guidance or reset hint limits. Do not reproduce hint text or provider/fixture/prompt metadata in new feedback. |
| Journey/retrieval | Own session/checkpoint summaries, due questions and own recall-answer correctness/feedback. Upcoming question is hidden. | No early question/explanation disclosure through feedback; recall facts remain auxiliary. |

Notes example: an original prediction can correctly anticipate rejection, while
the first changed mapping later verifies successfully. Feedback must keep those
two observations separate, as tested by
`test_correct_original_prediction_is_not_compared_with_first_successful_repair`
in `tests/integration/test_evidence_feedback.py`.

Tasks example: a failed flat submission precedes an accepted nested correction.
The recorded result can support recovery chronology and completion of this
particular Tasks exercise. It cannot support a debugging diagnosis or identify
an originating Notes session. See `test_tasks_flat_failure_nested_success_and_missing_parent_remain_precise`
in that same integration file.

## 5. Proposed learner visibility matrix

Every new rule in this table is **proposed**, not already enforced by the internal
service. Recommended minimum gate: an owned submitted attempt exists strictly
before the server cutoff. This matches current progress disclosure. A stricter
post-execution-only launch is an explicit alternative requiring approval.

“Call” means call the internal feedback service after normal authentication,
ownership, ingress limits and the new visibility gate. “Abstain” applies to the
unsupported claim, not a negative learner grade. Source labels refer to the
canonical extraction described in sections 3 and 10.

| Learner/evidence state | May see / supporting evidence | Must remain hidden | Call / abstention | Existing exposure and required new rule |
| --- | --- | --- | --- | --- |
| Session before prediction/attempt | Generic availability message and existing public lesson material only. | Accuracy, implied answer, evaluator outcomes, correctness-dependent labels/states. | **No call**; `not_ready`, grounding state null. No assessment. | Catalog already public. Add early no-evaluation gate and identical answer-independent message. |
| Prediction submitted, no attempt | Existing own selected option/reasoning via prediction API; generic feedback-not-ready notice. | Prediction accuracy in every section, citation, delivery/fallback difference and provider context. | **No call**, including deterministic/disabled paths. | Progress intentionally withholds accuracy; internal policy does not. New gate is mandatory. |
| Attempt submitted, not executed | Own prediction accuracy, finite submission observation and “execution unproven,” using prediction/attempt sources. | Successful implementation, independent code authorship, fabricated runtime results or repair values. | Call permitted under proposed first-attempt gate; partial grounding; abstain on execution. | Progress already exposes accuracy and attempt. New public projection/unknown language needed. |
| Run pending | Submission remains visible; verification is still pending. | Final pass/fail or any invented check. | Call may yield partial feedback; no claim that a pending run finished. | Existing run pending state exists. Do not convert pending into failure. |
| Execution unavailable/error | Recorded action and neutral unavailability, from actual error/run sources. | Learner-failure inference, hidden exception, connection details, internal execution check values. | Call permitted; partial support or unavailable source result. | Existing API has error runs. New diagnostic sanitization required. |
| Failed verification | Actual failed result and approved check-category match summaries from that run. | Private expected/observed values, repair mapping, raw HTTP/SQL data or psychological diagnosis. | Call permitted; supported can describe failure. Abstain on diagnosis/mastery. | Existing run API is broader; do not copy `CheckResponse`. Add check-category allowlist. |
| Passed verification | That selected attempt's passed categories, including independently recorded fresh readback. | General mastery, independence, arbitrary expected values, success of unobserved code. | Call permitted; supported facts only. | Existing completion/run visibility. Preserve exact five-category evidence, not inferred completion-only checks. |
| Partially supported evidence | Known submission/action plus the precise missing execution/assistance fact. | Claims that unavailable observation means wrong competence. | Call permitted if session gate passes; explicit partial state. | New state explanation is required; state is not a correctness score. |
| No competency observations in server cohort | Neutral insufficient-evidence notice; auxiliary facts only if individually allowed. | Invented competence, negative scores, invented investigation. | Call only after session gate; service skips provider when insufficient. | Internal behavior implemented; public visibility/filtering is new. |
| Invalid/unavailable/over-limit sources | Constant unavailable notice, no factual sections or source citations. | Whether corruption, missing dependency, private pin or context overflow caused it. | Service may return unavailable; abstain from every factual conclusion. | Internal empty unavailable reply exists; public coarse mapping is new. |
| Delivered tutor help before action | Friendly “guidance was delivered before this action” attribution from exact canonical delivery provenance. | Hint text, unseen progressive hints, “read/understood/caused success,” provider metadata. | Call permitted after session gate; assistance facts only. | Hint history exists. New feedback attribution projection must retain strict-before timing. |
| Requested/pending/error hint or unknown assistance | Request/error fact only if needed, or “assistance is unknown.” | False delivery/nondelivery, independence, external-help conclusions. | Call permitted; abstain from assisted/independent claims without delivery evidence. | Reservation alone is not delivery; preserve existing extractor distinction. |
| Recall answer in owned Tasks history | A past submitted recall answer's own result if checkpoint/question are already disclosable; describe as recall only. | Upcoming question, future answer, engineering competency or retrieval-specific independence. | Call only after session gate and separate due/history check. Otherwise omit whole recall claim. | Retrieval API gates upcoming questions and exposes submitted correctness; add feedback cross-check without changing schedule. |
| Tasks completion/transfer | Actual completed Tasks result, grounded in its own attempt/run. | Exact parent Notes session/version, broad transfer mastery. | Call permitted; state parent linkage unavailable. | Existing prerequisite is any owned Notes completion; exact link is not stored. |
| Completed or abandoned session | Already permissible historical facts/reflection. | New tutor guidance or answer-key disclosure through `next`. | Historical feedback may be called; omit actionable `next` under conservative draft policy. | New hints prohibited; exact saved hint retries remain existing behavior. Terminal feedback policy needs approval. |
| Evidence citations | Response-local aliases, friendly event/check labels and relevant own event timestamp. | Source-row UUIDs, table/source-kind names, stable cross-response evidence IDs, arbitrary lookup URLs. | Allowed only with disclosed claims; omitted claim loses its citations. | Current internal provenance is richer. New alias projection mandatory. |
| Lesson citations | Approved public field label, lesson slug/semantic version and public-field digest. | Database version ID in new DTO, private legacy hash inputs/answer fields, filesystem paths. | Public fields only; pin validated internally on every response. | Catalog already contains public code/version ID. New contract deliberately minimizes identifiers. |

Actionable `next` is the main unresolved hint-policy edge. Recommended initial
allowlist is the already approved generic code/schema comparison only, for
nonterminal sessions after the visibility gate, with no answer/mapping-specific
copy. This is not a tutor interaction and must not add a delivered-hint record
or consume an assignment. If this interpretation is not approved, omit `next`
entirely from public V1; do not relabel novel guidance as reflection. Public
sections are optional, unlike the internal usable reply's required next step.

## 6. Proposed authenticated contract

### Alternatives and recommendation

Do not extend progress: existing consumers expect its deterministic shape and
latency. Do not extend hints: feedback is not a new hint, and hint limits and
idempotent reservation semantics are different. A dedicated operation isolates
privacy, latency and operational controls. Keep it internal until the preceding
gates and open decisions are approved and implemented.

Proposed future operation (not present in OpenAPI):

`POST /api/v1/sessions/{session_id}/feedback`

It derives a response and makes no learner-state change. POST avoids accidental
GET prefetch/shared-cache behavior for potentially expensive work; it is not
permission to publish feedback or alter sessions.

### Request selectors and validation

| Input | Proposed contract |
| --- | --- |
| `session_id` path | Required canonical UUID string, one owned session. Invalid syntax 422; well-formed missing or foreign session same sanitized 404. |
| Body | Required JSON object `{}` with unknown fields forbidden; no optional body selectors in V1. Content type and existing global byte limits apply. |
| Authentication | Existing valid Bearer token or guest HttpOnly credential, if guest support is approved. A supplied invalid Bearer never falls back to cookie. No client Principal. |
| Origin/CSRF | Reuse modifying-request allowed Origin plus `X-Trace-Client: learning-web`, including cookie requests; explicit CORS remains. |
| Correlation | Optional existing `X-Request-ID`: current 1–64-character allowlist; replaced when invalid. It is a log correlation value, not authorization/idempotency evidence. Generate a separate internal query UUID server-side. |
| Timestamps/windows | **No client timestamp fields.** Server obtains aware UTC cutoff from its clock; `start_at = session.created_at`, `end_at = as_of = cutoff`, half-open `[start_at,end_at)`. Require increasing aware bounds and exclude future/equal-cutoff actions. Equal creation/cutoff yields not-ready without query construction. |
| Record budget | Server sets existing maximum 64 combined canonical records; no client override, no silent truncation. Overflow yields coarse unavailable. Full-session history is the initial cohort; adding an incremental/window selector requires another reviewed contract. |
| Lesson/focus | Resolve exact owned session pin and deterministic selected attempt internally. No client lesson version, digest, attempt/focus override or latest-version substitution. |
| Rejected payload fields | Learner/account ID, evidence/IDs, competency, correctness, runtime results, checks, provider/model/config, private evaluator values, policy, windows/as-of, record limit, arbitrary prompts/paths/documents, hint level, cached feedback token. |

No durable idempotency ledger is proposed for a read-only result. Do not promise
exactly-once provider invocation or byte-identical future replies. A repeat may
observe additional permitted history and select different approved wording.
`Idempotency-Key` is not part of this contract and confers no replay entitlement.
If exactly-once paid-call semantics become a requirement, design an explicit
operation contract separately; do not infer it from request IDs or hint behavior.

### Public response proposal

Use a **new public schema**, tentatively
`evidence-feedback-public-v1`, never `FeedbackReply.model_dump()` with exclusions.
An explicit constructor/allowlist should create every public field.

| Field | Proposed meaning / bound |
| --- | --- |
| `schema_version` | Exact `evidence-feedback-public-v1`. |
| `policy_version` | Public visibility-policy version, e.g. proposed `evidence-feedback-visibility-v1`; separate from internal interpretation version. |
| `availability` | `available`, `not_ready`, `not_supported` or `unavailable`; availability is not grounding or competence. |
| `feedback_state` | Existing four grounding states when evaluated; null for not-ready/not-supported. Never derive it from a hidden prediction. |
| `delivery_state` | `deterministic`, `mock` or `unavailable`; mock clearly labeled and permitted only in an approved test context. No live/AI-generated claim. |
| `session_id` | Echo the authorized session path identity; no learner/account identity. |
| `lesson` | If authorized/validated: lesson slug, semantic version, and SHA-256 of canonical **public-only** five-field content. No database version UUID or private legacy definition hash. Internal exact pin remains authoritative. |
| `as_of` | Server UTC cutoff, not a claim that the current session cannot change. Not-ready output may omit it. |
| `sections` | Up to four optional kinds `demonstrated`, `needs_improvement`, `why`, `next`; at most 16 total statements, each at most existing 600 characters; `next` at most one and policy-gated. No arbitrary HTML/Markdown links. |
| Statement | Server-approved text and response-local evidence/lesson aliases only; role can distinguish observation/limitation/next step. No provider prose, score or internal claim/evidence/source UUID. |
| `evidence_citations` | Up to 64 used local aliases, friendly allowlisted description, optional own UTC event time and allowlisted check-category match booleans. No expected/observed raw values or source-kind strings. |
| `lesson_citations` | Up to five used aliases, public field name/label, lesson slug/version, SHA-256 of that exact public UTF-8 field. Optional navigation target is a finite public-field enum, not URL/path. |
| `notice` | Bounded constant/approved safe message. No raw internal `fallback_reason`, exception, provider/fixture/model/prompt metadata. Deterministic delivery is labeled as such. |

If source evidence is unavailable, return no factual sections or citations.
If disclosure is not ready, return the same content-independent availability
shape for correct and incorrect predictions. Policy-vocabulary coverage metadata
can be translated to neutral approved text; do not expose a six-competency score
profile or treat `observed_in_window=false` as failure.

Internal grounding state is never upgraded by public filtering. If the public
visibility policy removes a claim, remove that whole claim and every dependent
conclusion, along with orphaned citations. Do not strip citations while keeping
their conclusions. If a safe self-contained projection cannot be established,
return unavailable. The current provider validator still requires the complete
original internal claim set; a public projection is a distinct later step, not
a weakening of that validator.

Public state mapping must also be conservative. Not-ready/not-supported replies
have null grounding state, unavailable delivery and empty sections/citations.
Source-unavailable replies have grounding/delivery unavailable and empty
sections/citations. After evaluated visibility filtering, if no permitted
canonical competency fact remains, downgrade supported/partially-supported to
insufficient-evidence; auxiliary recall/help facts and neutral limitations may
remain without becoming competency conclusions. Never retain supported with
only a next step or instrumentation limitations, and never upgrade an original
insufficient-evidence state because auxiliary facts exist. If a safe mapping or
complete support set cannot be established, return unavailable instead.

### Operations, resource limits and staleness

- Reauthenticate and authorize every request, including repeats. Request IDs,
  aliases, previous responses and session UUID possession never authorize access.
- Apply learner-scoped ingress rate and concurrent-work limits **before evidence
  extraction**, plus an application-wide concurrency bound. Use resolved learner
  identity so account/guest modes do not create independent quota buckets.
  Exact rate/window/global-cap values require approval. Reject excess work with
  429 and safe `Retry-After`; do not silently convert abuse rejection to success.
- Shared AI-client budgets/rate limits are a second layer. Disabled,
  insufficient-evidence and deterministic paths still consume ingress allowance;
  otherwise an attacker can repeatedly force database reads without a model call.
- Initially do not implement a cache, replay store or single-flight manager.
  Repeated calls can run again within ingress limits; concurrent calls over the
  chosen cap are rejected, not queued indefinitely. No Redis/distributed queue
  is needed for the current single-process design. Multi-worker deployment
  requires an approved aggregate limiting strategy before activation.
- Set `Cache-Control: private, no-store` on **all** outcomes, including validation,
  authentication, Origin, rate, timeout and unexpected-error responses. Ensure
  this at the feedback boundary/outer response layer; injected success Response
  headers do not survive a fresh exception-handler response automatically.
  No ETag, conditional 304 or shared/browser/service-worker feedback cache.
- Use the existing bounded synchronous service in a normal synchronous FastAPI
  handler/threadpool, with no streaming, jobs or polling endpoint. Do not call
  blocking provider work directly on an async event loop. The current shared
  deadline cannot forcibly stop an arbitrary stuck synchronous callback; any
  future approved transport must enforce its own I/O deadlines.
- Define an internal evaluation/release fence tied to owner, pin, visibility
  state and exact selected evidence cohort. If relevant history changes during
  evaluation, discard the stale result and return sanitized 409
  `feedback_changed`; do not repeatedly rerun provider work inside one request.
  This fence is proposed; the current internal reply does not supply one.
- Log only existing sanitized correlation/route/status/duration and approved
  coarse operational codes. Never log bodies, feedback text, source UUIDs,
  submitted reasoning/code, cookies/Authorization, provider context or raw errors.
  Do not use request IDs as trusted learner identifiers or metric dimensions.

## 7. Authentication and authorization sequence

The future boundary must not assume DI gives end-to-end authorization.

1. Apply request byte/deadline/context middleware and existing Origin/CSRF rules.
   Resolve `current_learner` through the actual Bearer/guest path. Never accept a
   serialized Principal or body learner UUID.
2. Authenticate at entry. For an account, current local account must be active,
   retain learner role and map to the resolved learner. For a guest, current
   credential must still exist, be unexpired/unrevoked and not have been claimed.
3. Enforce learner ingress limits before expensive source reads. For an allowed
   request, take a short read to validate exact session ownership, pin, current
   stage and approved audience policy. Return not-ready without invoking the
   feedback service when the attempt gate is closed.
4. Capture server-owned bounds and the initial release fence. Call the existing
   evidence/feedback orchestration; all actual facts still originate in
   `EngineeringEvidenceService`. No duplicate evidence history or new evaluator.
5. Close all learner database scopes before invoking a provider. Never hold a
   SQLite write transaction while awaiting slow work; preserve current invariant.
6. Validate the entire selection or rebuild the entire deterministic fallback.
   An invalid provider payload never has its conclusions salvaged.
7. Before releasing **any** evaluated result, perform a fresh, short consistent
   read of current authorization and session eligibility. Check current guest
   credential, anti-claim state; or account status, learner role, ownership
   mapping; and principal/token expiry against current clock. Confirm the same
   owned session and exact legacy pin and compare the evaluation fence.
8. Project approved claims to the public allowlist, rekey citations locally and
   validate every retained claim/alias/public-field digest. Close the short read
   scope, add no-store and emit. A repeat, fallback or future cache hit must use
   the same release authorization; none may bypass it.

Steps 3, 4's release fence, 7's fresh storage checks and 8's public projector are
**not implemented**. The existing internal service performs snapshot expiry
checks and two pre-provider evidence/public reads only. A future small internal
evaluation envelope or orchestration seam must bind its exact canonical bundle
to the release fence. A wrapper cannot honestly synthesize that fence from a
reply plus an unrelated later progress read. Design that seam in the next
implementation review without changing existing internal callers or grading.

Existing account and learning repository abstractions do not yet expose this
combined read-only release authorization. Prefer an additive internal read
adapter over the same short SQLAlchemy session/transaction, including credential
identity lookup and account mapping checks. Do not call `bootstrap`/`learner`
again at release merely to reuse DI: they can write metadata or create a learner.
No migration is obviously required for reading these already existing records.

Session owner/version immutability is protected by existing SQL history guards;
it reduces normal mutation races but is not a substitute for current credential
or account checks. A final read provides a defined release decision, not a claim
that revocation after that decision can retract bytes already sent. This residual
network-time race must be accepted explicitly.

Supabase JWT verification currently provides local signature/claims/expiry
validation with configured cached JWKS. Immediate remote Supabase sign-out or
token revocation is not proven by that path. The team must approve whether
local account disable + expiry suffices or an additional revocation policy is
needed. Do not invent an online provider call or token introspection mechanism.

## 8. Threat model

Statuses describe existing protection against future public exposure, not an
active public feedback vulnerability: there is currently no feedback route.

| Threat / attack | Existing protection and evidence | Remaining gap / status | Proposed mitigation | Required future regression |
| --- | --- | --- | --- | --- |
| Cross-account IDOR/BOLA: guessed session | `owned_session`, extractor owner-first read; `test_cross_owner_and_unknown_sessions_propagate_not_found_without_provider` and real `test_cross_owner_and_missing_session_do_not_reach_provider`. | **Verified protection** internally; new route must use server identity. | Same 404 for missing/foreign; no preliminary unowned lookup or source enumeration. | Foreign UUID, unknown UUID and cross-account replay have identical safe envelope; provider not reached. |
| Forged identity/evidence/selector | Strict `FeedbackQuery` refresh and provider schema; `test_forged_query_model_copy_is_revalidated_before_any_repository_read`. | **Partial protection**: no public request schema exists; Principal is trusted internal data. | Empty-body public contract, UUID path validation, reject all outcome/pin/window/evidence fields. | Body owner/competency/correctness/provider injection, duplicate/extra fields and malformed UUID fail without extraction. |
| Expired principal during slow work | `_authorize` before/after; `test_expired_authorization_during_provider_call_never_returns_feedback`. | **Verified protection** for expiry/snapshot checks; not fresh revocation. | Preserve current expiry checks plus fresh release storage checks. | Expiry at exact boundary on success, fallback and insufficient branches. |
| Credential revoked/guest claimed/account disabled mid-call | Current credential/account lookup at request entry; claim revokes credentials. Account claim tests verify storage behavior. | **Partial protection**: detached snapshot never learns of later storage changes. | Fresh release credential/account/role/mapping read; identity mode fixed through operation. | Block provider then revoke, claim, disable, remove learner role or change mapping; no feedback escapes. |
| Ownership/pin TOCTOU | `_public_lesson` rereads exact owner/session/pin; SQL guards preserve historical identity; `test_second_public_read_cannot_cross_owner_or_session_scope`. | **Partial protection**: no final owner/pin/stage/fence read. | Consistent release read and stale-result rejection. | Mutate test store between every pair of reads/provider and verify denied/stale safe result. |
| Unauthorized lesson version/candidate | Exact legacy hash/catalog validation; policy digest and public-content mutation tests. | **Verified protection** for internal legacy pins; public allowlist not built. | Retain exact pin; never resolve latest lesson or unassigned blueprint; public-only field hashes. | Wrong lesson family/version/hash, unavailable catalog, newer unapproved candidate cannot substitute. |
| Prediction answer oracle before attempt | `present_progress` gates accuracy until an attempt. | **Missing protection** in internal feedback; policy test explicitly reports accuracy without change. | Gate before internal call/provider; answer-independent not-ready response on every delivery path. | Correct/incorrect pre-attempt sessions yield same availability shape, no accuracy text/state/citation/provider call. |
| Hint bypass or terminal new guidance | Existing hint reservation/limits/terminal/expiry checks; tutor transaction tests. | **Partial protection**: feedback next-step policy is separate and does not consume hints. | Approved finite next-action allowlist; terminal omission; no hidden hint text or progression. | Exhaust three hints, terminal states and pending/error hints; feedback cannot reveal additional authored guidance. |
| Malicious provider changes grade/text | Exact selection validation; original approved wording only. `test_whole_selection_rejected_for_unsupported_or_conflicting_content`. | **Verified protection** against accepted free prose/new facts; live mode absent. | Preserve strict validator and complete deterministic fallback. | Scores/new correctness/paths/links/private config/injected instructions are fully rejected. |
| Citation substitution: unrelated valid source | Validator checks exact refs per claim, not global membership. | **Verified protection** internally; public alias mapping missing. | One-way local aliases bound to complete exact canonical support set; validate projected claim. | Swap another existing evidence ID/alias, change pin/digest, drop a support edge; no retained conclusion. |
| Replay/request-ID abuse | Read-only service; deterministic repeated output test. | **Missing protection** for dedup/rate; that test makes two provider calls, not exactly once. | No replay entitlement/cache; every call reauthenticates and consumes ingress allowance. | Repeated correlation values, prior response and concurrent retries cannot bypass auth/quota. |
| Error or identifier leakage | Generic middleware and sanitized validation; logging tests. | **Partial protection**: internal sources/diagnostics intentionally rich; error responses do not guarantee no-store. | New public projector, coarse notices, feedback-wide error/no-store handling. | Serialize every success/error/fallback and assert absence of sourceUUIDs/kinds/expected/config/provider details. |
| Excessive requests/large histories | Global request limits and shared client rate/budget; canonical record limits. | **Partial protection**: extraction materializes lists before 10,000 guard; 64 output records is not a DB work bound. | Pre-extraction limits/concurrency; over-limit unavailable without truncation. Audit bounded SQL selectors before scaling. | Disabled/insufficient/overflow paths still rate-limited; many histories cannot cause unbounded concurrent reads. |
| Missing/corrupt evidence becomes false assessment | Exact pin/source consistency and unavailable/insufficient states; source-integrity and feedback failure tests. | **Verified protection** internally; public state translation not built. | Never convert absent observation to failure; empty unavailable conclusions, neutral unknown limitations. | Corruption, missing checks, readback outage, request-only hints, auxiliary recall produce abstention. |
| Public citations leak cross-session hint/history | Internal `_sources` deliberately preserves genuine related/out-of-window sources. | **Missing protection** in direct serialization. | Friendly label and response-local alias only; no generic source retrieval route or hint-text fetch. | Out-of-window delivered assistance retains correct attribution with no raw IDs/content/other learner data. |
| Stale result after new attempt/run | Immutable original evidence protects historical facts. | **Missing protection** for public current-result semantics. | Exact evaluation/release fence; 409 on relevant changed history; no automatic retry loop. | New attempt/run/hint finalization during provider yields stale response rather than mismatched current summary. |

## 9. Privacy and citation policy

“Backend internal,” “provider transport” and “public learner response” are three
different boundaries. Current provider means approved mock transport only.

| Data | Actual internal / transport behavior | Proposed learner-visible policy |
| --- | --- | --- |
| Learner/account identity | Internal Principal and evidence owner UUID; adapter excludes both. Owner-derived rate subject stays inside shared client. | No raw account/learner identity in feedback. Existing identity endpoint remains separate. |
| Session identity | Internal query/reply; adapter excludes session UUID. | Authorized path session UUID may be echoed; never another session owner or parent identifier inferred. |
| Original source references | Canonical `SourceReference(kind,record_id)` retained in internal reply; excluded from transport data. `repr=False` is not a serialization exclusion. | Never serialize kind/record_id or raw nested references. |
| Derived evidence IDs | Stable UUID5 identity from event/schema/source; adapter sends these IDs. | Response-local `e1`, `e2` aliases only; no stable cross-response tracking or dereference endpoint. |
| Lesson identity/digests | Internal exact `LessonPin` includes database version UUID and legacy digest; provider receives these. | Slug/version and public-only digests; omit database UUID and private-definition hash. |
| Public lesson content | Exactly title/objective/scenario/outgoing_code/schema_code; adapter sends only used approved fields. | Approved public field labels/content or safe in-app enum target; field byte hashes tied to validated exact version. |
| Private lesson content | Backend extraction validates private answers/evaluators; adapter excludes private config. | No keys, correctness mappings, private expected values, completion logic or trusted runtime configuration. |
| Prediction | Backend derives accuracy; transport sees accuracy-bearing authorized wording, not selected answer/reasoning. | Accuracy only after approved stage gate; own raw answer remains existing prediction API, not duplicated into feedback. |
| Attempts/code | Canonical finite submission observations; no real code patch exists. Adapter excludes raw mapping/explanation/code. | Friendly selected-attempt fact; no invented diff or authored implementation proof. Own mapping history remains existing attempt API. |
| Verification | Canonical categories/matches and original source refs. | Only five approved category labels and actual match facts; no arbitrary `execution` detail, expected/observed JSON/rows or fixture secrets. |
| Hints/assistance | Delivery references/timing retained; adapter excludes hint text. | Friendly actual delivery-before-action attribution; no replay of text or claim it was read/understood. Unknown stays unknown. |
| Recall/transfer | Exact question/checkpoint and Tasks pin/provenance internally. | Past authorized recall fact and particular Tasks result only; no upcoming content or invented parent Notes link. |
| Provider metadata | Adapter/client have internal source/error/model/request metadata. Internal reply has fallback taxonomy. | Explicit deterministic/mock/unavailable delivery, coarse notice only; no model/provider/fixture/prompt IDs, keys or raw diagnostics. |

For public evidence aliases, enumerate only retained canonical citations in
deterministic order inside one response. Maintain an in-memory mapping to their
complete original support sets while building/validating that response. Aliases
are neither credentials nor persisted records. A new response may reuse `e1` for
a different fact; clients must scope aliases to that response and not aggregate
them as stable evidence identities. Friendly descriptions are backend-authored,
not database table names. Do not add an evidence lookup endpoint.

Public lesson aliases (`l1`, etc.) bind to a single allowlisted field, exact
public UTF-8 digest and validated internal pin. Never publish the private hash
inputs to explain a pin. A public-content digest can be computed from an
explicit canonical five-field object; canonical encoding must be specified and
tested in the implementation milestone. Same semantic version with changed
public bytes must never be silently accepted.

Timestamps may describe the learner's own cited action in UTC, with display
localization left outside this backend contract. They must not reveal other
learners or purport to prove causal order when timestamps are equal. Assistance
outside the event window may support attribution without exposing its original
record ID/text. No new raw history copy is needed.

Before any live-provider integration, separately approve whether stable derived
evidence IDs and database lesson-version UUIDs may leave the backend. Current
adapter transport includes them. If disallowed, introduce context-local provider
aliases with exact validated reverse mapping; do not describe that minimization
as implemented now. No live provider currently receives any such data.

## 10. Errors, abstention and fallback

All response choices below are proposed public behavior. Preserve current
`ErrorResponse` envelope/request correlation conventions for HTTP errors.

| Condition | Proposed response | Required content rule |
| --- | --- | --- |
| Pre-attempt / gate closed | 200, `availability=not_ready`, null grounding, unavailable delivery | Constant answer-independent notice; no internal call, sections or citations. |
| Authenticated but unsupported approved lesson | 200, `not_supported`, null grounding | Only after owned-session authorization; never substitute a blueprint/latest version. |
| Insufficient evidence | 200 available, `insufficient_evidence`, deterministic | Optional neutral limitations/allowed auxiliary facts; no negative assessment, no provider call. |
| Source unavailable/invalid/over limit | 200 unavailable, `feedback_state=unavailable`, unavailable delivery | Empty conclusions/citations, same coarse notice; do not reveal integrity-vs-dependency reason. |
| Foreign/missing session or forged ownership | 404 `not_found` | Same sanitized message; no confirmation of existence. |
| Missing/expired/revoked auth | 401 `unauthenticated` | No cached/fallback feedback; no credential details. |
| Disabled account / missing approved role | 403 `forbidden` | Coarse account unavailable message; no internal account identifiers. |
| Invalid public request/UUID | 422 `validation_error` | Field locations/codes only, never input or private exception context. |
| Corrupt lesson ref/provider citation | Reject provider selection; valid original plan can render deterministic fallback | Whole-output rejection; no retained unsupported conclusion or raw offending payload. If original source/pin invalid, unavailable instead. |
| Stale evaluation/session changed | 409 proposed `feedback_changed` | Discard evaluated text, safe “refresh/retry” notice; no automatic costly loop. |
| Provider timeout/refusal/exception/malformed output | 200 available if trusted evidence and fresh auth still valid; deterministic delivery | Original approved plan rendered afresh; generic deterministic notice, not live-AI feedback. |
| Duplicate/repeated request | Independently authorized current response, or 429 when ingress capped | No promise of saved operation; previous ID/result grants no access or cost exemption. |
| Ingress rate/concurrency limit | 429 `rate_limited`, safe `Retry-After` | No assessment or evidence extraction/provider call; not converted to learner failure. |
| Overall request deadline/unexpected infrastructure error | Existing sanitized 504/500 conventions | No partial streaming response, stack trace or provider/repository detail. |

Every row requires `private, no-store`, including errors from middleware. Mock
delivery is explicitly a test fixture; deterministic fallback must not be labeled
as an explanation generated by a live model. A supported grounding state can
describe a wrong prediction or failed execution. Neither delivery failure nor
missing instrumentation changes correctness or competency.

## 11. Regression strategy and execution evidence

No tests are added or changed in this architecture milestone. Existing tests are
inspected to ground the design, and selected existing tests are run only to
verify current claims. Future tests below are requirements, not passing results.

| Future group | Required cases | Existing evidence to retain / new coverage needed |
| --- | --- | --- |
| Authentication | Valid guest/account; expired/exact-expiry/malformed Principal; invalid account snapshot; invalid supplied Bearer never downgrades. | Retain JWT, accounts and feedback service tests. Add full future-route tests with real dependencies, not only overrides. |
| Credential lifecycle | Revoked/changed credential, guest claim, account disable, learner-role removal and mapping change while provider blocked; expiry on every fallback/insufficient branch. | Existing expiry and claim tests cover components only. New release-time DB race tests required. |
| Authorization | Correct owner, foreign/unknown/forged UUID, ownership/pin change between each read, unauthorized lesson and guest-to-account same historical learner. | Existing owner/pin/claim regressions; new public release fence and replay-access cases. |
| Early visibility | Both correct/incorrect predictions before any attempt; no correctness in sections/state/labels/notice/timing-dependent provider activity. No window/as-of/focus manipulation. | Internal prediction-only test intentionally reports accuracy; new public non-disclosure tests mandatory. Explicit legacy progress-null test also required. |
| Post-attempt visibility | Submitted/unexecuted mapping, pending run, failed verification, successful correction and first successful repair distinct from original prediction. | Existing Notes/Tasks integration scenarios; future response projection tests for approved gate and unknown execution. |
| Partial/empty/error | No observations, empty cohort, auxiliary-only cohort, context overflow, corrupted/missing record, runtime/readback outage. | Retain evidence-integrity and policy tests; assert public state/delivery/availability distinctions. |
| Assistance/hints | Request only, failed/pending delivery, earlier out-of-window delivery, equal timestamps, late delivery, three exhausted hints, terminal/new-vs-saved retry. | Existing policy/tutor transaction cases; public next-action allowlist and no hint-text/metadata leakage are new. |
| Recall/transfer | Upcoming question hidden, past recall correctness auxiliary only, unchanged +1/+7 due boundaries, completed Tasks and missing Notes parent. | Existing transfer/retrieval and feedback policy tests; public alias/history visibility checks new. |
| Provider integrity | Valid plain/concise choice, malformed/oversized/duplicate/nonfinite output, unsupported competence/score, prompt injection, timeout/refusal/exception, safe full fallback. | Existing validator/provider/service/evaluation suites; reassert all at new response boundary. |
| Citation integrity | Unknown and unrelated-but-valid evidence substitution, changed lesson digest/version, dropped support, nested assistance/recovery support. | Existing exact per-claim tests; add alias substitution/dangling alias/digest/public-navigation tests. |
| Privacy | No raw owner/account/sourceUUID/source-kind/DB-version-ID/private hash/expected values/code reasoning/hint text/provider metadata in any serialized result/error/log. | Existing minimization/logging tests plus strict serialized-public-DTO absence assertions and canary values. |
| Replay/idempotency | Repeated ID with same/other session/owner, changed history and revoked identity; no exactly-once promise or authenticated-cache bypass. | Current equal-output test explicitly calls provider twice. Future route limits/release checks required. |
| Rate/resources/concurrency | Disabled/insufficient/overflow paths counted; per-learner and global limits; bounded in-flight work; no DB scope across blocked provider. | Existing shared-client accounting and real SQLite independent-write tests; pre-extraction caps and max-history resource tests new. |
| HTTP/cache/errors | No-store on all statuses, Origin/client-header enforcement, no ETag/304, no body logs, safe validation/errors, unexpected timeout paths. | Existing middleware/error/origin tests; new feedback-boundary all-status header tests. |
| Regression | Notes, Tasks, progress, hint reservation/concurrency, retrieval, ownership, migration history, evidence extraction and feedback policy unchanged. OpenAPI snapshot addition only when route authorized. | Current 21 paths/23 operations must remain unchanged for this review. Future endpoint requires reviewed contract regeneration, not silent snapshot replacement. |

Phase 3.5B's freshly executed prerequisite results remain **2,635 passing tests,
97.39% coverage**, Ruff/formatting across 203 Python files, mypy across 134 source
files, exact OpenAPI 21 paths/23 operations. These are the preceding
implementation's full validation results, not a newly executed full suite for
this document. Source/test bytes were compared with that validated snapshot
before publication. Its one pre-existing timeout-duration outlier and successful
targeted rerun are recorded in `evidence-grounded-feedback-v1.md`.

Review-specific targeted execution results are recorded in section 15. Tests
run in the existing isolated validated
checkout, using the already installed Python environment, disposable fixtures
and fake/in-process transports. No real environment file/database is copied or
migrated, and no dependencies or provider SDKs are installed.

## 12. Implementation milestones and dependencies

All steps below need a separate authorization; this document does not start them.

1. **Approve visibility and audience policy.** Decide first-attempt versus stricter
   post-execution availability, guests, terminal reflection/next actions, recall
   inclusion and tolerated auth freshness. Freeze concrete public schema/error
   semantics and operational limits before building a route.
2. **Implement internal release authorization and evaluation fence.** Add a
   read-only current credential/account/learner/session/pin adapter plus a small
   evaluation envelope that binds the actual existing evidence extraction to a
   frozen cohort. Keep two-system evidence duplication out. Prove revocation,
   ownership, stage-change, transaction and blocked-provider races first.
3. **Implement pure public visibility/projection.** Empty-body request DTO,
   explicit public response allowlist, whole-claim policy, citation aliases and
   public-only digest/copy rules. Prove early-answer protection and all leakage
   tests without any public route. Retain internal exact-citation validator.
4. **Implement operational boundary controls.** Approved per-learner/global
   limits, deadline/concurrency behavior, coarse errors and all-status no-store.
   Cover disabled/insufficient paths and expected maximum source histories.
5. **Authorize and add the dedicated authenticated operation.** Compose existing
   Principal/dependencies with steps 2–4. Run real-DB auth/claim/race tests and
   existing API/runtime regressions; deliberately review OpenAPI/client contract
   delta. Leave existing progress and hints untouched.
6. **Deployment/rollout review.** Approve activation controls and aggregate limits
   for actual worker topology. A learner UI, live provider, SDK/models/credentials,
   provider identifier minimization, scoring and progression remain separate
   milestones; none is a prerequisite for this architecture document.

No database migration is currently justified for the proposed read-only
projection. If future exactly-once paid operations or durable audit/cache policy
requires persistence, review it separately with additive migration/idempotency
tests; do not silently introduce it while adding a presentation endpoint.

## 13. Open decisions requiring explicit approval

1. **Disclosure stage:** recommended minimum first submitted attempt, matching
   existing progress; choose whether launch should instead wait for a finalized
   execution. Existing routes must not silently change either way.
2. **Audience:** support authenticated guest credentials as existing learner
   routes do, or require an account. No current feedback route enforces either.
3. **Guidance policy:** allow only the existing generic nonterminal code/schema
   comparison, omit `next` entirely initially, and whether terminal reflection is
   permitted. No new specific hints or private repair mapping is proposed.
4. **Recall inclusion:** include only already-disclosed past recall facts in
   session feedback, or keep all recall feedback on its current surface.
5. **Authorization freshness:** approve fresh local release checks and the
   residual post-decision race; decide any stronger remote JWT revocation policy.
6. **Operations:** exact rate/window/global concurrency values, worker topology
   and aggregate-limit ownership; whether any future paid-call deduplication is
   actually required. No arbitrary production numbers are installed.
7. **Public contract:** approve dedicated retryable POST, no client windows or
   Idempotency-Key semantics, full-session 64-record fail-closed cohort,
   not-ready/state separation, stale 409 and coarse unavailable mapping.
8. **Citation/digest policy:** approve response-local aliases and public-only
   digests; separately approve future transport identifiers/retokenization before
   any live provider receives context.
9. **Legacy privacy discrepancy:** decide whether existing expected/observed run
   details and fixture metadata need their own compatibility review. They are
   deliberately not revised by this proposal.

## 14. Instrumentation limits and implemented-versus-proposed boundary

The six categories remain prediction, investigation, modification, debugging,
verification and transfer. This is a taxonomy, not six measured scores.

- Investigation actions/code-reference selection are not recorded.
- Attempts record finite mappings, not actual submitted code patches/diffs.
- Failed-then-changed-and-passed establishes chronology, not diagnosis.
- No authoritative independent-work proof exists.
- Authored-help consumption, external help and some historical exact hint
  request times are not observable. Delivery proves finalized guidance, not
  reading, comprehension or causal effect.
- Tasks has no exact parent Notes-session/version linkage. Do not infer one from
  the first/latest Notes completion.
- Recall answers are auxiliary facts, not engineering competency or mastery.
- No learner interest taxonomy, skill level, score, mastery threshold or adaptive
  progression is introduced. Daily new-assignment quota and +1/+7 retrieval
  schedules remain untouched.

**Implemented and inspected:** internal evidence extraction, deterministic claim
authorization, bounded mock/disabled selection, exact citation validation,
safe complete fallback, initial owned/pinned reads and expiry snapshot checks.

**Proposed only:** public stage/audience policy, current-storage release auth,
evaluation fence, public DTO/citation aliases, ingress quotas/all-status
no-store and the dedicated endpoint. None of these future protections may be
claimed as active until implemented and regression-tested.

## 15. Final validation and preservation record

The existing review selection passed **315 tests in 70.29 seconds**, with zero
failures, errors or skips. This is targeted validation, **not a new full-suite
or coverage run**. It was executed with `pytest --no-cov`, existing configured
socket restrictions and a 30-second faulthandler diagnostic setting. No test,
assertion, coverage threshold or source file was changed. The preceding full
2,635-test/97.39% baseline remains the implementation validation evidence.

The 13 existing test files executed were:

- `backend/tests/unit/test_evidence_feedback_service.py`
- `backend/tests/unit/test_evidence_feedback_policy.py`
- `backend/tests/unit/test_evidence_feedback_validation.py`
- `backend/tests/unit/test_evidence_feedback_providers.py`
- `backend/tests/unit/test_jwt.py`
- `backend/tests/integration/test_accounts.py`
- `backend/tests/integration/test_evidence_feedback.py`
- `backend/tests/integration/test_evidence_feedback_lifecycle.py`
- `backend/tests/integration/test_legacy_contracts.py`
- `backend/tests/integration/test_legacy_replays.py`
- `backend/tests/integration/test_transfer_retrieval.py`
- `backend/tests/integration/test_tutor_transactions.py`
- `backend/tests/integration/test_api.py`

An initial invocation in the restricted sandbox stopped making progress as it
entered account integration tests and was terminated without a completed test
result. The first account case passed separately outside the sandbox in 1.13
seconds; the identical complete 315-test selection then passed outside it in
70.29 seconds. The exact cause of the stalled invocation is not established.
It is not counted as a successful run, a skipped test or a proven code defect.
The JUnit result is retained locally at
`C:/Users/soore/.codex/visualizations/2026/10/30/01a18c8a-4fc7-70a0-bf35-3113cfa88f29/trace-phase35b-e319f1e/backend/feedback-results/phase35c-review.xml`.

Final preservation comparison: **all 380 pre-existing non-log paths** retain
their SHA-256, size and modification timestamp. This includes source, tests,
frontend, migrations, `.env.local`, `backend/.env` and `backend/trace.db`.
This document is the sole added non-log file. The five canonical Phase 3.5A
source/test files and stored OpenAPI have no diff from `e319f1e` to the published
Phase 3.5B commit. The OpenAPI exact-match checks also passed in the targeted
suite: 21 paths, 23 operations.

Two independent read-only source/security reviews found no blocking factual
issue in the proposal. Their final state-mapping clarification is incorporated
in section 6. All named concrete test functions resolve in the repository.
Markdown has no trailing-whitespace lines; `git diff --check` passes.

Final branch and local/remote-tracking HEAD remain
`feat/phase-3-5a-engineering-evidence` at
`e82bbd737246dbd347e370f4668bde2003b044c4`. No tracked source changes or staged
files remain. The working tree contains this untracked document and the same
four pre-existing untracked suggestion artifacts; native shared logging is
preserved. No Phase 3.5C commit, push, PR or merge was performed. No application
implementation, dependency installation, live AI provider call, provider SDK,
credential, paid request or real database migration was used for the review.

Stop here for human architecture/security review. API, frontend, scoring and
competency-progression implementation require separate authorization.
