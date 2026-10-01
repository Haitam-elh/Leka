"""Splunk, read-only, with an authentication token.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.splunk.connector import SplunkConfig, SplunkConnector, SplunkCredentials

__all__ = ["SplunkConfig", "SplunkConnector", "SplunkCredentials"]
