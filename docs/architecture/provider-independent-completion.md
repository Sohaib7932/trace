# Provider-independent backend completion

## Starting state and scope

Work starts at Phase 3.1A commit
`eede2009e46b3ad249b1aea8991687a713f206ef` on the separate branch
`feat/phase-3-2-provider-independent-completion`. Phase 3.1A remains available on
its own remote branch and open PR #8. No rebase, merge, commit or push is part of
this task. The current shared session log and four pre-existing untracked log
artifacts were inspected and are preserved in place.

The starting protected inventory contains 304 pre-existing files, including real
environment/database files. Existing lesson versions/hashes, migration files,
frontend, canonicalization, admission and verification remain protected. Necessary
additive migrations run only in disposable test databases. Live LLM providers,
credentials, SDK installation, frontend changes, publication and assignment of
unapproved content remain outside this implementation.

## Ordered milestone gates

1. **3.2A — blueprint candidates:** independently author complete Notes/Tasks
   definitions from implementation facts; preserve pending review and unreleased
   status; validate strict schemas, canonical digests and real isolated runtime.
2. **3.2B — candidate lifecycle:** preserve immutable composition/provenance
   snapshots and append-only validation/review events. Run existing validation
   outside write transactions. Separate technical success from human review and
   explicit production approval; every state remains unreleased/unassigned.
3. **3.3A — tutor transactions:** reserve under the existing learner write gate,
   call the tutor outside it, finalize briefly and idempotently. Keep legacy hint
   DTOs and fixture policy, history, budget and causal assistance metrics intact.
4. **3.3B — application AI lifecycle:** own/reuse/dispose one explicit disabled or
   mock client per app lifecycle; inject only internal services; add no endpoints.
5. **3.4A — support readiness:** draft customer-safe documentation and deterministic
   retrieval evaluations. Drafts do not activate the approved-source corpus.
6. **Daily assignment readiness:** inspect timezone and assignment authority;
   prepare contracts where product decisions are missing, without fake enforcement.
7. **Personalization readiness:** map factual bounded evidence and prepare a
   proposal for unsupported profile/difficulty/interest decisions.
8. **Final regression:** execute full backend coverage, static checks, OpenAPI,
   migration/concurrency/security tests and protected-file comparison.

No dependent implementation begins before the preceding technical gate passes.
This document records the final decisions and evidence as milestones complete.

## Decisions already established by existing implementation

- Learning identity is a Trace learner UUID, either guest-owned or attached to a
  verified account. Account records contain no authoritative learner timezone.
- No new-exercise assignment model or assignment endpoint currently exists.
- Existing session creation and transfer/retrieval are not silently reclassified
  as new daily assignments.
- The future quota is at most three **new assignments** per learner-local day.
  Hints, explanations, retries, reviews and existing +1/+7 retrieval do not consume it.
- Retrieval remains +1/+7 days anchored to transfer completion. Day 3 is not adopted.
- The generation brief accepts bounded factual count summaries, but no interests,
  skill score, difficulty policy or free-form history.
- There is no approved interest vocabulary or support escalation destination.

## Validation evidence

The unchanged Phase 3.1A baseline was freshly reproduced in the isolated validation
copy: **1,601 passed in 236.84 seconds; 96.86% statement/branch coverage**.
The real environment/database files were not used. OpenAPI matched the stored
contract exactly (21 paths, 23 operations).

Phase 3.2A gate: **278 passed in 27.69 seconds**, including 20 new unit tests and
seven real ASGI/runtime/gate tests, plus existing canonicalization/composition/
candidate runtime regressions. Ruff lint/format passed for the four added Python
files; mypy passed for both new source modules. The complete JSON review snapshots
match the strict canonical definitions. See `blueprint-candidates.md` for source
facts, identities, digests and pending human review.

