"""Types the context module exposes (LEKA-370).

An assembled context is what the interactive loop hands to a model, and
what a person reads to know what LEKA knew. Every piece of it carries where
it came from, because an answer without evidence is a guess with better
grammar.

    ContextCreate      what is asked: a title, a purpose, a subject, roots,
                       how far, through what, how much
    ContextRequest     the same, settled: what a context asks the model for
    AssembledContext   the contract downstream services read (CONTRACT_VERSION):
                       one version of a context, its elements in order — each
                       with its provenance and why it is there — its sources,
                       and from which build of the model
    ContextRead        a context: what it is for, where it stands
    ContextVersionRead one assembly: when, by what, what it holds, or why not
    ContextDiff        what changed between two versions
    ElementRanking,    how each thing was ranked, signal by signal; what
    RankingReport,     was left out and why; what its sources disagree on
    ContextConflictRead  (LEKA-372)
    IntentAsk          an intention, as asked: its words, its scope (LEKA-373)
    IntentPlan         what LEKA reads of it: its kind, what it is about,
                       when, where, under what constraints — the structured
                       context request it makes — and what is missing
    ContextChange      what made a context be made again, or behind: what
                       the model changed of what it holds, or what of its
                       request or intention changed (LEKA-374)
    ContextFreshness   whether it is up to date, and if not since when and
                       why; whether it follows the model on its own
    ContextCheckRead   one time it was made again, and what came of it
    ContextExpand,     its request widened or narrowed — a new version
    ContextCompress
    ContextQuality     how good a version is (LEKA-375): complete, fresh,
                       to be relied on — each measure with what it was read
                       from — what it lacks, what it disagrees on and how
                       badly, what each retriever brought
    ContextFeedback*   what people said of an element, or of what is missing
    ContextContract    the contract, published: its version, what each part
                       is judged by, its JSON schema, what each ticket added
                       (LEKA-376)
    ElementInspection  one element of a version, inspected: what it is, its
                       history in the context, what quality says of it
    ElementEvidence    the source records it was read from

What a version holds was written once and is read back as it was, whatever
the model has become since: the types that read it take strings, not the
registry's enums, and ignore what a later contract adds — a snapshot must
stay readable after a kind is renamed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from leka.context.language import words
from leka.knowledge import RelationshipType

# The header a response says its contract in, and a client may ask one by
# (LEKA-376); the versions this API serves.
CONTRACT_HEADER = "Leka-Context-Contract"
SUPPORTED_CONTRACTS = frozenset({1})

# What AssembledContext promises. Raised when a field changes meaning or
# goes; a field added is no new contract. Each version keeps the one it
# was made under.
CONTRACT_VERSION = 1

# How much a context holds: elements — entities and the relationships
# among them. Enough to answer about a thing and what surrounds it; more
# is a model's whole neighbourhood, which no reader reads.
DEFAULT_BUDGET = 100
MAX_BUDGET = 500
MAX_DEPTH = 3
MAX_ROOTS = 10
# How far back the timeline reads (LEKA-371), in days, ending now or `until`.
DEFAULT_WINDOW_DAYS = 14
MAX_WINDOW_DAYS = 365
# Under this score a thing found is left out (LEKA-372): roots and anchors
# never are. Low enough that a thing found once, not first, still stays.
MIN_RELEVANCE = 0.05

SubjectType = Literal["entity", "intention", "request"]
ContextStatus = Literal["assembling", "assembled", "failed", "archived"]
# Why a version was made, or a check run (LEKA-374): created; a refresh
# asked; the model changed what it holds; its request widened, narrowed;
# its intention asked again.
Trigger = Literal["created", "refreshed", "changed", "expanded", "compressed", "reasked"]
# How good a context is (LEKA-375).
QualityLevel = Literal["high", "medium", "low", "unknown"]
Severity = Literal["critical", "warning", "info"]
MeasureName = Literal["completeness", "freshness", "confidence"]
Verdict = Literal["useful", "not_useful", "wrong", "missing"]
StrategyName = Literal["neighbourhood", "hybrid"]
# How things are found (LEKA-371): around the roots, by the request's words
# in the model and in the records' own text, by their time, on the ways
# between two roots.
RetrieverName = Literal["graph", "search", "content", "timeline", "paths"]
RETRIEVERS: tuple[RetrieverName, ...] = ("graph", "search", "content", "timeline", "paths")
# How much a retriever's findings may be weighed, against its own weight
# (LEKA-373: an intention's kind weighs them).
MAX_RETRIEVER_WEIGHT = 3.0


class ContextSubject(BaseModel):
    """What a context is the context of: an entity, an intention
    (LEKA-384), or a request made of nothing else."""

    model_config = ConfigDict(frozen=True)

    type: SubjectType
    id: str | None = Field(default=None, max_length=100)


class ContextCreate(BaseModel):
    """A context to assemble. Its roots must be the workspace's."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=300)
    purpose: str = Field(
        default="", max_length=2000, description="Why, in the asker's words: what is to be known."
    )
    subject: ContextSubject = Field(default_factory=lambda: ContextSubject(type="request"))
    roots: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=MAX_ROOTS,
        description="The entities it starts from. None: what its words find (hybrid).",
    )
    query: str | None = Field(
        default=None, max_length=500, description="What to search for; the purpose when none."
    )
    depth: int = Field(default=1, ge=1, le=MAX_DEPTH, description="How many steps away.")
    relationships: list[RelationshipType] = Field(
        default_factory=list, description="Only through these kinds; every kind when none."
    )
    environment: str | None = Field(
        default=None, max_length=100, description="Only what is true in this environment."
    )
    limit: int = Field(
        default=DEFAULT_BUDGET,
        ge=1,
        le=MAX_BUDGET,
        description="At most this many elements, the most relevant first.",
    )
    window_days: int = Field(
        default=DEFAULT_WINDOW_DAYS,
        ge=1,
        le=MAX_WINDOW_DAYS,
        description="How far back what happened is read, in days.",
    )
    until: datetime | None = Field(
        default=None, description="When what happened is read up to; now when none."
    )
    retrievers: list[RetrieverName] = Field(
        default_factory=list, description="Which to combine (hybrid); every one when none."
    )
    strategy: StrategyName = "hybrid"
    min_relevance: float = Field(
        default=MIN_RELEVANCE,
        ge=0,
        le=1,
        description="Under this score a thing found is left out — never a root (LEKA-372); "
        "0 keeps everything the budget holds.",
    )
    weights: dict[RetrieverName, float] = Field(
        default_factory=dict,
        description="Each retriever's findings weighed this many times its own weight "
        "(LEKA-373); 1 when not said.",
    )
    sources: list[uuid.UUID] = Field(
        default_factory=list,
        description="Only what these sources say — never a root (LEKA-373); every source "
        "when none.",
    )

    @model_validator(mode="after")
    def _starts_somewhere(self) -> ContextCreate:
        if self.strategy == "neighbourhood" and not self.roots:
            raise ValueError("A neighbourhood starts from roots.")
        if self.retrievers and self.strategy != "hybrid":
            raise ValueError("Retrievers are combined by the hybrid strategy only.")
        if not self.roots and not words(self.query or self.purpose):
            raise ValueError("Nothing to start from: give roots, or words that say something.")
        if any(not 0 <= weight <= MAX_RETRIEVER_WEIGHT for weight in self.weights.values()):
            raise ValueError(f"A retriever is weighed from 0 to {MAX_RETRIEVER_WEIGHT:g}.")
        return self


