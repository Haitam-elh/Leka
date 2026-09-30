"""The company model's build and registry (LEKA-361): pure, no database.

What these protect: an entity's id is its resolved entity's, kept from one
build to the next; what it says is its sources' word, then enrichment's —
never enrichment's over a source's — and says where each piece came from;
a change of the thing is a new version, recorded with what changed, a
change of the clock is not; its lifecycle follows its sources, and a thing
no source shows any more is removed, kept, and comes back as itself; a
schema drops what does not fit and lets through what it does not know; a
relationship is the registry's type, the stated one kept over the inferred.

And the registry covers what the stages before it make: a type normalisation
or enrichment starts to produce is either modelled or left out on purpose.

The job, the database and the API are tests/test_company_model_job.py's.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from leka.ingestion.normalisation.mapping import (
    CUSTOM_ENTITIES,
    ENTITY_TYPES,
    PERSON_ROLES,
    REFERENCE_TYPES,
)
from leka.knowledge import EntityType, Lifecycle, RelationshipType
from leka.knowledge.build import (
    MEASURES,
    Candidate,
    Current,
    Enriched,
    Link,
    SeenKey,
    build,
    changes,
    content_of,
    fingerprint,
)
from leka.knowledge.registry import (
    BUILT_FROM,
    ENTITY_KINDS,
    NOT_MODELLED,
    RELATIONSHIP_FROM,
    RELATIONSHIP_KINDS,
    clean,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
GITHUB = uuid.uuid4()
PAGERDUTY = uuid.uuid4()
REPO = uuid.uuid4()
SERVICE = uuid.uuid4()
PERSON = uuid.uuid4()


def repo(**attributes: object) -> Candidate:
    return Candidate(
        id=REPO,
        type="repository",
        key="github.com/acme/billing-api",
        name="acme/billing-api",
        attributes={"language": "python", **attributes},
        confidence=0.95,
        quality=0.9,
        keys=(
            SeenKey(
                "github.com/acme/billing-api",
                GITHUB,
                "id",
                NOW - timedelta(days=30),
                NOW - timedelta(hours=1),
            ),
        ),
    )


def service() -> Candidate:
    return Candidate(
        id=SERVICE,
        type="service",
        key="service:billing",
        name="Billing",
        attributes={},
        keys=(SeenKey("service:billing", PAGERDUTY, "name"),),
    )


def person() -> Candidate:
    return Candidate(
        id=PERSON, type="person", key="person:email:sara@acme.io", name="Sara", attributes={}
    )


def current(built: list[dict[str, Any]]) -> dict[uuid.UUID, Current]:
    """What the last build left, as the repository reads it back."""
    names = [field.name for field in dataclasses.fields(Current)]
    return {row["id"]: Current(**{name: row[name] for name in names}) for row in built}


def by_id(rows: list[dict[str, Any]]) -> dict[uuid.UUID, dict[str, Any]]:
    return {row["id"]: row for row in rows}


def only(rows: list[dict[str, Any]]) -> dict[str, Any]:
    [row] = rows
    return row


# ── identity, content, provenance ────────────────────────────────────────────


def test_an_entity_is_its_resolved_entity_with_where_it_came_from() -> None:
    candidate = Candidate(
        **{
            **repo().__dict__,
            "enriched": {
                "lifecycle": Enriched("active", "last_activity", 0.9),
                # A source's word is never replaced by a rule's.
                "language": Enriched("go", "guess", 0.5),
            },
        }
    )

    built = build([candidate], [], {}, now=NOW)

    [row] = built.entities
    assert (row["id"], row["type"], row["key"], row["version"]) == (
        REPO,
        "repository",
        "github.com/acme/billing-api",
        1,
    )
    assert row["attributes"] == {"language": "python", "lifecycle": "active"}
    assert (row["lifecycle"], row["removed_at"]) == ("active", None)
    assert (row["confidence"], row["quality"]) == (0.95, 0.9)
    assert row["first_seen_at"] == NOW - timedelta(days=30)
    assert row["last_seen_at"] == NOW - timedelta(hours=1)
    assert row["provenance"] == {
        "sources": [{"source_id": str(GITHUB), "key": "github.com/acme/billing-api", "kind": "id"}],
        "attributes": {
            "language": {"origin": "source"},
            "lifecycle": {"origin": "enrichment", "rule": "last_activity", "confidence": 0.9},
        },
        "dropped": [],
        "conflicts": [],
    }
    [version] = built.versions
    assert (version["entity_id"], version["version"], version["changed"]) == (
        REPO,
        1,
        ["created"],
    )
    assert version["content"] == content_of("acme/billing-api", {"language": "python"}, "active")
    assert built.counts["created"] == 1


def test_the_same_thing_built_again_is_the_same_version() -> None:
    first = build([repo()], [], {}, now=NOW)

    again = build([repo()], [], current(first.entities), now=NOW + timedelta(hours=1))

    [row] = again.entities
    assert (row["id"], row["version"]) == (REPO, 1)
    assert row["content_hash"] == first.entities[0]["content_hash"]
    assert row["first_seen_at"] == first.entities[0]["first_seen_at"]
    assert again.versions == []
    assert (again.counts["unchanged"], again.counts["changed"]) == (1, 0)


def test_a_change_of_the_thing_is_a_new_version_that_says_what_changed() -> None:
    first = build([repo()], [], {}, now=NOW)

    renamed = Candidate(**{**repo(language="go").__dict__, "name": "acme/billing"})
    second = build([renamed], [], current(first.entities), now=NOW + timedelta(days=1))

    [row] = second.entities
    assert row["version"] == 2
    [version] = second.versions
    assert (version["version"], version["changed"]) == (2, ["name", "attributes.language"])
    assert second.counts["changed"] == 1


def test_a_change_of_the_clock_is_kept_current_but_no_version() -> None:
    first = build([repo(activity_90d=3)], [], {}, now=NOW)

    later = repo(activity_90d=9, last_activity_at="2026-09-30T10:00:00Z")
    second = build([later], [], current(first.entities), now=NOW + timedelta(days=1))

    row = only(second.entities)
    assert row["version"] == 1
    assert row["attributes"]["activity_90d"] == 9
    assert second.versions == []
    assert {"activity_90d", "last_activity_at", "incidents_90d"} <= MEASURES


# ── lifecycle ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("attributes", "enriched", "lifecycle"),
    [
        ({"state": "archived"}, {}, "archived"),
        ({}, {"lifecycle": Enriched("dormant", "last_activity", 0.8)}, "dormant"),
        ({}, {"lifecycle": Enriched("active", "last_activity", 0.8)}, "active"),
        ({}, {}, "active"),
    ],
)
def test_the_lifecycle_follows_the_sources(
    attributes: dict[str, object], enriched: dict[str, Enriched], lifecycle: str
) -> None:
    candidate = Candidate(**{**repo(**attributes).__dict__, "enriched": enriched})

    [row] = build([candidate], [], {}, now=NOW).entities

    assert row["lifecycle"] == lifecycle


def test_a_thing_no_source_shows_is_removed_kept_and_comes_back_as_itself() -> None:
    first = build([repo(), service()], [], {}, now=NOW)

    gone = build([service()], [], current(first.entities), now=NOW + timedelta(days=1))

    removed = by_id(gone.entities)[REPO]
    assert (removed["lifecycle"], removed["removed_at"], removed["version"]) == (
        "removed",
        NOW + timedelta(days=1),
        2,
    )
    assert removed["attributes"] == {"language": "python"}  # kept as it was
    assert [(v["entity_id"], v["changed"]) for v in gone.versions] == [(REPO, ["lifecycle"])]
    assert gone.counts["removed"] == 1

    still = build([service()], [], current(gone.entities), now=NOW + timedelta(days=2))
    assert still.counts["still_removed"] == 1
    assert REPO not in by_id(still.entities)  # nothing to write

    back = build([repo(), service()], [], current(gone.entities), now=NOW + timedelta(days=3))
    returned = by_id(back.entities)[REPO]
    assert (returned["lifecycle"], returned["removed_at"], returned["version"]) == (
        "active",
        None,
        3,
    )
    assert returned["first_seen_at"] == NOW - timedelta(days=30)
    assert returned["lifecycle_changed_at"] == NOW + timedelta(days=3)


def test_what_the_model_leaves_out_is_counted() -> None:
    branch = Candidate(id=uuid.uuid4(), type="branch", key="b", name="main", attributes={})

    built = build([branch], [], {}, now=NOW)

    assert built.entities == []
    assert built.counts["not_modelled"] == 1


# ── schemas ──────────────────────────────────────────────────────────────────


def test_a_schema_drops_what_does_not_fit_and_lets_through_what_it_does_not_know() -> None:
    kept, dropped = clean(
        ENTITY_KINDS[EntityType.REPOSITORY],
        {"topics": 5, "language": "python", "stars": 12, "fork": "maybe"},
    )

    assert kept == {"language": "python", "stars": 12}
    assert dropped == ["fork", "topics"]


def test_a_dropped_attribute_is_said_in_the_provenance() -> None:
    row = only(build([repo(topics="not-a-list")], [], {}, now=NOW).entities)

    assert "topics" not in row["attributes"]
    assert row["provenance"]["dropped"] == ["topics"]


# ── relationships ────────────────────────────────────────────────────────────


def test_relationships_take_the_registry_s_types_the_stated_kept_over_the_inferred() -> None:
    elsewhere = uuid.uuid4()
    links = [
        Link(REPO, SERVICE, "part_of", "inferred", "same_name", 0.7),
        Link(REPO, SERVICE, "part_of", "stated", "stated", 0.6, True, ({"source_id": "x"},)),
        Link(REPO, PERSON, "committed_by", "stated", "stated", 1.0),
        Link(REPO, elsewhere, "part_of", "stated", "stated", 1.0),
        Link(REPO, SERVICE, "haunts", "inferred", "ghost", 0.9),
    ]

    built = build([repo(), service(), person()], links, {}, now=NOW)

    edges = {(e["from_entity_id"], e["type"], e["to_entity_id"]): e for e in built.relationships}
    part_of = edges[(REPO, "part_of", SERVICE)]
    assert (part_of["origin"], part_of["confidence"], part_of["cross_source"]) == (
        "stated",
        0.6,
        True,
    )
    assert part_of["provenance"] == [{"source_id": "x"}]
    assert (REPO, "authored_by", PERSON) in edges
    assert len(edges) == 2
    assert built.counts["relationships_to_unmodelled"] == 1
    assert built.counts["relationships_not_modelled"] == 1


# ── versions, as content ─────────────────────────────────────────────────────


def test_what_changed_is_named_and_the_fingerprint_ignores_order() -> None:
    before = content_of("a", {"x": 1, "y": [1, 2]}, "active")
    after = content_of("a", {"y": [1, 2], "z": True}, "dormant")

    assert changes(before, after) == ["lifecycle", "attributes.x", "attributes.z"]
    assert fingerprint({"b": 1, "a": 2}) == fingerprint({"a": 2, "b": 1})
    measured: Any = content_of("a", {"activity_90d": 4}, "active")
    assert measured["attributes"] == {}


# ── the registry covers what the stages before it make ───────────────────────


def test_every_type_has_its_kind_in_the_registry() -> None:
    assert set(ENTITY_KINDS) == set(EntityType)
    assert set(RELATIONSHIP_KINDS) == set(RelationshipType)
    assert all(kind.version >= 1 for kind in ENTITY_KINDS.values())


def test_every_type_normalisation_makes_is_modelled_or_left_out_on_purpose() -> None:
    made = {
        *ENTITY_TYPES.values(),
        *CUSTOM_ENTITIES,
        "person",
        "team",
        "service",
        "application",
        "environment",
    }

    assert not made - set(BUILT_FROM) - NOT_MODELLED, "a kind is missing in registry.py"
    assert not NOT_MODELLED & set(BUILT_FROM)


def test_every_relationship_the_stages_state_or_infer_is_modelled() -> None:
    stated = {*PERSON_ROLES.values(), *REFERENCE_TYPES.values()}
    # What normalisation states between records and enrichment infers
    # (docs/normalisation.md § 3, docs/enrichment.md).
    structural = {
        "part_of",
        "child_of",
        "member_of",
        "owned_by",
        "maintained_by",
        "in_network",
        "depends_on",
        "affects",
        "runs_in",
    }

    assert not (stated | structural) - set(RELATIONSHIP_FROM)


def test_a_lifecycle_is_one_of_four() -> None:
    assert [state.value for state in Lifecycle] == ["active", "dormant", "archived", "removed"]


# ── applications and services (LEKA-362) ────────────────────────────────────

PROD = uuid.uuid4()
INSTANCE = uuid.uuid4()


def test_a_relationship_keeps_the_environment_its_end_runs_in() -> None:
    instance = Candidate(
        id=INSTANCE,
        type="infra_resource",
        key="aws:i-1",
        name="billing-1",
        attributes={"environment": "production"},
    )
    production = Candidate(
        id=PROD, type="environment", key="environment:production", name="production", attributes={}
    )
    links = [
        Link(INSTANCE, SERVICE, "part_of", "stated", "stated", 0.95),
        Link(INSTANCE, PROD, "runs_in", "stated", "stated", 0.95),
        Link(SERVICE, PROD, "runs_in", "inferred", "parts", 0.95),
        Link(REPO, SERVICE, "part_of", "inferred", "same_name", 0.8),
    ]

    built = build([instance, production, service(), repo()], links, {}, now=NOW)

    edges = {(e["from_entity_id"], e["type"], e["to_entity_id"]): e for e in built.relationships}
    assert edges[(INSTANCE, "part_of", SERVICE)]["attributes"] == {"environments": ["production"]}
    assert edges[(SERVICE, "runs_in", PROD)]["attributes"] == {"environments": ["production"]}
    # A repository and its service, seen in production only: production's.
    assert edges[(REPO, "part_of", SERVICE)]["attributes"] == {"environments": ["production"]}


def test_a_thing_that_runs_in_several_environments_says_none_of_them() -> None:
    staging = uuid.uuid4()
    environments = [
        Candidate(
            id=PROD, type="environment", key="environment:production", name="p", attributes={}
        ),
        Candidate(
            id=staging, type="environment", key="environment:staging", name="s", attributes={}
        ),
    ]
    links = [
        Link(SERVICE, PROD, "runs_in", "inferred", "parts", 0.9),
        Link(SERVICE, staging, "runs_in", "inferred", "parts", 0.9),
        Link(REPO, SERVICE, "part_of", "inferred", "same_name", 0.8),
    ]

    built = build([*environments, service(), repo()], links, {}, now=NOW)

    edges = {(e["from_entity_id"], e["type"], e["to_entity_id"]): e for e in built.relationships}
    assert edges[(REPO, "part_of", SERVICE)]["attributes"] == {}
    assert edges[(SERVICE, "runs_in", staging)]["attributes"] == {"environments": ["staging"]}


def test_what_the_sources_disagree_on_is_kept_every_value_with_its_source() -> None:
    disputed = Candidate(
        **{
            **service().__dict__,
            "attributes": {"criticality": "critical"},
            "conflicts": (
                {
                    "attribute": "criticality",
                    "chosen": "critical",
                    "values": [
                        {
                            "value": "critical",
                            "source_id": str(PAGERDUTY),
                            "key": "service:billing",
                        },
                        {"value": "high", "source_id": str(GITHUB), "key": "service:billing"},
                    ],
                },
            ),
        }
    )

    row = only(build([disputed], [], {}, now=NOW).entities)

    assert row["provenance"]["attributes"]["criticality"] == {
        "origin": "source",
        "disputed": True,
    }
    assert row["provenance"]["conflicts"] == [
        {
            "attribute": "criticality",
            "chosen": "critical",
            "values": [
                {"value": "critical", "source_id": str(PAGERDUTY)},
                {"value": "high", "source_id": str(GITHUB)},
            ],
        }
    ]


def test_a_retired_service_is_archived() -> None:
    retired = Candidate(**{**service().__dict__, "attributes": {"stage": "retired"}})

    assert only(build([retired], [], {}, now=NOW).entities)["lifecycle"] == "archived"


def test_a_service_s_schema_keeps_criticality_stage_and_environments() -> None:
    kept, dropped = clean(
        ENTITY_KINDS[EntityType.SERVICE],
        {
            "criticality": "critical",
            "stage": "production",
            "environments": ["production", "staging"],
            "languages": "python",
        },
    )

    assert kept == {
        "criticality": "critical",
        "stage": "production",
        "environments": ["production", "staging"],
    }
    assert dropped == ["languages"]
