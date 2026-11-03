# Support retrieval evaluation V1

The unchanged lexical retriever has a reproducible passage-level baseline. A
fixed offline binary-BM25 candidate regressed the heldout split, so production
ranking remains unchanged. No embedding provider, vector database or semantic
retrieval infrastructure was selected or installed.

These are **engineering reference labels pending independent team review**.
They are not approved production gold and do not establish Gemini reasoning,
prompt-injection resistance or language quality.

## Inputs and source boundaries

- Dataset: [support_retrieval_v1.json](../backend/tests/fixtures/support_retrieval_v1.json), version 1.0.0.
- Baseline report: [support-retrieval-baseline-v1.json](support-retrieval-baseline-v1.json).
- Candidate report: [support-lexical-comparison-v1.json](support-lexical-comparison-v1.json).
- Actual approved corpus: `backend/app/support/corpus.json`, revision 1.0.0,
  nine articles and 19 authored passages. Corpus copy is unchanged.
- Canonical authored-package SHA-256:
  `1fa44fda7549fcac866926c07c56c9778deaa8e29955309b1f8bab80c24f5063`.
- Fixed evaluation time: `2026-11-02T15:34:08Z`. This makes the historical
  benchmark reproducible; it does not certify present-time source freshness.
- The dataset includes the exact per-document digests. Reports also bind the
  dataset's canonical digest. Explicit current source revocation rejects a
  baseline run even though revocation is outside the authored-copy digest.

All questions are synthetic public-help questions. No account records, learner
history, real submissions, prompts from logs, credentials, private files, network
calls or databases are used. This test dataset is never registered as production
knowledge. Source eligibility uses the existing reviewed-knowledge contract.

There are 94 cases: 69 answerable, 21 expected semantic abstentions and four
source-unavailable fixtures. Every approved passage has exact, paraphrased and
conceptual coverage. Cases cover all ten requested categories: exact keywords,
paraphrases, concepts, multipart, multiple passages, ambiguity, outside-corpus
questions, outdated claims, injection attempts and unsupported policies/actions.
Categories overlap; their counts must not be added as if they were disjoint.

The 44 development and 50 heldout cases have disjoint intent-family identifiers.
Paraphrases of a passage family stay in one split. Engineering authors have seen
both splits, so this is not an independently blinded evaluation. An independent
reviewer must check completeness and relevance labels before tuning or adopting
a production candidate. New genuinely unseen families should then be added in a
separately versioned evaluation.

Each answerable case records relevant passage IDs and alternative minimal
sufficient evidence sets. Multipart cases also specify required evidence groups.
An equally sufficient alternative is not required merely because it is relevant.
Abstention cases require no answer evidence; unavailable source fixtures cannot
earn semantic-abstention credit. Rationales refer only to approved passage facts.
Requests to perform unavailable actions are labelled abstention; this does not
assert that the assistant cannot explain a documented product limitation.

## Unchanged lexical baseline

The evaluator calls the actual `ApprovedSupportKnowledge` ranking through
`ReviewedSupportKnowledge`: distinct token overlap, the existing stop words,
positive scores, stable source/passage ties and at most three passages. No
synonyms, metadata boosts or retrieval changes were added.

| k | Macro Recall@k | Precision@k | MRR@k | Sufficient evidence |
|---|---:|---:|---:|---:|
| 1 | 0.833333 | 0.913043 | 0.913043 | 56/69 |
| 2 | 0.876812 | 0.492754 | 0.920290 | 61/69 |
| 3 | 0.934783 | 0.362319 | 0.925121 | 65/69 |

At k=3, 75 relevant passages were retrieved among 203 returned passages, so
precision over returned items is 0.369458. Fixed-k precision uses 207 slots.
All 15 required evidence groups are covered, including all seven multipart cases.
Paraphrases have sufficient evidence in 17/19 cases; exact-keyword cases in 19/19.

Four answerable cases lack a sufficient evidence set at k=3:

- `p01-2`: types of coding problems the learner can practise.
- `p02-3`: why explanation differs from evidence that a change succeeds.
- `p15-2`: “When will I be quizzed again?”
- `outdated-review`: correcting a claim about day-three review scheduling.

| Split | Answerable | Recall@3 | Precision@3 | MRR@3 | Sufficient evidence |
|---|---:|---:|---:|---:|---:|
| Development | 38 | 0.921053 | 0.359649 | 0.921053 | 35/38 |
| Heldout | 31 | 0.951613 | 0.365591 | 0.930108 | 30/31 |

## Deterministic selection and contract layer

