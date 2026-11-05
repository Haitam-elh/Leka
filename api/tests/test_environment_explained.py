"""« Mon environnement », explained (LEKA-532) — pure.

What these protect:
- every thing with a state is a row of its own, a cloud resource never
  folded into its provider's box: what the counts count, the worst first,
  each with its provider, region, environment and the sources showing it;
- what AWS refused at a source's last test is said, with the permissions
  that would let LEKA read it — only once a test said what it could, and
  only for what AWS's policy decides;
- a cloud resource's network is drawn as its provider says it, and what
  runs in or is deployed to a resource as « deployed on »;
- a relationship says which sources state it, by name.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from leka.connectors import Capability
from leka.connectors.aws.connector import CLOUD_CAPABILITIES, PERMISSIONS
from leka.ingestion.enrichment import screens
from leka.ingestion.enrichment.twin import SourceSeen, state_of
from leka.ingestion.enrichment.view import Thing
from leka.knowledge import architecture as arch

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
AWS = SourceSeen(
    id=uuid.uuid4(),
    kind="aws",
    name="production account",
    category="cloud",
    status="active",
    sync_status="idle",
    health="healthy",
    last_synced_at=NOW - timedelta(minutes=10),
)


def resource(name: str, arn: str, **attributes: object) -> Thing:
    return Thing(id=uuid.uuid4(), type="infra_resource", key=arn, name=name, attributes=attributes)


def test_every_thing_with_a_state_is_a_row_of_its_own_the_worst_first() -> None:
    bucket = resource(
        "invoices",
        "aws:arn:aws:s3:::invoices",
        resource_type="s3:bucket",
        environment="production",
    )
    cluster = resource(
        "ecs-prod-cluster",
        "aws:arn:aws:eks:eu-west-1:123456789012:cluster/prod",
        resource_type="eks:cluster",
        state="running",
    )
    things = {t.id: t for t in (bucket, cluster)}
    twins = {
        t.id: state_of(t, sources=[AWS], incidents=[], monitoring_connected=True, now=NOW)
        for t in things.values()
    }
    rows = screens._tracked(things, twins, {bucket.id: {AWS.id}, cluster.id: {AWS.id}})
    assert [(r.entity.name, r.twin.state) for r in rows] == [
        ("invoices", "unknown"),
        ("ecs-prod-cluster", "operational"),
    ]
    first, second = rows
    assert (first.resource_type, first.provider, first.environment) == (
        "s3:bucket",
        "aws",
        "production",
    )
    assert first.twin.reason == "provider_no_state" and first.sources == [AWS.id]
    # Its region, read from its ARN.
    assert (second.provider, second.region) == ("aws", "eu-west-1")
    assert second.twin.said == "running"


def test_what_aws_refused_is_said_with_the_permissions_to_grant() -> None:
    granted = ["instances", "buckets", "networks", "accounts"]
    missing = screens._unread("aws", CLOUD_CAPABILITIES, granted)
    assert missing == sorted(
        [
            Capability.DB_INSTANCES,
            Capability.FUNCTIONS,
            Capability.CLUSTERS,
            Capability.LOAD_BALANCERS,
        ],
        key=str,
    )
    assert PERMISSIONS[Capability.FUNCTIONS] == ("lambda:ListFunctions",)
    # Never tested: nothing claimed missing. Another connector: not AWS's policy.
    assert screens._unread("aws", CLOUD_CAPABILITIES, []) == []
    assert screens._unread("github", CLOUD_CAPABILITIES, ["instances"]) == []
    # Every capability AWS reads has its permissions said.
    assert set(PERMISSIONS) == CLOUD_CAPABILITIES - {Capability.ACCOUNTS}


def test_a_resources_network_and_what_runs_on_it_are_drawn() -> None:
    instance = arch.Thing(
        uuid.uuid4(), "infra_resource", "aws:arn:aws:ec2:eu-west-1:1:i-1", "web-1"
    )
    vpc = arch.Thing(uuid.uuid4(), "infra_resource", "aws:arn:aws:ec2:eu-west-1:1:vpc-1", "main")
    service = arch.Thing(uuid.uuid4(), "service", "service:payment-api", "payment-api")
    things = {t.id: t for t in (instance, vpc, service)}
    network = arch.Edge(instance.id, vpc.id, "in_network", "stated", "references", 1.0)
    runs = arch.Edge(service.id, instance.id, "runs_in", "stated", "environment", 1.0)
    assert arch.role(network, things) == (instance.id, vpc.id, "in_network")
    assert arch.role(runs, things) == (service.id, instance.id, "deployed_on")
    assert "in_network" in arch.ROLE_ORDER


def test_a_relationship_says_which_sources_state_it() -> None:
    names = {AWS.id: AWS.name}
    provenance = [
        {"source_id": str(AWS.id), "record_id": "r1"},
        {"source_id": str(AWS.id), "record_id": "r2"},
        {"source_id": "not-an-id"},
        {"entity_id": str(uuid.uuid4())},
    ]
    assert screens._stated_by(provenance, names) == ["production account"]
    assert screens._stated_by([], names) == []
