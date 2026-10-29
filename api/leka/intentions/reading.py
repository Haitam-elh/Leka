"""What is asked, read by a language model with LEKA's rules (LEKA-394).

    the words ──▶ understanding.py: the rules — the things named in the
                  company model, the verbs, the goal when a word says it
              ──▶ this: a model, through the gateway, reads the same words —
                  the goal, a question or a request, what is asked in a
                  sentence
              ──▶ one understanding: the model's goal where the rules could
                  not tell or were less sure — and what the rules hold, kept

Through the LLM runtime (LEKA-429): the things named are its context, its
answer is checked against its shape before it is used, the execution kept.

What the model may not change, on purpose: the things named (the company
model's, not a guess), the actions asked (a verb that changes systems is
what puts a person in the loop — read from the words, never guessed), a
request (only the rules' verbs make one: a model may read a polite request
as the question it is, never a question as a request). What it settles: a goal
the rules could not tell, which was the ambiguity that stopped an intention
— « what is wanted cannot be told » — and which of two goals is meant.

No model, or none in time: the rules' reading, as before. Every call kept
(model_calls).
"""

from __future__ import annotations

import uuid
from typing import Literal, get_args

import structlog
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import ContextItem, ContextPack, LLMRuntime, Needs, Task, Tier
from leka.intentions.schemas import Goal, GoalRead, Understanding, UnderstoodBy
from leka.knowledge import fold

logger = structlog.get_logger(__name__)

NEEDS = Needs(structured=True)
# An intention is being asked: the person waits.
BUDGET = 12.0
# How sure the model must be to change what the rules read.
SURE = 0.5

GOALS: dict[str, str] = {
    "explain_cause": "why something happens, fails, is slow or broke",
    "find_change": "what changed, was deployed or modified",
    "find_owner": "who owns, maintains or is responsible for it",
    "map_dependencies": "what it depends on, or what depends on it",
    "assess_impact": "what a change or an outage would reach",
    "check_compliance": "whether it meets the rules: owner, documentation, criticality",
    "plan_migration": "moving it elsewhere, replacing it",
    "find_knowledge": "what is known or documented about it, where",
    "investigate": "look into it, open-ended",
    "act": "do something to systems: restart, deploy, roll back, scale…",
    "unknown": "it cannot be told",
}
# What an ambiguity about the goal is; settled once the goal is.
ABOUT_THE_GOAL = frozenset({"unclear_goal", "competing_goals"})

SYSTEM = f"""You read what someone asks LEKA, the assistant of an IT \
department, about the company's systems, and say what they want. LEKA's \
job is to understand the whole request and do the work: ask nothing back \
unless the words truly cannot be understood.

Goals:
{chr(10).join(f"- {code}: {said}" for code, said in GOALS.items())}

- act is only when they want LEKA to change systems now. Evaluating, \
simulating, planning, proposing a plan, documenting, drawing an \
architecture or writing a page is never act, even about a migration or a \
deployment: it is the goal of what they want to know or get \
(plan_migration, assess_impact, map_dependencies, find_knowledge…). \
Proposing a design, a mock-up or a code change for a person to review is \
never act either, even when it says it is « to deploy »: a person reviews \
and merges it, LEKA changes nothing by itself.
- unknown only when nothing can be understood of what is wanted.
- mode: "question" when they want an answer, "request" when they want \
something done or produced.
- confidence: how sure you are of the goal, 0 to 1.
- restated: what is asked, in one short sentence, in the language it was \
asked, naming what it is about as written.
- understood: true when LEKA can start working on it as it is — whatever \
it names, however broadly (« les serveurs AWS » is every AWS server LEKA \
knows); false only when the words say nothing LEKA could work on.
- about_technology: false only when the request has nothing to do with \
the company's technology — its software, code, systems, servers, cloud, \
data, tools, projects, teams or documentation: a recipe, the weather, a \
sports score, a poem. Anything about building, running, documenting or \
changing technology, however vague, is true.
Say only what the words say."""


class Reading(BaseModel):
    """What the model is asked to give back."""

    mode: Literal["question", "request"]
    goal: Goal
    confidence: float = Field(ge=0, le=1)
    restated: str = Field(max_length=300)
    understood: bool = True
    about_technology: bool = True


# What says the work asked is to think, plan or produce — not to change
# systems: what lets the model read « migrer… propose un plan » as a plan.
PLANNING = frozenset(
    {
        "plan",
        "planifie",
        "planifier",
        "evalue",
        "evaluer",
        "evaluation",
        "simule",
        "simuler",
        "simulation",
        "propose",
        "proposer",
        "proposition",
        "analyse",
        "analyser",
        "estime",
        "estimer",
        "compare",
        "comparer",
        "prepare",
        "preparer",
        "documente",
        "documenter",
        "documentation",
        "redige",
        "rediger",
        "genere",
        "generer",
        "dessine",
        "dessiner",
        "schema",
        "architecture",
        "deck",
        "rapport",
        "etude",
        "strategie",
        "feuille",
        "assess",
        "evaluate",
        "simulate",
        "draft",
        "design",
        "report",
        "document",
        "study",
        "strategy",
        "roadmap",
        "pdf",
    }
)
# The goals a plan may be read as: what is learnt or produced, never done.
PLANS = frozenset(
    {"plan_migration", "assess_impact", "map_dependencies", "check_compliance", "find_knowledge"}
)

