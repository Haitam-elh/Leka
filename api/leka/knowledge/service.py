"""Business logic over the company model.

What leka.context and leka.intentions ask of the graph: an entity, its
neighbourhood, its history; the landscape of applications and services,
and what depends on what (LEKA-362); the infrastructure — its resources,
the accounts they are in, where and whose each is (LEKA-363). The registry (registry.py) is what
they read to know what kinds of things a company is made of.

Depends on leka.ingestion. Must not import leka.context or leka.intentions
(architecture rule 1).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import Literal

from leka.knowledge.models import Entity, EntityType, Relationship, RelationshipType
from leka.knowledge.repository import EntityRepository, Holding
from leka.knowledge.schemas import (
    CloudAccountDetail,
    CloudAccountRead,
    Criticality,
    Dependencies,
    DependencyNode,
    DependencyRead,
    EntityBrief,
    EntityRead,
    InfrastructureDetail,
    InfrastructureRead,
    LandscapeDetail,
    LandscapeRead,
    Neighbourhood,
    PartRead,
    RelationshipRead,
    ResourceEnvironment,
)

MAX_DEPTH = 3
MAX_ENTITIES = 200
# The dependency walk: how far, how many.
MAX_DEPENDENCY_DEPTH = 5
MAX_DEPENDENCIES = 500
# What a service's detail lists of its parts and dependencies.
MAX_LISTED = 200
AROUND = (
    RelationshipType.PART_OF,
    RelationshipType.OWNED_BY,
    RelationshipType.MAINTAINED_BY,
    RelationshipType.DEPENDS_ON,
)
# What a resource's row reads around it (LEKA-363).
PLACED = (
    RelationshipType.PART_OF,
    RelationshipType.OWNED_BY,
    RelationshipType.IN_NETWORK,
    RelationshipType.DEPENDS_ON,
)


class KnowledgeService:
    """Reads the company model for the modules that answer questions."""

    def __init__(self, entities: EntityRepository) -> None:
        self._entities = entities

    async def neighbourhood(
        self, entity_id: uuid.UUID, *, depth: int = 1, limit: int = MAX_ENTITIES
    ) -> Neighbourhood | None:
        """An entity and what surrounds it, `depth` steps away (at most
        three) — None when the workspace has no such entity."""
        found, edges = await self._entities.neighbourhood(
            entity_id, depth=min(max(depth, 1), MAX_DEPTH), limit=min(limit, MAX_ENTITIES)
        )
        root = next((entity for entity in found if entity.id == entity_id), None)
        if root is None:
            return None
        return Neighbourhood(
            root=EntityRead.model_validate(root),
            entities=[EntityRead.model_validate(e) for e in found if e.id != entity_id],
            relationships=[RelationshipRead.model_validate(r) for r in edges],
        )

    # ── the landscape (LEKA-362) ─────────────────────────────────────────────

    async def landscape(self, found: Sequence[Entity]) -> list[LandscapeRead]:
        """A page of services or applications, each with what the
        landscape says of it."""
        rows, _, _ = await self._landscape(found)
        return rows

    async def detail(self, entity: Entity) -> LandscapeDetail:
        """One service or application: what it is made of, what it depends
        on and what depends on it — the surest first, up to MAX_LISTED each."""
        [row], edges, others = await self._landscape([entity])
        parts = sorted(
            (
                e
                for e in edges
                if e.type is RelationshipType.PART_OF and e.to_entity_id == entity.id
            ),
            key=lambda e: -e.confidence,
        )[:MAX_LISTED]
        return LandscapeDetail(
            **row.model_dump(),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            parts=[
                PartRead(
                    entity=EntityBrief.model_validate(others[e.from_entity_id]),
                    environments=_environments(e),
                )
                for e in parts
                if e.from_entity_id in others
            ],
            depends_on=_dependencies(edges, others, entity.id, outgoing=True),
            depended_on_by=_dependencies(edges, others, entity.id, outgoing=False),
        )

    async def dependencies(
        self,
        entity_id: uuid.UUID,
        *,
        direction: Literal["downstream", "upstream"],
        depth: int,
        environment: str | None,
    ) -> Dependencies | None:
        """What an entity depends on, `depth` steps away at most — or what
        depends on it — in one environment or all. None when the workspace
        has no such entity."""
        depth = min(max(depth, 1), MAX_DEPENDENCY_DEPTH)
        reached, edges = await self._entities.dependencies(
            entity_id,
            downstream=direction == "downstream",
            depth=depth,
            environment=environment,
            limit=MAX_DEPENDENCIES + 1,
        )
        if entity_id not in reached:
            return None
        truncated = len(reached) > MAX_DEPENDENCIES
        kept = dict(list(reached.items())[:MAX_DEPENDENCIES])
        kept[entity_id] = 0
        found = await self._entities.by_ids(list(kept))
        return Dependencies(
            root=EntityBrief.model_validate(found[entity_id]),
            direction=direction,
            environment=environment,
            depth=depth,
            nodes=[
                DependencyNode(
                    entity=EntityBrief.model_validate(found[other]),
                    depth=distance,
                    criticality=_level(found[other]),
                )
                for other, distance in sorted(kept.items(), key=lambda item: item[1])
                if other != entity_id and other in found
            ],
            relationships=[
                RelationshipRead.model_validate(edge)
                for edge in edges
                if edge.from_entity_id in kept and edge.to_entity_id in kept
            ],
            truncated=truncated,
        )

    async def _landscape(
        self, found: Sequence[Entity]
    ) -> tuple[list[LandscapeRead], list[Relationship], dict[uuid.UUID, Entity]]:
        ids = [entity.id for entity in found]
        edges = list(await self._entities.around(ids, AROUND))
        ends = {e.from_entity_id for e in edges} | {e.to_entity_id for e in edges}
        others = await self._entities.by_ids(list(ends - set(ids)))
        others |= {entity.id: entity for entity in found}
        outgoing: dict[tuple[uuid.UUID, RelationshipType], list[Relationship]] = defaultdict(list)
        incoming: dict[tuple[uuid.UUID, RelationshipType], list[Relationship]] = defaultdict(list)
        for edge in edges:
            outgoing[(edge.from_entity_id, edge.type)].append(edge)
            incoming[(edge.to_entity_id, edge.type)].append(edge)

        def briefs(
            of: uuid.UUID, relation: RelationshipType, kind: EntityType
        ) -> list[EntityBrief]:
            targets = [others.get(e.to_entity_id) for e in outgoing[(of, relation)]]
            return sorted(
                (
                    EntityBrief.model_validate(t)
                    for t in targets
                    if t is not None and t.type is kind
                ),
                key=lambda brief: brief.name.lower(),
            )

        rows = []
        for entity in found:
            services = [
                e
                for e in incoming[(entity.id, RelationshipType.PART_OF)]
                if (other := others.get(e.from_entity_id)) and other.type is EntityType.SERVICE
            ]
            rows.append(
                LandscapeRead(
                    id=entity.id,
                    type=entity.type,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    stage=_text(entity.attributes.get("stage")),
                    criticality=_criticality(entity),
                    environments=_names(entity.attributes.get("environments"))
                    or _names([entity.attributes.get("environment")]),
                    applications=briefs(
                        entity.id, RelationshipType.PART_OF, EntityType.APPLICATION
                    ),
                    owners=briefs(entity.id, RelationshipType.OWNED_BY, EntityType.TEAM),
                    maintainers=briefs(
                        entity.id, RelationshipType.MAINTAINED_BY, EntityType.PERSON
                    ),
                    services=len(services),
                    dependencies=len(outgoing[(entity.id, RelationshipType.DEPENDS_ON)]),
                    dependents=len(incoming[(entity.id, RelationshipType.DEPENDS_ON)]),
                    last_seen_at=entity.last_seen_at,
                )
            )
        return rows, edges, others

    # ── infrastructure and cloud (LEKA-363) ──────────────────────────────────

    async def infrastructure(self, found: Sequence[Entity]) -> list[InfrastructureRead]:
        """A page of resources, each placed: its account and group, its
        services, team, network and cluster."""
        rows, _, _ = await self._infrastructure(found)
        return rows

    async def resource(self, entity: Entity) -> InfrastructureDetail:
        """One resource: its row, what it holds — a cluster's nodes, a
        network's resources — and its dependencies both ways."""
        [row], edges, others = await self._infrastructure([entity])
        holds, total = await self._entities.held(entity.id, limit=MAX_LISTED)
        return InfrastructureDetail(
            **row.model_dump(),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            holds=[EntityBrief.model_validate(e) for e in holds],
            holds_total=total,
            depends_on=_dependencies(edges, others, entity.id, outgoing=True),
            depended_on_by=_dependencies(edges, others, entity.id, outgoing=False),
        )

    async def cloud_accounts(self, found: Sequence[Entity]) -> list[CloudAccountRead]:
        """A page of accounts — or resource groups — each with how much is
        in it, of which class, in which regions, and whose it is."""
        ids = [entity.id for entity in found]
        holdings = await self._entities.holdings(ids)
        edges = list(
            await self._entities.around(ids, (RelationshipType.PART_OF, RelationshipType.OWNED_BY))
        )
        outgoing = [e for e in edges if e.from_entity_id in set(ids)]
        others = await self._entities.by_ids([e.to_entity_id for e in outgoing])
        rows = []
        for entity in found:
            held = [h for h in holdings if h.holder == entity.id]
            rows.append(
                CloudAccountRead(
                    id=entity.id,
                    type=entity.type,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    provider=_text(entity.attributes.get("provider")),
                    account_type=_text(entity.attributes.get("account_type")),
                    account_id=_text(entity.attributes.get("account_id")),
                    state=_text(entity.attributes.get("state")),
                    organization=_text(entity.attributes.get("organization"))
                    or _text(entity.attributes.get("tenant"))
                    or _text(entity.attributes.get("parent")),
                    parent=_one(
                        outgoing,
                        others,
                        entity.id,
                        RelationshipType.PART_OF,
                        EntityType.CLOUD_ACCOUNT,
                    ),
                    environment=_environment(entity),
                    criticality=_criticality(entity),
                    owners=_briefs(
                        outgoing, others, entity.id, RelationshipType.OWNED_BY, EntityType.TEAM
                    ),
                    resources=sum(h.count for h in held),
                    classes=_classes(held),
                    regions=sorted({h.region for h in held if h.region}),
                    last_seen_at=entity.last_seen_at,
                )
            )
        return rows

    async def cloud_account(self, entity: Entity) -> CloudAccountDetail:
        """One account, subscription, project or resource group: its row,
        and its resource groups with theirs."""
        [row] = await self.cloud_accounts([entity])
        groups = await self._entities.groups_of(entity.id)
        return CloudAccountDetail(
            **row.model_dump(),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            resource_groups=await self.cloud_accounts(groups) if groups else [],
        )

    async def _infrastructure(
        self, found: Sequence[Entity]
    ) -> tuple[list[InfrastructureRead], list[Relationship], dict[uuid.UUID, Entity]]:
        ids = [entity.id for entity in found]
        edges = list(await self._entities.around(ids, PLACED))
        ends = {e.from_entity_id for e in edges} | {e.to_entity_id for e in edges}
        others = await self._entities.by_ids(list(ends - set(ids)))
        others |= {entity.id: entity for entity in found}
        outgoing = [e for e in edges if e.from_entity_id in set(ids)]
        accounts = await self._subscriptions(outgoing, others)
        rows = []
        for entity in found:
            a = entity.attributes
            clusters = [
                b
                for b in _briefs(
                    outgoing, others, entity.id, RelationshipType.PART_OF, EntityType.INFRA_RESOURCE
                )
                if others[b.id].attributes.get("resource_kind") == "cluster"
            ]
            networks = _briefs(
                outgoing, others, entity.id, RelationshipType.IN_NETWORK, EntityType.INFRA_RESOURCE
            )
            rows.append(
                InfrastructureRead(
                    id=entity.id,
                    type=entity.type,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    provider=_text(a.get("provider")),
                    resource_kind=_text(a.get("resource_kind")),
                    resource_class=_text(a.get("resource_class")),
                    resource_type=_text(a.get("resource_type")),
                    state=_text(a.get("state")),
                    account=_one(
                        outgoing,
                        others,
                        entity.id,
                        RelationshipType.PART_OF,
                        EntityType.CLOUD_ACCOUNT,
                    )
                    or accounts.get(entity.id),
                    resource_group=_one(
                        outgoing,
                        others,
                        entity.id,
                        RelationshipType.PART_OF,
                        EntityType.RESOURCE_GROUP,
                    ),
                    region=_text(a.get("region")),
                    zone=_text(a.get("zone")),
                    environment=_environment(entity),
                    exposure=_text(a.get("exposure")),
                    criticality=_criticality(entity),
                    services=_briefs(
                        outgoing, others, entity.id, RelationshipType.PART_OF, EntityType.SERVICE
                    ),
                    applications=_briefs(
                        outgoing,
                        others,
                        entity.id,
                        RelationshipType.PART_OF,
                        EntityType.APPLICATION,
                    ),
                    owners=_briefs(
                        outgoing, others, entity.id, RelationshipType.OWNED_BY, EntityType.TEAM
                    ),
                    network=networks[0] if networks else None,
                    cluster=clusters[0] if clusters else None,
                    dependencies=sum(
                        1
                        for e in edges
                        if e.type is RelationshipType.DEPENDS_ON and e.from_entity_id == entity.id
                    ),
                    dependents=sum(
                        1
                        for e in edges
                        if e.type is RelationshipType.DEPENDS_ON and e.to_entity_id == entity.id
                    ),
                    last_seen_at=entity.last_seen_at,
                )
            )
        return rows, edges, others

    async def _subscriptions(
        self, outgoing: list[Relationship], others: dict[uuid.UUID, Entity]
    ) -> dict[uuid.UUID, EntityBrief]:
        """An Azure resource's subscription — its resource group's — by the
        resource's id."""
        groups = {
            e.from_entity_id: e.to_entity_id
            for e in outgoing
            if e.type is RelationshipType.PART_OF
            and (group := others.get(e.to_entity_id)) is not None
            and group.type is EntityType.RESOURCE_GROUP
        }
        if not groups:
            return {}
        above = [
            e
            for e in await self._entities.around(
                list(set(groups.values())), (RelationshipType.PART_OF,)
            )
            if e.from_entity_id in set(groups.values())
        ]
        parents = await self._entities.by_ids([e.to_entity_id for e in above])
        of_group = {
            e.from_entity_id: EntityBrief.model_validate(parents[e.to_entity_id])
            for e in above
            if e.to_entity_id in parents
            and parents[e.to_entity_id].type is EntityType.CLOUD_ACCOUNT
        }
        return {
            resource: of_group[group] for resource, group in groups.items() if group in of_group
        }


