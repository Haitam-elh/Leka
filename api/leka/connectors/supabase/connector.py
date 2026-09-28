"""The Supabase connector — a Supabase project's database, which is
PostgreSQL (LEKA-349).

The PostgreSQL connector, under Supabase's name and with its defaults: the
database is `postgres`, and the host is the project's **session pooler**
(aws-0-<region>.pooler.supabase.com, port 5432) — the direct host,
db.<project>.supabase.co, has an IPv6 address only, which a server without
IPv6 cannot reach. Through the pooler, the role's name carries the
project's: `leka_reader.<project-ref>`. Everything else — the catalogue
read and never the rows, TLS, the public address, the read-only session —
is leka/connectors/postgresql's, and so are the tests of it.
"""

from __future__ import annotations

from pydantic import Field

from leka.connectors.base import Capability, ConnectorCategory, ConnectorManifest
from leka.connectors.databases import HOST
from leka.connectors.models import SourceKind
from leka.connectors.postgresql.connector import (
    IDENTIFIER_MAX,
    PostgreSQLConfig,
    PostgreSQLConnector,
    PostgreSQLCredentials,
)
from leka.connectors.registry import register_connector


class SupabaseConfig(PostgreSQLConfig):
    host: str = Field(
        min_length=1,
        max_length=253,
        pattern=HOST,
        description="The project's session pooler: aws-0-<region>.pooler.supabase.com.",
    )
    database: str = Field(
        default="postgres",
        min_length=1,
        max_length=IDENTIFIER_MAX,
        description="The database to describe: postgres, a Supabase project's.",
    )


class SupabaseCredentials(PostgreSQLCredentials):
    pass


@register_connector
class SupabaseConnector(PostgreSQLConnector):
    manifest = ConnectorManifest(
        key=SourceKind.SUPABASE,
        display_name="Supabase",
        category=ConnectorCategory.DATA,
        auth_type="token",
        config_schema=SupabaseConfig,
        credentials_schema=SupabaseCredentials,
        capabilities=frozenset({Capability.SCHEMAS, Capability.TABLES}),
        listed_whole=frozenset({Capability.SCHEMAS, Capability.TABLES}),
    )
