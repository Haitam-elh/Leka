"""Relevance and ranking (LEKA-372): what a context keeps, in which order,
and why — said signal by signal, so that a rank can be inspected.

Pure — no database, no clock: the time it is is given. assembly.assemble()
calls rank() on what a strategy gathered, then cuts to the budget.

TWO AXES, ONE SCORE. Each entity gathered is read on two axes; each signal
is kept with what it was read from (`detail`) and in words (`said`):

    topic   how much it is about the request
            asked          a root: 1, whatever else
            retrieval      how high, and by how many retrievers, it was
                           found — LEKA-371's fused relevance
            proximity      how near a root or an anchor: 1 / (1 + steps); 0
                           when tied to none. A bonus on what retrieval
                           left, never a cost:
                           topic = r + (1 - r) * 0.25 * proximity
    trust   how far what it says can be relied on: the weighted mean of
            confidence     how sure entity resolution was of it       0.25
            quality        how good its records were (LEKA-358)       0.15
            freshness      how lately a source showed it — halved
                           every 30 days                              0.15
            sources        how its best source is doing               0.15
            corroboration  how many sources say it                    0.10
            lifecycle      active, dormant, archived, removed         0.10
            consistency    whether what it holds is disputed          0.10

    score = topic * (0.6 + 0.4 * trust)

Trust moves a score by up to 40 %: of two things found as high, the better
sourced comes first; nothing becomes relevant for being well sourced. A
signal nothing measures — a quality never computed, a source's state never
read — is said unknown and left out of the mean, never guessed.

WHAT IS LEFT OUT, AND WHY — never a root, nor an anchor:
    duplicate      entity resolution linked it to another as probably the
                   same thing (docs/resolution.md): the surer is kept — the
                   more trusted, then the better scored — the other folded
                   into it, said on both
    low_relevance  its score is under the request's `min_relevance`
    out_of_scope   none of the sources the request reads says it (LEKA-373)
And assembly's budget: what does not fit.

CONFLICTS ARE SAID, NOT MERGED. Where what the context holds disagrees —
two owners folded into one are no competition, what they disagree on is:
    attribute   its sources give different values — resolution chose one
                and kept every one
    duplicates  two things probably the same, one folded into the other,
                give different values
    competing   two of a kind that admits one: owners, managers, leads,
                parents
    gone        a source still states a tie to a thing gone from every
                source
Each is listed with every side and who says so; what it involves carries
it, and its consistency is lower — disputed is not wrong, but it is less
sure.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from leka.context.schemas import (
    MIN_RELEVANCE,
    ConflictValue,
    ContextConflictRead,
    ElementRanking,
    FoldedRead,
    LeftOutRead,
    RankingSignal,
    RetrievalMatch,
    SignalName,
)
from leka.knowledge import ContextMaterial, MaterialEntity, MaterialRelationship, MaterialSource

# Raised each time the ranking ranks differently; kept with every version.
RANKING_VERSION = 1
# How much trust can move a score.
TRUST_SHARE = 0.4
# What being near the roots adds, at most, to what retrieval left.
PROXIMITY_BONUS = 0.25
# A thing a source stopped showing is half as fresh every this many days.
HALF_LIFE_DAYS = 30
# Resolution's links from this confidence are folded (docs/resolution.md:
# 0.6 to 0.9, "probably one").
LINKED = 0.6
# Where a thing tied to no root goes, among the rest: after the tied.
FAR = 99

TRUST_WEIGHTS: dict[str, float] = {
    "confidence": 0.25,
    "quality": 0.15,
    "freshness": 0.15,
    "sources": 0.15,
    "corroboration": 0.10,
    "lifecycle": 0.10,
    "consistency": 0.10,
}
# A relationship's own trust: how sure, said by a source or inferred, by
# how many sources.
TIE_WEIGHTS: dict[str, float] = {"confidence": 0.5, "origin": 0.3, "corroboration": 0.2}
WEIGHTS: dict[str, float] = {
    "retrieval": 1.0,
    "proximity": PROXIMITY_BONUS,
    **TRUST_WEIGHTS,
    **{f"tie.{name}": weight for name, weight in TIE_WEIGHTS.items()},
}

LIFECYCLE: dict[str, float] = {"active": 1.0, "dormant": 0.6, "archived": 0.3, "removed": 0.1}
# A link someone validated (LEKA-380) is trusted almost as a source's word.
ORIGIN: dict[str, float] = {"stated": 1.0, "accepted": 0.9, "inferred": 0.7}
# How many sources say it, as trust: one is a word, three are a fact.
CORROBORATION: dict[int, float] = {1: 0.6, 2: 0.85}
CORROBORATED = 1.0
# Disputed once, twice or more.
DISPUTED = (1.0, 0.6, 0.4)

# The kinds of tie a thing has one of: (kind, the end it is about, what).
SINGLE: tuple[tuple[str, Literal["from", "to"], str], ...] = (
    ("owned_by", "from", "owner"),
    ("owns", "to", "owner"),
    ("reports_to", "from", "manager"),
    ("led_by", "from", "lead"),
    ("child_of", "from", "parent"),
)

Axis = Literal["topic", "trust"]


@dataclass(frozen=True)
class Relevance:
    """How relevant a thing was found (LEKA-371), 0 to 1, and every way it
    was found, the surest first."""

    score: float
    matches: list[RetrievalMatch]


@dataclass(frozen=True)
class Link:
    """Two things entity resolution found probably the same, kept apart."""

    one: uuid.UUID
    other: uuid.UUID
    rule: str
    confidence: float
    evidence: str = ""


@dataclass(frozen=True)
class Ranking:
    """What rank() decided: the entities kept, in order — the roots and the
    anchors first — each one's ranking; what it left out and why; what the
    material disagrees on."""

    order: list[uuid.UUID]
    rankings: dict[uuid.UUID, ElementRanking]
    left: list[LeftOutRead]
    conflicts: list[ContextConflictRead]
    folded: dict[uuid.UUID, uuid.UUID]


def rank(
    material: ContextMaterial,
    *,
    starts: Sequence[uuid.UUID],
    depths: Mapping[uuid.UUID, int | None],
    nearest: Mapping[uuid.UUID, uuid.UUID],
    relevance: Mapping[uuid.UUID, Relevance] | None,
    links: Iterable[Link] = (),
    now: datetime | None = None,
    min_relevance: float = MIN_RELEVANCE,
    sources: Iterable[uuid.UUID] = (),
    exclude: Iterable[uuid.UUID] = (),
) -> Ranking:
    """Every entity of `material` scored; what is kept, in order; what is
    left out and why; the conflicts. `starts` — the roots, then the
    anchors — are kept first, as given. `depths` are the steps from the
    nearest start (`nearest`), none when tied to none; `relevance` is how
    each was found, none when no retriever ran (neighbourhood)."""
    entities = {item.entity.id: item for item in material.entities}
    named = {source.source_id: source for source in material.sources}
    roots = set(material.roots)
    kept_first = [s for s in dict.fromkeys(starts) if s in entities]
    first = set(kept_first)
    conflicts = _conflicts(material, entities, named)

    def ranked(entity_id: uuid.UUID, disputes: list[ContextConflictRead]) -> ElementRanking:
        return _ranking(
            entities[entity_id],
            named,
            entities,
            root=entity_id in roots,
            depth=depths.get(entity_id),
            nearest=nearest.get(entity_id),
            found=relevance.get(entity_id) if relevance is not None else None,
            scored=relevance is not None,
            tied=bool(first),
            now=now,
            disputes=[c for c in disputes if entity_id in c.refs],
        )

    rankings = {entity_id: ranked(entity_id, conflicts) for entity_id in entities}
    folded, kept_links = _fold(links, entities, first, rankings)
    if folded:
        # Two owners that are probably one person are one owner: folded,
        # a competition settles — what they disagree on does not.
        conflicts = [c for c in conflicts if not _settled(c, folded)]
        conflicts += _disagreements(folded, kept_links, entities, named)
        rankings = {entity_id: ranked(entity_id, conflicts) for entity_id in entities}
    for keeper, items in _folded_into(folded, kept_links, entities).items():
        rankings[keeper] = rankings[keeper].model_copy(update={"duplicates": items})

    left: list[LeftOutRead] = []
    for entity_id, keeper in folded.items():
        link = kept_links[entity_id]
        left.append(
            _left(
                entities[entity_id],
                rankings[entity_id],
                "duplicate",
                f"Probably the same as {entities[keeper].entity.name} "
                f"({link.rule}, {link.confidence:.2f}).",
                duplicate_of=keeper,
            )
        )
    rest = [i for i in entities if i not in first and i not in folded]
    # Asked not to (LEKA-387): never held, whatever found it.
    barred = frozenset(exclude)
    for entity_id in [i for i in rest if i in barred]:
        left.append(
            _left(
                entities[entity_id],
                rankings[entity_id],
                "excluded",
                "Excluded by the request.",
            )
        )
    rest = [i for i in rest if i not in barred]
    allowed = frozenset(sources)
    outside = {i for i in rest if not (_source_ids(entities[i]) & allowed)} if allowed else set()
    for entity_id in outside:
        left.append(
            _left(
                entities[entity_id],
                rankings[entity_id],
                "out_of_scope",
                "None of the sources read says it.",
            )
        )
    rest = [i for i in rest if i not in outside]
    low = {i for i in rest if rankings[i].score < min_relevance}
    for entity_id in low:
        left.append(
            _left(
                entities[entity_id],
                rankings[entity_id],
                "low_relevance",
                f"Scored {rankings[entity_id].score:.2f}, under {min_relevance:.2f}.",
            )
        )
    order = kept_first + sorted(
        (i for i in rest if i not in low),
        key=lambda i: (
            -rankings[i].score,
            depths.get(i) if depths.get(i) is not None else FAR,
            -entities[i].entity.confidence,
            entities[i].entity.name.casefold(),
            str(i),
        ),
    )
    return Ranking(
        order=order,
        rankings=rankings,
        left=sorted(left, key=lambda item: (-item.score, item.label.casefold(), str(item.ref_id))),
        conflicts=conflicts,
        folded=folded,
    )


def tie_ranking(
    edge: MaterialRelationship,
    ends: tuple[ElementRanking, ElementRanking],
    *,
    names: tuple[str, str],
    named: Mapping[uuid.UUID, MaterialSource],
    disputes: Sequence[str] = (),
) -> ElementRanking:
    """A relationship's ranking: as relevant as its weaker end; as sure as
    its confidence, who said it — a source, or a rule — and how many."""
    tie = edge.relationship
    weaker = 0 if ends[0].score <= ends[1].score else 1
    topic = ends[weaker].topic
    sources = {s for s in (_uuid(r.get("source_id")) for r in edge.provenance) if s is not None}
    signals = [
        _signal(
            "ends",
            "topic",
            ends[weaker].score,
            1.0,
            f"As relevant as its weaker end, {names[weaker]}.",
            end=names[weaker],
        ),
        _signal(
            "confidence",
            "trust",
            tie.confidence,
            TIE_WEIGHTS["confidence"],
            f"Confidence {tie.confidence:.2f}.",
        ),
        _signal(
            "origin",
            "trust",
            ORIGIN.get(tie.origin, ORIGIN["inferred"]),
            TIE_WEIGHTS["origin"],
            "Stated by a source." if tie.origin == "stated" else f"Inferred by {tie.rule}.",
            origin=tie.origin,
            rule=tie.rule or None,
        ),
        _corroboration(len(sources), TIE_WEIGHTS["corroboration"], named, sources),
    ]
    trust = _mean(signals)
    return ElementRanking(
        score=round(ends[weaker].score * _factor(trust), 4),
        rank=None,
        topic=round(topic, 4),
        trust=trust,
        signals=signals,
        conflicts=list(disputes),
    )


# ── one entity ──────────────────────────────────────────────────────────────


def _ranking(
    item: MaterialEntity,
    named: Mapping[uuid.UUID, MaterialSource],
    entities: Mapping[uuid.UUID, MaterialEntity],
    *,
    root: bool,
    depth: int | None,
    nearest: uuid.UUID | None,
    found: Relevance | None,
    scored: bool,
    tied: bool,
    now: datetime | None,
    disputes: list[ContextConflictRead],
) -> ElementRanking:
    entity = item.entity
    topic, signals = _topic(
        root=root,
        depth=depth,
        near=entities[nearest].entity.name if nearest is not None and nearest in entities else None,
        found=found,
        scored=scored,
        tied=tied,
    )
    sources = _source_ids(item)
    signals += [
        _signal(
            "confidence",
            "trust",
            entity.confidence,
            TRUST_WEIGHTS["confidence"],
            f"Entity resolution is {entity.confidence:.0%} sure of it.",
        ),
        _signal(
            "quality",
            "trust",
            entity.quality,
            TRUST_WEIGHTS["quality"],
            "Its records' quality was never measured."
            if entity.quality is None
            else f"Its best record's quality: {entity.quality:.0%}.",
        ),
        _freshness(entity.last_seen_at, now),
        _sources(sources, named),
        _corroboration(len(sources), TRUST_WEIGHTS["corroboration"], named, sources),
        _signal(
            "lifecycle",
            "trust",
            LIFECYCLE.get(entity.lifecycle.value, LIFECYCLE["active"]),
            TRUST_WEIGHTS["lifecycle"],
            f"It is {entity.lifecycle.value}.",
            lifecycle=entity.lifecycle.value,
        ),
        _signal(
            "consistency",
            "trust",
            DISPUTED[min(len(disputes), len(DISPUTED) - 1)],
            TRUST_WEIGHTS["consistency"],
            "Nothing it holds is disputed."
            if not disputes
            else f"Disputed: {', '.join(c.about for c in disputes)}.",
            disputed=[c.about for c in disputes],
        ),
    ]
    trust = _mean(signals)
    return ElementRanking(
        score=round(topic * _factor(trust), 4),
        rank=None,
        topic=round(topic, 4),
        trust=trust,
        signals=signals,
        conflicts=[c.id for c in disputes],
    )


def _topic(
    *,
    root: bool,
    depth: int | None,
    near: str | None,
    found: Relevance | None,
    scored: bool,
    tied: bool,
) -> tuple[float, list[RankingSignal]]:
    """How much a thing is about the request, and from what."""
    if root:
        return 1.0, [_signal("asked", "topic", 1.0, 1.0, "Asked for.")]
    signals: list[RankingSignal] = []
    retrieval: float | None = None
    if scored:
        retrieval = found.score if found else 0.0
        matches = list(found.matches) if found else []
        signals.append(
            _signal(
                "retrieval",
                "topic",
                retrieval,
                1.0,
                "Found by "
                + ", ".join(f"{m.retriever} (#{m.rank})" for m in matches)
                + f": {retrieval:.2f}."
                if matches
                else "No retriever found it.",
                matches=[{"retriever": m.retriever, "rank": m.rank} for m in matches],
            )
        )
    proximity = 1 / (1 + depth) if depth is not None else (0.0 if tied else None)
    if proximity is not None:
        steps = (
            "Tied to none of the roots."
            if depth is None
            else f"{depth} step{'s' if depth != 1 else ''} from {near}."
            if near
            else f"{depth} steps away."
        )
        signals.append(
            _signal("proximity", "topic", proximity, PROXIMITY_BONUS, steps, steps=depth, near=near)
        )
    if retrieval is None:
        return (proximity or 0.0), signals
    return retrieval + (1 - retrieval) * PROXIMITY_BONUS * (proximity or 0.0), signals


def _freshness(seen: datetime | None, now: datetime | None) -> RankingSignal:
    if seen is None or now is None:
        return _signal(
            "freshness",
            "trust",
            None,
            TRUST_WEIGHTS["freshness"],
            "Never shown by a source." if seen is None else "When it was read is not known.",
        )
    days = max(0.0, (now - seen).total_seconds() / 86_400)
    return _signal(
        "freshness",
        "trust",
        0.5 ** (days / HALF_LIFE_DAYS),
        TRUST_WEIGHTS["freshness"],
        f"A source showed it {days:.0f} days ago.",
        days=round(days, 1),
    )


def _sources(sources: set[uuid.UUID], named: Mapping[uuid.UUID, MaterialSource]) -> RankingSignal:
    """How its best source is doing: one healthy source vouches for it."""
    judged = [(_state(named.get(source)), named.get(source)) for source in sources]
    known = [(value, source) for (value, _), source in judged if value is not None]
    if not known:
        return _signal(
            "sources",
            "trust",
            None,
            TRUST_WEIGHTS["sources"],
            "How its sources are doing is not known.",
        )
    value, best = max(known, key=lambda pair: pair[0])
    said = (
        "Its only source has been deleted since."
        if best is None
        else f"Its best source, {best.name}, is {best.status or 'unknown'} "
        f"and {best.health or 'unknown'}."
    )
    return _signal(
        "sources",
        "trust",
        value,
        TRUST_WEIGHTS["sources"],
        said,
        source=best.name if best else None,
        status=best.status if best else "deleted",
        health=best.health if best else None,
    )


def _state(source: MaterialSource | None) -> tuple[float | None, str]:
    """A source's state, as trust in what it says."""
    if source is None:
        return 0.2, "deleted"
    status, health = source.status, source.health
    if status is None and health is None:
        return None, "unknown"
    if status in {"error", "disabled"} or health == "unhealthy":
        return 0.3, "failing"
    if status == "degraded" or health == "degraded":
        return 0.6, "degraded"
    if status == "active":
        return (1.0, "healthy") if health == "healthy" else (0.8, "active")
    return 0.5, "not read yet"


