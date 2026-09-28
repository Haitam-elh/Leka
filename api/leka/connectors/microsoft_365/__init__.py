"""Microsoft 365 — SharePoint, OneDrive, Word, Excel, PowerPoint — read-only,
through Microsoft Graph with an application's client secret.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.microsoft_365.connector import (
    Microsoft365Config,
    Microsoft365Connector,
    Microsoft365Credentials,
)

__all__ = ["Microsoft365Config", "Microsoft365Connector", "Microsoft365Credentials"]
