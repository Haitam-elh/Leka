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
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.catalogue import needs_of
from leka.capabilities.changes import propose_change
from leka.capabilities.definition import Definition
from leka.capabilities.deliverables import MEDIA_TYPES, ArchitectureDeck, render
from leka.capabilities.deliverables.deck import DECK_RULES
from leka.capabilities.gateway import Gateway, Message, NoModelError, Request, Tier
from leka.capabilities.mockups import design_target, propose_design, proposes
from leka.capabilities.models import AgentRun
from leka.capabilities.runtime import filled, parameters_of
from leka.platform import ObjectStoreError, Workspace, from_bytes, object_store

logger = structlog.get_logger(__name__)

# The deck's content, at most: every slide's text.
DECK_TOKENS = 16_000
# How long drawing may take, the model's answer included.
DECK_BUDGET = 10 * 60.0
FORMATS = ("pptx", "pdf")


def deck_messages(
    definition: Definition,
    inputs: Mapping[str, object],
    analysis: str,
    *,
    organisation: str | None = None,
) -> list[Message]:
    """The deck writer's rules, then the agent's own instructions — its
    template, its parameters filled; the inputs and the analysis, as data."""
    instructions = filled(definition.instructions or "", parameters_of(inputs, organisation))
    system = f"{DECK_RULES}\n\n---\n\n{instructions}"
    material = {"inputs": dict(inputs), "analysis": analysis}
    return [
        Message.system(system),
        Message.user(json.dumps(material, ensure_ascii=False, default=str)),
    ]


async def organisation_of(session: AsyncSession, workspace_id: uuid.UUID) -> str | None:
    """The organisation an agent works for, by default: its workspace's name."""
    name = await session.scalar(select(Workspace.name).where(Workspace.id == workspace_id))
    return str(name) if name else None


def _cleaned(value: Any, parameters: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return filled(value, parameters) if "{{" in value else value
    if isinstance(value, list):
        return [_cleaned(v, parameters) for v in value]
    if isinstance(value, dict):
        return {k: _cleaned(v, parameters) for k, v in value.items()}
    return value


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
    # What the provider said, when it refused: a person reads why.
    refusal: str | None = None

    def detail(self) -> dict[str, Any]:
        if self.error is not None:
            return {
                "deliverables_error": self.error,
                **({"deliverables_said": self.refusal} if self.refusal else {}),
            }
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
    formats: Sequence[str] | None = None,
    read: Mapping[str, str] | None = None,
) -> Drawn:
    """The deck of a run's analysis, drawn and kept — or, for a code-change
    agent, the change it proposes (changes.py); for the designer, the screen
    its review proposes, before and after (mockups.py) — or why not."""
    if definition.renders == "design_mockups":
        if not proposes(analysis):
            return Drawn([], step="design_none", kept={})
        designed = await propose_design(session, run, definition, analysis, read or {})
        if designed.kept is None:
            return Drawn(
                [], designed.error or "error", step="render_failed", refusal=designed.refusal
            )
        return Drawn([], usage=designed.usage, step="designed", kept=designed.kept)
    if definition.renders == "code_change":
        proposed = await propose_change(
            session,
            run,
            definition,
            analysis,
            read=read or {},
            target=await design_target(session, run),
        )
        if proposed.change is None:
            return Drawn(
                [],
                proposed.error or "no_change",
                step="render_failed",
                refusal=(
                    proposed.said or ", ".join(f"{s['path']}: {s['why']}" for s in proposed.skipped)
                )[:300]
                or None,
            )
        change = proposed.change
        return Drawn(
            [],
            usage=proposed.usage,
            step="proposed",
            kept={
                "code_change": str(change.id),
                "repository": change.repository,
                "files": len(change.files),
                **({"skipped": proposed.skipped} if proposed.skipped else {}),
            },
        )
    request = Request(
        purpose=f"agent:{definition.key}:deck"[:100],
        messages=deck_messages(
            definition,
            run.inputs,
            analysis,
            organisation=await organisation_of(session, run.workspace_id),
        ),
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
        # "none": no model this workspace reaches can write it; otherwise the
        # models were asked and none gave a deck — said with the last answer,
        # never as "no model" when one refused (a 400 hid that once).
        said = next((a.error for a in reversed(error.attempts) if a.error), None)
        logger.warning("deck_not_written", run=str(run.id), reason=error.reason, said=said)
        code = "no_model" if error.reason == "none" else error.reason
        return Drawn([], code, refusal=said[:300] if said else None)
    except TimeoutError:
        return Drawn([], "timeout")
    except Exception:
        # Whatever else: the run's analysis stands, said why its files are not.
        logger.exception("deck_not_written", run=str(run.id))
        return Drawn([], "error")
    # Any parameter the model copied as written, filled (2026-10-23).
    parameters = parameters_of(run.inputs, await organisation_of(session, run.workspace_id))
    deck = ArchitectureDeck.model_validate(_cleaned(answered.value.model_dump(), parameters))
    try:
        rendered = await asyncio.to_thread(render, deck)
    except Exception:
        logger.exception("deck_not_drawn", run=str(run.id))
        return Drawn([], "render")
    store = object_store()
    files: list[dict[str, Any]] = []
    try:
        for fmt in [f for f in FORMATS if formats is None or f in formats]:
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
    # Only ever a key of this run, in this workspace: its deck's, or its
    # dossier's (dossier.py).
    keys = {
        deliverable_key(run.workspace_id, run.id, fmt),
        f"{run.workspace_id}/agent-runs/{run.id}/dossier.{fmt}",
    }
    for one in files:
        if isinstance(one, dict) and one.get("format") == fmt and one.get("key") in keys:
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
