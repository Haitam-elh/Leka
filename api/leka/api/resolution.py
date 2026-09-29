"""Entity resolution, read (LEKA-357): what the workspace's sources resolve to.

    GET /ingestion/resolution                  where it stands: pending?, the last
                                               run, what it found
    GET /ingestion/resolution/entities         the resolved entities — by type,
                                               merged, conflicted, linked, ambiguous
    GET /ingestion/resolution/entities/{id}    one: every key it goes by per source
                                               (its provenance), and every decision
    GET /ingestion/resolution/lookup?key=…     the entity a key names — several when
                                               the key is ambiguous

Read by every member (`source:read`): what the sources hold, brought
together. What reads it to build the company model reads the same rows.

A route validates, calls one repository, and returns (architecture rule 6).
The workspace is the session's (rule 3): another workspace's entity is 404.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import exists, func, select

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.core.errors import ErrorCode
from leka.db import SortableField
from leka.governance import Permission, Principal, require_permission
from leka.ingestion import (
    RESOLVER_VERSION,
    ResolutionDecision,
    ResolutionDecisionRead,
    ResolutionRepository,
    ResolutionRunRead,
    ResolutionStatus,
    ResolvedEntity,
    ResolvedEntityDetail,
    ResolvedEntityRead,
    ResolvedKey,
    ResolvedKeyRead,
)

router = APIRouter(prefix="/ingestion/resolution", tags=["ingestion"])

Reader = Annotated[Principal, Depends(require_permission(Permission.SOURCE_READ))]

ENTITY_SORTS = SortCatalogue(
    fields=(
        SortableField("name", ResolvedEntity.name, "ix_resolved_entities_workspace_type_name"),
    ),
    default="name",
)
Only = Literal["merged", "conflicted", "linked", "ambiguous"]


@router.get("", response_model=ResolutionStatus)
async def resolution_status(session: SessionDep, principal: Reader) -> ResolutionStatus:
    """Whether the workspace has something new to resolve, the last run, and
    what the workspace resolves to now."""
    repository = ResolutionRepository(session, principal.workspace_id)
    last = await repository.latest_run()
    return ResolutionStatus(
        pending=await repository.pending(await repository.fingerprint(), RESOLVER_VERSION),
        last_run=ResolutionRunRead.model_validate(last, from_attributes=True) if last else None,
        counts=await repository.counts(),
    )


@router.get("/entities", response_model=PageEnvelope[ResolvedEntityRead])
async def resolved_entities(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    type: Annotated[str | None, Query(max_length=50)] = None,  # noqa: A002 — the API's word
    only: Annotated[
        Only | None,
        Query(
            description="merged: made of several keys; conflicted: its sources disagree; "
            "linked: probably one with another; ambiguous: a key or a match it would not guess."
        ),
    ] = None,
) -> PageEnvelope[ResolvedEntityRead]:
    """The workspace's resolved entities, by name."""
    repository = ResolutionRepository(session, principal.workspace_id)
    statement = repository.entities()
    if type is not None:
        statement = statement.where(ResolvedEntity.type == type)
    if only == "conflicted":
        statement = statement.where(func.jsonb_array_length(ResolvedEntity.conflicts) > 0)
    elif only == "merged":
        own_keys = (
            select(func.count(func.distinct(ResolvedKey.key)))
            .where(ResolvedKey.entity_id == ResolvedEntity.id, ResolvedKey.kind == "key")
            .scalar_subquery()
        )
        statement = statement.where(own_keys > 1)
    elif only in ("linked", "ambiguous"):
        kind = "link" if only == "linked" else "ambiguous"
        statement = statement.where(
            exists().where(
                ResolutionDecision.kind == kind,
                (ResolutionDecision.entity_id == ResolvedEntity.id)
                | (ResolutionDecision.other_entity_id == ResolvedEntity.id),
            )
        )
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=ResolvedEntity.id
    )
    return PageEnvelope(
        data=[ResolvedEntityRead.model_validate(e, from_attributes=True) for e in result.items],
        next_cursor=result.next_cursor,
    )


@router.get("/entities/{entity_id}", response_model=ResolvedEntityDetail)
async def resolved_entity(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> ResolvedEntityDetail:
    """One entity: every key it goes by, per source — and every decision
    that made it, linked it, or would not guess."""
    repository = ResolutionRepository(session, principal.workspace_id)
    entity = await repository.get(ResolvedEntity, entity_id)
    if entity is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    keys = await repository.keys_of([entity.id])
    decisions = await repository.decisions_of(entity.id)
    return ResolvedEntityDetail(
        **ResolvedEntityRead.model_validate(entity, from_attributes=True).model_dump(),
        keys=[ResolvedKeyRead.model_validate(k, from_attributes=True) for k in keys],
        decisions=[
            ResolutionDecisionRead(
                kind=d.kind,
                rule=d.rule,
                confidence=d.confidence,
                keys=list(d.keys),
                evidence=d.evidence,
                other_entity_id=(d.other_entity_id if d.entity_id == entity.id else d.entity_id)
                if d.kind == "link"
                else None,
            )
            for d in decisions
        ],
    )


@router.get("/lookup", response_model=list[ResolvedEntityRead])
async def lookup(
    session: SessionDep,
    principal: Reader,
    key: Annotated[str, Query(min_length=1, max_length=1000)],
) -> list[ResolvedEntityRead]:
    """The entity a key names — `person:email:sara@acme.io`, `ticket:PAY-42`
    — or several, when the key is ambiguous. None: no source shows it."""
    repository = ResolutionRepository(session, principal.workspace_id)
    return [
        ResolvedEntityRead.model_validate(e, from_attributes=True)
        for e in await repository.holding(key)
    ]
