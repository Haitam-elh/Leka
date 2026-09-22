"""Database access for the connectors module.

The only place in this module where a query is written (architecture rule 4).
SourceRepository's methods take a workspace_id and filter on it — there is no
"fetch all sources" there, because serving a customer never needs one.

The one exception is SourceCredentialSweeper, below: a key rotation spans
every workspace by definition, and says so.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, Result, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.connectors.models import Source


def _affected_rows(result: Result[Any]) -> int:
    """How many rows an UPDATE touched. Same shape as leka.ingestion's."""
    return int(cast("CursorResult[Any]", result).rowcount or 0)


class SourceRepository:
    """Reads and writes rows in `sources`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # list_for_workspace(workspace_id) -> Sequence[Source]
    # get(workspace_id, source_id) -> Source | None
    # mark_synced(workspace_id, source_id, at) -> None
    # mark_failed(workspace_id, source_id, error) -> None


class SourceCredentialSweeper:
    """Every stored credential, across every workspace — for key rotation only.

    Not workspace-scoped, for the reason RawPayloadSweeper gives: a rotation
    that stopped at one tenant would leave the others readable only with the
    old key, which is the key about to be removed. It must run inside
    system_scope(), which says so in one reviewable line.

    It moves ciphertext and nothing else. Nothing here can decrypt.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def encrypted_after(
        self, after: uuid.UUID | None, *, limit: int
    ) -> list[tuple[uuid.UUID, bytes]]:
        """The next batch of stored credentials, in id order, after `after`.

        Keyset, not OFFSET: rows rewritten by the previous batch do not move
        the position, so nothing is skipped or read twice.
        """
        statement = select(Source.id, Source.credentials_encrypted).where(
            Source.credentials_encrypted.is_not(None)
        )
        if after is not None:
            statement = statement.where(Source.id > after)
        result = await self._session.execute(statement.order_by(Source.id).limit(limit))
        return [(source_id, token) for source_id, token in result.tuples() if token is not None]

    async def replace(self, source_id: uuid.UUID, *, expected: bytes, new: bytes) -> bool:
        """Swap one ciphertext for another, unless the row changed since it was read.

        A plain UPDATE would overwrite a credential somebody saved while the
        rotation ran — encrypted under the new key already — with the rotated
        old one, silently reverting their change. False means that happened,
        and the row was left alone.
        """
        result = await self._session.execute(
            update(Source)
            .where(Source.id == source_id, Source.credentials_encrypted == expected)
            .values(credentials_encrypted=new)
        )
        return _affected_rows(result) == 1
