"""Datadog, read-only, with an API key and a read-only application key.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.datadog.connector import DatadogConfig, DatadogConnector, DatadogCredentials

__all__ = ["DatadogConfig", "DatadogConnector", "DatadogCredentials"]
