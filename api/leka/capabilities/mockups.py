"""The screens the designer proposes, drawn (`renders: design_mockups`).

    the run's review     markdown, from the code it read (list_files,
                         read_file — code_tools.py) and its method's guides;
                         a proposal opened by MARK when it proposes a design
        ──▶ the model again, no tools, one mock-up at a time (2026-10-18:
            asked all at once, the answer outgrew its tokens and the review
            came alone, said nothing):
              the plan — the screen, one to three directions, the one
              recommended and why — without a line of HTML;
              the screen today, drawn — its CSS and its body;
              each direction, drawn from today's mock-up, at once;
            from the review and the files the run read, nothing else
            (deliverables/design.py). A direction not drawn leaves the
            others; today not drawn, or none, is said why
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
import base64
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.catalogue import needs_of
from leka.capabilities.definition import Definition
from leka.capabilities.deliverables.design import (
    MIME,
    MOST_ASSET_BYTES,
    DesignDirection,
    DesignPlan,
    DesignProposal,
    MockupDrawing,
    assembled,
    asset_paths,
    candidates,
    cleaned,
    corrected,
    design_key,
    summary,
    unchanged,
    unstyled,
    with_assets,
    without_assets,
)
from leka.capabilities.gateway import Gateway, Message, NoModelError, Request, Tier
from leka.capabilities.models import AgentRun
from leka.db import session_factory
from leka.platform import ObjectStoreError, from_bytes, object_store

logger = structlog.get_logger(__name__)

# The line that opens a review's proposal: what asks LEKA to draw it.
MARK = "<!-- leka-design -->"
# Each answer's room, thinking included — held to what each model gives back.
PLAN_TOKENS = 16_000
DRAW_TOKENS = 48_000
# Each step's time: the plan, then today, then the directions at once —
# within the half hour after which a running run is said abandoned.
PLAN_BUDGET = 3 * 60.0
DRAW_BUDGET = 5 * 60.0
DESIGN_BUDGET = PLAN_BUDGET + 2 * DRAW_BUDGET
# A gateway's reason for no answer, as the design's error.
NO_MODEL = {"none": "no_model", "timeout": "timeout", "limited": "limited", "blocked": "refused"}
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

PLAN_RULES = """You are LEKA's mock-up planner for the agent whose \
instructions follow. From its review and the source files it read — and from \
nothing else — plan the screens its proposal draws, as one JSON object, \
without a line of HTML:
- screen: the screen's name and its route — the page the request names, \
found by its route and its navigation entry, never a component of another \
page carrying the same words; viewport: "desktop", or "mobile" when the \
review proposes for a phone.
- directions: the proposals the review makes — one to three, in its order, \
each its name, its axis, when it is the right choice, what it costs, and \
changes: what it changes on the screen, element by element, with the values \
(sizes, colours, spacing, order, texts) — what a drawer needs to draw it. \
Asked for a new design or a redesign, each direction changes what is SEEN — \
layout, hierarchy, density, what comes first — never only a value: one that \
leaves the screen looking as it is today is no direction.
- recommended: the index of the direction the review recommends; why: in one \
or two sentences.
- changes: the recommended direction's main changes — where (file and line), \
before, after, why — as the review states them.
Answer with the JSON object only."""

DRAW_RULES = """You are LEKA's mock-up drawer for the agent whose \
instructions follow. Draw ONE screen, as one JSON object {"css": …, "body": …}: \
css, its complete style sheet; body, the HTML inside <body>. No script, no \
event handler, no external resource — no <link>, no @import, no url() but \
data: —, no link that leads anywhere: icons are inline SVG, images are CSS \
shapes or inline SVG, fonts are named with a system fallback. What the code \
takes from data when it runs — a name, a count, a date — is a plausible \
example shaped like the code's types. Self-contained, laid out for the \
viewport's width, at most 40 000 characters of body, in the language the \
screen speaks, as finished as a real product screen. An image the code shows \
from the repository — its logo above all, an icon file, an illustration — is \
never redrawn by hand: write <img data-asset="…" alt="…" width="…" \
height="…"> with its path as the code gives it (src="/brand/leka-wordmark.png" \
gives data-asset="/brand/leka-wordmark.png"); LEKA puts the real image there.
Answer with the JSON object only."""

CORRECT = """Correct the mock-up given in `mockup` as asked in `correction` — that \
and nothing else: everything not asked stays exactly as it is, the same \
structure, texts, example data and styles. An image from the repository keeps \
its <img data-asset="…">; asked about one (a logo), use the path the code \
gives."""

TODAY = """Draw the screen as its code draws it TODAY: its structure from top to \
bottom, its texts as the code and its dictionaries write them, its colours, \
sizes, spacing, radii, shadows and fonts as its style sheets and tokens give \
them, by their values. Faithful, not improved: its flaws are what the \
directions answer."""

PROPOSED = """Draw the direction named in `direction`, starting from `today` — the \
screen as it is drawn now: the same content, the same example data, no \
feature, figure or text the code does not have — redrawn as the direction \
changes it: every change it lists, visibly. Never `today` given back. It \
meets the method's bar: one primary action, a clear hierarchy, the \
repository's tokens extended and never a parallel palette, \
every pressable element with press feedback (:active { transform: \
scale(0.97) } with transition: transform 160ms cubic-bezier(0.23, 1, 0.32, \
1)), hover only inside @media (hover: hover) and (pointer: fine), entrances \
eased out under 300 ms and never from scale(0), @media \
(prefers-reduced-motion: reduce) honoured."""

# A review's proposal, said by its heading when the mark was left out.
_PROPOSAL = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*)?(?:\d+\.\s*)?\**\s*(?:la proposition|les directions de design)\b",
    re.IGNORECASE | re.MULTILINE,
)


class _NotDrawnError(Exception):
    def __init__(self, code: str, said: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.said = said


def proposes(analysis: str) -> bool:
    """Whether a review proposes a design to draw: its mark — or, the mark
    left out, its section « La proposition » (2026-10-18: a review with
    its whole proposal drew nothing, its mark forgotten)."""
    return MARK in analysis or bool(_PROPOSAL.search(analysis))


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


def checked[T: BaseModel](
    model: type[T], also: Callable[[T], list[str]] | None
) -> Callable[[T], list[str]] | None:
    """What a drawing is held to: its style (2026-10-21), and what the step
    adds — a direction never drawn as today (2026-10-22)."""
    if model is not MockupDrawing and also is None:
        return None

    def problems(value: T) -> list[str]:
        said = unstyled(value) if isinstance(value, MockupDrawing) else []
        return [*said, *(also(value) if also is not None else [])]

    return problems


async def _asked[T: BaseModel](
    session: AsyncSession | None,
    run: AgentRun,
    definition: Definition,
    purpose: str,
    rules: str,
    material: dict[str, object],
    model: type[T],
    *,
    tokens: int,
    budget: float,
    usage: dict[str, Any],
    also: Callable[[T], list[str]] | None = None,
) -> T:
    """One answer of the shape asked — in `session`, or in its own when
    drawn alongside others — its tokens counted; else _NotDrawnError, said why.
    `also`: what else makes it not what was asked, said to the model."""
    request = Request(
        purpose=f"agent:{definition.key}:{purpose}"[:100],
        messages=[
            Message.system(f"{rules}\n\n---\n\n{definition.instructions or ''}"),
            Message.user(json.dumps(material, ensure_ascii=False, default=str)),
        ],
        tier=Tier.DEEP,
        max_tokens=tokens,
        ref=f"agent_run:{run.id}",
    )
    needs = replace(needs_of(definition), tools=False)

    async def ask(own: AsyncSession) -> T:
        answered = await asyncio.wait_for(
            Gateway(own, run.workspace_id).structured(
                request,
                model,
                needs,
                # A screen drawn bare is drawn again, told why — then by the
                # next model (2026-10-21).
                verify=checked(model, also),
            ),
            timeout=budget,
        )
        done = answered.completion
        usage["provider"], usage["model"] = done.provider, done.model
        usage["tokens_in"] = int(usage.get("tokens_in", 0)) + done.usage.tokens_in
        usage["tokens_out"] = int(usage.get("tokens_out", 0)) + done.usage.tokens_out
        return answered.value

    try:
        if session is not None:
            return await ask(session)
        async with session_factory() as own:
            try:
                return await ask(own)
            finally:
                await own.commit()
    except NoModelError as error:
        said = next((a.error for a in reversed(error.attempts) if a.error), None)
        logger.warning("design_not_drawn", run=str(run.id), step=purpose, reason=error.reason)
        raise _NotDrawnError(NO_MODEL.get(error.reason, "unanswered"), said) from error
    except TimeoutError as error:
        raise _NotDrawnError("timeout") from error
    except Exception as error:
        logger.exception("design_not_drawn", run=str(run.id), step=purpose)
        raise _NotDrawnError("error") from error


async def propose_design(
    session: AsyncSession,
    run: AgentRun,
    definition: Definition,
    analysis: str,
    files: Mapping[str, str],
    *,
    budget: float = DESIGN_BUDGET,
) -> Designed:
    """The screen a run's review proposes, drawn before and after, kept: its
    plan, then today, then each direction at once — each answer on its own."""
    usage: dict[str, Any] = {}
    material: dict[str, object] = {
        "inputs": dict(run.inputs or {}),
        "review": without_mark(analysis),
        "files": read_files(files),
    }
    plan_budget = min(PLAN_BUDGET, budget)
    draw_budget = min(DRAW_BUDGET, budget)
    try:
        plan = await _asked(
            session,
            run,
            definition,
            "design-plan",
            PLAN_RULES,
            material,
            DesignPlan,
            tokens=PLAN_TOKENS,
            budget=plan_budget,
            usage=usage,
        )
    except _NotDrawnError as failed:
        return Designed(None, failed.code, usage, _said("plan", failed.said))
    planned = {**material, "screen": plan.screen, "viewport": plan.viewport}
    try:
        today = await _asked(
            session,
            run,
            definition,
            "design-today",
            f"{DRAW_RULES}\n\n{TODAY}",
            planned,
            MockupDrawing,
            tokens=DRAW_TOKENS,
            budget=draw_budget,
            usage=usage,
        )
    except _NotDrawnError as failed:
        return Designed(None, failed.code, usage, _said("aujourd'hui", failed.said))
    # Nothing held while the directions are drawn, each in its own session.
    await session.commit()

    async def direction(each: DesignDirection) -> MockupDrawing:
        return await _asked(
            None,
            run,
            definition,
            "design-direction",
            f"{DRAW_RULES}\n\n{PROPOSED}",
            {**planned, "today": today.model_dump(), "direction": each.model_dump()},
            MockupDrawing,
            tokens=DRAW_TOKENS,
            budget=draw_budget,
            usage=usage,
            also=lambda drawn: unchanged(today, drawn, each),
        )

    results = await asyncio.gather(
        *(direction(each) for each in plan.directions), return_exceptions=True
    )
    drawn = [
        (each, result)
        for each, result in zip(plan.directions, results, strict=True)
        if isinstance(result, MockupDrawing)
    ]
    if not drawn:
        first = next((r for r in results if isinstance(r, _NotDrawnError)), _NotDrawnError("error"))
        return Designed(None, first.code, usage, _said("propositions", first.said))
    proposal = cleaned(assembled(plan, today, drawn))
    proposal = with_assets(proposal, await _assets(session, run, analysis, asset_paths(proposal)))
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
    kept = summary(proposal, key)
    missing = [
        each.name
        for each, result in zip(plan.directions, results, strict=True)
        if not isinstance(result, MockupDrawing)
    ]
    if missing:
        kept["missing"] = missing
    return Designed({"design": kept}, usage=usage)


async def _assets(
    session: AsyncSession, run: AgentRun, analysis: str, paths: list[str]
) -> dict[str, str]:
    """Each image a mock-up names from the repository, as a data: URI — read
    on its default branch, where the code names it or under its public
    folder; one not found, or too heavy, left out."""
    if not paths:
        return {}
    # Here, not at the top: changes.py reads the catalogue, which reads the
    # registry, which reads the code tools' names.
    from leka.capabilities.changes import code_of
    from leka.connectors import CodeRefusedError

    found = await code_of(session, run, analysis)
    if found is None:
        return {}
    code, repository, base = found
    assets: dict[str, str] = {}
    for path in paths:
        mime = MIME.get(path.split("?")[0].rsplit(".", 1)[-1].lower())
        if mime is None:
            continue
        for candidate in candidates(path):
            try:
                data = await code.read_bytes(repository, candidate, base, most=MOST_ASSET_BYTES)
            except CodeRefusedError:
                data = None
            if data:
                assets[path] = f"data:{mime};base64,{base64.b64encode(data).decode()}"
                break
    return assets


async def correct_design(
    session: AsyncSession,
    run: AgentRun,
    definition: Definition,
    analysis: str,
    files: Mapping[str, str],
    target: str,
    note: str,
) -> Designed:
    """One mock-up — today's (`before`) or a direction (its index) — drawn
    again as a person asked, the rest as it was (2026-10-19, Karim: « il
    faudrait qu'on puisse lui demander de corriger certaines parties de
    l'écran depuis la proposition »)."""
    kept = await read_design(run)
    if kept is None:
        return Designed(None, "not_drawn")
    if target != "before" and not (target.isdigit() and int(target) < len(kept.after)):
        return Designed(None, "not_found")
    mockup = kept.before if target == "before" else kept.after[int(target)]
    usage: dict[str, Any] = {}
    material: dict[str, object] = {
        "inputs": dict(run.inputs or {}),
        "review": without_mark(analysis),
        "files": read_files(files),
        "screen": kept.screen,
        "viewport": kept.viewport,
        "mockup": {"name": mockup.name, "css": mockup.css, "body": without_assets(mockup.body)},
        "correction": note,
    }
    if target != "before":
        material["today"] = {"css": kept.before.css, "body": without_assets(kept.before.body)}
    try:
        drawing = await _asked(
            session,
            run,
            definition,
            "design-correction",
            f"{DRAW_RULES}\n\n{CORRECT}",
            material,
            MockupDrawing,
            tokens=DRAW_TOKENS,
            budget=DRAW_BUDGET,
            usage=usage,
        )
    except _NotDrawnError as failed:
        return Designed(None, failed.code, usage, _said("correction", failed.said))
    proposal = cleaned(corrected(kept, target, drawing))
    proposal = with_assets(proposal, await _assets(session, run, analysis, asset_paths(proposal)))
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


def _said(step: str, said: str | None) -> str:
    """Which step did not draw, and what its model's provider said."""
    return f"{step} : {said}"[:300] if said else step


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
    "DRAW_RULES",
    "MARK",
    "PLAN_RULES",
    "Designed",
    "correct_design",
    "design_messages",
    "propose_design",
    "proposes",
    "read_design",
    "read_files",
    "without_mark",
]
