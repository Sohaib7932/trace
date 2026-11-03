"""Internal aggregate diagnostics; never prompts, subjects, provider messages or keys.

This is an in-process snapshot, not a public health endpoint, billing measurement
or distributed quota. No probe sends a provider request. Gemini async I/O has a
cancelable deadline; CPU stalls and arbitrary Python threads are not killable.
"""

from dataclasses import dataclass
from typing import Literal

from app.schemas.ai_client import Capability


@dataclass(frozen=True)
class ProviderOutcome:
    capability: Capability
    outcome: str
    count: int


@dataclass(frozen=True)
class ProviderDiagnostics:
    version: Literal["provider-diagnostics-v1"]
    mode: Literal["disabled", "mock", "gemini_free"]
    availability: Literal["disabled", "configured", "unconfigured", "closed"]
    capability_profile: str | None
    capabilities: tuple[Capability, ...]
    in_flight: int
    max_in_flight: int
    attempts: int
    outcomes: tuple[ProviderOutcome, ...]
    network_deadline_enforced: bool = False
    cleanup_failed: bool = False
    # Configuration validation and observed results do not imply live readiness.
    live_availability_verified: Literal[False] = False
    absolute_deadline_enforced: Literal[False] = False
