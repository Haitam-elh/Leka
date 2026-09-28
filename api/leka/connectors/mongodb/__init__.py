"""MongoDB, read-only: what it says of its collections, with a role that
may read no document.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.mongodb.connector import (
    MongoDBConfig,
    MongoDBConnector,
    MongoDBCredentials,
)

__all__ = ["MongoDBConfig", "MongoDBConnector", "MongoDBCredentials"]
