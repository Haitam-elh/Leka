"""How LEKA protects data, as it stands now (LEKA-405): read from the
running process and the database, never assumed from a document.

    in transit    the connection to PostgreSQL: TLS or not, and which
                  version — as PostgreSQL says it (pg_stat_ssl); the
                  browser's, through the proxy's TLS (deploy/Caddyfile)
    at rest       the object store and how each write asks it to encrypt;
                  credentials and endpoint secrets in Fernet (ADR 005), how
                  many keys are configured — more than one while a rotation
                  runs
    keys          the secrets past their declared lifetime, by name
    isolation     the workspace guard (ADR 007): on in every process

What a workspace's administrators see on Sécurité & gouvernance — the same
for every workspace, since it is the platform's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.core.config import settings
from leka.platform.secrets import secret_box


@dataclass(frozen=True)
class Posture:
    environment: str
    database_tls: bool | None
    database_tls_version: str | None
    object_store: str
    object_store_encryption: str | None
    credentials_encryption: str
    credential_keys: int
    session_cookie_secure: bool
    overdue_secrets: tuple[str, ...]


async def database_tls(session: AsyncSession) -> tuple[bool | None, str | None]:
    """Whether this connection to PostgreSQL is encrypted, and how — None
    when PostgreSQL cannot say."""
    try:
        row = (
            await session.execute(
                text("SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
            )
        ).first()
    except Exception:
        return None, None
    if row is None:
        return None, None
    return bool(row[0]), (str(row[1]) if row[1] else None)


async def posture(session: AsyncSession) -> Posture:
    tls, version = await database_tls(session)
    return Posture(
        environment=settings.environment,
        database_tls=tls,
        database_tls_version=version,
        object_store=settings.object_store,
        object_store_encryption=(settings.s3_encryption if settings.object_store == "s3" else None),
        credentials_encryption="fernet",
        # Asked of the box that holds them: the keys themselves are its alone.
        credential_keys=secret_box.key_count,
        session_cookie_secure=settings.session_cookie_secure,
        overdue_secrets=tuple(
            s.setting for s in settings.overdue_secrets(datetime.now(UTC).date())
        ),
    )


__all__ = ["Posture", "database_tls", "posture"]
