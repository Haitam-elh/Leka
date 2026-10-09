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
department, about the company's systems, and say what they want.

Goals:
{chr(10).join(f"- {code}: {said}" for code, said in GOALS.items())}

mode: "question" when they want an answer, "request" when they want \
something done. confidence: how sure you are of the goal, 0 to 1. restated: \
what is asked, in one short sentence, in the language it was asked, naming \
what it is about as written. Say only what the words say."""


class Reading(BaseModel):
    """What the model is asked to give back."""

    mode: Literal["question", "request"]
    goal: Goal
    confidence: float = Field(ge=0, le=1)
    restated: str = Field(max_length=300)


def merged(understood: Understanding, reading: Reading, by: UnderstoodBy) -> Understanding:
    """The rules' understanding, with what the model settles."""
    goal = understood.goal
    acting = any(a.changes_systems for a in understood.actions) or goal.code == "act"
    changed = (
        not acting
        and reading.goal not in ("unknown", "act")
        and reading.confidence >= max(SURE, goal.confidence)
        and reading.goal != goal.code
    )
    if changed:
        goal = GoalRead(
            code=reading.goal,
            # The words that said the old goal do not say this one.
            said=[],
            confidence=round(min(reading.confidence, 0.9), 2),
        )
    settled = goal.code != "unknown"
    ambiguities = [
        a for a in understood.ambiguities if not (settled and changed and a.kind in ABOUT_THE_GOAL)
    ]
    return understood.model_copy(
        update={
            "goal": goal,
            # A request is the rules' to say, from their verbs: a model may
            # read one as a question — the safe way — never a question as a
            # request (LEKA-429).
            "mode": "question" if not acting and reading.mode == "question" else understood.mode,
            "ambiguities": ambiguities,
            "clear": not any(a.blocking for a in ambiguities),
            "restated": reading.restated.strip() or None,
            "read_by": by,
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
            max_tokens=400,
            budget=BUDGET,
        )
        done = await self._runtime.run(task)
        if not done.ok:
            # No model, none in time, nothing usable: the rules' reading.
            logger.info("intention_read_by_rules", status=done.status, why=done.error)
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
            ),
        )


assert set(GOALS) == set(get_args(Goal)), "every goal is described to the model"
