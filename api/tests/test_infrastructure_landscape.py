"""An infrastructure landscape, modelled from five sources (LEKA-363).

Acme's infrastructure, as its tools see it — vendor payloads through the
whole pipeline: extraction, parsing, normalisation, stored as normalisation
leaves them, then entity resolution, enrichment and the company model's
build, then the API.

    AWS (prod)  the account `acme-prod` in its organisation; a VPC; an EKS
                cluster `billing` and its node; billing-api's instance,
                tagged critical, its service's and Payments'; Ledger's
                database, tagged high; an S3 bucket — its ARN names no
                account; a public load balancer; a function; an instance
                terminated an hour ago
    AWS (audit) a second source on the same account: billing-api's
                instance again, tagged high since
    Azure       the subscription `Acme Staging`, tagged staging; its
                resource group `rg-billing`, Payments'; a VM in the group
    Google      the project `acme-dev`, labelled dev; a Cloud SQL instance
    a CMDB      a custom source: Ledger's database by its ARN — Data
                platform's, tier 1; `batch-01`, a server of its own, which
                depends on Ledger's database

What these protect: one entity per real resource whatever reads it, every
source kept and what they disagree on; the hierarchy — account, group,
region — kept; the environment where no tag says it, from what the resource
is in, and said so; a node in its cluster, a resource in its network;
dependencies between a CMDB's server and a cloud's database; a terminated
instance archived; members read the infrastructure and the accounts —
never another workspace's.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.connectors import Capability, SourceKind
from leka.db import session_factory, workspace_scope
from leka.ingestion.enrichment.job import enrich_workspace
from leka.ingestion.normalisation import NormalisedRecord
from leka.ingestion.resolution.job import resolve_workspace
from leka.knowledge import Entity
from leka.knowledge.job import build_workspace
from tests.conftest import FakeIdentity
from tests.test_application_landscape import _edge, _entity, _record, _store
from tests.test_enrichment_job import NOW
from tests.test_resolution_job import _source
from tests.test_sources_api import FAKE_KEY, _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/knowledge"
C = Capability
ACCOUNT_ID = "123456789012"
REGION = "eu-west-3"
ARN = f"arn:aws:ec2:{REGION}:{ACCOUNT_ID}"
CLUSTER_ARN = f"arn:aws:eks:{REGION}:{ACCOUNT_ID}:cluster/billing"
LEDGER_ARN = f"arn:aws:rds:{REGION}:{ACCOUNT_ID}:db:ledger-prod"
SUB = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
GROUP_ID = f"/subscriptions/{SUB}/resourceGroups/rg-billing"
VM_ID = f"{GROUP_ID}/providers/Microsoft.Compute/virtualMachines/vm-1"
SQL = "//cloudsql.googleapis.com/projects/acme-dev/instances/ledger-replica"

ACCOUNT = f"aws:account:{ACCOUNT_ID}"
SUBSCRIPTION = f"azure:/subscriptions/{SUB}"
GROUP = f"azure:{GROUP_ID.lower()}"
PROJECT = "gcp:project:acme-dev"
VPC = f"aws:{ARN}:vpc/vpc-1"
CLUSTER = f"aws:{CLUSTER_ARN}"
NODE = f"aws:{ARN}:instance/i-node"
API_1 = f"aws:{ARN}:instance/i-api"
OLD = f"aws:{ARN}:instance/i-old"
LEDGER = f"aws:{LEDGER_ARN}"
BUCKET = "aws:arn:aws:s3:::acme-logs"
BALANCER = f"aws:arn:aws:elasticloadbalancing:{REGION}:{ACCOUNT_ID}:loadbalancer/app/web/1"
FUNCTION = f"aws:arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:resize"
VM = f"azure:{VM_ID.lower()}"
CLOUD_SQL = f"gcp:{SQL}"


def _tags(**tags: str) -> list[dict[str, str]]:
    return [{"Key": k.replace("_", ":"), "Value": v} for k, v in tags.items()]


def _aws(capability: Capability, payload: dict[str, Any], arn: str) -> NormalisedRecord:
    return _record(SourceKind.AWS, capability, payload, container=REGION, external_id=arn)


def _instance(instance: str, tags: dict[str, str], **payload: Any) -> NormalisedRecord:
    return _aws(
        C.INSTANCES,
        {
            "InstanceId": instance,
            "VpcId": "vpc-1",
            "State": {"Name": "running"},
            "Tags": [{"Key": k, "Value": v} for k, v in tags.items()],
            **payload,
        },
        f"{ARN}:instance/{instance}",
    )


def _cmdb(record_id: str, title: str, entity: str, metadata: dict[str, Any]) -> NormalisedRecord:
    return _record(
        SourceKind.CUSTOM_REST,
        C.RECORDS,
        {
            "resource": "servers",
            "entity": entity,
            "fields": {"id": record_id, "title": title, "metadata": metadata},
        },
        external_id=f"servers:{record_id}",
    )


async def _landscape(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    """The five sources, normalised, stored, resolved, enriched, built: the
    model's ids, by key."""
    prod, audit, azure, google, cmdb = [
        await _source(workspace, name)
        for name in ("AWS prod", "AWS audit", "Azure", "Google", "CMDB")
    ]
    records = [
        (
            prod,
            _record(
                SourceKind.AWS,
                C.ACCOUNTS,
                {
                    "Account": ACCOUNT_ID,
                    "AccountAliases": ["acme-prod"],
                    "Organization": {"Id": "o-abc123", "MasterAccountId": "999999999999"},
                },
                external_id=ACCOUNT_ID,
                container=None,
            ),
        ),
        (prod, _aws(C.NETWORKS, {"VpcId": "vpc-1", "State": "available"}, f"{ARN}:vpc/vpc-1")),
        (
            prod,
            _aws(
                C.CLUSTERS,
                {
                    "name": "billing",
                    "arn": CLUSTER_ARN,
                    "status": "ACTIVE",
                    "resourcesVpcConfig": {"vpcId": "vpc-1"},
                },
                CLUSTER_ARN,
            ),
        ),
        (prod, _instance("i-node", {"eks:cluster-name": "billing"})),
        (
            prod,
            _instance(
                "i-api",
                {
                    "service": "billing-api",
                    "team": "Payments",
                    "env": "prod",
                    "criticality": "critical",
                },
            ),
        ),
        (prod, _instance("i-old", {}, State={"Name": "terminated"})),
        (
            prod,
            _aws(
                C.DB_INSTANCES,
                {
                    "DBInstanceIdentifier": "ledger-prod",
                    "DBInstanceStatus": "available",
                    "Engine": "postgres",
                    "DBSubnetGroup": {"VpcId": "vpc-1"},
                    "Endpoint": {"Address": "ledger-prod.abc.eu-west-3.rds.amazonaws.com"},
                    "TagList": _tags(service="ledger", criticality="high"),
                },
                LEDGER_ARN,
            ),
        ),
        (
            prod,
            _record(
                SourceKind.AWS,
                C.BUCKETS,
                {"Name": "acme-logs"},
                external_id="arn:aws:s3:::acme-logs",
                container=None,
            ),
        ),
        (
            prod,
            _aws(
                C.LOAD_BALANCERS,
                {
                    "LoadBalancerName": "web",
                    "Scheme": "internet-facing",
                    "Type": "application",
                    "VpcId": "vpc-1",
                    "State": {"Code": "active"},
                },
                BALANCER.removeprefix("aws:"),
            ),
        ),
        (
            prod,
            _aws(
                C.FUNCTIONS,
                {
                    "FunctionName": "resize",
                    "Runtime": "python3.12",
                    "VpcConfig": {"VpcId": "vpc-1"},
                },
                FUNCTION.removeprefix("aws:"),
            ),
        ),
        # Read again by a second source, its criticality since changed.
        (
            audit,
            _instance(
                "i-api",
                {"service": "billing-api", "env": "prod", "criticality": "high"},
            ),
        ),
        (
            azure,
            _record(
                SourceKind.AZURE,
                C.ACCOUNTS,
                {
                    "id": f"/subscriptions/{SUB}",
                    "subscriptionId": SUB,
                    "displayName": "Acme Staging",
                    "state": "Enabled",
                    "tags": {"env": "staging"},
                },
                external_id=f"/subscriptions/{SUB}",
                container=None,
            ),
        ),
        (
            azure,
            _record(
                SourceKind.AZURE,
                C.ACCOUNTS,
                {
                    "id": GROUP_ID,
                    "name": "rg-billing",
                    "type": "Microsoft.Resources/resourceGroups",
                    "location": "westeurope",
                    "tags": {"owner": "Payments"},
                },
                external_id=GROUP_ID.lower(),
                container=SUB,
            ),
        ),
        (
            azure,
            _record(
                SourceKind.AZURE,
                C.INSTANCES,
                {
                    "id": VM_ID,
                    "name": "vm-1",
                    "type": "Microsoft.Compute/virtualMachines",
                    "location": "westeurope",
                },
                external_id=VM_ID.lower(),
                container=SUB,
            ),
        ),
        (
            google,
            _record(
                SourceKind.GCP,
                C.ACCOUNTS,
                {
                    "name": "projects/415104041262",
                    "projectId": "acme-dev",
                    "displayName": "Acme dev",
                    "state": "ACTIVE",
                    "labels": {"env": "dev"},
                },
                external_id="acme-dev",
                container=None,
            ),
        ),
        (
            google,
            _record(
                SourceKind.GCP,
                C.DB_INSTANCES,
                {
                    "name": SQL,
                    "assetType": "sqladmin.googleapis.com/Instance",
                    "resource": {
                        "location": "europe-west1",
                        "data": {"name": "ledger-replica", "databaseVersion": "POSTGRES_15"},
                    },
                },
                external_id=SQL,
                container="acme-dev",
            ),
        ),
        (
            cmdb,
            _cmdb(
                "db-7",
                "Ledger production DB",
                "database",
                {"arn": LEDGER_ARN, "owner": "Data platform", "criticality": "Tier 1"},
            ),
        ),
        (
            cmdb,
            _cmdb(
                "srv-1",
                "batch-01",
                "infra_resource",
                {"type": "server", "dependencies": LEDGER_ARN, "environment": "production"},
            ),
        ),
    ]
    for source, record in records:
        await _store(workspace, source, record)
    await resolve_workspace(workspace)
    await enrich_workspace(workspace, now=NOW)
    await build_workspace(workspace)
    with workspace_scope(workspace):
        async with session_factory() as session:
            rows = await session.execute(select(Entity.key, Entity.id))
            return dict(rows.tuples().all())


