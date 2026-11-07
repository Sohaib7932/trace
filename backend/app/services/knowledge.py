"""Account-authorized knowledge governance; no provider calls or automatic publication."""

import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.domain.accounts import AuthenticatedAccount
from app.domain.clock import Clock, as_utc, utc_now
from app.domain.knowledge import (
    ImportedReview,
    KnowledgeAction,
    KnowledgeEvent,
    KnowledgeHistory,
    KnowledgeManifest,
    KnowledgePublication,
    KnowledgeReleaseReceipt,
    KnowledgeRevision,
    KnowledgeState,
    canonical_json,
    lexical_index_artifact,
    lexical_index_digest,
    sealed,
    source_chunks,
)
from app.domain.learning import LearningError
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.support_knowledge import ApprovedSupportKnowledge
from app.services.support_readiness import support_document_digest
from app.support.database import archive_snapshot
from app.support.embedding_index import EmbeddingIndex
from app.support.knowledge import (
    CorpusDocument,
    ReviewedSupportKnowledge,
    SupportCorpusPackage,
    load_corpus_package,
    support_corpus_digest,
)
from app.support.receipts import VersionedSupportAnswer
from app.support.versioning import canonical_digest

_IMPORT_STEPS: tuple[KnowledgeAction, ...] = ("parse", "normalize", "chunk", "index", "validate")
_IMPORT_REASON = "Deterministic import checkpoint over the exact existing reviewed copy."
_ADOPTION_REASON = "Explicit adoption retains the genuine historical review attribution."


def operation_key(key: str, label: str) -> str:
    return str(uuid5(NAMESPACE_URL, str(UUID(key)) + ":" + label))


def _ingest_command(
    source_id: str,
    revision: str,
    digest: str,
    actor_id: UUID,
    imported_review: ImportedReview | None,
) -> str:
    return canonical_digest(
        {
            "source_id": source_id,
            "revision": revision,
            "document_sha256": digest,
            "actor_id": str(actor_id),
            "imported_review": imported_review.model_dump(mode="json") if imported_review else None,
        }
    )


def _transition_command(
    revision_id: str,
    action: KnowledgeAction,
    expected_sequence: int,
    actor_id: UUID,
    reason: str,
    reviewed_document_sha256: str | None = None,
    valid_until: datetime | None = None,
) -> str:
    return canonical_digest(
        {
            "revision_id": revision_id,
            "action": action,
            "expected_sequence": expected_sequence,
            "actor_id": str(actor_id),
            "reason": reason,
            "reviewed_document_sha256": reviewed_document_sha256,
            "valid_until": valid_until.isoformat() if valid_until else None,
        }
    )


def _matches_import(
    history: KnowledgeHistory,
    document: CorpusDocument,
    review: ImportedReview,
    key: str,
    actor_id: UUID,
    *,
    adopt_existing_review: bool,
) -> bool:
    revision = history.revision
    if (
        revision.source_id != document.source_id
        or revision.revision != review.package_revision
        or revision.actor_id != str(actor_id)
        or revision.normalized_sha256 != review.document_sha256
        or revision.imported_review != review
    ):
        return False
    expected = [
        (
            operation_key(key, document.source_id + ":ingest"),
            _ingest_command(
                document.source_id,
                review.package_revision,
                review.document_sha256,
                actor_id,
                review,
            ),
        )
    ]
    expected.extend(
        (
            operation_key(key, document.source_id + ":" + action),
            _transition_command(revision.id, action, sequence, actor_id, _IMPORT_REASON),
        )
        for sequence, action in enumerate(_IMPORT_STEPS)
    )
    if adopt_existing_review:
        expected.append(
            (
                operation_key(key, document.source_id + ":adopt"),
                _transition_command(
                    revision.id,
                    "adopt_existing_review",
                    len(_IMPORT_STEPS),
                    actor_id,
                    _ADOPTION_REASON,
                ),
            )
        )
    return [
        (e.operation_key, e.command_sha256) for e in history.events[: len(expected)]
    ] == expected


