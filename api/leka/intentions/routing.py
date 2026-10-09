"""An intention routed to a capability (LEKA-398): what the router reads of
it — what it wants (its goal, its kind, a question or a request), what it is
about, its words, whether it is clear — and of its context: the kinds of
things it holds, the kinds of sources they came from. The router
(leka.capabilities) decides; this says what it is deciding about.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import CapabilityRouter, CapabilityRouting, RouteQuery
from leka.connectors import SourceRepository
from leka.context import AssembledContext, ContextRepository, ContextService
from leka.ingestion import ContentRepository, ResolutionRepository
from leka.intentions.models import Intention
from leka.intentions.repository import IntentionRepository
from leka.intentions.schemas import Understanding
from leka.knowledge import GraphRepository, GraphService


def query_of(
    intention: Intention, understood: Understanding | None, context: AssembledContext | None
) -> RouteQuery:
    """The intention, as the router reads it."""
    text = intention.text if understood is None else understood.text
    if understood is None:
        return RouteQuery(text=text, goal=intention.goal)
    scoped = understood.scope.entities if understood.scope is not None else understood.entities
    return RouteQuery(
        text=text,
        goal=understood.goal.code,
        kind=understood.kind,
        mode=understood.mode,
        acting=any(a.changes_systems for a in understood.actions),
        entity_types=frozenset(e.type for e in scoped),
        clear=understood.clear,
        questions=tuple(a.said for a in understood.ambiguities if a.blocking),
        context_types=frozenset(
            e.ref_type for e in (context.elements if context else []) if e.kind == "entity"
        ),
        context_sources=frozenset(
            s.kind for s in (context.sources if context else []) if s.kind is not None
        ),
    )


async def route_intention(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    *,
    permissions: frozenset[str],
    by: uuid.UUID | None,
) -> CapabilityRouting | None:
    """Routed, as it stands — its understanding, its context — for this
    person: kept. None when it is not the workspace's."""
    intention = await IntentionRepository(session, workspace_id).intention(intention_id)
    if intention is None:
        return None
    understood = (
        Understanding.model_validate(intention.understanding) if intention.understanding else None
    )
    context = None
    if intention.context_id is not None:
        context = await ContextService(
            ContextRepository(session, workspace_id),
            GraphService(GraphRepository(session, workspace_id)),
            content=ContentRepository(session, workspace_id),
            resolution=ResolutionRepository(session, workspace_id),
            sources=SourceRepository(session, workspace_id),
        ).assembled(intention.context_id)
    return await CapabilityRouter(session, workspace_id).route(
        query_of(intention, understood, context),
        permissions=permissions,
        by=by,
        subject_id=intention.id,
    )
