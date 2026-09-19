"""Retrieval, ranking, assembly.

Turns a question into the smallest set of facts that can answer it. The
hard part is not finding relevant things, it is stopping: a context window
is finite, and evidence that does not fit has to be dropped deliberately
rather than truncated by accident. Hence AssembledContext.truncated.

Depends on leka.knowledge. Must not import leka.intentions (rule 1).
"""

from __future__ import annotations

from leka.context.repository import ContextRepository


class ContextService:
    """Assembles what an answer needs from state already prepared."""

    def __init__(self, repository: ContextRepository) -> None:
        self._repository = repository
