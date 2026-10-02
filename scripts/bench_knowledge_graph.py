"""Time the knowledge graph's questions on a company of a given size (LEKA-369).

    api/.venv/bin/python scripts/bench_knowledge_graph.py [--entities 20000]
        [--relationships 60000] [--runs 7]

Builds a synthetic workspace — "bench-graph", deleted and rebuilt each run —
shaped like a mid-sized company: teams and people, applications made of
services and repositories, databases with their schemas and tables, cloud
accounts and their resources, the business's capabilities and processes,
documents; and relationships among them in the proportions a real build
makes. Then asks GraphService (leka/knowledge/graph.py) what the screens
and the API ask — search, walks of 1 to 4 steps, the shortest ways, every
view, the coverage — and prints each question's median and slowest time.

The figures in docs/company-model.md § 16 come from this script: run it
again after changing a query, and say what moved.

Like seed.py, developer tooling: it writes through the ORM's tables
directly, in bulk, and never runs in production.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, text

# Every table known, as alembic/env.py does: a source's foreign keys reach
# the users'.
import leka.identity  # noqa: F401
from leka.connectors import Source, SourceKind, SourceStatus
from leka.db import session_factory, system_scope, workspace_scope
from leka.knowledge import (
    VIEWS,
    Entity,
    EntityType,
    GraphRepository,
    GraphService,
    Relationship,
    RelationshipType,
    search_fields,
)
from leka.platform import Workspace

SLUG = "bench-graph"
NOW = datetime.now(UTC)
CHUNK = 5_000

E = EntityType
R = RelationshipType

# A company's share of each kind, out of 1000.
SHAPE: dict[EntityType, int] = {
    E.TEAM: 10,
    E.PERSON: 150,
    E.APPLICATION: 15,
    E.SERVICE: 75,
    E.REPOSITORY: 150,
    E.DATABASE: 30,
    E.SCHEMA: 75,
    E.DATA_OBJECT: 300,
    E.CLOUD_ACCOUNT: 3,
    E.INFRA_RESOURCE: 150,
    E.BUSINESS_CAPABILITY: 5,
    E.BUSINESS_PROCESS: 10,
    E.DOCUMENT: 27,
}

# What ties what, and each kind of tie's share of the relationships, out of
# 1000: what a build makes of a company's sources.
TIES: tuple[tuple[RelationshipType, EntityType, EntityType, int], ...] = (
    (R.MEMBER_OF, E.PERSON, E.TEAM, 75),
    (R.REPORTS_TO, E.PERSON, E.PERSON, 50),
    (R.CHILD_OF, E.TEAM, E.TEAM, 2),
    (R.PART_OF, E.SERVICE, E.APPLICATION, 25),
    (R.PART_OF, E.REPOSITORY, E.SERVICE, 50),
    (R.PART_OF, E.SCHEMA, E.DATABASE, 25),
    (R.PART_OF, E.DATA_OBJECT, E.SCHEMA, 100),
    (R.PART_OF, E.INFRA_RESOURCE, E.CLOUD_ACCOUNT, 50),
    (R.OWNED_BY, E.SERVICE, E.TEAM, 25),
    (R.OWNED_BY, E.REPOSITORY, E.TEAM, 50),
    (R.OWNED_BY, E.APPLICATION, E.TEAM, 5),
    (R.CONTRIBUTES_TO, E.PERSON, E.REPOSITORY, 150),
    (R.DEPENDS_ON, E.SERVICE, E.SERVICE, 60),
    (R.DEPENDS_ON, E.SERVICE, E.DATABASE, 30),
    (R.READS_FROM, E.SERVICE, E.DATA_OBJECT, 80),
    (R.REFERENCES, E.DATA_OBJECT, E.DATA_OBJECT, 60),
    (R.IN_NETWORK, E.INFRA_RESOURCE, E.INFRA_RESOURCE, 40),
    (R.RUNS_IN, E.SERVICE, E.INFRA_RESOURCE, 30),
    (R.SUPPORTED_BY, E.BUSINESS_CAPABILITY, E.APPLICATION, 10),
    (R.USES, E.BUSINESS_PROCESS, E.APPLICATION, 15),
    (R.DESCRIBES, E.DOCUMENT, E.SERVICE, 30),
    (R.MAINTAINED_BY, E.REPOSITORY, E.PERSON, 38),
)

WORDS = (
    *("payment", "billing", "checkout", "order", "invoice", "catalog", "search", "user"),
    *("account", "auth", "notification", "shipping", "stock", "pricing", "report"),
    *("ledger", "refund", "customer", "partner", "loyalty", "fraud", "risk", "export"),
    *("import", "gateway", "queue", "cache", "archive", "audit"),
)
REGIONS = ("eu-west-1", "eu-west-3", "us-east-1", "eu-central-1")


def _name(kind: EntityType, n: int, rng: random.Random) -> tuple[str, str, dict[str, object]]:
    """A thing's key, name and attributes, as its sources would say them."""
    word = rng.choice(WORDS)
    other = rng.choice(WORDS)
    if kind is E.PERSON:
        name = f"{word.title()} {other.title()} {n}"
        return f"person:email:p{n}@acme.io", name, {"email": f"p{n}@acme.io"}
    if kind is E.REPOSITORY:
        name = f"acme/{word}-{other}-{n}"
        return f"github.com/{name}", name, {"language": rng.choice(("Python", "TypeScript"))}
    if kind is E.INFRA_RESOURCE:
        region = rng.choice(REGIONS)
        key = f"aws:arn:aws:ec2:{region}:123456789012:instance/i-{n:08x}"
        return key, f"{word}-{n}", {"state": rng.choice(("running", "running", "stopped"))}
    if kind is E.DATABASE:
        key = f"db:postgresql://db{n}:5432/{word}"
        return key, f"{word}_{n}", {"engine": "postgresql", "state": "running"}
    name = f"{word.title()} {other.title()} {n}"
    return f"{kind.value}:{word}-{other}-{n}", name, {"description": f"The {word} {other}."}


