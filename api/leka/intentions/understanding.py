"""What LEKA understands of an intention (LEKA-385): from its words, what
the asker wants to achieve, what to do, about what — and what it cannot
tell, flagged for clarification rather than guessed.

    the words ──▶ LEKA-373's reading (leka.context, IntentPlan): its kind,
                  the things it names — and those it names ambiguously —
                  when, where
              ──▶ this: the MODE — a question to answer, or a request to
                  act on; the ACTIONS it asks for — restart, roll back,
                  investigate… — and which would change a customer's
                  systems; the GOAL — explain a cause, find an owner,
                  assess an impact, act…; the AMBIGUITIES — what it would
                  ask to go on
              ──▶ Understanding: the structured intent, each part with
                  the words it came from, the words themselves kept beside

An intention whose understanding has a BLOCKING ambiguity is not analysed:
it is said `needs_clarification`, with the questions, until it is asked
again (lifecycle.py).

Deliberately words, not a model — the model gateway does not exist yet
(LEKA-394) — and pure: tested in a millisecond on the examples LEKA's
users ask (tests/test_intention_understanding.py). Each reading says which
words it came from, so what LEKA understood can be checked.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from leka.context import IntentPlan, kinds_said
from leka.intentions.schemas import (
    ActionRead,
    AmbiguityRead,
    GoalRead,
    Understanding,
    UnderstoodEntity,
)
from leka.intentions.scope import scope_of
from leka.knowledge import fold

# Raised each time intentions are understood differently: kept with each.
# 2: its scope and constraints, and what critical information is missing
#    (LEKA-386).
UNDERSTANDING_VERSION = 2

# ── actions ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Verb:
    code: str
    changes_systems: bool
    said: frozenset[str]


def _words(said: str) -> frozenset[str]:
    return frozenset(said.split())


def _verb(code: str, changes: bool, said: str) -> Verb:
    return Verb(code=code, changes_systems=changes, said=_words(said))


# Verbs, folded, French and English — never the nouns: « le déploiement »
# is what happened, « déploie » what is asked.
VERBS: tuple[Verb, ...] = (
    _verb(
        "restart", True, "redemarrer redemarre redemarrez relancer relance relancez restart reboot"
    ),
    _verb("rollback", True, "rollback rollbacker revert reverter"),
    _verb("deploy", True, "deployer deploie deployez redeployer redeploie redeploy"),
    _verb("scale", True, "scaler augmenter augmente augmentez scale upscale downscale"),
    _verb("stop", True, "arreter arrete arretez stopper desactiver desactive desactivez disable"),
    _verb(
        "fix", True, "corriger corrige corrigez reparer repare reparez fix resoudre resous resolve"
    ),
    _verb("update", True, "upgrade upgrader"),
    _verb("migrate", True, "migrer migre migrez migrate"),
    _verb(
        "investigate",
        False,
        "analyser analysez investiguer investigue investigate analyze analyse diagnostiquer",
    ),
    _verb("compare", False, "comparer compare comparez"),
    _verb(
        "assess", False, "evaluer evalue evaluez verifier verifie verifiez check auditer estimer"
    ),
    _verb("list", False, "lister listez list inventorier"),
    _verb("document", False, "documenter documente documentez rediger redige redigez"),
    _verb("notify", False, "prevenir previens prevenez notifier notifie notifiez notify informer"),
)
# Done, though they change no system: a request to do them is to act.
DOING = frozenset({"document", "notify", "ticket"})
# Said in more than a word.
UPDATE = re.compile(r"\b(?:mettre|mets|mettez|met) (?:a|à) jour\b|\bupdate\b")
TICKET = re.compile(
    r"\b(?:creer|cree|creez|ouvrir|ouvre|ouvrez|create|open)\b(?: \w+){0,2} (?:ticket|issue)\b"
)

# ── mode ────────────────────────────────────────────────────────────────

QUESTION_WORDS = _words(
    """pourquoi qui quoi quel quelle quels quelles comment combien quand ou est-ce
    why who what which how where when whose"""
)
# Asked politely, or wanted: a request, even with a question mark.
REQUEST_WORDS = re.compile(
    r"\b(?:peux tu|pourrais tu|pouvez vous|pourriez vous|je veux|je voudrais|il faut|"
    r"merci de|can you|could you|please|i want|i need)\b"
)

# ── goals ───────────────────────────────────────────────────────────────

GOAL_OF_KIND = {
    "diagnose": "explain_cause",
    "change": "find_change",
    "ownership": "find_owner",
    "dependency": "map_dependencies",
    "compliance": "check_compliance",
    "migration": "plan_migration",
    "knowledge": "find_knowledge",
}
IMPACT_WORDS = _words(
    "impact impacts impacte impacter affecte affectes touche touches casse cassera"
)
# Words that say nothing alone: what a request is not made of.
FILLER = _words(
    """le la les un une des de du a au aux et ou en sur pour par avec dans est sont
    the a an of to in on for and or is are it this that ca cela ceci"""
)
# How sure a goal is, by how much said it.
SURE, LIKELY, GUESS = 0.8, 0.6, 0.4
MIN_WORDS = 2


@dataclass(frozen=True)
class Found:
    """An action found: its verb and the word that said it."""

    verb: Verb
    said: str


def actions_of(text: str) -> list[Found]:
    """The actions its words ask for, in the order said, each once."""
    folded = fold(text)
    found: dict[str, Found] = {}
    for word in folded.split():
        for verb in VERBS:
            if word in verb.said and verb.code not in found:
                found[verb.code] = Found(verb, word)
    update = UPDATE.search(folded)
    if update and "update" not in found:
        found["update"] = Found(_verb("update", True, ""), update.group(0))
    ticket = TICKET.search(folded)
    if ticket:
        found["ticket"] = Found(_verb("ticket", False, ""), ticket.group(0))
    return list(found.values())


def mode_of(text: str, actions: Sequence[Found]) -> tuple[str, str | None]:
    """A question, or a request — and what said it."""
    folded = fold(text)
    asked = REQUEST_WORDS.search(folded)
    if asked and actions:
        return "request", asked.group(0)
    first = folded.split()[0] if folded.split() else ""
    if first in QUESTION_WORDS:
        return "question", first
    if text.strip().endswith("?"):
        return "question", "?"
    if actions:
        return "request", actions[0].said
    return "question", None


def _goal(
    plan: IntentPlan | None,
    kinds: Sequence[tuple[str, list[str]]],
    mode: str,
    actions: Sequence[Found],
    folded: set[str],
    has_entities: bool,
) -> GoalRead:
    acting = [a for a in actions if a.verb.changes_systems or a.verb.code in DOING]
    if mode == "request" and acting:
        return GoalRead(
            code="act",
            said=[a.said for a in acting],
            confidence=0.9 if has_entities else 0.5,
        )
    kind = plan.kind if plan is not None else (kinds[0][0] if kinds else "general")
    said = next((found for k, found in kinds if k == kind), list(plan.kind_said) if plan else [])
    if kind in GOAL_OF_KIND:
        code = GOAL_OF_KIND[kind]
        impact = sorted(folded & IMPACT_WORDS)
        if kind == "dependency" and impact:
            code, said = "assess_impact", impact
        return GoalRead(code=code, said=said, confidence=SURE if len(said) > 1 else LIKELY)
    looking = [a for a in actions if not a.verb.changes_systems and a.verb.code not in DOING]
    if looking:
        return GoalRead(code="investigate", said=[a.said for a in looking], confidence=GUESS)
    return GoalRead(code="unknown", said=[], confidence=0.0)


def _entities(plan: IntentPlan | None) -> list[UnderstoodEntity]:
    if plan is None:
        return []
    return [
        UnderstoodEntity(
            entity_id=s.entity_id,
            name=s.name,
            type=s.type,
            how=s.how,
            said=s.said,
            confidence=s.confidence,
        )
        for s in plan.subjects
    ]


def _ambiguities(
    text: str,
    plan: IntentPlan | None,
    kinds: Sequence[tuple[str, list[str]]],
    goal: GoalRead,
    actions: Sequence[Found],
    entities: Sequence[UnderstoodEntity],
) -> list[AmbiguityRead]:
    found: list[AmbiguityRead] = []
    if len([w for w in fold(text).split() if w not in FILLER and len(w) > 1]) < MIN_WORDS:
        found.append(
            AmbiguityRead(
                kind="too_short",
                blocking=True,
                said="Too few words to tell what is wanted.",
            )
        )
    if goal.code == "unknown":
        found.append(
            AmbiguityRead(
                kind="unclear_goal",
                blocking=True,
                said="What is wanted cannot be told: explain, find, assess, act?",
                options=sorted(set(GOAL_OF_KIND.values())),
            )
        )
    if goal.code != "act" and len(kinds) > 1 and len(kinds[0][1]) == len(kinds[1][1]):
        options = [GOAL_OF_KIND.get(kind, kind) for kind, _ in kinds[:2]]
        found.append(
            AmbiguityRead(
                kind="competing_goals",
                blocking=False,
                said=f"It says {options[0]} as much as {options[1]}: read as the first.",
                options=options,
            )
        )
    for gap in plan.gaps if plan is not None else []:
        detail = gap.detail
        if gap.kind == "no_subject":
            maybe = detail.get("maybe")
            found.append(
                AmbiguityRead(
                    kind="no_subject",
                    blocking=True,
                    said="It names nothing LEKA knows: which service, application or data?",
                    options=[str(m) for m in maybe] if isinstance(maybe, list) else [],
                )
            )
        elif gap.kind == "unknown_service":
            found.append(
                AmbiguityRead(
                    kind="unknown_subject",
                    blocking=True,
                    said="Something asked for is not in the company model.",
                )
            )
        elif gap.kind == "ambiguous_subject":
            things = detail.get("things")
            names = (
                [str(t.get("name")) for t in things if isinstance(t, dict)]
                if isinstance(things, list)
                else []
            )
            found.append(
                AmbiguityRead(
                    kind="ambiguous_subject",
                    # Acting on the wrong one is not a reading to correct later.
                    blocking=goal.code == "act",
                    said=f"« {detail.get('said', '')} » names several things.",
                    options=names,
                )
            )
        elif gap.kind == "unknown_environment":
            known = detail.get("known")
            found.append(
                AmbiguityRead(
                    kind="unknown_environment",
                    blocking=False,
                    said=f"« {detail.get('environment', '')} » is no environment LEKA knows.",
                    options=[str(e) for e in known] if isinstance(known, list) else [],
                )
            )
    if any(a.verb.changes_systems for a in actions) and not entities:
        found.append(
            AmbiguityRead(
                kind="action_without_target",
                blocking=True,
                said="An action is asked, on nothing LEKA knows: on what?",
                options=[a.verb.code for a in actions if a.verb.changes_systems],
            )
        )
    if text.count("?") > 1 or (
        len({a.verb.code for a in actions}) > 1
        and re.search(r"\b(?:et|and|puis|then)\b", fold(text))
    ):
        found.append(
            AmbiguityRead(
                kind="several_requests",
                blocking=False,
                said="It asks several things: each is read, the first leads.",
            )
        )
    return found


def understand(
    text: str,
    plan: IntentPlan | None,
    *,
    lifecycles: Mapping[uuid.UUID, str] | None = None,
    environments: Sequence[str] = (),
    now: datetime | None = None,
) -> Understanding:
    """What LEKA understands of these words, read with LEKA-373's plan —
    and, given what the company model says of each thing and the
    environments it knows, their scope (LEKA-386)."""
    found = actions_of(text)
    mode, mode_said = mode_of(text, found)
    kinds = kinds_said(text)
    named = _entities(plan)
    goal = _goal(plan, kinds, mode, found, set(fold(text).split()), bool(named))
    actions = [
        ActionRead(code=a.verb.code, said=a.said, changes_systems=a.verb.changes_systems)
        for a in found
    ]
    scope, missing = scope_of(
        text,
        plan,
        goal=goal,
        actions=actions,
        lifecycles=lifecycles or {},
        environments=environments,
        now=now or datetime.now(UTC),
    )
    # What it excludes is not what it is about.
    kept = {thing.entity_id for thing in scope.entities}
    entities = [entity for entity in named if entity.entity_id in kept]
    ambiguities = [
        *_ambiguities(text, plan, kinds, goal, found, entities),
        *missing,
    ]
    period = None
    if plan is not None:
        period = plan.period.model_dump(mode="json")
    return Understanding(
        version=UNDERSTANDING_VERSION,
        text=text,
        mode=mode,
        mode_said=mode_said,
        kind=plan.kind if plan is not None else (kinds[0][0] if kinds else "general"),
        goal=goal,
        actions=actions,
        entities=entities,
        period=period,
        environment=plan.environment if plan is not None else None,
        ambiguities=ambiguities,
        clear=not any(a.blocking for a in ambiguities),
        scope=scope,
    )
