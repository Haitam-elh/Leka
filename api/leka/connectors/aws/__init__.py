"""AWS, read-only, with an IAM access key — and a role to assume, preferably.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.aws.connector import AwsConfig, AwsConnector, AwsCredentials

__all__ = ["AwsConfig", "AwsConnector", "AwsCredentials"]
