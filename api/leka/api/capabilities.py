"""What LEKA can do, over HTTP (LEKA-393): its catalogue, for this
workspace and this person.

    GET    /capabilities                    the catalogue, filtered
    GET    /capabilities/summary            at a glance (mockup 13)
    POST   /capabilities/discover           what answers a router's question
    GET    /capabilities/{key}              one, its history, its week
    PUT    /capabilities/{key}/settings     turned on or off for the workspace
    PUT    /capabilities/{key}/favourite    kept at hand · DELETE: no longer
    POST   /capabilities/route              where words would be routed, and why
                                            (LEKA-398) — an intention's:
                                            /intentions/{id}/routing

Reading takes `workspace:read`; turning one on or off `workspace:update`. An
agent's instructions are never sent: what it is, is.

A route validates, calls one service, and returns (architecture rule 6).
Permissions come from a FastAPI dependency, never an `if` in the body
(rule 5). The workspace is read from the session, never from the path or the
payload (rule 3).
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import (
    CapabilityDayUse,
    CapabilityDetail,
    CapabilityDiscovery,
    CapabilityEventRead,
    CapabilityInputRead,
    CapabilityLatest,
    CapabilityMatch,
    CapabilityModelNeeds,
    CapabilityModelRead,
    CapabilityRead,
    CapabilityReason,
    CapabilityRouter,
    CapabilitySettingUpdate,
    CapabilitySourceNeed,
    CapabilityTop,
    CapabilityUsageRead,
    CapabilityVersionRead,
    CatalogueService,
    CatalogueSummary,
    CategoryCount,
    Entry,
    RouteAsk,
    RouteQuery,
    RoutingRead,
    mentions,
    routing_read,
)
from leka.capabilities import (
    Query as Asked,
)
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, require_permission
from leka.intentions import Usage, Use, capability_usage

router = APIRouter(prefix="/capabilities", tags=["capabilities"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
Admin = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_UPDATE))]
LifecycleWord = Literal["draft", "review", "active", "deprecated", "retired"]
# What the catalogue shows unless asked: what runs.
RUNNING: tuple[LifecycleWord, ...] = ("active", "deprecated")


def _permissions(principal: Principal) -> frozenset[str]:
    return frozenset(p.value for p in principal.permissions)


def _missing() -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such capability.")


def capability_read(entry: Entry, use: Use) -> CapabilityRead:
    d = entry.definition
    able = entry.availability
    missing = {
        group
        for group in d.sources
        if any(
            r.code == "missing_source" and r.detail.get("any_of") == list(group)
            for r in able.reasons
        )
    }
    setting = entry.setting
    return CapabilityRead(
        key=d.key,
        title=d.title,
        summary=d.summary,
        category=d.category,
        kind=d.kind.value,
        version=d.version,
        lifecycle=d.lifecycle.value,
        origin=d.origin,
        mode=d.mode,
        risk=d.risk,
        permission=d.permission,
        inputs=[
            CapabilityInputRead(
                name=i.name,
                type=i.type,
                required=i.required,
                description=i.description,
                choices=list(i.choices),
                entity_types=list(i.entity_types),
            )
            for i in d.contract.inputs
        ],
        output=d.contract.output,
        formats=list(d.contract.formats),
        sources=[
            CapabilitySourceNeed(any_of=list(group), connected=group not in missing)
            for group in d.sources
        ],
        model=d.model,
        model_needs=(
            CapabilityModelNeeds(
                structured=d.model_needs.structured,
                tools=d.model_needs.tools,
                context=d.model_needs.context,
                quality=d.model_needs.quality,
            )
            if d.model
            else None
        ),
        answering=(
            CapabilityModelRead(
                provider=entry.model.endpoint.provider,
                model=entry.model.profile.model,
                title=entry.model.profile.title,
                owner="workspace" if entry.model.endpoint.owner == "workspace" else "leka",
            )
            if entry.model is not None
            else None
        ),
        goals=sorted(d.goals),
        kinds=sorted(d.kinds),
        entity_types=list(d.entity_types),
        examples=list(d.examples),
        always=d.always,
        available=able.available,
        reasons=[CapabilityReason(code=r.code, detail=dict(r.detail)) for r in able.reasons],
        notes=[CapabilityReason(code=r.code, detail=dict(r.detail)) for r in able.notes],
        enabled=entry.enabled,
        enabled_reason=setting.reason if setting is not None else None,
        enabled_changed_at=setting.changed_at if setting is not None else None,
        favourite=entry.favourite,
        registered_at=entry.standing.registered_at,
        lifecycle_changed_at=entry.standing.lifecycle_changed_at,
        versions=entry.standing.versions,
        refused=entry.standing.refused,
        usage=CapabilityUsageRead(
            runs=use.runs, previous=use.previous, failures=use.failures, average_ms=use.average_ms
        ),
    )


async def _entries(
    session: SessionDep, principal: Principal
) -> tuple[CatalogueService, list[Entry], Usage]:
    service = CatalogueService(session, principal.workspace_id)
    entries = await service.entries(permissions=_permissions(principal), user_id=principal.user_id)
    usage = await capability_usage(session, principal.workspace_id, now=datetime.now(UTC))
    return service, entries, usage


@router.get("", response_model=list[CapabilityRead])
async def capabilities(
    principal: Reader,
    session: SessionDep,
    view: Literal["all", "mine"] = "all",
    category: Annotated[list[str] | None, Query()] = None,
    kind: Literal["rules", "model", "agent"] | None = None,
    lifecycle: Annotated[list[LifecycleWord] | None, Query()] = None,
    available: bool | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Literal["relevant", "name", "recent"] = "relevant",
) -> list[CapabilityRead]:
    """The catalogue: what runs, unless asked for every lifecycle — mine,
    what I keep at hand. The most used first, unless asked otherwise."""
    _, entries, usage = await _entries(session, principal)
    wanted = set(lifecycle or RUNNING)
    found = [
        e
        for e in entries
        if e.definition.lifecycle.value in wanted
        and (view == "all" or e.favourite)
        and (not category or e.definition.category in category)
        and (kind is None or e.definition.kind.value == kind)
        and (available is None or e.availability.available == available)
        and (not q or mentions(e.definition, q))
    ]
    if sort == "name":
        found.sort(key=lambda e: e.definition.title.lower())
    elif sort == "recent":
        found.sort(key=lambda e: e.standing.registered_at or datetime.min.replace(tzinfo=UTC))
        found.reverse()
    else:
        found.sort(
            key=lambda e: (
                not e.availability.available,
                -usage.of(e.definition.key).runs,
                e.definition.title.lower(),
            )
        )
    return [capability_read(e, usage.of(e.definition.key)) for e in found]


@router.get("/summary", response_model=CatalogueSummary)
async def summary(principal: Reader, session: SessionDep) -> CatalogueSummary:
    """At a glance: what is available, by category, how much it ran this
    week, the most used, the latest added."""
    _, entries, usage = await _entries(session, principal)
    running = [e for e in entries if e.definition.lifecycle.value in RUNNING]
    month = datetime.now(UTC) - timedelta(days=30)
    categories: Counter[str] = Counter(e.definition.category for e in running)
    able: Counter[str] = Counter(e.definition.category for e in running if e.availability.available)
    category_of = {e.definition.key: e.definition.category for e in entries}
    days: list[CapabilityDayUse] = []
    for day in usage.days:
        runs: Counter[str] = Counter()
        for key, use in usage.by_key.items():
            if use.days.get(day):
                runs[category_of.get(key, "knowledge")] += use.days[day]
        days.append(CapabilityDayUse(day=day, runs=dict(runs)))
    top = sorted(
        (e for e in entries if usage.of(e.definition.key).runs),
        key=lambda e: -usage.of(e.definition.key).runs,
    )[:5]
    latest = sorted(
        (e for e in running if e.standing.registered_at is not None),
        key=lambda e: e.standing.registered_at or month,
        reverse=True,
    )[:3]
    return CatalogueSummary(
        total=len(running),
        available=sum(1 for e in running if e.availability.available),
        added_this_month=sum(
            1 for e in running if e.standing.registered_at and e.standing.registered_at >= month
        ),
        categories=[
            CategoryCount(category=c, count=n, available=able[c])
            for c, n in sorted(categories.items(), key=lambda item: (-item[1], item[0]))
        ],
        runs=sum(u.runs for u in usage.by_key.values()),
        runs_previous=sum(u.previous for u in usage.by_key.values()),
        analysis_ms=usage.analysis_ms,
        analysis_previous_ms=usage.analysis_previous_ms,
        days=days,
        top=[
            CapabilityTop(
                key=e.definition.key,
                title=e.definition.title,
                category=e.definition.category,
                runs=usage.of(e.definition.key).runs,
                previous=usage.of(e.definition.key).previous,
            )
            for e in top
        ],
        latest=[
            CapabilityLatest(
                key=e.definition.key,
                title=e.definition.title,
                summary=e.definition.summary,
                category=e.definition.category,
                registered_at=e.standing.registered_at or month,
            )
            for e in latest
        ],
    )


@router.post("/discover", response_model=list[CapabilityMatch])
async def discover(
    payload: CapabilityDiscovery, principal: Reader, session: SessionDep
) -> list[CapabilityMatch]:
    """What answers what is asked, the best first, each with why — for the
    router (LEKA-398); what this person may not use, said so."""
    service, entries, usage = await _entries(session, principal)
    by_key = {e.definition.key: e for e in entries}
    matches = await service.discover(
        Asked(
            goal=payload.goal,
            kind=payload.kind,
            entity_types=frozenset(payload.entity_types),
            text=payload.text,
            categories=frozenset(payload.categories),
            available_only=payload.available_only,
        ),
        permissions=_permissions(principal),
    )
    return [
        CapabilityMatch(
            capability=capability_read(by_key[m.definition.key], usage.of(m.definition.key)),
            score=m.score,
            reasons=list(m.reasons),
        )
        for m in matches
    ]


@router.post("/route", response_model=RoutingRead)
async def route(payload: RouteAsk, principal: Reader, session: SessionDep) -> RoutingRead:
    """Where these words would be routed, for this person, and why
    (LEKA-398): each capability ranked by its signals, each one they may not
    use or that cannot run here left out, said why — kept, as any routing."""
    found = await CapabilityRouter(session, principal.workspace_id).route(
        RouteQuery(
            text=payload.text,
            goal=payload.goal,
            kind=payload.kind,
            mode=payload.mode,
            entity_types=frozenset(payload.entity_types),
        ),
        permissions=_permissions(principal),
        by=principal.user_id,
    )
    return routing_read(found)


@router.get("/{key}", response_model=CapabilityDetail)
async def capability(key: str, principal: Reader, session: SessionDep) -> CapabilityDetail:
    service, entries, usage = await _entries(session, principal)
    entry = next((e for e in entries if e.definition.key == key), None)
    if entry is None:
        raise _missing()
    history, events = await service.history(key)
    use = usage.of(key)
    return CapabilityDetail(
        **capability_read(entry, use).model_dump(),
        history=[CapabilityVersionRead.model_validate(r) for r in reversed(history)],
        events=[CapabilityEventRead.model_validate(e) for e in events],
        days=[
            CapabilityDayUse(day=day, runs={entry.definition.category: use.days.get(day, 0)})
            for day in usage.days
        ],
    )


@router.put("/{key}/settings", response_model=CapabilityRead)
async def settings(
    key: str, payload: CapabilitySettingUpdate, principal: Admin, session: SessionDep
) -> CapabilityRead:
    """Turned on, or off — saying why — for the whole workspace: off, its
    analyses no longer run it."""
    reason = (payload.reason or "").strip() or None
    if not payload.enabled and reason is None:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_FAILED,
            "Say why it is turned off.",
            details=[FieldError(field="reason", message="required")],
        )
    service = CatalogueService(session, principal.workspace_id)
    if not await service.set_enabled(
        key, enabled=payload.enabled, reason=reason, by=principal.user_id
    ):
        raise _missing()
    await session.commit()
    entry = await service.entry(key, permissions=_permissions(principal), user_id=principal.user_id)
    if entry is None:
        raise _missing()
    usage = await capability_usage(session, principal.workspace_id, now=datetime.now(UTC))
    return capability_read(entry, usage.of(key))


async def _favourite(key: str, principal: Principal, session: SessionDep, on: bool) -> Response:
    service = CatalogueService(session, principal.workspace_id)
    if not await service.set_favourite(key, user_id=principal.user_id, on=on):
        raise _missing()
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{key}/favourite", status_code=status.HTTP_204_NO_CONTENT)
async def favourite(key: str, principal: Reader, session: SessionDep) -> Response:
    return await _favourite(key, principal, session, True)


@router.delete("/{key}/favourite", status_code=status.HTTP_204_NO_CONTENT)
async def unfavourite(key: str, principal: Reader, session: SessionDep) -> Response:
    return await _favourite(key, principal, session, False)