def _corroboration(
    count: int, weight: float, named: Mapping[uuid.UUID, MaterialSource], sources: set[uuid.UUID]
) -> RankingSignal:
    if count == 0:
        return _signal("corroboration", "trust", None, weight, "No source says it.", sources=0)
    names = sorted(named[s].name if s in named else "a deleted source" for s in sources)
    return _signal(
        "corroboration",
        "trust",
        CORROBORATION.get(count, CORROBORATED),
        weight,
        f"Said by {count} source{'s' if count > 1 else ''}: {', '.join(names)}.",
        sources=count,
    )


# ── duplicates ──────────────────────────────────────────────────────────────


def _fold(
    links: Iterable[Link],
    entities: Mapping[uuid.UUID, MaterialEntity],
    starts: set[uuid.UUID],
    rankings: Mapping[uuid.UUID, ElementRanking],
) -> tuple[dict[uuid.UUID, uuid.UUID], dict[uuid.UUID, Link]]:
    """Which things are folded into which: in each group resolution linked,
    the starts are kept, and when none is a start the surest of the rest —
    the most trusted, then the best scored: they are one thing, said best
    by the surest; the others go into it. With the link each was folded
    by."""
    sure = [
        link
        for link in links
        if link.confidence >= LINKED and link.one in entities and link.other in entities
    ]
    parent: dict[uuid.UUID, uuid.UUID] = {}

    def top(i: uuid.UUID) -> uuid.UUID:
        while parent.get(i, i) != i:
            i = parent[i]
        return i

    for link in sure:
        a, b = top(link.one), top(link.other)
        if a != b:
            parent[b] = a
    groups: dict[uuid.UUID, list[uuid.UUID]] = {}
    for i in {end for link in sure for end in (link.one, link.other)}:
        groups.setdefault(top(i), []).append(i)
    folded: dict[uuid.UUID, uuid.UUID] = {}
    by: dict[uuid.UUID, Link] = {}
    for members in groups.values():
        # Probably one thing: kept as the surest of them says it — then the
        # best found.
        best = sorted(
            members,
            key=lambda i: (
                i not in starts,
                -(rankings[i].trust or 0.0),
                -rankings[i].score,
                entities[i].entity.name.casefold(),
                str(i),
            ),
        )[0]
        for member in members:
            if member == best or member in starts:
                continue
            folded[member] = best
            by[member] = next(
                (link for link in sure if {link.one, link.other} == {member, best}),
                next(link for link in sure if member in (link.one, link.other)),
            )
    return folded, by


