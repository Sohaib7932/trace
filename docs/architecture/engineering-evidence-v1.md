# Engineering evidence V1 — Phase 3.5A

## Scope and repository boundary

Latest fetched `main` is `897bd02fc23006a9254bccb997f4134eebadf29b`.
Both required merge commits are verified ancestors: PR #8
`5345c9e16143e9728a938f3f03be2a4f07b70c39` and PR #9
`897bd02fc23006a9254bccb997f4134eebadf29b`. The merged tree includes the
Phase 3.2–3.4 services, migrations `0006`/`0007`, and CI repair
`0b3ba09d44b26d18158cac0cdb376998ff150cdf`.

The previous checkout at `0b3ba09` had an identical tracked tree. The requested
branch `feat/phase-3-5a-engineering-evidence` was therefore created from verified
`origin/main`, carrying existing local work safely. SHA-256, size and modification
time of all 368 protected tracked/untracked/environment/database paths matched
before and after that switch. No stash, reset, clean, commit, push or merge was
used for this milestone. Existing uncommitted Phase 3.5A files were extended in
place rather than discarded.

Before extending the implementation, the fresh isolated merged-main baseline
passed **1,925 tests in 400.71 seconds, with 97.17% coverage**. Ruff lint and
formatting passed across 182 Python files; mypy passed across 125 source files.
The earlier 1,921 baseline predates the four regression cases in the merged CI
repair and is not the baseline for this delivery.

This milestone adds a read-only, internal projection over existing learner
records. It adds no evidence table, migration, event writer, backfill, public
endpoint, scoring, AI grading, frontend integration or automatic assignment.
The existing eight-count personalization contract remains intact.

See [engineering-evidence-sources.md](engineering-evidence-sources.md) for the
actual API/service/repository/database/evaluator map and Notes/Tasks matrix.

## Contracts and internal use

`backend/app/schemas/engineering_evidence.py` defines frozen, strict values with
unknown fields rejected and input values hidden in validation errors:

- `Competency`: `prediction`, `investigation`, `modification`, `debugging`,
  `verification`, `transfer`.
- `EvidenceQuery`: authenticated internal learner UUID, one session UUID,
  explicit half-open event window, `as_of` and combined observation limit.
- `LessonPin` and `RetrievalQuestionPin`: exact supported legacy definitions and
  question digests. Unassigned 1.1.0 blueprint candidates are never associated
  with historical 1.0.0 learner sessions.
- `SourceReference`, `ObservedCheck`, `AssistanceContext`: typed immutable record
  references and minimal factual details, without raw learner/provider content.
- `EngineeringObservation`, `HintEvidence`, `RetrievalEvidence`,
  `EngineeringEvidenceBatch`: version `engineering-evidence-v1`, event/source
  classification consistency, ownership, time bounds, bounded collections and
  duplicate protection.
- `EvidenceCoverage`: exactly six server-controlled instrumentation descriptors,
  with direct/partial/unavailable support, finite limitation codes and a factual
  `observed_in_window` flag. A batch always retains its exact lesson pin, even
  when its event cohort is empty.

The internal call is
`EngineeringEvidenceService(existing_learning_repository).extract(query)`.
Its caller supplies the learner ID from the established authenticated principal,
never an owner claimed by a client. The service has no creation method and no
route accepts evidence, competency labels, correctness or verification claims.
Schema validation alone is not authorization or proof of database provenance.

The extractor freshly revalidates query values, enters `repository.read()` and
checks `owned_session` before reading child sources. It resolves the session's
exact `lesson_version_id`, validates its supported identity/version and recomputes
the existing legacy canonical hash against the actual catalog. It never resolves
the latest lesson or promotes a candidate. The existing database configuration
uses `autocommit=False`, providing a consistent read transaction without taking
the learner write gate.

