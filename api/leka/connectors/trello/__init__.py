"""Trello (trello.com), read-only, with an API key and a read token.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.trello.connector import TrelloConfig, TrelloConnector, TrelloCredentials

__all__ = ["TrelloConfig", "TrelloConnector", "TrelloCredentials"]
