"""Two separate HTTP application instances share the actual SQL admission gate."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai.accounting import AdmissionPolicy
from app.core.errors import ApplicationError
from app.core.feedback_settings import FeedbackSettings
from app.db import accounting_models as m
from app.db.accounting import SqlAIControls
from app.db.session import Database
from app.services.feedback_operations import FeedbackOperations


def exercise_two_apps(database, settings):
    other_database = Database(settings)
    scope = "cross-app-" + uuid4().hex
    policy = AdmissionPolicy(
        scope=scope,
        global_requests_per_minute=30,
        subject_requests_per_minute=10,
        max_global_in_flight=1,
        max_subject_in_flight=1,
    )
    limits = FeedbackSettings(_env_file=None)
    first = FeedbackOperations(
        limits, shared_admission=SqlAIControls(database), admission_policy=policy
    )
    second = FeedbackOperations(
        limits, shared_admission=SqlAIControls(other_database), admission_policy=policy
    )
    entered, release = Event(), Event()
    owner, other_owner = uuid4(), uuid4()  # Trusted fixture principals, never request parameters.
    second_work = []

    def blocked():
        entered.set()
        assert release.wait(5)
        return "first-completed"

    def make_app(operations, principal_id, work):
        app = FastAPI()

        @app.get("/fixture")
        async def request():
            try:
                value = await operations.execute_account(principal_id, work)
                return JSONResponse({"value": value})
            except ApplicationError as error:
                return JSONResponse({"status": "safely_rejected"}, status_code=error.status_code)

        return app

    app1 = make_app(first, owner, blocked)
    app2 = make_app(second, other_owner, lambda: second_work.append(True) or "second-completed")
    try:
        with TestClient(app1) as client1, TestClient(app2) as client2:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(client1.get, "/fixture")
                assert entered.wait(5)
                denied = client2.get("/fixture")
                assert denied.status_code == 429 and not second_work
                release.set()
                assert pending.result(5).status_code == 200
            accepted = client2.get("/fixture")
            assert accepted.status_code == 200 and second_work == [True]
        with database.session() as session:
            leases = session.scalars(
                select(m.AIAdmissionLease).where(m.AIAdmissionLease.scope == scope)
            ).all()
            assert len(leases) == 2
            assert all(
                str(owner) not in lease.subject_hash and str(other_owner) not in lease.subject_hash
                for lease in leases
            )
            assert session.scalar(select(func.count()).select_from(m.AIAdmissionRelease)) == 2
    finally:
        release.set()
        first.close()
        second.close()
        other_database.dispose()


def test_two_http_apps_share_sqlite_admission(database, settings):
    exercise_two_apps(database, settings)
