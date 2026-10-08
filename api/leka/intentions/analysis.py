"""An intention's analysis (LEKA-388): what answers it, run on its context.

    understood (LEKA-385, 386) + context, judged ready (LEKA-387)
        │
        ▼
    select()     the capabilities its goal and kind call for — LEKA's own,
                 rules over the company model; an agent (agents/*.md) only
                 once a model can run it (LEKA-394): said skipped
        │
        ▼
    the parts each reads, read once (processing.py) — who owns it, what it
    depends on and what depends on it, the incidents, the changes, the
    documents, what LEKA already concluded, how well it is known
        │
        ▼
    execute()    each capability, isolated: its own budget, its error its
                 own — a failed or timed-out one is said, the others go on
        │
        ▼
    assemble()   one result, shaped for the decision interface: findings —
                 facts, each with the evidence it rests on — probable
                 causes, what it reaches, what is uncertain and missing,
                 how sure; every piece of evidence once, with where it
                 came from

CAPABILITY. A named, versioned function from MATERIAL to OUTPUT: the
intention as understood, the context's elements on the sides it reads
(technical, business, organizational, temporal), and the parts it
declared. Pure: tested in a millisecond, never touching the database.

EVIDENCE. Whatever a statement rests on — a thing, a relationship, an
event — with the sources that say it: the context element's provenance
when the context holds it (its sources, the records that stated it),
else the thing's own sources. An inference says it is one.

Words are English here, and each statement carries a code and its values:
the interface words them (French, English), as Insights does.
"""

from __future__ import annotations

import asyncio
import enum
import time
import uuid
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from leka.context import ContextElementRead
from leka.intelligence import KnowledgeQualityRead
from leka.knowledge import (
    ChangeFootprint,
    Dependencies,
    EntityBrief,
    EntityStanding,
    Impact,
    IncidentDetail,
    Responsibility,
)

# What a result is worth when its context is limited: a fact read from a
# context with warnings is a little less sure.
LIMITED = 0.85
# How many things a statement names at most.
NAMED = 5


class Part(enum.StrEnum):
    """What a capability reads, beyond its context."""

    STANDING = "standing"
    OWNERS = "owners"
    RESPONSIBILITY = "responsibility"
    DOWNSTREAM = "downstream"
    UPSTREAM = "upstream"
    IMPACT = "impact"
    INCIDENTS = "incidents"
    CHANGES = "changes"
    FINDINGS = "findings"
    QUALITY = "quality"


# ── what a capability reads ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Subject:
    """A thing the intention is about, as its scope resolved it."""

    id: uuid.UUID
    name: str
    type: str
    lifecycle: str | None = None


@dataclass(frozen=True)
class Asked:
    """The intention, as the analysis reads it."""

    id: uuid.UUID
    text: str
    mode: str
    kind: str
    goal: str
    actions: tuple[tuple[str, bool], ...] = ()
    subjects: tuple[Subject, ...] = ()
    since: datetime | None = None
    until: datetime | None = None
    environment: str | None = None
    constraints: tuple[tuple[str, object, bool], ...] = ()

    @property
    def acting(self) -> bool:
        """It asks to change systems: a person decides, never LEKA."""
        return any(changes for _, changes in self.actions)


@dataclass(frozen=True)
class FindingBrief:
    """What LEKA already concluded about a thing (LEKA-377 and after)."""

    id: uuid.UUID
    code: str
    category: str
    severity: str
    statement: str
    subject_id: uuid.UUID | None
    subject_name: str
    first_seen_at: datetime
    params: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceRef:
    id: uuid.UUID | None
    kind: str | None
    name: str | None


