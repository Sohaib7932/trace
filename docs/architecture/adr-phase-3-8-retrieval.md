# ADR: retain lexical retrieval; gate future semantic/hybrid indexing

Status: accepted for this implementation scope. Embedding selection and
production ranking replacement remain unapproved decisions.

## Evidence

The versioned 94-case engineering reference benchmark covers all 19 approved
passages. At top three, the existing retriever supplies sufficient evidence for
65/69 answerable cases. A fixed binary-BM25 candidate supplies 64/69 and regresses
heldout recall from 0.951613 to 0.903226. It improves none of the four missed
cases. See `../support-retrieval-evaluation-v1.md` and the two bound JSON reports.
These labels require independent review and are not a blinded model evaluation.

## Decision

Keep the existing active lexical algorithm, top-three bound and deterministic
fallback. Retain the candidate only inside the offline evaluation package. Do
not add embeddings, a semantic index, PostgreSQL or pgvector for nineteen
passages without demonstrated benefit and an explicit model/cost/data decision.
The current persistence configuration accepts SQLite only.

The existing `SupportKnowledge` port remains the service retrieval boundary.
The new immutable `SupportKnowledgeSnapshot` binds eligible authoritative copy
to versioned source and zero-overlap authored chunk identities. A future ranking
adapter may consume only that snapshot and return bounded candidate identities;
it must hydrate them through `resolve`/`reconstruct`. Stored index text is never
the citation authority. Source permissions, revision, canonical digest, approval,
revocation and expiry must gate both retrieval and final response release.

## Future adapter design, not implemented

A semantic adapter must pin its embedding model/version, input normalization,
dimensions, chunker identity, approved manifest and index version. A hybrid
adapter should combine independently bounded lexical and semantic rankings with
an explicit, evaluated fusion policy. Deduplicate exact chunk identities before
hydration; identical text must never merge different permissions/provenance.
Keep the authored zero-overlap chunks unless rechunking is reviewed. Fallback
must never use expired or revoked sources when another adapter is unavailable.

Before activation, independently review reference labels, add unseen paraphrase
families, measure relevant-passage recall and complete-evidence coverage, test
false answers/abstentions, and evaluate source filtering under stale index,
revocation, injection and substitution. Prove a gain on a frozen holdout without
weakening current citation/privacy gates. No approved text-model integration
implicitly authorizes sending documents to an embedding service.

## Consequences

Known paraphrase misses remain visible. Source-version governance and benchmark
reproducibility improve now. Retrieval score improvements and semantic model
quality are not claimed. No additional deployment dependency, paid call or
unreviewed production corpus is introduced.
