from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyState:
    connected: bool
    schema_current: bool

    @property
    def ready(self) -> bool:
        return self.connected and self.schema_current
