"""Jira Cloud, read-only, with an Atlassian account's API token.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.jira.connector import JiraConfig, JiraConnector, JiraCredentials

__all__ = ["JiraConfig", "JiraConnector", "JiraCredentials"]
