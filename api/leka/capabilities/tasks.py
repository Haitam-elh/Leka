"""Re-encrypting the keys of the workspaces' own language models (LEKA-394)
under the current key.

The same half of a key rotation as the sources' credentials
(leka/connectors/tasks.py) and the signing secrets
(leka/intentions/tasks.py), by the same rules: safe to interrupt, each batch
committed on its own, a key the new key already wrote skipped, a key
changed during the run left alone, an unreadable one counted and logged.
Run by scripts/rotate_encryption_key.py, after the signing secrets.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

import structlog
from sqlalchemy import select, update

from leka.capabilities.models import WorkspaceModel
from leka.connectors import RotationRefusedError, RotationReport
from leka.db import session_factory, system_scope
from leka.platform import DecryptionError, SecretBox

logger = structlog.get_logger(__name__)

# Every column this rotation rewrites (tests/test_key_rotation.py).
ROTATED_COLUMNS = frozenset({"workspace_models.key_ciphertext"})


async def rotate_model_keys(
    box: SecretBox, *, batch: int = 500, dry_run: bool = False
) -> RotationReport:
    """Rewrite every model key the primary key did not write."""
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
                query = (
                    select(WorkspaceModel.id, WorkspaceModel.key_ciphertext)
                    .where(WorkspaceModel.key_ciphertext.is_not(None))
                    .order_by(WorkspaceModel.id)
                    .limit(batch)
                )
                if after is not None:
                    query = query.where(WorkspaceModel.id > after)
                rows = (await session.execute(query)).tuples().all()
                for model_id, token in rows:
                    report.examined += 1
                    if token is None or not box.needs_rotation(token):
                        report.current += 1
                        continue
                    try:
                        rotated = box.rotate(token)
                    except DecryptionError:
                        report.unreadable += 1
                        logger.error("model_key_unreadable", model_id=str(model_id))
                        continue
                    if dry_run:
                        report.rotated += 1
                        continue
                    # Only if it is still the one read: a key saved meanwhile
                    # is under the new key already.
                    written = await session.execute(
                        update(WorkspaceModel)
                        .where(
                            WorkspaceModel.id == model_id,
                            WorkspaceModel.key_ciphertext == token,
                        )
                        .values(key_ciphertext=rotated)
                    )
                    if written.rowcount:  # type: ignore[attr-defined]
                        report.rotated += 1
                    else:
                        report.changed += 1
                if not dry_run:
                    await session.commit()
        if len(rows) < batch:
            break
        after = rows[-1][0]
    logger.info("model_key_rotation_completed", dry_run=dry_run, **asdict(report))
    return report