Phase 3.2B gate: **57 passed in 34.09 seconds**: 27 new unit tests, 18 new
persistence/runtime/concurrency tests, three new migration tests and nine existing
database/historical-migration regressions. The strengthened three migration tests
were rerun successfully in 2.73 seconds. Ruff passed for ten owned Python files;
mypy passed for six source files. Independent review found no actionable defect
in the trusted internal service boundary.

Migration `0006_candidate_lifecycle` adds only `generated_candidates` and
`candidate_lifecycle_events`, with immutable history, revision/key uniqueness,
state-chain and active-admin SQL guards. It preserves existing learner records;
empty downgrade works and populated candidate history refuses downgrade.

Lifecycle entry is successful admission and composition. Generated educational
content and the composed definition are stored separately in one immutable
snapshot, with request identity, original source/target definitions, canonical
digests, input fingerprints, transport metadata and a raw-output digest. Raw
prompts/completions are not stored. Admission failures create no candidate row;
candidate validation failures retain actual bounded rejection receipts.

Technical validation, human review and production approval are separate events.
Admin approval requires explicit source-digest attestation; mock-origin content
cannot receive production approval. A future provider-origin flag is an internal
server assertion, not cryptographic proof of a live call or a public request field.
No current disabled/mock application path produces live provenance. All states
remain unreleased, unpublished and unassigned. Pre-generation provider-job
idempotency remains a future live-integration concern, not a new paid-job wrapper.

Phase 3.3A gate: **25 new tests passed in 14.14 seconds**, plus **105 existing
regressions in 75 seconds**, covering hints, retries, ownership, legacy contracts,
account claims, pinned historical migrations, transfer and retrieval. Ruff and
mypy passed (nine applicable source files). Independent transaction/history review
found no actionable defect. Receipts: `completion-results/tutor-final.xml` and
`tutor-regression.xml` in the isolated copy.

Migration `0007_tutor_reservations` adds `hint_operations`, leaving delivered/error
`TutorInteraction` rows immutable. Reservation and finalization use short learner
transactions; the provider runs between them without the learner write gate. One
pending operation per session, unique request/sequence keys and result-binding
guards preserve identity and the three-request budget. In-flight retries return
the existing conflict response; finalized retries return the exact saved result.
An interrupted/expired request is finalized as error without reinvoking its tutor;
late workers cannot overwrite that result. Even an expired third-slot recovery
commits before returning the quota rejection.

The server Principal's existing expiry bounds the operation; expired authorization
does not receive a provider answer. Provider responses remain fixture-only. New
requests count immediately toward `hints_before` and progress, but delivery time is
recorded only when finalization succeeds. Thus guidance delivered after an attempt
cannot be mislabeled as assistance before it. Existing public schemas and authored
lesson-spec policies are unchanged. Empty downgrade works; reservation history
refuses destructive downgrade. No real database migration was run.

Phase 3.3B gate: **297 passed in 6.88 seconds**, including 27 new tests (15 unit
resource tests and 12 application lifecycle integration tests), plus existing API,
client, generation, tutoring and support regressions. Ruff passed for six owned
Python files; mypy passed for four applicable sources. Independent review found no
actionable defect. The exact stored OpenAPI comparison passed; there are still
21 paths and 23 operations.

`AIResources` owns one shared client and cached internal QuestionGenerator,
TutorProvider, LessonAssistant service and empty-corpus SupportService per app
lifespan. Internal dependency getters reuse those instances. Candidate lifecycle
dependency construction uses the existing database and isolated runtime without
constructing another AI client. There are no new public AI endpoints.

Default mode is disabled and never invokes a transport factory. Explicit mock mode
requires a valid injected fixture factory. AI settings remain separate from the
strict ordinary application environment file. Legacy learner hints still use
`FakeTutorProvider`, rather than silently switching to the internal bounded adapter.
Closing a client prevents further calls/retries and suppresses late output;
optional transport cleanup runs once with sanitized errors. Nested lifespan
cleanup disposes an app-owned database even if AI startup or cleanup fails, while
caller-owned databases remain caller-owned. Separate apps and repeated lifespans
receive isolated resources. No credentials, SDK, live mode or network AI was added.

