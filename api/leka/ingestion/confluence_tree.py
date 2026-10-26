"""What a Confluence source holds, as LEKA synced it (2026-10-25): its spaces,
and in each its pages — their parent, title, link, last change and text —
read from what extraction kept (source_records + extracted_records), never
by asking Confluence again.

    synced_confluence()   the spaces of one source, each with its pages as
                          the architect reads them (leka.architect.Page)

Only current pages: a page Confluence no longer shows (deleted_at) is not
here. Their text is the one protection kept (LEKA-405): a secret in a page
is already [redacted:…].
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.architect import Page
from leka.ingestion.models import ExtractedRecordRow, ExtractionStatus, SourceRecord

SPACES, PAGES = "spaces", "pages"


@dataclass
class SyncedSpace:
    key: str
    name: str
    url: str = ""
    pages: list[Page] = field(default_factory=list)


def _text(result: Mapping[str, Any]) -> str:
    parts = result.get("content") or []
    return "\n".join(
        str(part.get("text") or "") for part in parts if isinstance(part, dict)
    ).strip()


def _parent(result: Mapping[str, Any]) -> str | None:
    for reference in result.get("references") or []:
        if isinstance(reference, dict) and reference.get("role") == "parent":
            said = reference.get("external_id")
            return str(said) if said else None
    return None


async def synced_confluence(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    space: str | None = None,
    texts: bool = True,
) -> list[SyncedSpace]:
    """The spaces this source synced — `space`: that one only — each with
    its current pages; `texts`: False when only the tree is wanted."""
    query = (
        select(
            SourceRecord.kind,
            SourceRecord.external_id,
            SourceRecord.container,
            ExtractedRecordRow.result,
        )
        .join(ExtractedRecordRow, ExtractedRecordRow.source_record_id == SourceRecord.id)
        .where(
            SourceRecord.workspace_id == workspace_id,
            SourceRecord.source_id == source_id,
            SourceRecord.kind.in_((SPACES, PAGES)),
            SourceRecord.deleted_at.is_(None),
            ExtractedRecordRow.status == ExtractionStatus.EXTRACTED,
        )
    )
    if space is not None:
        query = query.where((SourceRecord.kind == SPACES) | (SourceRecord.container == space))
    spaces: dict[str, SyncedSpace] = {}
    pages: list[tuple[str, Page]] = []
    for kind, external_id, container, result in (await session.execute(query)).all():
        said: Mapping[str, Any] = result or {}
        if kind == SPACES:
            metadata = said.get("metadata") or {}
            key = str(metadata.get("key") or external_id)
            if space is None or key == space:
                spaces[key] = SyncedSpace(
                    key, str(said.get("title") or key), str(said.get("url") or "")
                )
            continue
        key = str(container or "")
        pages.append(
            (
                key,
                Page(
                    id=str(external_id),
                    title=str(said.get("title") or external_id),
                    text=_text(said) if texts else "",
                    url=str(said.get("url") or ""),
                    parent_id=_parent(said),
                    space=key,
                    updated_at=str(said.get("updated_at") or ""),
                ),
            )
        )
    for key, page in pages:
        spaces.setdefault(key, SyncedSpace(key, key)).pages.append(page)
    return sorted(spaces.values(), key=lambda s: s.name.lower())


__all__ = ["SyncedSpace", "synced_confluence"]
