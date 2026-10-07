"""An intention's scope (LEKA-386): exactly what it is about, and within
which boundaries it must be processed — so the analysis, and anything done
after, stays within what was meant.

    things       its subjects, resolved against the company model by
                 LEKA-373 — and what the model says of each now: a thing
                 removed or archived is no longer there to act on; one
                 dormant may not be what is used. Excluded ones apart:
                 « sauf auth-service »
    where        the environment asked, read from its words, or held to:
                 « uniquement en staging »
    when         the period, and whether the asker said it — or it is its
                 kind's default; a deadline, « avant vendredi »; a window,
                 « hors heures ouvrées »
    constraints  read only — « sans rien modifier »; no downtime; urgent;
                 a migration's target, « vers AWS »; the services and
                 sources the form held it to
    missing      the critical information a goal needs and the words do
                 not give: where to act when the company runs several
                 environments, where to migrate to; constraints at odds —
                 acting, read only; every thing excluded

What is missing is an ambiguity of the understanding (understanding.py):
blocking, it is routed to clarification before any analysis.

Pure: the words, LEKA-373's plan, the goal and actions understood, what
the model says of each thing and the environments it knows, the time.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from leka.context import IntentPlan
from leka.intentions.schemas import (
    ActionRead,
    AmbiguityRead,
    GoalRead,
    IntentScope,
    ScopeConstraint,
    ScopedEntity,
    ScopePeriod,
)
from leka.knowledge import fold

GONE = frozenset({"removed", "archived"})
DORMANT = "dormant"

EXCLUDE = re.compile(
    r"\b(?:sauf|hors|a part|excepte|except|excluding|other than|sans)\s+((?:\S+\s+){0,3})"
)
READ_ONLY = re.compile(
    r"\b(?:sans (?:rien )?(?:modifier|toucher|changer)|lecture seule|ne (?:rien )?"
    r"(?:modifie|change|touche)|read only|without (?:changing|touching)|do not "
    r"(?:change|touch)|don t (?:change|touch))\b"
)
NO_DOWNTIME = re.compile(
    r"\b(?:sans (?:interruption|coupure|downtime|indisponibilite)|zero downtime|"
    r"no downtime|without downtime)\b"
)
URGENCY = re.compile(
    r"\b(?:urgent|urgente|urgence|asap|au plus vite|immediatement|tout de suite|"
    r"right now|immediately)\b"
)
WINDOW = re.compile(
    r"\b(?:(?:en dehors des|hors) heures ouvrees|cette nuit|la nuit|ce week ?end|"
    r"le week ?end|outside (?:of )?business hours|tonight|at night|this weekend)\b"
)
_DAYS = {
    "lundi": 0, "monday": 0, "mardi": 1, "tuesday": 1, "mercredi": 2, "wednesday": 2,
    "jeudi": 3, "thursday": 3, "vendredi": 4, "friday": 4, "samedi": 5, "saturday": 5,
    "dimanche": 6, "sunday": 6,
}  # fmt: skip
DEADLINE = re.compile(
    r"\b(?:avant|d ici|by|before) (demain|tomorrow|ce soir|tonight|"
    r"(?:la )?fin de (?:la )?semaine|(?:the )?end of (?:the )?week|" + "|".join(_DAYS) + r")\b"
)
ONLY = re.compile(r"\b(?:uniquement|seulement|only) (?:en|in|on|sur) (\w+)")
TARGET = re.compile(r"\b(?:vers|towards|to) (\w+)")
# A migration's target read from « vers … »: not a word that says nothing.
NOT_TARGETS = frozenset({"le", "la", "les", "un", "une", "the", "a", "an", "de", "du"})


def _deadline(said: str, now: datetime) -> str | None:
    """When a deadline falls, as a day — when the words say one."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if said in ("demain", "tomorrow"):
        return (today + timedelta(days=1)).date().isoformat()
    if said in ("ce soir", "tonight"):
        return today.date().isoformat()
    if said in _DAYS:
        ahead = (_DAYS[said] - today.weekday()) % 7 or 7
        return (today + timedelta(days=ahead)).date().isoformat()
    if "semaine" in said or "week" in said:
        return (today + timedelta(days=(6 - today.weekday()) or 7)).date().isoformat()
    return None


def constraints_of(text: str, now: datetime) -> list[ScopeConstraint]:
    """The boundaries its words set, each with the words that set it."""
    folded = fold(text)
    found: list[ScopeConstraint] = []
    if match := READ_ONLY.search(folded):
        found.append(ScopeConstraint(kind="read_only", said=match.group(0), value=True, hard=True))
    if match := NO_DOWNTIME.search(folded):
        found.append(
            ScopeConstraint(kind="no_downtime", said=match.group(0), value=True, hard=True)
        )
    if match := DEADLINE.search(folded):
        found.append(
            ScopeConstraint(
                kind="deadline",
                said=match.group(0),
                value=_deadline(match.group(1), now),
                hard=True,
            )
        )
    if match := WINDOW.search(folded):
        found.append(
            ScopeConstraint(kind="window", said=match.group(0), value=match.group(0), hard=True)
        )
    if match := URGENCY.search(folded):
        found.append(ScopeConstraint(kind="urgency", said=match.group(0), value="high", hard=False))
    if match := ONLY.search(folded):
        found.append(
            ScopeConstraint(
                kind="environment_only", said=match.group(0), value=match.group(1), hard=True
            )
        )
    return found