def _source_ids(entity: Entity) -> set[str]:
    return {str(s["source_id"]) for s in entity.provenance["sources"]}  # type: ignore[attr-defined]


def _origin(entity: Entity, attribute: str) -> dict[str, Any]:
    found: dict[str, Any] = entity.provenance["attributes"][attribute]  # type: ignore[index]
    return found


# ── the model ────────────────────────────────────────────────────────────────


async def test_every_resource_is_one_entity_of_its_kind_and_class(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)

    kinds = {
        key: ((e := await _entity(workspace, ids[key])).type.value, e.attributes["resource_class"])
        for key in (NODE, CLUSTER, VPC, BALANCER, BUCKET, FUNCTION, LEDGER, VM, CLOUD_SQL)
    }
    assert kinds == {
        NODE: ("infra_resource", "compute"),
        CLUSTER: ("infra_resource", "compute"),
        VPC: ("infra_resource", "network"),
        BALANCER: ("infra_resource", "network"),
        BUCKET: ("infra_resource", "storage"),
        FUNCTION: ("infra_resource", "compute"),
        LEDGER: ("database", "database"),
        VM: ("infra_resource", "compute"),
        CLOUD_SQL: ("database", "database"),
    }
    for key, kind in (
        (ACCOUNT, "cloud_account"),
        (SUBSCRIPTION, "cloud_account"),
        (PROJECT, "cloud_account"),
        (GROUP, "resource_group"),
    ):
        assert (await _entity(workspace, ids[key])).type.value == kind
    account = await _entity(workspace, ids[ACCOUNT])
    assert account.name == "acme-prod"
    assert account.attributes["organization"] == "o-abc123"
    assert (await _entity(workspace, ids[SUBSCRIPTION])).name == "Acme Staging"


