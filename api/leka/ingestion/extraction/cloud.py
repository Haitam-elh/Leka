"""Cloud platforms: AWS, Azure, Google Cloud — seven kinds of resource, and
what they are in.

Every resource comes out with the same technical signals whatever its
provider: `provider`, `resource_type`, `region`, `tags` ('key=value'), and
what its kind has — `instance_type`, `engine`, `runtime`, `version`,
`network`. Its `title` is the name a person gave it (AWS's Name tag), else
its id.

What they are in (`accounts`, LEKA-363): an AWS account — its alias and its
organisation — Azure's subscriptions and resource groups, Google Cloud's
projects — their names, states, tags or labels, and what is above them.

The payloads are the ones leka/connectors/{aws,azure,gcp} store: boto3's
answers (dates as text), Azure Resource Manager's resource list, Cloud
Asset Inventory's assets.
"""

from __future__ import annotations

from datetime import datetime

from leka.connectors import Capability, RawRecord, SourceKind
from leka.ingestion.extraction.contract import Content, Extracted
from leka.ingestion.extraction.engine import Payload, record_strategy, strategy
from leka.ingestion.extraction.fields import (
    content,
    dig,
    flag,
    last_segment,
    lower,
    number,
    ref,
    required,
    string,
    strings,
    tags,
    when,
)

C = Capability
AWS, AZURE, GCP = SourceKind.AWS, SourceKind.AZURE, SourceKind.GCP
CLOUD = (
    C.INSTANCES,
    C.DB_INSTANCES,
    C.BUCKETS,
    C.FUNCTIONS,
    C.CLUSTERS,
    C.NETWORKS,
    C.LOAD_BALANCERS,
)

# ── AWS: one shape per service ───────────────────────────────────────────────


@record_strategy("aws.instances", 1, (AWS, C.INSTANCES))
def aws_instance(r: RawRecord) -> Extracted:
    p = r.payload
    return _aws(
        r,
        "ec2:instance",
        required(p, "InstanceId"),
        state=lower(p, "State", "Name"),
        created=when(p, "LaunchTime"),
        network=string(p, "VpcId"),
        signals={
            "instance_type": string(p, "InstanceType"),
            "platform": string(p, "PlatformDetails"),
            "architecture": string(p, "Architecture"),
            "zone": string(p, "Placement", "AvailabilityZone"),
        },
    )


@record_strategy("aws.db_instances", 2, (AWS, C.DB_INSTANCES))
def aws_database(r: RawRecord) -> Extracted:
    p = r.payload
    return _aws(
        r,
        "rds:db",
        required(p, "DBInstanceIdentifier"),
        state=lower(p, "DBInstanceStatus"),
        created=when(p, "InstanceCreateTime"),
        network=string(p, "DBSubnetGroup", "VpcId"),
        tag_list="TagList",
        signals={
            "engine": string(p, "Engine"),
            "version": string(p, "EngineVersion"),
            "instance_type": string(p, "DBInstanceClass"),
            "multi_az": flag(p, "MultiAZ"),
            "storage_gb": number(p, "AllocatedStorage"),
            "encrypted": flag(p, "StorageEncrypted"),
            "public": flag(p, "PubliclyAccessible"),
            # Where a client connects: what a database source names (LEKA-364).
            "endpoint": lower(p, "Endpoint", "Address"),
            "port": number(p, "Endpoint", "Port"),
        },
    )


@record_strategy("aws.buckets", 1, (AWS, C.BUCKETS))
def aws_bucket(r: RawRecord) -> Extracted:
    p = r.payload
    return _aws(r, "s3:bucket", required(p, "Name"), created=when(p, "CreationDate"))


@record_strategy("aws.functions", 1, (AWS, C.FUNCTIONS))
def aws_function(r: RawRecord) -> Extracted:
    p = r.payload
    return _aws(
        r,
        "lambda:function",
        required(p, "FunctionName"),
        state=lower(p, "State"),
        updated=when(p, "LastModified"),
        network=string(p, "VpcConfig", "VpcId"),
        description=string(p, "Description"),
        signals={
            "runtime": string(p, "Runtime"),
            "memory_mb": number(p, "MemorySize"),
            "timeout_s": number(p, "Timeout"),
            "architecture": ",".join(strings(p, "Architectures")) or None,
            "package": lower(p, "PackageType"),
        },
    )


