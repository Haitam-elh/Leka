"""The intelligence engine's frame (LEKA-377): what an analysis is, what it
reads, what it says, and how one runs beside the others.

    ANALYZER    a named, versioned analysis: what it reads (the company
                model, the contexts), how it reasons (rules; a model, once
                the gateway exists), how long it may take — and a function
                from MATERIAL to DRAFTS
    MATERIAL    what a run read, once, for all its analyses: the company
                model as the architecture reads it — its cards, their
                states and teams, the links between them — and the contexts
                where they stand. Read before any analysis runs: an
                analysis never touches the database, so it is a pure
                function, tested in a millisecond
    DRAFT       one conclusion: about what, how bad, how sure, in a code and
                its values and in an English sentence, with what shows it
    PROPOSAL    one enrichment of the company model (LEKA-380): a
                relationship or an attribute the model lacks, how sure,
                what shows it — kept as a candidate until it is validated
                or rejected
    OUTCOME     what came of running one analysis: its drafts and its
                proposals — or the error's type, its time out, why it was
                skipped

ISOLATION. `execute` runs one analysis and never raises: an exception is a
`failed` outcome, a budget exceeded `timed_out`, missing material or a
model-assisted analysis with no model gateway `skipped`. The run goes on
with the next. A failed analysis resolves none of its findings — not
seeing them is not knowing they are gone — nor withdraws its proposals.

MODEL-ASSISTED analyses are declared like the others (`method = model`) and
skipped, said so, until leka.capabilities calls a model (architecture rule
7): the frame does not change the day one runs.
"""

from __future__ import annotations

import asyncio
import enum
import hashlib
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from leka.knowledge import ArchitectureRead, ChangeFootprint, EntityBrief, EntityStanding


class Reads(enum.StrEnum):
    """What an analysis reads."""

    MODEL = "model"
    CONTEXT = "context"
    # The changes of the last HISTORY, each with its footprint (LEKA-378).
    CHANGES = "changes"


class Method(enum.StrEnum):
    """How it reasons: rules over the material, or a model."""

    RULES = "rules"
    MODEL = "model"


class Severity(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


WEIGHT = {Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1}


@dataclass(frozen=True)
class Subject:
    """What a finding is about, or involves: an entity, a context."""

    type: str
    id: uuid.UUID | None
    name: str
    kind: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "type": self.type,
            "id": str(self.id) if self.id else None,
            "name": self.name,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class Evidence:
    """One thing that shows a finding: what it is, and what it shows
    (English)."""

    kind: str
    name: str
    detail: str
    id: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "id": self.id, "name": self.name, "detail": self.detail}


