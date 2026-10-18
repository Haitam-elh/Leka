"""The screens the designer proposes, drawn (`renders: design_mockups`).

    the run's review     markdown, from the code it read (list_files,
                         read_file — code_tools.py) and its method's guides;
                         a proposal opened by MARK when it proposes a design
        ──▶ the model again, no tools: the screen today and one to three
            proposals, each a mock-up — its CSS and its body —, the one
            recommended and why (deliverables/design.py); from the review and
            the files the run read, nothing else
        ──▶ cleaned — nothing run, nothing fetched —, kept:
            {workspace}/agent-runs/{run}/design.json, erased with the
            workspace
    GET /agent-runs/{id}/design — each mock-up as the page the screen shows,
    side by side, before and after.

What fails here never fails the run: its review stands, said why no mock-up
is (`deliverables_error`). A review that proposes no design — of animations
alone, of one pull request — draws nothing, and is not asked to.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.catalogue import needs_of
from leka.capabilities.definition import Definition
from leka.capabilities.deliverables.design import DesignProposal, cleaned, design_key, summary
from leka.capabilities.gateway import Gateway, Message, NoModelError, Request, Tier
from leka.capabilities.models import AgentRun
from leka.platform import ObjectStoreError, from_bytes, object_store

logger = structlog.get_logger(__name__)

# The line that opens a review's proposal: what asks LEKA to draw it.
MARK = "<!-- leka-design -->"
DESIGN_TOKENS = 24_000
DESIGN_BUDGET = 8 * 60.0
# The source the writer is given, at most: per file, and in all.
MOST_FILE = 40_000
MOST_FILES = 160_000

DESIGN_RULES = """You are LEKA's mock-up writer for the agent whose \
instructions follow. From its review and from the source files it read — and \
from nothing else — draw the screen its proposal is about, as one JSON object:
- screen: the screen's name; viewport: "desktop", or "mobile" when the \
review proposes for a phone.
- before: the screen as its code draws it today — its structure from top to \
bottom, its texts as the code and its dictionaries write them, its colours, \
sizes, spacing, radii, shadows and fonts as its style sheets and tokens give \
them, by their values: the page holds no design system of its own. Faithful, \
not improved: its flaws are what the proposals answer.
- after: the proposals the review makes — one to three, each a direction on \
its named axis (axis), with when it is the right choice (when) and what it \
costs (cost). The same content as before — no feature, figure or text the \
code does not have — redrawn as the review proposes. Each meets the method's \
bar: one primary action, a clear hierarchy, the repository's tokens extended \
and never a parallel palette, every pressable element with press feedback \
(:active { transform: scale(0.97) } with transition: transform 160ms \
cubic-bezier(0.23, 1, 0.32, 1)), hover only inside @media (hover: hover) and \
(pointer: fine), entrances eased out under 300 ms and never from scale(0), \
@media (prefers-reduced-motion: reduce) honoured.
- recommended: the index in after of the proposal the review recommends; \
why: in one or two sentences, from the product's personality and how often \
the screen is used.
- changes: the recommended proposal's main changes — where (file and line), \
before, after, why — as the review states them.
Each mock-up is two strings: css, its complete style sheet, and body, the \
HTML inside <body>. No script, no event handler, no external resource — no \
<link>, no @import, no url() but data: —, no link that leads anywhere: icons \
are inline SVG, images are CSS shapes or inline SVG, fonts are named with a \
system fallback. What the code takes from data when it runs — a name, a \
count, a date — is a plausible example shaped like the code's types, the \
same in before and in every proposal. Self-contained, laid out for the \
viewport's width, at most 40 000 characters of body each, in the language \
the screen speaks.
Answer with the JSON object only."""


def proposes(analysis: str) -> bool:
    """Whether a review proposes a design to draw."""
    return MARK in analysis


def without_mark(report: str) -> str:
    """The review a person reads: the mark is for LEKA."""
    return report.replace(MARK, "")


def read_files(files: Mapping[str, str]) -> dict[str, str]:
    """What the writer is given of the files the run read: each cut, all of
    them within MOST_FILES — the first read first, as the review cites them."""
    given: dict[str, str] = {}
    left = MOST_FILES
    for path, text in files.items():
        if left <= 0:
            break
        cut = text[: min(MOST_FILE, left)]
        given[path] = cut
        left -= len(cut)
    return given


def design_messages(
    definition: Definition,
    inputs: Mapping[str, object],
    analysis: str,
    files: Mapping[str, str],
) -> list[Message]:
    """The writer's rules, then the agent's own instructions — its method;
    the inputs, the review and the source it read, as data."""
    system = f"{DESIGN_RULES}\n\n---\n\n{definition.instructions or ''}"
    material = {
        "inputs": dict(inputs),
        "review": without_mark(analysis),
        "files": read_files(files),
    }
    return [
        Message.system(system),
        Message.user(json.dumps(material, ensure_ascii=False, default=str)),
    ]


@dataclass(frozen=True)
class Designed:
    """What a run's proposal came to: where it is kept and what it holds — or
    why not."""

    kept: dict[str, Any] | None
    error: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    refusal: str | None = None


async def propose_design(
    session: AsyncSession,
    run: AgentRun,
    definition: Definition,
    analysis: str,
    files: Mapping[str, str],
    *,
    budget: float = DESIGN_BUDGET,
) -> Designed:
    """The screen a run's review proposes, drawn before and after, kept."""
    request = Request(
        purpose=f"agent:{definition.key}:design"[:100],
        messages=design_messages(definition, run.inputs, analysis, files),
        tier=Tier.DEEP,
        max_tokens=DESIGN_TOKENS,
        ref=f"agent_run:{run.id}",
    )
    try:
        answered = await asyncio.wait_for(
            Gateway(session, run.workspace_id).structured(
                request, DesignProposal, replace(needs_of(definition), tools=False)
            ),
            timeout=budget,
        )
    except NoModelError as error:
        said = next((a.error for a in reversed(error.attempts) if a.error), None)
        logger.warning("design_not_drawn", run=str(run.id), reason=error.reason, said=said)
        code = "no_model" if error.reason == "none" else error.reason
        return Designed(None, code, refusal=said[:300] if said else None)
    except TimeoutError:
        return Designed(None, "timeout")
    except Exception:
        # Whatever else: the run's review stands, said why no mock-up is.
        logger.exception("design_not_drawn", run=str(run.id))
        return Designed(None, "error")
    proposal = cleaned(answered.value)
    done = answered.completion
    usage = {
        "provider": done.provider,
        "model": done.model,
        "tokens_in": done.usage.tokens_in,
        "tokens_out": done.usage.tokens_out,
    }
    key = design_key(run.workspace_id, run.id)
    try:
        await object_store().put(
            key,
            from_bytes(proposal.model_dump_json().encode()),
            content_type="application/json",
        )
    except ObjectStoreError:
        logger.exception("design_not_kept", run=str(run.id))
        return Designed(None, "storage", usage)
    return Designed({"design": summary(proposal, key)}, usage=usage)


async def read_design(run: AgentRun) -> DesignProposal | None:
    """The proposal a run drew, as kept — None when it drew none, or it is no
    longer kept. Only ever this run's key, in its workspace."""
    kept = run.detail.get("design")
    key = design_key(run.workspace_id, run.id)
    if not isinstance(kept, Mapping) or kept.get("key") != key:
        return None
    chunks: list[bytes] = []
    try:
        async for chunk in object_store().get(key):
            chunks.append(chunk)
    except ObjectStoreError:
        return None
    return DesignProposal.model_validate_json(b"".join(chunks))


__all__ = [
    "DESIGN_BUDGET",
    "DESIGN_RULES",
    "MARK",
    "Designed",
    "design_messages",
    "propose_design",
    "proposes",
    "read_design",
    "read_files",
    "without_mark",
]
