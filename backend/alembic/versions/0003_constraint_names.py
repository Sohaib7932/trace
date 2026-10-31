"""Normalize legacy composite unique names without dropping learner records.

The initial local Module 2 draft inherited a first-column-only naming convention.
Fresh installations already have canonical names in 0002. This forward migration
also preserves any data created with that unreleased draft; it never resets a DB.
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_constraint_names"
down_revision = "0002_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    plans: list[sa.Table] = []
    for name in (
        "learner_credentials",
        "lesson_versions",
        "learning_sessions",
        "attempts",
        "predictions",
        "tutor_interactions",
        "verification_runs",
        "runtime_notes",
        "verification_checks",
    ):
        table = sa.Table(name, sa.MetaData(), autoload_with=connection)
        changed = False
        for constraint in table.constraints:
            if isinstance(constraint, sa.UniqueConstraint):
                canonical = (
                    "uq_" + name + "_" + "_".join(column.name for column in constraint.columns)
                )
                if constraint.name != canonical:
                    constraint.name = canonical
                    changed = True
        if changed:
            plans.append(table)
    if not plans:
        return
    # Triggers can refer to other rebuilt tables; restore the complete set afterwards.
    triggers = connection.execute(
        sa.text("SELECT name, sql FROM sqlite_master WHERE type='trigger'")
    ).all()
    for name, _ in triggers:
        connection.exec_driver_sql('DROP TRIGGER "' + name.replace('"', '""') + '"')
    connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
    for table in plans:
        with op.batch_alter_table(table.name, copy_from=table, recreate="always"):
            pass
    for _, sql in triggers:
        connection.exec_driver_sql(sql)
    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    if violations:
        raise RuntimeError("Constraint-name migration failed its foreign-key integrity check")
    # Recreated rows resolve every FK, but SQLite retains the DROP's deferred
    # violation counter. After the explicit full integrity check, end deferral;
    # foreign_keys stays ON and subsequent statements are checked immediately.
    connection.exec_driver_sql("PRAGMA defer_foreign_keys=OFF")


def downgrade() -> None:
    # Canonical names are also the declared 0002 schema; keep data/constraints intact.
    pass