class ContextRequest(BaseModel):
    """What a context asks the model for, settled — kept with the context
    and with each version, so a version says what it answered."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    roots: list[uuid.UUID]
    query: str | None
    depth: int
    relationships: list[str]
    environment: str | None
    limit: int
    window_days: int
    until: datetime | None
    retrievers: list[str]
    strategy: str
    min_relevance: float = MIN_RELEVANCE
    weights: dict[str, float] = Field(default_factory=dict)
    sources: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _older(cls, data: object) -> object:
        """A request kept before LEKA-371 had none of these: they read empty
        — before LEKA-372, the default threshold; before LEKA-373, no
        weights and every source."""
        if isinstance(data, dict):
            return {
                "query": None,
                "window_days": DEFAULT_WINDOW_DAYS,
                "until": None,
                "retrievers": [],
                **data,
            }
        return data


class ContextStrategyRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(description="How the elements were gathered: neighbourhood.")
    version: int = Field(description="Raised each time the strategy gathers differently.")


class ElementSource(BaseModel):
    """A source an element came from: which, how it knows it — its key, or
    the record that said it — and its name when it still exists."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    source_id: uuid.UUID
    kind: str | None
    name: str | None = Field(description="None when the source has been deleted since.")
    key: str | None = Field(description="The key it goes by there (an entity).")
    record_id: str | None = Field(description="The record that stated it (a relationship).")


class ElementProvenance(BaseModel):
    """Where an element came from, as the model said it when the version
    was made."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    origin: str = Field(
        description="stated: its sources show it; inferred: an enrichment rule made it; "
        "accepted: LEKA proposed it and someone validated it (LEKA-380)."
    )
    rule: str | None = Field(description="The rule that inferred it — or stated.")
    confidence: float
    sources: list[ElementSource]
    evidence: list[str] = Field(description="What the records said, or why it was inferred.")
    inferred_from: list[uuid.UUID] = Field(description="The entities an inference read.")
    attributes: dict[str, dict[str, object]] = Field(
        description="Each attribute's origin: a source, or an enrichment rule and its confidence."
    )
    conflicts: list[dict[str, object]] = Field(
        description="What its sources disagree on, every value with who said it."
    )
    first_seen_at: datetime | None
    last_seen_at: datetime | None = Field(description="When a source last showed it (an entity).")
    changed_at: datetime | None = Field(description="When it last changed (a relationship).")


class RetrievalMatch(BaseModel):
    """One way an element was found (LEKA-371): by what, how high it ranked
    there, what that added to its relevance, and on what."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    retriever: str = Field(description="graph, search, content, timeline or paths.")
    rank: int = Field(description="Its place among what that retriever found, from 1.")
    score: float = Field(description="What it added to the relevance, before it is scaled.")
    detail: str | None = Field(
        description="On what: the words it holds, the steps, the event and when."
    )


