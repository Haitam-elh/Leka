"""PagerDuty, read-only, with a read-only REST API key.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.pagerduty.connector import (
    PagerDutyConfig,
    PagerDutyConnector,
    PagerDutyCredentials,
)

__all__ = ["PagerDutyConfig", "PagerDutyConnector", "PagerDutyCredentials"]
