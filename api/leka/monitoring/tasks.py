"""Re-encrypting the webhooks of the alert channels (LEKA-496) under the
current key — the same half of a key rotation as the workspaces' model keys
(leka/capabilities/tasks.py), by the same rules: safe to interrupt, each
batch committed on its own, a URL the new key already wrote skipped, one
changed during the run left alone, an unreadable one counted and logged.
Run by scripts/rotate_encryption_key.py, after the model keys.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

import structlog
from sqlalchemy import select, update

from leka.connectors import RotationRefusedError, RotationReport
from leka.db import session_factory, system_scope
from leka.monitoring.models import ChannelEndpoint
from leka.platform import DecryptionError, SecretBox

logger = structlog.get_logger(__name__)

# Every column this rotation rewrites (tests/test_key_rotation.py).
ROTATED_COLUMNS = frozenset({"monitoring_channel_endpoints.webhook_ciphertext"})


async def rotate_channel_webhooks(
    box: SecretBox, *, batch: int = 500, dry_run: bool = False
) -> RotationReport:
    """Rewrite every webhook URL the primary key did not write."""
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
                    select(ChannelEndpoint.id, ChannelEndpoint.webhook_ciphertext)
                    .where(ChannelEndpoint.webhook_ciphertext.is_not(None))
                    .order_by(ChannelEndpoint.id)
                    .limit(batch)
                )
                if after is not None:
                    query = query.where(ChannelEndpoint.id > after)
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
                        logger.error("channel_webhook_unreadable", endpoint_id=str(model_id))
                        continue
                    if dry_run:
                        report.rotated += 1
                        continue
                    # Only if it is still the one read: a URL saved meanwhile
                    # is under the new key already.
                    written = await session.execute(
                        update(ChannelEndpoint)
                        .where(
                            ChannelEndpoint.id == model_id,
                            ChannelEndpoint.webhook_ciphertext == token,
                        )
                        .values(webhook_ciphertext=rotated)
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
    logger.info("channel_webhook_rotation_completed", dry_run=dry_run, **asdict(report))
    return report
