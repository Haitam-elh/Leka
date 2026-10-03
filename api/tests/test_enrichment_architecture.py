"""Where what the code runs runs, and how it is doing (LEKA-369): enrichment's
`architecture`.

LEKA's own world, as resolution leaves it: the repository and what its
code runs — the API and the web app answering at leka-core.com's address,
the worker and Redis deployed with them by the CD workflow, a PostgreSQL
reached by a URL the code does not show, an S3 store, OVH's mail outside;
the AWS account's instance at that address, its RDS PostgreSQL, two
buckets; the last deployment to production.

What these protect: a service runs on the instance its public address is,
what is deployed with it on the same; the code's database is served by the
cloud's only instance of its engine — two, and none is chosen — its store
by the bucket named for the repository; each deduces its health from what
runs it — a stopped machine, a failed deployment, a worse word — and a
service outside, run by no one here, deduces none.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from leka.ingestion.enrichment import enrich
from leka.ingestion.enrichment.engine import Enrichment
from leka.ingestion.enrichment.view import Thing, deduced, status
from tests.test_enrichment import AWS, GITHUB, World

REPO = "github.com/haitam-elh/leka"
REPO_URL = "https://github.com/Haitam-elh/Leka"
API, WEB, WORKER, OVH = (
    "service:leka-api",
    "service:leka-web",
    "service:leka-worker",
    "service:ovh-e-mail",
)
REDIS = "db:redis://github.com/haitam-elh/leka/redis"
POSTGRES = "db:postgresql://github.com/haitam-elh/leka/postgresql"
STORE = "code:github.com/haitam-elh/leka:storage:s3"
ARN = "aws:arn:aws:ec2:eu-central-1:123456789012"
BOX = f"{ARN}:instance/i-0leka"
RDS = "aws:arn:aws:rds:eu-central-1:123456789012:db:leka"
UPLOADS, LOGS = "aws:arn:aws:s3:::leka-uploads-prod", "aws:arn:aws:s3:::acme-logs"
DEPLOYMENT = f"{REPO}/deployments/1"
IP = "3.78.172.119"
CD = ".github/workflows/cd.yml"


def _world(
    *, box_state: str = "running", deployment: str = "succeeded", second_rds: bool = False
) -> World:
    world = World()
    shipped: dict[str, Any] = {
        "deployed_by": CD,
        "repository_url": REPO_URL,
        "environment": "production",
    }
    world.thing(REPO, "Haitam-elh/Leka", type="repository")
    world.thing(
        API,
        "Leka API",
        type="service",
        hosting="self",
        public_url="https://api.leka-core.com",
        public_addresses=[IP],
        **shipped,
    )
    world.thing(
        WEB,
        "Leka Web",
        type="service",
        hosting="self",
        public_url="https://leka-core.com",
        public_addresses=[IP],
        **shipped,
    )
    world.thing(WORKER, "Leka Worker", type="service", hosting="self", **shipped)
    world.thing(REDIS, "Redis", type="database", engine="redis", store_role="cache", **shipped)
    world.thing(
        POSTGRES,
        "PostgreSQL",
        type="database",
        engine="postgresql",
        store_role="database",
        environment="production",
    )
    world.thing(
        STORE,
        "S3",
        type="infra_resource",
        resource_class="storage",
        provider="aws",
        repository_url=REPO_URL,
    )
    world.thing(OVH, "OVH (e-mail)", type="service", hosting="external", vendor="OVH")
    world.states(GITHUB, REPO, "part_of", API, evidence="code: api")
    world.thing(
        DEPLOYMENT,
        "main to production",
        type="deployment",
        environment="production",
        state=deployment,
        created_at="2026-10-03T01:20:00Z",
    )
    world.states(GITHUB, DEPLOYMENT, "part_of", REPO, evidence="container")

    aws: dict[str, Any] = {"sources": (AWS,), "provider": "aws"}
    world.thing(BOX, "leka-prod", type="infra_resource", public_ip=IP, state=box_state, **aws)
    world.thing(RDS, "leka", type="database", engine="postgres", state="running", **aws)
    if second_rds:
        world.thing(RDS + "-replica", "leka-replica", type="database", engine="postgres", **aws)
    for bucket, name in ((UPLOADS, "leka-uploads-prod"), (LOGS, "acme-logs")):
        world.thing(bucket, name, type="infra_resource", resource_kind="bucket", **aws)
    return world


def _edges(world: World, result: Enrichment) -> dict[tuple[str, str], tuple[str, str, float]]:
    keys = {v: k for k, v in ((key, world.id(key)) for key in _keys(world))}
    return {
        (keys[e.from_id], keys[e.to_id]): (e.type, e.rule, e.confidence)
        for e in result.edges
        if e.origin == "inferred" and e.from_id in keys and e.to_id in keys
    }


def _keys(world: World) -> list[str]:
    return [node.key for node in world.nodes.values()]


def _health(world: World, result: Enrichment) -> dict[str, object]:
    keys = {world.id(k): k for k in _keys(world)}
    return {keys[f.entity_id]: f.value for f in result.facts if f.attribute == "deduced_health"}


def test_a_service_runs_on_the_instance_its_public_address_is() -> None:
    world = _world()

    edges = _edges(world, enrich(world.snapshot()))

    assert edges[(API, BOX)] == ("depends_on", "public_address", 0.9)
    assert edges[(WEB, BOX)] == ("depends_on", "public_address", 0.9)


def test_what_is_deployed_with_it_runs_with_it() -> None:
    world = _world()

    edges = _edges(world, enrich(world.snapshot()))

    assert edges[(WORKER, BOX)] == ("depends_on", "deployed_together", 0.8)
    assert edges[(REDIS, BOX)] == ("depends_on", "deployed_together", 0.8)
    # A service outside runs on nothing of the company's.
    assert not [pair for pair in edges if pair[0] == OVH]


def test_the_code_s_database_and_store_are_served_by_the_cloud() -> None:
    world = _world()

    edges = _edges(world, enrich(world.snapshot()))

    assert edges[(POSTGRES, RDS)] == ("part_of", "only_instance", 0.7)
    assert edges[(STORE, UPLOADS)] == ("part_of", "named_for_repository", 0.8)
    assert (STORE, LOGS) not in edges


def test_two_instances_of_its_engine_and_none_is_chosen() -> None:
    world = _world(second_rds=True)

    edges = _edges(world, enrich(world.snapshot()))

    assert not [pair for pair in edges if pair[0] == POSTGRES]


def test_each_deduces_its_health_from_what_runs_it() -> None:
    world = _world()

    health = _health(world, enrich(world.snapshot()))

    assert health == {
        API: "operational",
        WEB: "operational",
        WORKER: "operational",
        REDIS: "operational",
        POSTGRES: "operational",
    }


def test_a_stopped_machine_or_a_failed_deployment_is_attention() -> None:
    stopped = _world(box_state="stopped")
    assert _health(stopped, enrich(stopped.snapshot()))[API] == "attention"

    failed = _world(deployment="failed")
    result = enrich(failed.snapshot())
    assert _health(failed, result)[API] == "attention"
    fact = next(
        f for f in result.facts if f.attribute == "deduced_health" and f.entity_id == failed.id(API)
    )
    assert "leka-prod is running" in fact.evidence
    assert "last deployment failed" in fact.evidence


def test_the_screen_says_a_deduced_state_and_a_tool_s_word_wins() -> None:
    def thing(**facts: object) -> Thing:
        return Thing(
            id=uuid.uuid4(),
            type="service",
            key=API,
            name="Leka API",
            attributes={},
            facts=facts,
            kinds=frozenset({"github"}),
        )

    seen = thing(deduced_health="operational")
    assert status(seen, monitoring=frozenset({"datadog"}), recently_hit=False) == "operational"
    assert deduced(seen, monitoring=frozenset({"datadog"}), recently_hit=False)
    # Datadog shows it: its word, not a deduction.
    watched = replace(seen, kinds=frozenset({"github", "datadog"}))
    assert not deduced(watched, monitoring=frozenset({"datadog"}), recently_hit=False)
    # An open incident is an incident, whatever runs it.
    hit = thing(deduced_health="operational", open_incidents=1)
    assert status(hit, monitoring=frozenset(), recently_hit=False) == "incident"
    # Nothing deduced, nothing watching: unmonitored, as before.
    assert status(thing(), monitoring=frozenset(), recently_hit=False) == "unmonitored"
