import pytest

from app.domain.health import DependencyState
from app.services.health import HealthService


@pytest.mark.parametrize(
    "connected,current,expected",
    [
        (True, True, True),
        (True, False, False),
        (False, True, False),
        (False, False, False),
    ],
)
def test_readiness_requires_connectivity_and_migration_head(
    connected: bool, current: bool, expected: bool
) -> None:
    class Probe:
        def check(self) -> DependencyState:
            return DependencyState(connected, current)

    assert HealthService(Probe()).is_ready() is expected
