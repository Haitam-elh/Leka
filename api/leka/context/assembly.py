"""Assembly: a context's elements, from what a strategy gathered (LEKA-370).

Pure — no database, no clock — so that what a context holds, and in which
order, is decided in one place a test can read whole.

    assemble()     the elements, in order, within the budget, each with its
                   provenance and why it is there; what was left out
    restore()      an element as a version stored it, read back
    identity()     what an element is from one build of the model to the
                   next — an entity's id; a relationship's ends and kind
    fingerprint()  what a version holds, hashed: two assemblies that hold
                   the same things, said the same way, have the same one —
                   whichever build of the model they were read from
    diff()         what changed from one version's elements to another's
    text()         an element in one line, for a model to read

THE ORDER IS THE BUDGET'S. The roots first, as asked — or, none asked,
what the request's words found best (its anchors); then the most relevant
(LEKA-371: how high, and by how many retrievers, a thing was found), the
nearest, the surest, by name. Each entity taken brings the relationships
between it and those already taken — the surest first, a source's word
before a rule's — so a context cut short holds what matters most and how
it is tied, never a relationship whose end it lacks. What does not fit is
dropped deliberately, counted, and said (`truncated`), not lost by
accident.

WHY EACH IS THERE. A root was asked for; a thing tied to a root or an
anchor was reached from it, through a relationship, so many steps away —
found by walking the gathered relationships from them, the surest way
first; a thing tied to none was found — by its words, its time, on a way.
Each says every retriever that found it, at what rank (LEKA-371). A
relationship is there because it ties two of them.

PROVENANCE IS COPIED, NOT POINTED AT. The model moves on; a version says
what it was told then: each entity's sources and the keys it goes by
there, each attribute's origin, what its sources disagree on; each
relationship's records and their evidence, or the rule that inferred it
and the entities it read.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from leka.context.schemas import (
    ContextSummary,
    ElementEnd,
    ElementEntity,
    ElementProvenance,
    ElementReason,
    ElementRelationship,
    ElementSource,
    RetrievalMatch,
)
from leka.knowledge import ContextMaterial, MaterialEntity, MaterialRelationship, MaterialSource

# What a refresh must not count as a change: being seen again is not news,
# nor a source renamed.
VOLATILE = frozenset({"last_seen_at", "changed_at", "name"})
# Where a thing tied to no root goes, among the rest: after the tied.
MAX_DEPTH_UNKNOWN = 99
# The attributes a line of text shows, at most, and how long each.
TEXT_ATTRIBUTES = 8
TEXT_VALUE = 80


@dataclass(frozen=True)
class Element:
    """One thing a version holds, ready to be stored."""

    kind: str
    ref_id: uuid.UUID
    ref_type: str
    label: str
    entity: ElementEntity | None
    relationship: ElementRelationship | None
    provenance: ElementProvenance
    reason: ElementReason
    relevance: float | None = None

    def content(self) -> dict[str, object]:
        said = self.entity or self.relationship
        assert said is not None
        return said.model_dump(mode="json")


@dataclass(frozen=True)
class Relevance:
    """How relevant a thing was found (LEKA-371), 0 to 1, and every way it
    was found, the surest first."""

    score: float
    matches: list[RetrievalMatch]


@dataclass(frozen=True)
class Assembly:
    elements: list[Element]
    dropped: int
    truncated: bool
    summary: ContextSummary
    fingerprint: str


def assemble(
    material: ContextMaterial,
    *,
    limit: int,
    strategy: str,
    relevance: Mapping[uuid.UUID, Relevance] | None = None,
    anchors: Sequence[uuid.UUID] = (),
) -> Assembly:
    """The elements of a context from `material`, `limit` at most — the
    most relevant first when retrievers said how relevant (LEKA-371)."""
    entities = {item.entity.id: item for item in material.entities}
    named = {source.source_id: source for source in material.sources}
    edges = sorted(
        (e for e in material.relationships if _ends(e) <= entities.keys()), key=_edge_order
    )
    roots = [root for root in material.roots if root in entities]
    starts = roots + [a for a in dict.fromkeys(anchors) if a in entities and a not in roots]
    reached = _reached(starts, edges)
    depths = {
        i: item.depth if item.depth is not None else reached.get(i, (None, None, None))[2]
        for i, item in entities.items()
    }
    found = relevance or {}

    def score(i: uuid.UUID) -> float:
        return found[i].score if i in found else 0.0

    order = starts + sorted(
        (i for i in entities if i not in set(starts)),
        key=lambda i: (
            -score(i),
            depths[i] if depths[i] is not None else MAX_DEPTH_UNKNOWN,
            -entities[i].entity.confidence,
            entities[i].entity.name.casefold(),
            str(i),
        ),
    )
    touching: dict[uuid.UUID, list[MaterialRelationship]] = {}
    for edge in edges:
        for end in _ends(edge):
            touching.setdefault(end, []).append(edge)

    out: list[Element] = []
    taken: set[uuid.UUID] = set()
    tied: set[uuid.UUID] = set()
    for entity_id in order:
        if len(out) >= limit:
            break
        item = entities[entity_id]
        out.append(
            _entity(
                item,
                named,
                strategy,
                root=entity_id in roots,
                depth=depths[entity_id],
                reached=reached.get(entity_id),
                found=found.get(entity_id),
                scored=relevance is not None,
            )
        )
        taken.add(entity_id)
        for edge in touching.get(entity_id, []):
            if len(out) >= limit:
                break
            edge_id = edge.relationship.id
            if edge_id in tied or not _ends(edge) <= taken:
                continue
            out.append(_relationship(edge, entities, named, strategy, depths))
            tied.add(edge_id)

    dropped = len(entities) + len(edges) - len(out)
    return Assembly(
        elements=out,
        dropped=dropped,
        truncated=material.truncated or dropped > 0,
        summary=summary(out),
        fingerprint=fingerprint(out),
    )


def restore(
    kind: str,
    ref_id: uuid.UUID,
    ref_type: str,
    label: str,
    content: dict[str, object],
    provenance: dict[str, object],
    reason: dict[str, object],
    relevance: float | None = None,
) -> Element:
    """An element as a version stored it, read back."""
    return Element(
        kind=kind,
        ref_id=ref_id,
        ref_type=ref_type,
        label=label,
        entity=ElementEntity.model_validate(content) if kind == "entity" else None,
        relationship=(
            ElementRelationship.model_validate(content) if kind == "relationship" else None
        ),
        provenance=ElementProvenance.model_validate(provenance),
        reason=ElementReason.model_validate(reason),
        relevance=relevance,
    )


def summary(elements: Sequence[Element]) -> ContextSummary:
    origins = Counter(e.provenance.origin for e in elements if e.kind == "relationship")
    kinds: Counter[str] = Counter()
    retrievers: Counter[str] = Counter()
    for element in elements:
        kinds.update({s.kind or "unknown" for s in element.provenance.sources})
        retrievers.update({m.retriever for m in element.reason.retrievers})
    return ContextSummary(
        entities=sum(1 for e in elements if e.kind == "entity"),
        relationships=sum(1 for e in elements if e.kind == "relationship"),
        stated=origins["stated"],
        inferred=origins["inferred"],
        by_type=dict(sorted(Counter(e.ref_type for e in elements).items())),
        by_source_kind=dict(sorted(kinds.items())),
        by_retriever=dict(sorted(retrievers.items())),
    )


def identity(element: Element) -> str:
    """What an element is from one build of the model to the next: an
    entity, its id — kept across builds; a relationship, its ends and its
    kind — each build remakes the relationships, and their ids with them."""
    if element.relationship is not None:
        tie = element.relationship
        return f"{tie.start.id}>{tie.type}>{tie.end.id}"
    return str(element.ref_id)


def fingerprint(elements: Sequence[Element]) -> str:
    """What a version holds, hashed — by what each element is, not its id
    of the day, and leaving out what changes without anything being said
    differently (VOLATILE)."""
    ties = _ties(elements)
    said = [{"id": identity(e), "kind": e.kind, **_said(e, ties)} for e in elements]
    blob = json.dumps(said, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def diff(
    before: Sequence[Element], after: Sequence[Element]
) -> tuple[list[Element], list[Element], list[tuple[Element, Element, list[str]]], int]:
    """What `after` holds that `before` did not, what it no longer holds,
    what both hold said differently — and how many are the same. Matched by
    what each is (identity), whatever its id in either build."""
    was = {identity(e): e for e in before}
    now = {identity(e): e for e in after}
    then_ties, now_ties = _ties(before), _ties(after)
    added = [e for key, e in now.items() if key not in was]
    removed = [e for key, e in was.items() if key not in now]
    changed: list[tuple[Element, Element, list[str]]] = []
    same = 0
    for key, element in now.items():
        old = was.get(key)
        if old is None:
            continue
        fields = _changes(_said(old, then_ties), _said(element, now_ties))
        if fields:
            changed.append((old, element, fields))
        else:
            same += 1
    return added, removed, changed, same


def _said(element: Element, ties: Mapping[str, str]) -> dict[str, dict[str, object]]:
    """An element as compared: what it says, where it came from without what
    changes on its own, why it is there — the relationship it was reached
    through named by what it is."""
    reason = element.reason.model_dump(mode="json")
    via = reason.get("via")
    if isinstance(via, str):
        reason["via"] = ties.get(via, via)
    # Who found it, on what — not how high: a rank moves when something
    # else is found, and that is the other thing's change.
    reason["retrievers"] = [
        {"retriever": m.get("retriever"), "detail": m.get("detail")}
        for m in _dicts(reason.get("retrievers"))
    ]
    return {
        "content": element.content(),
        "provenance": _steady(element.provenance.model_dump(mode="json")),
        "reason": reason,
    }


def _changes(old: dict[str, dict[str, object]], new: dict[str, dict[str, object]]) -> list[str]:
    """What was said differently of one element: its fields, each attribute
    by name, its provenance by part, why it is there."""
    then, since = old["content"], new["content"]
    fields = [
        name
        for name in sorted(then.keys() | since.keys())
        if name not in {"attributes", "version"} and then.get(name) != since.get(name)
    ]
    was, now = _mapping(then.get("attributes")), _mapping(since.get("attributes"))
    fields += [
        f"attributes.{name}"
        for name in sorted(was.keys() | now.keys())
        if was.get(name) != now.get(name)
    ]
    fields += [
        f"provenance.{name}"
        for name in sorted(old["provenance"].keys() | new["provenance"].keys())
        if name not in {"confidence", "origin", "rule"}
        and old["provenance"].get(name) != new["provenance"].get(name)
    ]
    if old["reason"] != new["reason"]:
        fields.append("reason")
    return fields


def _ties(elements: Iterable[Element]) -> dict[str, str]:
    """Each relationship's id of the day, to what it is."""
    return {str(e.ref_id): identity(e) for e in elements if e.relationship is not None}


