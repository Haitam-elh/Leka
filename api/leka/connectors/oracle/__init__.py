"""Oracle, read-only: a database's catalogue, with an account that may read
no row.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.oracle.connector import OracleConfig, OracleConnector, OracleCredentials

__all__ = ["OracleConfig", "OracleConnector", "OracleCredentials"]
