"""What a repository's code says it runs, in the company model (LEKA-369).

LEKA's own repository, as GitHub's connector reads it: the repository, and
the components its files declare (test_components.py) — through
extraction, normalisation, resolution, enrichment and the model's build.

What these protect: each service of the code is a service — its type,
language, technology, where it is reached, run by the company — and its
repository is part of it; Redis and PostgreSQL are databases, S3 a storage
resource, OVH a service outside; each link the code declares is a
`depends_on` between them, its role and the file and line that say so in
its provenance — a front end calling its API less surely than a route; what
runs in production runs in it; and every member reads it, no other
workspace.

With the AWS account beside it: the services at leka-core.com's address run
on the instance that has it, what is deployed with them too; the code's
PostgreSQL is the account's RDS, its S3 store the bucket named for the
repository; and the landscape says each healthy as the machine running it
is — deduced, and says so.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from leka.connectors import Capability, SourceKind
from leka.connectors.components import discover
from tests.conftest import FakeIdentity
from tests.test_application_landscape import _record, _store
from tests.test_components import FILES, REPOSITORY
from tests.test_relationships_engine import _build
from tests.test_resolution_job import _source
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/knowledge"
REPO_URL = "https://github.com/Haitam-elh/Leka"
LEKA_API = "service:leka-api"
LEKA_WEB = "service:leka-web"
CADDY = "service:leka-caddy"
OVH = "service:ovh-e-mail"
REDIS = "db:redis://github.com/haitam-elh/leka/redis"
POSTGRES = "db:postgresql://github.com/haitam-elh/leka/postgresql"
S3 = "code:github.com/haitam-elh/leka:storage:s3"
REPOSITORY_KEY = "github.com/haitam-elh/leka"
LEKA_WORKER = "service:leka-worker"
ARN = "arn:aws:ec2:eu-central-1:123456789012"
BOX = f"aws:{ARN}:instance/i-0leka"
RDS = "aws:arn:aws:rds:eu-central-1:123456789012:db:leka"
BUCKET = "aws:arn:aws:s3:::leka-uploads-prod"
IP = "3.78.172.119"


async def _leka(workspace: uuid.UUID, *, aws: bool = False) -> dict[str, uuid.UUID]:
    github = await _source(workspace, "GitHub")
    await _store(
        workspace,
        github,
        _record(
            SourceKind.GITHUB,
            Capability.REPOSITORIES,
            {
                "node_id": "R_leka",
                "full_name": REPOSITORY,
                "html_url": REPO_URL,
                "default_branch": "main",
                "owner": {"login": "Haitam-elh"},
            },
            external_id="R_leka",
            container=REPOSITORY,
        ),
    )
    for component in discover(REPOSITORY, FILES):
        await _store(
            workspace,
            github,
            _record(
                SourceKind.GITHUB,
                Capability.COMPONENTS,
                {
                    **component,
                    "repository_url": REPO_URL,
                    "default_branch": "main",
                    # leka-core.com and api.leka-core.com, resolved.
                    "public_addresses": [IP] if component.get("public_url") else [],
                },
                external_id=f"R_leka:{component['name']}",
                container=REPOSITORY,
            ),
        )
    if aws:
        await _account(workspace)
    return await _build(workspace)


async def _account(workspace: uuid.UUID) -> None:
    """The AWS account LEKA runs in: its machine, its RDS, its buckets."""
    source = await _source(workspace, "AWS")
    for capability, payload, external_id in (
        (
            Capability.INSTANCES,
            {
                "InstanceId": "i-0leka",
                "State": {"Name": "running"},
                "PublicIpAddress": IP,
                "Tags": [{"Key": "Name", "Value": "leka-prod"}],
            },
            f"{ARN}:instance/i-0leka",
        ),
        (
            Capability.DB_INSTANCES,
            {"DBInstanceIdentifier": "leka", "Engine": "postgres", "DBInstanceStatus": "available"},
            RDS.removeprefix("aws:"),
        ),
        (Capability.BUCKETS, {"Name": "leka-uploads-prod"}, BUCKET.removeprefix("aws:")),
        (Capability.BUCKETS, {"Name": "acme-logs"}, "arn:aws:s3:::acme-logs"),
    ):
        await _store(
            workspace,
            source,
            _record(
                SourceKind.AWS,
                capability,
                payload,
                container=None if capability is Capability.BUCKETS else "eu-central-1",
                external_id=external_id,
            ),
        )


@pytest.fixture
async def leka(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    ids = await _leka(acme["acme"])
    _as(identity, acme, "member")
    return ids


async def _get(client: AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _ties(client: AsyncClient, entity: uuid.UUID) -> dict[tuple[str, str, str], Any]:
    found = await _get(client, "/relationships", entity_id=str(entity), limit=100)
    return {(r["from_entity"]["key"], r["type"], r["to_entity"]["key"]): r for r in found["data"]}


async def test_each_service_of_the_code_is_a_service_run_by_the_company(
    client: AsyncClient, leka: dict[str, uuid.UUID]
) -> None:
    api = (await _get(client, f"/entities/{leka[LEKA_API]}"))["attributes"]
    assert api["service_type"] == "api"
    assert api["languages"] == ["Python"]
    assert api["technology"] == ["Python", "FastAPI"]
    assert api["public_url"] == "https://api.leka-core.com"
    assert (api["hosting"], api["environment"], api["code_path"]) == ("self", "production", "api")
    assert api["deployed_by"] == ".github/workflows/cd.yml"
    assert any("deploy/docker-compose.production.yml" in e for e in api["evidence"])
    web = (await _get(client, f"/entities/{leka[LEKA_WEB]}"))["attributes"]
    assert (web["service_type"], web["public_url"]) == ("web", "https://leka-core.com")
    ovh = (await _get(client, f"/entities/{leka[OVH]}"))["attributes"]
    assert (ovh["hosting"], ovh["vendor"], ovh["service_type"]) == ("external", "OVH", "email")


async def test_stores_are_databases_and_a_storage_resource(
    client: AsyncClient, leka: dict[str, uuid.UUID]
) -> None:
    redis = await _get(client, f"/entities/{leka[REDIS]}")
    assert (redis["type"], redis["name"]) == ("database", "Redis")
    assert (redis["attributes"]["engine"], redis["attributes"]["store_role"]) == ("redis", "cache")
    postgres = await _get(client, f"/entities/{leka[POSTGRES]}")
    assert (postgres["type"], postgres["attributes"]["engine"]) == ("database", "postgresql")
    s3 = await _get(client, f"/entities/{leka[S3]}")
    assert s3["type"] == "infra_resource"
    assert (s3["attributes"]["provider"], s3["attributes"]["region"]) == ("aws", "eu-central-1")
    assert s3["attributes"]["resource_class"] == "storage"


async def test_each_link_is_a_dependency_with_its_role_and_its_evidence(
    client: AsyncClient, leka: dict[str, uuid.UUID]
) -> None:
    ties = await _ties(client, leka[LEKA_API])
    for target in (REDIS, POSTGRES, S3, OVH):
        assert (LEKA_API, "depends_on", target) in ties, target
    queue = ties[(LEKA_API, "depends_on", REDIS)]
    evidence = [p.get("evidence") for p in queue["provenance"]]
    assert any(str(e).startswith("queue: ") and "LEKA_REDIS_URL" in str(e) for e in evidence)
    # The repository is the code of the service.
    assert (REPOSITORY_KEY, "part_of", LEKA_API) in ties
    assert (LEKA_API, "runs_in", "environment:production") in ties

    routes = await _ties(client, leka[CADDY])
    assert (CADDY, "depends_on", LEKA_API) in routes
    assert (CADDY, "depends_on", LEKA_WEB) in routes
    calls = (await _ties(client, leka[LEKA_WEB]))[(LEKA_WEB, "depends_on", LEKA_API)]
    # What a front end is told of its API is less sure than a route.
    assert calls["confidence"] == 0.8
    assert routes[(CADDY, "depends_on", LEKA_API)]["confidence"] == 0.9


async def test_on_aws_each_runs_where_its_address_and_its_deployment_say(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _leka(acme["acme"], aws=True)
    _as(identity, acme, "member")

    def rule(ties: dict[tuple[str, str, str], Any], tie: tuple[str, str, str]) -> Any:
        return (ties[tie]["origin"], ties[tie]["rule"], ties[tie]["confidence"])

    hosted = (LEKA_API, "depends_on", BOX)
    assert rule(await _ties(client, ids[LEKA_API]), hosted) == ("inferred", "public_address", 0.9)
    # The worker is deployed with it by the same workflow: on the same machine.
    worker = (LEKA_WORKER, "depends_on", BOX)
    assert rule(await _ties(client, ids[LEKA_WORKER]), worker)[1] == "deployed_together"
    served = (POSTGRES, "part_of", RDS)
    assert rule(await _ties(client, ids[POSTGRES]), served)[1] == "only_instance"
    stored = await _ties(client, ids[S3])
    assert rule(stored, (S3, "part_of", BUCKET))[1] == "named_for_repository"
    assert not [tie for tie in stored if tie[2].endswith("acme-logs")]

    services = await _get(client, "/views/services")
    boxes = {node["key"]: node for node in services["nodes"]}
    # No tool watches it: its machine runs, so it is operational — deduced.
    assert (boxes[LEKA_API]["status"], boxes[LEKA_API]["deduced"]) == ("operational", True)
    assert (boxes[LEKA_WORKER]["status"], boxes[LEKA_WORKER]["deduced"]) == ("operational", True)
    # OVH's mail is outside, run by no one here: not a service of the company's.
    assert OVH not in boxes


async def test_another_workspace_sees_none_of_it(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    leka: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "other_admin")

    response = await client.get(f"{API}/entities/{leka[LEKA_API]}")

    assert response.status_code == 404
