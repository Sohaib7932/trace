# Global leaderboard backend validation

Date: 2026-11-05. Branch: `codex/leaderboard-backend`.
Base: `72bcfc329543f8d51e256a15d9be3beca61b7a30` (merged PR #31).

The backend implements `GET /api/v1/leaderboard` using existing registered-account
ownership and server-verification histories. No migration or scoring table is required.
The integration contract is [leaderboard-api-integration.md](../leaderboard-api-integration.md).
Changes remain uncommitted; this workstream did not stage, commit, push, open a PR or merge.

## Verified gates

Commands below run from `backend` using the project's locked Python environment.
The observed full-suite runtime was Windows with Python 3.13.5.

| Gate | Verified result |
| --- | --- |
| Complete configured backend suite: `python -m pytest --maxfail=1 -q -p no:cacheprovider` | **4,905 passed, 0 failed, 0 skipped**, in **1,760.85 seconds (29:20)**; exit 0. |
| Normal full-application coverage | **94.26%**, exceeding the unchanged **85%** gate; branch coverage enabled by the existing configuration. |
| Targeted leaderboard/account/learning/verification/legacy/architecture regression run | **118 passed** in 269.33 seconds; **98.40%** coverage of the new API, SQL adapter, service and response schemas. |
| Consolidated API golden/legacy contract checks | **7 passed** in 19.64 seconds before the successful complete run. |
| `python -m ruff check --no-cache .` | Passed. |
| `python -m ruff format --no-cache --check .` | Passed; **427 files** already formatted. |
| Configured `python -m mypy` with a task-specific cache | Passed; **263 source files**, no issues. |
| `python -m scripts.export_openapi` | Passed; the exported schema matches the running application's OpenAPI in integration tests. |

The targeted checks overlap with the complete suite. The complete successful run
includes all **38 new leaderboard cases** and all updated legacy API assertions.
No tests or coverage thresholds were skipped or relaxed for this feature.
The complete console capture was retained privately outside Git as
`leaderboard-full-backend-pytest-validated.txt`.

## Completion, ranking and privacy checks

Qualifying evidence is an existing completed learning session, a finished passed
verification run for that same session, and all five matching check categories:
`http_status`, `api_response`, `validation`, `row_count` and `stored_values`.
The SQL query counts distinct canonical `lesson_id` values across repeated sessions
and lesson versions. It joins through immutable `account_learners` ownership.

Tests exercise genuine Notes/Tasks API verification in disposable migrated databases.
They cover duplicate sessions/versions and verification replays; drafts, predictions,
unverified attempts, failed/error/pending verification, and late success on abandoned
sessions; AI answer-key/practice exclusion; unclaimed guests and explicit claims;
disabled accounts and role denial; zero/empty states; competition ties `1, 1, 3`;
stable pagination, off-page viewer rank and cutoff ownership; private-data exclusion;
cursor bounds and duplicate/unknown fields; quota and sanitized database failures.

The missing/mismatched-evidence fault-injection cases begin with a genuine successful
verification, then invalidate one check only in their disposable test database.
They do not synthesize successful completion records.

Aggregation uses SQL grouping, `DISTINCT`, and `RANK()` before pagination. The page
and viewer position use one consistent read snapshot and two queries, independent
of the number of returned users. A cursor retains its UTC cutoff and bounded offset;
account, ownership, completion and verification timestamps after the cutoff are excluded.

Only active registered learner accounts with positive counts appear. Display name
and avatar fields are required nulls because the backend stores no public profiles.
Board identifiers are stable domain-separated hashes, and cursors contain no account
identifiers. Anonymous cookies alone cannot authorize the endpoint. Reading the board
does not create a learner identity or obstruct a later guest claim.

## Four strict additive API golden updates

The full-suite diagnostic runs exposed existing whole-API expectations that needed
to explicitly recognize the new route. The following expectations were updated:

| Test file | Preserved and added assertions |
| --- | --- |
| `backend/tests/integration/test_api.py` | Adds `/api/v1/leaderboard` to the exact mounted-route set; retains every prior route and strict set equality. |
| `backend/tests/integration/test_ai_lifecycle.py` | Asserts the new leaderboard route is exactly one named path; retains 39 legacy paths and the existing exact administrator/custom route checks. |
| `backend/tests/integration/test_evidence_feedback_lifecycle.py` | Asserts the exact leaderboard path, total 54 paths, seven custom paths and the unchanged 39 legacy paths. |
| `backend/tests/integration/test_learner_feedback.py` | Asserts the exact leaderboard path and total 54 paths; retains seven custom paths, 39 legacy paths and 44 legacy operations. |

The consolidated golden checks and subsequent complete run pass with these explicit
additive expectations. Application behavior required no further correction after
the focused leaderboard validation.

## Changed files

Implementation:

- `backend/app/domain/leaderboard.py`
- `backend/app/repositories/leaderboard.py`
- `backend/app/schemas/leaderboard.py`
- `backend/app/db/leaderboard.py`
- `backend/app/services/leaderboard.py`
- `backend/app/api/v1/leaderboard.py`
- `backend/app/api/dependencies.py`
- `backend/app/main.py`

Tests:

- `backend/tests/integration/test_leaderboard.py`
- The four existing API golden files listed above.

Contracts and handoff:

- `backend/openapi.json`
- `src/lib/api/schema.d.ts` (generated API types)
- `docs/leaderboard-api-integration.md`
- `docs/reports/leaderboard-backend-validation.md`

## Validation limits and integration status

The complete run uses the configured `tests` suite. PostgreSQL runtime execution and
the separate infrastructure/production profiles were not run. The query uses portable
SQLAlchemy/window expressions and the existing PostgreSQL consistent-read adapter.
No live AI/provider calls, personal GitHub App credentials, developer databases,
original OneDrive databases or backups were used for this workstream's validation.

Account disablement and learner-role removal take effect immediately, including for
continuations; restart pagination after such membership changes. This takes priority
over retaining a removed account in an old page snapshot.

Public profile editing, avatars and opt-out preferences remain separate product work.
Zero-count users remain absent under the existing frontend empty-board contract.
The optional proposed `total_ranked` and `passable_with_one_more` fields are not returned.
The existing frontend's intentional unavailable adapter remains unchanged; the handoff
describes the authenticated integration. No leaderboard UI components were implemented.
