"""The context engine (LEKA-370): a context made, kept, made again, read back.

Turns a request into the smallest set of facts that can answer it — what
the company model says of the things asked about and what surrounds them,
each with where it came from. The hard part is not finding relevant
things, it is stopping: a context window is finite, and evidence that does
not fit is dropped deliberately rather than truncated by accident
(assembly.py). The model is read through leka.knowledge, never a
customer's API: by the time a question arrives, the work is done.

    create()     a context, and its first version, assembled from the model
    refresh()    assembled again: a new version when what the model says
                 of it changed — none when not, the latest still holds
    archive()    no longer reassembled; every version stays readable
    detail()     a context and its latest version
    assembled()  one version whole — the latest that holds something, a
                 number, or the one that stood at a date: the contract
                 downstream services read (AssembledContext)
    diff()       what changed from one version to another

THE LIFECYCLE. A context is `assembling` until its first version is made,
then `assembled` — or `failed`, when a refresh finds a root gone from the
model: that attempt is a version too, holding nothing and saying why, and
the last version that held something is still the one read by default.
`archived` is the end: read, never reassembled.

VERSIONS ARE NEVER CHANGED. Each holds its elements as the model said them
then, with their provenance; the model moving on changes the next version,
not this one. A refresh that would hold the same things, said the same way
— the same fingerprint — makes no version: it says it looked
(`refreshed_at`) and the latest holds.

Depends on leka.knowledge. Must not import leka.intentions (rule 1).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import structlog

from leka.context import assembly
from leka.context.models import Context, ContextElement, ContextVersion
from leka.context.repository import ContextRepository
from leka.context.schemas import (
    CONTRACT_VERSION,
    RETRIEVERS,
    AssembledContext,
    ContextCreate,
    ContextDetail,
    ContextDiff,
    ContextElementRead,
    ContextRead,
    ContextRequest,
    ContextSourceRead,
    ContextStrategyRead,
    ContextSubject,
    ContextSummary,
    ContextVersionRead,
    ElementChange,
    RefreshOutcome,
    RetrieverRunRead,
)
from leka.context.strategies import STRATEGIES, Gathered, Strategy, Tools
from leka.ingestion import ContentRepository
from leka.knowledge import MODEL_VERSION, GraphService, RelationshipType

logger = structlog.get_logger(__name__)

GONE = "A root of this context is no longer in the company model."
UNKNOWN = "What this context asks for is no longer something LEKA knows: {}."


class ContextArchivedError(Exception):
    """An archived context is read, never reassembled."""


class ContextService:
    """Assembles what an answer needs from the model, and keeps each assembly."""

    def __init__(
        self,
        repository: ContextRepository,
        graph: GraphService,
        *,
        content: ContentRepository | None = None,
        strategies: Mapping[str, Strategy] = STRATEGIES,
    ) -> None:
        self._repository = repository
        self._graph = graph
        self._content = content
        self._strategies = strategies

    async def create(self, body: ContextCreate, *, by: uuid.UUID | None) -> AssembledContext | None:
        """A context and its first version. None when a root is not the
        workspace's — nothing is kept."""
        request = ContextRequest(
            roots=list(dict.fromkeys(body.roots)),
            query=body.query,
            depth=body.depth,
            relationships=sorted({kind.value for kind in body.relationships}),
            environment=body.environment,
            limit=body.limit,
            window_days=body.window_days,
            until=body.until,
            retrievers=list(dict.fromkeys(body.retrievers)),
            strategy=body.strategy,
        )
        strategy = self._strategies[request.strategy]
        gathered = await strategy.gather(self._tools(), request, body.purpose)
        if gathered is None:
            return None
        context = Context(
            title=body.title,
            purpose=body.purpose,
            subject_type=body.subject.type,
            subject_id=body.subject.id,
            request=request.model_dump(mode="json"),
            status="assembling",
            current_version=0,
            created_by=by,
        )
        self._repository.keep(context)
        await self._repository.flush()
        built = _assemble(gathered, request, strategy.name)
        version, rows = await self._record(
            context,
            request,
            strategy,
            gathered,
            built,
            trigger="created",
            reason=None,
            by=by,
            error=gathered.error or GONE,
        )
        await self._repository.reload(context)
        return _assembled(context, version, rows)

    async def refresh(
        self, context_id: uuid.UUID, *, reason: str | None, by: uuid.UUID | None
    ) -> RefreshOutcome | None:
        """Assembled again from the model as it is now. None when the context
        is not the workspace's."""
        context = await self._repository.locked(context_id)
        if context is None:
            return None
        if context.status == "archived":
            raise ContextArchivedError
        request = ContextRequest.model_validate(context.request)
        strategy = self._strategies.get(request.strategy)
        unknown = _unknown(request, strategy)
        gathered = None
        if strategy is not None and not unknown:
            gathered = await strategy.gather(self._tools(), request, context.purpose)
        built = _assemble(gathered, request, request.strategy) if gathered else None
        latest = await self._repository.latest(context.id)
        status = "assembled" if built is not None else "failed"
        if (
            latest is not None
            and latest.status == status
            and latest.fingerprint == (built.fingerprint if built else "")
        ):
            context.refreshed_at = datetime.now(UTC)
            await self._repository.reload(context)
            return RefreshOutcome(changed=False, version=_version(latest))
        version, _ = await self._record(
            context,
            request,
            strategy,
            gathered,
            built,
            trigger="refreshed",
            reason=reason,
            by=by,
            error=(
                UNKNOWN.format(", ".join(unknown))
                if unknown
                else (gathered.error if gathered and gathered.error else GONE)
            ),
        )
        await self._repository.reload(context)
        return RefreshOutcome(changed=True, version=_version(version))

    async def archive(self, context_id: uuid.UUID) -> ContextRead | None:
        """No longer reassembled. Archiving twice changes nothing."""
        context = await self._repository.locked(context_id)
        if context is None:
            return None
        if context.status != "archived":
            context.status = "archived"
            context.archived_at = datetime.now(UTC)
            await self._repository.reload(context)
        return _context(context)

    async def detail(self, context_id: uuid.UUID) -> ContextDetail | None:
        context = await self._repository.context(context_id)
        if context is None:
            return None
        latest = await self._repository.latest(context.id)
        return ContextDetail(
            **_context(context).model_dump(), latest=_version(latest) if latest else None
        )

    async def assembled(
        self,
        context_id: uuid.UUID,
        *,
        version: int | None = None,
        at: datetime | None = None,
    ) -> AssembledContext | None:
        """Version `version`, or the one that stood at `at`, or the latest that
        holds something. None when there is no such context or version."""
        context = await self._repository.context(context_id)
        if context is None:
            return None
        found = (
            await self._repository.version(context.id, version)
            if version is not None
            else await self._repository.latest(context.id, assembled=True, at=at)
        )
        if found is None:
            return None
        return _assembled(context, found, await self._repository.elements(found.id))

    async def diff(self, context_id: uuid.UUID, before: int, after: int) -> ContextDiff | None:
        """What changed from version `before` to version `after`."""
        context = await self._repository.context(context_id)
        if context is None:
            return None
        then = await self._repository.version(context.id, before)
        now = await self._repository.version(context.id, after)
        if then is None or now is None:
            return None
        was = [_restore(row) for row in await self._repository.elements(then.id)]
        is_ = [_restore(row) for row in await self._repository.elements(now.id)]
        added, removed, changed, same = assembly.diff(
            [element for _, element in was], [element for _, element in is_]
        )
        before_at = {(e.kind, e.ref_id): at for at, e in was}
        after_at = {(e.kind, e.ref_id): at for at, e in is_}
        return ContextDiff(
            context_id=context.id,
            from_version=before,
            to_version=after,
            added=[_read(after_at[e.kind, e.ref_id], e) for e in added],
            removed=[_read(before_at[e.kind, e.ref_id], e) for e in removed],
            changed=[
                ElementChange(
                    before=_read(before_at[old.kind, old.ref_id], old),
                    after=_read(after_at[new.kind, new.ref_id], new),
                    fields=fields,
                )
                for old, new, fields in changed
            ],
            unchanged=same,
        )

    @staticmethod
    def reads(rows: Sequence[Context]) -> list[ContextRead]:
        """Contexts, as the API serves them."""
        return [_context(row) for row in rows]

    @staticmethod
    def version_reads(rows: Sequence[ContextVersion]) -> list[ContextVersionRead]:
        """Versions, as the API serves them."""
        return [_version(row) for row in rows]

    def _tools(self) -> Tools:
        return Tools(
            graph=self._graph,
            content=self._content,
            isolated=self._repository.isolated,
            now=datetime.now(UTC),
        )

    async def _record(
        self,
        context: Context,
        request: ContextRequest,
        strategy: Strategy | None,
        gathered: Gathered | None,
        built: assembly.Assembly | None,
        *,
        trigger: str,
        reason: str | None,
        by: uuid.UUID | None,
        error: str = GONE,
    ) -> tuple[ContextVersion, list[ContextElement]]:
        """The next version, as made — or as failed."""
        now = datetime.now(UTC)
        material = gathered.material if gathered is not None else None
        retrieval = gathered.retrieval if gathered is not None else []
        version = ContextVersion(
            context_id=context.id,
            version=context.current_version + 1,
            status="assembled" if built is not None else "failed",
            trigger=trigger,
            reason=reason,
            strategy=strategy.name if strategy is not None else request.strategy,
            strategy_version=strategy.version if strategy is not None else 0,
            contract_version=CONTRACT_VERSION,
            request=request.model_dump(mode="json"),
            model_built_at=material.built_at if material is not None else None,
            model_version=material.model_version if material is not None else MODEL_VERSION,
            element_count=len(built.elements) if built else 0,
            truncated=built.truncated if built else False,
            dropped=built.dropped if built else 0,
            summary=(built.summary if built else assembly.summary([])).model_dump(mode="json"),
            retrieval=[run.model_dump(mode="json") for run in retrieval],
            fingerprint=built.fingerprint if built else "",
            error=None if built is not None else error[:300],
            assembled_at=now,
            assembled_by=by,
        )
        rows = [
            ContextElement(
                position=position,
                kind=element.kind,
                ref_id=element.ref_id,
                ref_type=element.ref_type,
                label=element.label[:500],
                content=element.content(),
                provenance=element.provenance.model_dump(mode="json"),
                reason=element.reason.model_dump(mode="json"),
                relevance=element.relevance,
            )
            for position, element in enumerate(built.elements if built else [])
        ]
        await self._repository.record(version, rows)
        context.current_version = version.version
        context.status = version.status
        context.refreshed_at = now
        logger.info(
            "context_assembled",
            context_id=str(context.id),
            version=version.version,
            status=version.status,
            strategy=version.strategy,
            elements=version.element_count,
            retrievers={run.retriever: run.status for run in retrieval},
        )
        return version, rows