def _settled(conflict: ContextConflictRead, folded: Mapping[uuid.UUID, uuid.UUID]) -> bool:
    """A competition between things folded into one: no competition."""
    if conflict.kind != "competing":
        return False
    sides = {folded.get(v.ref_id, v.ref_id) for v in conflict.values if v.ref_id is not None}
    return len(sides) < 2


def _folded_into(
    folded: Mapping[uuid.UUID, uuid.UUID],
    by: Mapping[uuid.UUID, Link],
    entities: Mapping[uuid.UUID, MaterialEntity],
) -> dict[uuid.UUID, list[FoldedRead]]:
    into: dict[uuid.UUID, list[FoldedRead]] = {}
    for member, keeper in sorted(folded.items(), key=lambda pair: str(pair[0])):
        link = by[member]
        into.setdefault(keeper, []).append(
            FoldedRead(
                ref_id=member,
                label=entities[member].entity.name,
                rule=link.rule,
                confidence=link.confidence,
            )
        )
    return into


def _disagreements(
    folded: Mapping[uuid.UUID, uuid.UUID],
    by: Mapping[uuid.UUID, Link],
    entities: Mapping[uuid.UUID, MaterialEntity],
    named: Mapping[uuid.UUID, MaterialSource],
) -> list[ContextConflictRead]:
    """What two things folded together give differently: said, not lost
    with the one folded."""
    found: list[ContextConflictRead] = []
    for member, keeper in sorted(folded.items(), key=lambda pair: str(pair[0])):
        kept, gone = entities[keeper], entities[member]
        theirs = gone.entity.attributes
        for name in sorted(kept.entity.attributes.keys() & theirs.keys()):
            ours = kept.entity.attributes[name]
            if _canonical(ours) == _canonical(theirs[name]):
                continue
            found.append(
                ContextConflictRead(
                    id=f"duplicates:{keeper}:{member}:{name}",
                    kind="duplicates",
                    subject=keeper,
                    label=kept.entity.name,
                    about=name,
                    chosen=ours,
                    values=[
                        ConflictValue(value=ours, ref_id=keeper, by=_names(kept, named)),
                        ConflictValue(value=theirs[name], ref_id=member, by=_names(gone, named)),
                    ],
                    refs=[keeper],
                    said=f"{kept.entity.name} and {gone.entity.name}, probably the same "
                    f"({by[member].rule}), disagree on {name}: {_short(ours)} or "
                    f"{_short(theirs[name])}.",
                )
            )
    return found