@dataclass(frozen=True)
class Material:
    """What an analysis read, once, for all its capabilities. A part not
    read is absent: the capabilities that need it are skipped."""

    asked: Asked
    now: datetime
    readiness: str
    elements: tuple[ContextElementRead, ...] = ()
    parts: frozenset[Part] = frozenset()
    standing: Mapping[uuid.UUID, EntityStanding] = field(default_factory=dict)
    status: Mapping[uuid.UUID, str] = field(default_factory=dict)
    owners: Mapping[uuid.UUID, tuple[EntityBrief, ...]] = field(default_factory=dict)
    responsibility: Mapping[uuid.UUID, Responsibility] = field(default_factory=dict)
    downstream: Mapping[uuid.UUID, Dependencies] = field(default_factory=dict)
    upstream: Mapping[uuid.UUID, Dependencies] = field(default_factory=dict)
    impact: Impact | None = None
    incidents: tuple[IncidentDetail, ...] = ()
    changes: tuple[ChangeFootprint, ...] = ()
    findings: tuple[FindingBrief, ...] = ()
    quality: Mapping[uuid.UUID, KnowledgeQualityRead] = field(default_factory=dict)
    # Each thing's sources, for evidence the context does not hold.
    sources: Mapping[uuid.UUID, tuple[SourceRef, ...]] = field(default_factory=dict)

    def on(self, sides: frozenset[str], side_of: Callable[[str], str]) -> Material:
        """The material a capability receives: the context's elements on
        the sides it reads — every one when it names none."""
        if not sides:
            return self
        kept = tuple(
            e for e in self.elements if e.kind == "relationship" or side_of(e.ref_type) in sides
        )
        return Material(**{**self.__dict__, "elements": kept})


# ── what a capability says ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Evidence:
    """One thing a statement rests on, and where it came from."""

    id: str
    kind: str  # record, entity, event, inference
    label: str
    ref_type: str | None = None
    ref_id: uuid.UUID | None = None
    sources: tuple[SourceRef, ...] = ()
    records: tuple[str, ...] = ()
    origin: str | None = None
    confidence: float | None = None
    detail: str | None = None
    at: datetime | None = None
    # What its label is made of, for the interface to word: a tie's ends,
    # a finding's code and values.
    params: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Note:
    """A sentence the interface words: its code, its values — and in
    English."""

    code: str
    text: str
    params: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Statement:
    """A fact: what a source says, or LEKA observed."""

    id: str
    code: str
    text: str
    params: Mapping[str, object] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Cause:
    """A hypothesis: what may explain it, and how sure."""

    id: str
    code: str
    label: str
    basis: str  # stated, inferred
    why: str
    confidence: float | None
    ref_type: str | None = None
    ref_id: uuid.UUID | None = None
    params: Mapping[str, object] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImpactItem:
    ref_type: str
    ref_id: uuid.UUID
    name: str


@dataclass(frozen=True)
class ImpactArea:
    """What it reaches, of one kind: dependents, applications, business."""

    code: str
    items: tuple[ImpactItem, ...]


@dataclass(frozen=True)
class Output:
    """What one capability concluded."""

    findings: tuple[Statement, ...] = ()
    causes: tuple[Cause, ...] = ()
    impact: tuple[ImpactArea, ...] = ()
    risk: str | None = None
    risk_basis: Note | None = None
    uncertainties: tuple[Note, ...] = ()
    missing: tuple[Note, ...] = ()
    summary: Note | None = None
    # How sure it is of what it says; none when it said nothing.
    confidence: float | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class Capability:
    """A named, versioned analysis an intention may need."""

    name: str
    version: int
    summary: str
    # What calls for it: the goals (LEKA-385), the kinds (LEKA-373).
    goals: frozenset[str]
    kinds: frozenset[str] = frozenset()
    # The sides of the context it reads; none: all.
    sides: frozenset[str] = frozenset()
    reads: frozenset[Part] = frozenset()
    run: Callable[[Material], Output] | None = None
    # rules: LEKA's own; model: written by a language model from what the
    # rules found (LEKA-394), run after them.
    method: str = "rules"
    budget: float = 15.0
    # Run whatever the goal: what any answer starts from.
    always: bool = False


@dataclass(frozen=True)
class Choice:
    """A capability considered for an intention, and why it runs or not."""

    name: str
    version: int
    method: str
    chosen: bool
    reason: str  # always, goal, kind, acting · no_model, disabled, not_called


@dataclass(frozen=True)
class StepOutcome:
    """What came of running one capability."""

    name: str
    version: int
    status: str  # succeeded, failed, timed_out, skipped
    duration_ms: int = 0
    error: str | None = None
    reason: str | None = None
    output: Output | None = None


