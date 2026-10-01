"""The infrastructure, as normalisation writes it (LEKA-363).

From vendor payloads through extraction, parsing and normalisation: what a
cloud resource is in — an AWS account, an Azure resource group and its
subscription, a Google Cloud project — its class, its place, the cluster a
machine is a node of; the accounts themselves, read by the `accounts`
capability; a CMDB's servers and databases, keyed by the provider's id
where it gives one.

What these protect: one key per account whatever names it — a resource's
ARN, the account's own record — so they meet; the hierarchy kept as
relationships; a node's cluster found by the key the cluster's own record
has; an environment read from a scope's name surer than from a resource's;
a CMDB's resource one with the cloud's when it names it by its provider id.
"""

from __future__ import annotations

from typing import Any

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction import ExtractedRecord
from leka.ingestion.normalisation import NormalisedRecord, normalise
from leka.ingestion.parsing import FactType, ParsedRecord, parse
from tests.test_extraction import _extract

C = Capability
ACCOUNT = "123456789012"
ARN = f"arn:aws:ec2:eu-west-3:{ACCOUNT}"
SUBSCRIPTION = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
GROUP = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-Billing-Prod"
AWS_ACCOUNT = f"aws:account:{ACCOUNT}"
AZURE_SUBSCRIPTION = f"azure:/subscriptions/{SUBSCRIPTION}"
AZURE_GROUP = f"azure:{GROUP.lower()}"


def _pipeline(
    kind: SourceKind, capability: Capability, payload: dict[str, Any], **extra: Any
) -> tuple[ExtractedRecord, ParsedRecord]:
    extracted = _extract(kind, capability, payload, **extra)
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord), parsed
    return extracted, parsed


def _normalised(
    kind: SourceKind, capability: Capability, payload: dict[str, Any], **extra: Any
) -> NormalisedRecord:
    result = normalise(*_pipeline(kind, capability, payload, **extra))
    assert isinstance(result, NormalisedRecord), result
    return result


def _edges(record: NormalisedRecord) -> set[tuple[str, str, str]]:
    return {(r.from_key, r.type, r.to_key) for r in record.relationships}


def _related(record: NormalisedRecord) -> dict[str, tuple[str, str]]:
    return {e.key: (e.type, e.name) for e in record.related}


def _tags(**tags: str) -> list[dict[str, str]]:
    return [{"Key": k.replace("__", ":").replace("_", "-"), "Value": v} for k, v in tags.items()]


# ── what resources are in ────────────────────────────────────────────────────


def test_an_aws_account_is_named_by_its_alias_and_says_its_environment() -> None:
    account = _normalised(
        SourceKind.AWS,
        C.ACCOUNTS,
        {
            "Account": ACCOUNT,
            "AccountAliases": ["acme-prod"],
            "Organization": {"Id": "o-abc123", "MasterAccountId": "999999999999"},
        },
        external_id=ACCOUNT,
        container=None,
    )

    entity = account.entity
    assert (entity.type, entity.key, entity.name) == ("cloud_account", AWS_ACCOUNT, "acme-prod")
    a = entity.attributes
    assert (a["account_type"], a["account_id"], a["organization"]) == (
        "aws_account",
        ACCOUNT,
        "o-abc123",
    )
    # An account is named for its environment more often than not: surer
    # than a resource's name, less than a tag.
    assert (a["environment"], a["environment_confidence"]) == ("production", 0.7)
    assert (AWS_ACCOUNT, "runs_in", "environment:production") in _edges(account)


def test_an_aws_account_without_alias_is_its_id() -> None:
    account = _normalised(SourceKind.AWS, C.ACCOUNTS, {"Account": ACCOUNT}, external_id=ACCOUNT)

    assert (account.entity.name, account.entity.attributes.get("environment")) == (ACCOUNT, None)


