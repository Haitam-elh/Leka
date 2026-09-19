"""Platform primitives: tenancy, events, task queues, secrets, object storage.

Depended on by every other module. Depends on leka.core and leka.db only.
"""

from leka.platform.models import Workspace

__all__ = ["Workspace"]
