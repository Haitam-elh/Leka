"""The application architect on a Confluence space (2026-10-25): its
dossier structured as ArchiMate, every section citing its pages — the
steps of leka.architect, the same the downloadable agent runs, on what LEKA
synced and with the model LEKA routes to.

    wants_dossier()   the architect asked on a space (`espace`): this, not
                      the deck
    perimeter_of()    that space's synced pages — or a page and everything
                      under it (`page_racine`) — and the source they came from
    draw_dossier()    the model asked, step by step (leka.architect.analysis);
                      the dossier written — Markdown, PDF, Word, JSON — and
                      kept: {workspace}/agent-runs/{run}/dossier.{fmt}

Read only: Confluence is never written. Its pages go to the model this
workspace routes to, nowhere else; never to a log.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.architect import MEDIA_TYPES, Dossier, Page, Tree, analyse_async, docx, markdown, pdf
from leka.architect import problems as lacking
from leka.capabilities.catalogue import needs_of
from leka.capabilities.definition import Definition
from leka.capabilities.gateway import Completion, Gateway, Message, Request, Tier
from leka.capabilities.models import AgentRun
from leka.connectors import Source, SourceKind
from leka.ingestion import synced_confluence
from leka.platform import from_bytes, object_store

logger = structlog.get_logger(__name__)

SPACE, ROOT = "espace", "page_racine"
FORMATS = ("md", "pdf", "docx", "json")
# One call's answer at most: a dossier's every section, its elements.
DOSSIER_TOKENS = 16_000


def wants_dossier(definition: Definition, inputs: Mapping[str, object]) -> bool:
    """The architect, asked on a Confluence space."""
    said = inputs.get(SPACE)
    return (
        definition.renders == "architecture_deck" and isinstance(said, str) and bool(said.strip())
    )


def dossier_key(workspace_id: uuid.UUID, run_id: uuid.UUID, fmt: str) -> str:
    return f"{workspace_id}/agent-runs/{run_id}/dossier.{fmt}"


@dataclass
class Perimeter:
    space: str
    root: str | None
    source_id: uuid.UUID | None = None
    source_name: str = ""
    space_name: str = ""
    pages: list[Page] = field(default_factory=list)

    @property
    def said(self) -> str:
        """The scope, as the dossier says it."""
        name = self.space_name or self.space
        said = f"Espace Confluence « {name} » ({self.space})"
        if self.root and self.pages:
            said += f", à partir de la page « {self.pages[0].title} »"
        return said


async def perimeter_of(
    session: AsyncSession, workspace_id: uuid.UUID, inputs: Mapping[str, object]
) -> Perimeter:
    """The pages asked for, from the first Confluence source that synced
    that space — none when no source holds it."""
    space = str(inputs.get(SPACE) or "").strip()
    root = str(inputs.get(ROOT) or "").strip() or None
    found = Perimeter(space, root)
    sources = await session.scalars(
        select(Source)
        .where(Source.workspace_id == workspace_id, Source.kind == SourceKind.CONFLUENCE)
        .order_by(Source.created_at)
    )
    for source in sources:
        for synced in await synced_confluence(session, workspace_id, source.id, space=space):
            if synced.key != space or not synced.pages:
                continue
            tree = Tree(synced.pages)
            pages = tree.under(root)
            if not pages:
                continue
            return Perimeter(space, root, source.id, source.name, synced.name, pages)
    return found


@dataclass
class DossierDrawn:
    dossier: Dossier
    text: str
    files: list[dict[str, Any]]
    completion: Completion | None
    calls: int


def file_name(perimeter: Perimeter, fmt: str) -> str:
    name = " ".join(f"Dossier d'architecture - {perimeter.space_name or perimeter.space}".split())
    cleaned = "".join(c if c.isalnum() or c in " -_'()" else " " for c in name)
    return f"{' '.join(cleaned.split())[:150]}.{fmt}"


async def draw_dossier(
    session: AsyncSession,
    run: AgentRun,
    definition: Definition,
    perimeter: Perimeter,
    *,
    said: Any = None,
) -> DossierDrawn:
    """The dossier of these pages, asked of this workspace's model, written
    and kept — NoModelError, DossierError or ObjectStoreError otherwise."""
    gateway = Gateway(session, run.workspace_id)
    needs = replace(needs_of(definition), tools=False)
    last: list[Completion] = []

    async def ask(system: str, user: str) -> str:
        done = await gateway.complete(
            Request(
                purpose=f"agent:{definition.key}:dossier"[:100],
                messages=[Message.system(system), Message.user(user)],
                tier=Tier.DEEP,
                max_tokens=DOSSIER_TOKENS,
                ref=f"agent_run:{run.id}",
            ),
            needs,
        )
        last.append(done)
        return done.text

    focus = run.inputs.get("parcours")
    dossier = await analyse_async(
        ask,
        perimeter.pages,
        scope=perimeter.said,
        focus=str(focus) if isinstance(focus, str) and focus.strip() else None,
        said=said,
    )
    text = markdown(dossier)
    rendered = {
        "md": text.encode(),
        "pdf": await asyncio.to_thread(pdf, dossier),
        "docx": await asyncio.to_thread(docx, dossier),
        "json": json.dumps(dossier.to_json(), ensure_ascii=False, indent=2).encode(),
    }
    store = object_store()
    files: list[dict[str, Any]] = []
    for fmt in FORMATS:
        stored = await store.put(
            dossier_key(run.workspace_id, run.id, fmt),
            from_bytes(rendered[fmt]),
            content_type=MEDIA_TYPES[fmt],
        )
        files.append(
            {
                "format": fmt,
                "key": stored.key,
                "name": file_name(perimeter, fmt),
                "size": stored.size_bytes,
                "kind": "dossier",
            }
        )
    logger.info(
        "dossier_drawn",
        run=str(run.id),
        pages=len(perimeter.pages),
        elements=len(dossier.elements),
        dropped=len(dossier.dropped),
    )
    return DossierDrawn(dossier, text, files, last[-1] if last else None, len(last))


def summary_of(dossier: Dossier, perimeter: Perimeter) -> dict[str, object]:
    """What a run's detail keeps of its dossier: counted, never its text."""
    return {
        "space": perimeter.space,
        "root": perimeter.root,
        "pages": len(perimeter.pages),
        "cited": len(dossier.pages_read),
        "sections": len(dossier.sections),
        "elements": len(dossier.elements),
        "relations": len(dossier.relations),
        "points": len(dossier.points),
        "dropped": len(dossier.dropped),
        "lacking": lacking(dossier)[:20],
    }


__all__ = [
    "FORMATS",
    "DossierDrawn",
    "Perimeter",
    "dossier_key",
    "draw_dossier",
    "file_name",
    "perimeter_of",
    "summary_of",
    "wants_dossier",
]