Phase 3.4A gate: **37 new tests passed; 124 combined tests passed in 0.84 seconds**,
including existing support, resource, capability-isolation and architecture checks.
Ruff passed for three new Python files; mypy passed for two source modules. Ten
customer-support topic drafts, README and a hash-bound draft manifest are under
`docs/support-drafts/`. They contain no approved contact, billing policy, service
promise or claim that daily allocation/live AI is operational.

The separate inactive readiness helper accepts explicit typed documents and
server review metadata, binds the full document digest and evaluates at an explicit
aware timestamp. Draft/unknown/missing reviews, changed content, unknown freshness,
future/expired reviews and declared conflicts exclude material. It invents no TTL,
version precedence or semantic contradiction detector. The returned knowledge is a
point-in-time preparation result, not self-expiring production activation. Eleven
labelled evaluation cases cover exact/relevant sources, unsupported questions,
missing/stale/conflicting material, source integrity and instruction attacks.

No filesystem ingestion, model-selected paths or production wiring was added.
Draft Markdown hashes are review-index hashes, separate from runtime typed-document
digests. Source approval, passage extraction, freshness/conflict procedures and a
human escalation destination still require team decisions. `AIResources.support`
continues using the empty/unavailable default.

Daily-assignment readiness gate: **58 passed in 8.10 seconds**, including 44 new
tests and existing architecture, retrieval, ownership and no-assignment candidate
regressions. Ruff passed for five Python files; mypy passed for four sources.
The concrete service remains blocked and never invokes even injected resolver or
store ports. It reports no assignment creation, quota enforcement or remaining
slots. Future atomic contracts describe genuine eligibility/release, server-owned
timezone/semantics and idempotent transactional quota checks without implementing
an assignment database or changing existing session semantics.

The pure date helper requires both an aware instant and an explicitly resolved
`tzinfo`; it never consults the host timezone or supplies missing IANA data.
UTC/fixed-offset midnight, year/leap boundaries and ambiguous-boundary rejection
are tested. Production timezone authority, IANA data, DST/travel/change/claim rules,
assignment identity/classification and cancellation/expiry/refund semantics still
need decisions. See `daily-assignment-readiness.md`. Actual three-new-assignment
enforcement is **blocked**, not claimed complete.

Personalization input gate: **553 selected tests passed in 2.60 seconds**, including
71 new cases plus existing generation/admission/tutoring contracts. Ruff passed
for three Python files; mypy passed for two sources. The strict pure evidence batch
requires an explicit owner, UTC cohort/as-of bounds, record cap and real record
identities. Discriminated minimized facts reject cross-owner, duplicate, out-of-
window, future, oversized and private/profile inputs. Only the unchanged eight
`LearnerEvidenceSummary` counters leave the aggregator; IDs, dates, reasoning,
selected answers, private rules and inferred learner diagnoses do not.

Hint facts require explicit reservation request provenance and completion known by
the supplied cutoff. Legacy exact request time is unavailable and is not inferred
from delivery time or ambiguous request events. There is no SQL selector, default
window, profile migration, interest vocabulary, skill/difficulty policy, application
wiring or live personalization. Those product and selection decisions remain
**blocked**; see `personalization-readiness.md`. Existing +1/+7 retrieval is unchanged.

## Historical migration compatibility

The Phase 0 populated migration fixture deliberately checks 0004 -> 0005. Its
schema comparison now uses the explicit 22-table 0005 inventory and a scoped
Alembic metadata comparison. It continues checking all legacy rows, trigger SQL,
hashes, integrity and account claiming, while the existing current-head migration
test continues running `command.check` over the full current metadata. Additive
future tables are not incorrectly treated as pre-existing historical tables.