async def test_the_hierarchy_is_kept_and_a_bucket_finds_its_account(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)

    for a, kind, b in (
        (API_1, "part_of", ACCOUNT),
        (CLUSTER, "part_of", ACCOUNT),
        (VM, "part_of", GROUP),
        (GROUP, "part_of", SUBSCRIPTION),
        (CLOUD_SQL, "part_of", PROJECT),
        (NODE, "part_of", CLUSTER),
        (NODE, "in_network", VPC),
        (LEDGER, "in_network", VPC),
        (API_1, "part_of", "service:billing-api"),
        (API_1, "owned_by", "team:payments"),
        (LEDGER, "owned_by", "team:data-platform"),
    ):
        await _edge(workspace, ids[a], kind, ids[b])
    bucket = await _edge(workspace, ids[BUCKET], "part_of", ids[ACCOUNT])
    assert (bucket.origin, bucket.rule) == ("inferred", "source_account")
    assert (await _entity(workspace, ids[BUCKET])).attributes["account"] == ACCOUNT_ID
    # The VM's team: its group's, inherited.
    vm_team = await _edge(workspace, ids[VM], "owned_by", ids["team:payments"])
    assert vm_team.rule == "inherited"


async def test_where_no_tag_says_the_environment_what_it_is_in_does(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)

    async def environment(key: str) -> tuple[object, object]:
        entity = await _entity(workspace, ids[key])
        return entity.attributes["environment"], _origin(entity, "environment")["origin"]

    assert await environment(API_1) == ("production", "source")  # its tag
    assert await environment(ACCOUNT) == ("production", "source")  # its alias
    assert await environment(CLUSTER) == ("production", "enrichment")  # its account
    assert await environment(NODE) == ("production", "enrichment")  # its cluster
    assert await environment(VM) == ("staging", "enrichment")  # its group's subscription
    assert await environment(CLOUD_SQL) == ("development", "enrichment")  # its project
    assert _origin(await _entity(workspace, ids[VM]), "environment")["rule"] == "container"
    await _edge(workspace, ids[VM], "runs_in", ids["environment:staging"])


