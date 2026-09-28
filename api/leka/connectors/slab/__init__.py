"""Slab (slab.com), read-only, with the workspace's API token.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.slab.connector import SlabConfig, SlabConnector, SlabCredentials

__all__ = ["SlabConfig", "SlabConnector", "SlabCredentials"]
