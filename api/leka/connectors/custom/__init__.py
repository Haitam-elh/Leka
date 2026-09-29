"""Systems LEKA has no connector for, read as their admin declared them
(LEKA-350): a generic REST source, its definition, its mapping.

Importing this package registers the connectors (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.custom.rest import CustomCredentials, CustomRestConfig, CustomRestConnector

__all__ = ["CustomCredentials", "CustomRestConfig", "CustomRestConnector"]
