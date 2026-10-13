"""The agent an intention is handed to — LEKA doing what was asked, not only
saying it (docs/intentions.md § 15).

A request like « Construis l'architecture du parcours X sur le périmètre Y,
il me faut un PDF » is the architect's work: the deck is what it delivers.
Matching words would miss it as often as it finds it. A language model reads
the request and the agents this person may use here — each with what it
delivers and what it takes — and says which one does the work and with what
inputs, taken from the request's own words. LEKA then starts it, for the
person who asked, as if they had launched it themselves: the same checks
(the agent usable here, their role allowed), the same approval controls,
the run kept on the intention, where its files appear.

    the request, the agents      a model: which agent, which inputs, why
            │                    (or none: LEKA's own analysis answers)
            ▼
    checked      the agent one of those offered; its inputs exactly its
                 contract's, none required missing
    started      AgentRuntime.start, as the asker, on the intention and its
                 context — held by an approval control when one covers it
    said         the analysis says the agent is at work and what it will
                 deliver; never that LEKA cannot

Once per intention: analysing it again does not start it again.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import (
    AgentRun,
    AgentRuntime,
    CatalogueService,
    Kind,
    LLMRuntime,
    Needs,
    RunRefusedError,
    Task,
    Tier,
    check_input,
    permitted,
    queue_run,
)
from leka.governance import Actor, AIControlService, ai_event, holding
from leka.intentions.models import Intention
from leka.platform import MembershipRepository

logger = structlog.get_logger(__name__)

PURPOSE = "intention.dispatch"
NEEDS = Needs(structured=True)

RULES = """You decide which of LEKA's agents does the work a person asked \
for. You are given their request and the agents they may use here, each \
with what it delivers and the inputs it takes.

- Choose an agent when the request asks for what it delivers — a deck, a \
document, a review, an investigation, a plan — even in other words than \
its description. Asking for its deliverable in a format it produces (PDF, \
PowerPoint) is asking for it.
- Choose none when no agent delivers what is asked: LEKA's own analysis \
answers then. A plain question about the company's systems is the \
analysis's.
- Its inputs come from the request's own words: « le parcours De \
l'intention à l'action » is the parcours; « sur le périmètre Plateforme \
LEKA » the périmètre. Never invent a value the request does not say or \
plainly imply. A boolean input is true only when the request asks for it.
- Give every required input you can; one you cannot, leave out and say so \
in `missing`.
Answer with the JSON object only."""


async def _short(session: AsyncSession, workspace_id: uuid.UUID, key: str) -> bool:
    """Whether this month's credits are short of what this agent has cost
    here — and LEKA's models stop once they are spent."""
    # Metering reads intentions: read here, not at import.
    from leka.intentions.feasibility import run_costs
    from leka.metering.credits import credits_now

    now = datetime.now(UTC)
    month = await credits_now(session, workspace_id, now=now)
    if not month.enforced:
        return False
    cost = (await run_costs(session, [key], now=now)).get(key)
    return month.state == "exhausted" or (cost is not None and month.remaining < cost)


class Dispatched(BaseModel):
    """What the model says."""

    agent: str | None = Field(default=None, description="The agent's key, or none.")
    inputs: dict[str, str | bool] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list, max_length=10)
    why: str = Field(default="", max_length=400)


@dataclass(frozen=True)
class Handed:
    """What became of it: an agent started (`run_id`), or why not."""

    agent: str | None
    run_id: uuid.UUID | None = None
    title: str | None = None
    deliverables: tuple[str, ...] = ()
    inputs: Mapping[str, object] | None = None
    held: bool = False
    why: str | None = None

    def said(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "run_id": str(self.run_id) if self.run_id else None,
            "title": self.title,
            "deliverables": list(self.deliverables),
            "inputs": dict(self.inputs or {}),
            "held": self.held,
            "why": self.why,
        }


def offered(agent: Any) -> dict[str, Any]:
    """An agent as the model is shown it."""
    d = agent.definition
    return {
        "key": d.key,
        "title": d.title,
        "delivers": d.summary,
        "formats": list(d.contract.formats),
        "examples": list(d.examples)[:3],
        "inputs": [
            {
                "name": i.name,
                "type": i.type,
                "required": i.required,
                "description": i.description,
                **({"choices": list(i.choices)} if i.choices else {}),
            }
            for i in d.contract.inputs
        ],
    }


