"""What LEKA proposes to get an intention done: the agents its work needs
and the plan, step by step — proposed with its result, never started
(2026-10-14, the product call: « l'agent est choisi et lancé
automatiquement, sans que l'utilisateur le voie ni le valide »). A person
launches them at the Décision step, or does it themselves with the plan in
hand (agents.py).

    the request, every agent      a model: which agents — three at most —
    of the catalogue              their inputs from the request's words,
            │                     why each, the files the request asks
            ▼                     for; the plan in steps, each with the
                                  agent that would do it; whether it only
                                  asks to know
    checked     each agent one offered; its inputs exactly its contract's,
                what a required one lacks said (`missing`), never invented
    said        each with what it delivers, what a run of it has cost here,
                whether it can run here and why not
    no model    the catalogue's own discovery (goal, kind, words) and a
                plan by goal

An agent that cannot run here is proposed all the same when it is the one
the work needs: what it takes is said, never hidden.
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import (
    CatalogueService,
    Kind,
    LLMRuntime,
    Needs,
    Task,
    Tier,
    permitted,
)
from leka.capabilities.definition import Query, discover
from leka.capabilities.runtime import DRAWN
from leka.intentions.models import Intention
from leka.intentions.schemas import (
    AgentFieldRead,
    AgentProposalRead,
    PlanStepRead,
    ProposedAgentRead,
    Understanding,
)

logger = structlog.get_logger(__name__)

PURPOSE = "intention.proposal"
NEEDS = Needs(structured=True)
MOST_AGENTS = 3
# What a person may choose to have drawn — the rest of what an agent
# delivers (its report, a code change) always comes.
CHOSEN = frozenset({"pdf", "pptx"})

RULES = """You plan how a person's request gets done with LEKA's agents. \
You are given the request and LEKA's agents: what each delivers, the \
inputs it takes, whether it can run here.