def _briefs(
    outgoing: list[Relationship],
    others: dict[uuid.UUID, Entity],
    of: uuid.UUID,
    relation: RelationshipType,
    kind: EntityType,
) -> list[EntityBrief]:
    """What an entity points at, of a kind, by name."""
    targets = [
        others.get(e.to_entity_id)
        for e in outgoing
        if e.from_entity_id == of and e.type is relation
    ]
    return sorted(
        (EntityBrief.model_validate(t) for t in targets if t is not None and t.type is kind),
        key=lambda brief: brief.name.lower(),
    )


def _one(
    outgoing: list[Relationship],
    others: dict[uuid.UUID, Entity],
    of: uuid.UUID,
    relation: RelationshipType,
    kind: EntityType,
) -> EntityBrief | None:
    found = _briefs(outgoing, others, of, relation, kind)
    return found[0] if found else None


def _classes(held: list[Holding]) -> dict[str, int]:
    classes: dict[str, int] = defaultdict(int)
    for holding in held:
        classes[holding.resource_class or "other"] += holding.count
    return dict(sorted(classes.items()))


def _environment(entity: Entity) -> ResourceEnvironment | None:
    """Where it runs, and who says so: a source — a tag, a name, a CMDB — or
    enrichment, from what it is in."""
    name = _text(entity.attributes.get("environment"))
    if name is None:
        return None
    origins = entity.provenance.get("attributes")
    origin = origins.get("environment") if isinstance(origins, dict) else None
    said = origin if isinstance(origin, dict) else {}
    confidence = said.get("confidence", entity.attributes.get("environment_confidence"))
    return ResourceEnvironment(
        name=name,
        origin=str(said.get("origin") or "source"),
        confidence=float(confidence) if isinstance(confidence, int | float) else None,
    )


