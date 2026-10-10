"""The company model, read (LEKA-361).

    GET /knowledge/model                       where it stands: pending?, the last
                                               build, how many of each type
    GET /knowledge/registry                    the kinds of things a company is made
                                               of, their versions and attributes
    GET /knowledge/entities                    the entities — by type, lifecycle,
                                               name; the removed only when asked
    GET /knowledge/entities/{id}               one: its provenance, its relationships
    GET /knowledge/entities/{id}/versions      its history, the latest first
    GET /knowledge/entities/{id}/neighbourhood what surrounds it, 1 to 3 steps away
    GET /knowledge/entities/{id}/dependencies  what it depends on, or what depends
                                               on it, 1 to 5 steps — in one
                                               environment or all (LEKA-362)
    GET /knowledge/services                    the services: how critical, where
    GET /knowledge/applications                they run, whose, what they depend on
    GET /knowledge/services/{id}               one, what it is made of, its
    GET /knowledge/applications/{id}           dependencies both ways
    GET /knowledge/infrastructure              the cloud resources and databases: what
                                               kind and class, where, in which
                                               environment, whose (LEKA-363)
    GET /knowledge/infrastructure/{id}         one, what it holds, its dependencies
    GET /knowledge/cloud-accounts              the accounts, subscriptions, projects:
                                               how much is in each, of what, where
    GET /knowledge/cloud-accounts/{id}         one — or a resource group — and its
                                               resource groups
    GET /knowledge/databases                   the databases: where, what they hold
                                               (LEKA-364)
    GET /knowledge/databases/{id}              one, its schemas
    GET /knowledge/data-objects                the tables, views, collections
    GET /knowledge/data-objects/{id}           one: its columns, what it is tied to
    GET /knowledge/data-objects/{id}/lineage   what it reads from and references —
                                               or what reads from it — 1 to 5 steps
    GET /knowledge/teams                       the teams and departments: their parent,
                                               members, leads, what they own (LEKA-365)
    GET /knowledge/teams/{id}                  one, its sub-teams, members and owned
    GET /knowledge/people                      the people: title, department, teams,
                                               manager, what their work shows they know
    GET /knowledge/people/{id}                 one, their managers and reports, what
                                               they maintain and know
    GET /knowledge/entities/{id}/responsibility who owns and operates a thing, who
                                               leads its teams, who knows it
    GET /knowledge/documents                   the documents: where kept, who wrote and
                                               last changed them, how fresh, what they
                                               describe (LEKA-366)
    GET /knowledge/documents/{id}              one, its pages, links, everything tied
    GET /knowledge/knowledge-spaces            where documents are kept: how many, how
                                               fresh, whose, what each documents
    GET /knowledge/knowledge-spaces/{id}       one, its latest and its stalest documents
    GET /knowledge/documentation/coverage      how much documentation, how fresh, what
                                               of the company it covers, kind by kind
    GET /knowledge/documentation/gaps          what no document describes — or only
                                               stale ones
    GET /knowledge/business-capabilities       what the company does: its capabilities,
    GET /knowledge/business-processes          how — its processes and activities —
                                               whose, what supports them, what they use
    GET /knowledge/business-capabilities/{id}  one: its parts, processes, technology,
    GET /knowledge/business-processes/{id}     data, owners, documentation
    GET /knowledge/entities/{id}/business      what a technical thing means to the
                                               business: who relies on it, and how
    GET /knowledge/incidents                   the incidents, the latest first: state,
                                               priority, what they affect, what caused
                                               them (LEKA-367)
    GET /knowledge/incidents/{id}              one: its timeline, causes said or
                                               suspected, what changed before it, impact
    GET /knowledge/changes                     the changes: type, risk, state, what they
    GET /knowledge/changes/{id}                affect, who made them
    GET /knowledge/deployments                 the deployments: what to where, how each
    GET /knowledge/deployments/{id}            went, its statuses, what it shipped
    GET /knowledge/timeline                    what happened between two dates — around
                                               a thing, or everywhere
    GET /knowledge/relationships               the graph's relationships, both ends named,
                                               when each appeared and changed (LEKA-368)
    GET /knowledge/relationships/changes       what appeared, changed, went, at each build
    GET /knowledge/relationships/issues        what the last build found wrong: an end a
                                               contract does not take, a loop, two parents
    GET /knowledge/evolution                   the model's course (LEKA-383): each version
                                               an entity recorded, against the one before
    GET /knowledge/evolution/summary           what changed day by day, and the period
                                               before
    GET /knowledge/entities/{id}/history       its whole course: versions, relationships
                                               that came and went, operations on it
    GET /knowledge/entities/{id}/at            what it was at a moment, its ties then
    GET /knowledge/snapshots                   what the model held at each build
    GET /knowledge/snapshots/at                what it held at a moment — kept, or
                                               rebuilt from the history
    GET /knowledge/operations                  the restores and rebuilds asked, kept
    POST /knowledge/entities/{id}/restore      an entity's attributes put back as a
                                               version said them, from the next build
    POST /knowledge/operations/{id}/undo       a restore taken back
    POST /knowledge/model/rebuild              the model built again

Read by every member (`workspace:read`): it is the company's own picture.
Changing its course — restoring, undoing, rebuilding — is deciding what the
model says: `intention:approve`, as À valider is. A
route validates, calls one repository or service, and returns (architecture
rule 6). The workspace is read from the session, never from the path or the
payload (rule 3): another workspace's entity is 404.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.core.errors import ErrorCode
from leka.db import SortableField, current_hidden
from leka.governance import (
    Permission,
    Principal,
    Resource,
    RestrictionRepository,
    Subject,
    Target,
    audit_as,
    evaluate,
    record_apart,
    require_permission,
)
from leka.ingestion import EnrichmentRepository
from leka.knowledge import (
    ENTITY_KINDS,
    MAX_SUMMARY_DAYS,
    MODEL_VERSION,
    RELATIONSHIP_KINDS,
    AssertionRepository,
    BusinessContext,
    BusinessDetail,
    BusinessFilters,
    BusinessRead,
    ChangeDetail,
    ChangeRead,
    CloudAccountDetail,
    CloudAccountRead,
    DatabaseDetail,
    DatabaseRead,
    DataFilters,
    DataObjectDetail,
    DataObjectRead,
    Dependencies,
    DeploymentDetail,
    DeploymentRead,
    DocumentationCoverage,
    DocumentationGap,
    DocumentDetail,
    DocumentFilters,
    DocumentRead,
    Entity,
    EntityAtRead,
    EntityBrief,
    EntityChangeRead,
    EntityDetail,
    EntityHistoryRead,
    EntityKindRead,
    EntityRead,
    EntityRepository,
    EntityType,
    EntityVersion,
    EntityVersionRead,
    EventFilters,
    EvolutionFilters,
    EvolutionRepository,
    EvolutionService,
    EvolutionSummary,
    GraphRelationshipRead,
    IncidentDetail,
    IncidentRead,
    InfrastructureDetail,
    InfrastructureFilters,
    InfrastructureRead,
    KnowledgeService,
    KnowledgeSpaceDetail,
    KnowledgeSpaceRead,
    LandscapeDetail,
    LandscapeFilters,
    LandscapeRead,
    Lifecycle,
    LinkRead,
    ModelRepository,
    ModelRunRead,
    ModelStatus,
    Neighbourhood,
    OperationFilters,
    OperationRead,
    OperationRefusedError,
    PersonDetail,
    PersonRead,
    RebuildRequest,
    Registry,
    Relationship,
    RelationshipChange,
    RelationshipChangeRead,
    RelationshipFilters,
    RelationshipIssue,
    RelationshipIssueRead,
    RelationshipKindRead,
    RelationshipType,
    Responsibility,
    RestoreRequest,
    SnapshotRead,
    TeamDetail,
    TeamRead,
    Timeline,
    UndoRequest,
    queue_model_build,
    utc,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
# What a timeline holds (LEKA-367).
EVENTS = (
    EntityType.INCIDENT,
    EntityType.DEPLOYMENT,
    EntityType.CHANGE,
    EntityType.RELEASE,
    EntityType.PULL_REQUEST,
)

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
Approver = Annotated[Principal, Depends(require_permission(Permission.INTENTION_APPROVE))]

# An entity's relationships in its detail; its neighbourhood pages the rest.
EDGES = 100

# What a dependency walk may follow (the registry's contracts, LEKA-368).
Dependency = Literal["depends_on", "reads_from", "references", "supported_by", "uses"]
DEFAULT_THROUGH = (RelationshipType.DEPENDS_ON,)
ENTITY_SORTS = SortCatalogue(
    fields=(SortableField("name", Entity.name, "ix_entities_workspace_type_name"),),
    default="name",
)
# Incidents, changes, deployments: when they happened first (LEKA-367).
EVENT_SORTS = SortCatalogue(
    fields=(
        SortableField("occurred_at", Entity.occurred_at, "ix_entities_workspace_type_occurred"),
        SortableField("name", Entity.name, "ix_entities_workspace_type_name"),
    ),
    default="occurred_at",
)


@router.get("/model", response_model=ModelStatus)
async def model_status(session: SessionDep, principal: Reader) -> ModelStatus:
    """Whether enrichment made something the last build has not read, the
    last build, and what the model holds."""
    model = ModelRepository(session, principal.workspace_id)
    basis = await EnrichmentRepository(session, principal.workspace_id).latest_enrichment()
    last = await model.latest_run()
    counts = await EntityRepository(session, principal.workspace_id).counts()
    return ModelStatus(
        pending=await model.pending(basis, MODEL_VERSION),
        model_version=MODEL_VERSION,
        last_run=ModelRunRead.model_validate(last) if last else None,
        **counts,
    )


@router.get("/registry", response_model=Registry)
async def registry(principal: Reader) -> Registry:
    """The kinds of things a company is made of: each entity type — its
    version, its category, the attributes its schema declares, the
    ingestion types it is built from — and each relationship type."""
    return Registry(
        model_version=MODEL_VERSION,
        entities=[
            EntityKindRead(
                type=kind.type,
                version=kind.version,
                category=kind.category,
                attributes=sorted(kind.attributes.model_fields),
                built_from=list(kind.built_from),
            )
            for kind in ENTITY_KINDS.values()
        ],
        relationships=[
            RelationshipKindRead(
                type=kind.type,
                version=kind.version,
                built_from=list(kind.built_from),
                meaning=kind.meaning,
                sources=sorted(kind.sources) if kind.sources is not None else None,
                targets=sorted(kind.targets) if kind.targets is not None else None,
                single=kind.single,
                acyclic=kind.acyclic,
                dependency=kind.dependency,
            )
            for kind in RELATIONSHIP_KINDS.values()
        ],
    )


@router.get("/entities", response_model=PageEnvelope[EntityRead])
async def entities(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    type: EntityType | None = None,  # noqa: A002 — the API's word
    lifecycle: Annotated[
        Lifecycle | None,
        Query(description="Absent: every lifecycle but removed."),
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[EntityRead]:
    """The company's entities, by name."""
    statement = EntityRepository(session, principal.workspace_id).entities()
    if type is not None:
        statement = statement.where(Entity.type == type)
    if lifecycle is None:
        statement = statement.where(Entity.lifecycle != Lifecycle.REMOVED)
    else:
        statement = statement.where(Entity.lifecycle == lifecycle)
    if q:
        statement = statement.where(Entity.name.ilike(f"%{q}%"))
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=Entity.id
    )
    return PageEnvelope(
        data=[EntityRead.model_validate(entity) for entity in result.items],
        next_cursor=result.next_cursor,
    )


