"""GitHub, read-only, with a fine-grained personal access token.

Importing this package registers the connector (leka/connectors/__init__.py
does, once). See docs/connectors/adding-a-connector.md, which walks through
this file as the example.
"""

from leka.connectors.github.connector import GitHubConfig, GitHubConnector, GitHubCredentials

__all__ = ["GitHubConfig", "GitHubConnector", "GitHubCredentials"]
