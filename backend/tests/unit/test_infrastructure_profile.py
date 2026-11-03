"""Infrastructure test overrides cannot substitute arbitrary container images."""

import pytest

from infrastructure_tests.test_production_tls import postgres_image


@pytest.mark.parametrize(
    "image",
    [
        "",
        "postgres:17-alpine",
        "attacker.invalid/postgres@sha256:" + "a" * 64,
        "docker.io/other/postgres@sha256:" + "a" * 64,
        "docker.io/library/postgres@sha256:" + "a" * 63,
        "docker.io/library/postgres@sha256:" + "A" * 64,
    ],
)
def test_operator_image_override_requires_exact_pinned_official_repository(image, monkeypatch):
    monkeypatch.setenv("TRACE_TEST_POSTGRES_IMAGE", image)
    with pytest.raises(ValueError, match="pin the official image digest"):
        postgres_image()


def test_operator_can_select_verified_official_digest_without_changing_default(monkeypatch):
    monkeypatch.delenv("TRACE_TEST_POSTGRES_IMAGE", raising=False)
    assert postgres_image() == "postgres:15-alpine"
    image = "docker.io/library/postgres@sha256:" + "a" * 64
    monkeypatch.setenv("TRACE_TEST_POSTGRES_IMAGE", image)
    assert postgres_image() == image
