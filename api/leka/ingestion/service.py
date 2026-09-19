"""The normalisation pipeline: collect -> extract -> parse -> normalise.

This is where a vendor's vocabulary becomes LEKA's. A GitHub repository, a
Jira component and an AWS tag may all describe the same service; deciding
that they do is this module's hardest problem, and the one that determines
whether an answer is trustworthy.

Depends on leka.connectors. Must not import leka.context or leka.intentions
(architecture rule 1).
"""

from __future__ import annotations

from leka.ingestion.repository import IngestionRunRepository


class IngestionService:
    """Turns raw records into candidate entities and relationships."""

    def __init__(self, repository: IngestionRunRepository) -> None:
        self._repository = repository
