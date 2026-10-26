"""A context's elements, from what a strategy gathered (LEKA-370):
leka.context.assembly.

Acme, around Checkout: it depends on Billing API (its catalogue says so),
which a rule found deployed with Ledger DB; the team Payments owns
Checkout; Nora is a member of Payments. Two steps out, the root first.

What these protect: the roots first, then the nearest, the surest, by
name; each relationship right after its second end, never without one;
why each is there — asked for, reached from which root through which
relationship, or a tie between two; the budget cutting deliberately, what
it left out counted and said; provenance copied whole — each source named
and the key it goes by, a deleted source still said, each attribute's
origin, what the sources disagree on, the records that stated a
relationship and their evidence, the entities a rule read; the
fingerprint unmoved by being seen again or a source renamed, moved by what
is said; what changed between two versions, attribute by attribute; a
line of text for a model; a stored element read back as it was.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from leka.context.assembly import (
    Element,
    assemble,
    diff,
    fingerprint,
    identity,
    restore,
    text,
)
from leka.knowledge import (
    ContextMaterial,
    EntityRead,
    EntityType,
    Lifecycle,
    MaterialEntity,
    MaterialRelationship,
    MaterialSource,
    RelationshipRead,
    RelationshipType,
)

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
CATALOGUE = uuid.uuid4()
HR = uuid.uuid4()
GONE = uuid.uuid4()  # a source deleted since
SOURCES = [
    MaterialSource(source_id=CATALOGUE, kind="backstage", name="Catalogue"),
    MaterialSource(source_id=HR, kind="bamboohr", name="HR"),
]


def _entity(
    name: str,
    kind: EntityType,
    depth: int,
    *,
    confidence: float = 0.9,
    attributes: dict[str, object] | None = None,
    provenance: dict[str, object] | None = None,
    seen: datetime = NOW,
) -> MaterialEntity:
    return MaterialEntity(
        entity=EntityRead(
            id=uuid.uuid5(uuid.NAMESPACE_URL, name),
            type=kind,
            key=f"{kind.value}:{name.lower().replace(' ', '-')}",
            name=name,
            attributes=attributes or {},
            lifecycle=Lifecycle.ACTIVE,
            version=1,
            schema_version=1,
            confidence=confidence,
            quality=None,
            first_seen_at=NOW - timedelta(days=30),
            last_seen_at=seen,
            removed_at=None,
        ),
        depth=depth,
        provenance=provenance
        or {"sources": [{"source_id": str(CATALOGUE), "key": name.lower(), "kind": "key"}]},
    )


def _tie(
    start: MaterialEntity,
    end: MaterialEntity,
    kind: RelationshipType,
    *,
    origin: str = "stated",
    rule: str = "stated",
    confidence: float = 0.9,
    records: list[dict[str, object]] | None = None,
) -> MaterialRelationship:
    return MaterialRelationship(
        relationship=RelationshipRead(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"{start.entity.name}-{kind}-{end.entity.name}"),
            from_entity_id=start.entity.id,
            to_entity_id=end.entity.id,
            type=kind,
            confidence=confidence,
            origin=origin,
            rule=rule,
            cross_source=False,
            attributes={},
        ),
        provenance=records
        if records is not None
        else [{"source_id": str(CATALOGUE), "record_id": "r-1", "evidence": "dependsOn"}],
        first_seen_at=NOW - timedelta(days=10),
        changed_at=NOW - timedelta(days=1),
    )


CHECKOUT = _entity(
    "Checkout",
    EntityType.SERVICE,
    0,
    attributes={"language": "python", "tier": 1},
    provenance={
        "sources": [
            {"source_id": str(CATALOGUE), "key": "checkout", "kind": "key"},
            {"source_id": str(GONE), "key": "PCHK01", "kind": "key"},
        ],
        "attributes": {
            "language": {"origin": "source"},
            "tier": {"origin": "enrichment", "rule": "criticality", "confidence": 0.7},
        },
        "conflicts": [
            {
                "attribute": "tier",
                "chosen": 1,
                "values": [{"value": 1, "source_id": str(CATALOGUE)}],
            }
        ],
    },
)
BILLING = _entity("Billing API", EntityType.SERVICE, 1, confidence=0.95)
PAYMENTS = _entity("Payments", EntityType.TEAM, 1, confidence=0.95)
LEDGER = _entity("Ledger DB", EntityType.DATABASE, 2, confidence=0.6)
NORA = _entity(
    "Nora Diallo",
    EntityType.PERSON,
    2,
    provenance={"sources": [{"source_id": str(HR), "key": "nora@acme.io", "kind": "key"}]},
)
DEPENDS = _tie(CHECKOUT, BILLING, RelationshipType.DEPENDS_ON)
OWNS = _tie(PAYMENTS, CHECKOUT, RelationshipType.OWNS, confidence=0.95)
DEPLOYED = _tie(
    BILLING,
    LEDGER,
    RelationshipType.DEPENDS_ON,
    origin="inferred",
    rule="deployed_together",
    confidence=0.8,
    records=[{"entity_id": str(BILLING.entity.id)}, {"entity_id": str(LEDGER.entity.id)}],
)
MEMBER = _tie(
    NORA,
    PAYMENTS,
    RelationshipType.MEMBER_OF,
    records=[{"source_id": str(HR), "record_id": "p-1", "evidence": "team"}],
)


def _material(
    entities: list[MaterialEntity] | None = None,
    ties: list[MaterialRelationship] | None = None,
    *,
    truncated: bool = False,
    sources: list[MaterialSource] | None = None,
) -> ContextMaterial:
    return ContextMaterial(
        roots=[CHECKOUT.entity.id],
        entities=entities or [CHECKOUT, BILLING, PAYMENTS, LEDGER, NORA],
        relationships=ties if ties is not None else [DEPENDS, OWNS, DEPLOYED, MEMBER],
        sources=sources if sources is not None else SOURCES,
        truncated=truncated,
        built_at=NOW,
        model_version=9,
    )


def _labels(elements: list[Element]) -> list[str]:
    return [e.label for e in elements]


def test_the_roots_first_then_the_nearest_each_tie_after_its_second_end() -> None:
    made = assemble(_material(), limit=100, strategy="neighbourhood")

    assert _labels(made.elements) == [
        "Checkout",
        "Billing API",
        "Checkout → Billing API",
        "Payments",
        "Payments → Checkout",
        # Two steps out, the surest first.
        "Nora Diallo",
        "Nora Diallo → Payments",
        "Ledger DB",
        "Billing API → Ledger DB",
    ]
    assert not made.truncated
    assert made.dropped == 0
    assert made.summary.entities == 5
    assert made.summary.relationships == 4
    assert (made.summary.stated, made.summary.inferred) == (3, 1)
    assert made.summary.by_type == {
        "database": 1,
        "depends_on": 2,
        "member_of": 1,
        "owns": 1,
        "person": 1,
        "service": 2,
        "team": 1,
    }
    assert made.summary.by_source_kind == {"backstage": 6, "bamboohr": 2, "unknown": 1}


def test_why_each_is_there() -> None:
    made = {
        e.label: e.reason
        for e in assemble(_material(), limit=100, strategy="neighbourhood").elements
    }
    root = CHECKOUT.entity.id

    assert made["Checkout"].role == "root"
    assert (made["Checkout"].depth, made["Checkout"].root, made["Checkout"].via) == (0, root, None)
    assert made["Billing API"].role == "reached"
    assert (made["Billing API"].root, made["Billing API"].via) == (root, DEPENDS.relationship.id)
    # Two steps: through Billing API, by what a rule inferred.
    assert (made["Ledger DB"].depth, made["Ledger DB"].via) == (2, DEPLOYED.relationship.id)
    assert (made["Nora Diallo"].root, made["Nora Diallo"].via) == (root, MEMBER.relationship.id)
    tie = made["Billing API → Ledger DB"]
    assert (tie.role, tie.depth, tie.root, tie.via) == ("tie", 2, None, None)
    assert {r.strategy for r in made.values()} == {"neighbourhood"}


def test_the_budget_cuts_deliberately_never_a_tie_without_its_ends() -> None:
    made = assemble(_material(), limit=4, strategy="neighbourhood")

    assert _labels(made.elements) == [
        "Checkout",
        "Billing API",
        "Checkout → Billing API",
        "Payments",
    ]
    assert made.truncated
    assert made.dropped == 5

    # Ties do not count against an entity they would leave out.
    taken = {e.ref_id for e in made.elements if e.kind == "entity"}
    for element in made.elements:
        if element.relationship is not None:
            assert {element.relationship.start.id, element.relationship.end.id} <= taken

    # A walk that stopped short is said, whatever the budget.
    assert assemble(_material(truncated=True), limit=100, strategy="neighbourhood").truncated


def test_an_entity_keeps_its_sources_each_attribute_s_origin_and_its_conflicts() -> None:
    checkout = assemble(_material(), limit=100, strategy="neighbourhood").elements[0]
    said = checkout.provenance

    assert said.origin == "stated"
    assert said.confidence == 0.9
    assert [(s.source_id, s.kind, s.name, s.key) for s in said.sources] == [
        (CATALOGUE, "backstage", "Catalogue", "checkout"),
        # Deleted since: still said — its key there — but no kind, no name:
        # a provenance's kind is its key's, not its tool's.
        (GONE, None, None, "PCHK01"),
    ]
    assert said.attributes["tier"] == {
        "origin": "enrichment",
        "rule": "criticality",
        "confidence": 0.7,
    }
    assert said.conflicts[0]["attribute"] == "tier"
    assert (said.first_seen_at, said.last_seen_at) == (NOW - timedelta(days=30), NOW)
    assert checkout.entity is not None
    assert checkout.entity.attributes == {"language": "python", "tier": 1}
    assert (checkout.entity.key, checkout.entity.version) == ("service:checkout", 1)


def test_a_relationship_keeps_the_records_that_stated_it_or_what_a_rule_read() -> None:
    made = {e.label: e for e in assemble(_material(), limit=100, strategy="neighbourhood").elements}

    stated = made["Checkout → Billing API"].provenance
    assert (stated.origin, stated.rule) == ("stated", "stated")
    assert [(s.source_id, s.name, s.record_id) for s in stated.sources] == [
        (CATALOGUE, "Catalogue", "r-1")
    ]
    assert stated.evidence == ["dependsOn"]
    assert stated.changed_at == NOW - timedelta(days=1)

    inferred = made["Billing API → Ledger DB"].provenance
    assert (inferred.origin, inferred.rule, inferred.confidence) == (
        "inferred",
        "deployed_together",
        0.8,
    )
    assert inferred.sources == []
    assert inferred.inferred_from == [BILLING.entity.id, LEDGER.entity.id]

    tie = made["Billing API → Ledger DB"].relationship
    assert tie is not None
    assert (tie.start.name, tie.end.name, tie.type) == ("Billing API", "Ledger DB", "depends_on")


def test_the_fingerprint_moves_with_what_is_said_only() -> None:
    first = assemble(_material(), limit=100, strategy="neighbourhood").fingerprint

    # Seen again, a source renamed: nothing said differently.
    again = _entity("Billing API", EntityType.SERVICE, 1, confidence=0.95, seen=NOW + timedelta(1))
    renamed = [MaterialSource(source_id=CATALOGUE, kind="backstage", name="Backstage"), SOURCES[1]]
    assert (
        assemble(
            _material([CHECKOUT, again, PAYMENTS, LEDGER, NORA], sources=renamed),
            limit=100,
            strategy="neighbourhood",
        ).fingerprint
        == first
    )

    # An attribute changed: a new version.
    moved = _entity("Billing API", EntityType.SERVICE, 1, confidence=0.95, attributes={"tier": 2})
    assert (
        assemble(
            _material([CHECKOUT, moved, PAYMENTS, LEDGER, NORA]),
            limit=100,
            strategy="neighbourhood",
        ).fingerprint
        != first
    )
    # Fewer things: a new version.
    assert assemble(_material(), limit=3, strategy="neighbourhood").fingerprint != first


def test_what_changed_between_two_versions() -> None:
    before = assemble(_material(), limit=100, strategy="neighbourhood").elements
    moved = _entity(
        "Billing API",
        EntityType.SERVICE,
        1,
        confidence=0.95,
        attributes={"tier": 2},
        provenance={
            "sources": [{"source_id": str(HR), "key": "billing", "kind": "key"}],
        },
    )
    after = assemble(
        _material([CHECKOUT, moved, PAYMENTS, NORA], [DEPENDS, OWNS, MEMBER]),
        limit=100,
        strategy="neighbourhood",
    ).elements

    added, removed, changed, same = diff(before, after)

    assert added == []
    assert sorted(_labels(removed)) == ["Billing API → Ledger DB", "Ledger DB"]
    assert [(old.label, fields) for old, _, fields in changed] == [
        ("Billing API", ["attributes.tier", "provenance.sources"])
    ]
    assert same == 6


def test_the_same_model_built_again_is_the_same_context() -> None:
    """Each build remakes the relationships, their ids with them: what an
    element is — a relationship's ends and kind — is what counts."""
    before = assemble(_material(), limit=100, strategy="neighbourhood")
    remade = [
        MaterialRelationship(
            relationship=tie.relationship.model_copy(update={"id": uuid.uuid4()}),
            provenance=tie.provenance,
            first_seen_at=tie.first_seen_at,
            changed_at=tie.changed_at + timedelta(hours=1) if tie.changed_at else None,
        )
        for tie in reversed([DEPENDS, OWNS, DEPLOYED, MEMBER])
    ]
    after = assemble(_material(ties=remade), limit=100, strategy="neighbourhood")

    assert _labels(after.elements) == _labels(before.elements)
    assert after.fingerprint == before.fingerprint
    assert diff(before.elements, after.elements)[1:] == ([], [], 9)
    assert identity(after.elements[2]) == (f"{CHECKOUT.entity.id}>depends_on>{BILLING.entity.id}")


