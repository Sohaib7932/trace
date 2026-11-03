"""The same two-app admission contract on an actual disposable PostgreSQL schema."""

from tests.integration.test_shared_admission_http import exercise_two_apps


def test_two_http_apps_share_postgresql_admission(database, settings):
    exercise_two_apps(database, settings)