@dataclass(frozen=True)
class Draft:
    """One conclusion, before it is kept."""

    key: str
    code: str
    severity: Severity
    subject: Subject
    statement: str
    params: Mapping[str, object] = field(default_factory=dict)
    # How much it weighs within its severity: 0 to 1.
    score: float = 0.0
    confidence: float = 1.0
    related: tuple[Subject, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    # The kinds of the sources it rests on: github, aws…
    sources: tuple[str, ...] = ()
    # The context version it read, when it read one.
    context_version: int | None = None

    @property
    def rank(self) -> int:
        """Severity first, then its score: 300 to 399 for a high one."""
        return WEIGHT[self.severity] * 100 + round(max(0.0, min(self.score, 1.0)) * 99)


@dataclass(frozen=True)
class Proposal:
    """One enrichment of the company model, before it is kept as a
    candidate (LEKA-380): a relationship from one entity to another, or an
    attribute of one — about `subject`, the thing it enriches.

    `current` is what the model says of that attribute now; `overrides`,
    that a source says it — accepting the proposal would replace what a
    source says, and only a person may."""

    key: str
    # relationship, semantic, organisation, business
    family: str
    code: str
    subject: Subject
    statement: str
    confidence: float
    relationship: str | None = None
    start: Subject | None = None
    end: Subject | None = None
    attribute: str | None = None
    value: object = None
    current: object = None
    overrides: bool = False
    params: Mapping[str, object] = field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()
    sources: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "relationship" if self.relationship else "attribute"


@dataclass(frozen=True)
class ContextStanding:
    """Where one context stands: what it is, whether it follows the model,
    how far behind, how good its latest version was judged."""

    id: uuid.UUID
    title: str
    status: str
    follow: bool
    version: int
    used_at: datetime | None
    stale_since: datetime | None
    pending: int
    level: str | None
    score: float | None


@dataclass(frozen=True)
class Material:
    """What a run read, once, for all its analyses. A part a run could not
    read is None — and the analyses that need it are skipped."""

    now: datetime
    built_at: datetime | None
    architecture: ArchitectureRead | None = None
    # Who owns each card's entity — the teams and people a source names —
    # read with the architecture, which names only a team.
    owners: Mapping[uuid.UUID, tuple[str, ...]] = field(default_factory=dict)
    # And, read with it (LEKA-379): what the model holds around each card's
    # entity — criticality, documents, the business — how many documents
    # the workspace has, and each source kind's family (connector category).
    standing: Mapping[uuid.UUID, EntityStanding] = field(default_factory=dict)
    documents: int | None = None
    categories: Mapping[str, str] = field(default_factory=dict)
    # And (LEKA-380): the owners named for each card's entity, with their
    # ids; the teams each maintainer is a member of.
    owned_by: Mapping[uuid.UUID, tuple[EntityBrief, ...]] = field(default_factory=dict)
    memberships: Mapping[uuid.UUID, tuple[EntityBrief, ...]] = field(default_factory=dict)
    contexts: tuple[ContextStanding, ...] | None = None
    changes: tuple[ChangeFootprint, ...] | None = None

    def has(self, reads: Reads) -> bool:
        if reads is Reads.MODEL:
            return self.architecture is not None
        if reads is Reads.CHANGES:
            return self.changes is not None
        return self.contexts is not None


@dataclass(frozen=True)
class Analyzer:
    """A named, versioned analysis. Raise `version` whenever what it
    concludes changes: the sweep runs every workspace again."""

    name: str
    version: int
    category: str
    method: Method
    reads: frozenset[Reads]
    summary: str
    run: Callable[[Material], Sequence[Draft | Proposal]]
    # Seconds it may take before it is given up on.
    budget: float = 30.0
    # Parts read when they can be, which only weigh what it concludes —
    # unread, it still runs (LEKA-379: a gap on what a change just touched).
    heeds: frozenset[Reads] = frozenset()

    @property
    def wants(self) -> frozenset[Reads]:
        return self.reads | self.heeds


@dataclass(frozen=True)
class Outcome:
    """What came of running one analysis."""

    status: str
    drafts: tuple[Draft, ...] = ()
    proposals: tuple[Proposal, ...] = ()
    duration_ms: int = 0
    error: str | None = None
    reason: str | None = None


def skip_reason(analyzer: Analyzer, material: Material) -> str | None:
    """Why an analysis cannot run on this material, if it cannot."""
    if analyzer.method is Method.MODEL:
        # No model gateway yet (leka.capabilities, architecture rule 7).
        return "no_model"
    if any(not material.has(reads) for reads in analyzer.reads):
        return "no_material"
    return None


async def execute(analyzer: Analyzer, material: Material) -> Outcome:
    """Run one analysis, isolated: never raises. Its drafts and its
    proposals deduplicated by key — the last one said wins."""
    reason = skip_reason(analyzer, material)
    if reason is not None:
        return Outcome(status="skipped", reason=reason)
    started = time.monotonic()
    try:
        said = await asyncio.wait_for(
            asyncio.to_thread(analyzer.run, material), timeout=analyzer.budget
        )
    except TimeoutError:
        return Outcome(status="timed_out", duration_ms=_since(started), error="TimeoutError")
    except Exception as error:
        return Outcome(status="failed", duration_ms=_since(started), error=type(error).__name__)
    drafts = {d.key: d for d in said if isinstance(d, Draft)}
    proposals = {p.key: p for p in said if isinstance(p, Proposal)}
    return Outcome(
        status="succeeded",
        drafts=tuple(drafts.values()),
        proposals=tuple(proposals.values()),
        duration_ms=_since(started),
    )


def catalogue_hash(analyzers: Sequence[Analyzer]) -> str:
    """The analyses and their versions, hashed: a new version, or a new
    analysis, is something every workspace runs again."""
    said = ";".join(f"{a.name}:{a.version}" for a in sorted(analyzers, key=lambda a: a.name))
    return hashlib.sha256(said.encode()).hexdigest()


def _since(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))