class KnowledgeGovernanceService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        clock: Clock = utc_now,
        corpus_loader: Callable[[], SupportCorpusPackage] = load_corpus_package,
    ) -> None:
        self.repository, self.clock, self.corpus_loader = repository, clock, corpus_loader

    def _actor(self, actor: AuthenticatedAccount, *, learner: bool = False) -> datetime:
        now = as_utc(self.clock())
        actor.account.require_role("learner" if learner else "admin")
        if actor.identity.expires_at <= now:
            raise LearningError("unauthenticated", "Account authorization expired.")
        return now

    def get(self, revision_id: str, *, actor: AuthenticatedAccount) -> KnowledgeHistory:
        self._actor(actor)
        with self.repository.read() as store:
            store.require_role(actor.account.id, "admin")
            value = store.history(revision_id)
        if value is None:
            raise LearningError("not_found", "Knowledge revision not found.")
        return value

    def get_receipt(
        self, receipt_id: str, *, actor: AuthenticatedAccount
    ) -> KnowledgeReleaseReceipt:
        self._actor(actor)
        with self.repository.read() as store:
            store.require_role(actor.account.id, "admin")
            value = store.receipt(receipt_id)
        if value is None:
            raise LearningError("not_found", "Knowledge release receipt not found.")
        return value

    def ingest(
        self,
        document: CorpusDocument,
        *,
        revision: str,
        key: str,
        actor: AuthenticatedAccount,
        imported_review: ImportedReview | None = None,
    ) -> KnowledgeHistory:
        now = self._actor(actor)
        document = CorpusDocument.model_validate_json(document.model_dump_json())
        public = document.document()
        text = canonical_json(public.model_dump(mode="json"))
        digest = support_document_digest(public)
        command = _ingest_command(
            public.source_id, revision, digest, actor.account.id, imported_review
        )
        with self.repository.write() as store:
            store.require_role(actor.account.id, "admin")
            now = self._actor(actor)
            existing = store.by_creation_key(key)
            if existing is not None:
                if existing.events[0].command_sha256 != command:
                    raise LearningError(
                        "conflict", "Ingestion key belongs to different source inputs."
                    )
                return existing
            value = sealed(
                KnowledgeRevision,
                id=str(uuid4()),
                source_id=public.source_id,
                revision=revision,
                creation_key=key,
                actor_id=str(actor.account.id),
                created_at=now,
                original_json=text,
                normalized_json=text,
                original_sha256=digest,
                normalized_sha256=digest,
                imported_review=imported_review,
            )
            event = sealed(
                KnowledgeEvent,
                id=str(uuid4()),
                revision_id=value.id,
                sequence=0,
                operation_key=key,
                command_sha256=command,
                previous_event_sha256=None,
                previous_state=None,
                state="ingested",
                action="ingest",
                actor_id=str(actor.account.id),
                created_at=now,
                reason="Explicit administrator ingestion of bounded customer-authored copy.",
            )
            store.insert(value, event)
            result = store.history(value.id)
            assert result is not None
            return result

    def _review_record(self, revision: KnowledgeRevision) -> ImportedReview:
        package = SupportCorpusPackage.model_validate_json(self.corpus_loader().model_dump_json())
        snapshot = ReviewedSupportKnowledge(clock=self.clock, loader=lambda: package).snapshot()
        if (
            not snapshot.available
            or package.reviewed_by is None
            or package.reviewed_at is None
            or package.valid_until is None
        ):
            raise LearningError("conflict", "The exact existing review is not currently eligible.")
        document = next(
            (doc.document() for doc in package.documents if doc.source_id == revision.source_id),
            None,
        )
        if document is None or support_document_digest(document) != revision.normalized_sha256:
            raise LearningError(
                "conflict", "Existing review does not attest this exact source copy."
            )
        record = ImportedReview(
            reviewer_label=package.reviewed_by,
            reviewed_at=package.reviewed_at,
            valid_until=package.valid_until,
            package_revision=package.revision,
            package_sha256=support_corpus_digest(package),
            document_sha256=revision.normalized_sha256,
        )
        if revision.imported_review != record or revision.revision != package.revision:
            raise LearningError("conflict", "Historical review provenance changed before adoption.")
        return record

    def advance(
        self,
        revision_id: str,
        *,
        action: KnowledgeAction,
        expected_sequence: int,
        key: str,
        actor: AuthenticatedAccount,
        reason: str,
        reviewed_document_sha256: str | None = None,
        valid_until: datetime | None = None,
    ) -> KnowledgeHistory:
        now = self._actor(actor)
        if (
            type(expected_sequence) is not int
            or expected_sequence < 0
            or action in {"ingest", "publish"}
        ):
            raise LearningError("invalid_state", "Use a supported explicit knowledge transition.")
        if valid_until is not None:
            valid_until = as_utc(valid_until)
        legacy = (
            self._review_record(self.get(revision_id, actor=actor).revision)
            if action == "adopt_existing_review"
            else None
        )
        if action == "adopt_existing_review" and (
            valid_until is not None
            or (
                reviewed_document_sha256 is not None
                and legacy is not None
                and reviewed_document_sha256 != legacy.document_sha256
            )
        ):
            raise LearningError(
                "conflict", "Adoption cannot alter the existing review or validity."
            )
        command = _transition_command(
            revision_id,
            action,
            expected_sequence,
            actor.account.id,
            reason,
            reviewed_document_sha256,
            valid_until,
        )
        with self.repository.write() as store:
            store.require_role(actor.account.id, "admin")
            now = self._actor(actor)
            history = store.history(revision_id)
            if history is None:
                raise LearningError("not_found", "Knowledge revision not found.")
            prior = next((event for event in history.events if event.operation_key == key), None)
            if prior is not None:
                if prior.command_sha256 != command:
                    raise LearningError(
                        "conflict", "Knowledge operation key belongs to different inputs."
                    )
                return history
            if history.sequence != expected_sequence:
                raise LearningError("conflict", "Knowledge revision changed before finalization.")
            targets: dict[KnowledgeAction, KnowledgeState] = {
                "parse": "parsed",
                "normalize": "normalized",
                "chunk": "chunked",
                "index": "indexed",
                "validate": "validated",
                "review": "reviewed",
                "approve": "approved",
                "adopt_existing_review": "approved",
                "reject": "rejected",
                "revoke": "revoked",
                "expire": "expired",
            }
            if action not in targets:
                raise LearningError("invalid_state", "Knowledge transition is unsupported.")
            # Parsing/normalization/validation recheck exact immutable snapshots.
            KnowledgeRevision.model_validate_json(history.revision.model_dump_json())
            chunks = source_chunks(history.revision) if action == "chunk" else ()
            index_digest = lexical_index_digest(history.revision) if action == "index" else None
            if action == "index":
                # Candidate-only preparation; never wired as the learner corpus.
                # Human approval and publication remain separate later gates.
                ApprovedSupportKnowledge((history.revision.document(),))
            review_digest = reviewed_document_sha256
            origin = None
            historical_label = None
            historical_at = None
            if action == "adopt_existing_review":
                assert legacy is not None
                review_digest = legacy.document_sha256
                valid_until = legacy.valid_until
                origin, historical_label, historical_at = (
                    "imported_record",
                    legacy.reviewer_label,
                    legacy.reviewed_at,
                )
            elif action == "approve":
                origin = "manual"
            if action == "expire" and (
                history.approval is None
                or history.approval.valid_until is None
                or history.approval.valid_until > now
            ):
                raise LearningError("conflict", "A current approval cannot be marked expired.")
            event = sealed(
                KnowledgeEvent,
                id=str(uuid4()),
                revision_id=revision_id,
                sequence=history.sequence + 1,
                operation_key=key,
                command_sha256=command,
                previous_event_sha256=history.events[-1].content_sha256,
                previous_state=history.state,
                state=targets[action],
                action=action,
                actor_id=str(actor.account.id),
                created_at=now,
                reason=reason,
                chunks=chunks,
                index_sha256=index_digest,
                lexical_index=lexical_index_artifact(history.revision)
                if action == "index"
                else None,
                reviewed_document_sha256=review_digest,
                review_origin=origin,
                historical_reviewer_label=historical_label,
                historical_reviewed_at=historical_at,
                valid_until=valid_until,
            )
            store.append(event, expected_sequence)
            result = store.history(revision_id)
            assert result is not None
            return result

    def import_reviewed_corpus(
        self, *, key: str, actor: AuthenticatedAccount, adopt_existing_review: bool = False
    ) -> tuple[KnowledgeHistory, ...]:
        self._actor(actor)
        with self.repository.read() as store:
            store.require_role(actor.account.id, "admin")
            package = SupportCorpusPackage.model_validate_json(
                self.corpus_loader().model_dump_json()
            )
            if (
                not ReviewedSupportKnowledge(clock=self.clock, loader=lambda: package).available
                or package.reviewed_by is None
                or package.reviewed_at is None
                or package.valid_until is None
            ):
                raise LearningError(
                    "conflict", "Existing reviewed corpus is unavailable for explicit import."
                )
            digest = support_corpus_digest(package)
            reviews = {
                document.source_id: ImportedReview(
                    reviewer_label=package.reviewed_by,
                    reviewed_at=package.reviewed_at,
                    valid_until=package.valid_until,
                    package_revision=package.revision,
                    package_sha256=digest,
                    document_sha256=package.document_digests[document.source_id],
                )
                for document in package.documents
            }
            # A lost response can follow a committed import. Read its exact command
            # history once before falling back to the existing checkpoint writes.
            replayed = []
            for document in package.documents:
                history = store.by_creation_key(operation_key(key, document.source_id + ":ingest"))
                if history is None or not _matches_import(
                    history,
                    document,
                    reviews[document.source_id],
                    key,
                    actor.account.id,
                    adopt_existing_review=adopt_existing_review,
                ):
                    break
                replayed.append(history)
            else:
                self._actor(actor)
                return tuple(replayed)
        result = []
        for document in package.documents:
            history = self.ingest(
                document,
                revision=package.revision,
                key=operation_key(key, document.source_id + ":ingest"),
                actor=actor,
                imported_review=reviews[document.source_id],
            )
            for sequence, action in enumerate(_IMPORT_STEPS):
                history = self.advance(
                    history.revision.id,
                    action=action,
                    expected_sequence=sequence,
                    key=operation_key(key, document.source_id + ":" + action),
                    actor=actor,
                    reason=_IMPORT_REASON,
                )
            if adopt_existing_review:
                history = self.advance(
                    history.revision.id,
                    action="adopt_existing_review",
                    expected_sequence=len(_IMPORT_STEPS),
                    key=operation_key(key, document.source_id + ":adopt"),
                    actor=actor,
                    reason=_ADOPTION_REASON,
                )
            result.append(history)
        return tuple(result)

    def publish(
        self,
        revision_ids: tuple[str, ...],
        *,
        key: str,
        expected_sequence: int,
        actor: AuthenticatedAccount,
        reason: str,
    ) -> KnowledgePublication:
        now = self._actor(actor)
        if (
            type(revision_ids) is not tuple
            or not 1 <= len(revision_ids) <= 32
            or len(set(revision_ids)) != len(revision_ids)
            or type(expected_sequence) is not int
            or expected_sequence < -1
        ):
            raise LearningError(
                "invalid_state", "Use bounded unique source revisions and a publication sequence."
            )
        command = canonical_digest(
            {
                "revision_ids": sorted(revision_ids),
                "expected_sequence": expected_sequence,
                "actor_id": str(actor.account.id),
                "reason": reason,
            }
        )
        with self.repository.write() as store:
            store.require_role(actor.account.id, "admin")
            now = self._actor(actor)
            prior = store.publication_by_key(key)
            if prior is not None:
                if prior.command_sha256 != command:
                    raise LearningError("conflict", "Publication key belongs to different inputs.")
                return prior
            histories = [store.history(revision_id) for revision_id in revision_ids]
            if any(history is None for history in histories):
                raise LearningError("not_found", "A selected knowledge revision is missing.")
            selected = sorted(
                (h for h in histories if h is not None), key=lambda h: h.revision.source_id
            )
            if len({h.revision.source_id for h in selected}) != len(selected) or any(
                h.state not in {"approved", "published"}
                or h.approval is None
                or h.approval.valid_until is None
                or h.approval.valid_until <= now
                or h.index_sha256 is None
                for h in selected
            ):
                raise LearningError(
                    "conflict",
                    "Publication requires exact validated, approved and unexpired sources.",
                )
            ApprovedSupportKnowledge(tuple(history.revision.document() for history in selected))
            manifest = sealed(
                KnowledgeManifest,
                revision_ids=tuple(h.revision.id for h in selected),
                revision_sha256=tuple(h.revision.content_sha256 for h in selected),
                approval_sha256=tuple(h.approval.content_sha256 for h in selected if h.approval),
                chunk_ids=tuple(chunk.chunk_id for h in selected for chunk in h.chunks),
                lexical_index_sha256=tuple(h.index_sha256 for h in selected),
            )
            previous = store.current_publication()
            if (previous.sequence if previous else -1) != expected_sequence:
                raise LearningError("conflict", "Active publication changed before finalization.")
            store.put_manifest(manifest, str(actor.account.id), now)
            for history in selected:
                if history.state == "approved":
                    event = sealed(
                        KnowledgeEvent,
                        id=str(uuid4()),
                        revision_id=history.revision.id,
                        sequence=history.sequence + 1,
                        operation_key=operation_key(key, history.revision.id),
                        command_sha256=command,
                        previous_event_sha256=history.events[-1].content_sha256,
                        previous_state="approved",
                        state="published",
                        action="publish",
                        actor_id=str(actor.account.id),
                        created_at=now,
                        reason=reason,
                    )
                    store.append(event, history.sequence)
            value = sealed(
                KnowledgePublication,
                id=str(uuid4()),
                sequence=expected_sequence + 1,
                operation_key=key,
                command_sha256=command,
                previous_manifest_sha256=previous.manifest_sha256 if previous else None,
                manifest_sha256=manifest.content_sha256,
                actor_id=str(actor.account.id),
                created_at=now,
                reason=reason,
            )
            final_now = self._actor(actor)
            store.require_role(actor.account.id, "admin")
            if any(
                h.approval is None
                or h.approval.valid_until is None
                or h.approval.valid_until <= final_now
                for h in selected
            ):
                raise LearningError("conflict", "A selected source expired before publication.")
            store.publish(value, expected_sequence)
            return value

    def store_index(
        self, index: EmbeddingIndex, *, key: str, actor: AuthenticatedAccount
    ) -> EmbeddingIndex:
        now = self._actor(actor)
        checked = EmbeddingIndex.model_validate_json(index.model_dump_json())
        if (
            checked.metadata.scope != "production_candidate"
            or checked.metadata.source != "ai"
            or checked.metadata.created_at > now
        ):
            raise LearningError(
                "conflict",
                "Only genuine bounded production-candidate index receipts may be archived.",
            )
        with self.repository.write() as store:
            store.require_role(actor.account.id, "admin")
            now = self._actor(actor)
            snapshot = archive_snapshot(store, now)
            if not checked.matches_snapshot(snapshot):
                raise LearningError(
                    "conflict", "Index does not match the current eligible source manifest."
                )
            prior = store.index_by_key(key) or store.index(checked.index_sha256)
            if prior is not None:
                if prior != checked:
                    raise LearningError(
                        "conflict", "Index key belongs to different immutable vectors."
                    )
                return prior
            store.put_index(checked, key, str(actor.account.id))
            return checked

    def authorize_release(
        self,
        answer: VersionedSupportAnswer,
        *,
        actor: AuthenticatedAccount,
        request_id: str,
        receipt_id: str | None = None,
        retrieval_profile: Literal["lexical", "semantic", "hybrid"] = "lexical",
        index_sha256: str | None = None,
    ) -> KnowledgeReleaseReceipt:
        now = self._actor(actor, learner=True)
        checked = VersionedSupportAnswer.model_validate_json(answer.model_dump_json())
        if (
            checked.response.status != "answered"
            or checked.response.source != "ai"
            or checked.manifest_sha256 is None
            or not checked.passages
            or retrieval_profile != checked.retrieval_profile
            or index_sha256 != checked.index_sha256
            or not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 64
        ):
            raise LearningError(
                "conflict",
                "Only a grounded genuine answer may receive an authorized release receipt.",
            )
        with self.repository.write() as store:
            store.require_role(actor.account.id, "learner")
            now = self._actor(actor, learner=True)
            # Serialization orders this release decision against publication and
            # revocation, after all slow provider work has already completed.
            snapshot = archive_snapshot(store, now)
            if (
                not snapshot.available
                or snapshot.manifest_sha256 != checked.manifest_sha256
                or any(
                    (match := snapshot.reconstruct(version)) is None
                    or match.title != reference.source_name
                    or match.text != reference.quote
                    for reference, version in zip(
                        checked.response.references, checked.passages, strict=True
                    )
                )
            ):
                raise LearningError("conflict", "Knowledge changed before answer release.")
            space: str | None = None
            vector_hashes: tuple[str, ...] = ()
            if retrieval_profile != "lexical":
                index = store.index(index_sha256) if index_sha256 else None
                if index is None or not index.matches_snapshot(snapshot):
                    raise LearningError(
                        "conflict", "Selected semantic index is unavailable or stale."
                    )
                space = index.metadata.profile.space_sha256
                vectors = {p.version.chunk_id: p.vector.vector_sha256 for p in index.passages}
                vector_hashes = tuple(vectors[version.chunk_id] for version in checked.passages)
            receipt = sealed(
                KnowledgeReleaseReceipt,
                id=receipt_id or str(uuid4()),
                created_at=now,
                request_id_sha256=hashlib.sha256(request_id.encode("utf-8")).hexdigest(),
                manifest_sha256=checked.manifest_sha256,
                publication_sequence=snapshot.publication_sequence,
                passages=checked.passages,
                retrieval_profile=retrieval_profile,
                index_sha256=index_sha256,
                embedding_space_sha256=space,
                selected_vector_sha256=vector_hashes,
            )
            prior = store.receipt(receipt.id)

            def still_authorized() -> None:
                final_now = self._actor(actor, learner=True)
                store.require_role(actor.account.id, "learner")
                if any(
                    source.valid_until is None or source.valid_until <= final_now
                    for source in snapshot.sources
                ):
                    raise LearningError("conflict", "Knowledge expired before answer release.")

            if prior is not None:
                omit = {"created_at", "content_sha256"}
                if prior.model_dump(exclude=omit) != receipt.model_dump(exclude=omit):
                    raise LearningError(
                        "conflict", "Release identity belongs to a different decision."
                    )
                still_authorized()
                return prior
            store.put_receipt(receipt)
            still_authorized()
            return receipt