def test_an_azure_subscription_and_its_resource_group() -> None:
    subscription = _normalised(
        SourceKind.AZURE,
        C.ACCOUNTS,
        {
            "id": f"/subscriptions/{SUBSCRIPTION}",
            "subscriptionId": SUBSCRIPTION.upper(),
            "displayName": "Acme Production",
            "state": "Enabled",
            "tenantId": "t-1",
            "tags": {"owner": "Platform"},
        },
        external_id=f"/subscriptions/{SUBSCRIPTION}",
        container=None,
    )
    group = _normalised(
        SourceKind.AZURE,
        C.ACCOUNTS,
        {
            "id": GROUP,
            "name": "rg-Billing-Prod",
            "type": "Microsoft.Resources/resourceGroups",
            "location": "westeurope",
            "tags": {"service": "billing-api"},
            "properties": {"provisioningState": "Succeeded"},
        },
        external_id=GROUP.lower(),
        container=SUBSCRIPTION,
    )

    s = subscription.entity
    assert (s.type, s.key, s.name) == ("cloud_account", AZURE_SUBSCRIPTION, "Acme Production")
    assert (s.attributes["state"], s.attributes["account_type"]) == ("active", "azure_subscription")
    assert (AZURE_SUBSCRIPTION, "owned_by", "team:platform") in _edges(subscription)
    g = group.entity
    assert (g.type, g.key, g.name) == ("resource_group", AZURE_GROUP, "rg-Billing-Prod")
    assert g.attributes["region"] == "westeurope"
    assert g.attributes["environment"] == "production"  # its name
    edges = _edges(group)
    assert (AZURE_GROUP, "part_of", AZURE_SUBSCRIPTION) in edges
    assert (AZURE_GROUP, "part_of", "service:billing-api") in edges


def test_a_google_cloud_project_is_also_known_by_its_number() -> None:
    project = _normalised(
        SourceKind.GCP,
        C.ACCOUNTS,
        {
            "name": "projects/415104041262",
            "projectId": "acme-dev",
            "displayName": "Acme dev",
            "state": "ACTIVE",
            "labels": {"env": "dev", "team": "platform"},
            "parent": "folders/2001",
        },
        external_id="acme-dev",
        container=None,
    )

    entity = project.entity
    assert (entity.key, entity.name) == ("gcp:project:acme-dev", "Acme dev")
    assert entity.aliases == ["gcp:project:415104041262"]
    assert (entity.attributes["parent"], entity.attributes["environment"]) == (
        "folders/2001",
        "development",
    )
    assert entity.attributes["environment_confidence"] == 0.95  # a label


def test_a_deleted_project_says_so() -> None:
    project = _normalised(
        SourceKind.GCP,
        C.ACCOUNTS,
        {"name": "projects/1", "projectId": "acme-old", "state": "DELETE_REQUESTED"},
        external_id="acme-old",
        container=None,
    )

    assert project.entity.attributes["state"] == "deleted"


# ── resources, placed ────────────────────────────────────────────────────────


def test_an_aws_resource_is_in_its_account_with_its_class() -> None:
    instance = _normalised(
        SourceKind.AWS,
        C.INSTANCES,
        {"InstanceId": "i-1", "Placement": {"AvailabilityZone": "eu-west-3a"}},
        container="eu-west-3",
        external_id=f"{ARN}:instance/i-1",
    )

    a = instance.entity.attributes
    assert (a["resource_kind"], a["resource_class"], a["account"]) == (
        "instance",
        "compute",
        ACCOUNT,
    )
    assert (a["region"], a["zone"]) == ("eu-west-3", "eu-west-3a")
    assert _related(instance)[AWS_ACCOUNT] == ("cloud_account", ACCOUNT)
    assert (instance.entity.key, "part_of", AWS_ACCOUNT) in _edges(instance)


def test_a_bucket_s_arn_names_no_account() -> None:
    bucket = _normalised(
        SourceKind.AWS,
        C.BUCKETS,
        {"Name": "acme-logs"},
        external_id="arn:aws:s3:::acme-logs",
        container=None,
    )

    assert bucket.entity.attributes["resource_class"] == "storage"
    assert "account" not in bucket.entity.attributes
    assert not any(t == "cloud_account" for t, _ in _related(bucket).values())


def test_a_database_says_where_a_client_connects() -> None:
    database = _normalised(
        SourceKind.AWS,
        C.DB_INSTANCES,
        {
            "DBInstanceIdentifier": "ledger",
            "Engine": "postgres",
            "Endpoint": {"Address": "Ledger.abc.eu-west-3.rds.amazonaws.com", "Port": 5432},
        },
        container="eu-west-3",
        external_id=f"{ARN}:db:ledger",
    )

    a = database.entity.attributes
    assert (database.entity.type, a["resource_class"]) == ("database", "database")
    assert (a["endpoint"], a["port"]) == ("ledger.abc.eu-west-3.rds.amazonaws.com", 5432)


