"""Grafana, read-only, with a Viewer service account's token.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.grafana.connector import GrafanaConfig, GrafanaConnector, GrafanaCredentials

__all__ = ["GrafanaConfig", "GrafanaConnector", "GrafanaCredentials"]