async def build(entities: int, relationships: int, seed: int) -> uuid.UUID:
    rng = random.Random(seed)  # noqa: S311 — a synthetic company, not a secret
    with system_scope():
        async with session_factory() as session:
            await session.execute(delete(Workspace).where(Workspace.slug == SLUG))
            workspace = Workspace(name="Bench graph", slug=SLUG)
            session.add(workspace)
            await session.flush()
            sources = [
                Source(
                    workspace_id=workspace.id,
                    kind=kind,
                    name=f"bench {kind.value}",
                    status=SourceStatus.ACTIVE,
                    config={"bench": True},
                )
                for kind in (SourceKind.GITHUB, SourceKind.PAGERDUTY, SourceKind.AWS)
            ]
            session.add_all(sources)
            await session.flush()

            ids: dict[EntityType, list[uuid.UUID]] = {}
            rows: list[dict[str, Any]] = []
            weight = sum(SHAPE.values())
            for kind, share in SHAPE.items():
                for n in range(max(1, entities * share // weight)):
                    key, name, attributes = _name(kind, n, rng)
                    said = rng.sample(sources, k=rng.choice((1, 1, 2)))
                    search_name, search_text = search_fields(key, name, attributes)
                    one = uuid.uuid4()
                    ids.setdefault(kind, []).append(one)
                    rows.append(
                        {
                            "id": one,
                            "workspace_id": workspace.id,
                            "type": kind,
                            "key": key,
                            "name": name,
                            "attributes": attributes,
                            "provenance": {
                                "sources": [
                                    {"source_id": str(s.id), "key": key, "kind": "id"} for s in said
                                ]
                            },
                            "first_seen_at": NOW,
                            "last_seen_at": NOW,
                            "search_name": search_name,
                            "search_text": search_text,
                        }
                    )
            for start in range(0, len(rows), CHUNK):
                await session.execute(insert(Entity), rows[start : start + CHUNK])

            seen: set[tuple[uuid.UUID, uuid.UUID, RelationshipType]] = set()
            edges: list[dict[str, Any]] = []
            weight = sum(share for *_, share in TIES)
            for kind, near, far, share in TIES:
                wanted = relationships * share // weight
                for _ in range(wanted * 3):
                    if wanted == 0:
                        break
                    a, b = rng.choice(ids[near]), rng.choice(ids[far])
                    if a == b or (a, b, kind) in seen:
                        continue
                    seen.add((a, b, kind))
                    wanted -= 1
                    edges.append(
                        {
                            "workspace_id": workspace.id,
                            "from_entity_id": a,
                            "to_entity_id": b,
                            "type": kind,
                            "confidence": round(rng.uniform(0.6, 1.0), 2),
                            "first_seen_at": NOW,
                            "changed_at": NOW,
                        }
                    )
            for start in range(0, len(edges), CHUNK):
                await session.execute(insert(Relationship), edges[start : start + CHUNK])
            await session.commit()
            await session.execute(text("ANALYZE entities"))
            await session.execute(text("ANALYZE relationships"))
            print(f"built: {len(rows)} entities, {len(edges)} relationships", flush=True)
            return workspace.id


async def _timed(runs: int, ask: Callable[[], Awaitable[object]]) -> tuple[float, float]:
    """The median and the slowest of `runs` asks, in milliseconds — the
    first, which warms PostgreSQL's caches, not counted."""
    await ask()
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        await ask()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times), max(times)


async def bench(workspace_id: uuid.UUID, runs: int) -> None:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            graph = GraphService(GraphRepository(session, workspace_id))
            # The most connected service — the walk that reaches most — and
            # a typical one; a team, to find a way to.
            picked: list[uuid.UUID] = []
            for kind, order in (("service", "DESC"), ("service", "ASC"), ("team", "DESC")):
                found = await session.execute(
                    text(
                        f"""
                        SELECT e.id FROM entities e
                        WHERE e.workspace_id = :w AND e.type = '{kind}'
                        ORDER BY (SELECT count(*) FROM relationships r
                                  WHERE r.workspace_id = :w AND r.from_entity_id = e.id)
                               + (SELECT count(*) FROM relationships r
                                  WHERE r.workspace_id = :w AND r.to_entity_id = e.id)
                                 {order}, e.id
                        LIMIT 1
                        """  # noqa: S608 — this script's own constants
                    ),
                    {"w": workspace_id},
                )
                picked.append(found.scalar_one())
            hub, typical, team = picked
            questions: list[tuple[str, Callable[[], Awaitable[object]]]] = [
                ("search « pay »", lambda: graph.search("pay", limit=20)),
                ("search « billing api »", lambda: graph.search("billing api", limit=20)),
                ("search « zzz » (nothing)", lambda: graph.search("zzz", limit=20)),
                ("walk, typical service, 1 step", lambda: graph.walk([typical], depth=1)),
                ("walk, typical service, 2 steps", lambda: graph.walk([typical], depth=2)),
                ("walk, typical service, 4 steps", lambda: graph.walk([typical], depth=4)),
                ("walk, busiest service, 2 steps", lambda: graph.walk([hub], depth=2)),
                ("walk, busiest service, 4 steps", lambda: graph.walk([hub], depth=4)),
                (
                    "walk, busiest service, 4 steps, dependencies only",
                    lambda: graph.walk(
                        [hub],
                        depth=4,
                        types=(R.DEPENDS_ON, R.READS_FROM, R.REFERENCES),
                    ),
                ),
                ("paths, typical service → team", lambda: graph.paths(typical, team)),
                ("paths, busiest service → team", lambda: graph.paths(hub, team)),
                *((f"view {name}", lambda name=name: graph.view(name, now=NOW)) for name in VIEWS),
                ("coverage", graph.coverage),
            ]
            print("\n| question | median (ms) | slowest (ms) |\n|---|---:|---:|", flush=True)
            for label, ask in questions:
                median, slowest = await _timed(runs, ask)
                print(f"| {label} | {median:.0f} | {slowest:.0f} |", flush=True)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--entities", type=int, default=20_000)
    parser.add_argument("--relationships", type=int, default=60_000)
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--seed", type=int, default=369)
    parser.add_argument("--keep", action="store_true", help="Keep the workspace afterwards.")
    args = parser.parse_args()
    workspace_id = await build(args.entities, args.relationships, args.seed)
    try:
        await bench(workspace_id, args.runs)
    finally:
        if not args.keep:
            with system_scope():
                async with session_factory() as session:
                    await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
                    await session.commit()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