# ── conflicts ───────────────────────────────────────────────────────────────


def _conflicts(
    material: ContextMaterial,
    entities: Mapping[uuid.UUID, MaterialEntity],
    named: Mapping[uuid.UUID, MaterialSource],
) -> list[ContextConflictRead]:
    """What the material disagrees on, before anything is left out."""
    found: list[ContextConflictRead] = []
    for entity_id, item in entities.items():
        for said in _dicts(item.provenance.get("conflicts")):
            about = str(said.get("attribute") or "")
            if not about:
                continue
            values: dict[str, ConflictValue] = {}
            for value in _dicts(said.get("values")):
                source = _uuid(value.get("source_id"))
                if source is None:
                    who = "a source"
                else:
                    who = named[source].name if source in named else "a deleted source"
                key = _canonical(value.get("value"))
                held = values.get(key)
                values[key] = ConflictValue(
                    value=value.get("value"),
                    by=sorted({*(held.by if held else []), who}),
                )
            if len(values) < 2:
                continue
            sides = list(values.values())
            found.append(
                ContextConflictRead(
                    id=f"attribute:{entity_id}:{about}",
                    kind="attribute",
                    subject=entity_id,
                    label=item.entity.name,
                    about=about,
                    chosen=said.get("chosen"),
                    values=sides,
                    refs=[entity_id],
                    said=f"The sources of {item.entity.name} disagree on {about}: "
                    + "; ".join(f"{_short(v.value)} ({', '.join(v.by)})" for v in sides)
                    + ".",
                )
            )
    found += _competing(material.relationships, entities, named)
    found += _gone(material.relationships, entities, named)
    return found


