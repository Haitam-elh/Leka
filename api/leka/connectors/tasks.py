"""Re-encrypting stored credentials under the current key.

The half of a key rotation that touches the database. SecretBox already
decrypts with every configured key and encrypts with the first; this walks
every stored credential and rewrites the ones the first key did not write.
Run through scripts/rotate_encryption_key.py, which says when.

SAFE TO INTERRUPT, AND THAT IS WHAT MAKES IT SAFE TO RUN. MultiFernet
decrypts with any configured key, so a half-rotated table is a fully
readable table: rows already rewritten read with the new key, the rest with
the old one, and both stay configured for as long as the rotation runs.
Each batch commits on its own and a row the new key already wrote is
skipped, so a second run finishes the job without redoing or damaging any of
the first.

A ROW CHANGED DURING THE RUN IS LEFT ALONE. The rewrite only happens if the
ciphertext is still the one that was read: somebody saving a new token
meanwhile has it encrypted under the new key already, and writing the
rotated old one over it would silently revert their change.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass

import structlog

from leka.connectors.repository import SourceCredentialSweeper
from leka.db import session_factory, system_scope
from leka.platform import DecryptionError, SecretBox

logger = structlog.get_logger(__name__)

# Every column this rotation rewrites. tests/test_key_rotation.py fails if a
# column holding ciphertext appears anywhere without being listed here.
ROTATED_COLUMNS = frozenset({"sources.credentials_encrypted"})


class RotationRefusedError(RuntimeError):
    """Fewer than two keys configured: there is nothing to rotate to."""


@dataclass
class RotationReport:
    """What a run did, or in a dry run would have done."""

    examined: int = 0
    rotated: int = 0
    current: int = 0
    changed: int = 0
    unreadable: int = 0


async def rotate_source_credentials(
    box: SecretBox, *, batch: int = 500, dry_run: bool = False
) -> RotationReport:
    """Rewrite every stored credential the primary key did not write.

    Unreadable rows — no configured key decrypts them — are counted and
    logged, never skipped in silence, and never stop the others: the caller
    decides what a non-zero count means. A dry run still decrypts each
    candidate, so its count of unreadable rows is as real as a run's.
    """
    if box.key_count < 2:
        msg = (
            "only one key in LEKA_ENCRYPTION_KEYS. A rotation needs the new key "
            "first and the old one after it, both configured and deployed."
        )
        raise RotationRefusedError(msg)

    report = RotationReport()
    after: uuid.UUID | None = None
    while True:
        with system_scope():
            async with session_factory() as session:
                sweeper = SourceCredentialSweeper(session)
                rows = await sweeper.encrypted_after(after, limit=batch)
                for source_id, token in rows:
                    report.examined += 1
                    if not box.needs_rotation(token):
                        report.current += 1
                        continue
                    try:
                        rotated = box.rotate(token)
                    except DecryptionError:
                        report.unreadable += 1
                        logger.error("credential_unreadable", source_id=str(source_id))
                        continue
                    if dry_run or await sweeper.replace(source_id, expected=token, new=rotated):
                        report.rotated += 1
                    else:
                        report.changed += 1
                if not dry_run:
                    await session.commit()
        if len(rows) < batch:
            break
        after = rows[-1][0]

    logger.info("credential_rotation_completed", dry_run=dry_run, **asdict(report))
    return report
