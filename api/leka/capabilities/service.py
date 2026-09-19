"""The model gateway, and the only place a language model is called.

Architecture rule 7 exists so that prompting, retries, cost, rate limits and
redaction live in one file instead of being reinvented in nine. If a second
module ever calls a model, this rule has failed and the review missed it.

Nothing here is implemented: calling a model is out of scope for LEKA-329.
"""

from __future__ import annotations

from leka.capabilities.loader import AgentRegistry
from leka.capabilities.repository import CapabilityRunRepository


class CapabilityService:
    """Runs an agent against an assembled context."""

    def __init__(
        self,
        registry: AgentRegistry,
        repository: CapabilityRunRepository,
    ) -> None:
        self._registry = registry
        self._repository = repository