def _competing(
    edges: Sequence[MaterialRelationship],
    entities: Mapping[uuid.UUID, MaterialEntity],
    named: Mapping[uuid.UUID, MaterialSource],
) -> list[ContextConflictRead]:
    """Two of a kind that admits one: two owners, two managers."""
    sides: dict[tuple[uuid.UUID, str], dict[uuid.UUID, list[MaterialRelationship]]] = {}
    for edge in edges:
        tie = edge.relationship
        for kind, end, about in SINGLE:
            if tie.type.value != kind:
                continue
            subject, other = (
                (tie.from_entity_id, tie.to_entity_id)
                if end == "from"
                else (tie.to_entity_id, tie.from_entity_id)
            )
            if subject in entities and other in entities:
                sides.setdefault((subject, about), {}).setdefault(other, []).append(edge)
    found: list[ContextConflictRead] = []
    for (subject, about), others in sorted(sides.items(), key=lambda pair: str(pair[0])):
        if len(others) < 2:
            continue
        values = [
            ConflictValue(
                value=entities[other].entity.name,
                ref_id=other,
                by=sorted({who for edge in ties for who in _said_by(edge, named)}),
            )
            for other, ties in sorted(
                others.items(), key=lambda pair: entities[pair[0]].entity.name.casefold()
            )
        ]
        name = entities[subject].entity.name
        found.append(
            ContextConflictRead(
                id=f"competing:{subject}:{about}",
                kind="competing",
                subject=subject,
                label=name,
                about=about,
                values=values,
                refs=[
                    subject,
                    *others,
                    *(edge.relationship.id for ties in others.values() for edge in ties),
                ],
                said=f"{name} has {len(values)} of what it has one of — {about}: "
                + "; ".join(f"{v.value} ({', '.join(v.by)})" for v in values)
                + ".",
            )
        )
    return found


