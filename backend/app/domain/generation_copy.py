"""Reviewed copy destinations for the two current families, not runtime blueprints.

The local IDs match the public Phase 1.1 reference examples. Extending a template's
copy destinations requires an explicit policy change, not an AI-generated ID.
Variants and wording keys are authorized by each server-built generation brief.
"""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class TemplateCopySlots:
    objectives: frozenset[str]
    misconceptions: frozenset[str]


TEMPLATE_COPY_SLOTS = MappingProxyType(
    {
        "notes-v1": TemplateCopySlots(
            objectives=frozenset({"trace-contract"}),
            misconceptions=frozenset({"presence-implies-validity"}),
        ),
        "tasks-nested-v1": TemplateCopySlots(
            objectives=frozenset({"trace-nesting"}),
            misconceptions=frozenset({"presence-implies-validity"}),
        ),
    }
)

# Implicit required slots in every contract-version 1.0.0 request. Phase 2.1 does
# not support selecting a subset of these, or adding a generated family field.
PREDICTION_SLOTS = frozenset({"rejected", "saved", "server_error"})
HINT_SLOTS = frozenset({"orient", "compare", "investigate_evidence"})
EXPLANATION_SLOTS = frozenset({"concept", "evidence"})