def _excluded(text: str, said: str | None) -> bool:
    """Whether a thing is named after « sauf », « hors », « except »…"""
    if not said:
        return False
    folded = fold(text)
    for match in EXCLUDE.finditer(folded):
        following = folded[match.start(1) : match.start(1) + len(said) + 40]
        if fold(said) in following:
            return True
    return False


def _target(text: str) -> str | None:
    for match in TARGET.finditer(fold(text)):
        if match.group(1) not in NOT_TARGETS:
            return match.group(1)
    return None


def _environment(
    plan: IntentPlan | None, constraints: Sequence[ScopeConstraint], known: Sequence[str]
) -> tuple[list[str], str | None]:
    only = next((c for c in constraints if c.kind == "environment_only"), None)
    if only is not None:
        word = str(only.value)
        held = next((env for env in known if fold(env) == word or word in fold(env)), word)
        return [held], "constraint"
    if plan is not None and plan.environment:
        asked = any(c.kind == "environment" and c.origin == "asked" for c in plan.constraints)
        return [plan.environment], "asked" if asked else "text"
    return [], None


def scope_of(
    text: str,
    plan: IntentPlan | None,
    *,
    goal: GoalRead,
    actions: Sequence[ActionRead],
    lifecycles: Mapping[uuid.UUID, str],
    environments: Sequence[str],
    now: datetime,
) -> tuple[IntentScope, list[AmbiguityRead]]:
    """Its scope, and what is missing or at odds in it — as ambiguities."""
    constraints = constraints_of(text, now)
    subjects: list[ScopedEntity] = []
    excluded: list[ScopedEntity] = []
    for subject in plan.subjects if plan is not None else []:
        scoped = ScopedEntity(
            entity_id=subject.entity_id,
            name=subject.name,
            type=subject.type,
            how=subject.how,
            said=subject.said,
            confidence=subject.confidence,
            lifecycle=lifecycles.get(subject.entity_id),
        )
        (excluded if _excluded(text, subject.said) else subjects).append(scoped)
    for thing in excluded:
        constraints.append(
            ScopeConstraint(
                kind="exclude", said=thing.said or thing.name, value=str(thing.entity_id), hard=True
            )
        )
    acting = goal.code == "act" and any(a.changes_systems for a in actions)
    migrating = goal.code == "plan_migration" or any(a.code == "migrate" for a in actions)
    target = _target(text) if migrating else None
    if target:
        constraints.append(ScopeConstraint(kind="target", said=target, value=target, hard=True))
    for constraint in plan.constraints if plan is not None else []:
        if constraint.origin == "asked" and constraint.kind in ("services", "sources"):
            constraints.append(
                ScopeConstraint(
                    kind=constraint.kind,
                    said="asked",
                    value=[str(v) for v in constraint.value]
                    if isinstance(constraint.value, list)
                    else constraint.value,
                    hard=True,
                )
            )
    held, origin = _environment(plan, constraints, environments)
    period = None
    if plan is not None:
        period = ScopePeriod(
            since=plan.period.since,
            until=plan.period.until,
            origin=plan.period.origin,
            said=plan.period.said,
            explicit=plan.period.origin != "kind",
        )
    sources = [
        uuid.UUID(str(v))
        for c in (plan.constraints if plan is not None else [])
        if c.kind == "sources" and c.origin == "asked" and isinstance(c.value, list)
        for v in c.value
    ]

    missing: list[AmbiguityRead] = []
    if acting and not held and len(environments) > 1:
        missing.append(
            AmbiguityRead(
                kind="missing_environment",
                blocking=True,
                said="An action on systems, and the company runs several environments: which?",
                options=list(environments),
            )
        )
    if migrating and not target:
        missing.append(
            AmbiguityRead(
                kind="missing_target",
                blocking=True,
                said="A migration, and not where to: to what?",
            )
        )
    if acting and any(c.kind == "read_only" for c in constraints):
        missing.append(
            AmbiguityRead(
                kind="conflicting_constraints",
                blocking=True,
                said="It asks to change systems, and to change nothing.",
                options=["read_only", *[a.code for a in actions if a.changes_systems]],
            )
        )
    gone = [s for s in subjects if s.lifecycle in GONE]
    if gone:
        missing.append(
            AmbiguityRead(
                kind="subject_gone",
                blocking=True,
                said="What it is about is no longer in the company: removed or archived.",
                options=[s.name for s in gone],
            )
        )
    dormant = [s for s in subjects if s.lifecycle == DORMANT]
    if dormant:
        missing.append(
            AmbiguityRead(
                kind="subject_dormant",
                blocking=False,
                said="What it is about has been inactive for months: is it still what is used?",
                options=[s.name for s in dormant],
            )
        )
    if excluded and not subjects:
        missing.append(
            AmbiguityRead(
                kind="everything_excluded",
                blocking=True,
                said="Every thing it names, it excludes: about what, then?",
                options=[s.name for s in excluded],
            )
        )
    scope = IntentScope(
        entities=subjects,
        excluded=excluded,
        environments=held,
        environment_origin=origin,
        period=period,
        sources=sources,
        constraints=constraints,
        missing=[a.kind for a in missing],
    )
    return scope, missing
