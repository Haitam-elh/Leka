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

Read by every member (`workspace:read`): it is the company's own picture. A
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
from leka.db import SortableField
from leka.governance import Permission, Principal, require_permission
from leka.ingestion import EnrichmentRepository
from leka.knowledge import (
    ENTITY_KINDS,
    MODEL_VERSION,
    RELATIONSHIP_KINDS,
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
    EntityBrief,
    EntityDetail,
    EntityKindRead,
    EntityRead,
    EntityRepository,
    EntityType,
    EntityVersionRead,
    EventFilters,
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
    PersonDetail,
    PersonRead,
    Registry,
    RelationshipKindRead,
    Responsibility,
    TeamDetail,
    TeamRead,
    Timeline,
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

# An entity's relationships in its detail; its neighbourhood pages the rest.
EDGES = 100

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
                type=kind.type, version=kind.version, built_from=list(kind.built_from)
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
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
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
) -> Dependencies:
    """What an entity depends on — or what a failure of it reaches — through
    `depends_on`, `depth` steps at most: each thing reached, how far, and
    the relationships walked."""
    service = KnowledgeService(EntityRepository(session, principal.workspace_id))
    found = await service.dependencies(
        entity_id, direction=direction, depth=depth, environment=environment
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
