"""An intention's brief (LEKA-439): what LEKA must know to work on it, what it
knows of it, what it asks — and what follows.

    the contract       five parts, each known (said, answered), assumed
                       (LEKA's reading — never shown as a fact), missing,
                       or unknown (its asker said « je ne sais pas »)

        goal           what they want: explain, find, assess, act…
        target         what it is about: things of the company model
        scope          where and when: an environment, a period
        expected       what they expect back: an answer, a document, a
                       plan, an action on their systems
        constraints    what must hold: read only, no downtime, a deadline…

    the questions      what LEKA cannot tell (understanding.py's
                       ambiguities), the blocking first, then by part —
                       each with what it could be: its options, the things
                       it could mean by id, their own words when that helps
    the answers        kept with the intention, read again with it every
                       time it is understood: a thing chosen narrows its
                       scope, an environment holds it there, a goal is the
                       one meant, an action is confirmed or declined, their
                       words are read with the rest

    the decision       analyse      nothing is missing
                       clarify      something blocking is unanswered
                       continue     only what is useful is missing, or not
                                    known: it goes on, its limits said
                       block        an action on systems whose blocking
                                    question its asker cannot answer — never
                                    acted on a guess

Pure: tested in a millisecond (tests/test_intention_brief.py). What a model
read (LEKA-394) is `assumed`, never `known`: a hypothesis is not a fact.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from typing import get_args

from leka.context import IntentAsk
from leka.intentions.schemas import (
    ActionRead,
    AmbiguityKind,
    AmbiguityRead,
    BriefDecision,
    BriefQuestionRead,
    BriefSlotRead,
    Goal,
    GoalRead,
    IntentionAnswer,
    IntentionBrief,
    Slot,
    Understanding,
)
from leka.knowledge import fold

BRIEF_VERSION = 1

# Which part of the contract each of LEKA's questions is about.
SLOT_OF: Mapping[str, Slot] = {
    "too_short": "goal",
    "unclear_goal": "goal",
    "competing_goals": "goal",
    "several_requests": "goal",
    "no_subject": "target",
    "unknown_subject": "target",
    "ambiguous_subject": "target",
    "action_without_target": "target",
    "missing_target": "target",
    "subject_gone": "target",
    "subject_dormant": "target",
    "everything_excluded": "target",
    "unknown_environment": "scope",
    "missing_environment": "scope",
    "conflicting_constraints": "constraints",
    "ambiguous_action": "expected",
}
# Asked in that order, the blocking first: what it is about, then what they
# want, what they expect, where and when, what must hold.
ORDER: tuple[Slot, ...] = ("target", "goal", "expected", "scope", "constraints")
# Answered in their own words — read with the rest of what they asked.
WORDED = frozenset(
    {
        "too_short",
        "unclear_goal",
        "no_subject",
        "unknown_subject",
        "action_without_target",
        "missing_target",
    }
)
TARGETS = frozenset(k for k, slot in SLOT_OF.items() if slot == "target")
ENVIRONMENTS = frozenset({"unknown_environment", "missing_environment"})
GOALS_ASKED = frozenset({"unclear_goal", "competing_goals"})
GOALS: frozenset[str] = frozenset(get_args(Goal)) - {"unknown"}
# ambiguous_action: is the action they spoke of asked?
YES, NO = "yes", "no"
# conflicting_constraints: only look, or act.
READ_ONLY = "read_only"

# What says a document is expected back, folded.
DOCUMENT_WORDS = frozenset(
    {
        "pdf",
        "deck",
        "pptx",
        "powerpoint",
        "ppt",
        "slides",
        "presentation",
        "document",
        "documents",
        "doc",
        "rapport",
        "report",
        "schema",
        "diagramme",
        "diagram",
        "livrable",
        "support",
        "page",
    }
)
PLAN_WORDS = frozenset({"plan", "planning", "feuille", "roadmap", "strategie", "strategy"})


def _id(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def latest(answers: Sequence[IntentionAnswer]) -> dict[str, IntentionAnswer]:
    """Each question's answer: the latest, when it was answered twice."""
    return {answer.question: answer for answer in answers}


def acting(understanding: Understanding) -> bool:
    """It asks to change systems."""
    return any(action.changes_systems for action in understanding.actions)


# ── the answers, applied ────────────────────────────────────────────────


