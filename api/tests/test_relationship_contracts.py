"""Relationship contracts and history, as a build applies them (LEKA-368).

The pure part: a build's relationships in — the kinds of their ends known —
the relationships kept, the issues found, the changes since the last build
out.

What these protect: every kind of relationship has a contract, versioned;
an end a contract does not take is dropped, said as an error; an inferred
link closing a loop where none may be is dropped — the weakest — a loop the
sources state is kept and said, a dependency loop too; two of what a thing
has one of, said; a relationship's history — added, changed, removed — and
when it first appeared, kept across builds, an inference's small drift no
news.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from leka.knowledge.contracts import Previous, check, history
from leka.knowledge.models import RelationshipType
from leka.knowledge.registry import DEPENDENCIES, RELATIONSHIP_KINDS

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
A, B, C, SARA, NORA, KARIM, TEAM, DEPLOY = (uuid.uuid4() for _ in range(8))
TYPES = {
    A: "service",
    B: "service",
    C: "application",
    SARA: "person",
    NORA: "person",
    KARIM: "person",
    TEAM: "team",
    DEPLOY: "deployment",
}


def _edge(
    a: uuid.UUID,
    kind: str,
    b: uuid.UUID,
    *,
    origin: str = "stated",
    confidence: float = 1.0,
    environments: list[str] | None = None,
) -> tuple[tuple[uuid.UUID, uuid.UUID, str], dict[str, object]]:
    return (a, b, kind), {
        "from_entity_id": a,
        "to_entity_id": b,
        "type": kind,
        "origin": origin,
        "rule": "stated" if origin == "stated" else "inherited",
        "confidence": confidence,
        "attributes": {"environments": environments} if environments else {},
    }


def _issues(found: list[object]) -> set[tuple[str, str, str]]:
    return {(i.type, i.issue, i.severity) for i in found}  # type: ignore[attr-defined]


def test_every_kind_of_relationship_has_a_versioned_contract() -> None:
    for kind in RELATIONSHIP_KINDS.values():
        assert kind.meaning, kind.type
        assert kind.version >= 2
    assert set(RELATIONSHIP_KINDS) == set(RelationshipType)
    reports_to = RELATIONSHIP_KINDS[RelationshipType.REPORTS_TO]
    assert (reports_to.single, reports_to.acyclic) == (True, True)
    assert set(DEPENDENCIES) == {
        RelationshipType.DEPENDS_ON,
        RelationshipType.READS_FROM,
        RelationshipType.REFERENCES,
        RelationshipType.SUPPORTED_BY,
        RelationshipType.USES,
    }


def test_an_end_its_contract_does_not_take_is_dropped_and_said() -> None:
    edges = dict(
        [
            _edge(TEAM, "reports_to", SARA),  # a team reports to no one
            _edge(A, "deploys", B),  # a service deploys nothing
            _edge(NORA, "reports_to", SARA),
        ]
    )

    kept, issues = check(edges, TYPES)

    assert list(kept) == [(NORA, SARA, "reports_to")]
    wrong = {(i.type, i.detail["end"], i.detail["found"]) for i in issues}
    assert wrong == {("reports_to", "from", "team"), ("deploys", "from", "service")}
    assert {i.severity for i in issues} == {"error"}


def test_an_inferred_link_closing_a_loop_is_dropped_the_weakest() -> None:
    edges = dict(
        [
            _edge(A, "part_of", C),
            _edge(C, "part_of", B, origin="inferred", confidence=0.6),
            _edge(B, "part_of", A, origin="inferred", confidence=0.8),
        ]
    )

    kept, issues = check(edges, TYPES)

    assert (C, B, "part_of") not in kept
    assert {(A, C, "part_of"), (B, A, "part_of")} <= set(kept)
    [broken] = issues
    assert (broken.issue, broken.severity, broken.to_id) == ("cycle_broken", "warning", B)
    assert broken.detail["members"] == sorted(str(x) for x in (A, B, C))


def test_a_loop_the_sources_state_is_kept_and_said_as_a_dependency_loop() -> None:
    edges = dict(
        [
            _edge(SARA, "reports_to", NORA),
            _edge(NORA, "reports_to", SARA),
            _edge(A, "depends_on", B),
            _edge(B, "depends_on", A),
        ]
    )

    kept, issues = check(edges, TYPES)

    assert len(kept) == 4
    assert _issues(issues) == {
        ("reports_to", "cycle", "warning"),
        ("depends_on", "cycle", "warning"),
    }


def test_two_of_what_a_thing_has_one_of_is_said_the_surest_first() -> None:
    edges = dict(
        [
            _edge(NORA, "reports_to", SARA),
            _edge(NORA, "reports_to", KARIM, origin="inferred", confidence=0.7),
        ]
    )

    kept, issues = check(edges, TYPES)

    assert len(kept) == 2
    [several] = issues
    assert (several.issue, several.to_id) == ("several_targets", KARIM)
    assert several.detail["targets"] == [str(SARA), str(KARIM)]


def test_a_relationship_s_history_across_builds() -> None:
    before = NOW - timedelta(days=3)
    previous = {
        (A, B, "depends_on"): Previous(before, before, 1.0, "stated", "stated", ()),
        (A, C, "part_of"): Previous(before, before, 0.80, "inferred", "inherited", ()),
        (B, C, "part_of"): Previous(before, before, 0.80, "inferred", "inherited", ()),
        (SARA, TEAM, "member_of"): Previous(before, before, 1.0, "stated", "stated", ()),
    }
    edges = dict(
        [
            _edge(A, "depends_on", B),  # the same
            _edge(A, "part_of", C, origin="inferred", confidence=0.82),  # a drift: no news
            _edge(B, "part_of", C, origin="inferred", confidence=0.6),  # changed
            _edge(NORA, "member_of", TEAM),  # new
        ]
    )

    changes = history(edges, previous, NOW)

    by_key = {(c["from_entity_id"], c["to_entity_id"], c["type"]): c for c in changes}
    assert {k: c["change"] for k, c in by_key.items()} == {
        (B, C, "part_of"): "changed",
        (NORA, TEAM, "member_of"): "added",
        (SARA, TEAM, "member_of"): "removed",
    }
    changed = by_key[(B, C, "part_of")]
    assert (changed["before"]["confidence"], changed["after"]["confidence"]) == (0.8, 0.6)  # type: ignore[index]
    assert edges[(A, B, "depends_on")]["first_seen_at"] == before
    assert edges[(A, C, "part_of")]["changed_at"] == before
    assert edges[(B, C, "part_of")]["changed_at"] == NOW
    assert edges[(NORA, TEAM, "member_of")]["first_seen_at"] == NOW


def test_a_relationship_true_in_other_environments_has_changed() -> None:
    previous = {(A, B, "depends_on"): Previous(NOW, NOW, 1.0, "stated", "stated", ("staging",))}
    edges = dict([_edge(A, "depends_on", B, environments=["production"])])

    [change] = history(edges, previous, NOW + timedelta(hours=1))

    assert change["change"] == "changed"