def _context(context: Context) -> ContextRead:
    return ContextRead(
        id=context.id,
        title=context.title,
        purpose=context.purpose,
        subject=ContextSubject.model_validate(
            {"type": context.subject_type, "id": context.subject_id}
        ),
        request=ContextRequest.model_validate(context.request),
        status=context.status,
        current_version=context.current_version,
        created_by=context.created_by,
        created_at=context.created_at,
        updated_at=context.updated_at,
        refreshed_at=context.refreshed_at,
        archived_at=context.archived_at,
    )


def _version(row: ContextVersion) -> ContextVersionRead:
    return ContextVersionRead.model_validate(
        {
            "version": row.version,
            "status": row.status,
            "trigger": row.trigger,
            "reason": row.reason,
            "strategy": {"name": row.strategy, "version": row.strategy_version},
            "contract_version": row.contract_version,
            "request": row.request,
            "model_built_at": row.model_built_at,
            "model_version": row.model_version,
            "element_count": row.element_count,
            "truncated": row.truncated,
            "dropped": row.dropped,
            "summary": row.summary,
            "retrieval": row.retrieval,
            "fingerprint": row.fingerprint,
            "error": row.error,
            "assembled_at": row.assembled_at,
            "assembled_by": row.assembled_by,
        }
    )


