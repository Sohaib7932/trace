"""Short reservation/finalization transactions; no provider work in a database context."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db import models as m
from app.db.guide_models import PrivateLearningGuide as Guide
from app.db.session import Database
from app.domain.learning import LearningError
from app.schemas.private_guides import GuideContent, GuideCreate, GuideDetail, canonical_digest


class SqlPrivateGuideRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def access(
        self, owner: UUID, issuer: str, subject: str
    ) -> tuple[bool, UUID | None, str | None, bool]:
        with self.database.session() as session:
            user = session.get(m.User, owner)
            linked = session.scalar(
                select(m.AuthSubject.user_id).where(
                    m.AuthSubject.issuer == issuer,
                    m.AuthSubject.subject == subject,
                )
            )
            role = session.scalar(
                select(m.UserRole.role).where(
                    m.UserRole.user_id == owner,
                    m.UserRole.role == "learner",
                )
            )
            return (
                user is not None,
                linked,
                user.status if user is not None else None,
                role is not None,
            )

    @staticmethod
    def detail(row: Guide) -> GuideDetail:
        request = GuideCreate.model_validate(row.request_payload)
        if canonical_digest(request) != row.request_sha256:
            raise LearningError("dependency_unavailable", "Guide integrity failed.")
        return GuideDetail.model_validate(
            {
                "id": row.id,
                "topic": request.topic,
                "status": row.status,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "version": row.version,
                "title": row.content.get("title") if row.content else None,
                "request": request,
                "content": row.content,
                "content_sha256": row.content_sha256,
                "source": row.source,
            }
        )

    def get(self, owner: UUID, identity: UUID, now: datetime) -> GuideDetail:
        with self.database.session() as session, session.begin():
            # A crashed worker's reservation is terminal, not an indefinite spinner
            # or permission to replay a paid/network request with the same key.
            session.execute(
                update(Guide)
                .where(
                    Guide.id == identity,
                    Guide.owner_id == owner,
                    Guide.status == "generating",
                    Guide.reservation_expires_at <= now,
                )
                .values(status="unavailable", updated_at=now)
            )
            row = session.scalar(select(Guide).where(Guide.id == identity, Guide.owner_id == owner))
            if row is None:
                raise LearningError("not_found", "Guide not found.")
            return self.detail(row)

    def list(self, owner: UUID, now: datetime) -> tuple[GuideDetail, ...]:
        with self.database.session() as session, session.begin():
            session.execute(
                update(Guide)
                .where(
                    Guide.owner_id == owner,
                    Guide.status == "generating",
                    Guide.reservation_expires_at <= now,
                )
                .values(status="unavailable", updated_at=now)
            )
            rows = session.scalars(
                select(Guide)
                .where(Guide.owner_id == owner)
                .order_by(Guide.created_at.desc(), Guide.id.desc())
                .limit(50)
            )
            return tuple(self.detail(row) for row in rows)

    def reserve(
        self, owner: UUID, key: UUID, request: GuideCreate, now: datetime
    ) -> tuple[GuideDetail, bool]:
        digest = canonical_digest(request)
        try:
            with self.database.session() as session, session.begin():
                # Reserve writer ownership before the idempotency read, as in
                # account/custom-lesson writes; avoid SQLite read-to-write upgrades.
                session.execute(update(m.WriteGate).where(m.WriteGate.id == 1).values(id=1))
                existing = session.scalar(
                    select(Guide).where(Guide.owner_id == owner, Guide.creation_key == key)
                )
                if existing is not None:
                    if existing.request_sha256 != digest:
                        raise LearningError(
                            "conflict", "Idempotency key belongs to another request."
                        )
                    identity = existing.id
                else:
                    row = Guide(
                        id=uuid4(),
                        owner_id=owner,
                        creation_key=key,
                        request_sha256=digest,
                        request_payload=request.model_dump(mode="json"),
                        status="generating",
                        version="1.0.0",
                        content=None,
                        content_sha256=None,
                        source=None,
                        generation_provenance=None,
                        created_at=now,
                        updated_at=now,
                        reservation_expires_at=now + timedelta(seconds=60),
                    )
                    session.add(row)
                    session.flush()
                    return self.detail(row), True
            return self.get(owner, identity, now), False
        except IntegrityError:
            # Another process may have reserved the unique owner/key concurrently.
            with self.database.session() as session:
                existing = session.scalar(
                    select(Guide).where(Guide.owner_id == owner, Guide.creation_key == key)
                )
                if existing is None:
                    raise LearningError(
                        "dependency_unavailable", "Guide reservation failed."
                    ) from None
                if existing.request_sha256 != digest:
                    raise LearningError(
                        "conflict", "Idempotency key belongs to another request."
                    ) from None
                identity = existing.id
            return self.get(owner, identity, now), False

    def finish(
        self,
        owner: UUID,
        identity: UUID,
        content: GuideContent | None,
        source: str | None,
        now: datetime,
        provenance: dict[str, str | None] | None = None,
    ) -> GuideDetail:
        with self.database.session() as session, session.begin():
            session.execute(
                update(Guide)
                .where(
                    Guide.id == identity,
                    Guide.owner_id == owner,
                    Guide.status == "generating",
                    Guide.reservation_expires_at > now,
                )
                .values(
                    status="ready" if content else "unavailable",
                    content=content.model_dump(mode="json") if content else None,
                    content_sha256=canonical_digest(content) if content else None,
                    source=source if content else None,
                    generation_provenance=(
                        provenance or {"policy_version": "private-guide-generator-v1"}
                    )
                    if content
                    else None,
                    updated_at=now,
                )
            )
        return self.get(owner, identity, now)
