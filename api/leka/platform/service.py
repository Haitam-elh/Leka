"""Platform primitives: tenancy, events, task queues, secrets, object storage.

The things every other module needs and none of them should implement twice.

Secrets in particular: a source's credentials are held by a secret store and
referenced from `sources.credentials_ref`. No credential is ever written to
the database we back up, and none is ever written to Git (rule 12).
"""

from __future__ import annotations

from leka.platform.repository import WorkspaceRepository


class WorkspaceService:
    """Creates and manages tenants."""

    def __init__(self, repository: WorkspaceRepository) -> None:
        self._repository = repository
