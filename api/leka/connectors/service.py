"""Business logic for connected sources.

Holds what is true of every source regardless of vendor: when a sync is due,
what a failure means for its status, how credentials are resolved through
leka.platform's secret store.

Vendor specifics live in the subpackage for that vendor (connectors/github/,
connectors/jira/, …), behind the same interface.
"""

from __future__ import annotations

from leka.connectors.repository import SourceRepository


class SourceService:
    """Orchestrates sources without knowing any vendor's API."""

    def __init__(self, repository: SourceRepository) -> None:
        self._repository = repository
