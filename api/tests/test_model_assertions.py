"""Validated facts in the company model's build (LEKA-380): pure, no database.

What these protect: a fact validated about an attribute is applied where
no source says one — before enrichment's own guess — and never over a
source's word unless it overrides it, the value it replaced kept in the
provenance with the decision; a validated relationship has the origin
`accepted`, a source's stated one is kept over it, and an inferred one
gives way to it; a loop is broken by dropping an inference, never a
validated link; withdrawn, a fact is no longer applied and what the
sources say comes back — a version recording each change; a fact about a
thing the model does not have is skipped.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from leka.knowledge.build import Assertion, Candidate, Enriched, Link, build
from leka.knowledge.contracts import Previous
from leka.knowledge.repository import fingerprint_of
from tests.test_company_model import (
    NOW,
    PERSON,
    REPO,
    SERVICE,
    by_id,
    current,
    person,
    repo,
    service,
)

CANDIDATE = uuid.uuid4()
DECIDED = {
    "candidate_id": str(CANDIDATE),
    "analyzer": "enrich_criticality",
    "decided_via": "person",
    "decided_by": str(uuid.uuid4()),
    "decided_at": NOW.isoformat(),
}


def fact(**fields: object) -> Assertion:
    said: dict[str, object] = {
        "id": CANDIDATE,
        "kind": "attribute",
        "rule": "enrichment.enrich_criticality",
        "confidence": 0.75,
        "entity_id": SERVICE,
        "attribute": "criticality",
        "value": "critical",
        "evidence": "checkout: said critical; holds Billing",
        "provenance": DECIDED,
        **fields,
    }
    return Assertion(**said)  # type: ignore[arg-type]


def one(rows: list[dict[str, object]]) -> dict[str, Any]:
    [row] = rows
    return cast("dict[str, Any]", row)


# ── attributes ─────────────────────────────────────────────────────────────


def test_a_validated_attribute_is_applied_where_no_source_says_one() -> None:
    built = build([service()], [], {}, now=NOW, assertions=[fact()])

    row = one(built.entities)
    assert row["attributes"]["criticality"] == "critical"
    said = row["provenance"]["attributes"]["criticality"]
    assert said == {
        "origin": "accepted",
        "rule": "enrichment.enrich_criticality",
        "confidence": 0.75,
        "evidence": "checkout: said critical; holds Billing",
        "candidate_id": str(CANDIDATE),
        "decided_via": "person",
        "decided_at": NOW.isoformat(),
    }
    assert built.counts["assertions_applied"] == 1


def test_before_enrichment_s_own_guess() -> None:
    guessed = Candidate(
        **{**service().__dict__, "enriched": {"criticality": Enriched("medium", "landscape", 0.6)}}
    )
    row = one(build([guessed], [], {}, now=NOW, assertions=[fact()]).entities)
    assert row["attributes"]["criticality"] == "critical"
    assert row["provenance"]["attributes"]["criticality"]["origin"] == "accepted"


def test_never_over_a_source_s_word_unless_it_overrides_it() -> None:
    stated = Candidate(**{**service().__dict__, "attributes": {"criticality": "low"}})

    kept = build([stated], [], {}, now=NOW, assertions=[fact()])
    row = one(kept.entities)
    assert row["attributes"]["criticality"] == "low"
    assert row["provenance"]["attributes"]["criticality"] == {"origin": "source"}
    assert kept.counts["assertions_superseded"] == 1

    overridden = one(build([stated], [], {}, now=NOW, assertions=[fact(overrides=True)]).entities)
    assert overridden["attributes"]["criticality"] == "critical"
    assert overridden["provenance"]["attributes"]["criticality"]["replaced"] == "low"
    assert overridden["provenance"]["attributes"]["criticality"]["origin"] == "accepted"


def test_withdrawn_what_the_sources_say_comes_back_a_version_each_time() -> None:
    stated = Candidate(**{**service().__dict__, "attributes": {"criticality": "low"}})
    first = build([stated], [], {}, now=NOW, assertions=[fact(overrides=True)])
    second = build([stated], [], current(first.entities), now=NOW, assertions=[])

    row = one(second.entities)
    assert row["attributes"]["criticality"] == "low"
    assert row["provenance"]["attributes"]["criticality"] == {"origin": "source"}
    [version] = second.versions
    assert (version["version"], version["changed"]) == (2, ["attributes.criticality"])


def test_a_fact_about_a_thing_the_model_does_not_have_is_skipped() -> None:
    elsewhere = fact(entity_id=uuid.uuid4())
    built = build([service()], [], {}, now=NOW, assertions=[elsewhere])
    row = one(built.entities)
    assert "criticality" not in row["attributes"]
    assert built.counts["assertions_applied"] == 0


# ── relationships ──────────────────────────────────────────────────────────


def _owned(confidence: float = 0.9) -> Assertion:
    return fact(
        kind="relationship",
        rule="enrichment.enrich_code",
        confidence=confidence,
        entity_id=None,
        attribute=None,
        value=None,
        from_id=REPO,
        to_id=SERVICE,
        type="part_of",
    )


def test_a_validated_relationship_has_the_origin_accepted() -> None:
    built = build([repo(), service()], [], {}, now=NOW, assertions=[_owned()])

    edge = one(built.relationships)
    assert (edge["from_entity_id"], edge["to_entity_id"], edge["type"]) == (
        REPO,
        SERVICE,
        "part_of",
    )
    assert (edge["origin"], edge["rule"], edge["confidence"]) == (
        "accepted",
        "enrichment.enrich_code",
        0.9,
    )
    [said] = edge["provenance"]
    assert said["candidate_id"] == str(CANDIDATE)
    assert said["decided_via"] == "person"
    assert built.changes[0]["change"] == "added"


def test_a_source_s_word_is_kept_over_it_an_inference_gives_way_to_it() -> None:
    stated = Link(REPO, SERVICE, "part_of", "stated", "stated", 0.6)
    inferred = Link(REPO, SERVICE, "part_of", "inferred", "same_name", 0.95)

    over_inferred = one(
        build([repo(), service()], [inferred], {}, now=NOW, assertions=[_owned(0.7)]).relationships
    )
    assert (over_inferred["origin"], over_inferred["rule"]) == (
        "accepted",
        "enrichment.enrich_code",
    )

    under_stated = one(
        build([repo(), service()], [stated], {}, now=NOW, assertions=[_owned()]).relationships
    )
    assert under_stated["origin"] == "stated"


def test_a_loop_drops_an_inference_never_a_validated_link() -> None:
    # The service part of the repository, the repository part of the
    # service: one must go — the inference, though surer.
    loop = Link(SERVICE, REPO, "part_of", "inferred", "same_name", 0.95)
    built = build([repo(), service()], [loop], {}, now=NOW, assertions=[_owned(0.6)])

    kept = one(built.relationships)
    assert (kept["from_entity_id"], kept["origin"]) == (REPO, "accepted")
    assert [i["issue"] for i in built.issues] == ["cycle_broken"]


def test_withdrawn_a_validated_relationship_is_removed() -> None:
    first = build([repo(), service()], [], {}, now=NOW, assertions=[_owned()])
    previous = {
        (REPO, SERVICE, "part_of"): Previous(
            NOW, NOW, 0.9, "accepted", "enrichment.enrich_code", ()
        )
    }
    second = build(
        [repo(), service()], [], current(first.entities), now=NOW, previous=previous, assertions=[]
    )
    assert second.relationships == []
    assert [c["change"] for c in second.changes] == ["removed"]


def test_a_relationship_to_a_thing_the_model_does_not_have_is_skipped() -> None:
    gone = _owned()
    built = build([repo()], [], {}, now=NOW, assertions=[gone])
    assert built.relationships == []
    assert built.counts["relationships_to_unmodelled"] == 1


# ── what a build was made from ─────────────────────────────────────────────


def test_the_validated_facts_are_one_fingerprint() -> None:
    at = NOW
    one = fingerprint_of([(CANDIDATE, at)])
    assert one == fingerprint_of([(CANDIDATE, at)])
    assert one != fingerprint_of([(CANDIDATE, at.replace(minute=1))])
    assert one != fingerprint_of([(CANDIDATE, at), (uuid.uuid4(), at)])
    # None validated: nothing to build for.
    assert fingerprint_of([]) is None
    assert by_id(build([person()], [], {}, now=NOW).entities)[PERSON]["type"] == "person"
