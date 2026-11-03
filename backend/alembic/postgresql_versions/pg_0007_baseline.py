"""Frozen PostgreSQL equivalent of SQLite 0007; separate, explicit lineage.

Only an empty application schema may enter this baseline. Historical SQLite
revisions remain unchanged. This is not a stamp or a dynamic metadata bootstrap.
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_tutor_reservations"
down_revision = None
branch_labels = None
depends_on = None

HISTORICAL_SHA256 = {
    "0001_foundation.py": "c71076e5c20545012fdebee6190036f98911f75357aed9cd1e08c43b6880bcf5",
    "0002_learning_learning_engine.py": (
        "6b32b170f2ff7f41b90b9462fc2c26c699a703233c088bb04e3787e422c2e602"
    ),
    "0003_constraint_names.py": "83224002abfa28f1b67f91fdc5652ed0787cb5518ece4ed0b63369b960efb507",
    "0004_transfer_retrieval.py": (
        "9e40aff00bc40356df8676a399ad8cc0135d3381de3b052aeee4457bee2951ac"
    ),
    "0005_account_identity.py": "af1ca8caa3dde017af586d7f20285abfe73d88ef5930f544aa2f16e067ba0623",
    "0006_candidate_lifecycle.py": (
        "fd4c436cc0a39762e87755e48424e6ef076ab842ac082b1208cb4cc0404910bc"
    ),
    "0007_tutor_reservations.py": (
        "c57faf31c8c0d307e5961f9c1101e76f6bdf70cc8f22166e434ded09a44cb1d8"
    ),
}

GUARDS = (
    (
        "account_credential_insert",
        "BEFORE INSERT",
        "learner_credentials",
        "EXISTS\n        (SELECT 1 FROM account_learners WHERE learner_id=NEW.learner_id)",
        "account learner cannot receive guest credentials",
    ),
    (
        "account_credential_update",
        "BEFORE UPDATE",
        "learner_credentials",
        "EXISTS\n"
        "        (SELECT 1 FROM account_learners WHERE learner_id IN (NEW.learner_id, "
        "OLD.learner_id))\n"
        "        AND (NEW.revoked_at IS NULL OR NEW.learner_id != OLD.learner_id\n"
        "             OR NEW.token_hash != OLD.token_hash OR NEW.expires_at != OLD.expires_at)",
        "claimed credentials cannot be reactivated",
    ),
    (
        "account_owner_exclusive",
        "BEFORE INSERT",
        "account_learners",
        "EXISTS (SELECT 1 FROM learner_credentials WHERE learner_id=NEW.learner_id\n"
        "                AND revoked_at IS NULL) OR\n"
        "        (NEW.claimed_credential_id IS NOT NULL AND NOT EXISTS\n"
        "          (SELECT 1 FROM learner_credentials WHERE id=NEW.claimed_credential_id\n"
        "           AND learner_id=NEW.learner_id AND revoked_at IS NOT NULL))",
        "revoke guest credentials before attaching account",
    ),
    (
        "attempt_mapping_scope",
        "BEFORE INSERT",
        "attempts",
        "NOT EXISTS\n"
        "        (SELECT 1 FROM learning_sessions s JOIN lesson_versions v ON "
        "v.id=s.lesson_version_id\n"
        "         WHERE s.id=NEW.session_id AND\n"
        "          ((v.lesson_id='fastapi-payload-mismatch' AND NEW.field_name IN "
        "('body','content')) OR\n"
        "           (v.lesson_id='fastapi-nested-payload-transfer' AND NEW.field_name IN "
        "('flat','nested'))))",
        "mapping does not belong to lesson",
    ),
    (
        "candidate_event_admin",
        "BEFORE INSERT",
        "candidate_lifecycle_events",
        "NEW.action IN ('human_review','production_approval','reject') AND NOT EXISTS (\n"
        "        SELECT 1 FROM users JOIN user_roles ON users.id=user_roles.user_id\n"
        "        WHERE users.id=NEW.actor_id AND users.status='active' AND "
        "user_roles.role='admin')",
        "candidate review requires active admin",
    ),
    (
        "candidate_event_chain",
        "BEFORE INSERT",
        "candidate_lifecycle_events",
        "NEW.revision != COALESCE((SELECT MAX(revision)+1 FROM candidate_lifecycle_events\n"
        "        WHERE candidate_id=NEW.candidate_id),0) OR\n"
        "      NEW.previous_state IS DISTINCT FROM (SELECT state FROM "
        "candidate_lifecycle_events\n"
        "        WHERE candidate_id=NEW.candidate_id ORDER BY revision DESC LIMIT 1)",
        "candidate revision or predecessor mismatch",
    ),
    (
        "candidate_event_transition",
        "BEFORE INSERT",
        "candidate_lifecycle_events",
        "NOT COALESCE((\n"
        "      (NEW.action='created' AND NEW.revision=0 AND NEW.previous_state IS NULL\n"
        "        AND NEW.state='composed') OR\n"
        "      (NEW.action='validation' AND NEW.previous_state IN "
        "('composed','validation_unavailable')\n"
        "        AND NEW.state IN ('validated','validation_unavailable','rejected')) OR\n"
        "      (NEW.action='human_review' AND NEW.previous_state='validated'\n"
        "        AND NEW.state='human_reviewed') OR\n"
        "      (NEW.action='production_approval' AND NEW.previous_state='human_reviewed'\n"
        "        AND NEW.state='production_approved') OR\n"
        "      (NEW.action='reject' AND NEW.previous_state IN ('validated','human_reviewed')\n"
        "        AND NEW.state='rejected')),FALSE)",
        "invalid candidate state transition",
    ),
    (
        "checkpoint_completion",
        "BEFORE UPDATE",
        "retrieval_checkpoints",
        "OLD.completed_at IS NOT NULL OR NEW.completed_at IS NULL OR\n"
        "        NEW.completed_at < OLD.due_at OR NEW.id != OLD.id OR\n"
        "        NEW.transfer_session_id != OLD.transfer_session_id OR NEW.ordinal != "
        "OLD.ordinal OR\n"
        "        NEW.question_id != OLD.question_id OR NEW.question_hash != OLD.question_hash "
        "OR\n"
        "        NEW.due_at != OLD.due_at OR NEW.created_at != OLD.created_at OR\n"
        "        NOT EXISTS (SELECT 1 FROM retrieval_attempts WHERE checkpoint_id=OLD.id AND "
        "correct = TRUE)",
        "checkpoint identity/schedule/completion protected",
    ),
    (
        "checkpoint_source",
        "BEFORE INSERT",
        "retrieval_checkpoints",
        "NOT EXISTS\n"
        "        (SELECT 1 FROM learning_sessions s JOIN lesson_versions v ON "
        "v.id=s.lesson_version_id\n"
        "         WHERE s.id=NEW.transfer_session_id AND s.state='completed'\n"
        "         AND v.lesson_id='fastapi-nested-payload-transfer') OR NEW.completed_at IS NOT "
        "NULL",
        "checkpoint requires completed transfer",
    ),
    (
        "checks_before_finalization",
        "BEFORE INSERT",
        "verification_checks",
        "NOT EXISTS (SELECT 1 FROM verification_runs\n"
        "          WHERE id = NEW.run_id AND status = 'pending')",
        "checks require pending run",
    ),
    (
        "completion_evidence",
        "BEFORE UPDATE OF state",
        "learning_sessions",
        "NEW.state = 'completed' AND NOT EXISTS\n"
        "          (SELECT 1 FROM verification_runs WHERE session_id = NEW.id AND status = "
        "'passed')",
        "completion requires successful verification",
    ),
    (
        "finalize_run_once",
        "BEFORE UPDATE",
        "verification_runs",
        "OLD.status != 'pending' OR NEW.status NOT IN ('passed','failed','error') OR\n"
        "          NEW.id != OLD.id OR NEW.session_id != OLD.session_id OR\n"
        "          NEW.attempt_id != OLD.attempt_id OR NEW.idempotency_key != "
        "OLD.idempotency_key OR\n"
        "          NEW.created_at != OLD.created_at",
        "verification result is immutable",
    ),
    (
        "hint_operation_identity",
        "BEFORE UPDATE",
        "hint_operations",
        "NEW.id IS DISTINCT FROM OLD.id OR NEW.session_id IS DISTINCT FROM OLD.session_id OR\n"
        "        NEW.attempt_id IS DISTINCT FROM OLD.attempt_id OR NEW.sequence IS DISTINCT FROM "
        "OLD.sequence OR\n"
        "        NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR\n"
        "        NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.deadline_at IS DISTINCT "
        "FROM OLD.deadline_at OR\n"
        "        OLD.status != 'pending' OR NEW.status != 'finalized' OR NEW.completed_at IS "
        "NULL",
        "hint operation is immutable",
    ),
    (
        "hint_operation_preserve",
        "BEFORE DELETE",
        "hint_operations",
        None,
        "hint request history is preserved",
    ),
    (
        "hint_operation_result",
        "BEFORE UPDATE OF status",
        "hint_operations",
        "NOT EXISTS (\n"
        "        SELECT 1 FROM tutor_interactions WHERE id=NEW.id AND session_id=NEW.session_id\n"
        "        AND attempt_id IS NOT DISTINCT FROM NEW.attempt_id AND sequence=NEW.sequence\n"
        "        AND idempotency_key=NEW.idempotency_key AND created_at=NEW.completed_at)",
        "hint finalization requires matching result",
    ),
    (
        "hint_operation_sequence",
        "BEFORE INSERT",
        "hint_operations",
        "NEW.status != 'pending' OR NEW.completed_at IS NOT NULL OR\n"
        "        NEW.sequence != COALESCE((SELECT MAX(sequence) FROM (\n"
        "          SELECT sequence FROM tutor_interactions WHERE session_id=NEW.session_id\n"
        "          UNION ALL SELECT sequence FROM hint_operations WHERE "
        "session_id=NEW.session_id\n"
        "        ) AS all_hint_requests), 0) + 1 OR EXISTS (\n"
        "          SELECT 1 FROM tutor_interactions WHERE session_id=NEW.session_id\n"
        "          AND idempotency_key=NEW.idempotency_key)",
        "hint operation must reserve the next request",
    ),
    (
        "hint_result_reservation",
        "BEFORE INSERT",
        "tutor_interactions",
        "EXISTS (\n"
        "        SELECT 1 FROM hint_operations WHERE id=NEW.id OR\n"
        "        (session_id=NEW.session_id AND\n"
        "          (sequence=NEW.sequence OR idempotency_key=NEW.idempotency_key)))\n"
        "        AND NOT EXISTS (\n"
        "        SELECT 1 FROM hint_operations WHERE id=NEW.id AND status='pending'\n"
        "        AND session_id=NEW.session_id AND attempt_id IS NOT DISTINCT FROM "
        "NEW.attempt_id\n"
        "        AND sequence=NEW.sequence AND idempotency_key=NEW.idempotency_key)",
        "hint result must match its pending reservation",
    ),
    (
        "immutable_account_learners",
        "BEFORE UPDATE",
        "account_learners",
        None,
        "account identity is immutable",
    ),
    ("immutable_attempts_delete", "BEFORE DELETE", "attempts", None, "append-only record"),
    ("immutable_attempts_update", "BEFORE UPDATE", "attempts", None, "append-only record"),
    (
        "immutable_auth_subjects",
        "BEFORE UPDATE",
        "auth_subjects",
        "NEW.id != OLD.id OR NEW.issuer != OLD.issuer OR NEW.subject != OLD.subject OR "
        "NEW.user_id != OLD.user_id OR NEW.created_at != OLD.created_at",
        "account identity is immutable",
    ),
    (
        "immutable_learning_events_delete",
        "BEFORE DELETE",
        "learning_events",
        None,
        "append-only record",
    ),
    (
        "immutable_learning_events_update",
        "BEFORE UPDATE",
        "learning_events",
        None,
        "append-only record",
    ),
    (
        "immutable_lesson_versions_delete",
        "BEFORE DELETE",
        "lesson_versions",
        None,
        "append-only record",
    ),
    (
        "immutable_lesson_versions_update",
        "BEFORE UPDATE",
        "lesson_versions",
        None,
        "append-only record",
    ),
    ("immutable_predictions_delete", "BEFORE DELETE", "predictions", None, "append-only record"),
    ("immutable_predictions_update", "BEFORE UPDATE", "predictions", None, "append-only record"),
    (
        "immutable_retrieval_attempts_delete",
        "BEFORE DELETE",
        "retrieval_attempts",
        None,
        "append-only record",
    ),
    (
        "immutable_retrieval_attempts_update",
        "BEFORE UPDATE",
        "retrieval_attempts",
        None,
        "append-only record",
    ),
    (
        "immutable_role_grant_events",
        "BEFORE UPDATE",
        "role_grant_events",
        None,
        "account identity is immutable",
    ),
    (
        "immutable_runtime_notes_delete",
        "BEFORE DELETE",
        "runtime_notes",
        None,
        "append-only record",
    ),
    (
        "immutable_runtime_notes_update",
        "BEFORE UPDATE",
        "runtime_notes",
        None,
        "append-only record",
    ),
    (
        "immutable_runtime_tasks_delete",
        "BEFORE DELETE",
        "runtime_tasks",
        None,
        "append-only record",
    ),
    (
        "immutable_runtime_tasks_update",
        "BEFORE UPDATE",
        "runtime_tasks",
        None,
        "append-only record",
    ),
    (
        "immutable_tutor_interactions_delete",
        "BEFORE DELETE",
        "tutor_interactions",
        None,
        "append-only record",
    ),
    (
        "immutable_tutor_interactions_update",
        "BEFORE UPDATE",
        "tutor_interactions",
        None,
        "append-only record",
    ),
    (
        "immutable_verification_checks_delete",
        "BEFORE DELETE",
        "verification_checks",
        None,
        "append-only record",
    ),
    (
        "immutable_verification_checks_update",
        "BEFORE UPDATE",
        "verification_checks",
        None,
        "append-only record",
    ),
    (
        "notes_run_scope",
        "BEFORE INSERT",
        "runtime_notes",
        "NOT EXISTS\n"
        "        (SELECT 1 FROM verification_runs r JOIN learning_sessions s ON "
        "s.id=r.session_id\n"
        "         JOIN lesson_versions v ON v.id=s.lesson_version_id WHERE r.id=NEW.run_id\n"
        "         AND r.status='pending' AND v.lesson_id='fastapi-payload-mismatch')",
        "note requires pending original run",
    ),
    (
        "pinned_session",
        "BEFORE UPDATE OF id, learner_id, lesson_version_id,\n        idempotency_key, created_at",
        "learning_sessions",
        None,
        "session identity/version is immutable",
    ),
    (
        "preserve_account_learners",
        "BEFORE DELETE",
        "account_learners",
        None,
        "account history preserved",
    ),
    ("preserve_auth_subjects", "BEFORE DELETE", "auth_subjects", None, "account history preserved"),
    (
        "preserve_candidate_lifecycle_events_delete",
        "BEFORE DELETE",
        "candidate_lifecycle_events",
        None,
        "candidate history preserved",
    ),
    (
        "preserve_candidate_lifecycle_events_update",
        "BEFORE UPDATE",
        "candidate_lifecycle_events",
        None,
        "candidate history preserved",
    ),
    (
        "preserve_checkpoints",
        "BEFORE DELETE",
        "retrieval_checkpoints",
        None,
        "checkpoint history is preserved",
    ),
    (
        "preserve_generated_candidates_delete",
        "BEFORE DELETE",
        "generated_candidates",
        None,
        "candidate history preserved",
    ),
    (
        "preserve_generated_candidates_update",
        "BEFORE UPDATE",
        "generated_candidates",
        None,
        "candidate history preserved",
    ),
    (
        "preserve_role_grant_events",
        "BEFORE DELETE",
        "role_grant_events",
        None,
        "account history preserved",
    ),
    (
        "preserve_runs",
        "BEFORE DELETE",
        "verification_runs",
        None,
        "verification history is append-only",
    ),
    (
        "retrieval_attempt_available",
        "BEFORE INSERT",
        "retrieval_attempts",
        "NOT EXISTS\n"
        "        (SELECT 1 FROM retrieval_checkpoints WHERE id=NEW.checkpoint_id AND "
        "completed_at IS NULL\n"
        "         AND due_at<=NEW.created_at)",
        "checkpoint not available",
    ),
    (
        "session_transition",
        "BEFORE UPDATE OF state",
        "learning_sessions",
        "NOT (NEW.state = OLD.state OR\n"
        "          (OLD.state = 'awaiting_prediction' AND NEW.state = 'ready_for_attempt') OR\n"
        "          (OLD.state = 'ready_for_attempt' AND NEW.state = 'verification_pending') OR\n"
        "          (OLD.state = 'verification_pending' AND NEW.state IN "
        "('needs_revision','completed')) OR\n"
        "          (OLD.state = 'needs_revision' AND NEW.state = 'verification_pending') OR\n"
        "          (OLD.state NOT IN ('completed','abandoned') AND NEW.state = 'abandoned'))",
        "invalid session transition",
    ),
    (
        "tasks_run_scope",
        "BEFORE INSERT",
        "runtime_tasks",
        "NOT EXISTS\n"
        "        (SELECT 1 FROM verification_runs r JOIN learning_sessions s ON "
        "s.id=r.session_id\n"
        "         JOIN lesson_versions v ON v.id=s.lesson_version_id WHERE r.id=NEW.run_id\n"
        "         AND r.status='pending' AND v.lesson_id='fastapi-nested-payload-transfer')",
        "task requires pending transfer run",
    ),
    (
        "transfer_prerequisite",
        "BEFORE INSERT",
        "learning_sessions",
        "(SELECT lesson_id FROM lesson_versions WHERE "
        "id=NEW.lesson_version_id)='fastapi-nested-payload-transfer'\n"
        "        AND NOT EXISTS (SELECT 1 FROM learning_sessions s JOIN lesson_versions v ON "
        "v.id=s.lesson_version_id\n"
        "          WHERE s.learner_id=NEW.learner_id AND s.state='completed' AND "
        "v.lesson_id='fastapi-payload-mismatch')",
        "original completion required",
    ),
    (
        "verified_run",
        "BEFORE UPDATE OF status",
        "verification_runs",
        "NEW.status = 'passed' AND\n"
        "          (SELECT COUNT(*) FROM verification_checks WHERE run_id = NEW.id AND matched = "
        "TRUE\n"
        "            AND code IN ('http_status','api_response','validation',\n"
        "                         'row_count','stored_values')) != 5",
        "successful verification requires all observed checks",
    ),
)


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL baseline requires its explicit configuration")
    schema = connection.scalar(sa.text("SELECT current_schema()"))
    if schema in {None, "pg_catalog", "information_schema"}:
        raise RuntimeError("Create the intended application schema first")
    if set(sa.inspect(connection).get_table_names(schema=schema)) - {"alembic_version"}:
        raise RuntimeError("PostgreSQL baseline requires an empty application schema")
    op.create_table(
        "generated_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_request_id", sa.Uuid(), nullable=False),
        sa.Column("creation_key", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("composition_sha256", sa.String(64), nullable=False),
        sa.Column("release_eligible", sa.Boolean(), nullable=False),
        sa.CheckConstraint("NOT release_eligible", name=op.f("ck_generated_candidates_unreleased")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_candidates")),
        sa.UniqueConstraint("creation_key", name=op.f("uq_generated_candidates_creation_key")),
        sa.UniqueConstraint(
            "generation_request_id", name=op.f("uq_generated_candidates_generation_request_id")
        ),
    )
    op.create_table(
        "learners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learners")),
    )
    op.create_table(
        "lessons",
        sa.Column("id", sa.String(80), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lessons")),
    )
    op.create_table(
        "users",
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','disabled')", name=op.f("ck_users_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_table(
        "write_gate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_write_gate")),
    )
    op.create_table(
        "account_action_limits",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("window", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_account_action_limits_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", "action", name=op.f("pk_account_action_limits")),
    )
    op.create_table(
        "auth_subjects",
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_subjects_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_subjects")),
        sa.UniqueConstraint("issuer", "subject", name=op.f("uq_auth_subjects_issuer_subject")),
    )
    op.create_index(op.f("ix_auth_subjects_user_id"), "auth_subjects", ["user_id"], unique=False)
    op.create_table(
        "candidate_lifecycle_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("operation_key", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("previous_state", sa.String(32), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("release_eligible", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "action IN ('created','validation','human_review','production_approval','reject')",
            name=op.f("ck_candidate_lifecycle_events_action"),
        ),
        sa.CheckConstraint("revision >= 0", name=op.f("ck_candidate_lifecycle_events_revision")),
        sa.CheckConstraint(
            "state IN ('composed','validated','validation_unavailable','human_reviewed',"
            "'production_approved','rejected')",
            name=op.f("ck_candidate_lifecycle_events_state"),
        ),
        sa.CheckConstraint(
            "NOT release_eligible", name=op.f("ck_candidate_lifecycle_events_unreleased")
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_candidate_lifecycle_events_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["generated_candidates.id"],
            name=op.f("fk_candidate_lifecycle_events_candidate_id_generated_candidates"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_lifecycle_events")),
        sa.UniqueConstraint(
            "candidate_id",
            "operation_key",
            name=op.f("uq_candidate_lifecycle_events_candidate_id_operation_key"),
        ),
        sa.UniqueConstraint(
            "candidate_id",
            "revision",
            name=op.f("uq_candidate_lifecycle_events_candidate_id_revision"),
        ),
    )
    op.create_index(
        op.f("ix_candidate_lifecycle_events_candidate_id"),
        "candidate_lifecycle_events",
        ["candidate_id"],
        unique=False,
    )
    op.create_table(
        "learner_credentials",
        sa.Column("learner_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learners.id"], name=op.f("fk_learner_credentials_learner_id_learners")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learner_credentials")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_learner_credentials_token_hash")),
    )
    op.create_index(
        op.f("ix_learner_credentials_learner_id"),
        "learner_credentials",
        ["learner_id"],
        unique=False,
    )
    op.create_table(
        "lesson_versions",
        sa.Column("lesson_id", sa.String(80), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("public_content", sa.JSON(), nullable=False),
        sa.Column("expected_field", sa.String(16), nullable=False),
        sa.Column("prediction_answer", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["lesson_id"], ["lessons.id"], name=op.f("fk_lesson_versions_lesson_id_lessons")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lesson_versions")),
        sa.UniqueConstraint(
            "lesson_id", "version", name=op.f("uq_lesson_versions_lesson_id_version")
        ),
    )
    op.create_index(
        op.f("ix_lesson_versions_lesson_id"), "lesson_versions", ["lesson_id"], unique=False
    )
    op.create_table(
        "role_grant_events",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("operator", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('creator','admin')", name=op.f("ck_role_grant_events_role")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_role_grant_events_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_grant_events")),
    )
    op.create_index(
        op.f("ix_role_grant_events_user_id"), "role_grant_events", ["user_id"], unique=False
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.CheckConstraint(
            "role IN ('learner','creator','admin')", name=op.f("ck_user_roles_role")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_roles_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", "role", name=op.f("pk_user_roles")),
    )
    op.create_table(
        "account_learners",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("learner_id", sa.Uuid(), nullable=False),
        sa.Column("claim_key", sa.String(36), nullable=True),
        sa.Column("claimed_credential_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(claim_key IS NULL) = (claimed_credential_id IS NULL)",
            name=op.f("ck_account_learners_claim_receipt"),
        ),
        sa.ForeignKeyConstraint(
            ["claimed_credential_id"],
            ["learner_credentials.id"],
            name=op.f("fk_account_learners_claimed_credential_id_learner_credentials"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learners.id"], name=op.f("fk_account_learners_learner_id_learners")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_account_learners_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_account_learners")),
        sa.UniqueConstraint("learner_id", name=op.f("uq_account_learners_learner_id")),
    )
    op.create_table(
        "learning_sessions",
        sa.Column("learner_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_version_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(state = 'completed') = (completed_at IS NOT NULL)",
            name=op.f("ck_learning_sessions_completion_time"),
        ),
        sa.CheckConstraint(
            "state IN ('awaiting_prediction','ready_for_attempt','verification_pending',"
            "'needs_revision','completed','abandoned')",
            name=op.f("ck_learning_sessions_state"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learners.id"], name=op.f("fk_learning_sessions_learner_id_learners")
        ),
        sa.ForeignKeyConstraint(
            ["lesson_version_id"],
            ["lesson_versions.id"],
            name=op.f("fk_learning_sessions_lesson_version_id_lesson_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_sessions")),
        sa.UniqueConstraint(
            "learner_id",
            "idempotency_key",
            name=op.f("uq_learning_sessions_learner_id_idempotency_key"),
        ),
    )
    op.create_index(
        op.f("ix_learning_sessions_learner_id"), "learning_sessions", ["learner_id"], unique=False
    )
    op.create_table(
        "attempts",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(16), nullable=False),
        sa.Column("explanation", sa.String(2000), nullable=False),
        sa.Column("hints_before", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "hints_before >= 0 AND hints_before <= 3", name=op.f("ck_attempts_hint_count")
        ),
        sa.CheckConstraint("number > 0", name=op.f("ck_attempts_positive_number")),
        sa.CheckConstraint(
            "field_name IN ('body','content','flat','nested')",
            name=op.f("ck_attempts_supported_field"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.id"],
            name=op.f("fk_attempts_session_id_learning_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attempts")),
        sa.UniqueConstraint("id", "session_id", name=op.f("uq_attempts_id_session_id")),
        sa.UniqueConstraint(
            "session_id", "idempotency_key", name=op.f("uq_attempts_session_id_idempotency_key")
        ),
        sa.UniqueConstraint("session_id", "number", name=op.f("uq_attempts_session_id_number")),
    )
    op.create_index(op.f("ix_attempts_session_id"), "attempts", ["session_id"], unique=False)
    op.create_table(
        "learning_events",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.id"],
            name=op.f("fk_learning_events_session_id_learning_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_events")),
    )
    op.create_index(
        op.f("ix_learning_events_session_id"), "learning_events", ["session_id"], unique=False
    )
    op.create_table(
        "predictions",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("selected_answer", sa.String(32), nullable=False),
        sa.Column("reasoning", sa.String(2000), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.id"],
            name=op.f("fk_predictions_session_id_learning_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_predictions")),
        sa.UniqueConstraint("session_id", name=op.f("uq_predictions_session_id")),
    )
    op.create_table(
        "retrieval_checkpoints",
        sa.Column("transfer_session_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.String(64), nullable=False),
        sa.Column("question_hash", sa.String(64), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ordinal IN (1,2)", name=op.f("ck_retrieval_checkpoints_ordinal")),
        sa.ForeignKeyConstraint(
            ["transfer_session_id"],
            ["learning_sessions.id"],
            name=op.f("fk_retrieval_checkpoints_transfer_session_id_learning_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_checkpoints")),
        sa.UniqueConstraint(
            "transfer_session_id",
            "ordinal",
            name=op.f("uq_retrieval_checkpoints_transfer_session_id_ordinal"),
        ),
    )
    op.create_index(
        op.f("ix_retrieval_checkpoints_transfer_session_id"),
        "retrieval_checkpoints",
        ["transfer_session_id"],
        unique=False,
    )
    op.create_table(
        "hint_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name=op.f("ck_hint_operations_completed_after_request"),
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (completed_at IS NULL)",
            name=op.f("ck_hint_operations_completion_time"),
        ),
        sa.CheckConstraint("deadline_at > created_at", name=op.f("ck_hint_operations_deadline")),
        sa.CheckConstraint("sequence BETWEEN 1 AND 3", name=op.f("ck_hint_operations_hint_limit")),
        sa.CheckConstraint(
            "status IN ('pending','finalized')", name=op.f("ck_hint_operations_status")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "session_id"],
            ["attempts.id", "attempts.session_id"],
            name=op.f("fk_hint_operations_attempt_id_attempts"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.id"],
            name=op.f("fk_hint_operations_session_id_learning_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hint_operations")),
        sa.UniqueConstraint(
            "session_id",
            "idempotency_key",
            name=op.f("uq_hint_operations_session_id_idempotency_key"),
        ),
        sa.UniqueConstraint(
            "session_id", "sequence", name=op.f("uq_hint_operations_session_id_sequence")
        ),
    )
    op.create_index(
        op.f("ix_hint_operations_session_id"), "hint_operations", ["session_id"], unique=False
    )
    op.create_index(
        op.f("uq_hint_operations_pending_session"),
        "hint_operations",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "retrieval_attempts",
        sa.Column("checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("selection", sa.String(1), nullable=False),
        sa.Column("reasoning", sa.String(2000), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("feedback", sa.String(2000), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("number > 0", name=op.f("ck_retrieval_attempts_positive_number")),
        sa.CheckConstraint(
            "selection IN ('a','b','c')", name=op.f("ck_retrieval_attempts_selection")
        ),
        sa.ForeignKeyConstraint(
            ["checkpoint_id"],
            ["retrieval_checkpoints.id"],
            name=op.f("fk_retrieval_attempts_checkpoint_id_retrieval_checkpoints"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_attempts")),
        sa.UniqueConstraint(
            "checkpoint_id",
            "idempotency_key",
            name=op.f("uq_retrieval_attempts_checkpoint_id_idempotency_key"),
        ),
        sa.UniqueConstraint(
            "checkpoint_id", "number", name=op.f("uq_retrieval_attempts_checkpoint_id_number")
        ),
    )
    op.create_index(
        op.f("ix_retrieval_attempts_checkpoint_id"),
        "retrieval_attempts",
        ["checkpoint_id"],
        unique=False,
    )
    op.create_table(
        "tutor_interactions",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(2400), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("fixture", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("interaction_type", sa.String(16), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence BETWEEN 1 AND 3", name=op.f("ck_tutor_interactions_hint_limit")
        ),
        sa.CheckConstraint(
            "status IN ('delivered','error')", name=op.f("ck_tutor_interactions_status")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "session_id"],
            ["attempts.id", "attempts.session_id"],
            name=op.f("fk_tutor_interactions_attempt_id_attempts"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.id"],
            name=op.f("fk_tutor_interactions_session_id_learning_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_interactions")),
        sa.UniqueConstraint(
            "session_id",
            "idempotency_key",
            name=op.f("uq_tutor_interactions_session_id_idempotency_key"),
        ),
        sa.UniqueConstraint(
            "session_id", "sequence", name=op.f("uq_tutor_interactions_session_id_sequence")
        ),
    )
    op.create_index(
        op.f("ix_tutor_interactions_session_id"), "tutor_interactions", ["session_id"], unique=False
    )
    op.create_table(
        "verification_runs",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback", sa.String(2000), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(status = 'pending') = (completed_at IS NULL)",
            name=op.f("ck_verification_runs_completion_time"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','passed','failed','error')",
            name=op.f("ck_verification_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "session_id"],
            ["attempts.id", "attempts.session_id"],
            name=op.f("fk_verification_runs_attempt_id_attempts"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.id"],
            name=op.f("fk_verification_runs_session_id_learning_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_runs")),
        sa.UniqueConstraint(
            "attempt_id",
            "idempotency_key",
            name=op.f("uq_verification_runs_attempt_id_idempotency_key"),
        ),
    )
    op.create_index(
        op.f("ix_verification_runs_attempt_id"), "verification_runs", ["attempt_id"], unique=False
    )
    op.create_index(
        op.f("ix_verification_runs_session_id"), "verification_runs", ["session_id"], unique=False
    )
    op.create_table(
        "runtime_notes",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.String(2000), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["verification_runs.id"],
            name=op.f("fk_runtime_notes_run_id_verification_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runtime_notes")),
        sa.UniqueConstraint("run_id", name=op.f("uq_runtime_notes_run_id")),
    )
    op.create_table(
        "runtime_tasks",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "priority IN ('low','normal','high')", name=op.f("ck_runtime_tasks_priority")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["verification_runs.id"],
            name=op.f("fk_runtime_tasks_run_id_verification_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runtime_tasks")),
        sa.UniqueConstraint("run_id", name=op.f("uq_runtime_tasks_run_id")),
    )
    op.create_table(
        "verification_checks",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("matched", sa.Boolean(), nullable=False),
        sa.Column("expected", sa.String(4000), nullable=False),
        sa.Column("observed", sa.String(8000), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["verification_runs.id"],
            name=op.f("fk_verification_checks_run_id_verification_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_checks")),
        sa.UniqueConstraint("run_id", "code", name=op.f("uq_verification_checks_run_id_code")),
    )
    op.create_index(
        op.f("ix_verification_checks_run_id"), "verification_checks", ["run_id"], unique=False
    )
    op.execute("INSERT INTO write_gate(id) VALUES(1)")
    quoted_schema = connection.dialect.identifier_preparer.quote(schema)
    for name, event, table, condition, message in GUARDS:
        body = f"IF {condition} THEN " if condition else ""
        body += f"RAISE EXCEPTION '{message}' USING ERRCODE='23514'; "
        if condition:
            body += "END IF; "
        body += "RETURN OLD;" if event == "BEFORE DELETE" else "RETURN NEW;"
        op.execute(
            f"CREATE FUNCTION guard_{name}() RETURNS trigger LANGUAGE plpgsql "
            f"SET search_path={quoted_schema},pg_catalog AS $guard$ BEGIN {body} END; $guard$"
        )
        op.execute(
            f"CREATE TRIGGER {name} {event} ON {table} FOR EACH ROW EXECUTE FUNCTION guard_{name}()"
        )


def downgrade() -> None:
    raise RuntimeError("PostgreSQL baseline is a preservation floor; downgrade refused")
