from app.repositories.health import ReadinessProbe


class HealthService:
    def __init__(self, probe: ReadinessProbe) -> None:
        self.probe = probe

    def is_ready(self) -> bool:
        return self.probe.check().ready
