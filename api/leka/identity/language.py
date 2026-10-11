"""The language LEKA writes to someone in — what a model is told to answer
in, whatever surfaces are translated.

The person's own, else their workspace's, else the catalogue's default
(leka/core/languages.yaml). A model writes any language the catalogue
offers, translated interface or not: someone who chose Japanese reads
LEKA's answers in Japanese while the screens around them fall back.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.core import languages
from leka.identity.models import User
from leka.platform import Workspace


async def workspace_language(session: AsyncSession, workspace_id: uuid.UUID | None) -> str:
    """The language of what a workspace shares."""
    own = (
        await session.scalar(select(Workspace.default_language).where(Workspace.id == workspace_id))
        if workspace_id is not None
        else None
    )
    return own or languages.catalogue().default


async def spoken_language(
    session: AsyncSession, user_id: uuid.UUID | None, workspace_id: uuid.UUID | None
) -> str:
    """The language to write to this person in, in this workspace."""
    chosen = (
        await session.scalar(select(User.language).where(User.id == user_id))
        if user_id is not None
        else None
    )
    return chosen or await workspace_language(session, workspace_id)
