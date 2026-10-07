"""Relevance and ranking (LEKA-372): leka.context.ranking, through
leka.context.assembly.assemble().

Acme, asked "why is billing slow?": Billing API is the anchor its words
found best; around it, what the retrievers found, from sources doing well
or badly, seen lately or long ago, said by one source or three — some of
them probably the same thing, some disputed.

What these protect, case by case:
- two axes: a thing found as high but better sourced comes first; trust
  never makes a thing found low beat one found high — it moves a score by
  40 % at most;
- being near the anchor adds to what retrieval left, never takes away;
- a signal nothing measures is said unknown and left out of the mean;
- roots and anchors first, never left out, however they score;
- under min_relevance, left out — and said why; 0 keeps everything;
- what resolution linked as probably the same is folded into the better
  ranked — said on both, and what they disagree on said as a conflict; a
  weak link folds nothing; a root is never folded away;
- conflicts said, not merged: a disputed attribute, two owners, a tie to a
  thing gone — each with every side and who says so, the things involved
  less consistent; a conflict about a thing left out is that thing's;
- the budget: what does not fit, listed with why; ties left with an end
  counted;
- every rank traceable: its place, both axes, every signal, the score as
  the formula says;
- a relationship as relevant as its weaker end, a source's word surer
  than a rule's;
- the line a model reads says what is disputed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from leka.context.assembly import Assembly, Element, assemble, text
from leka.context.ranking import Link, Relevance
from leka.context.schemas import RetrievalMatch
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

NOW = datetime(2026, 10, 5, 9, tzinfo=UTC)
CATALOGUE, GITHUB, PAGERDUTY, OLD_JIRA = (uuid.uuid4() for _ in range(4))
SOURCES = [
    MaterialSource(
        source_id=CATALOGUE, kind="backstage", name="Catalogue", status="active", health="healthy"
    ),
    MaterialSource(
        source_id=GITHUB, kind="github", name="GitHub", status="active", health="healthy"
    ),
    MaterialSource(
        source_id=PAGERDUTY,
        kind="pagerduty",
        name="PagerDuty",
        status="degraded",
        health="degraded",
    ),
    MaterialSource(source_id=OLD_JIRA, kind="jira", name="Old Jira", status="error", health=None),
]


def _id(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"ranking/{name}")


def _entity(
    name: str,
    kind: EntityType = EntityType.SERVICE,
    *,
    depth: int | None = None,
    sources: tuple[uuid.UUID, ...] = (CATALOGUE,),
    confidence: float = 0.9,
    quality: float | None = 0.9,
    seen: datetime | None = NOW,
    lifecycle: Lifecycle = Lifecycle.ACTIVE,
    attributes: dict[str, object] | None = None,
    conflicts: list[dict[str, object]] | None = None,
) -> MaterialEntity:
    provenance: dict[str, object] = {
        "sources": [{"source_id": str(s), "key": name.lower(), "kind": "key"} for s in sources]
    }
    if conflicts:
        provenance["conflicts"] = conflicts
    return MaterialEntity(
        entity=EntityRead(
            id=_id(name),
            type=kind,
            key=f"{kind.value}:{name.lower().replace(' ', '-')}",
            name=name,
            attributes=attributes or {},
            lifecycle=lifecycle,
            version=1,
            schema_version=1,
            confidence=confidence,
            quality=quality,
            first_seen_at=NOW - timedelta(days=200),
            last_seen_at=seen,
            removed_at=None,
        ),
        depth=depth,
        provenance=provenance,
    )


def _tie(
    start: str,
    end: str,
    kind: RelationshipType = RelationshipType.DEPENDS_ON,
    *,
    origin: str = "stated",
    confidence: float = 0.9,
    sources: tuple[uuid.UUID, ...] = (CATALOGUE,),
) -> MaterialRelationship:
    return MaterialRelationship(
        relationship=RelationshipRead(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"ranking/{start}-{kind}-{end}"),
            from_entity_id=_id(start),
            to_entity_id=_id(end),
            type=kind,
            confidence=confidence,
            origin=origin,
            rule="stated" if origin == "stated" else "ownership",
            cross_source=False,
            attributes={},
        ),
        provenance=[
            {"source_id": str(s), "record_id": f"r-{start}-{end}", "evidence": "said"}
            for s in sources
        ]
        if origin == "stated"
        else [{"entity_id": str(_id(start))}],
        first_seen_at=NOW - timedelta(days=30),
        changed_at=NOW - timedelta(days=1),
    )


def _material(
    entities: list[MaterialEntity],
    ties: list[MaterialRelationship] | None = None,
    *,
    roots: list[str] | None = None,
) -> ContextMaterial:
    return ContextMaterial(
        roots=[_id(name) for name in roots or []],
        entities=entities,
        relationships=ties or [],
        sources=SOURCES,
        truncated=False,
        built_at=NOW,
        model_version=9,
    )


def _found(score: float, retriever: str = "search", rank: int = 1) -> Relevance:
    return Relevance(
        score=score,
        matches=[RetrievalMatch(retriever=retriever, rank=rank, score=score, detail=None)],
    )


def _assemble(
    material: ContextMaterial,
    relevance: dict[str, float] | None,
    *,
    anchors: tuple[str, ...] = ("Billing API",),
    links: tuple[Link, ...] = (),
    limit: int = 100,
    min_relevance: float = 0.05,
    exclude: tuple[str, ...] = (),
) -> Assembly:
    return assemble(
        material,
        limit=limit,
        strategy="hybrid" if relevance is not None else "neighbourhood",
        relevance=None
        if relevance is None
        else {_id(name): _found(score) for name, score in relevance.items()},
        anchors=[_id(name) for name in anchors],
        links=links,
        now=NOW,
        min_relevance=min_relevance,
        exclude=[_id(name) for name in exclude],
    )


def _entities(made: Assembly) -> list[Element]:
    return [e for e in made.elements if e.kind == "entity"]


def _labels(made: Assembly) -> list[str]:
    return [e.label for e in _entities(made)]


def _of(made: Assembly, label: str) -> Element:
    return next(e for e in made.elements if e.label == label)


def _signal(element: Element, name: str) -> tuple[float | None, str]:
    assert element.ranking is not None
    found = next(s for s in element.ranking.signals if s.name == name)
    return found.value, found.said


BILLING = _entity("Billing API", depth=0)


# ── two axes ────────────────────────────────────────────────────────────────


def test_of_two_found_as_high_the_better_sourced_comes_first() -> None:
    # Ledger and Invoicer found as high; Invoicer only by a failing source,
    # seen four months ago, resolution unsure, its records never measured.
    made = _assemble(
        _material(
            [
                BILLING,
                _entity(
                    "Invoicer",
                    sources=(OLD_JIRA,),
                    confidence=0.6,
                    quality=None,
                    seen=NOW - timedelta(days=120),
                ),
                _entity("Ledger", sources=(CATALOGUE, GITHUB, PAGERDUTY)),
            ]
        ),
        {"Billing API": 0.9, "Invoicer": 0.5, "Ledger": 0.5},
    )
    assert _labels(made) == ["Billing API", "Ledger", "Invoicer"]
    ledger, invoicer = _of(made, "Ledger"), _of(made, "Invoicer")
    assert ledger.ranking is not None and invoicer.ranking is not None
    assert ledger.ranking.topic == invoicer.ranking.topic
    assert ledger.ranking.trust is not None and invoicer.ranking.trust is not None
    assert ledger.ranking.trust > invoicer.ranking.trust
    # Each signal says what it was read from.
    assert _signal(invoicer, "sources") == (0.3, "Its best source, Old Jira, is error and unknown.")
    assert _signal(invoicer, "freshness")[1] == "A source showed it 120 days ago."
    assert _signal(ledger, "corroboration") == (
        1.0,
        "Said by 3 sources: Catalogue, GitHub, PagerDuty.",
    )


def test_trust_never_makes_a_thing_found_low_beat_one_found_high() -> None:
    made = _assemble(
        _material(
            [
                BILLING,
                _entity(
                    "Doubtful",
                    sources=(OLD_JIRA,),
                    confidence=0.3,
                    quality=0.2,
                    seen=NOW - timedelta(days=365),
                    lifecycle=Lifecycle.DORMANT,
                ),
                _entity("Solid", sources=(CATALOGUE, GITHUB, PAGERDUTY), quality=1.0),
            ]
        ),
        {"Billing API": 1.0, "Doubtful": 0.6, "Solid": 0.3},
    )
    assert _labels(made) == ["Billing API", "Doubtful", "Solid"]
    for element in _entities(made):
        ranking = element.ranking
        assert ranking is not None and ranking.trust is not None
        # The score is what the formula says — and so at most 40 % below
        # the topic.
        assert ranking.score == round(ranking.topic * (0.6 + 0.4 * ranking.trust), 4)
        assert ranking.topic * 0.6 <= ranking.score <= ranking.topic


def test_being_near_the_anchor_adds_never_takes_away() -> None:
    made = _assemble(
        _material(
            [BILLING, _entity("Ledger", depth=1), _entity("Payroll")],
            [_tie("Billing API", "Ledger")],
        ),
        {"Billing API": 1.0, "Ledger": 0.3, "Payroll": 0.3},
    )
    ledger, payroll = _of(made, "Ledger"), _of(made, "Payroll")
    assert ledger.ranking is not None and payroll.ranking is not None
    # 0.3 + 0.7 x 0.25 x 1/2: a step from the anchor.
    assert ledger.ranking.topic == pytest.approx(0.3875)
    # Tied to nothing: what retrieval said, no less.
    assert payroll.ranking.topic == pytest.approx(0.3)
    assert _signal(ledger, "proximity") == (0.5, "1 step from Billing API.")
    assert _signal(payroll, "proximity") == (0.0, "Tied to none of the roots.")
    assert _labels(made).index("Ledger") < _labels(made).index("Payroll")


def test_a_neighbourhood_is_ranked_on_nearness_alone() -> None:
    made = _assemble(
        _material(
            [BILLING, _entity("Ledger", depth=1), _entity("Vault", depth=2)],
            [_tie("Billing API", "Ledger"), _tie("Ledger", "Vault")],
            roots=["Billing API"],
        ),
        None,
        anchors=(),
    )
    assert _labels(made) == ["Billing API", "Ledger", "Vault"]
    vault = _of(made, "Vault")
    assert vault.ranking is not None
    assert vault.ranking.topic == pytest.approx(1 / 3, abs=1e-4)
    assert [s.name for s in vault.ranking.signals if s.axis == "topic"] == ["proximity"]
    assert _signal(_of(made, "Billing API"), "asked") == (1.0, "Asked for.")


def test_what_nothing_measures_is_unknown_and_left_out_of_the_mean() -> None:
    unmeasured = _entity("Unmeasured", quality=None, seen=None)
    plain = MaterialSource(source_id=GITHUB, kind="github", name="GitHub")
    material = _material([BILLING, unmeasured]).model_copy(update={"sources": [plain]})
    made = _assemble(material, {"Billing API": 1.0, "Unmeasured": 0.5})
    element = _of(made, "Unmeasured")
    assert _signal(element, "quality") == (None, "Its records' quality was never measured.")
    assert _signal(element, "freshness") == (None, "Never shown by a source.")
    # Its source is Catalogue, which this material does not name: deleted.
    assert _signal(element, "sources")[0] == 0.2
    ranking = element.ranking
    assert ranking is not None and ranking.trust is not None
    known = [s for s in ranking.signals if s.axis == "trust" and s.value is not None]
    assert ranking.trust == pytest.approx(
        sum(s.weight * (s.value or 0) for s in known) / sum(s.weight for s in known), abs=1e-4
    )


# ── what is left out ────────────────────────────────────────────────────────


def test_what_the_request_excludes_is_never_held_and_said_so() -> None:
    """LEKA-387: « sauf Noise » — whatever found it, however relevant."""
    material = _material(
        [_entity("Checkout", depth=0), BILLING, _entity("Noise", depth=1)],
        roots=["Checkout"],
    )
    relevance = {"Checkout": 0.9, "Billing API": 0.8, "Noise": 0.9}
    made = _assemble(material, relevance, exclude=("Noise",))
    assert _labels(made) == ["Checkout", "Billing API"]
    assert made.ranking is not None
    assert made.ranking.left_out["excluded"] == 1
    (noise,) = made.ranking.left
    assert (noise.label, noise.reason, noise.said) == (
        "Noise",
        "excluded",
        "Excluded by the request.",
    )


def test_under_the_threshold_left_out_and_said_never_a_root_nor_an_anchor() -> None:
    material = _material(
        [
            _entity("Checkout", depth=0),
            BILLING,
            _entity("Noise", sources=(OLD_JIRA,), seen=NOW - timedelta(days=300)),
        ],
        roots=["Checkout"],
    )
    relevance = {"Checkout": 0.0, "Billing API": 0.01, "Noise": 0.04}
    made = _assemble(material, relevance)
    assert _labels(made) == ["Checkout", "Billing API"]
    assert made.ranking is not None
    assert made.ranking.left_out == {
        "duplicate": 0,
        "low_relevance": 1,
        "out_of_scope": 0,
        "excluded": 0,
        "budget": 0,
        "ties": 0,
    }
    (noise,) = made.ranking.left
    assert (noise.label, noise.reason) == ("Noise", "low_relevance")
    assert noise.said == f"Scored {noise.score:.2f}, under 0.05."
    # 0 keeps everything the budget holds.
    assert _labels(_assemble(material, relevance, min_relevance=0)) == [
        "Checkout",
        "Billing API",
        "Noise",
    ]


def test_what_does_not_fit_is_listed_and_the_ties_it_takes_counted() -> None:
    made = _assemble(
        _material(
            [BILLING, _entity("Ledger", depth=1), _entity("Vault", depth=2)],
            [_tie("Billing API", "Ledger"), _tie("Ledger", "Vault")],
        ),
        {"Billing API": 1.0, "Ledger": 0.6, "Vault": 0.4},
        limit=3,
    )
    assert [e.label for e in made.elements] == ["Billing API", "Ledger", "Billing API → Ledger"]
    assert made.ranking is not None
    assert made.ranking.left_out == {
        "duplicate": 0,
        "low_relevance": 0,
        "out_of_scope": 0,
        "excluded": 0,
        "budget": 1,
        "ties": 1,
    }
    assert [(i.label, i.reason) for i in made.ranking.left] == [("Vault", "budget")]
    assert made.ranking.left[0].said == "Beyond the budget of 3 elements."
    assert made.dropped == 2 and made.truncated
    # Each entity kept, at its place.
    assert [e.ranking.rank for e in _entities(made) if e.ranking] == [1, 2]


# ── duplicates ──────────────────────────────────────────────────────────────


def test_what_resolution_linked_is_folded_into_the_better_ranked_and_their_disagreement_said() -> (
    None
):
    made = _assemble(
        _material(
            [
                BILLING,
                _entity("Ledger", attributes={"tier": 1, "language": "go"}),
                _entity("ledger-svc", sources=(PAGERDUTY,), attributes={"tier": 2}),
            ]
        ),
        {"Billing API": 1.0, "Ledger": 0.6, "ledger-svc": 0.5},
        links=(Link(_id("ledger-svc"), _id("Ledger"), "same_name", 0.75, "Ledger ~ ledger-svc"),),
    )
    assert _labels(made) == ["Billing API", "Ledger"]
    ledger = _of(made, "Ledger")
    assert ledger.ranking is not None
    assert [(f.label, f.rule, f.confidence) for f in ledger.ranking.duplicates] == [
        ("ledger-svc", "same_name", 0.75)
    ]
    assert made.ranking is not None
    (folded,) = made.ranking.left
    assert (folded.label, folded.reason, folded.duplicate_of) == (
        "ledger-svc",
        "duplicate",
        _id("Ledger"),
    )
    assert folded.said == "Probably the same as Ledger (same_name, 0.75)."
    (conflict,) = made.conflicts
    assert (conflict.kind, conflict.about, conflict.chosen) == ("duplicates", "tier", 1)
    assert [(v.value, v.ref_id, v.by) for v in conflict.values] == [
        (1, _id("Ledger"), ["Catalogue"]),
        (2, _id("ledger-svc"), ["PagerDuty"]),
    ]
    assert ledger.ranking.conflicts == [conflict.id]
    assert _signal(ledger, "consistency") == (0.6, "Disputed: tier.")


def test_a_weak_link_folds_nothing_and_a_root_is_never_folded_away() -> None:
    material = _material(
        [_entity("Checkout", depth=0), BILLING, _entity("checkout-web")], roots=["Checkout"]
    )
    relevance = {"Checkout": 0.1, "Billing API": 1.0, "checkout-web": 0.9}
    weak = _assemble(
        material, relevance, links=(Link(_id("Checkout"), _id("checkout-web"), "fuzzy", 0.4),)
    )
    assert "checkout-web" in _labels(weak)
    sure = _assemble(
        material, relevance, links=(Link(_id("Checkout"), _id("checkout-web"), "fuzzy", 0.8),)
    )
    # Found higher, but the root was asked for: the other goes into it.
    assert _labels(sure) == ["Checkout", "Billing API"]
    assert sure.ranking is not None
    assert sure.ranking.left[0].duplicate_of == _id("Checkout")


# ── conflicts ───────────────────────────────────────────────────────────────


def test_a_disputed_attribute_is_said_with_every_value_and_who_gives_it() -> None:
    billing = _entity(
        "Billing API",
        depth=0,
        sources=(CATALOGUE, PAGERDUTY),
        attributes={"tier": 1},
        conflicts=[
            {
                "attribute": "tier",
                "chosen": 1,
                "values": [
                    {"value": 1, "source_id": str(CATALOGUE)},
                    {"value": 2, "source_id": str(PAGERDUTY)},
                ],
            }
        ],
    )
    made = _assemble(_material([billing]), {"Billing API": 1.0})
    (conflict,) = made.conflicts
    assert (conflict.kind, conflict.subject, conflict.about, conflict.chosen) == (
        "attribute",
        _id("Billing API"),
        "tier",
        1,
    )
    assert [(v.value, v.by) for v in conflict.values] == [(1, ["Catalogue"]), (2, ["PagerDuty"])]
    assert conflict.said == (
        "The sources of Billing API disagree on tier: 1 (Catalogue); 2 (PagerDuty)."
    )
    element = _of(made, "Billing API")
    assert element.ranking is not None and element.ranking.conflicts == [conflict.id]
    # And the line a model reads does not take 1 for the only value said.
    assert text(element).endswith(" — disputed: tier: 1 by Catalogue, 2 by PagerDuty")


def test_two_owners_are_said_not_one_chosen() -> None:
    made = _assemble(
        _material(
            [
                BILLING,
                _entity("Payments", EntityType.TEAM, depth=1),
                _entity("Platform", EntityType.TEAM, depth=1),
            ],
            [
                _tie("Billing API", "Payments", RelationshipType.OWNED_BY),
                _tie("Platform", "Billing API", RelationshipType.OWNS, origin="inferred"),
            ],
        ),
        {"Billing API": 1.0, "Payments": 0.4, "Platform": 0.4},
    )
    (conflict,) = made.conflicts
    assert (conflict.kind, conflict.about, conflict.label) == ("competing", "owner", "Billing API")
    assert [(v.value, v.by) for v in conflict.values] == [
        ("Payments", ["Catalogue"]),
        ("Platform", ["rule ownership"]),
    ]
    # Billing API, both owners and both ties carry it.
    disputed = [e.label for e in made.elements if e.ranking and e.ranking.conflicts]
    assert sorted(disputed) == [
        "Billing API",
        "Billing API → Payments",
        "Payments",
        "Platform",
        "Platform → Billing API",
    ]


def test_two_owners_probably_the_same_person_are_one_owner_and_their_disagreement_said() -> None:
    made = _assemble(
        _material(
            [
                BILLING,
                _entity(
                    "Nadia Kowalski",
                    EntityType.PERSON,
                    depth=1,
                    sources=(GITHUB,),
                    attributes={"email": "nadia.kowalski@acme.example"},
                ),
                _entity(
                    "Nadia K.",
                    EntityType.PERSON,
                    depth=1,
                    sources=(OLD_JIRA,),
                    confidence=0.8,
                    attributes={"email": "nadia.k@acme.example"},
                ),
            ],
            [
                _tie("Nadia Kowalski", "Billing API", RelationshipType.OWNS, sources=(GITHUB,)),
                _tie("Nadia K.", "Billing API", RelationshipType.OWNS, sources=(OLD_JIRA,)),
            ],
        ),
        {"Billing API": 1.0, "Nadia Kowalski": 0.5, "Nadia K.": 0.5},
        links=(Link(_id("Nadia K."), _id("Nadia Kowalski"), "similar_name", 0.78),),
    )
    assert "Nadia K." not in _labels(made)
    (conflict,) = made.conflicts
    assert (conflict.kind, conflict.about, conflict.label) == (
        "duplicates",
        "email",
        "Nadia Kowalski",
    )
    assert [v.value for v in conflict.values] == [
        "nadia.kowalski@acme.example",
        "nadia.k@acme.example",
    ]
    # No competing owners left: Billing API is not disputed.
    assert _signal(_of(made, "Billing API"), "consistency")[0] == 1.0


def test_a_tie_still_stated_to_a_thing_gone_is_said() -> None:
    made = _assemble(
        _material(
            [BILLING, _entity("Legacy Ledger", depth=1, lifecycle=Lifecycle.REMOVED)],
            [_tie("Billing API", "Legacy Ledger")],
        ),
        {"Billing API": 1.0, "Legacy Ledger": 0.5},
    )
    (conflict,) = made.conflicts
    assert (conflict.kind, conflict.subject, conflict.about) == (
        "gone",
        _id("Billing API"),
        "depends_on",
    )
    assert conflict.said == (
        "Billing API depends_on Legacy Ledger is still stated, but Legacy Ledger is gone from "
        "every source."
    )
    assert _signal(_of(made, "Legacy Ledger"), "lifecycle") == (0.1, "It is removed.")


def test_a_conflict_about_a_thing_left_out_is_that_things() -> None:
    noise = _entity(
        "Noise",
        attributes={"tier": 3},
        conflicts=[
            {
                "attribute": "tier",
                "chosen": 3,
                "values": [
                    {"value": 3, "source_id": str(CATALOGUE)},
                    {"value": 4, "source_id": str(GITHUB)},
                ],
            }
        ],
    )
    made = _assemble(_material([BILLING, noise]), {"Billing API": 1.0, "Noise": 0.01})
    assert "Noise" not in _labels(made)
    assert made.conflicts == []


# ── relationships ───────────────────────────────────────────────────────────


def test_a_relationship_is_as_relevant_as_its_weaker_end_and_a_sources_word_is_surer() -> None:
    made = _assemble(
        _material(
            [BILLING, _entity("Ledger", depth=1), _entity("Vault", depth=1)],
            [
                _tie("Billing API", "Ledger"),
                _tie("Billing API", "Vault", RelationshipType.USES, origin="inferred"),
            ],
        ),
        {"Billing API": 1.0, "Ledger": 0.5, "Vault": 0.5},
    )
    stated, inferred = _of(made, "Billing API → Ledger"), _of(made, "Billing API → Vault")
    ledger = _of(made, "Ledger")
    assert stated.ranking is not None and inferred.ranking is not None and ledger.ranking
    assert stated.ranking.topic == ledger.ranking.topic
    assert _signal(stated, "ends") == (
        ledger.ranking.score,
        "As relevant as its weaker end, Ledger.",
    )
    assert stated.ranking.trust is not None and inferred.ranking.trust is not None
    assert stated.ranking.trust > inferred.ranking.trust
    assert _signal(inferred, "origin") == (0.7, "Inferred by ownership.")
    assert stated.ranking.rank is None