def _criticality(entity: Entity) -> Criticality | None:
    """How critical, and who says so: a source (a catalogue, a tag) or
    enrichment (its parts)."""
    level = _text(entity.attributes.get("criticality"))
    if level is None:
        return None
    origins = entity.provenance.get("attributes")
    origin = origins.get("criticality") if isinstance(origins, dict) else None
    said = origin if isinstance(origin, dict) else {}
    confidence = said.get("confidence", entity.attributes.get("criticality_confidence"))
    return Criticality(
        level=level,
        origin=str(said.get("origin") or "source"),
        confidence=float(confidence) if isinstance(confidence, int | float) else None,
        raw=_text(entity.attributes.get("criticality_raw")),
    )


def _level(entity: Entity) -> str | None:
    return _text(entity.attributes.get("criticality"))


def _dependencies(
    edges: list[Relationship],
    others: dict[uuid.UUID, Entity],
    entity_id: uuid.UUID,
    *,
    outgoing: bool,
) -> list[DependencyRead]:
    found = [
        e
        for e in edges
        if e.type is RelationshipType.DEPENDS_ON
        and (e.from_entity_id if outgoing else e.to_entity_id) == entity_id
    ]
    found.sort(key=lambda e: -e.confidence)
    listed = []
    for edge in found[:MAX_LISTED]:
        other = others.get(edge.to_entity_id if outgoing else edge.from_entity_id)
        if other is None:
            continue
        listed.append(
            DependencyRead(
                entity=EntityBrief.model_validate(other),
                confidence=edge.confidence,
                origin=edge.origin,
                environments=_environments(edge),
            )
        )
    return listed


def _environments(edge: Relationship) -> list[str]:
    return _names((edge.attributes or {}).get("environments"))


def _names(value: object) -> list[str]:
    return [str(v) for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