Every original source comes from the repository, not request payloads. Cross-
session child references, duplicate identities, malformed timing, invalid hint
joins, unsupported versions, incorrect hashes and inconsistent runtime evidence
fail closed with a sanitized `evidence_integrity` error. Foreign and missing
sessions share the existing `not_found` behavior. Output overflow returns
`evidence_limit`; history is never silently truncated.

The output limit is 1–10,000 combined observations, hint events and retrieval
events. The six coverage descriptors do not consume that event budget. A separate
10,000-source guard bounds validated source records. Existing repository methods
materialize their selected lists before this guard; this is not SQL pagination
or a new scalable cross-session history selector. An authenticated cohort policy
and paginated selector would require a subsequent milestone.

## Observable facts and interpretation limits

| Event | Competency | Result and limitation |
| --- | --- | --- |
| `prediction_submitted` | Prediction, direct | Selected outcome compared with the pinned private answer; no answer key or reasoning is returned. Correct selection is not conceptual mastery. |
| `modification_submitted` | Modification, direct | A finite mapping was submitted; outcome remains unknown under this immutable event. Subsequent verification references that attempt separately. There is no submitted code patch. |
| `verification_finished` | Verification, direct | Actual passed/failed/error run becomes success/failure/unavailable, with its original check references. Pending runs yield no finished event. |
| `debugging_recovery_observed` | Debugging, indirect | An earlier failed run completed before a changed, later attempt that passed. Both original attempts/runs remain referenced. Diagnosis, insight and blind retries are indistinguishable. |
| `transfer_completed` | Transfer, direct | A completed Tasks session and successful runtime, pinned to its own exact lesson. The legacy source Notes-session relationship was never stored, so none is invented. |

Investigation has a stable taxonomy entry but no generated observation: current
learner workflows do not capture investigation actions or selected code references.
Empty observations mean absence of supported observations in that cohort, not a
zero competence score. Infrastructure errors never become learner failure.

`retrieval_answered` is auxiliary `RetrievalEvidence`, with its original answer
source, checkpoint reference, exact question pin and recorded correctness. It
has no competency, basis or verification-check fields. The existing retrieval
questions disclose a rejection or ask which mapping satisfies a contract; they
do not establish a before-result prediction or prove implementation competence.
These facts never increase competency observation presence. Their existing
correctness, completion records and +1/+7 schedule remain unchanged.

## Explicit instrumentation coverage

Coverage describes what the current source records can establish, not a learner
score, success, skill level or mastery claim. `observed_in_window` is true only
when an actual competency observation exists in the selected cohort, including
an unavailable verification outcome. Auxiliary hint/retrieval facts do not set
this flag. Empty cohorts retain the complete profile with every flag false.

| Competency | Notes support | Tasks support | Explicit limitation codes |
| --- | --- | --- | --- |
| Prediction | direct | direct | `selected_outcome_only` |
| Investigation | unavailable | unavailable | `investigation_not_recorded` |
| Modification | partial | partial | `finite_mapping_only`, `code_patch_not_recorded`, `runtime_outcome_separate` |
| Debugging | partial | partial | `recovery_chronology_only`, `diagnosis_not_recorded` |
| Verification | direct | direct | None; individual outcomes/checks retain their actual runtime limits |
| Transfer | unavailable | partial | Notes: `outgoing_transfer_not_recorded`; Tasks: `exact_notes_parent_not_pinned` |

The batch validates the exact fixed profile against its pinned lesson, all six
unique categories, and each observation-presence flag. Unavailable support cannot
claim an observation. These descriptors have no source IDs or event timestamps:
they are metadata about instrumentation, not invented learner history. No new
database events are created merely to fill a matrix.

The five original categories remain exactly `http_status`, `api_response`,
`validation`, `row_count`, `stored_values`. Their origins remain `asgi_http` and
`fresh_database_read`. Execution-only errors retain their original `execution`
check from `verifier` or `server_lifecycle`; five artificial checks are not added.

