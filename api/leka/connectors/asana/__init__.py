"""Asana (app.asana.com), read-only, with a personal access token.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.asana.connector import AsanaConfig, AsanaConnector, AsanaCredentials

__all__ = ["AsanaConfig", "AsanaConnector", "AsanaCredentials"]