The oracle selects a labelled sufficient set only when it is present in the
actual retrieved top three; otherwise it abstains. It exercises the real
`SupportService` selection/citation validation with a deterministic test provider.
It does not call Gemini and cannot establish whether Gemini would make the same
selection.

| Oracle measure | Result |
|---|---:|
| Supported answers / answered cases | 65/65 |
| Exact, eligible, retrieved citations / all citations | 72/72 |
| Gold-relevant citations / all citations | 72/72 |
| Correct semantic abstentions / expected abstentions | 21/21 |
| False abstentions / answerable cases | 4/69 |
| Unsupported answers / answered cases | 0/65 |
| Expected source-unavailable cases | 4/4 |
| Unexpected unavailable cases | 0 |

The perfect oracle support and abstention scores are consequences of supplying
the engineering labels to the mock. They are **not live-model quality scores**.
In particular, injection questions in this dataset do not prove that a real model
resists instruction injection.

Eight adversarial/contract controls separately exercise a deliberately bad
selector, unknown IDs, valid-but-unretrieved IDs, exceptions, timeouts, no result
and malformed output. Invalid results fail closed. Provider errors receive no
semantic-abstention credit. The deliberately bad selector can return an exact,
retrieved quotation for an unsupported action: citation integrity passes while
answer support fails. This records the boundary accurately: source integrity
does not establish question relevance or model judgment. All nonanswers have
zero citations; citation-rate denominators of zero are `null`, never 100%.

## Fixed ranking experiment and decision

Before running the comparison, the candidate was declared as binary term
frequency with BM25 inverse-document frequency and length normalization,
`k1=1.2`, `b=0.75`. It uses the baseline's exact token sets and stop words, approved
sources, positive-score filter, top-three bound and tie order. Binary term
frequency is explicit; this is not a full term-frequency BM25 implementation.
No synonym tuning or heldout parameter selection was performed.

| Split | Baseline Recall@3 | Candidate Recall@3 | Baseline MRR@3 | Candidate MRR@3 | Sufficient baseline → candidate |
|---|---:|---:|---:|---:|---:|
| Development | 0.921053 | 0.921053 | 0.921053 | 0.921053 | 35/38 → 35/38 |
| Heldout | 0.951613 | 0.903226 | 0.930108 | 0.887097 | 30/31 → 29/31 |
| Overall | 0.934783 | 0.913043 | 0.925121 | 0.905797 | 65/69 → 64/69 |

No previously missed case gained sufficient evidence. `p10-2`, about whether a
correction erases the original prediction, regressed. The experiment does not
justify deploying this candidate. It also does not establish that embeddings
would resolve the misses safely. Independent label review and additional unseen
paraphrases are the next evaluation steps. Production lexical retrieval remains
the tested fallback and active implementation.

## Metric definitions

- Recall@k averages `relevant retrieved / relevant labelled` over eligible
  answerable cases. Missing retrieval counts as zero.
- Precision@k uses `k` slots, including empty slots. Precision over returned
  items is reported separately.
- MRR@k averages the reciprocal rank of the first relevant passage, zero on miss.
- Sufficient-evidence coverage requires an entire permitted evidence set and all
  required groups. Extra retrieved passages do not erase available evidence.
- Answer support requires a sufficient evidence set and only relevant, permitted
  cited passages. Unsupported or forbidden citations cannot be silently removed
  while preserving a supported-answer score.
- Structural citation integrity checks retrieved passage ID, source ID, source
  name and exact quotation, within the pinned reviewed package.
- Semantic abstention accuracy includes only source-available expected-abstention
  cases. Unavailable source/provider states remain separate.
- Unsupported-answer rate divides unsupported answered cases by all answered
  cases. False answers on expected abstentions and false abstentions on answerable
  cases are also reported. Zero denominators produce `null`; all count fields
  and category/split breakdowns are preserved in JSON.

## Reproduce offline

From `backend`, using the existing virtual environment:

```powershell
.venv/Scripts/python.exe -B -m scripts.evaluate_support_retrieval --dataset tests/fixtures/support_retrieval_v1.json
.venv/Scripts/python.exe -B -m scripts.evaluate_support_retrieval --dataset tests/fixtures/support_retrieval_v1.json --compare-candidate
.venv/Scripts/python.exe -B -m pytest tests/unit/test_support_retrieval_evaluation.py --no-cov --disable-socket -q
```

Both evaluator commands emit machine-readable JSON to stdout. Optional `--output`
writes a new report and refuses to overwrite an existing one. No environment
configuration or API key is needed. The CLI never initializes the application
AI client, and the tests forbid network sockets.