async def test_what_two_sources_say_of_one_resource_is_kept_with_who_said_it(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)

    # Two AWS sources read the instance: one entity, both kept, and the
    # criticality they disagree on, every value with its source.
    instance = await _entity(workspace, ids[API_1])
    assert len(_source_ids(instance)) == 2
    [conflict] = [
        c
        for c in instance.provenance["conflicts"]  # type: ignore[attr-defined]
        if c["attribute"] == "criticality"
    ]
    assert {v["value"] for v in conflict["values"]} == {"critical", "high"}
    # The CMDB names Ledger's database by its ARN: one entity with AWS's.
    ledger = await _entity(workspace, ids[LEDGER])
    assert len(_source_ids(ledger)) == 2
    assert ledger.name in ("ledger-prod", "Ledger production DB")
    assert ledger.attributes["endpoint"] == "ledger-prod.abc.eu-west-3.rds.amazonaws.com"
    criticality = next(
        c
        for c in ledger.provenance["conflicts"]  # type: ignore[attr-defined]
        if c["attribute"] == "criticality"
    )
    assert {v["value"] for v in criticality["values"]} == {"critical", "high"}


async def test_a_cmdb_server_depends_on_a_cloud_database(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)
    batch = next(key for key in ids if key.endswith(":infra_resource:servers:srv-1"))

    dependency = await _edge(workspace, ids[batch], "depends_on", ids[LEDGER])

    assert (dependency.origin, dependency.rule) == ("stated", "stated")
    assert dependency.attributes == {"environments": ["production"]}
    # What the failure of the database reaches: the server.
    upstream = await _entity(workspace, ids[batch])
    assert upstream.attributes["resource_kind"] == "instance"


async def test_a_terminated_instance_is_archived(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)

    old = await _entity(workspace, ids[OLD])

    assert (old.attributes["state"], old.lifecycle.value) == ("terminated", "archived")


# ── the API ──────────────────────────────────────────────────────────────────