def answered_ask(ask: IntentAsk, answers: Sequence[IntentionAnswer]) -> IntentAsk:
    """What is read, answers given: their words with the rest of what they
    asked; a thing chosen narrows its scope; an environment chosen holds it
    there. The words kept with the intention are not changed."""
    given = latest(answers)
    words = [
        a.value.strip()
        for a in given.values()
        if a.question in WORDED and not a.unknown and a.value and _id(a.value) is None
    ]
    services = list(ask.services)
    for a in given.values():
        chosen = _id(a.value) if a.question in TARGETS and not a.unknown else None
        if chosen is not None and chosen not in services:
            services.append(chosen)
    environment = ask.environment
    for kind in ENVIRONMENTS:
        chose = given.get(kind)
        if chose is not None and not chose.unknown and chose.value:
            environment = chose.value
    update: dict[str, object] = {}
    if words:
        update["text"] = "\n".join([ask.text, *words])[:2000]
    if services != list(ask.services):
        update["services"] = services
    if environment != ask.environment:
        update["environment"] = environment
    return ask.model_copy(update=update) if update else ask


def answered(understanding: Understanding, answers: Sequence[IntentionAnswer]) -> Understanding:
    """What LEKA understands, its asker's answers taken: the goal they mean,
    an action confirmed or declined, what must hold — each question
    answered no longer asked; one they cannot answer still said, and
    blocking only what acts on systems (`decision`)."""
    if not answers:
        return understanding
    given = latest(answers)
    goal = understanding.goal
    for kind in GOALS_ASKED:
        a = given.get(kind)
        if a is not None and not a.unknown and a.value in GOALS:
            goal = GoalRead(code=a.value, said=[], confidence=1.0)
    actions = list(understanding.actions)
    withheld = list(understanding.withheld)
    scope = understanding.scope
    doubt = given.get("ambiguous_action")
    if doubt is not None and not doubt.unknown and doubt.value == YES:
        # Asked, said so: the doubtful ones on systems are asked — never one
        # they said not to do.
        confirmed = [
            w for w in withheld if w.changes_systems and w.polarity in ("conditional", "ambiguous")
        ]
        actions += [w.model_copy(update={"polarity": "affirmed"}) for w in confirmed]
        withheld = [w for w in withheld if w not in confirmed]
    conflict = given.get("conflicting_constraints")
    if conflict is not None and not conflict.unknown and conflict.value:
        if conflict.value == READ_ONLY:
            # Only to look: what would change systems is not asked.
            declined = [a for a in actions if a.changes_systems]
            withheld += [a.model_copy(update={"polarity": "negated"}) for a in declined]
            actions = [a for a in actions if not a.changes_systems]
        elif scope is not None:
            # To act: what said « read only » no longer holds.
            scope = scope.model_copy(
                update={"constraints": [c for c in scope.constraints if c.kind != "read_only"]}
            )
    acts = any(a.changes_systems for a in actions)
    if goal.code == "act" and not acts and conflict is not None and conflict.value == READ_ONLY:
        goal = GoalRead(code="investigate", said=[], confidence=1.0)
    kept: list[AmbiguityRead] = []
    for ambiguity in understanding.ambiguities:
        a = given.get(ambiguity.kind)
        if a is None:
            kept.append(ambiguity)
        elif a.unknown:
            # Not known: said — it stops only what acts on systems.
            kept.append(ambiguity.model_copy(update={"blocking": ambiguity.blocking and acts}))
        elif ambiguity.kind in WORDED and _id(a.value) is None:
            # Read again with their words (answered_ask): still there, the
            # words did not settle it — asked again.
            kept.append(ambiguity)
        # Otherwise answered: a choice made, a goal meant, an action settled.
    return understanding.model_copy(
        update={
            "goal": goal,
            "actions": actions,
            "withheld": withheld,
            "scope": scope,
            "ambiguities": kept,
            "clear": not any(a.blocking for a in kept),
        }
    )


# ── the brief ───────────────────────────────────────────────────────────


def _expected(understanding: Understanding, words: set[str]) -> tuple[str, bool]:
    """What they expect back, and whether their words say it."""
    if acting(understanding):
        return "action", True
    if any(a.code == "document" for a in understanding.actions):
        # « Documente », « mets à jour la documentation »: a document, written.
        return "document", True
    if words & DOCUMENT_WORDS:
        return "document", True
    if words & PLAN_WORDS:
        return "plan", True
    if understanding.goal.code == "plan_migration":
        return "plan", False
    return "answer", understanding.mode == "question"