class ElementReason(BaseModel):
    """Why an element is in the context."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    strategy: str
    role: Literal["root", "reached", "found", "tie"] = Field(
        description="root: asked for; reached: tied to a root or to what was found; found: by "
        "its words, its time, on a way — tied to nothing else; tie: a relationship between two."
    )
    depth: int | None = Field(
        description="Steps from the nearest root or anchor; a tie, its farther end's; none when "
        "tied to none."
    )
    root: uuid.UUID | None = Field(
        description="The root it was reached from — or, none asked, the best thing found."
    )
    via: uuid.UUID | None = Field(description="The relationship it was reached through.")
    retrievers: list[RetrievalMatch] = Field(
        description="Every way it was found, the surest first (LEKA-371)."
    )

    @model_validator(mode="before")
    @classmethod
    def _older(cls, data: object) -> object:
        """A reason kept before LEKA-371 says no retriever."""
        if isinstance(data, dict):
            return {"retrievers": [], **data}
        return data


class ElementEnd(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: uuid.UUID
    type: str
    key: str
    name: str


class ElementEntity(BaseModel):
    """An entity, as the model said it then."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    type: str
    key: str
    name: str
    attributes: dict[str, object]
    lifecycle: str
    version: int = Field(description="Its version in the model then.")
    confidence: float
    quality: float | None


class ElementRelationship(BaseModel):
    """A relationship, as the model said it then, both ends named."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    type: str
    start: ElementEnd = Field(description="Where it goes from.")
    end: ElementEnd = Field(description="Where it goes to.")
    confidence: float
    origin: str
    rule: str
    cross_source: bool
    attributes: dict[str, object]


SignalName = Literal[
    "asked",
    "retrieval",
    "proximity",
    "ends",
    "confidence",
    "quality",
    "freshness",
    "sources",
    "corroboration",
    "lifecycle",
    "consistency",
    "origin",
]


class RankingSignal(BaseModel):
    """One thing a rank was read from (LEKA-372)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str = Field(
        description="asked, retrieval, proximity, ends — how much it is about the request; "
        "confidence, quality, freshness, sources, corroboration, lifecycle, consistency, "
        "origin — how far it can be relied on."
    )
    axis: Literal["topic", "trust"]
    value: float | None = Field(
        description="0 to 1; none when nothing measures it — left out of its axis, never guessed."
    )
    weight: float = Field(description="What it counts for on its axis.")
    detail: dict[str, object] = Field(
        default_factory=dict,
        description="What it was read from: the retrievers and ranks, the steps, the days since "
        "a source showed it, the best source and its state, how many sources…",
    )
    said: str = Field(description="It, in words.")


class FoldedRead(BaseModel):
    """A thing folded into another: entity resolution linked them as
    probably the same (docs/resolution.md)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    ref_id: uuid.UUID
    label: str
    rule: str = Field(description="The rule that linked them.")
    confidence: float


class ElementRanking(BaseModel):
    """How an element was ranked (LEKA-372): its score, its place, and every
    signal it was read from."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    score: float = Field(
        description="What the order follows, 0 to 1: topic * (0.6 + 0.4 * trust) — for a "
        "relationship, its weaker end's score * the same factor of its own trust."
    )
    rank: int | None = Field(description="Its place among the entities kept, from 1.")
    topic: float = Field(description="How much it is about the request, 0 to 1.")
    trust: float | None = Field(description="How far it can be relied on, 0 to 1.")
    signals: list[RankingSignal]
    conflicts: list[str] = Field(
        default_factory=list, description="The ids of the conflicts it is part of."
    )
    duplicates: list[FoldedRead] = Field(
        default_factory=list, description="What was folded into it, probably the same thing."
    )


class LeftOutRead(BaseModel):
    """A thing found and left out (LEKA-372), and why."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    ref_id: uuid.UUID
    ref_type: str
    label: str
    reason: Literal["duplicate", "low_relevance", "out_of_scope", "budget"]
    score: float
    duplicate_of: uuid.UUID | None = Field(
        default=None, description="What it was folded into, when a duplicate."
    )
    said: str


class RankingReport(BaseModel):
    """How a version was ranked (LEKA-372): the policy, and what was left
    out — counted by why, and the best of it listed."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    version: int = Field(description="Raised each time the ranking ranks differently.")
    min_relevance: float
    trust_share: float = Field(description="How much trust can move a score: 0.4 is 40 %.")
    weights: dict[str, float] = Field(description="Each signal's weight on its axis.")
    left_out: dict[str, int] = Field(
        description="duplicate, low_relevance, out_of_scope (none of the sources asked says "
        "it, LEKA-373), budget — entities; ties — relationships left out with an end."
    )
    left: list[LeftOutRead] = Field(description="What was left out, the best first, at most 100.")