@dataclass(frozen=True)
class Point:
    """One thing the answer says, and what it rests on: the ids of the
    findings, causes and evidence it cites."""

    text: str
    cites: tuple[str, ...]


@dataclass(frozen=True)
class Answer:
    """The analysis, answered in words by a language model (LEKA-394): only
    what the analysis holds, each point citing what it rests on."""

    text: str
    points: tuple[Point, ...]
    caveats: tuple[str, ...]
    provider: str
    model: str
    version: str


@dataclass(frozen=True)
class Recommendation:
    """What LEKA proposes to do (LEKA-389) — never a fact: a proposal, from
    the findings and causes it names, that a person decides on."""

    id: str
    code: str
    text: str
    action: str  # rollback, change, monitor, other
    changes_systems: bool
    priority: str  # high, medium, low
    risk: str  # high, medium, low, unknown
    reversible: bool | None
    confidence: float | None
    why: Note
    params: Mapping[str, object] = field(default_factory=dict)
    # The findings and causes it follows from; the evidence they rest on.
    basis: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    target: ImpactItem | None = None


@dataclass(frozen=True)
class Result:
    """The analysis, whole: what the decision interface reads."""

    status: str  # complete, partial, inconclusive, failed
    summary: tuple[Note, ...]
    findings: tuple[tuple[str, Statement], ...]
    causes: tuple[tuple[str, Cause], ...]
    impact: tuple[ImpactArea, ...]
    risk: str
    risk_basis: Note | None
    uncertainties: tuple[Note, ...]
    missing: tuple[Note, ...]
    confidence: float | None
    support: tuple[Note, ...]
    evidence: tuple[Evidence, ...]
    # Written by a model from all of the above, when one can (LEKA-394).
    answer: Answer | None = None
    # What LEKA proposes, apart from what it found (LEKA-389, recommend.py).
    recommendations: tuple[Recommendation, ...] = ()


# ── selecting ────────────────────────────────────────────────────────────────


def select(
    asked: Asked,
    capabilities: Sequence[Capability],
    *,
    model: bool = False,
    disabled: frozenset[str] = frozenset(),
) -> list[Choice]:
    """The capabilities its goal and kind call for — and every other one,
    said not called. An agent waits for a model (LEKA-394); one the
    workspace turned off (LEKA-393) is not run, said so."""
    chosen: list[Choice] = []
    for capability in capabilities:
        if capability.name in disabled:
            chosen.append(
                Choice(capability.name, capability.version, capability.method, False, "disabled")
            )
            continue
        reason: str | None = None
        if capability.always:
            reason = "always"
        elif asked.goal in capability.goals:
            reason = "goal"
        elif asked.kind in capability.kinds:
            reason = "kind"
        elif asked.acting and "act" in capability.goals:
            reason = "acting"
        if reason is not None and capability.method == "model" and not model:
            chosen.append(
                Choice(capability.name, capability.version, capability.method, False, "no_model")
            )
            continue
        chosen.append(
            Choice(
                capability.name,
                capability.version,
                capability.method,
                reason is not None,
                reason or "not_called",
            )
        )
    return chosen


# ── running ──────────────────────────────────────────────────────────────────


async def execute(capability: Capability, material: Material) -> StepOutcome:
    """One capability, isolated: never raises. Missing what it reads, it
    is skipped; over its budget, timed out; raising, failed."""
    if capability.run is None:
        return StepOutcome(capability.name, capability.version, "skipped", reason="no_model")
    if not capability.reads <= material.parts:
        return StepOutcome(capability.name, capability.version, "skipped", reason="no_material")
    started = time.monotonic()
    try:
        output = await asyncio.wait_for(
            asyncio.to_thread(capability.run, material), timeout=capability.budget
        )
    except TimeoutError:
        return StepOutcome(
            capability.name,
            capability.version,
            "timed_out",
            duration_ms=_since(started),
            error="TimeoutError",
        )
    except Exception as error:
        return StepOutcome(
            capability.name,
            capability.version,
            "failed",
            duration_ms=_since(started),
            error=type(error).__name__,
        )
    return StepOutcome(
        capability.name,
        capability.version,
        "succeeded",
        duration_ms=_since(started),
        output=output,
    )


