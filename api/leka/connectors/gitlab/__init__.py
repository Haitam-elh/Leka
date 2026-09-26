"""GitLab (gitlab.com or self-managed), read-only, with an access token.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.gitlab.connector import GitLabConfig, GitLabConnector, GitLabCredentials

__all__ = ["GitLabConfig", "GitLabConnector", "GitLabCredentials"]
