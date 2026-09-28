"""Google Workspace — Drive, Docs, Sheets, Slides — read-only, by a service account.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.google_workspace.connector import (
    GoogleWorkspaceConfig,
    GoogleWorkspaceConnector,
    GoogleWorkspaceCredentials,
)

__all__ = ["GoogleWorkspaceConfig", "GoogleWorkspaceConnector", "GoogleWorkspaceCredentials"]