def checked(said: Dispatched, agents: Sequence[Any]) -> tuple[Any, dict[str, object]] | None:
    """The agent and its inputs, exactly as its contract takes them — or
    None: an agent not offered, or a required input missing."""
    agent = next((a for a in agents if a.definition.key == said.agent), None)
    if agent is None:
        return None
    contract = agent.definition.contract
    names = {i.name: i for i in contract.inputs}
    inputs: dict[str, object] = {}
    for name, value in said.inputs.items():
        field = names.get(name)
        if field is None:
            continue
        if field.type == "boolean":
            inputs[name] = value is True or str(value).strip().lower() in {"true", "oui", "yes"}
        elif isinstance(value, str) and value.strip():
            inputs[name] = value.strip()[:500]
    if check_input(contract, inputs):
        return None
    return agent, inputs


async def dispatch(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    intention: Intention,
) -> Handed | None:
    """The agent this intention is handed to, started — or None when none
    does what it asks, or no model can say."""
    asker = intention.created_by
    if asker is None:
        return None
    # Once: an agent already at work on it is the one said.
    started = await session.scalar(
        select(AgentRun)
        .where(AgentRun.workspace_id == workspace_id, AgentRun.intention_id == intention.id)
        .order_by(AgentRun.created_at)
        .limit(1)
    )
    if started is not None:
        known = await CatalogueService(session, workspace_id).entry(
            started.key, permissions=await permitted(session, workspace_id, asker), user_id=asker
        )
        return Handed(
            started.key,
            run_id=started.id,
            title=known.definition.title if known else started.key,
            deliverables=tuple(known.definition.contract.formats) if known else (),
            inputs=dict(started.inputs),
            held=started.status == "held",
        )
    permissions = await permitted(session, workspace_id, asker)
    entries = await CatalogueService(session, workspace_id).entries(
        permissions=permissions, user_id=asker
    )
    agents = [
        e
        for e in entries
        if e.definition.kind is Kind.AGENT and e.availability.available and e.enabled
    ]
    if not agents:
        return None
    runtime = LLMRuntime(session, workspace_id)
    if not await runtime.ready(NEEDS):
        return None
    done = await runtime.run(
        Task(
            purpose=PURPOSE,
            instructions=RULES,
            input=json.dumps(
                {"request": intention.text, "agents": [offered(a) for a in agents]},
                ensure_ascii=False,
            ),
            output=Dispatched,
            needs=NEEDS,
            tier=Tier.FAST,
            max_tokens=3000,
            budget=60.0,
            ref=f"intention:{intention.id}",
        )
    )
    if not done.ok or done.value is None or not done.value.agent:
        return None
    said: Dispatched = done.value
    found = checked(said, agents)
    if found is None:
        logger.info(
            "intention_not_dispatched",
            intention=str(intention.id),
            agent=said.agent,
            missing=said.missing,
        )
        return Handed(said.agent, why="missing_inputs" if said.missing else "not_offered")
    agent, inputs = found
    definition = agent.definition
    if await _short(session, workspace_id, definition.key):
        # What it has cost here is more than is left, and LEKA's models stop
        # once credits are spent: never started to be stopped midway — what
        # it takes is said on the intention (LEKA-439).
        logger.info("intention_not_dispatched", intention=str(intention.id), credits="short")
        return Handed(definition.key, title=definition.title, why="credits")
    seat = await MembershipRepository(session, workspace_id).get_for_user(asker)
    actor = Actor(user_id=asker, roles=frozenset({seat.role.value})) if seat else None
    held = holding(
        await AIControlService(session, workspace_id).active(),
        definition.key,
        definition.risk,
        actor,
    )
    try:
        run = await AgentRuntime(session, workspace_id).start(
            definition.key,
            inputs,
            by=asker,
            permissions=permissions,
            intention_id=intention.id,
            context_id=intention.context_id,
            held_by=held.name if held is not None else None,
        )
    except RunRefusedError as error:
        logger.info("intention_not_dispatched", intention=str(intention.id), refused=str(error))
        return Handed(definition.key, why="refused")
    if held is not None:
        ai_event(
            session,
            workspace_id,
            held,
            "held",
            actor=actor,
            purpose=f"agent:{run.key}",
            ref=run.key,
            run_id=run.id,
            detail={"risk": definition.risk, "intention_id": str(intention.id)},
        )
    await session.commit()
    if held is None:
        await queue_run(workspace_id, run.id)
    return Handed(
        definition.key,
        run_id=run.id,
        title=definition.title,
        deliverables=tuple(definition.contract.formats),
        inputs=inputs,
        held=held is not None,
        why=said.why or None,
    )
