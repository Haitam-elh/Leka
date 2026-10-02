"""The company's landscapes, as the screens draw them (LEKA-369). The pure
part: views.py; test_knowledge_graph.py reads them from PostgreSQL through
the API.

What these protect: the API serves every view there is and no other; each
view's rows hold kinds of the model, and the dependency view the
registry's dependencies; cloud resources are boxed per provider and region
where a view boxes them — in their worst state, counted — and listed one by
one where it does not; a line joins two boxes only through the view's own
relationships, once, coloured by the worse of its ends; a thing's state
follows the environment screen's rules; coverage says none for a measure
that does not apply.
"""

from __future__ import annotations

import uuid
from typing import get_args

from leka.api.graph import View as ApiView
from leka.knowledge.models import EntityType, RelationshipType
from leka.knowledge.registry import DEPENDENCIES
from leka.knowledge.views import (
    VIEWS,
    Layer,
    Placed,
    Tie,
    View,
    coverage,
    layout,
    state,
)

E = EntityType
R = RelationshipType
PAYMENTS, BILLING, ORDERS, EC2_A, EC2_B, EC2_C, VM = (uuid.uuid4() for _ in range(7))
TEAM = uuid.uuid4()

SERVICES = View(
    "test",
    (
        Layer("services", (E.SERVICE,)),
        Layer("data", (E.DATABASE,)),
        Layer("infrastructure", (E.INFRA_RESOURCE,), boxed=True),
    ),
    (R.DEPENDS_ON, R.IN_NETWORK),
)


def _ec2(one: uuid.UUID, region: str, state: str) -> Placed:
    return Placed(
        id=one,
        type="infra_resource",
        key=f"aws:arn:aws:ec2:{region}:123:instance/{one.hex[:8]}",
        name=f"i-{one.hex[:8]}",
        layer="infrastructure",
        attributes={"state": state, "resource_class": "compute"},
    )


PLACED = [
    Placed(
        id=PAYMENTS,
        type="service",
        key="service:payments",
        name="Payments",
        layer="services",
        attributes={"environment": "production"},
    ),
    Placed(id=BILLING, type="service", key="service:billing", name="Billing", layer="services"),
    Placed(
        id=ORDERS,
        type="database",
        key="db:postgresql://db:5432/orders",
        name="orders",
        layer="data",
        attributes={"engine": "postgresql", "state": "running"},
    ),
    _ec2(EC2_A, "eu-west-3", "running"),
    _ec2(EC2_B, "eu-west-3", "stopped"),
    _ec2(EC2_C, "us-east-1", "running"),
    Placed(
        id=VM,
        type="infra_resource",
        key="azure:/subscriptions/s/resourceGroups/g/providers/Microsoft.Compute/virtualMachines/vm",
        name="vm",
        layer="infrastructure",
        attributes={"region": "francecentral", "state": "failed"},
    ),
]
STATUSES: dict[uuid.UUID, str | None] = {
    PAYMENTS: "incident",
    BILLING: "operational",
    ORDERS: "operational",
    EC2_A: "operational",
    EC2_B: "attention",
    EC2_C: "operational",
    VM: "incident",
}


def test_the_api_serves_every_view_and_no_other() -> None:
    assert set(get_args(ApiView)) == set(VIEWS)


def test_each_view_holds_kinds_of_the_model_and_draws_its_own_relationships() -> None:
    for view in VIEWS.values():
        assert view.layers, view.name
        assert view.links, view.name
        assert len({layer.name for layer in view.layers}) == len(view.layers), view.name
        for layer in view.layers:
            assert all(isinstance(kind, EntityType) for kind in (*layer.types, *layer.fallback))
            assert all(isinstance(kind, EntityType) for kind in layer.tied)
    # The dependency view draws what the registry calls a dependency.
    assert set(VIEWS["dependencies"].links) == set(DEPENDENCIES)


def test_a_views_kinds_are_its_rows_and_their_fallbacks_each_once() -> None:
    assert VIEWS["company"].types == (
        E.APPLICATION,
        E.REPOSITORY,
        E.SERVICE,
        E.DATABASE,
        E.INFRA_RESOURCE,
    )
    assert VIEWS["data"].types == (E.DATABASE, E.SCHEMA, E.DATA_OBJECT)


