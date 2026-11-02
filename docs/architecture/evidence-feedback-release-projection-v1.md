# Evidence feedback release and public projection V1

## Scope and repository boundary

This report covers Phase **3.5C.1** (fresh release authorization and evaluation
fencing) and **3.5C.2** (public projection and local citation aliases).
Implementation, milestone gates and final full-suite validation are complete.
No public endpoint is implemented.

Work stays local on `feat/phase-3-5a-engineering-evidence` at
`3c547d847c3ab312d89375be49f68b13d2268f8d`. Preflight verified the remote head at
the same commit and found PR #11 had already been merged. No branch switch,
commit, stage, push, PR creation, merge, reset, stash or cleanup was performed.
Published commits `e319f1e`, `e82bbd7` and `3c547d8` remain preserved.

At entry, only genuine shared logs were tracked modifications. Four existing
suggestion artifacts and the local
`docs/architecture/evidence-feedback-learner-integration-v1.md` were untracked.
Those files are preserved. All four prerequisite architecture documents were
read and important guarantees checked against actual source.

## Phase 3.5C.1 — implemented

### Fresh storage authorization

`backend/app/repositories/feedback_release.py` defines a small read-only port.
`backend/app/db/feedback_release.py:SqlFeedbackReleaseRepository.read` authorizes
before looking up the owned session, using a single consistent SQLAlchemy read
with the existing SQLite `autocommit=False` transaction behavior.

Account checks use the current user, active status, learner role, exact
account-to-learner mapping, account creation identity and immutable auth-subject
bindings. Missing accounts/bindings or changed identities are rejected. Mutable
last-seen metadata is not part of the identity fingerprint.

Guest checks resolve the exact credential ID, current owner, revocation, expiry,
learner existence and absence of account claiming. Bare or ambiguous principals
are rejected. The stable credential fingerprint includes its identity, owner,
creation time and token hash; it does not expose those values or mistake harmless
renewal for identity reassignment.

The caller still obtains its `Principal` from existing authentication. The new
port does not verify a raw Bearer token itself and is not an alternate login
mechanism. It does not claim immediate remote Supabase token-revocation checks.
Current local eligibility and expiry are checked; the established JWT boundary
continues to provide signature/claims/expiry validation upstream.

No bootstrap, learner creation, write gate, insert/update/delete, migration or
new database table is used by this read path. Owned and missing foreign sessions
retain the same sanitized not-found behavior. Real database tests check the
absence of DML and prove unrelated writes can commit while a provider is blocked.

### The actual evaluated bundle

`backend/app/services/feedback_release.py:FeedbackReleaseService.evaluate`
captures authorization, exact session/pin, public material, source state and
canonical evidence within that same short read. The existing
`EngineeringEvidenceService` is reused through a borrowed read-only repository;
there is no parallel evidence extractor or reconstruction from a later progress
response.

`backend/app/schemas/feedback_release.py` provides strict frozen values for:

- Fresh authorization observation, authentication mode, identity fingerprint and
  effective `valid_until` deadline.
- Explicit release scope, with disabled audience/reflection defaults.
- Session lifecycle and exact selected attempt/run metadata.
- The server-owned evaluation envelope and the final release-authorized result.

The cutoff is server-generated UTC. The event cohort is the full session up to
that cutoff, half-open, with the existing 64-record feedback bound. The caller
cannot choose correctness, evidence, version, focus, record limits or timestamps.
Request identity is generated internally.

The supported legacy lesson must match the exact stored version ID, canonical
digest, approved public fields and legacy private definition. New/unapproved
blueprints or versions cannot replace historical definitions. An owned
unsupported version produces no evaluation; invalid trusted material cannot
produce factual feedback.

Before the first legitimate attempt, the service does not call the extractor,
calculate prediction accuracy, construct a provider plan or invoke the provider.
It returns a release-checked `not_ready` result. Source hashing for freshness
does not compare a prediction with an answer key.

### Two complementary fences

The envelope binds the exact canonical evidence cohort and the deterministic
policy plan. The schema rederives that plan with the existing policy builder and
checks selected attempt/run identity, timing and observed outcome. Recomputed
checksums do not make contradictory selected metadata or invented copy valid.

A separate current source-head fingerprint covers session/definition,
prediction, attempts, pending and finalized runs, checks, runtime readback,
hint reservations/deliveries and linked recall records. It includes source
changes after the original cutoff, which a cutoff-limited evidence query alone
would miss. Source lists are ordered deterministically. Private source text is
hashed transiently and is not copied into the envelope or provider context.