class ConflictValue(BaseModel):
    """One side of a conflict: a value, or a thing, and who says so."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    value: object
    ref_id: uuid.UUID | None = Field(default=None, description="The thing, when it is one.")
    by: list[str] = Field(description="The sources that say so, or the rule.")


class ContextConflictRead(BaseModel):
    """Something the context's sources disagree on (LEKA-372): said, every
    side with who says so — never silently merged."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    kind: Literal["attribute", "duplicates", "competing", "gone"] = Field(
        description="attribute — its sources give different values; duplicates — two things "
        "probably the same disagree; competing — two of a kind that admits one: owners, "
        "managers, leads, parents; gone — a tie still stated to a thing gone from every source."
    )
    subject: uuid.UUID = Field(description="The entity it is about.")
    label: str
    about: str = Field(description="The attribute, or the kind of tie: owner, manager…")
    chosen: object | None = Field(
        default=None, description="What the company model shows, when it chose."
    )
    values: list[ConflictValue]
    refs: list[uuid.UUID] = Field(description="The elements it involves.")
    said: str


class ContextElementRead(BaseModel):
    """One thing a context holds — an entity or a relationship — what it
    said, where it came from, why it is there."""

    model_config = ConfigDict(frozen=True)

    position: int = Field(description="Its place: the roots first, then the nearest.")
    kind: Literal["entity", "relationship"]
    ref_id: uuid.UUID = Field(description="Its id in the company model.")
    ref_type: str
    label: str
    entity: ElementEntity | None
    relationship: ElementRelationship | None
    provenance: ElementProvenance
    reason: ElementReason
    relevance: float | None = Field(
        description="How relevant, 0 to 1: how high and by how many retrievers it was found "
        "(LEKA-371); 1 for a root; none for a tie, and before LEKA-371."
    )
    ranking: ElementRanking | None = Field(
        default=None, description="How it was ranked (LEKA-372); none before."
    )
    text: str = Field(description="It, in one line, for a model to read.")


class ContextSourceRead(BaseModel):
    """A source a context's elements came from, and how many."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    kind: str | None
    name: str | None
    elements: int


class ContextSummary(BaseModel):
    """What a version holds, counted."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    entities: int
    relationships: int
    stated: int = Field(description="Relationships its sources stated.")
    inferred: int = Field(description="Relationships an enrichment rule inferred.")
    accepted: int = Field(
        default=0, description="Relationships LEKA proposed and someone validated (LEKA-380)."
    )
    by_type: dict[str, int]
    by_source_kind: dict[str, int]
    by_retriever: dict[str, int] = Field(description="Elements each retriever found (LEKA-371).")

    @model_validator(mode="before")
    @classmethod
    def _older(cls, data: object) -> object:
        if isinstance(data, dict):
            return {"by_retriever": {}, **data}
        return data


class RetrieverRunRead(BaseModel):
    """What one retriever did for a version (LEKA-371): found how much, in
    how long — or failed, timed out, or had nothing to start from, the
    others going on without it."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    retriever: str
    version: int
    status: Literal["ok", "failed", "timeout", "skipped"]
    found: int
    ms: int = Field(description="How long it took, in milliseconds.")
    detail: str | None = Field(description="What it was asked: the words, the window, the ways.")
    error: str | None = Field(description="Why it failed, or why it was skipped.")
    weight: float | None = Field(
        default=None,
        description="What its findings counted for — its own weight, times the request's "
        "(LEKA-373); none before.",
    )


IntentKind = Literal[
    "diagnose",
    "change",
    "ownership",
    "dependency",
    "compliance",
    "migration",
    "knowledge",
    "general",
]
Facet = Literal["technical", "business", "organizational", "temporal"]
Origin = Literal["asked", "text", "kind", "model"]


class IntentAsk(BaseModel):
    """An intention, as asked (LEKA-373): its words, and the scope its asker
    gave — none of which is required beyond the words."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=3, max_length=2000, description="The intention, in its words.")
    intention_id: str | None = Field(
        default=None,
        max_length=100,
        description="The intention it is for, when there is one (LEKA-384): the context's subject.",
    )
    title: str | None = Field(default=None, max_length=300)
    environment: str | None = Field(
        default=None, max_length=100, description="Where to look; read from the words when none."
    )
    since: datetime | None = Field(
        default=None, description="The period asked; read from the words when none."
    )
    until: datetime | None = None
    services: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=MAX_ROOTS,
        description="What the asker narrowed it to: the context's roots, first.",
    )
    sources: list[uuid.UUID] = Field(
        default_factory=list, description="What to read; every source when none."
    )
    limit: int = Field(default=DEFAULT_BUDGET, ge=1, le=MAX_BUDGET)

    @model_validator(mode="after")
    def _a_period(self) -> IntentAsk:
        if self.since and self.until and self.since >= self.until:
            raise ValueError("A period starts before it ends.")
        return self


class IntentSubject(BaseModel):
    """A thing an intention is about, and how LEKA knows."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    entity_id: uuid.UUID
    name: str
    type: str
    facet: Facet
    how: Literal["asked", "named", "business"] = Field(
        description="asked — the asker chose it; named — the words name it; business — what "
        "a thing named belongs to, for its business side."
    )
    said: str | None = Field(default=None, description="The words that named it.")
    confidence: float = Field(description="How surely the words name it, 0 to 1.")


class IntentPeriod(BaseModel):
    """When an intention looks: asked, read from its words, or its kind's."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    since: datetime
    until: datetime
    origin: Origin
    said: str | None = Field(default=None, description="The words that said it: « depuis hier ».")