async def test_members_read_the_infrastructure_and_filter_it(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "member")

    async def keys(**params: str | int) -> set[str]:
        response = await client.get(f"{API}/infrastructure", params={"limit": 100, **params})
        assert response.status_code == 200, response.text
        return {row["key"] for row in response.json()["data"]}

    rows = {
        row["key"]: row
        for row in (await client.get(f"{API}/infrastructure", params={"limit": 100})).json()["data"]
    }
    instance = rows[API_1]
    assert instance["account"]["key"] == ACCOUNT
    assert instance["network"]["key"] == VPC
    assert [s["key"] for s in instance["services"]] == ["service:billing-api"]
    assert [o["key"] for o in instance["owners"]] == ["team:payments"]
    # A tag said it: a source, whose own confidence resolution does not keep.
    assert instance["environment"] == {"name": "production", "origin": "source", "confidence": None}
    assert (instance["region"], instance["provider"]) == (REGION, "aws")
    assert rows[NODE]["cluster"]["key"] == CLUSTER
    vm = rows[VM]
    assert (vm["resource_group"]["key"], vm["account"]["key"]) == (GROUP, SUBSCRIPTION)
    assert vm["environment"]["origin"] == "enrichment"
    assert rows[BALANCER]["exposure"] == "public"
    assert OLD in rows  # archived, not removed: still listed

    assert await keys(resource_class="storage") == {BUCKET}
    assert await keys(provider="gcp") == {CLOUD_SQL}
    assert await keys(account_id=str(ids[SUBSCRIPTION])) == {VM}
    assert BUCKET in await keys(account_id=str(ids[ACCOUNT]))
    assert await keys(environment="staging") == {VM}
    assert await keys(exposure="public") == {BALANCER}
    assert await keys(state="terminated") == {OLD}
    assert await keys(service_id=str(ids["service:billing-api"])) == {API_1}
    assert LEDGER in await keys(team_id=str(ids["team:data-platform"]))
    assert await keys(q="ledger") == {LEDGER, CLOUD_SQL}


async def test_a_resource_s_detail_says_what_it_holds_and_what_depends_on_it(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "member")

    cluster = (await client.get(f"{API}/infrastructure/{ids[CLUSTER]}")).json()
    network = (await client.get(f"{API}/infrastructure/{ids[VPC]}")).json()
    ledger = (await client.get(f"{API}/infrastructure/{ids[LEDGER]}")).json()

    assert [h["key"] for h in cluster["holds"]] == [NODE]
    assert {h["key"] for h in network["holds"]} >= {NODE, API_1, LEDGER, BALANCER, FUNCTION}
    assert network["holds_total"] == len(network["holds"])
    assert [d["entity"]["name"] for d in ledger["depended_on_by"]] == ["batch-01"]
    assert ledger["provenance"]["conflicts"]
    wrong = await client.get(f"{API}/infrastructure/{ids['service:billing-api']}")
    assert wrong.status_code == 404  # a service is not a resource


async def test_the_accounts_say_how_much_is_in_each(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "member")

    listed = {row["key"]: row for row in (await client.get(f"{API}/cloud-accounts")).json()["data"]}
    detail = (await client.get(f"{API}/cloud-accounts/{ids[SUBSCRIPTION]}")).json()

    assert set(listed) == {ACCOUNT, SUBSCRIPTION, PROJECT}
    aws = listed[ACCOUNT]
    assert (aws["account_type"], aws["account_id"], aws["organization"]) == (
        "aws_account",
        ACCOUNT_ID,
        "o-abc123",
    )
    # Its nine resources — a node counted once, though in its cluster too;
    # the terminated one, archived but there; the bucket its source reads
    # in it.
    assert aws["classes"] == {"compute": 5, "database": 1, "network": 2, "storage": 1}
    assert aws["regions"] == [REGION]
    assert aws["environment"]["name"] == "production"
    assert listed[SUBSCRIPTION]["resources"] == 1  # the VM, through its group
    assert [g["key"] for g in detail["resource_groups"]] == [GROUP]
    assert detail["resource_groups"][0]["resources"] == 1
    assert detail["resource_groups"][0]["parent"]["key"] == SUBSCRIPTION
    assert [o["key"] for o in detail["resource_groups"][0]["owners"]] == ["team:payments"]
    filtered = (await client.get(f"{API}/cloud-accounts", params={"provider": "gcp"})).json()
    assert [row["key"] for row in filtered["data"]] == [PROJECT]
    wrong = await client.get(f"{API}/cloud-accounts/{ids[VM]}")
    assert wrong.status_code == 404


async def test_another_workspace_s_infrastructure_is_not_found(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "other_admin")  # Globex's

    for path in (f"/infrastructure/{ids[API_1]}", f"/cloud-accounts/{ids[ACCOUNT]}"):
        assert (await client.get(f"{API}{path}")).status_code == 404, path
    assert (await client.get(f"{API}/infrastructure")).json()["data"] == []
    assert (await client.get(f"{API}/cloud-accounts")).json()["data"] == []
