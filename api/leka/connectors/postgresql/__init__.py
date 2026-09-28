"""PostgreSQL, read-only: its catalogue, with a role that needs no SELECT.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.postgresql.connector import (
    PostgreSQLConfig,
    PostgreSQLConnector,
    PostgreSQLCredentials,
)

__all__ = ["PostgreSQLConfig", "PostgreSQLConnector", "PostgreSQLCredentials"]