@record_strategy("aws.clusters", 1, (AWS, C.CLUSTERS))
def aws_cluster(r: RawRecord) -> Extracted:
    p = r.payload
    return _aws(
        r,
        "eks:cluster",
        required(p, "name"),
        state=lower(p, "status"),
        created=when(p, "createdAt"),
        network=string(p, "resourcesVpcConfig", "vpcId"),
        tag_list="tags",
        signals={"version": string(p, "version"), "platform": string(p, "platformVersion")},
    )


@record_strategy("aws.networks", 1, (AWS, C.NETWORKS))
def aws_network(r: RawRecord) -> Extracted:
    p = r.payload
    return _aws(
        r,
        "ec2:vpc",
        required(p, "VpcId"),
        state=lower(p, "State"),
        signals={"cidr": string(p, "CidrBlock"), "default": flag(p, "IsDefault")},
    )


@record_strategy("aws.load_balancers", 1, (AWS, C.LOAD_BALANCERS))
def aws_load_balancer(r: RawRecord) -> Extracted:
    p = r.payload
    return _aws(
        r,
        "elbv2:loadbalancer",
        required(p, "LoadBalancerName"),
        state=lower(p, "State", "Code"),
        created=when(p, "CreatedTime"),
        network=string(p, "VpcId"),
        signals={
            "type": lower(p, "Type"),
            "scheme": lower(p, "Scheme"),
            "dns": string(p, "DNSName"),
        },
    )


def _aws(
    r: RawRecord,
    resource_type: str,
    resource_id: str,
    *,
    state: str | None = None,
    created: datetime | None = None,
    updated: datetime | None = None,
    network: str | None = None,
    description: str | None = None,
    tag_list: str = "Tags",
    signals: dict[str, str | int | float | bool | None] | None = None,
) -> Extracted:
    """What every AWS resource has: its Name tag or id, its region (the
    record's container; none for S3's global list), its tags, its VPC."""
    found = tags(r.payload, tag_list)
    name = next((t.split("=", 1)[1] for t in found if t.startswith("Name=")), None)
    return Extracted(
        title=name or resource_id,
        state=state,
        created_at=created,
        updated_at=updated or created,
        content=_description(description),
        references=ref("network", "network", external_id=network),
        metadata={"id": resource_id},
        signals={
            "provider": "aws",
            "resource_type": resource_type,
            "region": r.container,
            "tags": found,
            **(signals or {}),
        },
    )


# ── Azure: one shape for every resource ─────────────────────────────────────


@record_strategy("azure.resources", 1, *((AZURE, c) for c in CLOUD))
def azure_resource(r: RawRecord) -> Extracted:
    p = r.payload
    resource_id = required(p, "id")
    return Extracted(
        title=required(p, "name"),
        state=lower(p, "properties", "provisioningState"),
        created_at=when(p, "createdTime"),
        updated_at=when(p, "changedTime"),
        metadata={
            "id": resource_id,
            "subscription": r.container,
            "resource_group": _segment_after(resource_id, "resourceGroups"),
        },
        signals={
            "provider": "azure",
            "resource_type": lower(p, "type"),
            "region": lower(p, "location"),
            "tags": tags(p, "tags"),
            "sku": string(p, "sku", "name"),
            "tier": string(p, "sku", "tier"),
            "kind": lower(p, "kind"),
        },
    )


# ── Google Cloud: an asset around each API's own resource ────────────────────


