"""Test-only catalog control on the existing disposable Playwright bootstrap.

Never imported by production. No developer database, environment file or live
identity provider is used: scripts.e2e_server owns the temporary database.
"""

from dataclasses import replace
from datetime import timedelta
from itertools import count
from unittest.mock import patch
from uuid import uuid4

from app.api.presentation import present_lesson
from app.db.learning import SqlLearningRepository
from app.main import create_app
from app.services.catalog import LESSON_ID, lesson_hash
from scripts import e2e_server


def create_fixture_app(settings, database, clock):
    assert settings.environment == "test"
    assert settings.supabase_url == "http://127.0.0.1:8001"
    app = create_app(settings, database, clock)
    repository = SqlLearningRepository(database)
    revisions = count(1)

    @app.post("/__fixture__/catalog/advance")
    def advance_catalog():
        with repository.write() as store:
            previous = store.version(LESSON_ID)
            assert previous is not None
            revision = next(revisions)
            content = {**previous.public_content, "title": f"Future catalog revision {revision}"}
            version = replace(
                previous,
                id=uuid4(),
                version=f"1.1.{revision}",
                public_content=content,
                content_hash=lesson_hash(
                    content, previous.expected_field, previous.prediction_answer
                ),
                created_at=previous.created_at + timedelta(seconds=1),
            )
            store.publish(version)
        return present_lesson(version)

    return app


def main():
    with patch.object(e2e_server, "create_app", create_fixture_app):
        e2e_server.main()


if __name__ == "__main__":
    main()