def _gone(
    edges: Sequence[MaterialRelationship],
    entities: Mapping[uuid.UUID, MaterialEntity],
    named: Mapping[uuid.UUID, MaterialSource],
) -> list[ContextConflictRead]:
    """A tie a source still states, to a thing gone from every source."""
    found: list[ContextConflictRead] = []
    for edge in edges:
        tie = edge.relationship
        if tie.origin != "stated":
            continue
        start, end = entities.get(tie.from_entity_id), entities.get(tie.to_entity_id)
        if start is None or end is None:
            continue
        for gone, alive in ((end, start), (start, end)):
            if (
                gone.entity.lifecycle.value != "removed"
                or alive.entity.lifecycle.value == "removed"
            ):
                continue
            found.append(
                ContextConflictRead(
                    id=f"gone:{tie.from_entity_id}>{tie.type.value}>{tie.to_entity_id}",
                    kind="gone",
                    subject=alive.entity.id,
                    label=alive.entity.name,
                    about=tie.type.value,
                    values=[
                        ConflictValue(
                            value=f"{start.entity.name} {tie.type.value} {end.entity.name}",
                            ref_id=tie.id,
                            by=_said_by(edge, named),
                        ),
                        ConflictValue(value="removed", ref_id=gone.entity.id, by=[]),
                    ],
                    refs=[alive.entity.id, gone.entity.id, tie.id],
                    said=f"{start.entity.name} {tie.type.value} {end.entity.name} is still "
                    f"stated, but {gone.entity.name} is gone from every source.",
                )
            )
            break
    return found


