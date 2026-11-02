# Daily exercise assignment readiness — execution blocked

The approved limit is at most **three new exercise assignments per learner-local
calendar day**. This milestone adds bounded contracts and pure date arithmetic;
it does not enforce a production quota, create assignments or fabricate available
slots. `DailyAssignmentService` always returns `blocked`, `assignment_created=false`
and `quota_enforced=false`. It never invokes an injected resolver or store.

## Existing source facts

- `User`, `Learner` and `AccountLearner` have no authoritative timezone/profile
  field. Guest claiming preserves a learner identity but defines no timezone rule.
- Existing `LearningService.create_session` opens a pinned legacy learning session;
  it is not an exercise-assignment operation and is unchanged.
- There is no assignment table, repository implementation or daily scheduler.
- Account action rate limits are minute-based request controls, not exercise quotas.
- Retrieval remains the existing +1/+7-day schedule anchored to transfer completion.
- Generated candidates retain `release_eligible=false`, including review states.
  No candidate is currently authorized for learner assignment by this work.

## Implemented boundaries

`app/domain/daily_assignments.py` defines the limit and `local_day_window(at,
resolved_timezone)`. Both arguments are explicit. The instant must be aware;
the supplied `tzinfo` is already resolved by trusted server code. The helper never
looks up an IANA key, reads the host timezone or supplies a default timezone. It
returns a half-open UTC window `[start, end)` and its local calendar date.
Ambiguous/nonexistent midnight boundaries fail closed for separate resolution.

UTC and explicit fixed-offset tests establish arithmetic across midnight, year
changes and leap days. They do not establish a production IANA resolver or DST
policy. The inspected Windows environment has no usable installed timezone-data
package; no dependency was installed. Fixed offsets are test inputs, not a
substitute for an approved learner timezone.

`app/schemas/daily_assignments.py` separates blocked readiness from future atomic
requests/receipts. There is no `remaining_slots` field. Future receipts distinguish
new assignment from existing idempotent receipt; only the former consumes quota.
Hints, explanations, attempts/retries, reviews and retrieval are not valid inputs
to `NewAssignmentRequest`. No public endpoint, dependency wiring, database model
or migration is added.

`app/repositories/assignments.py` defines future timezone, approved-semantics and
atomic-store ports without implementing them. The atomic store must authenticate
the owned learner, recheck authoritative candidate validation, human approval,
separately authorized release and non-fixture provenance, then check the quota and
create exactly one assignment in one transaction. Count-then-insert in separate
transactions is not acceptable.

Exact learner/idempotency-key retries must return the original immutable receipt
and original local day, including retries after midnight. A different candidate or
approved policy binding conflicts. An LLM, client or frontend cannot choose quota
availability, timezone authority, eligibility or arbitrary document/record access.

## Decisions required before assignment implementation

1. Authoritative timezone source for accounts and guests, capture/confirmation,
   approved IANA vocabulary, resolver/data distribution and missing-data behavior.
2. DST boundary resolution and timezone-data versioning; no host-local fallback.
3. Travel/timezone-change effective boundaries and prevention of quota resets;
   historical assignment receipts must retain their original UTC/local-day facts.
4. Guest-to-account timezone selection and preserved learner/quota identity.
5. Assignment identity, which activities qualify as new assignments, and how
   existing lesson sessions and transfer tasks relate to assignments.
6. Assignment timestamp authority, atomic midnight handling, idempotency lifetime,
   cancellation, expiration, replacement and any quota-refund semantics.
7. A separately authorized release process, genuine eligibility lookup, assignment
   persistence, uniqueness constraints, concurrency tests and safe migrations.

Hints, explanations, reading theory, retries, reviews and current retrieval must
not consume a new-assignment slot. A future explicit reclassification decision is
required before a retrieval/review exercise can count as a new assignment.

After these decisions are approved, implement the resolver and atomic store,
then test concurrent assignment attempts, cross-midnight exact retries, timezone
changes, DST, ownership, guest claiming, ineligible/fixture candidates and the
three-assignment cap. Until then, production enforcement remains blocked.
