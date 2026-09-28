"""Guru (getguru.com), read-only, with a collection token or a user's.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.guru.connector import GuruConfig, GuruConnector, GuruCredentials

__all__ = ["GuruConfig", "GuruConnector", "GuruCredentials"]