# ── helpers ─────────────────────────────────────────────────────────────────


def _signal(
    name: SignalName,
    axis: Axis,
    value: float | None,
    weight: float,
    said: str,
    **detail: object,
) -> RankingSignal:
    return RankingSignal(
        name=name,
        axis=axis,
        value=None if value is None else round(max(0.0, min(1.0, value)), 4),
        weight=weight,
        detail={key: v for key, v in detail.items() if v is not None},
        said=said,
    )


def _mean(signals: Sequence[RankingSignal]) -> float | None:
    """The weighted mean of the trust signals something measures."""
    known = [s for s in signals if s.axis == "trust" and s.value is not None]
    weight = sum(s.weight for s in known)
    if not weight:
        return None
    return round(sum(s.weight * (s.value or 0.0) for s in known) / weight, 4)


def _factor(trust: float | None) -> float:
    """What trust does to a score: from 0.6 to 1; unknown, the middle."""
    said = 0.5 if trust is None else trust
    return 1 - TRUST_SHARE + TRUST_SHARE * said


def _left(
    item: MaterialEntity,
    ranking: ElementRanking,
    reason: Literal["duplicate", "low_relevance", "out_of_scope", "excluded", "budget"],
    said: str,
    *,
    duplicate_of: uuid.UUID | None = None,
) -> LeftOutRead:
    return LeftOutRead(
        ref_id=item.entity.id,
        ref_type=item.entity.type.value,
        label=item.entity.name,
        reason=reason,
        score=ranking.score,
        duplicate_of=duplicate_of,
        said=said,
    )