The extractor checks saved observations against the trusted existing evaluator
and independently persisted runtime rows without starting another execution.
Per-category flags are checked against available saved facts. An original failed
database read remains unavailable even if a committed row is readable today.
The transient observation's response ID was not separately persisted: malformed
response error records may retain a stored-values correlation decision that
cannot be reconstructed from their raw JSON. For that unavailable result only,
the original check is preserved and bounded by the independently stored trusted
values; it cannot establish a successful verification or a learner grade.

Retrieval extraction checks question identity/hash, source Tasks session,
ordinal, unchanged +1/+7 due timestamp, answer correctness and checkpoint
completion consistency. It does not reschedule anything or consume daily quota.

## Assistance and historical identity

`hint_requested` references the exact reservation at its request timestamp with
outcome `requested`. `hint_finalized` references the immutable interaction at
finalization with outcome `delivered` or `error`. They have different stable
UUID5 identities. Finalization adds a new event; it does not mutate a request
event from pending to delivered. Legacy interactions without reservations yield
only finalization evidence, never a fabricated request timestamp.

Reservation and final interaction identity/session/attempt/sequence/key/time must
agree. `Attempt.hints_before` is a request count including pending/errors; it is
never used as proof of delivered help. Only nonempty delivered guidance strictly
before the original action establishes `tutor_assisted`. Equal timestamps do not
establish causal order. Verification/recovery/transfer use the original mapping
submission time for assistance, not the later execution completion time.

Prior guidance remains available to later attempts in the same session. An
attempt cannot revert to independent because it requested no additional hint.
Otherwise assistance stays `unknown`, including requested-but-undelivered help,
failed tutoring and absent delivery instrumentation. `independent` and
`authored_hint_assisted` are reserved vocabulary rejected by the current contract
because no authoritative record establishes either claim. External assistance
and authored-hint views remain unobservable. Retrieval assistance stays unknown;
old Tasks guidance is not reclassified as help for a later recall response.

Stable evidence IDs derive from schema version, event type, source kind and
source UUID. Source tables already preserve immutable predictions, attempts,
checks, interactions and finalized runs. No duplicate persistence is necessary.
Later attempts and deliveries cannot change earlier observations; source reads
are sorted deterministically by UTC event time and stable ID. Guest-to-account
claiming retains the same learner UUID and original sources.

## Files and preservation

New application files:

- `backend/app/schemas/engineering_evidence.py`
- `backend/app/services/engineering_evidence.py`

New tests:

- `backend/tests/unit/test_engineering_evidence_contracts.py`
- `backend/tests/unit/test_engineering_evidence_sources.py`
- `backend/tests/integration/test_engineering_evidence.py`

New documents: this report and `engineering-evidence-sources.md`.

No pre-existing application, test, frontend, migration or dependency file is
modified for Phase 3.5A. Existing environment/database files and shared logs are
preserved. There are no provider SDKs, credentials, live AI calls or paid usage.
All runtime fault/concurrency tests use controlled deterministic implementations.

## Remaining instrumentation

Explicit investigation actions, actual code-diff provenance, trusted debugging
diagnoses, an exact source Notes-session transfer link, authored-help delivery,
external-help visibility and historical exact hint requests remain missing.
Competency scores, progression policies, mastery thresholds and AI feedback
require later review. Phases 3.5B–3.5D are not implemented here.

## Validation

The earlier uncommitted implementation passed 2,230 tests at a 1,921-test base,
with 97.33% coverage. Those are historical results. The merged CI repair added
four baseline regressions, and this review corrected recall classification and
explicit missing-instrumentation metadata. Current gates are recorded separately:

