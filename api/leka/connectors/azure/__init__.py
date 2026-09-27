"""Microsoft Azure, read-only, with a service principal holding the Reader role.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.azure.connector import AzureConfig, AzureConnector, AzureCredentials

__all__ = ["AzureConfig", "AzureConnector", "AzureCredentials"]