def left_for_budget(item: MaterialEntity, ranking: ElementRanking, limit: int) -> LeftOutRead:
    """A thing kept by the ranking that the budget could not hold."""
    return _left(item, ranking, "budget", f"Beyond the budget of {limit} elements.")


def _source_ids(item: MaterialEntity) -> set[uuid.UUID]:
    return {
        source
        for source in (
            _uuid(said.get("source_id")) for said in _dicts(item.provenance.get("sources"))
        )
        if source is not None
    }


def _names(item: MaterialEntity, named: Mapping[uuid.UUID, MaterialSource]) -> list[str]:
    return sorted(
        {named[s].name if s in named else "a deleted source" for s in _source_ids(item)}
    ) or [item.entity.name]


def _said_by(edge: MaterialRelationship, named: Mapping[uuid.UUID, MaterialSource]) -> list[str]:
    """Who states a relationship: its records' sources — or the rule."""
    tie = edge.relationship
    if tie.origin != "stated":
        return [f"rule {tie.rule}"]
    sources = {s for s in (_uuid(r.get("source_id")) for r in edge.provenance) if s is not None}
    return sorted({named[s].name if s in named else "a deleted source" for s in sources}) or [
        "a source"
    ]


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _short(value: object) -> str:
    said = str(value)
    return said if len(said) <= 60 else said[:59] + "…"


def _dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [{str(k): v for k, v in item.items()} for item in value if isinstance(item, dict)]


def _uuid(value: object) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
