"""SQL Server, read-only: a database's catalogue, with an account that may
read no row.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.sqlserver.connector import (
    SQLServerConfig,
    SQLServerConnector,
    SQLServerCredentials,
)

__all__ = ["SQLServerConfig", "SQLServerConnector", "SQLServerCredentials"]
