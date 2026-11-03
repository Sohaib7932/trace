"""Docker 29's endpoint schema preserves the real untrusted-peer security probe."""

import json
from types import SimpleNamespace

import pytest

from infrastructure_tests import test_production_tls as tls


def response(monkeypatch, networks):
    calls = []

    def inspect(*args):
        calls.append(args)
        # No legacy top-level IPAddress exists in this Docker 29 response.
        if args != ("inspect", "--format", "{{json .NetworkSettings.Networks}}", "fixture"):
            raise RuntimeError("Template parsing error: legacy network address field missing")
        return SimpleNamespace(stdout=json.dumps(networks))

    monkeypatch.setattr(tls, "docker", inspect)
    return calls


def test_docker_29_network_endpoint_without_legacy_address_is_supported(monkeypatch):
    calls = response(monkeypatch, {"bridge": {"IPAddress": "172.17.0.2"}})
    assert tls.container_private_ipv4("fixture") == "172.17.0.2"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "networks",
    [
        {},
        {"bridge": {"IPAddress": "172.17.0.2"}, "other": {"IPAddress": "172.18.0.2"}},
        {"bridge": {"IPAddress": "127.0.0.1"}},
        {"bridge": {"IPAddress": "8.8.8.8"}},
        {"bridge": {"IPAddress": "::1"}},
        {"bridge": {"IPAddress": ""}},
        {"bridge": {}},
        {"bridge": "untrusted-endpoint"},
    ],
)
def test_invalid_topology_cannot_turn_untrusted_peer_probe_into_a_trusted_one(
    monkeypatch, networks
):
    response(monkeypatch, networks)
    with pytest.raises((AssertionError, ValueError, KeyError)):
        tls.container_private_ipv4("fixture")
