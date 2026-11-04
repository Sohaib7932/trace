"""Loopback browser fixture for custom lessons. Mock transport only: no key, no live provider.

Markers in the learner's topic choose a scripted outcome so every tracker state can be
exercised: [fixture:declined], [fixture:invalid], [fixture:slow]. Anything else returns a
valid lesson in the requested language after a short delay.
"""

import argparse
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from pydantic import SecretStr

from alembic import command
from app.core.ai_settings import AIClientSettings
from app.core.custom_lesson_settings import CustomLessonSettings
from app.core.settings import Settings
from app.db.learning import SqlLearningRepository
from app.db.migrations import migration_config
from app.db.session import Database
from app.main import create_app
from app.schemas.ai_client import TransportCompletion
from app.services.catalog import seed_first_lesson, seed_transfer_lesson
from scripts import auth_fixture

API_PORT, AUTH_PORT, FRONT = 8110, 8111, "http://127.0.0.1:3300"
AUTH = f"http://127.0.0.1:{AUTH_PORT}"


def lesson(language: str, number: int) -> str:
    python = language.strip().lower() == "python"
    code = (
        "from pydantic import BaseModel\n\nclass Note(BaseModel):\n    title: str\n"
        if python
        else "function total(items) {\n  let sum = 0;\n"
        "  for (const item of items) sum += item;\n  return sum;\n}"
    )
    return json.dumps(
        {
            "status": "lesson",
            "decline_reason": "none",
            "language": language,
            "title": f"Reading code carefully, part {number}",
            "objective": "Predict what this code does before you run it in your head.",
            "sections": [
                {
                    "heading": "What the code receives",
                    "body": "Every function or model expects data in a certain shape.",
                },
                {
                    "heading": "Why prediction helps",
                    "body": "Saying what you expect first makes the real result easier "
                    "to understand.",
                },
            ],
            "challenges": [
                {
                    "kind": "multiple_choice",
                    "prompt": "Which statement about this code is true?",
                    "code": code,
                    "options": [
                        "It always fails",
                        "It describes the expected shape",
                        "It sends an email",
                    ],
                    "correct_option": 1,
                    "model_answer": "",
                    "hints": [
                        "Read the first line.",
                        "Look at what is declared.",
                        "Think about inputs.",
                    ],
                    "explanation": "The code declares what data it expects; "
                    "it does not send anything.",
                    "verification_mode": "answer_key",
                },
                {
                    "kind": "predict_output",
                    "prompt": "What does the code produce for an empty input?",
                    "code": code,
                    "options": ["An error", "Nothing useful", "A zero or empty result"],
                    "correct_option": 2,
                    "model_answer": "",
                    "hints": [
                        "Start from the initial value.",
                        "No loop iterations run.",
                        "What is returned?",
                    ],
                    "explanation": "With no items the starting value is returned unchanged.",
                    "verification_mode": "answer_key",
                },
                {
                    "kind": "explain",
                    "prompt": "Explain in one or two sentences what this code is for.",
                    "code": "",
                    "options": [],
                    "correct_option": -1,
                    "model_answer": "It describes or computes a value from the data it is given.",
                    "hints": ["Who would call it?", "What goes in?", "What comes out?"],
                    "explanation": "Naming the purpose helps you reason about every later change.",
                    "verification_mode": "practice_only",
                },
            ],
        }
    )


class LessonFixtureTransport:
    source = "test_fixture"

    def complete(self, request):
        data = json.loads(request.data_json)
        untrusted = data.get("untrusted_request", {})
        topic = str(untrusted.get("topic", ""))
        if "[fixture:slow]" in topic:
            time.sleep(4)
        else:
            time.sleep(1.2)
        if "[fixture:declined]" in topic:
            text = json.dumps(
                {
                    "status": "declined",
                    "decline_reason": "off_topic",
                    "language": "",
                    "title": "",
                    "objective": "",
                    "sections": [],
                    "challenges": [],
                }
            )
        elif "[fixture:invalid]" in topic:
            text = '{"status": "lesson"}'
        else:
            text = lesson(
                str(untrusted.get("language", "Python")), int(data.get("lesson_number", 1))
            )
        return TransportCompletion(text=text, input_tokens=100, output_tokens=300, cost_microusd=0)

    def close(self):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("auth", "backend"))
    option = parser.parse_args()
    if option.service == "auth":
        auth_fixture.URL, auth_fixture.ORIGIN = AUTH, FRONT
        uvicorn.run(
            auth_fixture.create_fixture(),
            host="127.0.0.1",
            port=AUTH_PORT,
            access_log=False,
            log_level="warning",
        )
        return
    with TemporaryDirectory(prefix="trace-custom-lessons-") as directory:
        settings = Settings(
            _env_file=None,
            environment="test",
            log_level="WARNING",
            database_url=SecretStr(
                "sqlite+pysqlite:///" + (Path(directory) / "learning.db").as_posix()
            ),
            cookie_secure=False,
            allow_insecure_local_cookies=True,
            cors_origins=(FRONT,),
            supabase_url=AUTH,
            supabase_issuer=AUTH + "/auth/v1",
            supabase_jwks_url=AUTH + "/auth/v1/.well-known/jwks.json",
            auth_allow_insecure_loopback=True,
        )
        database = Database(settings)
        try:
            migration = migration_config()
            with database.engine.begin() as connection:
                migration.attributes["connection"] = connection
                command.upgrade(migration, "head")
            repository = SqlLearningRepository(database)
            seed_first_lesson(repository)
            seed_transfer_lesson(repository)
            transport = LessonFixtureTransport()
            app = create_app(
                settings,
                database,
                ai_settings=AIClientSettings(
                    _env_file=None, mode="mock", max_live_requests_per_process=100
                ),
                ai_transport_factory=lambda: transport,
                custom_lesson_settings=CustomLessonSettings(
                    requests_per_minute=30, daily_requests_per_account=100
                ),
            )
            uvicorn.run(app, host="127.0.0.1", port=API_PORT, access_log=False, log_level="warning")
        finally:
            database.dispose()


if __name__ == "__main__":
    main()
