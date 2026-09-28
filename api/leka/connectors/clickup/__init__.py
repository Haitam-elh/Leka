"""ClickUp (clickup.com), read-only, with a personal token.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.clickup.connector import ClickUpConfig, ClickUpConnector, ClickUpCredentials

__all__ = ["ClickUpConfig", "ClickUpConnector", "ClickUpCredentials"]
