# Personalization readiness — selected factual evidence

This milestone prepares deterministic inputs. It does not implement personalized
generation, a learner profile, an interest taxonomy, a skill score, a difficulty
policy, a history query or an automatic scheduler.

## Existing signals and their limits

| Product signal | Actual source | Permitted interpretation |
| --- | --- | --- |
| Predictions | Immutable original prediction records | Submission count and deterministic correctness boolean; no reasoning or answer key in a future prompt |
| Attempts | Immutable numbered modification attempts | Attempt count; a change is not proof of understanding |
| Help | Durable hint reservations and append-only delivered/error interactions | Requests, pending work and delivered guidance remain separate facts |
| Verification | Trusted persisted verification results | Infrastructure-error count; an infrastructure failure is not a learner mistake |
| Retrieval | Persisted responses and deterministic correctness | Response/correct-response counts; these are not mastery or retention scores |
| Interests / preferred context | No approved persisted vocabulary or profile | Unresolved product decision |
| Skill / difficulty progression | No approved measurement or progression policy | Unresolved product decision; no inferred score |
| Misconceptions | Authored template indicators and possible tutor interpretations | No persisted authoritative diagnosis of an individual learner |

The stable learner UUID is different from an account/user UUID. A future trusted
selector must authorize the learner owned by the current guest/account principal.
Guest-history claiming preserves the existing learner history rather than creating
a second evidence copy. This pure contract does not perform identity lookup or
claim database authorization.

## Internal contract

`LearnerEvidenceWindow` requires every parameter explicitly:

- `owner_learner_id`: internal authorization scope, excluded from provider output.
- `start_at` inclusive and `end_at` exclusive.
- `as_of`: the latest time at which an outcome may be known, at or after `end_at`.
- `max_records`: a caller-selected limit from 1 through 10,000.

Timestamps must be aware and are normalized to UTC. There is no server-local
timezone assumption, default duration, default record ordering or implicit
selection/truncation policy.

The discriminated fact variants are prediction, modification, hint, retrieval
answer and verification infrastructure error. They contain only an internal record
identity, owner, event timestamp and the minimum boolean/status data needed to
aggregate the existing generation evidence contract. Prediction/retrieval
correctness must already be established by trusted deterministic application code;
the aggregator does not grade or diagnose anything.

`LearnerEvidenceBatch` rejects cross-owner records, duplicate category/identity
pairs, events outside the window, future completion knowledge, unknown fields and
record-limit overflow. It does not silently trim history or claim that selected
facts represent all available records. A future selector must define and enforce
completeness/ordering under an approved product policy.

`summarize_learner_evidence(batch)` returns only the unchanged
`LearnerEvidenceSummary` fields:

```text
prediction_count
correct_prediction_count
modification_attempt_count
hint_request_count
hints_delivered_count
retrieval_answer_count
correct_retrieval_answer_count
verification_error_count
```

No owner/record IDs, dates, reasoning, selected choices, mapping values, answer
keys, evaluator rules, credentials, contact details or arbitrary profile text enter
that projection. The existing `GenerationRequest` schema is unchanged. There is no
database adapter, application wiring or learner-facing endpoint for this service.

## Hint cohorts and historical limitations

The event cohort is the set of requests whose exact reservation time lies in
`[start_at, end_at)`. A reservation and its final interaction form one fact with
the same identity; passing both separately is rejected. Pending and failed work
counts as requested help, while only delivered work counts as delivered guidance.

A completion after the event window may count if it is already known by the
explicit `as_of` cutoff. Completion after `as_of` is rejected rather than silently
using future information. A different temporal policy would require an explicit
contract decision. This cohort treatment preserves delivered <= requested without
pretending that pending help has reached the learner.

Only `request_time_source="reservation"` is admitted. Pre-reservation legacy
`TutorInteraction.created_at` records finalization/delivery time, not an exact
request start. Historical `hint_requested` events refer to attempts and cannot be
uniquely joined to individual hints. No fallback timestamp, fabricated event join
or exact legacy request-cohort claim is implemented. Legacy selection remains
unresolved until an approved evidence policy defines a truthful treatment.

Verification-error facts use the recorded infrastructure-error completion time.
Failed learner verification, wrong predictions and failed retrieval responses are
distinct from infrastructure errors. None is converted into a personality,
mastery, skill or misconception label.

## Decisions required before SQL selection or personalization

1. Approve window duration, ordering, record caps, completeness reporting and
   legacy hint treatment. The current contract deliberately provides no defaults.
2. Approve an interest vocabulary, consent/update behavior and permitted framing
   mappings. No vocabulary is proposed or installed here.
3. Define skill, difficulty progression and preferred-context policies, including
   which factual evidence supports each decision and how uncertainty is reported.
4. Review any future misconception model separately from raw wrong-answer or
   mapping observations; current evidence does not establish a learner diagnosis.
5. Implement an ownership-checked bounded selector that produces these facts,
   minimizes data and never returns private evaluator configuration or raw learner
   reasoning to the provider.
6. Keep interests restricted to approved scenario framing. Objectives, trusted
   artifacts, expected answers, evaluation, verification and release decisions
   remain controlled by existing composition/candidate-validation boundaries.

No personalization, assignment, retrieval scheduling or live provider call is
activated. Existing +1/+7-day retrieval remains independent from future daily new
exercise quotas.