@router.get("/entities/{entity_id}", response_model=EntityDetail)
async def entity(entity_id: uuid.UUID, session: SessionDep, principal: Reader) -> EntityDetail:
    """One entity: where every piece of it came from, and its relationships
    — the surest first, up to 100."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None:
        if entity_id in current_hidden():
            # Restricted (LEKA-402): the same answer as none, the refusal kept.
            await record_apart(
                principal.workspace_id,
                principal.user_id,
                principal.role,
                evaluate(
                    Subject.of(principal),
                    Permission.WORKSPACE_READ,
                    Resource("entity", str(entity_id), restricted=True),
                ),
                resource=Resource("entity", str(entity_id), restricted=True),
                route=f"GET /knowledge/entities/{entity_id}",
            )
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    # A restricted entity read by who may (LEKA-407): who looked, when.
    if found.id in await RestrictionRepository(session, principal.workspace_id).restricted_ids():
        audit_as(
            session,
            principal,
            "data",
            "entity.restricted_read",
            target=Target("entity", found.id, found.name),
        )
    edges, total = await repository.edges_of(found.id, limit=EDGES)
    others = await repository.by_ids(
        [e.to_entity_id if e.from_entity_id == found.id else e.from_entity_id for e in edges]
    )
    links = []
    for edge in edges:
        outgoing = edge.from_entity_id == found.id
        other = others.get(edge.to_entity_id if outgoing else edge.from_entity_id)
        if other is None:
            continue
        links.append(
            LinkRead.model_validate(
                {
                    **{
                        key: getattr(edge, key)
                        for key in (
                            "id",
                            "from_entity_id",
                            "to_entity_id",
                            "type",
                            "confidence",
                            "origin",
                            "rule",
                            "cross_source",
                            "attributes",
                        )
                    },
                    "direction": "out" if outgoing else "in",
                    "other": EntityBrief.model_validate(other),
                }
            )
        )
    versions = await repository.versions_of(found.id)
    return EntityDetail(
        **EntityRead.model_validate(found).model_dump(),
        provenance=dict(found.provenance),
        relationships=links,
        relationships_total=total,
        versions=len(versions),
    )


@router.get("/entities/{entity_id}/versions", response_model=list[EntityVersionRead])
async def versions(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> list[EntityVersionRead]:
    """An entity's history: what it said at each version, and what changed."""
    repository = EntityRepository(session, principal.workspace_id)
    if await repository.get(Entity, entity_id) is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    return [EntityVersionRead.model_validate(v) for v in await repository.versions_of(entity_id)]