- agents: the agents whose work the request needs, the most useful first, \
three at most. None when no agent's work fits: a plain question is \
answered by LEKA's own analysis. A request to build, develop, change, test, \
review, document, investigate, secure or draw needs the agent that does it \
— developing a feature needs the code change, its tests and its review. \
Choose an agent that cannot run here too when it is the one the work \
needs: the person is told what it takes.
- inputs: each agent's, from the request's own words — « le parcours De \
l'intention à l'action » is the parcours. Never invent a value the request \
does not say or plainly imply. A boolean is true only when asked. A \
required input the request does not give goes in `missing`.
- formats: the files the request asks for, among the agent's formats \
(« il me faut un PDF » is pdf); none when it asks for none.
- why: one sentence, in the request's language, why this agent helps here.
- steps: the plan to get it done, three to eight concrete steps in order, \
in the request's language — each a short title and one sentence of \
detail; `agent` is the key of the agent that would do it, none when the \
person does it. A migration: what moves and what depends on it, the \
target provisioned, data and backups moved, services deployed, the DNS TTL \
lowered then traffic switched, checked, the old one retired.
- informative: true when the request only asks to know something — who, \
what, why, where — and nothing is to be produced or changed.
Answer with the JSON object only."""


class Chosen(BaseModel):
    """An agent, as the model proposes it."""

    key: str
    inputs: dict[str, str | bool] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list, max_length=10)
    why: str = Field(default="", max_length=400)
    formats: list[str] = Field(default_factory=list, max_length=5)


class Step(BaseModel):
    title: str = Field(max_length=200)
    detail: str = Field(default="", max_length=600)
    agent: str | None = None


class Proposed(BaseModel):
    """What the model says."""

    agents: list[Chosen] = Field(default_factory=list, max_length=MOST_AGENTS)
    steps: list[Step] = Field(default_factory=list, max_length=10)
    informative: bool = False


def deliverables_of(definition: Any) -> list[str]:
    """What a run of it delivers: its report, then what LEKA draws of it."""
    drawn = DRAWN.get(definition.renders or "", ())
    return ["report", *drawn]


def offered(entry: Any) -> dict[str, Any]:
    """An agent as the model is shown it."""
    d = entry.definition
    return {
        "key": d.key,
        "title": d.title,
        "delivers": d.summary,
        "formats": sorted(CHOSEN & set(deliverables_of(d))),
        "examples": list(d.examples)[:3],
        "can_run_here": entry.availability.available,
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


def inputs_of(entry: Any, said: Mapping[str, object]) -> tuple[dict[str, object], list[str]]:
    """Its inputs exactly as its contract takes them, and the required ones
    the request does not give."""
    contract = entry.definition.contract
    names = {i.name: i for i in contract.inputs}
    inputs: dict[str, object] = {}
    for name, value in said.items():
        field = names.get(name)
        if field is None:
            continue
        if field.type == "boolean":
            inputs[name] = value is True or str(value).strip().lower() in {"true", "oui", "yes"}
        elif isinstance(value, str) and value.strip():
            if field.type == "choice" and value.strip() not in field.choices:
                continue
            inputs[name] = value.strip()[:500]
    missing = [i.name for i in contract.inputs if i.required and i.name not in inputs]
    return inputs, missing


def asked_formats(text: str, deliverables: Collection[str]) -> list[str]:
    """The files the words ask for, among those it draws."""
    words = text.lower()
    found = []
    if "pdf" in deliverables and "pdf" in words:
        found.append("pdf")
    if "pptx" in deliverables and any(
        w in words for w in ("powerpoint", "pptx", "ppt", "deck", "présentation", "presentation")
    ):
        found.append("pptx")
    return found


def agent_read(
    entry: Any,
    *,
    why: str,
    said_inputs: Mapping[str, object],
    formats: Sequence[str],
    cost: float | None,
) -> ProposedAgentRead:
    d = entry.definition
    inputs, missing = inputs_of(entry, said_inputs)
    deliverables = deliverables_of(d)
    return ProposedAgentRead(
        key=d.key,
        title=d.title,
        summary=d.summary,
        category=d.category,
        why=why.strip(),
        deliverables=deliverables,
        asked=[f for f in formats if f in CHOSEN and f in deliverables],
        inputs={k: v for k, v in inputs.items() if isinstance(v, str | bool)},
        missing=missing,
        fields=[
            AgentFieldRead(
                name=i.name,
                type=i.type,
                required=i.required,
                description=i.description,
                choices=list(i.choices),
            )
            for i in d.contract.inputs
        ],
        credits=cost,
        available=entry.availability.available,
        reasons=list(entry.availability.codes),
    )


# The plan when no model writes one, by what is wanted — the language the
# answer is written in, French unless said otherwise.
PLANS: Mapping[str, Mapping[str, tuple[tuple[str, str], ...]]] = {
    "plan_migration": {
        "fr": (
            ("Inventorier ce qui migre", "Les serveurs, services et données, et ce qui en dépend."),
            ("Provisionner la cible", "Les comptes, réseaux et ressources de destination."),
            ("Migrer les données et les sauvegardes", "Copiées, puis vérifiées sur la cible."),
            ("Déployer les services sur la cible", "Configurés comme à la source, testés."),
            ("Basculer le trafic", "Le TTL DNS abaissé d'abord, puis la bascule."),
            ("Vérifier, puis retirer l'ancien", "Une fois la cible stable, la source arrêtée."),
        ),
        "en": (
            ("Inventory what moves", "Servers, services and data, and what depends on them."),
            ("Provision the target", "The destination's accounts, networks and resources."),
            ("Move data and backups", "Copied, then checked on the target."),
            ("Deploy the services on the target", "Configured as at the source, tested."),
            ("Switch traffic", "The DNS TTL lowered first, then the switch."),
            ("Check, then retire the old one", "Once the target is stable, the source stopped."),
        ),
    },
    "explain_cause": {
        "fr": (
            ("Rassembler ce qui a changé", "Déploiements, changements et incidents récents."),
            ("Isoler la cause probable", "Ce qui a changé juste avant, ce dont il dépend."),
            ("Corriger ou contourner", "La correction proposée, validée par une personne."),
            ("Vérifier", "Le problème a disparu, rien d'autre n'a bougé."),
        ),
        "en": (
            ("Gather what changed", "Recent deployments, changes and incidents."),
            ("Isolate the probable cause", "What changed just before, what it depends on."),
            ("Fix or work around", "The fix proposed, approved by a person."),
            ("Check", "The problem is gone, nothing else moved."),
        ),
    },
}
GENERIC: Mapping[str, tuple[tuple[str, str], ...]] = {
    "fr": (
        ("Lire ce que LEKA a trouvé", "La réponse et ses preuves, ci-dessus."),
        ("Faire le travail", "Avec les agents proposés, ou vous-même avec ce plan."),
        ("Vérifier le résultat", "Ce qui a été produit ou changé, relu par une personne."),
    ),
    "en": (
        ("Read what LEKA found", "The answer and its evidence, above."),
        ("Do the work", "With the agents proposed, or yourself with this plan."),
        ("Check the result", "What was produced or changed, read by a person."),
    ),
}
INFORMATIVE = frozenset(
    {"find_owner", "find_change", "find_knowledge", "map_dependencies", "check_compliance"}
)


def _plain(words: str) -> str:
    """« Architecte applicatif » → « architecte-applicatif »: as the new
    home's chips write an agent's name (web/components/v2/home.tsx)."""
    bare = "".join(c for c in unicodedata.normalize("NFD", words) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", bare.lower()).strip("-")


def named(text: str, entries: Sequence[Any]) -> str | None:
    """The agent a request names first, by its « /mot » (2026-10-14: a chip
    of the new home puts « /architecte » first in the bar) — its first word,
    its whole name or its key. One agent, or none: a word two agents share
    names neither."""
    found = re.match(r"\s*/(\S+)", text)
    if found is None:
        return None
    word = found.group(1).lower()
    keys = [
        e.definition.key
        for e in entries
        if word
        in (
            _plain(e.definition.title.split()[0]) if e.definition.title.split() else "",
            _plain(e.definition.title),
            e.definition.key,
        )
    ]
    return keys[0] if len(keys) == 1 else None


def plan_by_rules(goal: str, language: str | None, agents: Sequence[str]) -> list[PlanStepRead]:
    lang = "en" if (language or "fr").startswith("en") else "fr"
    steps = PLANS.get(goal, {}).get(lang) or (
        PLANS["explain_cause"][lang] if goal == "investigate" else GENERIC[lang]
    )
    planned = [PlanStepRead(title=title, detail=detail) for title, detail in steps]
    if agents and planned:
        # The work itself is the first agent's.
        middle = min(1, len(planned) - 1)
        planned[middle] = planned[middle].model_copy(update={"agent": agents[0]})
    return planned


async def propose(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    intention: Intention,
    *,
    language: str | None = None,
    now: datetime | None = None,
) -> AgentProposalRead | None:
    """The agents its work needs and the plan — None when its asker is gone."""
    asker = intention.created_by
    if asker is None:
        return None
    # Looked up when used: feasibility's own imports reach back here.
    from leka.intentions.feasibility import run_costs

    moment = now or datetime.now(UTC)
    understood = (
        Understanding.model_validate(intention.understanding) if intention.understanding else None
    )
    goal = understood.goal.code if understood is not None else "unknown"
    permissions = await permitted(session, workspace_id, asker)
    entries = [
        e
        for e in await CatalogueService(session, workspace_id).entries(
            permissions=permissions, user_id=asker
        )
        if e.definition.kind is Kind.AGENT and e.enabled
    ]
    by_key = {e.definition.key: e for e in entries}
    # Named by the person — « /architecte … »: proposed, whatever a model or
    # the catalogue would have chosen; still launched by a person only.
    asked = named(intention.text, entries)
    said: Proposed | None = None
    if entries:
        runtime = LLMRuntime(session, workspace_id)
        if await runtime.ready(NEEDS):
            done = await runtime.run(
                Task(
                    purpose=PURPOSE,
                    instructions=RULES,
                    input=json.dumps(
                        {
                            "request": intention.text,
                            "goal": goal,
                            **({"language": language} if language else {}),
                            "agents": [offered(e) for e in entries],
                        },
                        ensure_ascii=False,
                    ),
                    output=Proposed,
                    needs=NEEDS,
                    tier=Tier.FAST,
                    max_tokens=4000,
                    budget=60.0,
                    ref=f"intention:{intention.id}",
                )
            )
            if done.ok and done.value is not None:
                said = done.value
    if said is not None:
        chosen = [c for c in said.agents if c.key in by_key]
        # The one the person named comes first: as the model read it when it
        # chose it too — its inputs from the request's words — else alone.
        chosen = sorted(chosen, key=lambda c: c.key != asked)[:MOST_AGENTS]
        alone = asked is not None and asked not in {c.key for c in chosen}
        costs = await run_costs(
            session, [c.key for c in chosen] + ([asked] if alone and asked else []), now=moment
        )
        agents = [
            agent_read(
                by_key[c.key],
                why=c.why,
                said_inputs=c.inputs,
                formats=c.formats or asked_formats(intention.text, CHOSEN),
                cost=costs.get(c.key),
            )
            for c in chosen
        ]
        if alone and asked is not None:
            agents = [
                agent_read(
                    by_key[asked],
                    why="",
                    said_inputs={},
                    formats=asked_formats(intention.text, CHOSEN),
                    cost=costs.get(asked),
                ),
                *agents[: MOST_AGENTS - 1],
            ]
        keys = {a.key for a in agents}
        steps = [
            PlanStepRead(
                title=s.title.strip(),
                detail=s.detail.strip(),
                agent=s.agent if s.agent in keys else None,
            )
            for s in said.steps
            if s.title.strip()
        ]
        if not steps:
            steps = plan_by_rules(goal, language, [a.key for a in agents])
        logger.info("intention_proposed", intention=str(intention.id), agents=sorted(keys))
        return AgentProposalRead(
            agents=agents,
            steps=steps,
            informative=said.informative and asked is None,
            by="model",
        )
    # No model, or nothing usable from it: the catalogue's own discovery.
    found = discover(
        [e.definition for e in entries],
        Query(
            goal=goal if goal != "unknown" else None,
            kind=understood.kind if understood is not None else None,
            text=intention.text,
        ),
        {e.definition.key: e.availability for e in entries},
    )
    picked = [m.definition.key for m in found if m.score >= 3][:1]
    if asked is not None:
        picked = [asked, *(key for key in picked if key != asked)]
    costs = await run_costs(session, picked, now=moment)
    agents = [
        agent_read(
            by_key[key],
            why="",
            said_inputs={},
            formats=asked_formats(intention.text, CHOSEN),
            cost=costs.get(key),
        )
        for key in picked
    ]
    return AgentProposalRead(
        agents=agents,
        steps=plan_by_rules(goal, language, picked),
        informative=goal in INFORMATIVE and not agents,
        by="rules",
    )


def proposed_said(proposal: AgentProposalRead) -> dict[str, object]:
    """What the answer's writer is told LEKA proposes: never at work yet."""
    return {
        "agents": [
            {
                "title": a.title,
                "delivers": [d for d in a.deliverables if d != "report"] or ["report"],
                "can_run_here": a.available,
            }
            for a in proposal.agents
        ],
        "steps": [s.title for s in proposal.steps],
    }
