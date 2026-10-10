"""Where secrets are kept, and what the API gives back (LEKA-405), checked
on the code itself — so that the next table, or the next route, is checked
the day it is written.

What these protect:
- No column keeps a secret in the clear: one named like a secret is a hash,
  a ciphertext, a count or a date; every binary column is a ciphertext, or
  listed here with why.
- No response carries a field named like a secret but those listed here,
  each with why — a secret shown once, a CSRF token, a hint.
- Production refuses a database URL that turns TLS off, and Amazon S3 told
  to write unencrypted; S3 is asked to encrypt by default.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, LargeBinary

import leka.main  # noqa: F401 — every model registered
from leka.core.config import Settings
from leka.db import Base
from leka.main import app

SECRET_NAME = re.compile(
    r"(secret|password|passwd|api_key|apikey|private_key|access_token|refresh_token|credential|token)",
    re.IGNORECASE,
)

# Response fields named like a secret, and why each may be.
ALLOWED_IN_RESPONSES: dict[tuple[str, str], str] = {
    ("ActionEndpointCreated", "secret"): "an endpoint's signing secret, shown once (LEKA-391)",
    ("CatalogEntry", "credentials_schema"): "which credentials a connector asks for, not them",
    ("InvitationCreated", "token"): "the invitation's token, shown once to send it",
    ("MeResponse", "csrf_token"): "the double-submit CSRF token (ADR 009)",
    ("SourceRead", "credentials"): "a hint and when it was rotated, never the secret",
    ("PostureRead", "credential_keys"): "how many keys encrypt credentials: a count",
    ("PostureRead", "credentials_encryption"): "how credentials are encrypted: fernet",
    ("PostureRead", "overdue_secrets"): "the names of secrets past their lifetime",
    ("SourceFindingsRead", "secrets"): "what was found, by kind and count",
    ("SourceFindingsRead", "with_secrets"): "how many records held one",
    ("AIControlRead", "max_tokens"): "a usage limit in model tokens: a count (LEKA-406)",
}
COUNTS = re.compile(r"^tokens(_|$)")
# Binary columns that are not a ciphertext, and why each may be.
ALLOWED_BINARY: dict[str, str] = {
    "webhook_deliveries.body": "a delivery's body while a pass has yet to store it — seconds; "
    "customer data, not a credential, protected like any record once extracted",
}


def test_no_column_keeps_a_secret_in_the_clear() -> None:
    found = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            kind = column.type
            if isinstance(kind, LargeBinary):
                if (
                    not column.name.endswith("ciphertext")
                    and f"{table.name}.{column.name}" not in ALLOWED_BINARY
                ):
                    found.append(f"{table.name}.{column.name}: binary, not a ciphertext")
                continue
            if not SECRET_NAME.search(column.name) or COUNTS.match(column.name):
                continue
            if column.name.endswith(("_hash", "_ciphertext")):
                continue
            if isinstance(kind, Integer | BigInteger | DateTime | Boolean):
                continue
            found.append(f"{table.name}.{column.name}: {type(kind).__name__}")
    assert found == [], "A secret kept in the clear — hash it, or encrypt it (ADR 005)."


def _response_schemas() -> set[str]:
    """Every schema a response can carry, followed through its references."""
    spec = app.openapi()
    schemas: dict[str, Any] = spec["components"]["schemas"]
    seen: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name not in seen:
                    seen.add(name)
                    visit(schemas.get(name, {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    for path in spec["paths"].values():
        for operation in path.values():
            if isinstance(operation, dict):
                visit(operation.get("responses", {}))
    return seen


def test_no_response_exposes_a_secret() -> None:
    schemas = app.openapi()["components"]["schemas"]
    exposed = sorted(
        (name, field)
        for name in _response_schemas()
        for field in (schemas[name].get("properties") or {})
        if SECRET_NAME.search(field) and not COUNTS.match(field)
    )
    unexplained = [e for e in exposed if e not in ALLOWED_IN_RESPONSES]
    assert unexplained == [], "A response field named like a secret: remove it, or say why here."
    # And none listed here that is gone: the list says what is.
    assert set(ALLOWED_IN_RESPONSES) <= set(exposed)


def _production(**overrides: object) -> dict[str, object]:
    said: dict[str, object] = {
        "environment": "production",
        "database_url": "postgresql+asyncpg://leka:pw@db.internal:5432/leka?ssl=require",
        "redis_url": "redis://redis:6379/0",
        "secret_key": "s" * 64,
        "encryption_keys": ["MN3nrX7VP5Mj0SRB4G-pIPOrvlCyT-CQoBZvsQFYHss="],
        "object_store": "s3",
        "s3_bucket": "leka",
        "s3_access_key_id": "id",
        "s3_secret_access_key": "k" * 40,
        "web_url": "https://leka-core.com",
        "smtp_host": "smtp.example.com",
        "smtp_password": "p" * 20,
        "email_from": "noreply@leka-core.com",
    }
    said.update(overrides)
    return said


def test_production_refuses_plaintext_data() -> None:
    for wrong in (
        {"database_url": "postgresql+asyncpg://leka:pw@db:5432/leka?ssl=disable"},
        {"database_url": "postgresql+asyncpg://leka:pw@db:5432/leka?sslmode=disable"},
        {"s3_server_side_encryption": "none"},
    ):
        with pytest.raises(ValidationError, match="production"):
            Settings(**_production(**wrong))  # type: ignore[arg-type]
    # Amazon S3 is asked to encrypt; another endpoint only when told to.
    assert Settings(**_production()).s3_encryption == "AES256"  # type: ignore[arg-type]
    elsewhere = Settings(**_production(s3_endpoint_url="https://minio.internal"))  # type: ignore[arg-type]
    assert elsewhere.s3_encryption is None
    kms = Settings(**_production(s3_server_side_encryption="aws:kms"))  # type: ignore[arg-type]
    assert kms.s3_encryption == "aws:kms"
