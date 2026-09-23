"""Rotating the credential encryption key, against a real database.

The half of a rotation that touches data: every stored credential
re-encrypted under the new key, so the old one can be removed without
leaving a row nobody can read. docs/adr/005-credential-storage.md names
rotation as this design's known weakness; these tests are what turn it from
a hope into a procedure.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import LargeBinary, select, update

from leka.connectors import (
    ROTATED_COLUMNS,
    RotationRefusedError,
    Source,
    SourceCredential,
    SourceCredentialSweeper,
    SourceKind,
    rotate_source_credentials,
)
from leka.db import Base, session_factory, system_scope
from leka.platform import DecryptionError, SecretBox, Workspace

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
OLD, NEW, FOREIGN = (Fernet.generate_key().decode() for _ in range(3))

# Step 1 of the procedure: the new key first, the old one kept behind it.
ROTATING = SecretBox((NEW, OLD))


def _credential(source: Source, ciphertext: bytes, key_version: str) -> SourceCredential:
    return SourceCredential(
        workspace_id=source.workspace_id,
        source_id=source.id,
        ciphertext=ciphertext,
        key_version=key_version,
        hint="…",
        rotated_at=datetime.now(UTC),
    )


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
                        workspace_id=workspace.id, kind=SourceKind.GITHUB, name=f"{tenant}-{index}"
                    )
                    session.add(source)
                    await session.flush()
                    session.add(_credential(source, box.encrypt(token), "old"))
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
                select(SourceCredential.source_id, SourceCredential.ciphertext).where(
                    SourceCredential.source_id.in_(source_ids)
                )
            )
            # list() first: a Result has keys(), and dict() would take it for a mapping.
            return dict(list(rows.tuples()))


def _all_read_by(
    box: SecretBox, stored: dict[uuid.UUID, str], rows: dict[uuid.UUID, bytes]
) -> bool:
    return all(box.decrypt(rows[source_id]) == token for source_id, token in stored.items())


async def test_a_rotation_rewrites_every_credential_under_the_new_key(
    stored: dict[uuid.UUID, str],
) -> None:
    """Readable afterwards with the new key alone — and no longer with the old one,
    which proves each row was rewritten rather than left as it was."""
    report = await rotate_source_credentials(ROTATING)

    assert (report.rotated, report.current, report.unreadable) == (5, 0, 0)
    after = await _ciphertexts(stored)
    assert _all_read_by(SecretBox((NEW,)), stored, after)
    for token in after.values():
        with pytest.raises(DecryptionError):
            SecretBox((OLD,)).decrypt(token)


class _KilledMidway(SecretBox):
    """Dies on its third rotation: in the middle of the second batch."""

    def __init__(self) -> None:
        super().__init__((NEW, OLD))
        self.calls = 0

    def rotate(self, token: bytes) -> bytes:
        self.calls += 1
        if self.calls == 3:
            msg = "killed"
            raise RuntimeError(msg)
        return super().rotate(token)


async def test_an_interrupted_rotation_stays_readable_and_resumes(
    stored: dict[uuid.UUID, str],
) -> None:
    """The property the whole procedure rests on."""
    with pytest.raises(RuntimeError, match="killed"):
        await rotate_source_credentials(_KilledMidway(), batch=2)

    # Half rotated, fully readable: both keys are still configured.
    assert _all_read_by(ROTATING, stored, await _ciphertexts(stored))

    report = await rotate_source_credentials(ROTATING, batch=2)

    # The committed first batch is recognised, not redone.
    assert (report.current, report.rotated) == (2, 3)
    assert _all_read_by(SecretBox((NEW,)), stored, await _ciphertexts(stored))


async def test_a_dry_run_counts_and_writes_nothing(stored: dict[uuid.UUID, str]) -> None:
    before = await _ciphertexts(stored)

    report = await rotate_source_credentials(ROTATING, dry_run=True)

    assert report.rotated == 5
    assert await _ciphertexts(stored) == before


async def test_an_unchanged_credential_is_swapped(stored: dict[uuid.UUID, str]) -> None:
    """The other half: without it, a swap that never writes would pass the test below."""
    source_id = next(iter(stored))
    read = (await _ciphertexts([source_id]))[source_id]
    rotated = ROTATING.rotate(read)

    with system_scope():
        async with session_factory() as session:
            swapped = await SourceCredentialSweeper(session).replace(
                source_id, expected=read, new=rotated, key_version=ROTATING.key_version
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
                update(SourceCredential)
                .where(SourceCredential.source_id == source_id)
                .values(ciphertext=saved_meanwhile)
            )
            await session.commit()

    with system_scope():
        async with session_factory() as session:
            swapped = await SourceCredentialSweeper(session).replace(
                source_id,
                expected=read,
                new=ROTATING.rotate(read),
                key_version=ROTATING.key_version,
            )
            await session.commit()

    assert swapped is False
    assert (await _ciphertexts([source_id]))[source_id] == saved_meanwhile


async def test_a_credential_no_configured_key_reads_is_reported(
    stored: dict[uuid.UUID, str],
) -> None:
    """An old key removed too early, a backup from another environment. The
    row is counted and logged, and the others still rotate."""
    with system_scope():
        async with session_factory() as session:
            workspace_id = await session.scalar(
                select(Source.workspace_id).where(Source.id == next(iter(stored)))
            )
            assert workspace_id is not None
            foreign = Source(
                workspace_id=workspace_id, kind=SourceKind.GITHUB, name="from-another-environment"
            )
            session.add(foreign)
            await session.flush()
            session.add(_credential(foreign, SecretBox((FOREIGN,)).encrypt("ghp_unreadable"), "x"))
            await session.commit()

    report = await rotate_source_credentials(ROTATING)

    assert (report.rotated, report.unreadable) == (5, 1)


async def test_a_single_key_is_refused() -> None:
    """With one key there is nothing to rotate to, and an operator who forgot
    to put the new key first would read "0 rotated" as a success."""
    with pytest.raises(RotationRefusedError, match="new key first"):
        await rotate_source_credentials(SecretBox((OLD,)))


def test_the_script_runs_and_refuses_a_single_key() -> None:
    """The script as an operator runs it, wired end to end, touching no row."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(REPO_ROOT / "scripts" / "rotate_encryption_key.py"), "--dry-run"],
        capture_output=True,
        text=True,
        env={**os.environ, "LEKA_ENCRYPTION_KEYS": f'["{OLD}"]'},
        check=False,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "new key first" in result.stderr


def test_every_encrypted_column_is_rotated() -> None:
    """A column added later under the same key would come through a rotation
    untouched — and become unreadable the day the old key is removed."""
    encrypted = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, LargeBinary) or column.name.endswith("_encrypted")
    }
    assert encrypted, "no encrypted column found at all: are the models imported?"
    assert encrypted <= ROTATED_COLUMNS, (
        f"encrypted but never rotated: {sorted(encrypted - ROTATED_COLUMNS)}. "
        "Rotate it in its module's tasks.py and call that from "
        "scripts/rotate_encryption_key.py."
    )


async def test_a_rotated_credential_records_the_key_that_wrote_it(
    stored: dict[uuid.UUID, str],
) -> None:
    """What an operator reads to know a rotation finished: every row names the new key."""
    await rotate_source_credentials(ROTATING)

    with system_scope():
        async with session_factory() as session:
            versions = set(
                (
                    await session.execute(
                        select(SourceCredential.key_version).where(
                            SourceCredential.source_id.in_(stored)
                        )
                    )
                ).scalars()
            )
    assert versions == {ROTATING.key_version}