class IntentConstraint(BaseModel):
    """What an assembly is held to, and where it comes from."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: Literal["environment", "period", "services", "sources", "relationships", "retrievers"]
    value: object
    origin: Origin
    said: str


class IntentGap(BaseModel):
    """What an intention needs that is missing — said, never ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: str = Field(
        description="no_subject, ambiguous_subject, unknown_service, unknown_environment, "
        "no_source_for, no_event_anchor, model_not_built, model_stale, nothing_happened, "
        "retriever_failed, no_business, disputed_subject."
    )
    severity: Literal["critical", "warning"]
    said: str
    detail: dict[str, object] = Field(default_factory=dict)


class IntentPlan(BaseModel):
    """What LEKA reads of an intention (LEKA-373): its kind, what it is
    about, when, where and under what constraints — the structured context
    request it makes — and what is missing. Kept with the context it made."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    version: int = Field(description="Raised each time intentions are read differently.")
    text: str
    intention_id: str | None
    kind: IntentKind
    kind_said: list[str] = Field(description="The words that said its kind.")
    facets: list[Facet]
    subjects: list[IntentSubject]
    period: IntentPeriod
    environment: str | None
    constraints: list[IntentConstraint]
    request: ContextRequest = Field(description="The structured context request it makes.")
    gaps: list[IntentGap]


class ContextChange(BaseModel):
    """What made a context be made again, or what it is behind on (LEKA-374):
    something the model changed of what it holds — an entity added, changed
    or removed, a relationship between its ends — or a field of its request
    or its intention; `model` when a build changed more than can be said
    one by one."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["entity", "relationship", "request", "intent", "model"]
    change: Literal["added", "changed", "removed"] | None = None
    ref_id: uuid.UUID | None = Field(default=None, description="The entity, in the model.")
    from_id: uuid.UUID | None = Field(default=None, description="A relationship's ends.")
    to_id: uuid.UUID | None = None
    type: str | None = Field(default=None, description="The entity's type, or the relationship's.")
    name: str | None = Field(default=None, description="The entity's name, or its ends: A → B.")
    fields: list[str] = Field(default_factory=list, description="What of an entity changed.")
    field: str | None = Field(
        default=None, description="What of the request or the intention changed."
    )
    before: object = None
    after: object = None
    at: datetime | None = Field(default=None, description="When the model recorded it.")
    touches: Literal["held", "words"] | None = Field(
        default=None,
        description="How it touches the context: something it holds, or a new thing its words "
        "name.",
    )


class ContextDelta(BaseModel):
    """How a version differs from the last one that held something
    (LEKA-374)."""

    model_config = ConfigDict(frozen=True)

    added: int
    removed: int
    changed: int
    unchanged: int


class QualityFactor(BaseModel):
    """One thing a measure of quality was read from (LEKA-375)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    value: float | None = Field(
        description="0 to 1; none when nothing measures it — left out of its measure, never "
        "guessed."
    )
    weight: float = Field(description="What it counts for in its measure.")
    said: str = Field(description="It, in words.")
    refs: list[uuid.UUID] = Field(
        default_factory=list, description="The elements it was read from, the most telling first."
    )
    detail: dict[str, object] = Field(default_factory=dict, description="What it was read from.")


class QualityMeasure(BaseModel):
    """Completeness, freshness or confidence: a score and what it rests on."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: MeasureName
    score: float | None = Field(description="0 to 1; none when nothing measures it.")
    weight: float = Field(description="What it counts for in the context's score.")
    factors: list[QualityFactor]


class QualityGap(BaseModel):
    """What a context lacks (LEKA-375): context missing, knowledge the
    company model does not have, evidence gone stale — or what an
    intention's reading found missing (LEKA-373)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: str
    severity: Severity
    measure: MeasureName = Field(description="What it lowers.")
    origin: Literal["quality", "intent"]
    said: str
    refs: list[uuid.UUID] = Field(default_factory=list, description="The elements it is about.")
    detail: dict[str, object] = Field(default_factory=dict)


class QualityConflict(BaseModel):
    """A conflict of the context (LEKA-372), judged: how much it matters to
    what was asked, and why."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    kind: str
    subject: uuid.UUID
    label: str
    about: str
    severity: Severity
    why: str = Field(description="Why it matters this much.")
    said: str
    refs: list[uuid.UUID]


class QualitySupport(BaseModel):
    """What a context's confidence rests on, counted."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    entities: int
    sources: int = Field(description="The sources its elements came from.")
    events: int = Field(description="What happened that it holds: incidents, deployments…")
    corroborated: int = Field(description="Entities two sources or more say.")
    conflicts: int
    critical: int = Field(description="Conflicts that matter to what was asked.")


class RetrieverYield(BaseModel):
    """What a retriever brought (LEKA-375): what it found, what was kept,
    what only it found, what made the first ranks — a signal for weighing
    it next time."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    retriever: str
    status: str
    found: int
    kept: int
    only: int = Field(description="Kept, and found by it alone.")
    top: int = Field(description="Kept among the first ranks.")
    said: str


