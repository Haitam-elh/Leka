"""The architecture view, as leka/knowledge/architecture.py lays it out
(LEKA-369).

Things and relationships as the model holds them, in; cards, links and
figures out.

What these protect: each thing in its column — a cloud's database in the
cloud, the code's in the data, a service outside on the right; each link
named by what it is — a resource a service's tags name runs it, a
catalogue's dependency is a dependency, a monitoring tool that shows a
service watches it; a provider's resources, a few, those tied to the rest
first, its count whole; the states counted.
"""

from __future__ import annotations

import uuid

from leka.knowledge import architecture as arch

IDS = uuid.UUID("00000000-0000-0000-0000-000000000369")


def thing(key: str, type_: str, name: str = "", **attributes: object) -> arch.Thing:
    status = attributes.pop("status", None)
    kinds = attributes.pop("kinds", frozenset())
    return arch.Thing(
        id=uuid.uuid5(IDS, key),
        type=type_,
        key=key,
        name=name or key,
        attributes=attributes,
        status=status if isinstance(status, str) else None,
        kinds=kinds if isinstance(kinds, frozenset) else frozenset(),
    )


def edge(
    a: arch.Thing, kind: str, b: arch.Thing, *, origin: str = "stated", rule: str = "stated"
) -> arch.Edge:
    return arch.Edge(from_id=a.id, to_id=b.id, type=kind, origin=origin, rule=rule, confidence=1.0)


def laid(things: list[arch.Thing], edges: list[arch.Edge], **extra: object) -> arch.Architecture:
    return arch.build(
        things,
        edges,
        stats={},
        teams={},
        totals={},
        providers=extra.get("providers", {}),  # type: ignore[arg-type]
        monitoring=frozenset({"datadog", "pagerduty"}),
    )


def test_each_thing_in_its_column() -> None:
    assert arch.column("database", "aws:arn:aws:rds:x", {"provider": "aws"}) == "cloud"
    code = {"provider": "aws", "store_role": "database"}
    assert arch.column("database", "db:postgresql://github.com/a/b/pg", code) == "data"
    assert arch.column("infra_resource", "code:github.com/a/b:storage:s3", {}) == "data"
    assert arch.column("service", "service:stripe", {"hosting": "external"}) == "external"
    assert arch.column("person", "person:x", {}) is None
    assert arch.group("code", "gitlab.com/acme/shop", {}) == "gitlab"


def test_a_resource_a_service_s_tags_name_runs_it_and_a_tool_watches_it() -> None:
    billing = thing("service:billing", "service", "Billing", kinds=frozenset({"datadog"}))
    box = thing("aws:arn:aws:ec2:eu-west-3:1:instance/i-1", "infra_resource", provider="aws")
    ledger = thing("service:ledger", "service", "Ledger")

    found = laid(
        [billing, box, ledger],
        [edge(box, "part_of", billing), edge(billing, "depends_on", ledger)],
    )

    links = {(li.from_id, li.role, li.to_id) for li in found.links}
    assert (str(billing.id), "deployed_on", str(box.id)) in links
    # A catalogue's dependency, no file to say what for: a dependency.
    assert (str(billing.id), "depends", str(ledger.id)) in links
    assert (str(billing.id), "monitored_by", "tool:datadog") in links
    tool = next(card for card in found.cards if card.id == "tool:datadog")
    assert (tool.column, tool.kind) == ("external", "monitoring")


def test_a_provider_s_resources_a_few_those_tied_to_the_rest_first() -> None:
    api = thing("service:api", "service", "API", status="operational")
    boxes = [
        thing(f"aws:arn:aws:ec2:eu-west-3:1:instance/i-{n}", "infra_resource", f"i-{n:02}")
        for n in range(12)
    ]
    tied = boxes[11]

    found = laid(
        [api, *boxes],
        [edge(api, "depends_on", tied, origin="inferred", rule="public_address")],
        providers={"aws": 30},
    )

    cloud = [card for card in found.cards if card.column == "cloud"]
    assert len(cloud) == arch.MAX_PER_PROVIDER
    assert cloud[0].id == str(tied.id)
    group = next(g for g in found.groups if g.id == "cloud:aws")
    assert (group.total, group.shown) == (30, arch.MAX_PER_PROVIDER)


def test_the_states_counted() -> None:
    things = [
        thing("service:a", "service", status="operational"),
        thing("service:b", "service", status="incident"),
        thing("service:c", "service", status="unmonitored"),
        thing("db:redis://x/y/redis", "database", status="attention", store_role="cache"),
        thing("github.com/a/b", "repository"),
    ]

    found = laid(things, [])

    assert found.services == {"incident": 1, "attention": 0, "operational": 1, "unmonitored": 1}
    assert found.health == {"operational": 1, "attention": 1, "incident": 1, "unmonitored": 1}
