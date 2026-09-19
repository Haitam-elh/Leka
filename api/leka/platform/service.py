"""Platform primitives: tenancy, events, task queues, secrets, object storage.

The things every other module needs and none of them should implement twice.

Secrets in particular: a source's credentials are encrypted by
leka.platform.secret_box before they reach the database, and the key lives in
the environment. Nothing readable is written to the database we back up, and
no key is ever written to Git (rule 12). See
docs/adr/005-credential-storage.md.
"""

from __future__ import annotations

from leka.platform.repository import WorkspaceRepository


class WorkspaceService:
    """Creates and manages tenants."""

    def __init__(self, repository: WorkspaceRepository) -> None:
        self._repository = repository