class ContextQuality(BaseModel):
    """How good a version of a context is (LEKA-375): its score and level,
    each measure with what it was read from, what it lacks, what it
    disagrees on and how badly, what each retriever brought."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    version: int = Field(description="Raised each time quality is judged differently.")
    score: float | None = Field(description="0 to 1; none when nothing measures it.")
    level: QualityLevel = Field(description="high from 0.85, medium from 0.6, else low.")
    capped: Literal["critical_gap", "critical_conflict"] | None = Field(
        default=None,
        description="What held the score down: a critical gap (low at most), a critical "
        "conflict (medium at most).",
    )
    measures: list[QualityMeasure]
    gaps: list[QualityGap] = Field(description="The critical first.")
    conflicts: list[QualityConflict] = Field(description="The critical first.")
    support: QualitySupport
    retrieval: list[RetrieverYield]
    assessed: Literal["assembled", "read"] = Field(
        default="assembled",
        description="Judged when the version was made — or, for one made before, read from "
        "what it holds: what the model knew of its roots then is not known.",
    )


class AssembledContext(BaseModel):
    """One version of a context: the contract downstream services read.

    Assembled from the company model as it was built when the version was
    made — `model_built_at` — never from a customer's API. Its elements are
    in order, the roots first, then the nearest; what its budget could not
    hold was left out deliberately, and said (`truncated`, `dropped`). A
    version that failed — its roots gone from the model — holds nothing,
    and says why.
    """

    model_config = ConfigDict(frozen=True)

    contract_version: int
    context_id: uuid.UUID
    version: int
    status: Literal["assembled", "failed"]
    error: str | None = Field(description="Why it holds nothing, when it failed.")
    title: str
    purpose: str
    subject: ContextSubject
    request: ContextRequest
    strategy: ContextStrategyRead
    elements: list[ContextElementRead]
    sources: list[ContextSourceRead]
    summary: ContextSummary
    retrieval: list[RetrieverRunRead] = Field(
        description="What each retriever did: found, failed, timed out, skipped (LEKA-371)."
    )
    truncated: bool = Field(description="More was found than the budget holds.")
    dropped: int = Field(description="How many found were left out.")
    ranking: RankingReport | None = Field(
        default=None, description="How it was ranked, and what was left out why (LEKA-372)."
    )
    conflicts: list[ContextConflictRead] = Field(
        default_factory=list, description="What its sources disagree on (LEKA-372)."
    )
    intent: IntentPlan | None = Field(
        default=None,
        description="The intention it was assembled for, as LEKA read it, and what is missing "
        "— this version's too (LEKA-373).",
    )
    model_built_at: datetime | None = Field(description="The build of the model it was read from.")
    model_version: int
    assembled_at: datetime
    trigger: Trigger = Field(
        default="created",
        description="Why this version was made: created, refreshed, the model changed, "
        "expanded, compressed, asked again (LEKA-374).",
    )
    reason: str | None = None
    changes: list[ContextChange] = Field(
        default_factory=list,
        description="What made it: the model's changes it followed, or what of its request or "
        "intention changed — the first MAX_PENDING (LEKA-374).",
    )
    change_count: int = Field(default=0, description="How many changes made it, in all.")
    delta: ContextDelta | None = Field(
        default=None,
        description="How it differs from the last version that held something (LEKA-374).",
    )
    quality: ContextQuality | None = Field(
        default=None,
        description="How good it is: complete, fresh, to be relied on; what it lacks; what it "
        "disagrees on (LEKA-375).",
    )


Following = Literal["active", "dormant", "off", "archived"]


class ContextFreshness(BaseModel):
    """Whether a context is up to date with the company model (LEKA-374):
    `stale` when the model has changed what it holds since it was last
    checked — the changes said — or when its last recalculation failed. And
    whether it is made again on its own: `active` when it follows the model
    and was used lately, `dormant` when nobody used it for a while — made
    again when asked — `off` when it follows nothing, `archived`."""

    model_config = ConfigDict(frozen=True)

    state: Literal["fresh", "stale"]
    reasons: list[Literal["changes", "failed"]]
    since: datetime | None = Field(description="Since when it is behind.")
    changes: int = Field(description="How many changes it is behind on.")
    pending: list[ContextChange] = Field(description="The latest of them, MAX_PENDING at most.")
    checked_at: datetime | None = Field(description="When it was last checked.")
    checked_model_at: datetime | None = Field(description="The build its last check read.")
    following: Following


class ContextRead(BaseModel):
    """A context: what it is for, what it asks, where it stands."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    title: str
    purpose: str
    subject: ContextSubject
    request: ContextRequest
    status: ContextStatus
    current_version: int = Field(description="Its latest version; 0 until one is made.")
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    refreshed_at: datetime | None = Field(
        description="When it was last checked against the model, changed or not."
    )
    archived_at: datetime | None
    intent: IntentPlan | None = Field(
        default=None, description="The intention it was assembled for (LEKA-373)."
    )
    follow: bool = Field(
        default=True,
        description="Made again on its own when the model changes what it holds (LEKA-374).",
    )
    used_at: datetime | None = Field(default=None, description="When it was last used.")
    freshness: ContextFreshness