The encoding uses sorted compact JSON, UTF-8, finite supported primitives and
UTC microsecond timestamps. Source rows are ordered by stable identity before
hashing. Unrelated learning events and account activity timestamps are excluded.
The 10,000-source guard never silently truncates; an unfenceable source manifest
does not produce a released result. Existing list materialization is not SQL
pagination; operational resource controls remain a later milestone.

### Evaluation and release

The small additive `EvidenceFeedbackService.evaluate_prepared` seam invokes the
existing provider/selection validator/renderer over the captured plan, with no
repository scope. Legacy `feedback(principal, query)` keeps its original API and
snapshot/expiry behavior. Future learner integration uses the secure facade,
not direct exposure of that legacy internal method.

All provider success, timeout, exception, malformed-output and deterministic
fallback paths finish with a fresh read. The same applies to not-ready,
unsupported and unavailable-source short circuits. Authorization errors take
precedence over provider fallback. Session, identity, scope, source-head and
canonical cohort changes reject the result; stale feedback is not silently
reused or retried in a provider loop.

Effective expiry is the minimum of principal expiry and, for guests, both the
credential snapshot and current storage deadline. Known expiry is checked after
initial capture before provider work, after the final read, after release-result
validation and again after public projection. No database context spans provider
execution.

### Release boundary and residual race

The final consistent storage snapshot establishes authorization and history at
that read's observation point. `observed_at` records the read-start observation;
`released_at` records the subsequent decision after the read closes. Known
expiry is checked again at CPU handoffs without reopening a provider/read loop.

Commits after the final storage snapshot can revoke access or add history during
bounded validation/projection CPU work or a later network handoff. These checks
cannot retroactively retract an already emitted result. No continuous
authorization, lock-across-network or immediate remote token-revocation guarantee
is claimed. No HTTP response is emitted by this milestone.

## Phase 3.5C.2 — implemented

### Explicit public contract and policy

`backend/app/schemas/public_feedback.py` defines a separate
`evidence-feedback-public-v1` response. It never serializes an internal
`FeedbackReply` with an exclusion list. Public values reject unknown fields,
coercion and forged nested typed copies, and remain frozen.

The public schema separates availability, feedback grounding and delivery:

| State dimension | Values / meaning |
| --- | --- |
| Availability | available, not_ready, not_supported, unavailable |
| Grounding | supported, partially_supported, insufficient_evidence, unavailable; null when unevaluated |
| Delivery | deterministic, explicitly labeled mock, unavailable |

Closed/unavailable responses have constant safe notices, no lesson/time payload,
no sections and no citations. A failed verification can support factual feedback;
an infrastructure error or absent observation is never a learner-failure grade.

`FeedbackVisibilityPolicy` is a versioned server contract with required audience
scope, reflection setting, recall setting, finite next-action IDs, mock-delivery
permission and approval-reference metadata. An approval reference is not an
authentication credential or a self-proving production approval.

The default policy has no enabled audience, no terminal reflection, no next
actions and no mock delivery. Recall cannot be enabled in this version.
Proposed policies in tests do not register or activate a production policy.

### Whole-claim projection

`backend/app/services/public_feedback_projection.py` revalidates the released
bundle and exact policy scope, then explicitly constructs approved public fields.
It retains only finite known claims. Hidden claims are removed in full; dependent
recovery/transfer/explanation claims and orphaned citations are also removed.
Grounding is never upgraded, and absence of a permitted competency fact cannot
leave a supported result containing only neutral limitations or a next action.

Recall facts and hint-only auxiliary claims are excluded. Actual assistance
attribution remains tied to action provenance: delivery must precede the action
strictly; pending, failed, equal-time and late guidance do not prove assistance.
No hint text, reading/comprehension claim or independent-work conclusion is added.

Generic code/schema comparison is the only finite next-action identifier. It is
omitted without explicit approval. The imperative `receiving-contract`
explanation is also omitted when that permission is absent, preventing guidance
from bypassing the next-action gate. Terminal sessions never receive either
actionable claim, even in an explicit proposed reflection policy.

The actual Tasks result can be described, with the missing exact Notes-parent
link left unknown. The system still does not capture investigation actions,
submitted code patches, debugging diagnosis, independent-work proof, authored or
external help, or exact historical hint request times. All six competencies are
not thereby made measurable.

