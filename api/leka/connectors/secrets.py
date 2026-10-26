"""Where a source's secret lives, behind one interface.

SecretStore is what the framework asks; DatabaseFernetSecretStore is today's
answer: Fernet (leka.platform.SecretBox, ADR 005), in `source_credentials`.
Moving to AWS KMS or Secrets Manager (LEKA-405) is another class with the
same three methods — no connector changes, because no connector knows.

WRITE-ONLY FROM OUTSIDE. The API can put a secret and describe it (a masked
hint, when it was set); only the lifecycle service opens one, at the moment
it builds a connector, and holds it no longer than that call. Nothing here
caches a plaintext.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, SecretStr

from leka.connectors.repository import SourceCredentialRepository
from leka.platform import SecretBox, secret_box


class StoredCredentials(BaseModel):
    """What may be said about a stored secret: never the secret."""

    hint: str
    key_version: str
    rotated_at: datetime


class SecretStore(Protocol):
    async def put(self, source_id: uuid.UUID, credentials: BaseModel) -> StoredCredentials: ...

    async def open(self, source_id: uuid.UUID) -> dict[str, str] | None: ...

    async def describe(self, source_id: uuid.UUID) -> StoredCredentials | None: ...

    async def erase(self, source_id: uuid.UUID) -> bool: ...


def reveal(credentials: BaseModel) -> dict[str, str]:
    """A credentials model as plain strings — for encryption, and nothing else."""
    revealed: dict[str, str] = {}
    for name, value in credentials:
        if value is None:
            continue
        revealed[name] = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
    return revealed


def mask(secret: str) -> str:
    """'github_pat_11ABC…xyz9' → 'github_pat_…xyz9'. Recognisable, not usable.

    A vendor prefix (up to the last underscore in the first twelve
    characters) is kept, because it says which kind of token this is; the
    last four characters say which one. A secret too short to spare four
    characters shows none.
    """
    if len(secret) < 12:
        return "…"
    head = secret[:12]
    prefix = head[: head.rfind("_") + 1] if "_" in head else ""
    return f"{prefix}…{secret[-4:]}"


class DatabaseFernetSecretStore:
    def __init__(self, repository: SourceCredentialRepository, box: SecretBox = secret_box) -> None:
        self._repository = repository
        self._box = box

    async def put(self, source_id: uuid.UUID, credentials: BaseModel) -> StoredCredentials:
        plain = reveal(credentials)
        first = next(iter(plain.values()), "")
        row = await self._repository.put(
            source_id,
            ciphertext=self._box.encrypt(json.dumps(plain, sort_keys=True)),
            key_version=self._box.key_version,
            hint=mask(first),
            rotated_at=datetime.now(UTC),
        )
        return StoredCredentials(
            hint=row.hint, key_version=row.key_version, rotated_at=row.rotated_at
        )

    async def open(self, source_id: uuid.UUID) -> dict[str, str] | None:
        row = await self._repository.find(source_id)
        if row is None:
            return None
        opened: dict[str, str] = json.loads(self._box.decrypt(row.ciphertext))
        return opened

    async def describe(self, source_id: uuid.UUID) -> StoredCredentials | None:
        row = await self._repository.find(source_id)
        if row is None:
            return None
        return StoredCredentials(
            hint=row.hint, key_version=row.key_version, rotated_at=row.rotated_at
        )

    async def erase(self, source_id: uuid.UUID) -> bool:
        """Its secret gone — revoked by a person (2026-10-25) — True when there
        was one."""
        row = await self._repository.find(source_id)
        if row is None:
            return False
        await self._repository.delete(row)
        await self._repository.flush()
        return True