class ContextVersionRead(BaseModel):
    """One assembly of a context: when, from which build, by what, what it
    holds — or why it failed."""

    model_config = ConfigDict(frozen=True)

    version: int
    status: Literal["assembled", "failed"]
    trigger: Trigger
    reason: str | None
    changes: list[ContextChange] = Field(
        default_factory=list, description="What made it (LEKA-374)."
    )
    change_count: int = 0
    delta: ContextDelta | None = Field(
        default=None, description="How it differs from the last version that held something."
    )
    quality_score: float | None = Field(
        default=None, description="How good it is, 0 to 1 (LEKA-375); none before."
    )
    quality_level: QualityLevel | None = None
    strategy: ContextStrategyRead
    contract_version: int
    request: ContextRequest
    model_built_at: datetime | None
    model_version: int
    element_count: int
    truncated: bool
    dropped: int
    summary: ContextSummary
    retrieval: list[RetrieverRunRead]
    left_out: dict[str, int] = Field(
        default_factory=dict,
        description="What was left out, by why: duplicate, low_relevance, budget, ties (LEKA-372).",
    )
    conflicts: int = Field(default=0, description="How many conflicts it says (LEKA-372).")
    fingerprint: str = Field(description="What it holds, hashed: equal when nothing changed.")
    error: str | None
    assembled_at: datetime
    assembled_by: uuid.UUID | None


class ContextDetail(ContextRead):
    """A context and its latest version."""

    latest: ContextVersionRead | None


