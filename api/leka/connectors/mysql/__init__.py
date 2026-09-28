"""MySQL, read-only: its catalogue, with an account that may read no row.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.mysql.connector import MySQLConfig, MySQLConnector, MySQLCredentials

__all__ = ["MySQLConfig", "MySQLConnector", "MySQLCredentials"]
