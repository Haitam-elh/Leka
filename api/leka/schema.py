"""Every table LEKA declares, registered in one import.

A table's foreign keys name other tables by string ("users.id"), and
SQLAlchemy resolves them only against the tables it has been shown. A
process that imports one module — a worker running `leka.connectors.health`
— sees `sources.created_by -> users.id` and no `users`, and every query on
sources fails with NoReferencedTableError. The API never hit this: it
imports every module to mount their routes. alembic/env.py never did: it
imports them all by hand. The worker imported only the job, and the
source-health sweep crashed on every source, every fifteen minutes, from
LEKA-344 until this file.

A file at the top of the package, like leka/main.py, and for the same
reason: it depends on every module, so it belongs to none of the layers
(tests/test_module_boundaries.py). Each module is imported through its
__init__.py, never through its models.

A module that declares a table is added here — test_schema_registry.py
fails until it is.
"""

from __future__ import annotations

import leka.background
import leka.capabilities
import leka.connectors
import leka.context
import leka.governance
import leka.identity
import leka.ingestion
import leka.intelligence
import leka.intentions
import leka.knowledge
import leka.metering
import leka.platform  # noqa: F401
from leka.db import Base

__all__ = ["Base"]
