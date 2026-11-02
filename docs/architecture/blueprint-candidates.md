# Phase 3.2A — trusted lesson blueprint candidates

Status: **authored candidates pending independent human review**. Technical
validation does not approve a production lesson. Both envelopes permanently expose
`review_status="pending"`, `production_approved=False`, `release_eligible=False`.
There is no registry, seeding, publication, learner endpoint or assignment here.

## Independently authored definitions

- [Notes complete review snapshot](blueprint-candidates/notes-v1.json)
- [Tasks complete review snapshot](blueprint-candidates/tasks-nested-v1.json)
- Authoring source: `backend/app/blueprints/candidates.py`.

These complete definitions were authored from Trace's actual runtime and existing
V1 specification, without importing or copying any test lesson definition. Tests
verify the JSON review snapshots equal the strict canonical factory definitions.
The snapshots include private answers and runtime expectations for server review;
they are not learner projections or customer-support knowledge sources.

## Proposed identity and version

Both use specification version `1.0.0` and proposed lesson version `1.1.0`, keeping
the existing lesson IDs `fastapi-payload-mismatch` and
`fastapi-nested-payload-transfer`. The existing published legacy `1.0.0` content,
identities, hash algorithm and stored history are untouched.

Each candidate version UUID is deterministically derived as
`uuid5(NAMESPACE_URL, "trace:blueprint-candidate:{lesson_id}:1.1.0")`. This is an
explicit proposed candidate identity, not database allocation or publication.
Changing reviewed content later requires a separately reviewed versioning policy;
these factories do not authorize overwriting a published version.

Tasks is finalized first. Notes includes Tasks' exact lesson ID, version UUID,
version and canonical SHA-256 as its transfer target. Missing that complete target
remains an unavailable dependency under the existing candidate-validation gate.

## Source-of-truth review map

| Definition fact | Actual source |
| --- | --- |
| Existing lesson identities and educational scenario | `backend/app/services/catalog.py`; `backend/app/domain/transfer.py` |
| Notes title/content values | `NOTE_TITLE` / `NOTE_CONTENT` in `backend/app/domain/learning.py`; used by `AsgiNotesVerifier._request` |
| Tasks title/priority values | `TASK_TITLE` / `TASK_PRIORITY` in `backend/app/domain/transfer.py`; used by `AsgiTasksVerifier._request` |
| Exact bounded receiver schemas | `NoteCreate`, `TaskMetadata`, `TaskCreate` in `backend/app/verification/asgi_notes.py` and `asgi_tasks.py` |
| Initial body/flat and repaired content/nested mapping | Existing ASGI verifier payload builders and deterministic evaluators |
| Source artifact byte contracts / runtime family revisions | `backend/app/domain/lesson_spec/templates.py`; `RuntimeBinding` in `fields.py` |
| HTTP 422, missing/extra validation, zero rows | Actual Pydantic receiving-model validation and `evaluate` / `evaluate_transfer` |
| HTTP 201 and response schemas | Existing private `create_notes_app` / `create_tasks_app` routes |
| Committed writes and detached independent readback | `NotesService`, `TasksService`, `AsgiNotesVerifier.observe`, `AsgiTasksVerifier.observe` |
| Saved title/content/priority and response-row identity | `response_matches_fixture`, `response_matches_task`, `task_values_match`, existing evaluators |
| Five evidence categories and baseline/repair execution | Existing `IsolatedCandidateRuntime` and strict V1 verification policy |
| Authored-only tutoring, three progressive hints | Approved V1 `TutorPolicy`, existing bounded hint progression; no new live tutoring authority |
| Transfer-only Tasks and fixed Notes topology | Existing strict `LessonSpecV1` validation and original/transfer learner flow |
| Retrieval content, private answers, feedback and +1/+7 days | Unchanged `QUESTIONS` and `RETRIEVAL_DAYS` in `backend/app/domain/retrieval.py` |

The V1 word "fixture" names the trusted exercise's fixed input values. These
values come from the actual running verifier, not from test blueprint fixtures.
The ten-second verification budget matches the existing backend verification
default and V1's bound; it does not change learner runtime configuration.

New authored instructional framing includes objectives, checkpoint prompts,
progressive hints, misconception wording and trusted explanations. It states only
facts established by the sources above. No evaluator expression, arbitrary code
executor, database query or configurable executable structure is introduced.

## Existing validation boundaries

Explicit `notes_blueprint_candidate()` and `tasks_blueprint_candidate()` return
immutable review envelopes. Their `trusted_blueprint()` conversion validates
server-owned composition fields; "trusted" here identifies field authority,
not human approval. Candidate lifecycle services must retain the separate review
status and must not infer approval from that conversion or from a verified digest.

Validation uses existing strict schema checks, complete canonical SHA-256,
`TrustedLessonBlueprint`, `compose_lesson_spec`, `CandidateValidationService` and
`IsolatedCandidateRuntime`. Both baseline and repair profiles must execute through
the real private FastAPI exercise apps and check HTTP status, API response,
validation, row count and stored values, including independent committed readback.
Private-field changes remain invalid even when a changed definition has a fresh
canonical digest. All successful results remain unreleased.

The normal initial learner projection continues to exclude private evaluation and
verification data, future explanations, hints and canonical digest. No new public
projection or API is introduced.

## Human review checklist

1. Review the complete two JSON definitions and the source map above.
2. Confirm proposed identities/version and the exact Notes-to-Tasks digest pin.
3. Review authored prompts, hint progression, trusted explanations and misconception
   wording against the intended learning objectives.
4. Review baseline and repaired runtime receipts from isolated tests, including all
   five evidence categories and fresh database readback.
5. Preserve the existing +1/+7-day retrieval content and schedules.
6. Record approval through a separately authorized review workflow; do not turn
   these review files into a production registry or assign them to learners.

## Executed milestone validation

- 20 new unit tests passed: strict definition/canonical integrity, deterministic
  identity, exact JSON snapshot equality, immutable pending review status, source
  model behavior, retrieval preservation and initial learner projection boundaries.
- Seven new integration cases passed against the existing in-process Notes/Tasks
  ASGI runtime and candidate gate. Both rejection and repaired profiles satisfied
  all five evidence categories and independent database readback. Missing transfer
  targets remained unavailable, and a fresh digest did not permit private-field changes.
- Combined new tests and existing canonicalization/composition/candidate/runtime
  regressions: **278 passed in 27.69 seconds**.
- Ruff lint and formatting passed for all four new Python files; mypy passed for
  the two new application source files.

Execution used the existing isolated validation copy and disposable in-memory
exercise storage. No real learner database, migration, credential, live AI request,
published lesson or learner assignment was involved. The result is technical
validation of pending candidates; independent human approval is still required.
