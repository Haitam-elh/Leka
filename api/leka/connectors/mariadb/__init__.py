"""MariaDB, read-only: its catalogue, with an account that may read no row.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.mariadb.connector import (
    MariaDBConfig,
    MariaDBConnector,
    MariaDBCredentials,
)

__all__ = ["MariaDBConfig", "MariaDBConnector", "MariaDBCredentials"]
