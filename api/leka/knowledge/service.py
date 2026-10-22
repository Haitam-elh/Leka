"""Business logic over the company model.

What leka.context and leka.intentions ask of the graph: an entity, its
neighbourhood, its history; the landscape of applications and services,
and what depends on what (LEKA-362); the infrastructure — its resources,
the accounts they are in, where and whose each is (LEKA-363); the data —
databases, schemas, tables — what each holds and what it is tied to
(LEKA-364); the organisation — teams, people, who owns and operates what,
who knows it (LEKA-365); the documentation — where it is kept, how fresh,
what it covers — and the business — its capabilities and processes, what
supports them, what a technical thing means to them (LEKA-366); what
happens — incidents, changes, deployments, their timelines, what changed
before an incident and what it reaches (LEKA-367). The
registry (registry.py) is what they read to know what kinds of things a
company is made of.

Depends on leka.ingestion. Must not import leka.context or leka.intentions
(architecture rule 1).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from leka.knowledge.models import (
    Entity,
    EntityType,
    Lifecycle,
    Relationship,
    RelationshipChange,
    RelationshipIssue,
    RelationshipType,
)
from leka.knowledge.repository import BUSINESS, DOCUMENTED, EntityRepository, Holding
from leka.knowledge.schemas import (
    BusinessContext,
    BusinessDetail,
    BusinessPart,
    BusinessRead,
    BusinessTie,
    ChangeDetail,
    ChangeRead,
    CloudAccountDetail,
    CloudAccountRead,
    ColumnRead,
    CoverageRead,
    Criticality,
    DatabaseDetail,
    DatabaseRead,
    DataObjectDetail,
    DataObjectRead,
    Dependencies,
    DependencyNode,
    DependencyRead,
    DeploymentDetail,
    DeploymentRead,
    DocumentationCoverage,
    DocumentationGap,
    DocumentDetail,
    DocumentRead,
    EntityBrief,
    EntityRead,
    Expertise,
    GraphRelationshipRead,
    Holds,
    Impact,
    IncidentDetail,
    IncidentRead,
    InfrastructureDetail,
    InfrastructureRead,
    KnowledgeSpaceDetail,
    KnowledgeSpaceRead,
    LandscapeDetail,
    LandscapeRead,
    Neighbourhood,
    PartRead,
    PersonDetail,
    PersonRead,
    RelationshipChangeRead,
    RelationshipIssueRead,
    RelationshipRead,
    ResourceEnvironment,
    Responsibility,
    SchemaRead,
    TeamDetail,
    TeamRead,
    Tie,
    Ties,
    Timeline,
    TimelineEvent,
    TimelineStep,
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
# A data object's lineage: its foreign keys, what views read (LEKA-364).
LINEAGE = (RelationshipType.REFERENCES, RelationshipType.READS_FROM)
# The organisation (LEKA-365): what a team's and a person's rows read
# around them; how far a chain of managers or parents goes.
ORGANISATION = (
    RelationshipType.MEMBER_OF,
    RelationshipType.LED_BY,
    RelationshipType.CHILD_OF,
    RelationshipType.REPORTS_TO,
    RelationshipType.MAINTAINED_BY,
    RelationshipType.OWNED_BY,
    RelationshipType.CONTRIBUTES_TO,
)
MAX_CHAIN = 10
MAX_EXPERTS = 10
SHOWN_EXPERTISE = 3
# What a data object's row reads around it.
DATA_AROUND = (RelationshipType.PART_OF, RelationshipType.OWNED_BY, *LINEAGE)
# Documentation and business knowledge (LEKA-366): what a document's, a
# space's, a capability's or a process's row reads around it — and a
# capability's parts; what documents; what documentation covers.
DOCUMENTED_AROUND = (
    RelationshipType.PART_OF,
    RelationshipType.CHILD_OF,
    RelationshipType.AUTHORED_BY,
    RelationshipType.EDITED_BY,
    RelationshipType.OWNED_BY,
    RelationshipType.DESCRIBES,
    RelationshipType.REFERENCES,
    RelationshipType.MENTIONS,
)
SPACE_AROUND = (
    RelationshipType.OWNED_BY,
    RelationshipType.DESCRIBES,
    RelationshipType.MAINTAINED_BY,
)
BUSINESS_AROUND = (
    RelationshipType.CHILD_OF,
    RelationshipType.PART_OF,
    RelationshipType.REALIZES,
    RelationshipType.SUPPORTED_BY,
    RelationshipType.USES,
    RelationshipType.OWNED_BY,
    RelationshipType.DESCRIBES,
)
PART_AROUND = (
    RelationshipType.SUPPORTED_BY,
    RelationshipType.USES,
    RelationshipType.OWNED_BY,
)
DOCUMENTATION = (EntityType.DOCUMENT, EntityType.KNOWLEDGE_SPACE)
FRESHNESS = ("fresh", "aging", "stale", "unknown")
SHOWN_DOCUMENTS = 10
# A technical thing's business context: what holds it — a table's service,
# a service's application — and what depends on it, this many steps.
TECHNICAL = frozenset(
    {
        EntityType.SERVICE,
        EntityType.APPLICATION,
        EntityType.REPOSITORY,
        EntityType.DATABASE,
        EntityType.SCHEMA,
        EntityType.DATA_OBJECT,
        EntityType.INFRA_RESOURCE,
    }
)
MAX_HOLDERS = 3
PATHS = ("direct", "contained", "dependent")
# Incidents, changes, deployments (LEKA-367): what each row reads around
# it; the dates of an incident's and a change's life, in its words; what
# changed before an incident is looked for this long before it, around
# what it affects; how far what depends on it is followed.
INCIDENT_AROUND = (
    RelationshipType.AFFECTS,
    RelationshipType.LED_BY,
    RelationshipType.ASSIGNED_TO,
    RelationshipType.REPORTED_BY,
    RelationshipType.CAUSED_BY,
)
DEPLOYMENT_AROUND = (
    RelationshipType.PART_OF,
    RelationshipType.DEPLOYS,
    RelationshipType.DEPLOYED_TO,
    RelationshipType.REPORTED_BY,
    RelationshipType.CAUSED_BY,
)
CHANGE_AROUND = (
    RelationshipType.AFFECTS,
    RelationshipType.ASSIGNED_TO,
    RelationshipType.REPORTED_BY,
    RelationshipType.CAUSED_BY,
)
INCIDENT_STEPS = (
    ("created_at", "opened"),
    ("detected_at", "detected"),
    ("acknowledged_at", "acknowledged"),
    ("resolved_at", "resolved"),
    ("closed_at", "closed"),
)
CHANGE_STEPS = (
    ("created_at", "opened"),
    ("planned_start_at", "planned_start"),
    ("planned_end_at", "planned_end"),
    ("started_at", "started"),
    ("finished_at", "finished"),
)
CHANGE_KINDS = (
    EntityType.DEPLOYMENT,
    EntityType.CHANGE,
    EntityType.RELEASE,
    EntityType.PULL_REQUEST,
)
KIND_EVENTS = {
    EntityType.DEPLOYMENT: "deployment",
    EntityType.CHANGE: "change",
    EntityType.RELEASE: "release",
    EntityType.PULL_REQUEST: "merge",
}
CHANGED_BEFORE = timedelta(hours=72)
MAX_SCOPE = 2
IMPACT_DEPTH = 2
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

    async def attributes(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[str, object]]:
        """Each thing's attributes, as the model holds them — what an agent
        reads of it beside its name (2026-10-22)."""
        found = await self._entities.by_ids(list(ids))
        return {key: dict(entity.attributes) for key, entity in found.items()}

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
        lineage: bool = False,
        through: Sequence[RelationshipType] = (RelationshipType.DEPENDS_ON,),
    ) -> Dependencies | None:
        """What an entity depends on, `depth` steps away at most — or what
        depends on it — in one environment or all. None when the workspace
        has no such entity.

        A data object's LINEAGE (LEKA-364) walks its foreign keys and what
        views read instead, in data's words: upstream, what it reads from
        and references; downstream, what reads from or references it.

        `through`: the dependency relationships followed (LEKA-368) —
        `depends_on` alone unless asked."""
        depth = min(max(depth, 1), MAX_DEPENDENCY_DEPTH)
        reached, edges = await self._entities.dependencies(
            entity_id,
            downstream=(direction == "upstream") if lineage else (direction == "downstream"),
            depth=depth,
            environment=environment,
            limit=MAX_DEPENDENCIES + 1,
            types=LINEAGE if lineage else tuple(through),
        )
        if entity_id not in reached:
            return None
        truncated = len(reached) > MAX_DEPENDENCIES
        kept = dict(list(reached.items())[:MAX_DEPENDENCIES])
        kept[entity_id] = 0
        found = await self._entities.by_ids(list(kept))
        if entity_id not in found:
            # Hidden from whoever asks (LEKA-402): as if there were none.
            return None
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

    # ── people and teams (LEKA-365) ──────────────────────────────────────────

    async def _around(
        self, found: Sequence[Entity]
    ) -> tuple[list[Relationship], dict[uuid.UUID, Entity]]:
        """The organisation's relationships of these entities, and every end
        of them — these included: a manager, a parent team on the same page."""
        ids = [entity.id for entity in found]
        edges = list(await self._entities.around(ids, ORGANISATION))
        ends = {e.from_entity_id for e in edges} | {e.to_entity_id for e in edges}
        others = await self._entities.by_ids(list(ends - set(ids)))
        return edges, others | {entity.id: entity for entity in found}

    async def teams(self, found: Sequence[Entity]) -> list[TeamRead]:
        """A page of teams: their parent, how many sub-teams and members,
        who leads them, what they own."""
        rows, _, _ = await self._teams(found)
        return rows

    async def team(self, entity: Entity) -> TeamDetail:
        """One team: its parents up to the top, its sub-teams, its members —
        said or inferred — and what it owns, the surest first."""
        [row], edges, others = await self._teams([entity])
        alive = {k: v for k, v in others.items() if v.lifecycle is not Lifecycle.REMOVED}
        members = sorted(
            (
                _tie(e, alive[e.from_entity_id])
                for e in edges
                if e.type is RelationshipType.MEMBER_OF
                and e.to_entity_id == entity.id
                and e.from_entity_id in alive
            ),
            key=lambda tie: (tie.origin != "stated", -tie.confidence, tie.entity.name.lower()),
        )
        owned = sorted(
            (
                _tie(e, alive[e.from_entity_id])
                for e in edges
                if e.type is RelationshipType.OWNED_BY
                and e.to_entity_id == entity.id
                and e.from_entity_id in alive
            ),
            key=lambda tie: (tie.origin != "stated", -tie.confidence, tie.entity.name.lower()),
        )[:MAX_LISTED]
        sub_teams = sorted(
            (
                EntityBrief.model_validate(alive[e.from_entity_id])
                for e in edges
                if e.type is RelationshipType.CHILD_OF
                and e.to_entity_id == entity.id
                and e.from_entity_id in alive
                and alive[e.from_entity_id].type is EntityType.TEAM
            ),
            key=lambda brief: brief.name.lower(),
        )
        ancestors = await self._entities.chain(
            entity.id, RelationshipType.CHILD_OF, limit=MAX_CHAIN
        )
        return TeamDetail(
            **row.model_dump(),
            description=_text(entity.attributes.get("description")),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            ancestors=[EntityBrief.model_validate(a) for a in ancestors],
            sub_teams=sub_teams,
            members=members,
            owned=owned,
        )

    async def _teams(
        self, found: Sequence[Entity]
    ) -> tuple[list[TeamRead], list[Relationship], dict[uuid.UUID, Entity]]:
        ids = [entity.id for entity in found]
        edges, others = await self._around(found)
        owns = await self._entities.owned_counts(ids)
        rows = []
        for entity in found:
            members = [
                e
                for e in edges
                if e.type is RelationshipType.MEMBER_OF
                and e.to_entity_id == entity.id
                and (p := others.get(e.from_entity_id)) is not None
                and p.lifecycle is not Lifecycle.REMOVED
            ]
            parents = [
                others[e.to_entity_id]
                for e in edges
                if e.type is RelationshipType.CHILD_OF
                and e.from_entity_id == entity.id
                and e.to_entity_id in others
                and others[e.to_entity_id].type is EntityType.TEAM
            ]
            rows.append(
                TeamRead(
                    id=entity.id,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    team_type=_text(entity.attributes.get("team_type")),
                    parent=EntityBrief.model_validate(parents[0]) if parents else None,
                    sub_team_count=sum(
                        1
                        for e in edges
                        if e.type is RelationshipType.CHILD_OF
                        and e.to_entity_id == entity.id
                        and (t := others.get(e.from_entity_id)) is not None
                        and t.type is EntityType.TEAM
                    ),
                    member_count=sum(1 for e in members if e.origin == "stated"),
                    inferred_member_count=sum(1 for e in members if e.origin != "stated"),
                    leads=sorted(
                        (
                            EntityBrief.model_validate(others[e.to_entity_id])
                            for e in edges
                            if e.type is RelationshipType.LED_BY
                            and e.from_entity_id == entity.id
                            and e.to_entity_id in others
                        ),
                        key=lambda brief: brief.name.lower(),
                    ),
                    owns=dict(sorted(owns.get(entity.id, {}).items())),
                )
            )
        return rows, edges, others

    async def people(self, found: Sequence[Entity]) -> list[PersonRead]:
        """A page of people: their teams, their manager, how many report to
        them, what they maintain, what their work shows they know."""
        rows, _, _ = await self._people(found)
        return rows

    async def person(self, entity: Entity) -> PersonDetail:
        """One person: their teams — said or inferred — their managers up to
        the top, their reports, what they maintain and own, everything their
        work shows they know."""
        [row], edges, others = await self._people([entity])

        def ties(relation: RelationshipType, *, outgoing: bool) -> list[Tie]:
            found = [
                _tie(e, others[e.to_entity_id if outgoing else e.from_entity_id])
                for e in edges
                if e.type is relation
                and (e.from_entity_id if outgoing else e.to_entity_id) == entity.id
                and (e.to_entity_id if outgoing else e.from_entity_id) in others
            ]
            return sorted(found, key=lambda tie: (tie.origin != "stated", -tie.confidence))

        managers = await self._entities.chain(
            entity.id, RelationshipType.REPORTS_TO, limit=MAX_CHAIN
        )
        return PersonDetail(
            **row.model_dump(),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            memberships=ties(RelationshipType.MEMBER_OF, outgoing=True),
            managers=[EntityBrief.model_validate(m) for m in managers],
            reports=sorted(
                (t.entity for t in ties(RelationshipType.REPORTS_TO, outgoing=False)),
                key=lambda brief: brief.name.lower(),
            ),
            maintained=ties(RelationshipType.MAINTAINED_BY, outgoing=False),
            owned=[t.entity for t in ties(RelationshipType.OWNED_BY, outgoing=False)],
            contributions=ties(RelationshipType.CONTRIBUTES_TO, outgoing=True),
            all_expertise=_expertise(entity),
        )

    async def _people(
        self, found: Sequence[Entity]
    ) -> tuple[list[PersonRead], list[Relationship], dict[uuid.UUID, Entity]]:
        edges, others = await self._around(found)
        rows = []
        for entity in found:
            a = entity.attributes
            teams = sorted(
                (
                    EntityBrief.model_validate(others[e.to_entity_id])
                    for e in edges
                    if e.type is RelationshipType.MEMBER_OF
                    and e.from_entity_id == entity.id
                    and e.to_entity_id in others
                ),
                key=lambda brief: brief.name.lower(),
            )
            managers = sorted(
                (
                    e
                    for e in edges
                    if e.type is RelationshipType.REPORTS_TO
                    and e.from_entity_id == entity.id
                    and e.to_entity_id in others
                ),
                key=lambda e: -e.confidence,
            )
            active = a.get("active")
            languages = a.get("languages")
            rows.append(
                PersonRead(
                    id=entity.id,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    email=_text(a.get("email")) or _email_of(entity.key),
                    job_title=_text(a.get("job_title")),
                    department=_text(a.get("department")),
                    active=active if isinstance(active, bool) else None,
                    bot=a.get("bot") is True,
                    teams=teams,
                    manager=EntityBrief.model_validate(others[managers[0].to_entity_id])
                    if managers
                    else None,
                    report_count=sum(
                        1
                        for e in edges
                        if e.type is RelationshipType.REPORTS_TO and e.to_entity_id == entity.id
                    ),
                    maintains=sum(
                        1
                        for e in edges
                        if e.type is RelationshipType.MAINTAINED_BY and e.to_entity_id == entity.id
                    ),
                    expertise=_expertise(entity)[:SHOWN_EXPERTISE],
                    languages=[str(x) for x in languages] if isinstance(languages, list) else [],
                    last_activity_at=_text(a.get("last_activity_at")),
                )
            )
        return rows, edges, others

    async def responsibility(self, entity: Entity) -> Responsibility:
        """Who owns a thing — its teams, said or inherited — who leads them,
        who maintains it, whose work shows they know it."""
        edges, others = await self._around([entity])
        alive = {k: v for k, v in others.items() if v.lifecycle is not Lifecycle.REMOVED}

        def ties(relation: RelationshipType, *, outgoing: bool) -> list[Tie]:
            found = [
                _tie(e, alive[e.to_entity_id if outgoing else e.from_entity_id])
                for e in edges
                if e.type is relation
                and (e.from_entity_id if outgoing else e.to_entity_id) == entity.id
                and (e.to_entity_id if outgoing else e.from_entity_id) in alive
            ]
            return sorted(found, key=lambda tie: (tie.origin != "stated", -tie.confidence))

        owners = ties(RelationshipType.OWNED_BY, outgoing=True)
        teams = [t.entity.id for t in owners if t.entity.type is EntityType.TEAM]
        lead_edges = [
            e
            for e in await self._entities.around(teams, (RelationshipType.LED_BY,))
            if e.from_entity_id in set(teams)
        ]
        leads = await self._entities.by_ids([e.to_entity_id for e in lead_edges])
        return Responsibility(
            entity=EntityBrief.model_validate(entity),
            owners=owners,
            leads=sorted(
                (EntityBrief.model_validate(p) for p in leads.values()),
                key=lambda brief: brief.name.lower(),
            ),
            maintainers=ties(RelationshipType.MAINTAINED_BY, outgoing=True),
            experts=ties(RelationshipType.CONTRIBUTES_TO, outgoing=False)[:MAX_EXPERTS],
            escalation_policy=_text(entity.attributes.get("escalation_policy")),
        )

    # ── data (LEKA-364) ──────────────────────────────────────────────────────

    async def databases(self, found: Sequence[Entity]) -> list[DatabaseRead]:
        """A page of databases, each with what it holds and where it is."""
        ids = [entity.id for entity in found]
        edges = list(
            await self._entities.around(ids, (RelationshipType.PART_OF, RelationshipType.OWNED_BY))
        )
        outgoing = [e for e in edges if e.from_entity_id in set(ids)]
        others = await self._entities.by_ids([e.to_entity_id for e in outgoing])
        schemas = await self._entities.parts(ids, EntityType.SCHEMA)
        objects = await self._entities.parts(
            [s.id for held in schemas.values() for s in held], EntityType.DATA_OBJECT
        )
        rows = []
        for entity in found:
            a = entity.attributes
            instances = _briefs(
                outgoing, others, entity.id, RelationshipType.PART_OF, EntityType.DATABASE
            )
            port = a.get("port")
            rows.append(
                DatabaseRead(
                    id=entity.id,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    engine=_text(a.get("engine")),
                    host=_text(a.get("host")) or _text(a.get("endpoint")),
                    port=port if isinstance(port, int) else None,
                    database_name=_text(a.get("database_name")),
                    provider=_text(a.get("provider")),
                    instance=instances[0] if instances else None,
                    schema_count=len(schemas.get(entity.id, [])),
                    object_count=sum(
                        len(objects.get(s.id, [])) for s in schemas.get(entity.id, [])
                    ),
                    holds=_holds(entity),
                    environment=_environment(entity),
                    owners=_briefs(
                        outgoing, others, entity.id, RelationshipType.OWNED_BY, EntityType.TEAM
                    ),
                    services=_briefs(
                        outgoing, others, entity.id, RelationshipType.PART_OF, EntityType.SERVICE
                    ),
                    last_seen_at=entity.last_seen_at,
                )
            )
        return rows

    async def database(self, entity: Entity) -> DatabaseDetail:
        """One database: its row, its schemas with theirs, the databases it
        serves when it is an instance."""
        [row] = await self.databases([entity])
        schemas = (await self._entities.parts([entity.id], EntityType.SCHEMA))[entity.id]
        serves = (await self._entities.parts([entity.id], EntityType.DATABASE))[entity.id]
        return DatabaseDetail(
            **row.model_dump(),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            schemas=await self._schemas(schemas),
            serves=[EntityBrief.model_validate(d) for d in serves],
        )

    async def _schemas(self, found: Sequence[Entity]) -> list[SchemaRead]:
        ids = [entity.id for entity in found]
        objects = await self._entities.parts(ids, EntityType.DATA_OBJECT)
        edges = list(
            await self._entities.around(ids, (RelationshipType.PART_OF, RelationshipType.OWNED_BY))
        )
        outgoing = [e for e in edges if e.from_entity_id in set(ids)]
        others = await self._entities.by_ids([e.to_entity_id for e in outgoing])
        rows = []
        for entity in found:
            held = objects.get(entity.id, [])
            kinds: dict[str, int] = defaultdict(int)
            for item in held:
                kinds[_text(item.attributes.get("object_kind")) or "table"] += 1
            rows.append(
                SchemaRead(
                    id=entity.id,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    object_count=len(held),
                    kinds=dict(sorted(kinds.items())),
                    holds=_holds(entity),
                    owners=_briefs(
                        outgoing, others, entity.id, RelationshipType.OWNED_BY, EntityType.TEAM
                    ),
                    services=_briefs(
                        outgoing, others, entity.id, RelationshipType.PART_OF, EntityType.SERVICE
                    ),
                )
            )
        return rows

    async def data_objects(self, found: Sequence[Entity]) -> list[DataObjectRead]:
        """A page of tables, views and collections: where each is, what it
        holds, how it is tied to the others."""
        rows, _, _ = await self._data_objects(found)
        return rows

    async def data_object(self, entity: Entity) -> DataObjectDetail:
        """One data object: its row, its columns, and what it is tied to —
        each way."""
        [row], edges, others = await self._data_objects([entity])
        a = entity.attributes
        found = a.get("column_categories")
        categories = found if isinstance(found, dict) else {}
        key = a.get("primary_key")
        primary = {str(c) for c in key} if isinstance(key, list) else set()
        listed = a.get("columns")
        names = [str(name) for name in listed] if isinstance(listed, list) else []

        def tied(relation: RelationshipType, *, outgoing: bool) -> list[EntityBrief]:
            ends = [
                others.get(e.to_entity_id if outgoing else e.from_entity_id)
                for e in edges
                if e.type is relation
                and (e.from_entity_id if outgoing else e.to_entity_id) == entity.id
            ]
            return sorted(
                (EntityBrief.model_validate(end) for end in ends if end is not None),
                key=lambda brief: brief.name.lower(),
            )

        return DataObjectDetail(
            **row.model_dump(),
            description=_text(a.get("description")),
            columns=[
                ColumnRead(
                    name=name,
                    category=_text(categories.get(name)),
                    primary_key=name in primary,
                )
                for name in names
            ],
            attributes=dict(a),
            provenance=dict(entity.provenance),
            references=tied(RelationshipType.REFERENCES, outgoing=True),
            referenced_by=tied(RelationshipType.REFERENCES, outgoing=False),
            reads_from=tied(RelationshipType.READS_FROM, outgoing=True),
            read_by=tied(RelationshipType.READS_FROM, outgoing=False),
        )

    async def _data_objects(
        self, found: Sequence[Entity]
    ) -> tuple[list[DataObjectRead], list[Relationship], dict[uuid.UUID, Entity]]:
        ids = [entity.id for entity in found]
        edges = list(await self._entities.around(ids, DATA_AROUND))
        ends = {e.from_entity_id for e in edges} | {e.to_entity_id for e in edges}
        others = await self._entities.by_ids(list(ends - set(ids)))
        others |= {entity.id: entity for entity in found}
        outgoing = [e for e in edges if e.from_entity_id in set(ids)]
        schemas = {
            e.from_entity_id: e.to_entity_id
            for e in outgoing
            if e.type is RelationshipType.PART_OF
            and (s := others.get(e.to_entity_id)) is not None
            and s.type is EntityType.SCHEMA
        }
        above = [
            e
            for e in await self._entities.around(
                list(set(schemas.values())), (RelationshipType.PART_OF,)
            )
            if e.from_entity_id in set(schemas.values())
        ]
        databases = await self._entities.by_ids([e.to_entity_id for e in above])
        of_schema = {
            e.from_entity_id: EntityBrief.model_validate(databases[e.to_entity_id])
            for e in above
            if e.to_entity_id in databases and databases[e.to_entity_id].type is EntityType.DATABASE
        }

        def count(of: uuid.UUID, relation: RelationshipType, *, outgoing: bool) -> int:
            return sum(
                1
                for e in edges
                if e.type is relation and (e.from_entity_id if outgoing else e.to_entity_id) == of
            )

        rows = []
        for entity in found:
            a = entity.attributes
            columns = a.get("columns")
            rows_, size = a.get("estimated_rows"), a.get("size_bytes")
            schema = schemas.get(entity.id)
            rows.append(
                DataObjectRead(
                    id=entity.id,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    object_kind=_text(a.get("object_kind")),
                    engine=_text(a.get("engine")),
                    database=of_schema.get(schema) if schema else None,
                    schema_name=_text(a.get("schema_name")),
                    container=EntityBrief.model_validate(others[schema]) if schema else None,
                    column_count=len(columns) if isinstance(columns, list) else 0,
                    estimated_rows=rows_ if isinstance(rows_, int) else None,
                    size_bytes=size if isinstance(size, int) else None,
                    holds=_holds(entity),
                    owners=_briefs(
                        outgoing, others, entity.id, RelationshipType.OWNED_BY, EntityType.TEAM
                    ),
                    services=_briefs(
                        outgoing, others, entity.id, RelationshipType.PART_OF, EntityType.SERVICE
                    ),
                    ties=Ties(
                        references=count(entity.id, RelationshipType.REFERENCES, outgoing=True),
                        referenced_by=count(entity.id, RelationshipType.REFERENCES, outgoing=False),
                        reads_from=count(entity.id, RelationshipType.READS_FROM, outgoing=True),
                        read_by=count(entity.id, RelationshipType.READS_FROM, outgoing=False),
                    ),
                    last_seen_at=entity.last_seen_at,
                )
            )
        return rows, edges, others

    # ── documentation and business knowledge (LEKA-366) ──────────────────────

    async def _ends(
        self, found: Sequence[Entity], types: Sequence[RelationshipType]
    ) -> tuple[list[Relationship], dict[uuid.UUID, Entity]]:
        """The relationships of these types of these entities, and every end
        of them — these included — the removed left out."""
        ids = [entity.id for entity in found]
        edges = list(await self._entities.around(ids, types))
        ends = {e.from_entity_id for e in edges} | {e.to_entity_id for e in edges}
        others = await self._entities.by_ids(list(ends - set(ids)))
        alive = {k: v for k, v in others.items() if v.lifecycle is not Lifecycle.REMOVED}
        return edges, alive | {entity.id: entity for entity in found}

    async def documents(self, found: Sequence[Entity]) -> list[DocumentRead]:
        """A page of documents: where each is kept, who wrote it and last
        changed it, how fresh, whose, what it describes."""
        rows, _, _ = await self._documents(found)
        return rows

    async def document(self, entity: Entity) -> DocumentDetail:
        """One document: its pages above and below, and everything it is
        tied to — each said or inferred, how surely."""
        [row], edges, others = await self._documents([entity])
        ancestors = await self._entities.chain(
            entity.id, RelationshipType.CHILD_OF, limit=MAX_CHAIN
        )
        children = sorted(
            (
                EntityBrief.model_validate(others[e.from_entity_id])
                for e in edges
                if e.type is RelationshipType.CHILD_OF
                and e.to_entity_id == entity.id
                and e.from_entity_id in others
            ),
            key=lambda brief: brief.name.lower(),
        )
        ties = _ties(edges, others, entity.id)
        return DocumentDetail(
            **row.model_dump(),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            verification_due_at=_text(entity.attributes.get("verification_due_at")),
            ancestors=[EntityBrief.model_validate(a) for a in ancestors],
            children=children[:MAX_LISTED],
            descriptions=ties(RelationshipType.DESCRIBES, outgoing=True),
            ownership=ties(RelationshipType.OWNED_BY, outgoing=True),
            written_by=ties(RelationshipType.AUTHORED_BY, outgoing=True),
            edited_by=ties(RelationshipType.EDITED_BY, outgoing=True),
            links_to=ties(RelationshipType.REFERENCES, outgoing=True),
            linked_from=ties(RelationshipType.REFERENCES, outgoing=False),
            mentions=ties(RelationshipType.MENTIONS, outgoing=True),
        )

    async def _documents(
        self, found: Sequence[Entity]
    ) -> tuple[list[DocumentRead], list[Relationship], dict[uuid.UUID, Entity]]:
        edges, others = await self._ends(found, DOCUMENTED_AROUND)
        rows = []
        for entity in found:
            out = _out(edges, others, entity.id)
            a = entity.attributes
            verified = a.get("verified")
            editors = out(RelationshipType.EDITED_BY)
            rows.append(
                DocumentRead(
                    id=entity.id,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    url=_text(a.get("url")),
                    tools=_tools(entity),
                    document_kind=_text(a.get("document_kind")),
                    space=next(
                        (
                            b
                            for b in out(RelationshipType.PART_OF)
                            if b.type is EntityType.KNOWLEDGE_SPACE
                        ),
                        None,
                    ),
                    freshness=_text(a.get("freshness")),
                    last_changed_at=_text(a.get("last_activity_at")),
                    verified=verified if isinstance(verified, bool) else None,
                    authors=out(RelationshipType.AUTHORED_BY),
                    last_editor=editors[0] if editors else None,
                    owners=out(RelationshipType.OWNED_BY),
                    describes=out(RelationshipType.DESCRIBES),
                )
            )
        return rows, edges, others

    async def spaces(self, found: Sequence[Entity]) -> list[KnowledgeSpaceRead]:
        """A page of spaces: how many documents each holds, how fresh, whose,
        what it documents, who writes it most."""
        rows, _, _ = await self._spaces(found)
        return rows

    async def space(self, entity: Entity) -> KnowledgeSpaceDetail:
        """One space: everything it is tied to, its latest documents and its
        stalest."""
        [row], edges, others = await self._spaces([entity])
        ties = _ties(edges, others, entity.id)
        recent = await self._entities.documents_of(entity.id, stale=False, limit=SHOWN_DOCUMENTS)
        stalest = await self._entities.documents_of(entity.id, stale=True, limit=SHOWN_DOCUMENTS)
        return KnowledgeSpaceDetail(
            **row.model_dump(),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            ownership=ties(RelationshipType.OWNED_BY, outgoing=True),
            descriptions=ties(RelationshipType.DESCRIBES, outgoing=True),
            maintained_by=ties(RelationshipType.MAINTAINED_BY, outgoing=True),
            recent=[EntityBrief.model_validate(d) for d in recent],
            stalest=[EntityBrief.model_validate(d) for d in stalest],
        )

    async def _spaces(
        self, found: Sequence[Entity]
    ) -> tuple[list[KnowledgeSpaceRead], list[Relationship], dict[uuid.UUID, Entity]]:
        edges, others = await self._ends(found, SPACE_AROUND)
        held = await self._entities.space_documents([entity.id for entity in found])
        rows = []
        for entity in found:
            out = _out(edges, others, entity.id)
            a = entity.attributes
            counts = held.get(entity.id, {})
            rows.append(
                KnowledgeSpaceRead(
                    id=entity.id,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    url=_text(a.get("url")),
                    tools=_tools(entity),
                    space_kind=_text(a.get("space_kind")),
                    description=_text(a.get("description")),
                    document_count=sum(counts.values()),
                    freshness={w: counts[w] for w in FRESHNESS if w in counts},
                    last_changed_at=_text(a.get("last_activity_at")),
                    owners=out(RelationshipType.OWNED_BY),
                    describes=out(RelationshipType.DESCRIBES),
                    maintainers=out(RelationshipType.MAINTAINED_BY),
                )
            )
        return rows, edges, others

    async def coverage(self) -> DocumentationCoverage:
        """How much documentation there is, how fresh, and how much of the
        company it covers — kind by kind."""
        counts = await self._entities.coverage()
        by_freshness, unverified, spaces = await self._entities.documentation_counts()
        return DocumentationCoverage(
            documents=sum(by_freshness.values()),
            spaces=spaces,
            freshness=by_freshness,
            unverified=unverified,
            coverage=[
                CoverageRead(
                    type=kind,
                    total=counts.get(kind, (0, 0, 0))[0],
                    documented=counts.get(kind, (0, 0, 0))[1],
                    fresh=counts.get(kind, (0, 0, 0))[2],
                )
                for kind in DOCUMENTED
            ],
        )

    async def gaps(self, found: Sequence[Entity]) -> list[DocumentationGap]:
        """A page of things without documentation — or with stale only:
        how critical, whose, how many documents, the latest when."""
        edges, others = await self._ends(found, (RelationshipType.OWNED_BY,))
        documented = await self._entities.documented([entity.id for entity in found])
        return [
            DocumentationGap(
                entity=EntityBrief.model_validate(entity),
                criticality=_level(entity),
                owners=_out(edges, others, entity.id)(RelationshipType.OWNED_BY),
                documents=documented[entity.id].count,
                last_documented_at=documented[entity.id].last_changed_at,
            )
            for entity in found
        ]

    async def business(self, found: Sequence[Entity]) -> list[BusinessRead]:
        """A page of capabilities or processes: where each sits, whose, what
        supports it, what it uses, how documented."""
        rows, _, _ = await self._business(found)
        return rows

    async def business_detail(self, entity: Entity) -> BusinessDetail:
        """One capability or process: its parents, its parts in order, the
        processes realizing it, what supports it — and the services of its
        applications — the data it uses, its owners, its documentation."""
        [row], edges, others = await self._business([entity])
        up = _up(entity)
        ties = _ties(edges, others, entity.id)
        ancestors = await self._entities.chain(entity.id, up, limit=MAX_CHAIN)
        parts = [
            others[e.from_entity_id]
            for e in edges
            if e.type is up
            and e.to_entity_id == entity.id
            and e.from_entity_id in others
            and others[e.from_entity_id].type is entity.type
        ]
        part_edges, part_ends = await self._ends(parts, PART_AROUND)
        listed = []
        for part in parts:
            out = _out(part_edges, part_ends, part.id)
            step = part.attributes.get("step")
            listed.append(
                BusinessPart(
                    entity=EntityBrief.model_validate(part),
                    step=step if isinstance(step, int) else None,
                    supported_by=out(RelationshipType.SUPPORTED_BY),
                    data=out(RelationshipType.USES),
                    owners=out(RelationshipType.OWNED_BY),
                )
            )
        listed.sort(key=lambda p: (p.step is None, p.step or 0, p.entity.name.lower()))
        support = ties(RelationshipType.SUPPORTED_BY, outgoing=True)
        applications = [t.entity.id for t in support if t.entity.type is EntityType.APPLICATION]
        direct = {t.entity.id for t in support}
        services = {
            s.id: s
            for held in (await self._entities.parts(applications, EntityType.SERVICE)).values()
            for s in held
            if s.id not in direct
        }
        return BusinessDetail(
            **row.model_dump(),
            description=_text(entity.attributes.get("description")),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            ancestors=[EntityBrief.model_validate(a) for a in ancestors],
            parts=listed,
            processes=sorted(
                (
                    t.entity
                    for t in ties(RelationshipType.REALIZES, outgoing=False)
                    if t.entity.type is EntityType.BUSINESS_PROCESS
                ),
                key=lambda brief: brief.name.lower(),
            ),
            support=support,
            services=sorted(
                (EntityBrief.model_validate(s) for s in services.values()),
                key=lambda brief: brief.name.lower(),
            ),
            data=ties(RelationshipType.USES, outgoing=True),
            ownership=ties(RelationshipType.OWNED_BY, outgoing=True),
            documentation=[
                t
                for t in ties(RelationshipType.DESCRIBES, outgoing=False)
                if t.entity.type in DOCUMENTATION
            ],
        )

    async def _business(
        self, found: Sequence[Entity]
    ) -> tuple[list[BusinessRead], list[Relationship], dict[uuid.UUID, Entity]]:
        edges, others = await self._ends(found, BUSINESS_AROUND)
        rows = []
        for entity in found:
            out = _out(edges, others, entity.id)
            up = _up(entity)
            a = entity.attributes

            def into(relation: RelationshipType, kinds: Sequence[EntityType], of: uuid.UUID) -> int:
                return sum(
                    1
                    for e in edges
                    if e.type is relation
                    and e.to_entity_id == of
                    and e.from_entity_id in others
                    and others[e.from_entity_id].type in kinds
                )

            parents = [b for b in out(up) if b.type is entity.type]
            level, step = a.get("level"), a.get("step")
            rows.append(
                BusinessRead(
                    id=entity.id,
                    key=entity.key,
                    name=entity.name,
                    type=entity.type,
                    lifecycle=entity.lifecycle,
                    level=level if isinstance(level, int) else None,
                    criticality=_level(entity),
                    stage=_text(a.get("stage")),
                    process_type=_text(a.get("process_type")),
                    step=step if isinstance(step, int) else None,
                    parent=parents[0] if parents else None,
                    capabilities=[
                        b
                        for b in out(RelationshipType.REALIZES)
                        if b.type is EntityType.BUSINESS_CAPABILITY
                    ],
                    part_count=into(up, (entity.type,), entity.id),
                    process_count=into(
                        RelationshipType.REALIZES, (EntityType.BUSINESS_PROCESS,), entity.id
                    ),
                    supported_by=out(RelationshipType.SUPPORTED_BY),
                    data_count=len(out(RelationshipType.USES)),
                    owners=out(RelationshipType.OWNED_BY),
                    document_count=into(RelationshipType.DESCRIBES, DOCUMENTATION, entity.id),
                )
            )
        return rows, edges, others

    async def business_context(self, entity: Entity) -> BusinessContext:
        """What a technical thing means to the business: the capabilities
        and processes that rely on it — on itself, on what holds it (its
        service, its application), or on what depends on it."""
        held: dict[uuid.UUID, tuple[Literal["direct", "contained", "dependent"], Entity | None]]
        held = {entity.id: ("direct", None)}
        frontier = [entity.id]
        for _ in range(MAX_HOLDERS):
            above = [
                e.to_entity_id
                for e in await self._entities.around(frontier, (RelationshipType.PART_OF,))
                if e.from_entity_id in set(frontier) and e.to_entity_id not in held
            ]
            holders = await self._entities.by_ids(above)
            frontier = [
                h.id
                for h in holders.values()
                if h.type in TECHNICAL and h.lifecycle is not Lifecycle.REMOVED
            ]
            held |= {h: ("contained", holders[h]) for h in frontier}
            if not frontier:
                break
        dependents: set[uuid.UUID] = set()
        for root in list(held):
            reached, _ = await self._entities.dependencies(
                root,
                downstream=False,
                depth=MAX_HOLDERS,
                environment=None,
                limit=MAX_DEPENDENCIES,
            )
            dependents |= set(reached) - set(held)
        for dependent in (await self._entities.by_ids(list(dependents))).values():
            held[dependent.id] = ("dependent", dependent)
        best: dict[uuid.UUID, BusinessTie] = {}
        for edge, relying in await self._entities.pointing(
            list(held), (RelationshipType.SUPPORTED_BY, RelationshipType.USES), BUSINESS
        ):
            path, via = held[edge.to_entity_id]
            tie = BusinessTie(
                entity=EntityBrief.model_validate(relying),
                relation=edge.type,
                via=EntityBrief.model_validate(via) if via is not None else None,
                path=path,
                origin=edge.origin,
                rule=edge.rule,
                confidence=edge.confidence,
            )
            known = best.get(relying.id)
            if known is None or (PATHS.index(path), -edge.confidence) < (
                PATHS.index(known.path),
                -known.confidence,
            ):
                best[relying.id] = tie
        ranked = sorted(
            best.values(),
            key=lambda t: (PATHS.index(t.path), -t.confidence, t.entity.name.lower()),
        )
        return BusinessContext(
            entity=EntityBrief.model_validate(entity),
            capabilities=[t for t in ranked if t.entity.type is EntityType.BUSINESS_CAPABILITY],
            processes=[t for t in ranked if t.entity.type is EntityType.BUSINESS_PROCESS],
        )

    # ── incidents, changes and deployments (LEKA-367) ───────────────────────

    async def incidents(self, found: Sequence[Entity]) -> list[IncidentRead]:
        """A page of incidents: how bad, where each stands, when it opened
        and was handled, what it affects, who leads it, what caused it."""
        rows, _, _ = await self._incidents(found)
        return rows

    async def incident(self, entity: Entity) -> IncidentDetail:
        """One incident: its timeline, everything it is tied to, what
        changed on what it affects before it opened, and what it reaches."""
        [row], edges, others = await self._incidents([entity])
        ties = _ties(edges, others, entity.id)
        affected = ties(RelationshipType.AFFECTS, outgoing=True)
        opened = entity.occurred_at
        changed: list[TimelineEvent] = []
        if opened is not None and affected:
            scope: set[uuid.UUID] = set()
            for tie in affected:
                scope |= await self._entities.scope(tie.entity.id, depth=MAX_SCOPE)
            changed = await self._events(
                scope,
                kinds=CHANGE_KINDS,
                since=opened - CHANGED_BEFORE,
                until=opened,
                limit=MAX_LISTED,
            )
        return IncidentDetail(
            **row.model_dump(),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            timeline=await self._steps(entity, INCIDENT_STEPS),
            affected=affected,
            people=[
                *ties(RelationshipType.LED_BY, outgoing=True),
                *ties(RelationshipType.ASSIGNED_TO, outgoing=True),
                *ties(RelationshipType.REPORTED_BY, outgoing=True),
            ],
            suspected_causes=ties(RelationshipType.CAUSED_BY, outgoing=True),
            changed_before=[e for e in changed if e.entity.id != entity.id],
            impact=await self.impact([tie.entity.id for tie in affected]),
        )

    async def _incidents(
        self, found: Sequence[Entity]
    ) -> tuple[list[IncidentRead], list[Relationship], dict[uuid.UUID, Entity]]:
        edges, others = await self._ends(found, INCIDENT_AROUND)
        rows = []
        for entity in found:
            out = _out(edges, others, entity.id)
            a = entity.attributes
            leads = out(RelationshipType.LED_BY)
            rows.append(
                IncidentRead(
                    id=entity.id,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    url=_text(a.get("url")),
                    tools=_tools(entity),
                    state=_text(a.get("state")),
                    priority=_text(a.get("priority")),
                    severity=_text(a.get("severity")),
                    urgency=_text(a.get("urgency")),
                    opened_at=entity.occurred_at,
                    acknowledged_at=_text(a.get("acknowledged_at")),
                    resolved_at=_text(a.get("resolved_at")),
                    time_to_acknowledge_minutes=_int(a.get("time_to_acknowledge_minutes")),
                    duration_minutes=_int(a.get("duration_minutes")),
                    affects=out(RelationshipType.AFFECTS),
                    commander=leads[0] if leads else None,
                    assignees=out(RelationshipType.ASSIGNED_TO),
                    causes=out(RelationshipType.CAUSED_BY),
                )
            )
        return rows, edges, others

    async def deployments(self, found: Sequence[Entity]) -> list[DeploymentRead]:
        """A page of deployments: what to where, how each went, when, by
        whom, for which services."""
        rows, _, _ = await self._deployments(found)
        return rows

    async def deployment(self, entity: Entity) -> DeploymentDetail:
        """One deployment: each status with when, what it shipped, where it
        went, the incidents said or suspected to follow from it."""
        [row], edges, others = await self._deployments([entity])
        ties = _ties(edges, others, entity.id)
        history = entity.attributes.get("status_history")
        steps = [
            TimelineStep(at=at, step="state", state=_text(h.get("state")), origin="source")
            for h in (history if isinstance(history, list) else [])
            if isinstance(h, dict) and (at := _moment(h.get("at"))) is not None
        ]
        return DeploymentDetail(
            **row.model_dump(),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            status_history=sorted(steps, key=lambda step: step.at),
            ships=ties(RelationshipType.DEPLOYS, outgoing=True),
            environments=_out(edges, others, entity.id)(RelationshipType.DEPLOYED_TO),
            incidents=ties(RelationshipType.CAUSED_BY, outgoing=False),
        )

    async def _deployments(
        self, found: Sequence[Entity]
    ) -> tuple[list[DeploymentRead], list[Relationship], dict[uuid.UUID, Entity]]:
        edges, others = await self._ends(found, DEPLOYMENT_AROUND)
        repositories = [
            e.to_entity_id
            for e in edges
            if e.type is RelationshipType.PART_OF
            and (r := others.get(e.to_entity_id)) is not None
            and r.type is EntityType.REPOSITORY
        ]
        above = [
            e
            for e in await self._entities.around(repositories, (RelationshipType.PART_OF,))
            if e.from_entity_id in set(repositories)
        ]
        held = await self._entities.by_ids([e.to_entity_id for e in above])
        rows = []
        for entity in found:
            out = _out(edges, others, entity.id)
            a = entity.attributes
            parents = out(RelationshipType.PART_OF)
            repository = next((p for p in parents if p.type is EntityType.REPOSITORY), None)
            services = {p.id: p for p in parents if p.type is EntityType.SERVICE}
            for e in above:
                service = held.get(e.to_entity_id)
                if (
                    repository
                    and e.from_entity_id == repository.id
                    and service is not None
                    and service.type is EntityType.SERVICE
                ):
                    services.setdefault(service.id, EntityBrief.model_validate(service))
            deployers = out(RelationshipType.REPORTED_BY)
            production = a.get("production")
            rows.append(
                DeploymentRead(
                    id=entity.id,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    url=_text(a.get("url")),
                    tools=_tools(entity),
                    state=_text(a.get("state")),
                    environment=_text(a.get("environment")),
                    production=production if isinstance(production, bool) else None,
                    ref=_text(a.get("ref")),
                    sha=_text(a.get("sha")),
                    deployed_at=entity.occurred_at,
                    started_at=_text(a.get("started_at")),
                    finished_at=_text(a.get("finished_at")),
                    duration_minutes=_int(a.get("duration_minutes")),
                    repository=repository,
                    services=sorted(services.values(), key=lambda b: b.name.lower()),
                    deployer=deployers[0] if deployers else None,
                    incident_count=_into(edges, others, entity.id, RelationshipType.CAUSED_BY),
                )
            )
        return rows, edges, others

    async def changes(self, found: Sequence[Entity]) -> list[ChangeRead]:
        """A page of changes: of what type, how risky, where each stands,
        when, what it affects, who made it and asked for it."""
        rows, _, _ = await self._changes(found)
        return rows

    async def change(self, entity: Entity) -> ChangeDetail:
        """One change: its timeline, what it affects, who made and asked
        for it, the incidents said or suspected to follow from it."""
        [row], edges, others = await self._changes([entity])
        ties = _ties(edges, others, entity.id)
        return ChangeDetail(
            **row.model_dump(),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            timeline=await self._steps(entity, CHANGE_STEPS),
            affected=ties(RelationshipType.AFFECTS, outgoing=True),
            people=[
                *ties(RelationshipType.ASSIGNED_TO, outgoing=True),
                *ties(RelationshipType.REPORTED_BY, outgoing=True),
            ],
            incidents=ties(RelationshipType.CAUSED_BY, outgoing=False),
        )

    async def _changes(
        self, found: Sequence[Entity]
    ) -> tuple[list[ChangeRead], list[Relationship], dict[uuid.UUID, Entity]]:
        edges, others = await self._ends(found, CHANGE_AROUND)
        rows = []
        for entity in found:
            out = _out(edges, others, entity.id)
            a = entity.attributes
            assignees, requesters = (
                out(RelationshipType.ASSIGNED_TO),
                out(RelationshipType.REPORTED_BY),
            )
            rows.append(
                ChangeRead(
                    id=entity.id,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    url=_text(a.get("url")),
                    tools=_tools(entity),
                    state=_text(a.get("state")),
                    change_type=_text(a.get("change_type")),
                    risk=_text(a.get("risk")),
                    environment=_text(a.get("environment")),
                    changed_at=entity.occurred_at,
                    planned_start_at=_text(a.get("planned_start_at")),
                    planned_end_at=_text(a.get("planned_end_at")),
                    affects=out(RelationshipType.AFFECTS),
                    assignee=assignees[0] if assignees else None,
                    requester=requesters[0] if requesters else None,
                    incident_count=_into(edges, others, entity.id, RelationshipType.CAUSED_BY),
                )
            )
        return rows, edges, others

    async def timeline(
        self,
        entity: Entity | None,
        *,
        since: datetime,
        until: datetime,
        kinds: Sequence[EntityType],
        limit: int,
    ) -> Timeline:
        """What happened between two dates, the latest first: around a
        thing — itself and what is part of it, two steps down, what
        affects it — or in the whole workspace."""
        scope = await self._entities.scope(entity.id, depth=MAX_SCOPE) if entity else None
        events, truncated = await self._timeline(
            scope, kinds=kinds, since=since, until=until, limit=limit
        )
        return Timeline(
            entity=EntityBrief.model_validate(entity) if entity else None,
            since=since,
            until=until,
            events=events,
            truncated=truncated,
        )

    async def _events(
        self,
        scope: set[uuid.UUID] | None,
        *,
        kinds: Sequence[EntityType],
        since: datetime,
        until: datetime,
        limit: int,
    ) -> list[TimelineEvent]:
        events, _ = await self._timeline(scope, kinds=kinds, since=since, until=until, limit=limit)
        return events

    async def _timeline(
        self,
        scope: set[uuid.UUID] | None,
        *,
        kinds: Sequence[EntityType],
        since: datetime,
        until: datetime,
        limit: int,
    ) -> tuple[list[TimelineEvent], bool]:
        found, truncated = await self._entities.happened(
            scope=scope, kinds=kinds, since=since, until=until, limit=limit
        )
        vias = await self._entities.by_ids([via for _, via in found if via is not None])
        events: list[TimelineEvent] = []
        for thing, via_id in found:
            via = vias.get(via_id) if via_id is not None else None
            brief = EntityBrief.model_validate(thing)
            seen = (
                EntityBrief.model_validate(via) if via is not None and via.id != thing.id else None
            )
            a = thing.attributes
            moments: list[tuple[str, datetime | None]] = []
            if thing.type is EntityType.INCIDENT:
                moments = [
                    ("incident_opened", thing.occurred_at),
                    ("incident_resolved", _moment(a.get("resolved_at"))),
                ]
            else:
                moments = [(KIND_EVENTS[thing.type], thing.occurred_at)]
            for kind, at in moments:
                if at is None or not since <= at < until:
                    continue
                events.append(
                    TimelineEvent(
                        entity=brief,
                        kind=kind,
                        at=at,
                        state=_text(a.get("state")),
                        environment=_text(a.get("environment")),
                        via=seen,
                    )
                )
        events.sort(key=lambda e: (e.at, e.entity.name), reverse=True)
        return events[:limit], truncated or len(events) > limit

    async def _steps(
        self, entity: Entity, steps: tuple[tuple[str, str], ...]
    ) -> list[TimelineStep]:
        """An event's life: the dates its sources give, and each state a
        build saw it take — when it saw it."""
        found = [
            TimelineStep(at=at, step=step, state=None, origin="source")
            for name, step in steps
            if (at := _moment(entity.attributes.get(name))) is not None
        ]
        previous: object = None
        for version in sorted(await self._entities.versions_of(entity.id), key=lambda v: v.version):
            content = version.content if isinstance(version.content, dict) else {}
            attributes = content.get("attributes")
            state = attributes.get("state") if isinstance(attributes, dict) else None
            if isinstance(state, str) and state != previous:
                found.append(
                    TimelineStep(at=version.recorded_at, step="state", state=state, origin="model")
                )
            previous = state
        return sorted(found, key=lambda step: (step.at, step.origin != "source"))

    async def impact(self, affected: list[uuid.UUID]) -> Impact:
        """What an incident — or a change (LEKA-378) — reaches: what depends
        on what it affects, two steps, the applications holding them, the
        business relying on them."""
        reached: set[uuid.UUID] = set()
        for thing in affected:
            found, _ = await self._entities.dependencies(
                thing,
                downstream=False,
                depth=IMPACT_DEPTH,
                environment=None,
                limit=MAX_DEPENDENCIES,
            )
            reached |= set(found)
        dependents = reached - set(affected)
        everything = set(affected) | dependents
        holders = [
            e.to_entity_id
            for e in await self._entities.around(list(everything), (RelationshipType.PART_OF,))
            if e.from_entity_id in everything
        ]
        known = await self._entities.by_ids([*everything, *holders])
        alive = {k: v for k, v in known.items() if v.lifecycle is not Lifecycle.REMOVED}
        capabilities: dict[uuid.UUID, BusinessTie] = {}
        processes: dict[uuid.UUID, BusinessTie] = {}
        for thing in affected:
            if thing not in alive:
                continue
            context = await self.business_context(alive[thing])
            for found_ties, kept in (
                (context.capabilities, capabilities),
                (context.processes, processes),
            ):
                for tie in found_ties:
                    held = kept.get(tie.entity.id)
                    if held is None or PATHS.index(tie.path) < PATHS.index(held.path):
                        kept[tie.entity.id] = tie

        def briefs(ids: set[uuid.UUID] | list[uuid.UUID]) -> list[EntityBrief]:
            return sorted(
                (EntityBrief.model_validate(alive[i]) for i in set(ids) if i in alive),
                key=lambda brief: brief.name.lower(),
            )

        return Impact(
            affected=briefs(affected),
            dependents=briefs(dependents),
            applications=[b for b in briefs(holders) if b.type is EntityType.APPLICATION],
            capabilities=sorted(capabilities.values(), key=lambda t: t.entity.name.lower()),
            processes=sorted(processes.values(), key=lambda t: t.entity.name.lower()),
        )

    # ── relationships (LEKA-368) ─────────────────────────────────────────────

    async def relationships(self, found: Sequence[Relationship]) -> list[GraphRelationshipRead]:
        """A page of relationships, both ends named."""
        ends = await self._entities.by_ids(
            [i for e in found for i in (e.from_entity_id, e.to_entity_id)]
        )
        return [
            GraphRelationshipRead(
                **RelationshipRead.model_validate(edge).model_dump(),
                from_entity=EntityBrief.model_validate(ends[edge.from_entity_id]),
                to_entity=EntityBrief.model_validate(ends[edge.to_entity_id]),
                provenance=list(edge.provenance),
                first_seen_at=edge.first_seen_at,
                changed_at=edge.changed_at,
            )
            for edge in found
            if edge.from_entity_id in ends and edge.to_entity_id in ends
        ]

    async def relationship_changes(
        self, found: Sequence[RelationshipChange]
    ) -> list[RelationshipChangeRead]:
        """A page of the relationships' history, both ends named — a removed
        entity's too: it is kept."""
        ends = await self._entities.by_ids(
            [i for c in found for i in (c.from_entity_id, c.to_entity_id)]
        )
        return [
            RelationshipChangeRead(
                id=change.id,
                type=change.type,
                change=change.change,
                from_entity=_brief(ends.get(change.from_entity_id)),
                to_entity=_brief(ends.get(change.to_entity_id)),
                before=change.before,
                after=change.after,
                recorded_at=change.recorded_at,
                run_id=change.run_id,
            )
            for change in found
        ]

    async def relationship_issues(
        self, found: Sequence[RelationshipIssue]
    ) -> list[RelationshipIssueRead]:
        """A page of what the last build found wrong, both ends named."""
        ends = await self._entities.by_ids(
            [i for f in found for i in (f.from_entity_id, f.to_entity_id)]
        )
        return [
            RelationshipIssueRead(
                id=issue.id,
                type=issue.type,
                issue=issue.issue,
                severity=issue.severity,
                from_entity=_brief(ends.get(issue.from_entity_id)),
                to_entity=_brief(ends.get(issue.to_entity_id)),
                origin=issue.origin,
                rule=issue.rule,
                confidence=issue.confidence,
                detail=dict(issue.detail),
                found_at=issue.created_at,
            )
            for issue in found
        ]


