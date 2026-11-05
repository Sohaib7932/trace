# PR #35 CI repair follow-up

Date: 2026-11-05. Branch: `codex/fix-ci-paths-and-rate-windows`.
Base: externally merged main `a28970993501282abd240d03a6c7ab7c28e12299`.

## Actual failed checks

Complete GitHub Actions logs were inspected:

- [Windows push](https://github.com/Sohaib7932/trace/actions/runs/42022663700/job/127229022499): 4,905 backend tests passed (94.26% coverage), followed by three logging-installer test errors/failures.
- [Windows pull request](https://github.com/Sohaib7932/trace/actions/runs/42022854816/job/127229657709): the same three logging tests failed after 4,905 backend tests passed (94.28% coverage). Both jobs passed lint, format, mypy, migrations and OpenAPI checks before the logging step.
- [PostgreSQL 15 pull request](https://github.com/Sohaib7932/trace/actions/runs/42022854722/job/127229658046): 35 production tests passed; the shared admission rate-window assertion failed. PostgreSQL 15 push and PostgreSQL 17 comparison jobs passed. Later trigger errors in cleanup output were expected negative-test evidence, not the first failure.

## Windows path fixture correction

Windows CI exposes temporary paths through an 8.3 alias (`RUNNER~1`). The installer and subprocess correctly resolve its canonical long spelling, but the fixture compared unresolved dictionary keys, registry paths and child cwd strings.

Only the test fixture base now resolves its temporary directory. A real existing-directory/`..` alias reproduced all three failures before correction and passes afterward. The new regression checks canonical keys, registered scope, byte-preserved native input, canonical child cwd, silent output, unchanged trust and no-op reinstall. Production path resolution and security restrictions remain unchanged.

## Deterministic admission-window correction

The test assumed all nine database-clock observations occurred within one real UTC minute. Running the unchanged test with eight observations at `11:55:59` and the last at `11:56:00` reproduced its exact `DID NOT RAISE` failure: three admissions persisted in the first bucket, then one legitimate admission in the next. Individual CI lease timestamps were not retained; these are controlled reproduction records, not a claimed CI database dump.

Only the test's existing trusted clock seam is pinned. Every original assertion remains. A new UTC-midnight regression verifies rate reset, outstanding subject/global leases, no refunded quota, and exact persisted bucket/release counts. Production quota policies, database-time code and transaction boundaries are unchanged. The existing PostgreSQL wrapper discovers the new test automatically.

## Concurrent updates and authentic log preservation

While fixes were validated, PR #34 merged the leaderboard into main. Before the reviewed local repair could be pushed, the remote PR #35 branch independently advanced to `6a6b6af`, and PR #35 merged as `a289709`. The ordinary push was correctly rejected and was never forced. Local commits `69615cf` and `4629b0d` and both remote/main states retain backup references.

This follow-up starts directly from that main and applies only the two validated test-file fixes. It neither rewrites the merged branch nor pushes directly to main.

The concurrent remote log resolution added 23 duplicate frontmatter fields and an orphan prompt marker with no metadata/body. Strict parsing correctly rejected it. Structural comparison proved that fragment added zero genuine records: removing the orphan marker in memory restored the exact 236-entry body of the published source. The validated local history retained one further genuine prompt. The follow-up restores that exact verified source through render/parse checks, preserving all 237 entries (134 prompts, 103 finals), attribution, timestamps, unique identities and statistics. No production parser was relaxed, genuine message deleted, text re-redacted or final answer invented. Exact inputs and a value-free repair receipt remain privately backed up outside Git.

## Completed local validation

- Root logging suite: **172 passed**, no failures/skips; 18 installer tests included. Rechecked on this main-based branch.
- SQLite accounting/admission module: **12 passed**, rechecked on this branch.
- Actual disposable PostgreSQL **15.19: 37 production tests passed**; **17.11: 37 production tests passed**.
- Ruff check and formatting: passed, 427 existing Python files. Strict mypy: passed, 263 source files. Whitespace checks: passed.
- Repaired actual log: strict parse, exact round-trip, uniqueness, statistics and preservation checks passed.

Only new task-owned Docker containers on unused loopback ports and temporary databases were used, then removed. No original database, backup, environment file, credential, production implementation, frontend, workflow, migration, dependency, global setting or hook trust changed. No live provider calls occurred. Assertions, retries, timeouts, security checks and coverage thresholds were not weakened.

The original complete backend baseline is evidenced by the jobs above; the new boundary case adds one test. Fresh full push/PR checks must finish before this follow-up is declared CI-green. Private job logs and runtime evidence are excluded from Git. This follow-up is for review only; no automatic main merge is authorized.