def text(element: Element) -> str:
    """An element in one line, for a model to read: what it is, what it
    says, who says so."""
    by = sorted({s.name or s.kind or "a deleted source" for s in element.provenance.sources})
    if element.entity is not None:
        entity = element.entity
        line = f'{entity.type} "{entity.name}" ({entity.key})'
        if entity.lifecycle != "active":
            line += f", {entity.lifecycle}"
        shown = [
            f"{name}: {_short(value)}"
            for name, value in sorted(entity.attributes.items())
            if isinstance(value, str | int | float | bool) and value != ""
        ][:TEXT_ATTRIBUTES]
        if shown:
            line += " — " + "; ".join(shown)
        return line + (f" [from {', '.join(by)}]" if by else "")
    tie = element.relationship
    assert tie is not None
    line = f'"{tie.start.name}" {tie.type} "{tie.end.name}"'
    if tie.origin == "inferred":
        line += f" — inferred by {tie.rule}"
    elif by:
        line += f" — stated by {', '.join(by)}"
    return line + f", confidence {tie.confidence:.2f}"


def _reached(
    starts: Sequence[uuid.UUID], edges: Sequence[MaterialRelationship]
) -> dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID | None, int]]:
    """For each entity the gathered relationships reach from the starts —
    the roots, or the anchors: the one it is nearest, the relationship it
    was reached through — the surest way first, as `edges` are ordered —
    and how many steps."""
    ways: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID]]] = {}
    for edge in edges:
        start, end = edge.relationship.from_entity_id, edge.relationship.to_entity_id
        ways.setdefault(start, []).append((end, edge.relationship.id))
        ways.setdefault(end, []).append((start, edge.relationship.id))
    found: dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID | None, int]] = {
        s: (s, None, 0) for s in starts
    }
    queue = deque(starts)
    while queue:
        here = queue.popleft()
        root, _, far = found[here]
        for there, through in ways.get(here, []):
            if there not in found:
                found[there] = (root, through, far + 1)
                queue.append(there)
    return found


