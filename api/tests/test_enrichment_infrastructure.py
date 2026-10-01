"""Enrichment of the infrastructure (LEKA-363): what a cloud resource's place
says where its own sources say nothing.

A workspace as resolution leaves it: an AWS account named for production,
its instances — one tagged, one not — a bucket whose ARN names no account,
an EKS cluster in staging and its node; an Azure subscription, a resource
group of it in staging, a virtual machine in the group; a service owning
nothing but tagged on one instance, an account owned by the platform team.

What these protect: the environment comes from the nearest container that
says one — the cluster, the group, the account — a little less surely, and
never over a resource's own; the account a source reads a bucket in is the
bucket's when the source reads one account of its provider; a team
inherited through a service wins over one inherited through an account.
"""

from __future__ import annotations

import uuid
from typing import Any

from leka.ingestion.enrichment import enrich
from leka.ingestion.enrichment.engine import Enrichment
from tests.test_enrichment import AWS, World

AZURE = uuid.UUID("00000000-0000-0000-0000-0000000000a2")
ACCOUNT = "aws:account:123456789012"
ARN = "aws:arn:aws:ec2:eu-west-3:123456789012"
SUBSCRIPTION = "azure:/subscriptions/s1"
GROUP = "azure:/subscriptions/s1/resourcegroups/rg-billing-stg"
CLUSTER = "aws:arn:aws:eks:eu-west-3:123456789012:cluster/billing"


def _world() -> World:
    world = World()
    on: dict[str, Any] = {"sources": (AWS,)}
    world.thing(
        ACCOUNT,
        "acme-prod",
        type="cloud_account",
        provider="aws",
        account_id="123456789012",
        environment="production",
        environment_confidence=0.7,
        **on,
    )
    world.thing("environment:production", "production", type="environment", **on)
    world.thing("environment:staging", "staging", type="environment", **on)
    world.thing(f"{ARN}:instance/i-1", "api-1", type="infra_resource", provider="aws", **on)
    world.thing(
        f"{ARN}:instance/i-2",
        "api-2",
        type="infra_resource",
        provider="aws",
        environment="staging",
        environment_confidence=0.95,
        **on,
    )
    world.thing(
        "aws:arn:aws:s3:::acme-logs", "acme-logs", type="infra_resource", provider="aws", **on
    )
    world.thing(
        CLUSTER,
        "billing",
        type="infra_resource",
        provider="aws",
        resource_kind="cluster",
        environment="staging",
        environment_confidence=0.95,
        **on,
    )
    world.thing(f"{ARN}:instance/i-node", "node", type="infra_resource", provider="aws", **on)
    for key in (f"{ARN}:instance/i-1", f"{ARN}:instance/i-2", CLUSTER, f"{ARN}:instance/i-node"):
        world.states(AWS, key, "part_of", ACCOUNT, evidence="hierarchy")
    world.states(AWS, f"{ARN}:instance/i-node", "part_of", CLUSTER, evidence="signals.tags")

    azure: dict[str, Any] = {"sources": (AZURE,)}
    world.thing(
        SUBSCRIPTION,
        "Acme",
        type="cloud_account",
        provider="azure",
        account_id="s1",
        **azure,
    )
    world.thing(
        GROUP,
        "rg-billing-stg",
        type="resource_group",
        provider="azure",
        environment="staging",
        environment_confidence=0.7,
        **azure,
    )
    world.thing(f"{GROUP}/providers/vm-1", "vm-1", type="infra_resource", provider="azure", **azure)
    world.states(AZURE, GROUP, "part_of", SUBSCRIPTION, evidence="hierarchy")
    world.states(AZURE, f"{GROUP}/providers/vm-1", "part_of", GROUP, evidence="hierarchy")
    return world


def _environment(enrichment: Enrichment, world: World, key: str) -> tuple[object, float, str]:
    [fact] = [
        f for f in enrichment.facts if f.entity_id == world.id(key) and f.attribute == "environment"
    ]
    return fact.value, fact.confidence, fact.rule


def _edges(enrichment: Enrichment, world: World, key: str, kind: str) -> dict[str, str]:
    keys = {node.id: node.key for node in world.nodes.values()}
    return {
        keys[e.to_id]: e.rule
        for e in enrichment.edges
        if e.from_id == world.id(key) and e.type == kind
    }


def test_a_resource_runs_where_its_account_runs_a_little_less_surely() -> None:
    world = _world()

    enrichment = enrich(world.snapshot())

    assert _environment(enrichment, world, f"{ARN}:instance/i-1") == (
        "production",
        0.63,
        "container",
    )
    assert _edges(enrichment, world, f"{ARN}:instance/i-1", "runs_in") == {
        "environment:production": "container"
    }


def test_a_resource_s_own_environment_stands() -> None:
    world = _world()

    enrichment = enrich(world.snapshot())

    assert not [
        f
        for f in enrichment.facts
        if f.entity_id == world.id(f"{ARN}:instance/i-2") and f.attribute == "environment"
    ]


def test_the_nearest_container_decides_a_node_its_cluster() -> None:
    world = _world()

    enrichment = enrich(world.snapshot())

    # Its cluster runs in staging, its account in production: the cluster
    # is nearer.
    assert _environment(enrichment, world, f"{ARN}:instance/i-node")[:1] == ("staging",)


def test_a_group_s_environment_is_its_resources() -> None:
    world = _world()

    enrichment = enrich(world.snapshot())

    assert _environment(enrichment, world, f"{GROUP}/providers/vm-1") == (
        "staging",
        0.63,
        "container",
    )


def test_a_bucket_is_in_the_one_account_its_source_reads() -> None:
    world = _world()

    enrichment = enrich(world.snapshot())

    bucket = "aws:arn:aws:s3:::acme-logs"
    assert _edges(enrichment, world, bucket, "part_of") == {ACCOUNT: "source_account"}
    [account] = [
        f for f in enrichment.facts if f.entity_id == world.id(bucket) and f.attribute == "account"
    ]
    assert (account.value, account.confidence) == ("123456789012", 0.9)
    # And so where the account runs: production.
    assert _environment(enrichment, world, bucket)[0] == "production"


def test_a_source_that_reads_two_accounts_places_no_bucket() -> None:
    world = _world()
    world.thing(
        "aws:account:210987654321", "acme-dev", type="cloud_account", provider="aws", sources=(AWS,)
    )

    enrichment = enrich(world.snapshot())

    assert _edges(enrichment, world, "aws:arn:aws:s3:::acme-logs", "part_of") == {}


def test_a_service_s_team_wins_over_the_account_s() -> None:
    world = _world()
    world.thing("team:platform", "Platform", type="team", sources=(AWS,))
    world.thing("team:payments", "Payments", type="team", sources=(AWS,))
    world.thing("service:billing-api", "Billing API", type="service", sources=(AWS,))
    world.states(AWS, ACCOUNT, "owned_by", "team:platform", confidence=0.9)
    world.states(AWS, "service:billing-api", "owned_by", "team:payments")
    world.states(AWS, f"{ARN}:instance/i-1", "part_of", "service:billing-api", confidence=0.9)

    enrichment = enrich(world.snapshot())

    assert _edges(enrichment, world, f"{ARN}:instance/i-1", "owned_by") == {
        "team:payments": "inherited"
    }
    # Where no service says, the account's team is the resource's.
    assert _edges(enrichment, world, f"{ARN}:instance/i-2", "owned_by") == {
        "team:platform": "inherited"
    }