def test_an_azure_resource_is_in_its_group_in_its_subscription() -> None:
    vm_id = f"{GROUP}/providers/Microsoft.Compute/virtualMachines/vm-1"
    vm = _normalised(
        SourceKind.AZURE,
        C.INSTANCES,
        {"id": vm_id, "name": "vm-1", "type": "Microsoft.Compute/virtualMachines"},
        container=SUBSCRIPTION,
        external_id=vm_id.lower(),
    )

    edges = _edges(vm)
    assert (vm.entity.key, "part_of", AZURE_GROUP) in edges
    assert (AZURE_GROUP, "part_of", AZURE_SUBSCRIPTION) in edges
    assert (vm.entity.key, "part_of", AZURE_SUBSCRIPTION) not in edges
    assert _related(vm)[AZURE_GROUP] == ("resource_group", "rg-Billing-Prod")
    assert vm.entity.attributes["account"] == SUBSCRIPTION


def test_a_google_resource_s_zone_says_its_region() -> None:
    name = "//compute.googleapis.com/projects/acme-dev/zones/europe-west1-b/instances/vm-1"
    vm = _normalised(
        SourceKind.GCP,
        C.INSTANCES,
        {
            "name": name,
            "assetType": "compute.googleapis.com/Instance",
            "resource": {"location": "europe-west1-b", "data": {"name": "vm-1"}},
        },
        container="acme-dev",
        external_id=name,
    )

    a = vm.entity.attributes
    assert (a["zone"], a["region"], a["account"]) == ("europe-west1-b", "europe-west1", "acme-dev")
    assert (vm.entity.key, "part_of", "gcp:project:acme-dev") in _edges(vm)


def test_a_terminated_instance_says_it_is_gone() -> None:
    instance = _normalised(
        SourceKind.AWS,
        C.INSTANCES,
        {"InstanceId": "i-9", "State": {"Name": "terminated"}},
        container="eu-west-3",
        external_id=f"{ARN}:instance/i-9",
    )

    assert instance.entity.attributes["state"] == "terminated"


# ── a node and its cluster ───────────────────────────────────────────────────


def test_an_eks_node_is_part_of_its_cluster_by_the_cluster_s_arn() -> None:
    cluster_arn = f"arn:aws:eks:eu-west-3:{ACCOUNT}:cluster/billing"
    for tags in (
        [{"Key": "eks:cluster-name", "Value": "billing"}],
        [{"Key": "kubernetes.io/cluster/billing", "Value": "owned"}],
    ):
        node = _normalised(
            SourceKind.AWS,
            C.INSTANCES,
            {"InstanceId": "i-node", "Tags": tags},
            container="eu-west-3",
            external_id=f"{ARN}:instance/i-node",
        )
        assert (node.entity.key, "part_of", f"aws:{cluster_arn}") in _edges(node)
        assert _related(node)[f"aws:{cluster_arn}"] == ("infra_resource", "billing")

    cluster = _normalised(
        SourceKind.AWS,
        C.CLUSTERS,
        {"name": "billing", "arn": cluster_arn},
        container="eu-west-3",
        external_id=cluster_arn,
    )
    assert cluster.entity.key == f"aws:{cluster_arn}"


def test_an_aks_node_finds_its_cluster_in_another_group() -> None:
    vmss = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/MC_rg-billing_aks_westeurope"
    vmss += "/providers/Microsoft.Compute/virtualMachineScaleSets/aks-nodes"
    node = _normalised(
        SourceKind.AZURE,
        C.INSTANCES,
        {
            "id": vmss,
            "name": "aks-nodes",
            "tags": {"aks-managed-cluster-name": "aks", "aks-managed-cluster-rg": "rg-billing"},
        },
        container=SUBSCRIPTION,
        external_id=vmss.lower(),
    )

    cluster = (
        f"azure:/subscriptions/{SUBSCRIPTION}/resourcegroups/rg-billing"
        "/providers/microsoft.containerservice/managedclusters/aks"
    )
    assert (node.entity.key, "part_of", cluster) in _edges(node)


