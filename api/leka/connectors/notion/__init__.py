"""Notion (notion.so), read-only, with an internal integration's secret.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.notion.connector import NotionConfig, NotionConnector, NotionCredentials

__all__ = ["NotionConfig", "NotionConnector", "NotionCredentials"]