def test_a_line_for_a_model_to_read() -> None:
    made = {e.label: e for e in assemble(_material(), limit=100, strategy="neighbourhood").elements}

    assert text(made["Checkout"]) == (
        'service "Checkout" (service:checkout): language: python; tier: 1 '
        "[from Catalogue, a deleted source]"
    )
    assert text(made["Checkout → Billing API"]) == (
        '"Checkout" depends_on "Billing API" — stated by Catalogue, confidence 0.90'
    )
    assert text(made["Billing API → Ledger DB"]) == (
        '"Billing API" depends_on "Ledger DB" — inferred by deployed_together, confidence 0.80'
    )


def test_a_stored_element_reads_back_as_it_was() -> None:
    for element in assemble(_material(), limit=100, strategy="neighbourhood").elements:
        stored = restore(
            element.kind,
            element.ref_id,
            element.ref_type,
            element.label,
            element.content(),
            element.provenance.model_dump(mode="json"),
            element.reason.model_dump(mode="json"),
            element.relevance,
            element.ranking.model_dump(mode="json") if element.ranking else None,
        )
        assert stored == element
    # What a later contract adds is ignored, not refused; an element kept
    # before LEKA-372 reads back with no ranking.
    element = assemble(_material(), limit=1, strategy="neighbourhood").elements[0]
    later = {**element.provenance.model_dump(mode="json"), "lineage": ["a later field"]}
    assert restore(
        element.kind,
        element.ref_id,
        element.ref_type,
        element.label,
        element.content(),
        later,
        element.reason.model_dump(mode="json"),
    ) == replace(element, ranking=None)
    # How it was ranked is not what it holds.
    assert fingerprint([element]) == fingerprint([replace(element, ranking=None)])