@router.get("/entities/{entity_id}/neighbourhood", response_model=Neighbourhood)
async def neighbourhood(
    entity_id: uuid.UUID,
    session: SessionDep,
    principal: Reader,
    depth: Annotated[int, Query(ge=1, le=3)] = 1,
) -> Neighbourhood:
    """What surrounds an entity, 1 to 3 steps away in either direction: the
    unit leka.context reads."""
    service = KnowledgeService(EntityRepository(session, principal.workspace_id))
    found = await service.neighbourhood(entity_id, depth=depth)
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    return found


# ── the landscape: applications and services (LEKA-362) ─────────────────────

Level = Literal["critical", "high", "medium", "low"]
Stage = Literal["experimental", "production", "deprecated", "retired"]


async def _landscape_page(
    kind: EntityType,
    session: SessionDep,
    principal: Principal,
    page: PageParams,
    filters: LandscapeFilters,
) -> PageEnvelope[LandscapeRead]:
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.landscape(kind, filters)
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=Entity.id
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).landscape(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/services", response_model=PageEnvelope[LandscapeRead])
async def services(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    criticality: Level | None = None,
    stage: Stage | None = None,
    environment: Annotated[str | None, Query(max_length=50)] = None,
    application_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[LandscapeRead]:
    """The services, by name: how critical — and who says so — where in
    their life, where they run, their application, their team, how many
    things they depend on and depend on them."""
    return await _landscape_page(
        EntityType.SERVICE,
        session,
        principal,
        page,
        LandscapeFilters(
            lifecycle=lifecycle,
            criticality=criticality,
            stage=stage,
            environment=environment,
            application_id=application_id,
            team_id=team_id,
            q=q,
        ),
    )


@router.get("/applications", response_model=PageEnvelope[LandscapeRead])
async def applications(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    criticality: Level | None = None,
    stage: Stage | None = None,
    environment: Annotated[str | None, Query(max_length=50)] = None,
    team_id: uuid.UUID | None = None,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[LandscapeRead]:
    """The applications — groups of services the company names as one — by
    name, with how many services each holds."""
    return await _landscape_page(
        EntityType.APPLICATION,
        session,
        principal,
        page,
        LandscapeFilters(
            lifecycle=lifecycle,
            criticality=criticality,
            stage=stage,
            environment=environment,
            team_id=team_id,
            q=q,
        ),
    )


async def _detail(
    kind: EntityType, entity_id: uuid.UUID, session: SessionDep, principal: Principal
) -> LandscapeDetail:
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not kind:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, f"No such {kind.value}.")
    return await KnowledgeService(repository).detail(found)


@router.get("/services/{entity_id}", response_model=LandscapeDetail)
async def service(entity_id: uuid.UUID, session: SessionDep, principal: Reader) -> LandscapeDetail:
    """One service: its landscape, what it is made of — its resources,
    databases, repositories, in which environments — and its dependencies
    both ways."""
    return await _detail(EntityType.SERVICE, entity_id, session, principal)


@router.get("/applications/{entity_id}", response_model=LandscapeDetail)
async def application(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> LandscapeDetail:
    """One application: its services and what else it is made of, and its
    dependencies both ways."""
    return await _detail(EntityType.APPLICATION, entity_id, session, principal)


@router.get("/entities/{entity_id}/dependencies", response_model=Dependencies)
async def dependencies(
    entity_id: uuid.UUID,
    session: SessionDep,
    principal: Reader,
    direction: Annotated[
        Literal["downstream", "upstream"],
        Query(description="downstream: what it depends on; upstream: what depends on it."),
    ] = "downstream",
    depth: Annotated[int, Query(ge=1, le=5)] = 3,
    environment: Annotated[
        str | None, Query(max_length=50, description="Only what holds there. Absent: all.")
    ] = None,
    through: Annotated[
        list[Dependency] | None,
        Query(
            description="The dependency relationships followed (LEKA-368): depends_on, "
            "reads_from, references, supported_by, uses. Absent: depends_on."
        ),
    ] = None,
) -> Dependencies:
    """What an entity depends on — or what a failure of it reaches — through
    `depends_on` (or the dependency relationships asked), `depth` steps at
    most: each thing reached, how far, and the relationships walked."""
    service = KnowledgeService(EntityRepository(session, principal.workspace_id))
    found = await service.dependencies(
        entity_id,
        direction=direction,
        depth=depth,
        environment=environment,
        through=[RelationshipType(kind) for kind in through] if through else DEFAULT_THROUGH,
    )
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    return found


# ── infrastructure and cloud (LEKA-363) ──────────────────────────────────────

Provider = Literal["aws", "azure", "gcp"]
ResourceClass = Literal["compute", "network", "storage", "database"]
ResourceKind = Literal[
    "instance", "function", "cluster", "network", "load_balancer", "bucket", "database"
]
State = Literal["running", "starting", "stopping", "stopped", "deleting", "terminated", "failed"]


@router.get("/infrastructure", response_model=PageEnvelope[InfrastructureRead])
async def infrastructure(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    resource_class: ResourceClass | None = None,
    resource_kind: ResourceKind | None = None,
    provider: Provider | None = None,
    account_id: Annotated[
        uuid.UUID | None,
        Query(description="An account, subscription or project — or a resource group."),
    ] = None,
    region: Annotated[str | None, Query(max_length=50)] = None,
    environment: Annotated[str | None, Query(max_length=50)] = None,
    state: State | None = None,
    exposure: Literal["public", "internal"] | None = None,
    criticality: Level | None = None,
    service_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[InfrastructureRead]:
    """The cloud resources and databases, by name: what kind and class,
    where — provider, account, group, region — in which environment and who
    says so, how reachable and critical, whose, what they serve."""
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.infrastructure(
        InfrastructureFilters(
            lifecycle=lifecycle,
            resource_class=resource_class,
            resource_kind=resource_kind,
            provider=provider,
            account_id=account_id,
            region=region,
            environment=environment,
            state=state,
            exposure=exposure,
            criticality=criticality,
            service_id=service_id,
            team_id=team_id,
            q=q,
        )
    )
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=Entity.id
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).infrastructure(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/infrastructure/{entity_id}", response_model=InfrastructureDetail)
async def resource(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> InfrastructureDetail:
    """One resource: where it is and whose, what it holds — a cluster's
    nodes, a network's resources — and its dependencies both ways."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type not in (EntityType.INFRA_RESOURCE, EntityType.DATABASE):
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such resource.")
    return await KnowledgeService(repository).resource(found)


@router.get("/cloud-accounts", response_model=PageEnvelope[CloudAccountRead])
async def cloud_accounts(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    provider: Provider | None = None,
    environment: Annotated[str | None, Query(max_length=50)] = None,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[CloudAccountRead]:
    """The AWS accounts, Azure subscriptions and Google Cloud projects, by
    name: how many resources each holds, of which class, in which regions;
    its environment and its team."""
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.cloud_accounts(
        lifecycle=lifecycle, provider=provider, environment=environment, q=q
    )
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=Entity.id
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).cloud_accounts(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/cloud-accounts/{entity_id}", response_model=CloudAccountDetail)
async def cloud_account(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> CloudAccountDetail:
    """One account, subscription or project — or an Azure resource group:
    what it holds, its resource groups, where each piece came from."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type not in (EntityType.CLOUD_ACCOUNT, EntityType.RESOURCE_GROUP):
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such account.")
    return await KnowledgeService(repository).cloud_account(found)


# ── data: databases, schemas, data objects (LEKA-364) ────────────────────────

Classification = Literal["restricted", "confidential", "internal", "public"]
DataCategory = Literal[
    "contact", "identity", "location", "financial", "credential", "health", "personal"
]
ObjectKind = Literal[
    "table", "partitioned_table", "view", "materialized_view", "foreign_table", "collection"
]


@router.get("/databases", response_model=PageEnvelope[DatabaseRead])
async def databases(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    engine: Annotated[str | None, Query(max_length=50)] = None,
    classification: Classification | None = None,
    personal_data: bool | None = None,
    environment: Annotated[str | None, Query(max_length=50)] = None,
    team_id: uuid.UUID | None = None,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[DatabaseRead]:
    """The databases, by name — what database sources read, and the cloud
    instances serving them: where each is, the instance serving it, how
    many schemas and objects, what data it holds and how sensitive."""
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.databases(
        lifecycle=lifecycle,
        engine=engine,
        classification=classification,
        personal_data=personal_data,
        environment=environment,
        team_id=team_id,
        q=q,
    )
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=Entity.id
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).databases(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/databases/{entity_id}", response_model=DatabaseDetail)
async def database(entity_id: uuid.UUID, session: SessionDep, principal: Reader) -> DatabaseDetail:
    """One database: its schemas — what each holds — the databases it serves
    when it is an instance, where each piece came from."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not EntityType.DATABASE:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such database.")
    return await KnowledgeService(repository).database(found)


@router.get("/data-objects", response_model=PageEnvelope[DataObjectRead])
async def data_objects(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    database_id: uuid.UUID | None = None,
    schema_id: uuid.UUID | None = None,
    object_kind: ObjectKind | None = None,
    classification: Classification | None = None,
    category: DataCategory | None = None,
    personal_data: bool | None = None,
    service_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[DataObjectRead]:
    """The tables, views and collections, by name: their database and
    schema, their size, what data they hold, how they are tied."""
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.data_objects(
        DataFilters(
            lifecycle=lifecycle,
            database_id=database_id,
            schema_id=schema_id,
            object_kind=object_kind,
            classification=classification,
            category=category,
            personal_data=personal_data,
            service_id=service_id,
            team_id=team_id,
            q=q,
        )
    )
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=Entity.id
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).data_objects(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/data-objects/{entity_id}", response_model=DataObjectDetail)
async def data_object(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> DataObjectDetail:
    """One data object: its columns — what each holds — its keys, what it
    references and reads from, what references and reads from it."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not EntityType.DATA_OBJECT:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such data object.")
    return await KnowledgeService(repository).data_object(found)


@router.get("/data-objects/{entity_id}/lineage", response_model=Dependencies)
async def lineage(
    entity_id: uuid.UUID,
    session: SessionDep,
    principal: Reader,
    direction: Annotated[
        Literal["downstream", "upstream"],
        Query(
            description="upstream: what it reads from and references; downstream: what reads "
            "from or references it."
        ),
    ] = "upstream",
    depth: Annotated[int, Query(ge=1, le=5)] = 3,
) -> Dependencies:
    """A data object's lineage: through foreign keys and what views read,
    `depth` steps at most — each thing reached, how far, the relationships
    walked."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not EntityType.DATA_OBJECT:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such data object.")
    walked = await KnowledgeService(repository).dependencies(
        entity_id, direction=direction, depth=depth, environment=None, lineage=True
    )
    if walked is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such data object.")
    return walked


# ── people and teams (LEKA-365) ──────────────────────────────────────────────


@router.get("/teams", response_model=PageEnvelope[TeamRead])
async def teams(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    team_type: Literal["team", "department"] | None = None,
    parent_id: uuid.UUID | None = None,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[TeamRead]:
    """The teams and departments, by name: their parent, how many sub-teams
    and members — said or inferred — who leads them, what they own."""
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.teams(lifecycle=lifecycle, team_type=team_type, parent_id=parent_id, q=q)
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=Entity.id
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).teams(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/teams/{entity_id}", response_model=TeamDetail)
async def team(entity_id: uuid.UUID, session: SessionDep, principal: Reader) -> TeamDetail:
    """One team: its parents up to the top, its sub-teams, its members —
    each said or inferred, how surely — and what it owns."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not EntityType.TEAM:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such team.")
    return await KnowledgeService(repository).team(found)


@router.get("/people", response_model=PageEnvelope[PersonRead])
async def people(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    team_id: uuid.UUID | None = None,
    department: Annotated[str | None, Query(max_length=200)] = None,
    contributors: Annotated[
        bool | None, Query(description="true: those whose work shows what they know.")
    ] = None,
    bots: Annotated[bool, Query(description="Bots too.")] = False,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name or address.")] = None,
) -> PageEnvelope[PersonRead]:
    """The people, by name: their title and department, their teams and
    manager, what they maintain, what their work shows they know."""
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.people(
        lifecycle=lifecycle,
        team_id=team_id,
        department=department,
        bots=bots,
        contributors=contributors,
        q=q,
    )
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=Entity.id
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).people(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/people/{entity_id}", response_model=PersonDetail)
async def person(entity_id: uuid.UUID, session: SessionDep, principal: Reader) -> PersonDetail:
    """One person: their teams, their managers up to the top, their
    reports, what they maintain and own, and everything their work shows
    they know — with its evidence."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not EntityType.PERSON:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such person.")
    return await KnowledgeService(repository).person(found)


@router.get("/entities/{entity_id}/responsibility", response_model=Responsibility)
async def responsibility(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> Responsibility:
    """Who owns and operates a thing — its teams, said or inherited, who
    leads them, who maintains it — and whose work shows they know it."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    return await KnowledgeService(repository).responsibility(found)


# ── documentation and business knowledge (LEKA-366) ─────────────────────────

Freshness = Literal["fresh", "aging", "stale"]
# What documentation can describe — what its coverage and its gaps are of.
Documented = Literal[
    "application",
    "service",
    "repository",
    "database",
    "data_object",
    "business_capability",
    "business_process",
]


@router.get("/documents", response_model=PageEnvelope[DocumentRead])
async def documents(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    space_id: uuid.UUID | None = None,
    freshness: Freshness | None = None,
    about_id: Annotated[
        uuid.UUID | None, Query(description="Those describing this entity: its documentation.")
    ] = None,
    person_id: Annotated[
        uuid.UUID | None, Query(description="Those this person wrote, edited or owns.")
    ] = None,
    team_id: uuid.UUID | None = None,
    verified: Annotated[
        bool | None, Query(description="Those their tool says are verified — or are not.")
    ] = None,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the title.")] = None,
) -> PageEnvelope[DocumentRead]:
    """The documents, by title: where each is kept, who wrote it and last
    changed it, how fresh it is, whose it is, what it describes."""
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.documents(
        DocumentFilters(
            lifecycle=lifecycle,
            space_id=space_id,
            freshness=freshness,
            about_id=about_id,
            person_id=person_id,
            team_id=team_id,
            verified=verified,
            q=q,
        )
    )
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=Entity.id
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).documents(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/documents/{entity_id}", response_model=DocumentDetail)
async def document(entity_id: uuid.UUID, session: SessionDep, principal: Reader) -> DocumentDetail:
    """One document: its pages above and below, what it describes, links
    to and mentions, who wrote, edited and owns it — each said by a source
    or inferred by a rule, how surely."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not EntityType.DOCUMENT:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such document.")
    return await KnowledgeService(repository).document(found)


@router.get("/knowledge-spaces", response_model=PageEnvelope[KnowledgeSpaceRead])
async def knowledge_spaces(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    space_kind: Annotated[
        str | None,
        Query(
            max_length=50,
            description="space, database, topic, collection, shared_drive, document_library, "
            "onedrive.",
        ),
    ] = None,
    team_id: uuid.UUID | None = None,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[KnowledgeSpaceRead]:
    """Where documents are kept, by name: how many each holds and how
    fresh, whose it is, what it documents, who writes it most."""
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.knowledge_spaces(
        lifecycle=lifecycle, space_kind=space_kind, team_id=team_id, q=q
    )
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=Entity.id
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).spaces(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/knowledge-spaces/{entity_id}", response_model=KnowledgeSpaceDetail)
async def knowledge_space(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> KnowledgeSpaceDetail:
    """One space: whose it is, what it documents, who maintains it, its
    latest documents and its stalest."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not EntityType.KNOWLEDGE_SPACE:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such space.")
    return await KnowledgeService(repository).space(found)


@router.get("/documentation/coverage", response_model=DocumentationCoverage)
async def documentation_coverage(session: SessionDep, principal: Reader) -> DocumentationCoverage:
    """How much documentation there is, how fresh, how much needs verifying
    — and, kind by kind, how much of the company it describes."""
    repository = EntityRepository(session, principal.workspace_id)
    return await KnowledgeService(repository).coverage()


@router.get("/documentation/gaps", response_model=PageEnvelope[DocumentationGap])
async def documentation_gaps(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    type: Annotated[Documented, Query(description="The kind of thing.")],  # noqa: A002
    stale: Annotated[bool, Query(description="true: those only stale documents describe.")] = False,
    criticality: Literal["critical", "high", "medium", "low"] | None = None,
    team_id: uuid.UUID | None = None,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[DocumentationGap]:
    """The things of a kind no document or space describes — or only stale
    documents do — by name: how critical, whose."""
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.gaps(
        EntityType(type),
        stale=stale,
        lifecycle=lifecycle,
        criticality=criticality,
        team_id=team_id,
        q=q,
    )
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=Entity.id
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).gaps(list(result.items)),
        next_cursor=result.next_cursor,
    )


async def _business_page(
    kind: EntityType,
    session: SessionDep,
    principal: Principal,
    page: PageParams,
    filters: BusinessFilters,
) -> PageEnvelope[BusinessRead]:
    repository = EntityRepository(session, principal.workspace_id)
    result = await serve_page(
        session,
        repository.business(kind, filters),
        request=page,
        catalogue=ENTITY_SORTS,
        id_column=Entity.id,
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).business(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/business-capabilities", response_model=PageEnvelope[BusinessRead])
async def business_capabilities(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    parent_id: uuid.UUID | None = None,
    top: Annotated[
        bool | None, Query(description="true: those with no parent; false: the others.")
    ] = None,
    team_id: uuid.UUID | None = None,
    application_id: Annotated[
        uuid.UUID | None, Query(description="Those this application — or service — supports.")
    ] = None,
    data_id: Annotated[uuid.UUID | None, Query(description="Those using this data.")] = None,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[BusinessRead]:
    """What the company does — its business capabilities, by name: where
    each sits, whose, what supports it, what it uses, how documented."""
    return await _business_page(
        EntityType.BUSINESS_CAPABILITY,
        session,
        principal,
        page,
        BusinessFilters(
            lifecycle=lifecycle,
            parent_id=parent_id,
            top=top,
            team_id=team_id,
            application_id=application_id,
            data_id=data_id,
            q=q,
        ),
    )


@router.get("/business-processes", response_model=PageEnvelope[BusinessRead])
async def business_processes(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    capability_id: Annotated[
        uuid.UUID | None, Query(description="Those realizing this capability.")
    ] = None,
    parent_id: Annotated[
        uuid.UUID | None, Query(description="The activities of this process.")
    ] = None,
    top: Annotated[
        bool | None, Query(description="true: processes; false: their activities.")
    ] = None,
    team_id: uuid.UUID | None = None,
    application_id: Annotated[
        uuid.UUID | None, Query(description="Those this application — or service — supports.")
    ] = None,
    data_id: Annotated[uuid.UUID | None, Query(description="Those using this data.")] = None,
    lifecycle: Annotated[
        Lifecycle | None, Query(description="Absent: every lifecycle but removed.")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[BusinessRead]:
    """How the company works — its business processes and their
    activities, by name: what each realizes, whose, what supports it, what
    it uses."""
    return await _business_page(
        EntityType.BUSINESS_PROCESS,
        session,
        principal,
        page,
        BusinessFilters(
            lifecycle=lifecycle,
            parent_id=parent_id,
            top=top,
            capability_id=capability_id,
            team_id=team_id,
            application_id=application_id,
            data_id=data_id,
            q=q,
        ),
    )


@router.get("/business-capabilities/{entity_id}", response_model=BusinessDetail)
async def business_capability(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> BusinessDetail:
    """One capability: its parents and sub-capabilities, the processes
    realizing it, the applications and services supporting it, the data it
    uses, its owners, its documentation."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not EntityType.BUSINESS_CAPABILITY:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such capability.")
    return await KnowledgeService(repository).business_detail(found)


@router.get("/business-processes/{entity_id}", response_model=BusinessDetail)
async def business_process(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> BusinessDetail:
    """One process: the capabilities it realizes, its activities by step —
    each with what supports it and what it uses — its technology, its data,
    its owners, its documentation."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not EntityType.BUSINESS_PROCESS:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such process.")
    return await KnowledgeService(repository).business_detail(found)


@router.get("/entities/{entity_id}/business", response_model=BusinessContext)
async def business_context(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> BusinessContext:
    """What a technical thing means to the business: the capabilities and
    processes relying on it — on itself, on what holds it (its service,
    its application) or on what depends on it — each with how, and who
    says so."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    return await KnowledgeService(repository).business_context(found)


# ── incidents, changes and deployments (LEKA-367) ───────────────────────────

# A timeline's window: a month by default, a year at most.
TIMELINE_DAYS = 30
MAX_TIMELINE = timedelta(days=366)
Happening = Literal["incident", "deployment", "change", "release", "pull_request"]
Since = Annotated[datetime | None, Query(description="From this date: when it happened.")]
Until = Annotated[datetime | None, Query(description="Before this date.")]
Lifecycles = Annotated[Lifecycle | None, Query(description="Absent: every lifecycle but removed.")]
Words = Annotated[str | None, Query(max_length=200, description="In the title.")]


async def _events_page(
    kind: EntityType,
    session: SessionDep,
    principal: Principal,
    page: PageParams,
    filters: EventFilters,
) -> tuple[EntityRepository, list[Entity], str | None]:
    repository = EntityRepository(session, principal.workspace_id)
    result = await serve_page(
        session,
        repository.events(kind, filters),
        request=page,
        catalogue=EVENT_SORTS,
        id_column=Entity.id,
    )
    return repository, list(result.items), result.next_cursor


@router.get("/incidents", response_model=PageEnvelope[IncidentRead])
async def incidents(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    state: Literal["open", "in_progress", "closed"] | None = None,
    priority: Annotated[str | None, Query(max_length=50)] = None,
    service_id: Annotated[uuid.UUID | None, Query(description="Those affecting it.")] = None,
    cause_id: Annotated[
        uuid.UUID | None, Query(description="Those this change or deployment caused.")
    ] = None,
    since: Since = None,
    until: Until = None,
    lifecycle: Lifecycles = None,
    q: Words = None,
) -> PageEnvelope[IncidentRead]:
    """The incidents, the latest first: how bad, where each stands, when it
    opened and was handled, what it affects, who leads it, what is said or
    suspected to have caused it."""
    repository, found, cursor = await _events_page(
        EntityType.INCIDENT,
        session,
        principal,
        page,
        EventFilters(
            lifecycle=lifecycle,
            state=state,
            priority=priority,
            service_id=service_id,
            cause_id=cause_id,
            since=since,
            until=until,
            q=q,
        ),
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).incidents(found), next_cursor=cursor
    )


@router.get("/incidents/{entity_id}", response_model=IncidentDetail)
async def incident(entity_id: uuid.UUID, session: SessionDep, principal: Reader) -> IncidentDetail:
    """One incident: its timeline — the dates its sources give, the states
    LEKA saw — what it affects, who handled it, what is said or suspected to
    have caused it, what changed on what it affects in the 72 hours before,
    and what it reaches: dependents, applications, the business."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not EntityType.INCIDENT:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such incident.")
    return await KnowledgeService(repository).incident(found)


@router.get("/changes", response_model=PageEnvelope[ChangeRead])
async def changes(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    state: Literal["requested", "scheduled", "in_progress", "completed", "failed", "canceled"]
    | None = None,
    change_type: Annotated[str | None, Query(max_length=50)] = None,
    environment: Annotated[str | None, Query(max_length=50)] = None,
    service_id: Annotated[uuid.UUID | None, Query(description="Those affecting it.")] = None,
    since: Since = None,
    until: Until = None,
    lifecycle: Lifecycles = None,
    q: Words = None,
) -> PageEnvelope[ChangeRead]:
    """The changes, the latest first: of what type, how risky, where each
    stands, when, what it affects, who made it and asked for it."""
    repository, found, cursor = await _events_page(
        EntityType.CHANGE,
        session,
        principal,
        page,
        EventFilters(
            lifecycle=lifecycle,
            state=state,
            change_type=change_type,
            environment=environment,
            service_id=service_id,
            since=since,
            until=until,
            q=q,
        ),
    )
    return PageEnvelope(data=await KnowledgeService(repository).changes(found), next_cursor=cursor)


@router.get("/changes/{entity_id}", response_model=ChangeDetail)
async def change(entity_id: uuid.UUID, session: SessionDep, principal: Reader) -> ChangeDetail:
    """One change: its timeline, what it affects, who made and asked for
    it, the incidents said or suspected to follow from it."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not EntityType.CHANGE:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such change.")
    return await KnowledgeService(repository).change(found)


@router.get("/deployments", response_model=PageEnvelope[DeploymentRead])
async def deployments(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    state: Literal["pending", "in_progress", "succeeded", "failed", "canceled", "inactive"]
    | None = None,
    environment: Annotated[str | None, Query(max_length=50)] = None,
    service_id: Annotated[
        uuid.UUID | None, Query(description="Its own, or its repositories'.")
    ] = None,
    repository_id: uuid.UUID | None = None,
    since: Since = None,
    until: Until = None,
    lifecycle: Lifecycles = None,
    q: Words = None,
) -> PageEnvelope[DeploymentRead]:
    """The deployments, the latest first: what to where, how each went,
    when, by whom, for which services."""
    repository, found, cursor = await _events_page(
        EntityType.DEPLOYMENT,
        session,
        principal,
        page,
        EventFilters(
            lifecycle=lifecycle,
            state=state,
            environment=environment,
            service_id=service_id,
            repository_id=repository_id,
            since=since,
            until=until,
            q=q,
        ),
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).deployments(found), next_cursor=cursor
    )


@router.get("/deployments/{entity_id}", response_model=DeploymentDetail)
async def deployment(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> DeploymentDetail:
    """One deployment: each status with when, what it shipped, where it
    went, the incidents said or suspected to follow from it."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None or found.type is not EntityType.DEPLOYMENT:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such deployment.")
    return await KnowledgeService(repository).deployment(found)


@router.get("/timeline", response_model=Timeline)
async def timeline(
    session: SessionDep,
    principal: Reader,
    entity_id: Annotated[
        uuid.UUID | None,
        Query(description="Around this thing: itself, what is part of it, what affects it."),
    ] = None,
    since: Annotated[datetime | None, Query(description="Absent: 30 days before `until`.")] = None,
    until: Annotated[datetime | None, Query(description="Absent: now.")] = None,
    kinds: Annotated[list[Happening] | None, Query(description="Absent: every kind.")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> Timeline:
    """What happened between two dates, the latest first — incidents opened
    and resolved, deployments, changes, releases, merges — around a thing,
    or in the whole workspace. A year at most."""
    end = until or datetime.now(UTC)
    start = since or end - timedelta(days=TIMELINE_DAYS)
    if start.tzinfo is None or end.tzinfo is None:
        # A date without a zone is UTC's.
        start, end = (
            start.replace(tzinfo=start.tzinfo or UTC),
            end.replace(tzinfo=end.tzinfo or UTC),
        )
    if start >= end or end - start > MAX_TIMELINE:
        raise ApiError(
            422,
            ErrorCode.VALIDATION_FAILED,
            "`since` must come before `until`, a year apart at most.",
        )
    repository = EntityRepository(session, principal.workspace_id)
    around = None
    if entity_id is not None:
        around = await repository.get(Entity, entity_id)
        if around is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    wanted = [EntityType(kind) for kind in kinds] if kinds else list(EVENTS)
    return await KnowledgeService(repository).timeline(
        around, since=start, until=end, kinds=wanted, limit=limit
    )


# ── relationships (LEKA-368) ────────────────────────────────────────────────

RELATIONSHIP_SORTS = SortCatalogue(
    fields=(
        SortableField("changed_at", Relationship.changed_at, "a sort in memory, per workspace"),
        SortableField("confidence", Relationship.confidence, "a sort in memory, per workspace"),
    ),
    default="changed_at",
)
CHANGE_SORTS = SortCatalogue(
    fields=(
        SortableField(
            "recorded_at",
            RelationshipChange.recorded_at,
            "ix_relationship_changes_workspace_recorded",
        ),
    ),
    default="recorded_at",
)
ISSUE_SORTS = SortCatalogue(
    fields=(SortableField("found_at", RelationshipIssue.created_at, "a sort in memory"),),
    default="found_at",
)
RelationshipKind = Annotated[
    RelationshipType | None, Query(alias="type", description="Of this kind.")
]
Touching = Annotated[uuid.UUID | None, Query(description="Touching it: either end.")]


@router.get("/relationships", response_model=PageEnvelope[GraphRelationshipRead])
async def relationships(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    kind: RelationshipKind = None,
    entity_id: Touching = None,
    origin: Literal["stated", "inferred", "accepted"] | None = None,
    rule: Annotated[str | None, Query(max_length=100)] = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    since: Annotated[datetime | None, Query(description="Changed from this date.")] = None,
    until: Annotated[datetime | None, Query(description="Changed before this date.")] = None,
) -> PageEnvelope[GraphRelationshipRead]:
    """The graph's relationships, the latest changed first: both ends named,
    stated or inferred and by what rule, how sure, the records they come
    from, when each first appeared and last changed."""
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.relationships(
        RelationshipFilters(
            type=kind.value if kind else None,
            entity_id=entity_id,
            origin=origin,
            rule=rule,
            min_confidence=min_confidence,
            since=since,
            until=until,
        )
    )
    result = await serve_page(
        session, statement, request=page, catalogue=RELATIONSHIP_SORTS, id_column=Relationship.id
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).relationships(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/relationships/changes", response_model=PageEnvelope[RelationshipChangeRead])
async def relationship_changes(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    kind: RelationshipKind = None,
    entity_id: Touching = None,
    change: Literal["added", "changed", "removed"] | None = None,
    since: Annotated[datetime | None, Query(description="Recorded from this date.")] = None,
    until: Annotated[datetime | None, Query(description="Recorded before this date.")] = None,
) -> PageEnvelope[RelationshipChangeRead]:
    """The relationships' history, the latest first: each that appeared,
    changed — its origin, rule, environments, its confidence by 0.05 — or
    went, at each build, before and after."""
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.relationship_changes(
        RelationshipFilters(
            type=kind.value if kind else None,
            entity_id=entity_id,
            change=change,
            since=since,
            until=until,
        )
    )
    result = await serve_page(
        session,
        statement,
        request=page,
        catalogue=CHANGE_SORTS,
        id_column=RelationshipChange.id,
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).relationship_changes(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/relationships/issues", response_model=PageEnvelope[RelationshipIssueRead])
async def relationship_issues(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    kind: RelationshipKind = None,
    entity_id: Touching = None,
    severity: Literal["error", "warning"] | None = None,
    issue: Literal["wrong_end", "cycle_broken", "cycle", "several_targets"] | None = None,
) -> PageEnvelope[RelationshipIssueRead]:
    """What the last build found wrong: an end its contract does not take —
    dropped, an error — an inferred link closing a loop where none may be —
    dropped — a loop its sources state, a dependency loop, two of what a
    thing has one of — kept, warnings."""
    repository = EntityRepository(session, principal.workspace_id)
    statement = repository.relationship_issues(
        RelationshipFilters(
            type=kind.value if kind else None, entity_id=entity_id, severity=severity, issue=issue
        )
    )
    result = await serve_page(
        session, statement, request=page, catalogue=ISSUE_SORTS, id_column=RelationshipIssue.id
    )
    return PageEnvelope(
        data=await KnowledgeService(repository).relationship_issues(list(result.items)),
        next_cursor=result.next_cursor,
    )


# ── the model's course (LEKA-383) ───────────────────────────────────────────

EVOLUTION_SORTS = SortCatalogue(
    fields=(
        SortableField(
            "recorded_at", EntityVersion.recorded_at, "ix_entity_versions_workspace_recorded"
        ),
    ),
    default="recorded_at",
)
# Snapshots a list holds at most.
MAX_SNAPSHOTS = 400
MAX_OPERATIONS = 200
Moment = Annotated[datetime, Query(description="A moment; without a zone, UTC.")]


def _evolution(session: SessionDep, principal: Principal) -> EvolutionService:
    return EvolutionService(
        EvolutionRepository(session, principal.workspace_id),
        AssertionRepository(session, principal.workspace_id),
    )


def _no_entity() -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")


def _refused(error: OperationRefusedError) -> ApiError:
    said = {
        "removed": "No source shows it any more: there is nothing to restore it on.",
        "current": "That is the version it is at.",
        "nothing_to_restore": "That version says nothing the model does not say now.",
        "not_undoable": "Only a restore can be undone.",
        "already_undone": "It was already undone.",
    }
    return ApiError(
        status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, said.get(error.reason, error.reason)
    )


@router.get("/evolution", response_model=PageEnvelope[EntityChangeRead])
async def evolution(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    entity_id: Annotated[uuid.UUID | None, Query(description="Of this entity.")] = None,
    kind: Annotated[EntityType | None, Query(alias="type", description="Of this kind.")] = None,
    change: Literal["created", "changed", "removed", "returned"] | None = None,
    since: Annotated[datetime | None, Query(description="Recorded from this date.")] = None,
    until: Annotated[datetime | None, Query(description="Recorded before this date.")] = None,
) -> PageEnvelope[EntityChangeRead]:
    """What changed in the model, the latest first: each version an entity
    recorded — created, changed, removed, back — with each field it changed,
    from what, to what."""
    repository = EvolutionRepository(session, principal.workspace_id)
    statement = repository.entity_changes(
        EvolutionFilters(
            entity_id=entity_id,
            type=kind,
            change=change,
            since=utc(since) if since else None,
            until=utc(until) if until else None,
        )
    )
    result = await serve_page(
        session, statement, request=page, catalogue=EVOLUTION_SORTS, id_column=EntityVersion.id
    )
    return PageEnvelope(
        data=await _evolution(session, principal).entity_changes(list(result.items)),
        next_cursor=result.next_cursor,
    )


@router.get("/evolution/summary", response_model=EvolutionSummary)
async def evolution_summary(
    session: SessionDep,
    principal: Reader,
    since: Annotated[datetime | None, Query(description="From; 7 days ago by default.")] = None,
    until: Annotated[datetime | None, Query(description="Before; now by default.")] = None,
    timezone: Annotated[
        str | None, Query(max_length=64, description="The days' zone, IANA: Europe/Paris. UTC.")
    ] = None,
) -> EvolutionSummary:
    """What changed day by day — things created, changed, removed, back;
    relationships added, changed, removed — and over the period before, as
    long."""
    end = utc(until) if until else datetime.now(UTC)
    start = utc(since) if since else end - timedelta(days=7)
    if start >= end or end - start > timedelta(days=MAX_SUMMARY_DAYS):
        raise ApiError(
            422,
            ErrorCode.VALIDATION_FAILED,
            "`since` must come before `until`, a year apart at most.",
        )
    return await _evolution(session, principal).summary(since=start, until=end, timezone=timezone)


@router.get("/entities/{entity_id}/history", response_model=EntityHistoryRead)
async def entity_history(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> EntityHistoryRead:
    """An entity's whole course: each version against the one before, its
    relationships that appeared, changed or went, the operations on it."""
    found = await _evolution(session, principal).history(entity_id)
    if found is None:
        raise _no_entity()
    return found


@router.get("/entities/{entity_id}/at", response_model=EntityAtRead)
async def entity_at(
    entity_id: uuid.UUID, moment: Moment, session: SessionDep, principal: Reader
) -> EntityAtRead:
    """An entity as it was at a moment: the version in force then, its
    relationships as they stood — `complete` false when the history does
    not reach that far."""
    found = await _evolution(session, principal).at(entity_id, utc(moment))
    if found is None:
        raise _no_entity()
    return found


@router.get("/snapshots", response_model=list[SnapshotRead])
async def snapshots(
    session: SessionDep,
    principal: Reader,
    since: Annotated[datetime | None, Query(description="Taken from this date.")] = None,
    until: Annotated[datetime | None, Query(description="Taken before this date.")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_SNAPSHOTS)] = 100,
) -> list[SnapshotRead]:
    """What the model held at each build that changed it — a day's first
    at least — the oldest first: the latest `limit`."""
    return await _evolution(session, principal).snapshots(
        since=utc(since) if since else None, until=utc(until) if until else None, limit=limit
    )


@router.get("/snapshots/at", response_model=SnapshotRead)
async def snapshot_at(moment: Moment, session: SessionDep, principal: Reader) -> SnapshotRead:
    """What the model held at a moment: the snapshot in force then — or one
    rebuilt now from the history. 404 where the history does not reach."""
    found = await _evolution(session, principal).snapshot_at(utc(moment))
    if found is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            ErrorCode.NOT_FOUND,
            "The model's history does not reach that far.",
        )
    return found


@router.get("/operations", response_model=list[OperationRead])
async def operations(
    session: SessionDep,
    principal: Reader,
    kind: Literal["restore", "rebuild"] | None = None,
    state: Annotated[
        Literal["queued", "applied", "done", "failed", "undone"] | None,
        Query(alias="status"),
    ] = None,
    entity_id: Annotated[uuid.UUID | None, Query(description="On this entity.")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_OPERATIONS)] = 50,
) -> list[OperationRead]:
    """The restores and rebuilds asked, the latest first: who, when, why,
    what came of them."""
    return await _evolution(session, principal).operations(
        OperationFilters(kind=kind, status=state, entity_id=entity_id), limit=limit
    )


@router.post(
    "/entities/{entity_id}/restore",
    response_model=OperationRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def restore(
    entity_id: uuid.UUID, body: RestoreRequest, session: SessionDep, principal: Approver
) -> OperationRead:
    """Put an entity's attributes back as one of its versions said them —
    every one it said otherwise, or those named: the model shows them from
    its next build, over what the sources say, until the operation is
    undone. 404 for an unknown version; 409 for a removed entity, its own
    version, or a version that restores nothing."""
    try:
        found = await _evolution(session, principal).restore(
            entity_id,
            body.version,
            attributes=body.attributes,
            reason=body.reason,
            by=principal.user_id,
            now=datetime.now(UTC),
        )
    except OperationRefusedError as error:
        raise _refused(error) from error
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such version.")
    await session.commit()
    await queue_model_build(principal.workspace_id)
    return found


@router.post("/operations/{operation_id}/undo", response_model=OperationRead)
async def undo(
    operation_id: uuid.UUID, body: UndoRequest, session: SessionDep, principal: Approver
) -> OperationRead:
    """A restore taken back: the next build shows what the sources say. 409
    for a rebuild, or a restore already undone."""
    try:
        found = await _evolution(session, principal).undo(
            operation_id, reason=body.reason, by=principal.user_id, now=datetime.now(UTC)
        )
    except OperationRefusedError as error:
        raise _refused(error) from error
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such operation.")
    await session.commit()
    await queue_model_build(principal.workspace_id)
    return found


@router.post("/model/rebuild", response_model=OperationRead, status_code=status.HTTP_202_ACCEPTED)
async def rebuild(body: RebuildRequest, session: SessionDep, principal: Approver) -> OperationRead:
    """Build the model again from what it is made of, though nothing new
    came: queued — the operation says, when the build ran, what it did, or
    why it could not. One already queued answers."""
    found = await _evolution(session, principal).rebuild(
        reason=body.reason, by=principal.user_id, now=datetime.now(UTC)
    )
    await session.commit()
    await queue_model_build(principal.workspace_id)
    return found