def _brief(entity: Entity | None) -> EntityBrief | None:
    return EntityBrief.model_validate(entity) if entity is not None else None


def _expertise(entity: Entity) -> list[Expertise]:
    """What a person's work shows they know, as enrichment kept it."""
    found = entity.attributes.get("expertise")
    shown: list[Expertise] = []
    for area in found if isinstance(found, list) else []:
        if not isinstance(area, dict):
            continue
        roles = area.get("roles")
        items = area.get("items")
        shown.append(
            Expertise(
                key=str(area.get("key") or ""),
                name=str(area.get("name") or ""),
                type=str(area.get("type") or ""),
                items=items if isinstance(items, int) else 0,
                roles={str(k): v for k, v in roles.items() if isinstance(v, int)}
                if isinstance(roles, dict)
                else {},
                last_at=_text(area.get("last_at")),
            )
        )
    return shown


def _email_of(key: str) -> str | None:
    return key.removeprefix("person:email:") if key.startswith("person:email:") else None


def _tie(edge: Relationship, other: Entity) -> Tie:
    return Tie(
        entity=EntityBrief.model_validate(other),
        origin=edge.origin,
        rule=edge.rule,
        confidence=edge.confidence,
    )


def _tools(entity: Entity) -> list[str]:
    """The kinds of tools a document or a space is read from: Confluence,
    Notion… — enrichment's, from its records."""
    return _names(entity.attributes.get("tools"))


