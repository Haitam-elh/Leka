"""Google Cloud, read-only, with a service account holding Cloud Asset Viewer.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.gcp.connector import GcpConfig, GcpConnector, GcpCredentials

__all__ = ["GcpConfig", "GcpConnector", "GcpCredentials"]