### Citations and public digests

Evidence citations use dense response-local `e1`, `e2`, etc.; lesson citations
use `l1`, `l2`, etc. They have friendly fixed labels and no source kind, source
UUID, stable evidence UUID, database version UUID or generic lookup endpoint.
An `e1` in a later response is not the identity of an earlier source. The same
spelling can be reused in another response; no cross-response identity or
stability is promised.

Only five check categories and their actual match booleans can be cited:
`http_status`, `api_response`, `validation`, `row_count`, `stored_values`.
No expected/observed raw values, response JSON, SQL rows or internal execution
diagnostics enter the public citation.

Public lesson identity contains the approved slug, semantic version and digest
of exactly these five public fields: title, objective, scenario, outgoing_code,
schema_code. The exact encoding is:

`json.dumps(five_fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")`

There is no trailing newline, BOM, Unicode normalization or private wrapper.
Lesson citations additionally bind the exact public field's UTF-8 SHA-256.
Notes/Tasks golden digests, key ordering, Unicode, normalization and newline
distinctions are tested. Private legacy definition hashes remain internal.

The exact regeneration validator rejects swapped-but-valid aliases, altered
text/checks/digests, missing support, duplicate aliases and dangling/orphaned
citations. Invalid citations are not deleted while retaining their conclusions.

Public JSON roundtrip tests exposed a nested strict timestamp issue caused by
the existing generic container pre-validator. The affected citation array uses
native tuple/JSON-array validation. Aware JSON timestamps roundtrip while Python
string/naive/integer/boolean timestamps remain rejected. Existing evidence/schema
contracts and global strictness were not weakened.

### Internal facade and application wiring

`backend/app/services/learner_feedback.py:LearnerFeedbackService.feedback`
accepts an authenticated principal and session UUID only. It connects fresh
authorization, stage gating, evidence evaluation, release fencing and pure public
projection. It checks known expiry once more after projection/validation.

New internal dependency getters compose the facade from the existing database
and application-scoped feedback provider. The shared AI client is reused and
disposed by its established lifecycle. Default wiring explicitly uses the
disabled visibility policy. No new public endpoint or route calls this facade.

Raw account/source IDs, private definition hashes, evaluator values, submitted
reasoning, raw response payloads, hint text, model/provider metadata and internal
fallback codes are absent from public serialization. Existing legacy learner
run/hint responses are not silently redesigned by this safer new contract.

## Files

Modified existing source:

- `backend/app/services/evidence_feedback.py` — additive prepared-plan seam.
- `backend/app/api/dependencies.py` — disabled internal composition only.

New application files:

- `backend/app/repositories/feedback_release.py`
- `backend/app/db/feedback_release.py`
- `backend/app/schemas/feedback_release.py`
- `backend/app/services/feedback_release.py`
- `backend/app/schemas/public_feedback.py`
- `backend/app/services/public_feedback_projection.py`
- `backend/app/services/learner_feedback.py`

New tests:

- `backend/tests/unit/test_feedback_release.py` — 134 cases.
- `backend/tests/integration/test_feedback_release_authorization.py` — 58 cases.
- `backend/tests/integration/test_feedback_release_races.py` — 89 cases.
- `backend/tests/unit/test_public_feedback_contracts.py` — 160 cases.
- `backend/tests/unit/test_public_feedback_projection.py` — 56 cases.
- `backend/tests/integration/test_learner_feedback.py` — 29 cases.

New documentation: this report. The earlier local Phase 3.5C review is unchanged.

## Executed milestone validation

| Gate | Actual executed result |
| --- | --- |
| Fresh prerequisite full suite | 2,648 passed in 585.42 seconds; 97.39% coverage |
| Prerequisite static/OpenAPI | Ruff/format 203 files; mypy 134 sources; exact 21 paths/23 operations |
| Legacy prepared-seam regression | 74 passed in 15.90 seconds |
| C1 final focused | 207 passed in 76.04 seconds |
| C1 related regression | 1,073 passed in 213.38 seconds; subsequent final handoff guard covered by the complete 207-case focused gate |
| C2 focused unit | 208 passed in 5.08 seconds |
| C2 actual-runtime integration | 29 passed in 19.14 seconds |
| C2 combined related regression | 1,312 passed in 243.79 seconds |
| Final Ruff/format | Passed across 216 Python files |
| Final mypy | Passed across 141 source files |
| OpenAPI with new DI | Exact stored-contract equality: 21 paths, 23 operations |
| First full implementation run | 3,092 passed in 657.65 seconds; 96.67% coverage |
| Supplemental auth/public/projector guard run | 274 passed in 55.60 seconds, measured against unchanged application source |
| Supplemental envelope/source guard run | 134 passed in 27.73 seconds with coverage; separate normal focused run 134 passed in 8.20 seconds |
| Final fresh full suite | **3,174 passed in 668.14 seconds; 97.62% coverage; zero failures, errors or skipped tests** |