def _up(entity: Entity) -> RelationshipType:
    """What a capability's parent is to it — child_of — or an activity's
    process: part_of."""
    if entity.type is EntityType.BUSINESS_CAPABILITY:
        return RelationshipType.CHILD_OF
    return RelationshipType.PART_OF


def _out(
    edges: list[Relationship], others: dict[uuid.UUID, Entity], of: uuid.UUID
) -> Callable[[RelationshipType], list[EntityBrief]]:
    """What an entity points at, by relation: said first, the surest first."""

    def pointed(relation: RelationshipType) -> list[EntityBrief]:
        found = sorted(
            (
                e
                for e in edges
                if e.type is relation and e.from_entity_id == of and e.to_entity_id in others
            ),
            key=lambda e: (
                e.origin != "stated",
                -e.confidence,
                others[e.to_entity_id].name.lower(),
            ),
        )
        return [EntityBrief.model_validate(others[e.to_entity_id]) for e in found]

    return pointed


def _ties(
    edges: list[Relationship], others: dict[uuid.UUID, Entity], of: uuid.UUID
) -> Callable[..., list[Tie]]:
    """An entity's ties by relation, either way: said first, the surest
    first — up to MAX_LISTED."""

    def tied(relation: RelationshipType, *, outgoing: bool) -> list[Tie]:
        found = [
            _tie(e, others[e.to_entity_id if outgoing else e.from_entity_id])
            for e in edges
            if e.type is relation
            and (e.from_entity_id if outgoing else e.to_entity_id) == of
            and (e.to_entity_id if outgoing else e.from_entity_id) in others
            and (e.to_entity_id if outgoing else e.from_entity_id) != of
        ]
        found.sort(key=lambda t: (t.origin != "stated", -t.confidence, t.entity.name.lower()))
        return found[:MAX_LISTED]

    return tied


def _into(
    edges: list[Relationship],
    others: dict[uuid.UUID, Entity],
    of: uuid.UUID,
    relation: RelationshipType,
) -> int:
    """How many point at an entity through a relation, not removed."""
    return sum(
        1
        for e in edges
        if e.type is relation and e.to_entity_id == of and e.from_entity_id in others
    )


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _moment(value: object) -> datetime | None:
    """A date an attribute holds — none for what does not read as one."""
    if not isinstance(value, str) or not value:
        return None
    try:
        found = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)


def _holds(entity: Entity) -> Holds:
    """What data it holds, and who says so: its columns, its documentation,
    a catalogue — or enrichment, from what it holds."""
    a = entity.attributes
    found = a.get("data_categories")
    origins = entity.provenance.get("attributes")
    said = (
        origins.get("classification") or origins.get("data_categories")
        if isinstance(origins, dict)
        else None
    )
    return Holds(
        classification=_text(a.get("classification")),
        data_categories=[str(c) for c in found] if isinstance(found, list) else [],
        personal_data=a.get("personal_data") is True,
        origin=str(said.get("origin") or "source") if isinstance(said, dict) else None,
    )


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