Historical fixtures use a test-only transient tutoring-operation port when running
current handlers against schemas that predate reservations. Real HTTP validation,
immutable tutor interactions, events and SQL readback remain exercised. Running
application code has no missing-table fallback. The pre-Module-3 reconstruction
also uses its exact 13-table inventory instead of accidentally creating future
tables before their migrations.


## Final milestone status

| Milestone | Status | Operational boundary |
| --- | --- | --- |
| Repository safety | Complete | Separate local branch based on unchanged Phase 3.1A commit; no commit/push |
| 3.2A blueprint authoring | Complete | Two technically validated candidates; human approval/publication still pending |
| 3.2B candidate lifecycle | Complete | Durable provenance/validation/review; every state unreleased and unassigned |
| 3.3A tutor transaction safety | Complete | Reservation/finalization tested; existing fixture-only learner policy retained |
| 3.3B application AI lifecycle | Complete | Shared disabled/explicit-mock client; no live activation or public AI endpoints |
| 3.4A support readiness | Complete | Ten unapproved drafts and evaluations; production corpus/contact remain blocked |
| Daily assignment policy | Partial | Contracts/calendar math tested; real quota/store/timezone authority blocked |
| Personalization readiness | Partial | Strict factual aggregation tested; selector/profile/vocabulary policies blocked |
| Existing retrieval | Preserved | +1/+7 elapsed-day behavior and pinned historical data unchanged |

The initial full implementation run passed 1,880 tests with 96.43% coverage.
Coverage review then added 41 failure-defense cases, without application-code or
threshold changes: provenance/receipt/actor/audit-chain forgery, lost storage and
idempotent races, duplicate support references, partial-startup cleanup/redaction,
and invalid assignment/clock metadata. All 164 affected tests passed in 68.31
seconds; combined coverage reached 97.17%. The final clean full-suite result below
is authoritative rather than that intermediate combined measurement.

Preservation review found only the 11 intentional existing code/test modifications
listed below; 293 other pre-existing protected files retained their bytes, sizes
and modification times. Real `.env.local`, `backend/.env`, `backend/trace.db`, all
five existing migrations, frontend and public API artifacts are unchanged. All
201 tested backend Python/JSON and support-draft data files match the isolated
copy byte-for-byte. No files were deleted or staged.

## Final validation result

The final clean full backend run passed **1,921 tests in 428.96 seconds**, including
all 1,601 original tests and **320 new tests**, with **97.17% statement/branch
coverage**. This is **+0.31 percentage points** above the freshly reproduced
96.86% baseline. There were no failures, errors or skipped tests. No existing
test was deleted and the coverage threshold/configuration was not reduced.

Ruff lint and format checks pass for **182 Python files**; mypy passes for **125
source files**. OpenAPI equals the stored schema exactly: **21 paths and 23
operations**, with no frontend API-type regeneration needed. Existing lesson and
retrieval hashes, deterministic evaluators and trusted runtime regressions pass.
Migration, ownership, account claim, idempotency and concurrency cases are included
in the full run. All migrations used disposable fixture databases.

Final artifacts in the existing isolated validation copy:

- `completion-results/backend-verified.xml`
- `completion-results/backend-verified-output.txt`
- `completion-results/baseline.xml`
- `completion-results/blueprints.xml`
- `completion-results/candidate-lifecycle.xml`
- `completion-results/tutor-final.xml` and `tutor-regression.xml`
- `completion-results/guards.xml`

There was no dependency/SDK installation, real credential loading, live provider
request, automatic publication or learner assignment. The actual learner database
is unchanged; applying new migrations to it requires a separate operator review
and execution. This task did not deploy or change real authentication configuration.

