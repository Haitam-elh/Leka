"""What LEKA draws of what an agent delivered — the application architect's
deck (`renders: architecture_deck`): its editable PowerPoint and its PDF.

    the run's analysis   markdown, from its sources (runs.py)
        ──▶ the model again, no tools: the deck's content, structured
            (deliverables.ArchitectureDeck) — from the analysis only;
            checked, asked again when it does not match
        ──▶ drawn on the agent's template (deliverables.render)
        ──▶ kept: {workspace}/agent-runs/{run}/deck.{pptx,pdf} — erased
            with the workspace; a key the orphan reconciliation leaves
            alone (it judges only {workspace}/{source}/{yyyy}/{mm}/{dd}/…)
    GET /agent-runs/{id}/deliverables/{format} — to download.

What fails here never fails the run: its analysis stands, the run says why
its files are missing (`deliverables_error`).
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, replace
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.catalogue import needs_of
from leka.capabilities.changes import propose_change
from leka.capabilities.definition import Definition
from leka.capabilities.deliverables import MEDIA_TYPES, ArchitectureDeck, render
from leka.capabilities.gateway import Gateway, Message, NoModelError, Request, Tier
from leka.capabilities.models import AgentRun
from leka.platform import ObjectStoreError, from_bytes, object_store

logger = structlog.get_logger(__name__)

# The deck's content, at most: every slide's text.
DECK_TOKENS = 16_000
# How long drawing may take, the model's answer included.
DECK_BUDGET = 10 * 60.0
FORMATS = ("pptx", "pdf")

DECK_RULES = """You are LEKA's deck writer for the agent whose instructions \
follow. From its analysis — and from nothing else — fill the content of its \
deck, each part as its template defines it:
- Only what the analysis holds: no application, service, rule, name or \
contact of your own. What the template needs and the analysis lacks is \
`missing: true` (drawn in orange) or « À confirmer », and is one of the \
points to confirm (`controls`), with where it is (« Process C - bande 2 », \
« Transverse »).
- business: the actor (« Client » or « Conseiller », with « ? » when \
uncertain), the trigger, the source process and its channel, the groupings \
A, B, C… each with its steps — on the baseline (`branch: main`), \
alternatives above or below it.
- processes: one per grouping, same letter and label; its columns in the \
order of their first call; its bands are its phases; each line is one \
chain of calls read left to right, each call naming its column exactly.
- app_view: only when the inputs ask for it (vue_applicative true), else \
null; one box per application, flows aggregated, numbered in order.
- raci: one row per brick and role found; a contact is a name from the \
analysis, else « À confirmer ».
- sources: each source consulted, one row « Requêtes restées SANS \
RÉSULTAT », one row « Couche infrastructure » (« NON DOCUMENTÉ » when \
absent).
- In French, as short as the template wants it: a step in a few words, a \
service by its name and a precision in parentheses.
Answer with the JSON object only."""


def deck_messages(
    definition: Definition, inputs: Mapping[str, object], analysis: str
) -> list[Message]:
    """The deck writer's rules, then the agent's own instructions — its
    template; the inputs and the analysis, as data."""
    system = f"{DECK_RULES}\n\n---\n\n{definition.instructions or ''}"
    material = {"inputs": dict(inputs), "analysis": analysis}
    return [
        Message.system(system),
        Message.user(json.dumps(material, ensure_ascii=False, default=str)),
    ]


def deliverable_key(workspace_id: uuid.UUID, run_id: uuid.UUID, fmt: str) -> str:
    return f"{workspace_id}/agent-runs/{run_id}/deck.{fmt}"


_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def file_name(deck: ArchitectureDeck, fmt: str) -> str:
    """« Architecture applicative - Parcours Paiement CB.pdf » — nothing a
    file system refuses."""
    title = _UNSAFE.sub(" ", f"Architecture applicative - Parcours {deck.parcours}")
    return f"{' '.join(title.split())[:150]}.{fmt}"


@dataclass(frozen=True)
class Drawn:
    """What a run's detail keeps of what LEKA made of it — or why nothing:
    its files (a deck), or the change it proposes (code_change)."""

    files: list[dict[str, Any]]
    error: str | None = None
    usage: dict[str, Any] | None = None
    # The step it is said as, and what the run's detail keeps instead of
    # files.
    step: str = "rendered"
    kept: dict[str, Any] | None = None

    def detail(self) -> dict[str, Any]:
        if self.error is not None:
            return {"deliverables_error": self.error}
        if self.kept is not None:
            return dict(self.kept)
        return {"deliverables": self.files}

    def said(self) -> dict[str, Any]:
        """What its step says."""
        if self.kept is not None:
            return {**self.kept, **(self.usage or {})}
        return {
            "formats": [f["format"] for f in self.files],
            "slides": self.files[0]["slides"] if self.files else 0,
            **(self.usage or {}),
        }


async def draw(
    session: AsyncSession,
    run: AgentRun,
    definition: Definition,
    analysis: str,
    *,
    budget: float = DECK_BUDGET,
) -> Drawn:
    """The deck of a run's analysis, drawn and kept — or, for a code-change
    agent, the change it proposes (changes.py) — or why not."""
    if definition.renders == "code_change":
        proposed = await propose_change(session, run, definition, analysis)
        if proposed.change is None:
            return Drawn([], proposed.error or "no_change", step="render_failed")
        change = proposed.change
        return Drawn(
            [],
            usage=proposed.usage,
            step="proposed",
            kept={
                "code_change": str(change.id),
                "repository": change.repository,
                "files": len(change.files),
            },
        )
    request = Request(
        purpose=f"agent:{definition.key}:deck"[:100],
        messages=deck_messages(definition, run.inputs, analysis),
        tier=Tier.DEEP,
        max_tokens=DECK_TOKENS,
        ref=f"agent_run:{run.id}",
    )
    try:
        answered = await asyncio.wait_for(
            Gateway(session, run.workspace_id).structured(
                request, ArchitectureDeck, replace(needs_of(definition), tools=False)
            ),
            timeout=budget,
        )
    except NoModelError as error:
        logger.warning("deck_not_written", run=str(run.id), reason=error.reason)
        return Drawn([], "no_model")
    except TimeoutError:
        return Drawn([], "timeout")
    deck = answered.value
    try:
        rendered = await asyncio.to_thread(render, deck)
    except Exception:
        logger.exception("deck_not_drawn", run=str(run.id))
        return Drawn([], "render")
    store = object_store()
    files: list[dict[str, Any]] = []
    try:
        for fmt in FORMATS:
            stored = await store.put(
                deliverable_key(run.workspace_id, run.id, fmt),
                from_bytes(rendered.of(fmt)),
                content_type=MEDIA_TYPES[fmt],
            )
            files.append(
                {
                    "format": fmt,
                    "key": stored.key,
                    "name": file_name(deck, fmt),
                    "size": stored.size_bytes,
                    "slides": rendered.slides,
                }
            )
    except ObjectStoreError:
        logger.exception("deck_not_kept", run=str(run.id))
        return Drawn([], "storage")
    done = answered.completion
    return Drawn(
        files,
        usage={
            "provider": done.provider,
            "model": done.model,
            "tokens_in": done.usage.tokens_in,
            "tokens_out": done.usage.tokens_out,
        },
    )


def deliverable_of(run: AgentRun, fmt: str) -> Mapping[str, Any] | None:
    """The file of this format a run delivered, as its detail keeps it."""
    files = run.detail.get("deliverables")
    if not isinstance(files, list):
        return None
    # Only ever a key of this run, in this workspace.
    key = deliverable_key(run.workspace_id, run.id, fmt)
    for one in files:
        if isinstance(one, dict) and one.get("format") == fmt and one.get("key") == key:
            return one
    return None


def read_deliverable(key: str) -> AsyncIterator[bytes]:
    return object_store().get(key)


__all__ = [
    "DECK_BUDGET",
    "FORMATS",
    "Drawn",
    "deck_messages",
    "deliverable_key",
    "deliverable_of",
    "draw",
    "file_name",
    "read_deliverable",
]
