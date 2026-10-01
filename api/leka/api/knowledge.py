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

Read by every member (`workspace:read`): it is the company's own picture. A
route validates, calls one repository or service, and returns (architecture
rule 6). The workspace is read from the session, never from the path or the
payload (rule 3): another workspace's entity is 404.
"""

from __future__ import annotations

import uuid
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
    CloudAccountDetail,
    CloudAccountRead,
    DatabaseDetail,
    DatabaseRead,
    DataFilters,
    DataObjectDetail,
    DataObjectRead,
    Dependencies,
    Entity,
    EntityBrief,
    EntityDetail,
    EntityKindRead,
    EntityRead,
    EntityRepository,
    EntityType,
    EntityVersionRead,
    InfrastructureDetail,
    InfrastructureFilters,
    InfrastructureRead,
    KnowledgeService,
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
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]

# An entity's relationships in its detail; its neighbourhood pages the rest.
EDGES = 100

ENTITY_SORTS = SortCatalogue(
    fields=(SortableField("name", Entity.name, "ix_entities_workspace_type_name"),),
    default="name",
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