def _entity(
    item: MaterialEntity,
    named: dict[uuid.UUID, MaterialSource],
    strategy: str,
    *,
    root: bool,
    depth: int | None,
    reached: tuple[uuid.UUID, uuid.UUID | None, int] | None,
    found: Relevance | None,
    scored: bool,
) -> Element:
    entity, provenance = item.entity, item.provenance
    sources: dict[tuple[uuid.UUID, str | None], ElementSource] = {}
    for said in _dicts(provenance.get("sources")):
        source_id = _uuid(said.get("source_id"))
        if source_id is None:
            continue
        key = _text(said.get("key"))
        known = named.get(source_id)
        sources.setdefault(
            (source_id, key),
            # A provenance's `kind` is its key's — key, alias, derived — not
            # its tool's: a source deleted since is said, not guessed.
            ElementSource(
                source_id=source_id,
                kind=known.kind if known else None,
                name=known.name if known else None,
                key=key,
                record_id=None,
            ),
        )
    origins = provenance.get("attributes")
    start, via = (reached[0], reached[1]) if reached else (None, None)
    role = "root" if root else "reached" if depth is not None and depth > 0 else "found"
    return Element(
        kind="entity",
        ref_id=entity.id,
        ref_type=entity.type.value,
        label=entity.name,
        entity=ElementEntity(
            type=entity.type.value,
            key=entity.key,
            name=entity.name,
            attributes=dict(entity.attributes),
            lifecycle=entity.lifecycle.value,
            version=entity.version,
            confidence=entity.confidence,
            quality=entity.quality,
        ),
        relationship=None,
        provenance=ElementProvenance(
            origin="stated",
            rule=None,
            confidence=entity.confidence,
            sources=list(sources.values()),
            evidence=[],
            inferred_from=[],
            attributes={
                name: dict(origin)
                for name, origin in (origins.items() if isinstance(origins, dict) else [])
                if isinstance(origin, dict)
            },
            conflicts=_dicts(provenance.get("conflicts")),
            first_seen_at=entity.first_seen_at,
            last_seen_at=entity.last_seen_at,
            changed_at=None,
        ),
        reason=ElementReason(
            strategy=strategy,
            role=role,
            depth=depth,
            root=start,
            via=via,
            retrievers=found.matches if found else [],
        ),
        relevance=(1.0 if root else found.score if found else 0.0) if scored else None,
    )