All tests use the existing locked Python environment and an isolated tracked
snapshot plus intentional changes. Real `.env` files and the learner database are
not copied. Migration fixtures and runtime writes target disposable databases.
No dependency or provider SDK is installed and no live/paid AI request is made.

The final new tests add 526 cases: 281 for C1 and 245 for C2. Earlier failures were investigated and repaired:
the final-read clock observation exposed the missing effective deadline checks;
rehashed selected metadata exposed semantic envelope gaps; JSON roundtrip found
the public timestamp bug; new assistance assertions were bound to the actual
approved claim/role/citation instead of assuming only the concise wording. No
existing assertion, coverage threshold or test was weakened or skipped.

## Final full validation and preservation

The first complete run passed but reduced overall coverage to 96.67%. Review of
uncovered new code found worthwhile semantic rejection cases. Another 82 tests
were added, without changing application code or thresholds: malformed and
ineligible authentication, rehashed but contradictory evaluation/release values,
source failures, private citation substitution, unknown claims, unapproved
versions, and public payload/section limits. These test the intended security
properties rather than bypassing validators to reach implementation details.

Accumulated execution against the unchanged application yielded a 97.62%
coverage preview. That preview combined actual runs and was not represented as a
new full-suite result. The subsequent fresh complete suite independently passed
**3,174 tests in 668.14 seconds**, with **97.62% coverage** (97.62362792802988%
unrounded), zero failures/errors/skips. This is **0.23 percentage points above**
the freshly reproduced 97.39% prerequisite baseline.

The final JUnit report contains all 281 C1 and 245 C2 cases, plus the original
2,648 tests. It includes 29 migration/upgrade/downgrade-named cases and the
existing ownership, security, transaction/concurrency, Notes/Tasks runtime and
retrieval regressions. No single final test case exceeded 6.55 seconds. Overall
runtime differences are not a benchmark or proof of a performance change.

Final lint/format checks pass for 216 Python files; mypy passes for 141 source
files. Generated OpenAPI still equals the stored document exactly: 21 paths and
23 operations. There are no database migrations, SQL model changes, frontend
changes or dependency changes.

The 15 application/test paths match the validated isolated snapshot byte for
byte. Of 381 pre-existing non-log paths, 379 retain their original SHA-256, size
and modification time; the only intended existing-file changes are the two
integration files listed above. The 13 new Python files and this new report are
the only additional non-log deliverables. Real `.env.local`, `backend/.env`,
`backend/trace.db`, migration files, legacy lesson/evaluator/runtime definitions
and the original local Phase 3.5C review remain unchanged. Shared logs and all
four original suggestion artifacts are preserved.

The final privacy review found no credential or email candidates in the 16
deliverable files. No native logs were manually reconstructed. Nothing is staged;
HEAD remains `3c547d847c3ab312d89375be49f68b13d2268f8d`. No commit, push, new PR or
merge was made. No live provider, real provider credential, SDK installation or
paid API request was used.

Status: **Phase 3.5C.1 complete; Phase 3.5C.2 complete**, with production policy
paths disabled pending approval. Stop here; operational security, HTTP exposure,
frontend integration and progression remain separate authorizations.

## Disabled and future work

Production audience, terminal reflection and generic next-action approval remain
unresolved and disabled. Recall remains excluded. The facade is an internal
integration foundation, not an active learner-facing feature.

Operational ingress quotas, rate/concurrency policy, all-status HTTP no-store
handling, caching, a public endpoint and frontend integration require separate
milestones. Immediate remote JWT revocation policy and any future live provider
configuration/identifier minimization also need separate review. No scores,
mastery/progression, new assignments, retrieval rescheduling or creator workflow
is introduced here. The existing +1/+7 retrieval schedule is preserved.