def _slots(
    understanding: Understanding,
    given: Mapping[str, IntentionAnswer],
    questions: Sequence[BriefQuestionRead],
) -> list[BriefSlotRead]:
    acts = acting(understanding)
    words = set(fold(understanding.text).split())
    asked = {q.slot for q in questions}
    unknown = {q.slot for q in questions if q.answer is not None and q.answer.unknown}
    blocking = {q.slot for q in questions if q.blocking}

    def state(slot: Slot, have: bool, assumed: bool = False) -> str:
        if slot in unknown:
            return "unknown"
        if slot in blocking or (slot in asked and not have):
            return "missing"
        if not have:
            return "missing"
        return "assumed" if assumed else "known"

    goal = understanding.goal
    answered_goal = any(k in given and not given[k].unknown for k in GOALS_ASKED)
    by_model = (
        understanding.read_by is not None
        and understanding.read_by.method == "model"
        and not goal.said
        and not answered_goal
    )
    scope = understanding.scope
    things = [e.name for e in (scope.entities if scope is not None else understanding.entities)]
    chose = any(k in given and _id(given[k].value) is not None for k in TARGETS)
    environments = list(scope.environments) if scope is not None else []
    if not environments and understanding.environment:
        environments = [understanding.environment]
    period = scope.period if scope is not None else None
    expected, said = _expected(understanding, words)
    constraints = [c.kind for c in scope.constraints] if scope is not None else []
    return [
        BriefSlotRead(
            slot="goal",
            state=state("goal", goal.code != "unknown", assumed=by_model),
            need="blocking",
            value=goal.code,
            origin="answer" if answered_goal else "model" if by_model else "words",
        ),
        BriefSlotRead(
            slot="target",
            state=state("target", bool(things)),
            # A question about everything is answered by looking; only an
            # action needs to know what it acts on.
            need="blocking" if acts else "useful",
            value=None,
            values=things,
            origin=("answer" if chose else "company_model") if things else None,
        ),
        BriefSlotRead(
            slot="scope",
            state=state(
                "scope",
                bool(environments) or period is not None,
                assumed=not environments and period is not None and not period.explicit,
            ),
            need="blocking" if acts else "optional",
            value=environments[0] if environments else None,
            values=environments,
            origin=(
                "answer"
                if any(k in given and not given[k].unknown for k in ENVIRONMENTS)
                else "words"
                if environments or (period is not None and period.explicit)
                else "default"
                if period is not None
                else None
            ),
        ),
        BriefSlotRead(
            slot="expected",
            state=state("expected", True, assumed=not said),
            need="useful",
            value=expected,
            origin="words" if said else "default",
        ),
        BriefSlotRead(
            slot="constraints",
            state=state("constraints", bool(constraints)),
            need="optional",
            value=None,
            values=constraints,
            origin="words" if constraints else None,
        ),
    ]


def _questions(
    understanding: Understanding, given: Mapping[str, IntentionAnswer]
) -> list[BriefQuestionRead]:
    asked = [
        BriefQuestionRead(
            kind=a.kind,
            slot=SLOT_OF.get(a.kind, "goal"),
            blocking=a.blocking,
            said=a.said,
            options=list(a.options),
            choices=list(a.choices),
            free=a.kind in WORDED,
            answer=given.get(a.kind),
        )
        for a in understanding.ambiguities
    ]
    return sorted(asked, key=lambda q: (not q.blocking, ORDER.index(q.slot)))


def brief_of(
    understanding: Understanding, answers: Sequence[IntentionAnswer] = ()
) -> IntentionBrief:
    """Its brief, answers taken (`answered` first): each part's state, the
    questions in order, and what follows."""
    given = latest(answers)
    questions = _questions(understanding, given)
    acts = acting(understanding)
    stuck = [q for q in questions if q.blocking and q.answer is not None and q.answer.unknown]
    open_ = [q for q in questions if q.blocking and (q.answer is None or not q.answer.unknown)]
    decision: BriefDecision
    if understanding.off_topic:
        # Not about technology: nothing to ask, nothing to analyse — said.
        decision = "off_topic"
    elif acts and stuck:
        decision = "block"
    elif open_:
        decision = "clarify"
    elif questions:
        decision = "continue"
    else:
        decision = "analyse"
    limits: list[AmbiguityKind] = [q.kind for q in questions if not q.blocking]
    return IntentionBrief(
        version=BRIEF_VERSION,
        decision=decision,
        restated=understanding.restated,
        acting=acts,
        slots=_slots(understanding, given, questions),
        questions=questions,
        limits=limits,
    )


# What a free answer can never be: a line break would end what was asked.
ONE_LINE = re.compile(r"\s+")


def tidy(answers: Sequence[IntentionAnswer]) -> list[IntentionAnswer]:
    """Answers as kept: one per question, the latest; words on one line."""
    return [
        a.model_copy(update={"value": ONE_LINE.sub(" ", a.value).strip() if a.value else None})
        for a in latest(answers).values()
    ]


def actions_of(understanding: Understanding) -> list[ActionRead]:
    """What it asks done on systems — never what is withheld."""
    return [a for a in understanding.actions if a.changes_systems]
