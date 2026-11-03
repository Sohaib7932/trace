"""Provider-neutral private instructional-content port."""

from typing import Literal, Protocol

from app.schemas.private_guides import GuideContent, GuideCreate


class GuideGenerator(Protocol):
    def generate(
        self, request: GuideCreate, *, subject: str, timeout_seconds: float
    ) -> tuple[GuideContent, Literal["ai", "test_fixture"]] | None: ...
