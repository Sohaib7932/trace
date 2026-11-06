"""Actual future completion owns every queued/running custom-job reservation."""

import logging
from threading import Event, Thread
from unittest.mock import patch
from uuid import uuid4

from app.domain.clock import utc_now
from app.services.custom_lessons import CustomLessonRunner


def runner():
    return CustomLessonRunner(object(), object(), utc_now, logging.getLogger("custom-worker-test"))


def test_cancelling_queued_jobs_releases_counts_only_when_actual_futures_finish():
    worker = runner()
    entered, release = Event(), Event()
    executions = []

    def blocked(request_id):
        executions.append(request_id)
        entered.set()
        assert release.wait(5)

    worker._generate = blocked
    first, queued = uuid4(), uuid4()
    try:
        worker.submit(first)
        assert entered.wait(2)
        worker.submit(queued)
        worker.close(timeout=0)
        assert not worker.wait_for_idle(0)
    finally:
        release.set()
        worker._executor.shutdown(wait=True)
    assert worker.wait_for_idle(0)
    assert executions == [first]
    worker.close(timeout=0)
    worker.submit(uuid4())
    assert worker.wait_for_idle(0) and executions == [first]


def test_shutdown_between_reservation_and_executor_submit_releases_rejected_job():
    worker = runner()
    entered, release = Event(), Event()
    submit = worker._executor.submit

    def racing_submit(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return submit(*args, **kwargs)

    caller = Thread(target=lambda: worker.submit(uuid4()))
    with patch.object(worker._executor, "submit", side_effect=racing_submit):
        try:
            caller.start()
            assert entered.wait(2)
            worker.stop_admission()
            assert not worker.wait_for_idle(0)
        finally:
            release.set()
            caller.join(3)
    assert not caller.is_alive() and worker.wait_for_idle(0)
    worker.close(timeout=0)


def test_failed_worker_is_idle_and_does_not_log_private_exception_text(caplog):
    worker = runner()

    def failed(_):
        raise RuntimeError("private-provider-output-canary")

    worker._generate = failed
    worker.submit(uuid4())
    assert worker.wait_for_idle(2)
    worker.close(timeout=0)
    assert "custom_lesson_job_failed" in caplog.text
    assert "private-provider-output-canary" not in caplog.text