def test_cloud_resources_are_boxed_per_provider_and_region_in_their_worst_state() -> None:
    boxes, _ = layout(SERVICES, PLACED, [], STATUSES, {})

    by_id = {box.id: box for box in boxes}
    paris = by_id["provider:aws:eu-west-3"]
    assert (paris.name, paris.detail, paris.count, paris.status) == (
        "aws",
        "eu-west-3",
        2,
        "attention",
    )
    assert paris.entity_id is None
    assert by_id["provider:aws:us-east-1"].count == 1
    azure = by_id["provider:azure:francecentral"]
    assert (azure.count, azure.status) == (1, "incident")
    # Services and databases are their own boxes.
    assert by_id[str(PAYMENTS)].entity_id == PAYMENTS
    assert len(boxes) == 6


def test_where_a_view_does_not_box_them_resources_are_listed_one_by_one() -> None:
    listed = View("flat", (Layer("resources", (E.INFRA_RESOURCE,)),), (R.PART_OF,))
    resources = [
        Placed(**{**vars(thing), "layer": "resources"})
        for thing in PLACED
        if thing.type == "infra_resource"
    ]

    boxes, _ = layout(listed, resources, [], STATUSES, {})

    assert sorted(box.id for box in boxes) == sorted(str(thing.id) for thing in resources)
    assert {box.detail for box in boxes} == {"compute", None}


def test_a_box_says_its_detail_environment_and_team() -> None:
    boxes, _ = layout(SERVICES, PLACED, [], STATUSES, {PAYMENTS: TEAM})

    by_id = {box.id: box for box in boxes}
    payments = by_id[str(PAYMENTS)]
    assert (payments.environment, payments.team_id, payments.status) == (
        "production",
        TEAM,
        "incident",
    )
    assert by_id[str(ORDERS)].detail == "postgresql"
    assert by_id[str(BILLING)].team_id is None


def test_lines_join_boxes_through_the_views_relationships_once_coloured_by_the_worse_end() -> None:
    ties = [
        Tie(PAYMENTS, ORDERS, "depends_on"),
        # The same two the other way: one line.
        Tie(ORDERS, PAYMENTS, "depends_on"),
        Tie(BILLING, ORDERS, "depends_on"),
        # Two resources of one box: no line from a box to itself.
        Tie(EC2_A, EC2_B, "in_network"),
        # Into a provider's box.
        Tie(ORDERS, EC2_B, "in_network"),
        # Not one of the view's relationships.
        Tie(PAYMENTS, BILLING, "owned_by"),
        # An end not drawn.
        Tie(PAYMENTS, uuid.uuid4(), "depends_on"),
    ]

    _, lines = layout(SERVICES, PLACED, ties, STATUSES, {})

    assert {(line.from_id, line.to_id, line.type, line.status) for line in lines} == {
        (str(PAYMENTS), str(ORDERS), "depends_on", "incident"),
        (str(BILLING), str(ORDERS), "depends_on", "operational"),
        (str(ORDERS), "provider:aws:eu-west-3", "in_network", "attention"),
    }


def test_a_things_state_follows_the_environment_screens_rules() -> None:
    def service(**facts: object) -> Placed:
        return Placed(
            id=uuid.uuid4(),
            type="service",
            key="service:x",
            name="x",
            layer="services",
            attributes=facts,
            kinds=frozenset({"pagerduty"}),
        )

    watched = frozenset({"pagerduty", "datadog"})
    assert state(service(open_incidents=2), monitoring=watched, recently_hit=False) == "incident"
    assert state(service(), monitoring=watched, recently_hit=True) == "attention"
    assert state(service(), monitoring=watched, recently_hit=False) == "operational"
    assert state(service(), monitoring=frozenset(), recently_hit=False) == "unmonitored"
    database = next(thing for thing in PLACED if thing.id == ORDERS)
    assert state(database, monitoring=watched, recently_hit=False) == "operational"
    repository = Placed(id=uuid.uuid4(), type="repository", key="r", name="r", layer="applications")
    assert state(repository, monitoring=watched, recently_hit=False) is None


def test_coverage_says_none_where_a_measure_does_not_apply() -> None:
    rows = coverage(
        [
            ("service", 10, 7, 3, 2, 9),
            ("person", 40, 0, 0, 5, 38),
            ("team", 4, 0, 1, 0, 4),
        ]
    )

    service, person, team = rows
    assert (service.owned, service.documented, service.corroborated, service.connected) == (
        7,
        3,
        2,
        9,
    )
    # A person has no owner and is not documented; a team has no owner.
    assert (person.owned, person.documented, person.total) == (None, None, 40)
    assert (team.owned, team.documented) == (None, 1)
