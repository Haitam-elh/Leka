"""Supabase, read-only: its PostgreSQL's catalogue, through the session
pooler.

Importing this package registers the connector (leka/connectors/__init__.py
does, once).
"""

from leka.connectors.supabase.connector import (
    SupabaseConfig,
    SupabaseConnector,
    SupabaseCredentials,
)

__all__ = ["SupabaseConfig", "SupabaseConnector", "SupabaseCredentials"]