def _relationship(
    edge: MaterialRelationship,
    entities: dict[uuid.UUID, MaterialEntity],
    named: dict[uuid.UUID, MaterialSource],
    strategy: str,
    depths: Mapping[uuid.UUID, int | None],
) -> Element:
    tie = edge.relationship
    start, end = entities[tie.from_entity_id], entities[tie.to_entity_id]
    sources: dict[tuple[uuid.UUID, str | None], ElementSource] = {}
    evidence: list[str] = []
    inferred_from: list[uuid.UUID] = []
    for record in edge.provenance:
        said = _text(record.get("evidence"))
        if said and said not in evidence:
            evidence.append(said)
        read = _uuid(record.get("entity_id"))
        if read is not None and read not in inferred_from:
            inferred_from.append(read)
        source_id = _uuid(record.get("source_id"))
        if source_id is None:
            continue
        record_id = _text(record.get("record_id"))
        known = named.get(source_id)
        sources.setdefault(
            (source_id, record_id),
            ElementSource(
                source_id=source_id,
                kind=known.kind if known else None,
                name=known.name if known else None,
                key=None,
                record_id=record_id,
            ),
        )
    return Element(
        kind="relationship",
        ref_id=tie.id,
        ref_type=tie.type.value,
        label=f"{start.entity.name} → {end.entity.name}",
        entity=None,
        relationship=ElementRelationship(
            type=tie.type.value,
            start=_end(start),
            end=_end(end),
            confidence=tie.confidence,
            origin=tie.origin,
            rule=tie.rule,
            cross_source=tie.cross_source,
            attributes=dict(tie.attributes),
        ),
        provenance=ElementProvenance(
            origin=tie.origin,
            rule=tie.rule or None,
            confidence=tie.confidence,
            sources=list(sources.values()),
            evidence=evidence,
            inferred_from=inferred_from,
            attributes={},
            conflicts=[],
            first_seen_at=edge.first_seen_at,
            last_seen_at=None,
            changed_at=edge.changed_at,
        ),
        reason=ElementReason(
            strategy=strategy,
            role="tie",
            depth=max(
                (
                    d
                    for d in (depths[tie.from_entity_id], depths[tie.to_entity_id])
                    if d is not None
                ),
                default=None,
            ),
            root=None,
            via=None,
            retrievers=[],
        ),
    )


def _end(item: MaterialEntity) -> ElementEnd:
    entity = item.entity
    return ElementEnd(id=entity.id, type=entity.type.value, key=entity.key, name=entity.name)


def _ends(edge: MaterialRelationship) -> set[uuid.UUID]:
    return {edge.relationship.from_entity_id, edge.relationship.to_entity_id}


def _edge_order(edge: MaterialRelationship) -> tuple[bool, float, str, str, str]:
    """A source's word before a rule's, the surest first — then by what it
    is, never by its id of the day: the same model, built again, must give
    the same order."""
    tie = edge.relationship
    return (
        tie.origin != "stated",
        -tie.confidence,
        tie.type.value,
        str(tie.from_entity_id),
        str(tie.to_entity_id),
    )


def _steady(provenance: dict[str, object]) -> dict[str, object]:
    """Provenance without what changes when nothing is said differently."""
    steady = {k: v for k, v in provenance.items() if k not in VOLATILE}
    steady["sources"] = [
        {k: v for k, v in source.items() if k not in VOLATILE}
        for source in _dicts(provenance.get("sources"))
    ]
    return steady


def _mapping(value: object) -> dict[str, object]:
    return {str(k): v for k, v in value.items()} if isinstance(value, dict) else {}


def _dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [{str(k): v for k, v in item.items()} for item in value if isinstance(item, dict)]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _short(value: object) -> str:
    said = str(value)
    return said if len(said) <= TEXT_VALUE else said[: TEXT_VALUE - 1] + "…"


def _uuid(value: object) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