| Gate | Executed result |
| --- | --- |
| Fresh merged-main baseline | 1,925 passed in 400.71 seconds; 97.17% coverage |
| Merged-main static baseline | Ruff/formatting passed for 182 files; mypy passed for 125 sources |
| Current focused evidence tests | 378 passed in 39.96 seconds: 188 contracts, 140 source-integrity, 50 real-runtime integration cases |
| Current full backend regression and coverage | 2,303 passed in 399.25 seconds; 97.35% coverage, up 0.18 percentage points; zero errors, failures or skipped tests |
| Current Ruff / formatting / mypy | Passed: 187 Python files formatted/linted; 127 source files type-checked |
| Current OpenAPI comparison | Exact stored-contract match: 21 paths and 23 operations |
| Preservation | All 368 protected paths matched across the safe branch switch. Final comparison: only the seven intended Phase 3.5A deliverables changed; the other 361 paths retain their bytes, size and modification time |
| Git | `feat/phase-3-5a-engineering-evidence` at verified merged main; no staged files or Phase 3.5A commit/push |

The earlier implementation's initial focused run found two issues: a test
helper incorrectly rewrapped a UUID, and a malformed-response verifier fault
retained an observation ID that older persistence does not separately store.
The original assertions were preserved. Independent review also caught the
unavailable-readback/committed-row distinction and per-check flag consistency;
both received targeted regression coverage.

Current validation uses an isolated tracked snapshot of the verified merged
commit, with real `.env` and `trace.db` absent, and the already installed locked
Python environment from the CI investigation. No dependencies are installed.
Existing Alembic upgrade/downgrade, ownership, security, tutor concurrency and
preservation tests use disposable fixture databases. The prior security and
source-integrity guards are retained. Earlier assertions that mislabeled recall
answers as prediction evidence are replaced with stronger auxiliary-source,
question-pin and no-inferred-competency assertions.

The full JUnit report includes seven explicitly named migration cases, including
upgrade/downgrade and preservation guards, plus the existing database, ownership,
security and tutor concurrency suites. All passed against disposable fixture
databases. Coverage of the new schema module is 100%; extraction service coverage
is 98.34%. No coverage threshold or existing learner test was weakened. Relative
to the merged baseline, the three evidence test files add 378 cases; the revised
contract and missing-instrumentation checks increase the prior uncommitted
evidence test count by a net 69 cases.

Implementation status: **complete for Phase 3.5A**, with partial/unavailable
instrumentation explicitly represented rather than overstated as competence.
There is no new migration. The two application modules, three test modules and
two architecture documents listed above are the seven new files relative to
merged main; they were preserved and extended from existing local work.
All original application, migration, frontend, dependency, environment/database
and shared-log files retain their starting contents. Existing log modifications
and untracked log artifacts remain local; nothing is staged. HEAD remains the
verified merge commit and this task creates no commit, push, PR or merge.

Reproducible commands, from the isolated backend working directory with the
existing locked Python environment activated:

```powershell
python -B -m pytest tests/unit/test_engineering_evidence_contracts.py tests/unit/test_engineering_evidence_sources.py tests/integration/test_engineering_evidence.py --basetemp ../evidence-results/focused-temp -p no:cacheprovider -o 'addopts=' --junitxml ../evidence-results/focused.xml -q --tb=short
python -B -m pytest --basetemp ../evidence-results/full-temp -p no:cacheprovider -o faulthandler_timeout=30 --junitxml ../evidence-results/final.xml -q --tb=short
ruff check .
ruff format --check .
python -m mypy
```

The isolated `evidence-results/` holds `baseline.xml`/`baseline.txt` and, as gates
complete, `focused.xml`/`focused.txt`, `final.xml`/`final.txt` and `coverage.json`.
OpenAPI comparison uses Python values in memory without starting application
lifespan or connecting to the development database.

The shared log and four pre-existing untracked suggestion-only log artifacts
remain untouched by implementation work. Native logging may capture genuine
user prompts/final answers; no pending final response or subagent conversation is
fabricated. There are no Phase 3.5A commits, pushes, PRs or merges. No live
provider calls, SDK installations, credentials or paid usage occurred.
