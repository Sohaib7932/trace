"""Offline JSON-lines transport to a real isolated FastAPI app, never a network proxy."""

import base64
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, update

from alembic import command
from app.auth.jwt import JwtVerifier
from app.core.settings import Settings
from app.db import models as m
from app.db.migrations import migration_config
from app.db.session import Database
from app.main import create_app
from app.services.identity import credential_digest
from tests.auth_fixtures import KeysFixture, SigningFixture, auth_settings


def main():
    with TemporaryDirectory(prefix="trace-relay-offline-") as scratch:
        settings = auth_settings(Settings(
            _env_file=None,
            environment="test",
            database_url=SecretStr("sqlite+pysqlite:///" + str(Path(scratch) / "test.db")),
            cors_origins=("https://trace-ten-mu.vercel.app",),
            cookie_secure=True,
        ))
        database = Database(settings)
        config = migration_config()
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        signer, other = SigningFixture(), SigningFixture(kid="other")
        app = create_app(settings, database, jwt_verifier=JwtVerifier(settings, KeysFixture(signer, other)))
        try:
            with TestClient(app, base_url="https://trace-backend-1lio.onrender.com") as client:
                print(json.dumps({"ready": True, "tokens": [signer.token(), other.token()]}), flush=True)
                for line in sys.stdin:
                    packet = json.loads(line)
                    if packet.get("action") == "counts":
                        with database.session() as session:
                            result = {"learners": session.scalar(select(func.count()).select_from(m.Learner)),
                                      "credentials": session.scalar(select(func.count()).select_from(m.LearnerCredential))}
                    elif packet.get("action") == "expire_guest":
                        with database.session() as session, session.begin():
                            session.execute(update(m.LearnerCredential).where(
                                m.LearnerCredential.token_hash == credential_digest(packet["cookie"])
                            ).values(expires_at=datetime.now(UTC) + timedelta(seconds=60)))
                        result = {"updated": True}
                    else:
                        # No hidden TestClient cookie jar: only the relay's explicit
                        # allowlisted credentials reach each independent request.
                        client.cookies.clear()
                        response = client.request(packet["method"], packet["path"], headers=packet["headers"],
                                                  content=base64.b64decode(packet.get("body", "")))
                        result = {"status": response.status_code, "body": base64.b64encode(response.content).decode(),
                                  "headers": list(response.headers.multi_items())}
                    print(json.dumps(result), flush=True)
        finally:
            database.dispose()


if __name__ == "__main__":
    main()