class ContextRefresh(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str | None = Field(default=None, max_length=500, description="Why it is reassembled.")


class ContextCheckRead(BaseModel):
    """One time a context was made again (LEKA-374): why, by whom — none
    when LEKA followed the model — after which changes, and what came of
    it."""

    model_config = ConfigDict(frozen=True)

    checked_at: datetime
    trigger: Trigger
    checked_by: uuid.UUID | None
    changes: list[ContextChange]
    change_count: int
    outcome: Literal["version", "unchanged", "failed"]
    version: int = Field(description="The version it made, or the one that still holds.")
    model_built_at: datetime | None


class RefreshOutcome(BaseModel):
    """What a refresh did: a new version when what the model says changed;
    none when it did not — the latest still holds."""

    model_config = ConfigDict(frozen=True)

    changed: bool
    version: ContextVersionRead = Field(description="The version it made, or the one that holds.")
    check: ContextCheckRead | None = Field(
        default=None, description="The check it was, and after which changes (LEKA-374)."
    )


class ContextUpdate(BaseModel):
    """What may be changed of a context without making it again (LEKA-374)."""

    model_config = ConfigDict(frozen=True)

    follow: bool = Field(
        description="Made again on its own when the model changes what it holds — or only when "
        "asked."
    )


class ContextExpand(BaseModel):
    """A context widened (LEKA-374): further, more of it, further back,
    less relevant things kept, more roots, more kinds of relationship.
    Nothing said: one step — a step further, twice the budget and the
    window, as far as each goes."""

    model_config = ConfigDict(frozen=True)

    depth: int | None = Field(default=None, ge=1, le=MAX_DEPTH)
    limit: int | None = Field(default=None, ge=1, le=MAX_BUDGET)
    window_days: int | None = Field(default=None, ge=1, le=MAX_WINDOW_DAYS)
    min_relevance: float | None = Field(default=None, ge=0, le=1)
    roots: list[uuid.UUID] = Field(
        default_factory=list, max_length=MAX_ROOTS, description="Roots added."
    )
    relationships: list[RelationshipType] = Field(
        default_factory=list, description="Kinds of relationship walked through too."
    )
    reason: str | None = Field(default=None, max_length=500)


class ContextCompress(BaseModel):
    """A context narrowed to what a reader can take (LEKA-374): fewer
    elements — the most relevant kept — nearer, a shorter window, only the
    more relevant. Nothing said: half its budget."""

    model_config = ConfigDict(frozen=True)

    depth: int | None = Field(default=None, ge=1, le=MAX_DEPTH)
    limit: int | None = Field(default=None, ge=1, le=MAX_BUDGET)
    window_days: int | None = Field(default=None, ge=1, le=MAX_WINDOW_DAYS)
    min_relevance: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = Field(default=None, max_length=500)


class ContextFeedbackCreate(BaseModel):
    """What someone says of a context (LEKA-375): an element useful, not
    useful, wrong — or something missing, said in a note."""

    model_config = ConfigDict(frozen=True)

    version: int | None = Field(
        default=None, ge=1, description="The version read; the latest that holds something."
    )
    ref_id: uuid.UUID | None = Field(default=None, description="The element it is about.")
    verdict: Verdict
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _about_something(self) -> ContextFeedbackCreate:
        if self.verdict == "missing":
            if self.ref_id is not None:
                raise ValueError("What is missing is not an element of it.")
            if not (self.note or "").strip():
                raise ValueError("Say what is missing.")
        elif self.ref_id is None:
            raise ValueError("Say which element it is about.")
        return self


class ContextFeedbackRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    version: int
    ref_id: uuid.UUID | None
    label: str | None = Field(description="The element, as the version said it.")
    verdict: Verdict
    note: str | None
    given_by: uuid.UUID | None
    given_at: datetime


class FeedbackCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    useful: int = 0
    not_useful: int = 0
    wrong: int = 0
    missing: int = 0


class QualityInspection(BaseModel):
    """A version's quality, inspected (LEKA-375): as judged, whether the
    context is up to date now, and what people said of it."""

    model_config = ConfigDict(frozen=True)

    context_id: uuid.UUID
    version: int
    quality: ContextQuality
    freshness: ContextFreshness = Field(description="Whether the context is up to date now.")
    feedback: FeedbackCounts
    given: list[ContextFeedbackRead] = Field(description="What was said of it, the latest first.")


class RetrievalFeedback(BaseModel):
    """What people said of what LEKA retrieved, counted (LEKA-375): by the
    retrievers that found it, by why it was there, by kind of thing — what
    weighing them next time can learn from."""

    model_config = ConfigDict(frozen=True)

    since: datetime
    total: FeedbackCounts
    by_retriever: dict[str, FeedbackCounts]
    by_role: dict[str, FeedbackCounts]
    by_type: dict[str, FeedbackCounts]


class ContractChange(BaseModel):
    """What a ticket added to a contract version: fields added only."""

    model_config = ConfigDict(frozen=True)

    ticket: str
    added: list[str]


class ContextContract(BaseModel):
    """The contract downstream services read (LEKA-376), published: its
    version and the header it is said in, what each part of it is judged
    by — ranking, quality, an intention's reading, each strategy — its JSON
    schema, and what each ticket added under this version."""

    model_config = ConfigDict(frozen=True)

    version: int
    supported: list[int] = Field(description="The versions a client may ask for.")
    header: str = Field(description="The header a response says it in, a client asks by.")
    versions: dict[str, int] = Field(
        description="ranking, quality, intent, strategy.<name>: raised when that part judges "
        "differently — each version keeps the ones it was made under."
    )
    json_schema: dict[str, object] = Field(description="AssembledContext, as JSON Schema.")
    changes: list[ContractChange]


class ElementStep(BaseModel):
    """One version of a context, as it held an element — or did not."""

    model_config = ConfigDict(frozen=True)

    version: int
    trigger: Trigger
    status: Literal["assembled", "failed"]
    assembled_at: datetime
    held: bool
    rank: int | None = None
    score: float | None = None
    changed: list[str] = Field(
        default_factory=list,
        description="What of it was said differently from the version before that held it.",
    )


class ElementFactor(BaseModel):
    """A factor of a version's quality read from the element."""

    model_config = ConfigDict(frozen=True)

    measure: MeasureName
    name: str
    value: float | None
    said: str


class ElementQuality(BaseModel):
    """What a version's quality says of one element (LEKA-375)."""

    model_config = ConfigDict(frozen=True)

    gaps: list[QualityGap]
    factors: list[ElementFactor]
    conflicts: list[QualityConflict]


class ElementInspection(BaseModel):
    """One element of a version, inspected (LEKA-376): what it is and where
    it came from, how it was ranked; what the version's quality says of it;
    its history across the context's versions; what people said of it."""

    model_config = ConfigDict(frozen=True)

    context_id: uuid.UUID
    version: int
    element: ContextElementRead
    quality: ElementQuality
    history: list[ElementStep] = Field(description="The context's versions, the latest first.")
    feedback: FeedbackCounts = Field(description="What people said of it, in every version.")


class EvidenceRecord(BaseModel):
    """A record an element was read from: which source, its id there, what
    extraction said of it, when the source last showed it — or that it is
    gone from the source."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    source_name: str | None = Field(description="None when the source has been deleted since.")
    kind: str = Field(description="The kind of record: issues, pages, deployments…")
    external_id: str = Field(description="Its id at the source.")
    title: str | None
    url: str | None
    state: str | None
    created_at: str | None
    updated_at: str | None
    excerpt: str | None = Field(description="The start of its text, MAX_EXCERPT at most.")
    seen_at: datetime = Field(description="When the source last showed it.")
    gone: bool = Field(description="The source no longer shows it.")


class ElementEvidence(BaseModel):
    """The source records an element was read from (LEKA-376): an entity's,
    every record whose key entity resolution made it; a relationship's, the
    records that stated it."""

    model_config = ConfigDict(frozen=True)

    context_id: uuid.UUID
    version: int
    ref_id: uuid.UUID
    label: str
    kind: Literal["entity", "relationship"]
    records: list[EvidenceRecord] = Field(description="Still shown first, the latest seen first.")
    truncated: bool = Field(description="More records than a response holds.")


class ElementChange(BaseModel):
    """An element in both versions, said differently."""

    model_config = ConfigDict(frozen=True)

    before: ContextElementRead
    after: ContextElementRead
    fields: list[str] = Field(
        description="What changed: name, lifecycle, attributes.<name>, confidence, provenance…"
    )


class ContextDiff(BaseModel):
    """What changed from one version of a context to another."""

    model_config = ConfigDict(frozen=True)

    context_id: uuid.UUID
    from_version: int
    to_version: int
    added: list[ContextElementRead]
    removed: list[ContextElementRead]
    changed: list[ElementChange]
    unchanged: int
