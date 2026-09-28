"""Monday (monday.com), read-only, with a personal API token.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.monday.connector import MondayConfig, MondayConnector, MondayCredentials

__all__ = ["MondayConfig", "MondayConnector", "MondayCredentials"]
