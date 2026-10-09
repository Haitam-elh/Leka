"""The capability router (LEKA-398), pure: which of LEKA's capabilities an
intention should go to — from what it wants, what it is about, the context
it was given, and what can be used here by this person — each candidate
with the signals that ranked it, each one left out with why.

    the intention, as understood    goal, kind, mode, what it is about,
                                    its words; whether it is clear
    its context                     the kinds of things it holds, the
                                    kinds of sources they came from
    the catalogue, for this person  each capability, available or not, why
            │
            ▼
    signals      goal 3 · kind 2 · each type it acts on 1 (2 at most) ·
                 each word in common 1 (3 at most) · its types in the
                 context 1 · its sources in the context 1 · a request to
                 act and a capability that proposes 1 · deprecated -1
    eligible     scoring MIN_SCORE or more, on what is asked (goal, kind
                 or words) — never on context alone
    excluded     unavailable or not permitted, or against a policy: never
                 routed to, said why. POLICY: a question never goes to a
                 capability that proposes actions — only a request to act
    selected     the best, and those within one point of it — three at most
    outcome      routed · fallback (LEKA's analysis, which always runs) ·
                 clarify (the intention is not clear, or nothing it says
                 points anywhere: what to ask, and what it could mean)

Capabilities that always run (`always`) run with every analysis: they are
not routed to, and said so. Nothing here reads a database.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from leka.capabilities.definition import Availability, Definition, Kind, Lifecycle, Reason

ROUTING_VERSION = 1
# What a capability must score, on what is asked, to be routed to.
MIN_SCORE = 3.0
# Selected with the best: within this of it.
CLOSE = 1.0
MOST_SELECTED = 3
# Suggested when an intention must be clarified.
MOST_SUGGESTED = 3

WEIGHTS: Mapping[str, float] = {
    "goal": 3.0,
    "kind": 2.0,
    "entity": 1.0,
    "words": 1.0,
    "context_types": 1.0,
    "context_sources": 1.0,
    "mode": 1.0,
    "deprecated": -1.0,
}
# What is asked: a capability routed to on context alone is not.
ASKED = frozenset({"goal", "kind", "entity", "words"})
MOST_ENTITIES = 2
MOST_WORDS = 3
# LEKA's own analysis: what every intention gets, routed or not.
FALLBACK = "analysis"


@dataclass(frozen=True)
class RouteQuery:
    """An intention, as the router reads it."""

    text: str = ""
    goal: str | None = None
    kind: str | None = None
    mode: str = "question"  # question, request
    acting: bool = False  # it asks to change systems
    entity_types: frozenset[str] = frozenset()
    clear: bool = True
    # What LEKA would ask, when it is not clear.
    questions: tuple[str, ...] = ()
    # Its context: the types of the things it holds, the kinds of the
    # sources they came from.
    context_types: frozenset[str] = frozenset()
    context_sources: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Signal:
    code: str
    points: float
    detail: str | None = None


@dataclass(frozen=True)
class Candidate:
    definition: Definition
    availability: Availability
    signals: tuple[Signal, ...]
    score: float
    eligible: bool  # scores enough on what is asked
    selected: bool = False
    # An agent's inputs it must be given and the intention does not say.
    needs_inputs: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return self.definition.key


@dataclass(frozen=True)
class Routing:
    outcome: str  # routed, fallback, clarify
    selected: tuple[Candidate, ...]
    candidates: tuple[Candidate, ...]  # ranked, available
    excluded: tuple[Candidate, ...]  # matched, but cannot be used here
    background: tuple[str, ...]  # run with every analysis
    fallback: str | None = None
    # Why it fell back, or must be clarified.
    why: str | None = None
    questions: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = field(default_factory=tuple)
    version: int = ROUTING_VERSION


def words(text: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", plain) if len(w) > 3}


def signals_of(definition: Definition, query: RouteQuery) -> tuple[Signal, ...]:
    """Why it fits — each signal with its points."""
    d = definition
    found: list[Signal] = []
    if query.goal and query.goal in d.goals:
        found.append(Signal("goal", WEIGHTS["goal"], query.goal))
    if query.kind and query.kind in d.kinds:
        found.append(Signal("kind", WEIGHTS["kind"], query.kind))
    for kind in [t for t in d.entity_types if t in query.entity_types][:MOST_ENTITIES]:
        found.append(Signal("entity", WEIGHTS["entity"], kind))
    asked = words(query.text)
    if asked:
        said = words(" ".join((d.title, d.summary, *d.examples)))
        common = sorted(asked & said)[:MOST_WORDS]
        if common:
            found.append(Signal("words", WEIGHTS["words"] * len(common), ", ".join(common)))
    if d.entity_types and set(d.entity_types) & query.context_types:
        held = sorted(set(d.entity_types) & query.context_types)
        found.append(Signal("context_types", WEIGHTS["context_types"], ", ".join(held)))
    if d.sources and all(set(group) & query.context_sources for group in d.sources):
        read = sorted({k for group in d.sources for k in group} & query.context_sources)
        found.append(Signal("context_sources", WEIGHTS["context_sources"], ", ".join(read)))
    if d.mode == "proposes_action" and query.acting:
        found.append(Signal("mode", WEIGHTS["mode"], "request"))
    if d.lifecycle is Lifecycle.DEPRECATED:
        found.append(Signal("deprecated", WEIGHTS["deprecated"]))
    return tuple(found)


def needs_inputs(definition: Definition) -> tuple[str, ...]:
    """What an agent or a workflow must be given that an intention does not
    say: its required inputs — asked of the person before it runs."""
    if definition.kind not in (Kind.AGENT, Kind.WORKFLOW):
        return ()
    return tuple(i.name for i in definition.contract.inputs if i.required)


def policed(definition: Definition, query: RouteQuery, able: Availability) -> Availability:
    """Its availability, with what LEKA's policies forbid for this
    intention: a question never goes to what proposes actions."""
    if definition.mode == "proposes_action" and not query.acting:
        policy = Reason("policy", {"rule": "proposes_actions_to_a_question"})
        return Availability(False, (*able.reasons, policy), able.notes)
    return able


def route(
    query: RouteQuery,
    definitions: Sequence[Definition],
    availabilities: Mapping[str, Availability],
) -> Routing:
    """Where an intention goes, and why — every capability it could go to
    ranked, every one it cannot said why."""
    background: list[str] = []
    ranked: list[Candidate] = []
    excluded: list[Candidate] = []
    for d in definitions:
        if d.lifecycle is Lifecycle.RETIRED:
            continue
        if d.always:
            background.append(d.key)
            continue
        signals = signals_of(d, query)
        score = round(sum(s.points for s in signals), 2)
        on_asked = any(s.code in ASKED for s in signals)
        able = policed(d, query, availabilities.get(d.key, Availability(False)))
        candidate = Candidate(
            d,
            able,
            signals,
            score,
            eligible=on_asked and score >= MIN_SCORE,
            needs_inputs=needs_inputs(d),
        )
        if not on_asked:
            continue
        (ranked if able.available else excluded).append(candidate)

    def order(c: Candidate) -> tuple[float, int, str]:
        return (-c.score, -len({s.code for s in c.signals}), c.key)

    ranked.sort(key=order)
    excluded.sort(key=order)
    eligible = [c for c in ranked if c.eligible]
    if not query.clear:
        return Routing(
            "clarify",
            (),
            tuple(ranked),
            tuple(excluded),
            tuple(background),
            why="unclear",
            questions=query.questions,
            suggestions=tuple(c.key for c in ranked[:MOST_SUGGESTED]),
        )
    if eligible:
        best = eligible[0].score
        close = [c for c in eligible if best - c.score <= CLOSE][:MOST_SELECTED]
        keys = {c.key for c in close}
        marked = tuple(replace(c, selected=c.key in keys) for c in ranked)
        return Routing(
            "routed",
            tuple(c for c in marked if c.selected),
            marked,
            tuple(excluded),
            tuple(background),
        )
    if query.goal in (None, "", "unknown"):
        return Routing(
            "clarify",
            (),
            tuple(ranked),
            tuple(excluded),
            tuple(background),
            why="no_goal",
            questions=query.questions,
            suggestions=tuple(c.key for c in ranked[:MOST_SUGGESTED]),
        )
    better = any(c.eligible for c in excluded)
    return Routing(
        "fallback",
        (),
        tuple(ranked),
        tuple(excluded),
        tuple(background),
        fallback=FALLBACK,
        why="excluded" if better else "no_match",
    )


# ── kept ────────────────────────────────────────────────────────────────────


def _candidate(c: Candidate) -> dict[str, object]:
    d = c.definition
    return {
        "key": d.key,
        "title": d.title,
        "kind": d.kind.value,
        "category": d.category,
        "score": c.score,
        "eligible": c.eligible,
        "selected": c.selected,
        "available": c.availability.available,
        "reasons": [{"code": r.code, **r.detail} for r in c.availability.reasons],
        "signals": [{"code": s.code, "points": s.points, "detail": s.detail} for s in c.signals],
        "needs_inputs": list(c.needs_inputs),
    }


def query_said(query: RouteQuery) -> dict[str, object]:
    """What the router read, as kept."""
    return {
        "text": query.text[:500],
        "goal": query.goal,
        "kind": query.kind,
        "mode": query.mode,
        "acting": query.acting,
        "entity_types": sorted(query.entity_types),
        "clear": query.clear,
        "context_types": sorted(query.context_types),
        "context_sources": sorted(query.context_sources),
    }


def decision_said(routing: Routing) -> dict[str, object]:
    """How it decided, as kept: every candidate, every one left out."""
    return {
        "candidates": [_candidate(c) for c in routing.candidates],
        "excluded": [_candidate(c) for c in routing.excluded],
        "background": list(routing.background),
        "fallback": routing.fallback,
        "why": routing.why,
        "questions": list(routing.questions),
        "suggestions": list(routing.suggestions),
    }
