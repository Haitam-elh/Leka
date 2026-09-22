"""Rotating the credential encryption key, against a real database.

The half of a rotation that touches data: every stored credential
re-encrypted under the new key, so the old one can be removed without
leaving a row nobody can read. docs/adr/005-credential-storage.md names
rotation as this design's known weakness; these tests are what turn it from
a hope into a procedure.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterable

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update

from leka.connectors import Source, SourceCredentialSweeper, SourceKind
from leka.db import session_factory, system_scope
from leka.platform import SecretBox, Workspace

pytestmark = pytest.mark.integration

OLD, NEW = (Fernet.generate_key().decode() for _ in range(2))

# Step 1 of the procedure: the new key first, the old one kept behind it.
ROTATING = SecretBox((NEW, OLD))


@pytest.fixture
async def stored() -> AsyncIterator[dict[uuid.UUID, str]]:
    """Five credentials under the OLD key, over two workspaces. Source id -> token."""
    box = SecretBox((OLD,))
    tokens: dict[uuid.UUID, str] = {}
    workspaces: list[uuid.UUID] = []
    with system_scope():
        async with session_factory() as session:
            for tenant, count in (("alpha", 3), ("beta", 2)):
                workspace = Workspace(name=tenant, slug=f"{tenant}-{uuid.uuid4().hex[:10]}")
                session.add(workspace)
                await session.flush()
                workspaces.append(workspace.id)
                for index in range(count):
                    token = f"ghp_{tenant}_{index}_{uuid.uuid4().hex}"
                    source = Source(
                        workspace_id=workspace.id,
                        kind=SourceKind.GITHUB,
                        name=f"{tenant}-{index}",
                        credentials_encrypted=box.encrypt(token),
                    )
                    session.add(source)
                    await session.flush()
                    tokens[source.id] = token
            await session.commit()
    try:
        yield tokens
    finally:
        with system_scope():
            async with session_factory() as session:
                for workspace_id in workspaces:
                    leftover = await session.get(Workspace, workspace_id)
                    if leftover is not None:
                        await session.delete(leftover)
                await session.commit()


async def _ciphertexts(source_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, bytes]:
    with system_scope():
        async with session_factory() as session:
            rows = await session.execute(
                select(Source.id, Source.credentials_encrypted).where(Source.id.in_(source_ids))
            )
            return {source_id: token for source_id, token in rows.tuples() if token is not None}


async def test_an_unchanged_credential_is_swapped(stored: dict[uuid.UUID, str]) -> None:
    """The other half: without it, a swap that never writes would pass the test below."""
    source_id = next(iter(stored))
    read = (await _ciphertexts([source_id]))[source_id]
    rotated = ROTATING.rotate(read)

    with system_scope():
        async with session_factory() as session:
            swapped = await SourceCredentialSweeper(session).replace(
                source_id, expected=read, new=rotated
            )
            await session.commit()

    assert swapped is True
    assert (await _ciphertexts([source_id]))[source_id] == rotated


async def test_a_credential_saved_during_the_rotation_is_not_overwritten(
    stored: dict[uuid.UUID, str],
) -> None:
    """The rotation read a ciphertext; a user then saved a new token. Writing
    the rotated old one over it would silently revert their change."""
    source_id = next(iter(stored))
    read = (await _ciphertexts([source_id]))[source_id]
    saved_meanwhile = ROTATING.encrypt("ghp_saved_while_the_rotation_ran")
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                update(Source)
                .where(Source.id == source_id)
                .values(credentials_encrypted=saved_meanwhile)
            )
            await session.commit()

    with system_scope():
        async with session_factory() as session:
            swapped = await SourceCredentialSweeper(session).replace(
                source_id, expected=read, new=ROTATING.rotate(read)
            )
            await session.commit()

    assert swapped is False
    assert (await _ciphertexts([source_id]))[source_id] == saved_meanwhile
