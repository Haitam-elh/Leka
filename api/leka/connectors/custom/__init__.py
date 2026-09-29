"""Systems LEKA has no connector for, read as their admin declared them
(LEKA-350): a generic REST source and a generic GraphQL source, read; a
generic webhook, sent to; their definitions, their mapping.

Importing this package registers the connectors (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.custom.common import CustomCredentials
from leka.connectors.custom.graphql_api import CustomGraphQLConfig, CustomGraphQLConnector
from leka.connectors.custom.rest import CustomRestConfig, CustomRestConnector
from leka.connectors.custom.webhook import (
    CustomWebhookConfig,
    CustomWebhookConnector,
    WebhookCredentials,
)

__all__ = [
    "CustomCredentials",
    "CustomGraphQLConfig",
    "CustomGraphQLConnector",
    "CustomRestConfig",
    "CustomRestConnector",
    "CustomWebhookConfig",
    "CustomWebhookConnector",
    "WebhookCredentials",
]