def _assembled(
    context: Context, version: ContextVersion, rows: Sequence[ContextElement]
) -> AssembledContext:
    elements = [_read(at, element) for at, element in map(_restore, rows)]
    counted: dict[uuid.UUID, ContextSourceRead] = {}
    for element in elements:
        for source in {s.source_id: s for s in element.provenance.sources}.values():
            held = counted.get(source.source_id)
            counted[source.source_id] = ContextSourceRead(
                source_id=source.source_id,
                kind=source.kind,
                name=source.name,
                elements=(held.elements if held else 0) + 1,
            )
    return AssembledContext(
        contract_version=version.contract_version,
        context_id=context.id,
        version=version.version,
        status=version.status,
        error=version.error,
        title=context.title,
        purpose=context.purpose,
        subject=ContextSubject.model_validate(
            {"type": context.subject_type, "id": context.subject_id}
        ),
        request=ContextRequest.model_validate(version.request),
        strategy=ContextStrategyRead(name=version.strategy, version=version.strategy_version),
        elements=elements,
        sources=sorted(
            counted.values(), key=lambda s: (-s.elements, (s.name or s.kind or "").casefold())
        ),
        summary=ContextSummary.model_validate(version.summary),
        retrieval=[RetrieverRunRead.model_validate(run) for run in version.retrieval],
        truncated=version.truncated,
        dropped=version.dropped,
        model_built_at=version.model_built_at,
        model_version=version.model_version,
        assembled_at=version.assembled_at,
    )


def _restore(row: ContextElement) -> tuple[int, assembly.Element]:
    return row.position, assembly.restore(
        row.kind,
        row.ref_id,
        row.ref_type,
        row.label,
        row.content,
        row.provenance,
        row.reason,
        row.relevance,
    )


def _read(position: int, element: assembly.Element) -> ContextElementRead:
    return ContextElementRead(
        position=position,
        kind=element.kind,
        ref_id=element.ref_id,
        ref_type=element.ref_type,
        label=element.label,
        entity=element.entity,
        relationship=element.relationship,
        provenance=element.provenance,
        reason=element.reason,
        relevance=element.relevance,
        text=assembly.text(element),
    )


def _unknown(request: ContextRequest, strategy: Strategy | None) -> list[str]:
    """What a context asks for that LEKA no longer knows: a strategy, a kind
    of relationship — renamed since it was made."""
    known = {kind.value for kind in RelationshipType}
    unknown = [f"the strategy {request.strategy}"] if strategy is None else []
    unknown += [f"the retriever {name}" for name in request.retrievers if name not in RETRIEVERS]
    return unknown + [f"the relationship {k}" for k in request.relationships if k not in known]


def _assemble(
    gathered: Gathered, request: ContextRequest, strategy: str
) -> assembly.Assembly | None:
    """What the strategy gathered, assembled — none when every retriever
    failed."""
    if gathered.material is None:
        return None
    return assembly.assemble(
        gathered.material,
        limit=request.limit,
        strategy=strategy,
        relevance=gathered.relevance,
        anchors=gathered.anchors,
    )