def test_a_gke_node_and_its_cluster_meet_on_project_location_and_name() -> None:
    node_name = "//compute.googleapis.com/projects/acme-dev/zones/europe-west1-b/instances/gke-1"
    node = _normalised(
        SourceKind.GCP,
        C.INSTANCES,
        {
            "name": node_name,
            "resource": {
                "location": "europe-west1-b",
                "data": {
                    "name": "gke-1",
                    "labels": {
                        "goog-k8s-cluster-name": "main",
                        "goog-k8s-cluster-location": "europe-west1",
                    },
                },
            },
        },
        container="acme-dev",
        external_id=node_name,
    )
    cluster_name = (
        "//container.googleapis.com/projects/acme-dev/locations/europe-west1/clusters/main"
    )
    cluster = _normalised(
        SourceKind.GCP,
        C.CLUSTERS,
        {
            "name": cluster_name,
            "resource": {"location": "europe-west1", "data": {"name": "main"}},
        },
        container="acme-dev",
        external_id=cluster_name,
    )

    alias = "gcp:cluster:acme-dev/europe-west1/main"
    assert (node.entity.key, "part_of", alias) in _edges(node)
    assert alias in cluster.entity.aliases


def test_a_node_whose_tags_do_not_say_where_its_cluster_is_says_nothing() -> None:
    vmss = f"{GROUP}/providers/Microsoft.Compute/virtualMachineScaleSets/nodes"
    node = _normalised(
        SourceKind.AZURE,
        C.INSTANCES,
        {"id": vmss, "name": "nodes", "tags": {"aks-managed-cluster-name": "aks"}},
        container=SUBSCRIPTION,
        external_id=vmss.lower(),
    )

    assert not any("managedclusters" in to for _, _, to in _edges(node))


def test_cluster_tags_are_read_as_facts() -> None:
    _, parsed = _pipeline(
        SourceKind.AWS,
        C.INSTANCES,
        {"InstanceId": "i-1", "Tags": _tags(**{"kubernetes.io/cluster/billing": "owned"})},
        container="eu-west-3",
        external_id=f"{ARN}:instance/i-1",
    )

    assert [(f.value, f.confidence) for f in parsed.facts if f.type is FactType.CLUSTER] == [
        ("billing", 1.0)
    ]


# ── a CMDB's servers and databases ───────────────────────────────────────────


def _cmdb(record_id: str, title: str, metadata: dict[str, Any], **entity: str) -> NormalisedRecord:
    return _normalised(
        SourceKind.CUSTOM_REST,
        C.RECORDS,
        {
            "resource": "servers",
            "entity": entity.get("entity", "infra_resource"),
            "fields": {"id": record_id, "title": title, "metadata": metadata},
        },
        external_id=f"servers:{record_id}",
    )


def test_a_cmdb_resource_named_by_its_arn_is_keyed_as_the_cloud_s() -> None:
    database_arn = f"arn:aws:rds:eu-west-3:{ACCOUNT}:db:ledger"
    server = _cmdb(
        "42",
        "Ledger DB",
        {
            "arn": database_arn,
            "owner": "Data platform",
            "criticality": "Tier 1",
            "environment": "prod",
            "service": "ledger",
        },
        entity="database",
    )

    entity = server.entity
    assert (entity.type, entity.key) == ("database", f"aws:{database_arn}")
    a = entity.attributes
    assert (a["provider"], a["resource_class"], a["criticality"], a["environment"]) == (
        "aws",
        "database",
        "critical",
        "production",
    )
    edges = _edges(server)
    assert {
        (entity.key, "owned_by", "team:data-platform"),
        (entity.key, "part_of", "service:ledger"),
        (entity.key, "runs_in", "environment:production"),
    } <= edges


def test_a_cmdb_s_own_server_is_keyed_by_its_source_and_depends_by_id() -> None:
    database_arn = f"arn:aws:rds:eu-west-3:{ACCOUNT}:db:ledger"
    server = _cmdb(
        "srv-7",
        "batch-01",
        {"type": "server", "dependencies": f"{database_arn}, srv-8", "team": "Data platform"},
    )

    entity = server.entity
    assert entity.key.endswith(":infra_resource:servers:srv-7")
    assert (entity.attributes["resource_kind"], entity.attributes["resource_class"]) == (
        "instance",
        "compute",
    )
    depends = {to for _, kind, to in _edges(server) if kind == "depends_on"}
    assert depends == {
        f"aws:{database_arn}",
        entity.key.replace("servers:srv-7", "servers:srv-8"),
    }
