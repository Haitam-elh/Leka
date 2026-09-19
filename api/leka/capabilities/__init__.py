"""Capabilities: the model gateway and the agent loader.

Two responsibilities, one module because they are the same boundary: this is
where LEKA talks to a language model, and where the instructions it sends are
loaded from.

The agents themselves live in agents/, as content (architecture rule 8).
"""

from leka.capabilities.loader import (
    AgentLoadError,
    AgentRegistry,
    discover,
    load_all,
    parse_agent,
)
from leka.capabilities.repository import CapabilityRunRepository
from leka.capabilities.schemas import Agent, AgentFrontMatter, AgentMode, AgentRisk
from leka.capabilities.service import CapabilityService

__all__ = [
    "Agent",
    "AgentFrontMatter",
    "AgentLoadError",
    "AgentMode",
    "AgentRegistry",
    "AgentRisk",
    "CapabilityRunRepository",
    "CapabilityService",
    "discover",
    "load_all",
    "parse_agent",
]