@strategy("gcp.assets", 1, *((GCP, c) for c in CLOUD))
def gcp_asset(p: Payload) -> Extracted:
    name = required(p, "name")
    d = dig(p, "resource", "data")
    return Extracted(
        title=last_segment(string(d, "name")) or string(d, "displayName") or last_segment(name),
        state=lower(d, "status") or lower(d, "state"),
        created_at=when(d, "creationTimestamp") or when(d, "createTime") or when(d, "timeCreated"),
        updated_at=when(p, "updateTime"),
        content=_description(string(d, "description")),
        references=ref("network", "network", external_id=last_segment(string(d, "network"))),
        metadata={"id": name, "project": _segment_after(name, "projects")},
        signals={
            "provider": "gcp",
            "resource_type": lower(p, "assetType"),
            "region": lower(p, "resource", "location"),
            "tags": tags(d, "labels") or tags(d, "settings", "userLabels"),
            "instance_type": last_segment(string(d, "machineType"))
            or string(d, "settings", "tier"),
            "engine": lower(d, "databaseVersion"),
            "runtime": string(d, "runtime") or string(d, "buildConfig", "runtime"),
            "version": string(d, "currentMasterVersion"),
            "storage_class": lower(d, "storageClass"),
            "scheme": lower(d, "loadBalancingScheme"),
        },
    )


# ── what the resources are in (LEKA-363) ─────────────────────────────────────


@record_strategy("aws.accounts", 1, (AWS, C.ACCOUNTS))
def aws_account(r: RawRecord) -> Extracted:
    """The account: its alias — the name its admins gave it — else its id;
    its organisation, when the policy allowed reading it."""
    p = r.payload
    account = required(p, "Account")
    aliases = strings(p, "AccountAliases")
    return Extracted(
        title=aliases[0] if aliases else account,
        metadata={
            "id": account,
            "organization": string(p, "Organization", "Id"),
            "management_account": string(p, "Organization", "MasterAccountId"),
        },
        signals={"provider": "aws", "resource_type": "account"},
    )


@record_strategy("azure.accounts", 1, (AZURE, C.ACCOUNTS))
def azure_scope(r: RawRecord) -> Extracted:
    """A subscription — its name, state, tenant, tags — or one of its
    resource groups, with its location and tags."""
    p = r.payload
    if "subscriptionId" in p:
        subscription = required(p, "subscriptionId").lower()
        return Extracted(
            title=string(p, "displayName") or subscription,
            state=lower(p, "state"),
            metadata={"id": f"/subscriptions/{subscription}", "tenant": string(p, "tenantId")},
            signals={"provider": "azure", "resource_type": "subscription", "tags": tags(p, "tags")},
        )
    resource_id = required(p, "id").lower()
    return Extracted(
        title=required(p, "name"),
        state=lower(p, "properties", "provisioningState"),
        metadata={
            "id": resource_id,
            "subscription": r.container,
            "resource_group": _segment_after(resource_id, "resourceGroups"),
        },
        signals={
            "provider": "azure",
            "resource_type": "resource_group",
            "region": lower(p, "location"),
            "tags": tags(p, "tags"),
        },
    )


@strategy("gcp.accounts", 1, (GCP, C.ACCOUNTS))
def gcp_project(p: Payload) -> Extracted:
    """A project: its name, labels and state, its number — some APIs name
    it by that — and the folder or organisation it is in."""
    project = required(p, "projectId")
    return Extracted(
        title=string(p, "displayName") or project,
        state=lower(p, "state"),
        created_at=when(p, "createTime"),
        updated_at=when(p, "updateTime"),
        metadata={
            "id": project,
            "number": last_segment(string(p, "name")),
            "parent": string(p, "parent"),
        },
        signals={"provider": "gcp", "resource_type": "project", "tags": tags(p, "labels")},
    )


# ── shared ───────────────────────────────────────────────────────────────────


def _description(text: str | None) -> list[Content]:
    return content("description", text)


def _segment_after(path: str, marker: str) -> str | None:
    """'/subscriptions/s/resourceGroups/Prod/…' → 'Prod' for 'resourceGroups'."""
    parts = path.split("/")
    for index, part in enumerate(parts[:-1]):
        if part.lower() == marker.lower():
            return parts[index + 1] or None
    return None
