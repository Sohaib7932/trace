"""Temporary Unix initialization readiness is insufficient for TCP/TLS tests."""

from types import SimpleNamespace

import pytest

from infrastructure_tests import test_production_tls as tls


def test_socket_only_initialization_must_wait_for_final_tcp_server(monkeypatch):
    now, observations = [0.0], []

    def probe(*args, check, timeout):
        assert check is False and 0 < timeout <= 40
        tcp = "-h" in args and args[args.index("-h") + 1] == "127.0.0.1"
        # The temporary server would already report ready over a Unix socket.
        ready = not tcp or now[0] > 0
        observations.append((tcp, ready))
        return SimpleNamespace(returncode=0 if ready else 1)

    def advance(seconds):
        now[0] += seconds

    monkeypatch.setattr(tls, "docker", probe)
    monkeypatch.setattr(tls.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(tls.time, "sleep", advance)
    tls.wait_for_postgres_tcp("fixture")
    assert observations == [(True, False), (True, True)]


@pytest.mark.parametrize("reported_ready", [False, True])
def test_failure_or_late_readiness_cannot_cross_the_original_startup_bound(
    monkeypatch, reported_ready
):
    now, calls = [0.0], []

    def probe(*args, check, timeout):
        assert check is False and timeout == 40
        calls.append(args)
        now[0] = 41
        return SimpleNamespace(returncode=0 if reported_ready else 1)

    monkeypatch.setattr(tls, "docker", probe)
    monkeypatch.setattr(tls.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        tls.time, "sleep", lambda _: pytest.fail("Expired startup must not sleep or retry")
    )
    with pytest.raises(RuntimeError, match="PostgreSQL TLS did not become ready"):
        tls.wait_for_postgres_tcp("fixture")
    assert len(calls) == 1
