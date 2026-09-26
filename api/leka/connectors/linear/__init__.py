"""Linear (linear.app), read-only, with a personal API key.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.linear.connector import LinearConfig, LinearConnector, LinearCredentials

__all__ = ["LinearConfig", "LinearConnector", "LinearCredentials"]
