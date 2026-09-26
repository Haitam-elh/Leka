"""Confluence Cloud, read-only, with an Atlassian account's API token.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.confluence.connector import (
    ConfluenceConfig,
    ConfluenceConnector,
    ConfluenceCredentials,
)

__all__ = ["ConfluenceConfig", "ConfluenceConnector", "ConfluenceCredentials"]
