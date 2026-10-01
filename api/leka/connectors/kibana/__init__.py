"""Kibana, read-only, with an Elastic API key.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.kibana.connector import KibanaConfig, KibanaConnector, KibanaCredentials

__all__ = ["KibanaConfig", "KibanaConnector", "KibanaCredentials"]
