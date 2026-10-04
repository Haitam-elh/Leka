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

SubjectType = Literal["entity", "intention", "request"]
ContextStatus = Literal["assembling", "assembled", "failed", "archived"]
StrategyName = Literal["neighbourhood", "hybrid"]
# How things are found (LEKA-371): around the roots, by the request's words
# in the model and in the records' own text, by their time, on the ways
# between two roots.
RetrieverName = Literal["graph", "search", "content", "timeline", "paths"]
RETRIEVERS: tuple[RetrieverName, ...] = ("graph", "search", "content", "timeline", "paths")


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

    @model_validator(mode="after")
    def _starts_somewhere(self) -> ContextCreate:
        if self.strategy == "neighbourhood" and not self.roots:
            raise ValueError("A neighbourhood starts from roots.")
        if self.retrievers and self.strategy != "hybrid":
            raise ValueError("Retrievers are combined by the hybrid strategy only.")
        if not self.roots and not words(self.query or self.purpose):
            raise ValueError("Nothing to start from: give roots, or words that say something.")
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

    @model_validator(mode="before")
    @classmethod
    def _older(cls, data: object) -> object:
        """A request kept before LEKA-371 had none of these: they read empty."""
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
        description="stated: its sources show it; inferred: an enrichment rule made it."
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
    model_built_at: datetime | None = Field(description="The build of the model it was read from.")
    model_version: int
    assembled_at: datetime


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


class ContextVersionRead(BaseModel):
    """One assembly of a context: when, from which build, by what, what it
    holds — or why it failed."""

    model_config = ConfigDict(frozen=True)

    version: int
    status: Literal["assembled", "failed"]
    trigger: Literal["created", "refreshed"]
    reason: str | None
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


class RefreshOutcome(BaseModel):
    """What a refresh did: a new version when what the model says changed;
    none when it did not — the latest still holds."""

    model_config = ConfigDict(frozen=True)

    changed: bool
    version: ContextVersionRead = Field(description="The version it made, or the one that holds.")


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