Final branch: `feat/phase-3-2-provider-independent-completion`. HEAD remains the
original Phase 3.1A commit `eede2009e46b3ad249b1aea8991687a713f206ef`; the new work
is unstaged/uncommitted. No commit, push, PR creation, merge or destructive Git
operation was performed. The existing Phase 3.1A branch/PR and genuine shared
logs are preserved. Its client/startup/DI files are extended by this working diff;
its original commit and compatible contracts remain intact.

## Detailed file inventory

New deliverables:

- `backend/alembic/versions/0006_candidate_lifecycle.py`
- `backend/alembic/versions/0007_tutor_reservations.py`
- `backend/app/ai/resources.py`
- `backend/app/blueprints/__init__.py`
- `backend/app/blueprints/candidates.py`
- `backend/app/db/candidates.py`
- `backend/app/domain/daily_assignments.py`
- `backend/app/domain/tutoring_operations.py`
- `backend/app/repositories/assignments.py`
- `backend/app/repositories/candidates.py`
- `backend/app/schemas/candidate_lifecycle.py`
- `backend/app/schemas/daily_assignments.py`
- `backend/app/schemas/learner_evidence.py`
- `backend/app/schemas/support_readiness.py`
- `backend/app/services/candidate_lifecycle.py`
- `backend/app/services/daily_assignments.py`
- `backend/app/services/learner_evidence.py`
- `backend/app/services/support_readiness.py`
- `backend/tests/fixtures/support_retrieval_cases.json`
- `backend/tests/historical_tutoring.py`
- `backend/tests/integration/test_ai_lifecycle.py`
- `backend/tests/integration/test_blueprint_candidate_runtime.py`
- `backend/tests/integration/test_candidate_lifecycle_migration.py`
- `backend/tests/integration/test_candidate_lifecycle_persistence.py`
- `backend/tests/integration/test_tutor_operation_migration.py`
- `backend/tests/integration/test_tutor_transactions.py`
- `backend/tests/lifecycle_fixtures.py`
- `backend/tests/unit/test_ai_resources.py`
- `backend/tests/unit/test_blueprint_candidates.py`
- `backend/tests/unit/test_candidate_lifecycle.py`
- `backend/tests/unit/test_daily_assignment_readiness.py`
- `backend/tests/unit/test_learner_evidence.py`
- `backend/tests/unit/test_support_readiness.py`
- `docs/architecture/blueprint-candidates.md`
- `docs/architecture/blueprint-candidates/notes-v1.json`
- `docs/architecture/blueprint-candidates/tasks-nested-v1.json`
- `docs/architecture/daily-assignment-readiness.md`
- `docs/architecture/personalization-readiness.md`
- `docs/architecture/provider-independent-completion.md`
- `docs/support-drafts/01-trace-overview.md`
- `docs/support-drafts/02-registration-authentication.md`
- `docs/support-drafts/03-google-authentication.md`
- `docs/support-drafts/04-learning-navigation.md`
- `docs/support-drafts/05-prediction-attempts-verification.md`
- `docs/support-drafts/06-hints-explanations.md`
- `docs/support-drafts/07-progress-retrieval.md`
- `docs/support-drafts/08-daily-availability.md`
- `docs/support-drafts/09-technical-problems.md`
- `docs/support-drafts/10-human-escalation.md`
- `docs/support-drafts/README.md`
- `docs/support-drafts/manifest.json`

Modified pre-existing files:

- `backend/app/ai/client.py`
- `backend/app/api/dependencies.py`
- `backend/app/api/presentation.py`
- `backend/app/api/v1/learning.py`
- `backend/app/db/learning.py`
- `backend/app/db/models.py`
- `backend/app/main.py`
- `backend/app/repositories/learning.py`
- `backend/app/services/learning.py`
- `backend/tests/integration/test_learning_failures.py`
- `backend/tests/integration/test_phase0_migration.py`

The shared session log is managed only by its existing native hook. Four pre-existing
untracked log artifacts remain preserved; they are not source deliverables. No user
history or environment files are included in the implementation changes.
