"""Re-encrypting the signing secrets of the systems a workspace authorized
(LEKA-391) under the current key.

The same half of a key rotation as the sources' credentials
(leka/connectors/tasks.py), and the same rules: safe to interrupt — a
half-rotated table reads with either key — each batch committed on its own,
a secret the new key already wrote skipped, a secret changed during the run
left alone, an unreadable one counted and logged. Run by
scripts/rotate_encryption_key.py, after the credentials.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

import structlog
from sqlalchemy import select, update

from leka.connectors import RotationRefusedError, RotationReport
from leka.db import session_factory, system_scope
from leka.intentions.models import ActionEndpoint
from leka.platform import DecryptionError, SecretBox

logger = structlog.get_logger(__name__)

# Every column this rotation rewrites (tests/test_key_rotation.py).
ROTATED_COLUMNS = frozenset({"action_endpoints.secret_ciphertext"})


async def rotate_endpoint_secrets(
    box: SecretBox, *, batch: int = 500, dry_run: bool = False
) -> RotationReport:
    """Rewrite every signing secret the primary key did not write."""
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
                    select(ActionEndpoint.id, ActionEndpoint.secret_ciphertext)
                    .order_by(ActionEndpoint.id)
                    .limit(batch)
                )
                if after is not None:
                    query = query.where(ActionEndpoint.id > after)
                rows = (await session.execute(query)).tuples().all()
                for endpoint_id, token in rows:
                    report.examined += 1
                    if not box.needs_rotation(token):
                        report.current += 1
                        continue
                    try:
                        rotated = box.rotate(token)
                    except DecryptionError:
                        report.unreadable += 1
                        logger.error("endpoint_secret_unreadable", endpoint_id=str(endpoint_id))
                        continue
                    if dry_run:
                        report.rotated += 1
                        continue
                    # Only if it is still the one read: a secret saved meanwhile
                    # is under the new key already.
                    written = await session.execute(
                        update(ActionEndpoint)
                        .where(
                            ActionEndpoint.id == endpoint_id,
                            ActionEndpoint.secret_ciphertext == token,
                        )
                        .values(secret_ciphertext=rotated)
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
    logger.info("endpoint_secret_rotation_completed", dry_run=dry_run, **asdict(report))
    return report