# What only matters when systems are changed: the rules ask it of an
# action, never of a plan or a question.
ABOUT_ACTING = frozenset(
    {"no_subject", "unknown_subject", "ambiguous_subject", "action_without_target"}
)


def merged(understood: Understanding, reading: Reading, by: UnderstoodBy) -> Understanding:
    """The rules' understanding, with what the model settles.

    The model settles the goal where the rules could not tell or were less
    sure — and may say that what a verb made look like an action (« migrer »)
    is a plan or an assessment: the safe way, nothing is then done to
    systems. It never makes an action of a question. Understood, a request
    is worked on as it is: only what acting needs (which thing, exactly)
    still stops one that changes systems."""
    goal = understood.goal
    acting = any(a.changes_systems for a in understood.actions) or goal.code == "act"
    sure = reading.confidence >= SURE
    # An action read as a plan only when its words ask for one — « Redémarre
    # Billing API » stays the action it is, whatever a model says.
    planned = reading.goal in PLANS and bool(PLANNING & set(fold(understood.text).split()))
    changed = (
        sure
        and reading.goal not in ("unknown", "act")
        and reading.goal != goal.code
        and (not acting or (planned and reading.confidence >= max(SURE, goal.confidence)))
    )
    actions = understood.actions
    if changed:
        goal = GoalRead(
            code=reading.goal,
            # The words that said the old goal do not say this one.
            said=[],
            confidence=round(min(reading.confidence, 0.9), 2),
        )
        if acting:
            # A plan, not an action: what would change systems is not asked.
            actions = [a for a in actions if not a.changes_systems]
    still_acting = goal.code == "act" or any(a.changes_systems for a in actions)
    # Nothing about technology, and nothing of the company's named: LEKA says
    # what it answers about rather than asking what is wanted (2026-10-14).
    off_topic = not reading.about_technology and sure and not understood.entities and not acting
    settled = goal.code != "unknown"
    understood_as_is = reading.understood and sure
    ambiguities = []
    for a in understood.ambiguities:
        if settled and (changed or reading.goal == goal.code) and a.kind in ABOUT_THE_GOAL:
            continue
        if a.kind == "action_without_target" and not still_acting:
            continue
        if a.blocking and (
            (a.kind in ABOUT_ACTING and not still_acting)
            or (a.kind == "unclear_goal" and understood_as_is)
        ):
            # Worked on as it is: LEKA looks, and says what it assumed.
            a = a.model_copy(update={"blocking": False})
        ambiguities.append(a)
    return understood.model_copy(
        update={
            "goal": goal,
            "actions": actions,
            # A request is the rules' to say, from their verbs: a model may
            # read one as a question — the safe way — never a question as a
            # request (LEKA-429).
            "mode": "question" if not acting and reading.mode == "question" else understood.mode,
            "ambiguities": ambiguities,
            "clear": not any(a.blocking for a in ambiguities),
            "restated": reading.restated.strip() or None,
            "read_by": by,
            "off_topic": off_topic,
        }
    )


class ModelReading:
    """Reads an intention with a model, through the LLM runtime (LEKA-429),
    for IntentionService. The things the company model matched are its
    context: what it may refer to, by id."""

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._runtime = LLMRuntime(session, workspace_id)

    async def __call__(self, text: str, understood: Understanding) -> Understanding:
        task = Task(
            purpose="intention.understanding",
            instructions=SYSTEM,
            input={
                "text": text,
                "rules_read": {
                    "goal": understood.goal.code,
                    "mode": understood.mode,
                    "actions": [a.code for a in understood.actions],
                },
            },
            context=ContextPack.of(
                [
                    ContextItem(
                        id=f"entity:{e.entity_id}",
                        kind=e.type,
                        text=f"{e.name} ({e.type}), named in the request",
                    )
                    for e in understood.entities
                ],
                ref="intention.understanding",
            ),
            output=Reading,
            needs=NEEDS,
            tier=Tier.FAST,
            # Its thinking counts in it: room enough never to be cut short.
            max_tokens=2000,
            budget=BUDGET,
        )
        done = await self._runtime.run(task)
        if not done.ok:
            # No model, none in time, nothing usable: the rules' reading —
            # what asking cost kept with it (LEKA-430).
            logger.info("intention_read_by_rules", status=done.status, why=done.error)
            if done.calls and done.run_id is not None:
                by = understood.read_by or UnderstoodBy(method="rules")
                return understood.model_copy(
                    update={"read_by": by.model_copy(update={"run_id": done.run_id})}
                )
            return understood
        reading: Reading = done.value
        return merged(
            understood,
            reading,
            UnderstoodBy(
                method="model",
                provider=done.provider,
                model=done.model,
                version=done.version,
                confidence=reading.confidence,
                run_id=done.run_id,
            ),
        )


assert set(GOALS) == set(get_args(Goal)), "every goal is described to the model"
