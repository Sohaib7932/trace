# ADR: genuine semantic retrieval as a gated internal experiment

Decision recorded: 2026-11-03. Status: implementation candidate; production
activation remains disabled. Existing lexical retrieval, approved source copy,
learner APIs and deterministic exercise verification are unchanged.

## Model and operating cost

Use the exact stable model ID `gemini-embedding-001`, 768 dimensions and the
already installed Google GenAI 2.34.0 SDK. Documents use `RETRIEVAL_DOCUMENT`;
questions use `RETRIEVAL_QUERY`. Reduced vectors receive explicit finite L2
normalization and float32 encoding. This is an embedding operation, separate
from the approved conversational model. [Google embedding documentation](https://ai.google.dev/gemini-api/docs/embeddings)

Standard embeddings are currently free on the Free Tier. The paid standard
price is $0.15 per million input tokens, and the asynchronous Batch API is not
available on Free Tier. This implementation allows only the standard online RPC,
zero paid budget, an explicitly confirmed unbilled project, zero retries and no
model/provider fallback. Free-tier content may be used to improve Google
products; the experiment sends only approved public copy and synthetic public
questions. [Official pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-embedding)

Project RPM/TPM/RPD availability must be checked privately in AI Studio. Published
limits are not universal guarantees; a 429 remains an honest unavailable result.
No billing is activated or queried. [Rate-limit policy](https://ai.google.dev/gemini-api/docs/rate-limits)

The bounded real experiment on 2026-11-03 returned the sanitized
`unavailable/rate_limited` state after 9.58 seconds. The first planned RPC was
the 19 approved document passages; the 94-query RPC follows only after that
step succeeds. No retry or fallback was performed, no usable index was produced,
and no semantic ranking or quality result is established by this failed run.
The planned ceiling was two RPCs / 113 items, not evidence that both RPCs ran.
The failure output did not include per-RPC counters, so whether the document or
query RPC encountered the limit is unknown; observed attempted/completed RPC
counts and measured usage are not reconstructed from the elapsed time.
An operator must inspect the project's actual embedding quota privately before
any separately authorized rerun. Offline mock vector tests establish mechanics,
not semantic model quality.

Google currently lists May 14, 2028 for this model's shutdown. A replacement must
create a new vector space and re-embed source content; incompatible vectors must
never be mixed. [Model lifecycle](https://ai.google.dev/gemini-api/docs/deprecations#embedding-models)

## Provider-neutral port and resource ownership

`BoundedEmbeddingClient` owns admission, request/item/reserved-input limits,
normalization, usage observations and close behavior. `EmbeddingTransport` is
separate from the existing generative-completion port. It has no grading,
publication, assignment or learner-history capability.

`GeminiEmbeddingTransport` owns one reusable SDK client and one asynchronous I/O
loop. It allowlists only HTTPS to
`generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents`.
No arbitrary host, query-string credential, asynchronous paid batch operation or
generation request is allowed. The SDK supports this standard embedding method
and ordered multiple inputs. [Official SDK](https://googleapis.github.io/python-genai/#embed-content),
[API reference](https://ai.google.dev/api/embeddings#method:-models.batchembedcontents)

The application bounds each request to 100 inputs, 2,000 UTF-8 bytes per input,
64 KiB request data and 4 MiB response data. These are application safety bounds.
The primary API description does not publish a current numeric hard batch
maximum; successful handling of the proposed 94-query batch must be established
by the bounded real experiment. No automatic split/retry hides rejection.

The async deadline covers actual provider I/O and cleanup. Admission is retained
until work finishes. Close rejects new calls and disposes resources after active
calls finish. There is no new client per question.

The UTF-8-byte-plus-16 estimate is an admission reservation, **not measured
tokens**. RPC attempts, item counts, reserved estimates, observed tokens and
missing usage remain separate. The current API exposes embedding usage metadata,
but the installed SDK's Developer API response conversion does not preserve it.
The adapter reports unknown measured usage and unknown provider weight revision;
it does not invent zero tokens, an immutable model checksum or billing proof.
An optional `AIUsageLedger`/`AllowancePolicy` pair now reserves a backend UUID and
hashed trusted subject before each real RPC, records batch item counts and
nullable usage, and finishes only after actual transport cleanup. Failed
finalization withholds vectors and leaves the durable pending lease consumed.
`stop_admission`/`wait_for_idle` let application shutdown retain the database until
finalization ends. Production wiring belongs to the shared-ledger milestone.

## Vector identity, persistence and source authority

The vector-space fingerprint binds model/provider ID, dimensions, document/query
tasks, API profile, `title-plus-passage-v1`, `exact-question-v1` and
`finite-l2-f32-v1`. The document renderer uses the exact approved title, two
newlines and unchanged passage text. No normalization edits the approved copy.

Each index row binds `ApprovedSupportPassageVersion`, space fingerprint, exact
rendered-input SHA-256 and a vector digest over canonical big-endian float32
bytes. The index binds the reviewed manifest, creation instant, adapter version,
nullable observed provider revision and complete rows. Changed inputs, dimensions,
model, source revision or processing profile cannot silently reuse an index.

`FileEmbeddingIndex` and `SemanticEvaluationCache` persist explicit derived
benchmark files. Writes refuse to overwrite existing work. They never become a
production knowledge registry. The approved source snapshot remains the source
of quotations; index text is never citation authority.

Nineteen 768-dimensional float32 document vectors occupy 58,368 bytes before
metadata. Exact cosine search over this corpus is sufficient as an initial
implementation. No vector database, ANN index or additional numerical dependency
is justified yet. The durable archive can later persist these typed artifacts
through an additive SQLAlchemy adapter, portable across SQLite development and
the separately reviewed PostgreSQL production architecture.

Query vectors remain internal and request-bound. No learner query, conversation
or vector is durably retained by this adapter. The explicit benchmark cache
contains vectors of synthetic dataset questions only.

## Retrieval, fusion and release

The internal adapter exposes `retrieve_with_snapshot(question)` returning an
immutable `BoundRetrievalOutcome`: authoritative snapshot, matches, exact source
versions, index/space identities and bounded ranking metadata. Its internal query
vector is excluded from repr and from `safe_receipt()`. `revalidate(outcome)`
rereads source eligibility and reconstructs exact quotations without an embedding
RPC. Expired, revoked, changed or incompatible sources fail closed.

Semantic retrieval uses exact cosine similarity, deterministic source/passage
tie order, a configurable threshold and at most three candidates. Hybrid mode
uses weighted reciprocal-rank fusion over bounded lexical and semantic results,
deduplicated by exact source identity. Weights default to 1:1 and RRF constant
60; minimum cosine defaults to 0. These are initial engineering experiment
settings, **not calibrated confidence or answer-correctness thresholds**.

Disabled/unreviewed experiments, missing/incompatible indices and unavailable
embeddings fall back to eligible current lexical sources. No fallback bypasses
source review. A retrieved passage or high similarity score never establishes an
answer: the existing selection and exact-quotation gates still apply.

The generic `retrieve` port is provided for compatibility tests. Production
wiring must retain the request-bound outcome and call `revalidate`; it must not
repeat query embedding for final source checks. No existing public route or
application resource activates this adapter in Stage C.

## Reproducible evaluation and activation gates

Use the existing 94-case versioned reference dataset without rewriting its
labels or lexical baseline. The cache binds its canonical digest, approved corpus
digest, document index and ordered query input/vector receipts. Offline replay
requires no credentials or network.

The initial real experiment is bounded to two standard RPCs: nineteen documents
and ninety-four synthetic questions, 113 input items total. Their rendered input
is 11,995 UTF-8 bytes; the conservative reservation is 13,803. The CLI cap is two
RPC attempts, 113 items and 16,000 reserved input tokens. Failure consumes the
attempt; there are no retries or paid fallbacks.

The CLI requires both `--live-free-tier` and `--confirm-unbilled-project` to build
a missing cache. An existing cache always replays offline and is preserved.
Actual live execution requires review of the exact command and evidence that
offline focused tests pass. No live execution is claimed by this ADR.

```powershell
# Offline replay, once a reviewed real-vector cache exists:
.venv/Scripts/python.exe -B -m scripts.evaluate_semantic_retrieval --dataset tests/fixtures/support_retrieval_v1.json --cache "C:/path/to/local-artifacts/semantic-gemini-001-cache-v1.json" --summary-only
```

Reports compare lexical, semantic and hybrid Recall@k, Precision@k, MRR,
sufficient evidence, false abstentions, oracle abstention precision/recall and
source-integrity results. Actual model-generated vectors establish an embedding
retrieval experiment. The deterministic selection oracle still does not measure
Gemini answer selection or reasoning. Mock vectors test only contracts and are
explicitly marked as non-genuine semantic measurements.

Keep the full numerical cache outside the repository until it has been reviewed;
`--summary-only` removes per-case detail from the shareable JSON report. CLI
argument, credential-loading and file errors never echo supplied values.

Production remains lexical until an independent reviewer checks reference labels,
new unseen paraphrases are added, an experiment improves meaningful coverage
without heldout regressions, and source/citation/privacy/failure gates remain
passing. A unit-test pass or apparent score increase alone cannot activate it.

## Local alternative considered

`sentence-transformers/all-MiniLM-L6-v2` is an English Apache-2.0 model producing
384-dimensional embeddings. A reproducible candidate revision is
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. The model truncates beyond 256 word
pieces, which must be checked explicitly against inputs rather than silently
losing evidence. [Model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)

Its pinned safetensors weights occupy 90.9 MB; runtime RAM, latency and dependency
overhead are unmeasured on the intended host. Sentence Transformers, Torch and
ONNX Runtime are absent from this checkout. A local candidate therefore needs
separate dependency/download verification and host measurements. It could offer
stronger question-data locality but is not silently installed or substituted.
[Pinned weights and checksum](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/blob/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/model.safetensors)
