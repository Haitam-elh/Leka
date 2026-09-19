"""The lifecycle: intention -> decision -> action.

The gate every action passes through. An agent in proposes_action mode
proposes; it never executes. Execution happens here, and only after an
approval that carries a user and a timestamp.

That is not a policy this module implements on behalf of someone else — it
is the reason this module exists.

Depends on leka.context and leka.capabilities.
"""

from __future__ import annotations

from leka.intentions.repository import IntentionRepository


class IntentionService:
    """Carries an intention from proposal to execution, or to rejection."""

    def __init__(self, repository: IntentionRepository) -> None:
        self._repository = repository