def _since(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


# ── assembling ───────────────────────────────────────────────────────────────

RISKS = {"high": 3, "medium": 2, "low": 1, "unknown": 0}


def assemble(
    outcomes: Sequence[StepOutcome],
    *,
    readiness: str,
    sources: int,
    contradictions: int,
    context_level: str | None,
    background: Collection[str] = (),
) -> Result:
    """One result from every capability that ran: what each found, under
    its name; every piece of evidence once; how sure, and on what.

    `background` names the capabilities that set the scene — what the thing
    is, how well it is known — without answering: what they find does not
    make an analysis conclusive, unless nothing else ran."""
    ran = [o for o in outcomes if o.status != "skipped"]
    done = [o for o in ran if o.status == "succeeded" and o.output is not None]
    outputs = [(o.name, o.output) for o in done if o.output is not None]
    findings = tuple((name, s) for name, out in outputs for s in out.findings)
    causes = tuple((name, c) for name, out in outputs for c in out.causes)
    areas: dict[str, dict[uuid.UUID, ImpactItem]] = {}
    for _, out in outputs:
        for area in out.impact:
            held = areas.setdefault(area.code, {})
            for reached in area.items:
                held.setdefault(reached.ref_id, reached)
    impact = tuple(ImpactArea(code, tuple(items.values())) for code, items in areas.items())
    risked = [out for _, out in outputs if out.risk]
    worst = max(risked, key=lambda out: RISKS.get(out.risk or "unknown", 0), default=None)
    evidence: dict[str, Evidence] = {}
    for _, out in outputs:
        for item in out.evidence:
            evidence.setdefault(item.id, item)
    missing = [n for _, out in outputs for n in out.missing]
    for outcome in ran:
        if outcome.status != "succeeded":
            missing.append(
                Note(
                    f"capability.{outcome.status}",
                    f"{outcome.name} did not finish: {outcome.status.replace('_', ' ')}.",
                    {"capability": outcome.name, "error": outcome.error},
                )
            )
    sure = [out.confidence for _, out in outputs if out.confidence is not None]
    confidence = (
        round(sum(sure) / len(sure) * (LIMITED if readiness == "limited" else 1.0), 3)
        if sure
        else None
    )
    if not done:
        status = "failed"
    elif len(done) < len(ran):
        status = "partial"
    elif not any(
        out.findings or out.causes
        for name, out in outputs
        if name not in background or all(o.name in background for o in ran)
    ):
        status = "inconclusive"
    else:
        status = "complete"
    support = (
        Note(
            "support.sources",
            f"{sources} source(s) behind its context.",
            {"count": sources, "established": sources > 0},
        ),
        Note(
            "support.contradictions",
            f"{contradictions} contradiction(s) between them.",
            {"count": contradictions, "established": contradictions == 0},
        ),
        Note(
            "support.context",
            f"Its context is {readiness}, its quality {context_level or 'unknown'}.",
            {"readiness": readiness, "level": context_level, "established": readiness == "ready"},
        ),
    )
    return Result(
        status=status,
        summary=tuple(out.summary for _, out in outputs if out.summary is not None),
        findings=findings,
        causes=causes,
        impact=impact,
        risk=(worst.risk or "unknown") if worst else "unknown",
        risk_basis=worst.risk_basis if worst else None,
        uncertainties=tuple(n for _, out in outputs for n in out.uncertainties),
        missing=tuple(missing),
        confidence=confidence,
        support=support,
        evidence=tuple(evidence.values()),
    )


# ── evidence ─────────────────────────────────────────────────────────────────


class Proofs:
    """The evidence of one capability: each thing, relationship or event
    it cites, once, with where it came from — the context's word on it when
    the context holds it, else the thing's own sources."""

    def __init__(self, material: Material) -> None:
        self._material = material
        self._found: dict[str, Evidence] = {}
        self._entities = {e.ref_id: e for e in material.elements if e.kind == "entity"}
        self._ties: dict[tuple[uuid.UUID, uuid.UUID, str], ContextElementRead] = {}
        for element in material.elements:
            tie = element.relationship
            if element.kind == "relationship" and tie is not None:
                self._ties[(tie.start.id, tie.end.id, tie.type)] = element

    @property
    def all(self) -> tuple[Evidence, ...]:
        return tuple(self._found.values())

    def _keep(self, evidence: Evidence) -> str:
        self._found.setdefault(evidence.id, evidence)
        return evidence.id

    def _held(self, element: ContextElementRead) -> tuple[tuple[SourceRef, ...], tuple[str, ...]]:
        provenance = element.provenance
        return (
            tuple(SourceRef(s.source_id, s.kind, s.name) for s in provenance.sources),
            tuple(s.record_id for s in provenance.sources if s.record_id),
        )

    def entity(self, thing: EntityBrief | Subject, *, detail: str | None = None) -> str:
        """A thing: what the context says of it, or its own sources."""
        element = self._entities.get(thing.id)
        kind = thing.type.value if hasattr(thing.type, "value") else str(thing.type)
        if element is not None:
            sources, records = self._held(element)
            return self._keep(
                Evidence(
                    id=f"entity:{thing.id}",
                    kind="entity",
                    label=thing.name,
                    ref_type=kind,
                    ref_id=thing.id,
                    sources=sources,
                    records=records,
                    origin=element.provenance.origin,
                    confidence=element.provenance.confidence,
                    detail=detail or element.text,
                    at=element.provenance.last_seen_at,
                )
            )
        return self._keep(
            Evidence(
                id=f"entity:{thing.id}",
                kind="entity",
                label=thing.name,
                ref_type=kind,
                ref_id=thing.id,
                sources=self._material.sources.get(thing.id, ()),
                detail=detail,
            )
        )

    def tie(
        self,
        start: EntityBrief | Subject,
        end: EntityBrief | Subject,
        kind: str,
        *,
        origin: str | None = None,
        confidence: float | None = None,
        label: str | None = None,
    ) -> str:
        """A relationship: the records that stated it, or the rule that
        inferred it."""
        element = self._ties.get((start.id, end.id, kind))
        said = label or f"{start.name} {kind.replace('_', ' ')} {end.name}"
        ends = {"from": start.name, "to": end.name}
        if element is not None:
            sources, records = self._held(element)
            inferred = element.provenance.origin == "inferred"
            return self._keep(
                Evidence(
                    id=f"tie:{start.id}:{kind}:{end.id}",
                    kind="inference" if inferred else "record",
                    label=said,
                    ref_type=kind,
                    sources=sources,
                    records=records,
                    origin=element.provenance.origin,
                    confidence=element.provenance.confidence,
                    detail="; ".join(element.provenance.evidence[:2]) or None,
                    at=element.provenance.changed_at,
                    params=ends,
                )
            )
        return self._keep(
            Evidence(
                id=f"tie:{start.id}:{kind}:{end.id}",
                kind="inference" if origin == "inferred" else "record",
                label=said,
                ref_type=kind,
                sources=self._material.sources.get(end.id, ())
                or self._material.sources.get(start.id, ()),
                origin=origin,
                confidence=confidence,
                params=ends,
            )
        )

    def event(self, thing: EntityBrief, *, at: datetime | None, detail: str | None = None) -> str:
        """Something that happened: an incident, a deployment, a change."""
        element = self._entities.get(thing.id)
        sources, records = (
            self._held(element)
            if element is not None
            else (
                self._material.sources.get(thing.id, ()),
                (),
            )
        )
        return self._keep(
            Evidence(
                id=f"event:{thing.id}",
                kind="event",
                label=thing.name,
                ref_type=thing.type.value if hasattr(thing.type, "value") else str(thing.type),
                ref_id=thing.id,
                sources=sources,
                records=records,
                detail=detail,
                at=at,
            )
        )

    def finding(self, found: FindingBrief) -> str:
        """What LEKA already concluded: an inference of its own."""
        return self._keep(
            Evidence(
                id=f"finding:{found.id}",
                kind="inference",
                label=found.statement[:200],
                ref_type="finding",
                ref_id=found.id,
                origin="leka",
                detail=f"{found.category} · {found.severity}",
                at=found.first_seen_at,
                params={"code": found.code, "params": dict(found.params)},
            )
        )


def names(things: Iterable[EntityBrief | Subject]) -> list[str]:
    return [t.name for t in things][:NAMED]
