from typing import Protocol

from app.domain.health import DependencyState


class ReadinessProbe(Protocol):
    def check(self) -> DependencyState: ...
