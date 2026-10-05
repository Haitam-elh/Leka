"""The context engine (LEKA-370): a context made, kept, made again, read back.

Turns a request into the smallest set of facts that can answer it — what
the company model says of the things asked about and what surrounds them,
each with where it came from. The hard part is not finding relevant
things, it is stopping: a context window is finite, and evidence that does
not fit is dropped deliberately rather than truncated by accident
(assembly.py), what matters most first (ranking.py, LEKA-372). The model
is read through leka.knowledge, the records' text and what entity
resolution linked through leka.ingestion — never a customer's API: by the
time a question arrives, the work is done.

    create()     a context, and its first version, assembled from the model
    refresh()    assembled again: a new version when what the model says
                 of it changed — none when not, the latest still holds
    archive()    no longer reassembled; every version stays readable
    detail()     a context and its latest version
    assembled()  one version whole — the latest that holds something, a
                 number, or the one that stood at a date: the contract
                 downstream services read (AssembledContext)
    diff()       what changed from one version to another
    plan_intent()     what an intention asks for, read from its words and
                      its scope (LEKA-373): the structured context request
                      it makes, and what is missing
    assemble_intent() that context, assembled and kept with its plan

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

import math
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import structlog

from leka.connectors import SourceRepository, manifests
from leka.context import assembly
from leka.context.intent import (
    BUSINESS,
    INTENT_VERSION,
    MAX_BUSINESS,
    MAX_NAMED,
    NAMED,
    PROFILES,
    Readable,
    environment_of,
    facet_of,
    kind_of,
    named,
    period_of,
    plan_gaps,
    version_gaps,
)
from leka.context.language import expanded, words
from leka.context.models import Context, ContextElement, ContextVersion
from leka.context.ranking import Link
from leka.context.repository import ContextRepository
from leka.context.schemas import (
    CONTRACT_VERSION,
    MAX_ROOTS,
    MAX_WINDOW_DAYS,
    MIN_RELEVANCE,
    RETRIEVERS,
    AssembledContext,
    ContextConflictRead,
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
    IntentAsk,
    IntentConstraint,
    IntentPeriod,
    IntentPlan,
    IntentSubject,
    RankingReport,
    RefreshOutcome,
    RetrieverRunRead,
)
from leka.context.strategies import STRATEGIES, Gathered, Strategy, Tools
from leka.ingestion import ContentRepository, ResolutionRepository
from leka.knowledge import (
    MODEL_VERSION,
    ContextMaterial,
    EntityBrief,
    EntityType,
    GraphService,
    Lifecycle,
    RelationshipType,
    fold,
)

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
        resolution: ResolutionRepository | None = None,
        sources: SourceRepository | None = None,
        strategies: Mapping[str, Strategy] = STRATEGIES,
    ) -> None:
        self._repository = repository
        self._graph = graph
        self._content = content
        self._resolution = resolution
        self._sources = sources
        self._strategies = strategies

    async def create(
        self, body: ContextCreate, *, by: uuid.UUID | None, intent: IntentPlan | None = None
    ) -> AssembledContext | None:
        """A context and its first version — kept with the intention it was
        assembled for, as read (LEKA-373). None when a root is not the
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
            min_relevance=body.min_relevance,
            weights=dict(body.weights),
            sources=list(dict.fromkeys(body.sources)),
        )
        strategy = self._strategies[request.strategy]
        tools = self._tools()
        gathered = await strategy.gather(tools, request, body.purpose)
        if gathered is None:
            return None
        context = Context(
            title=body.title,
            purpose=body.purpose,
            subject_type=body.subject.type,
            subject_id=body.subject.id,
            request=request.model_dump(mode="json"),
            intent=intent.model_dump(mode="json") if intent else None,
            status="assembling",
            current_version=0,
            created_by=by,
        )
        self._repository.keep(context)
        await self._repository.flush()
        built = await self._assemble(gathered, request, strategy.name, tools.now)
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
        tools = self._tools()
        if strategy is not None and not unknown:
            gathered = await strategy.gather(tools, request, context.purpose)
        built = (
            await self._assemble(gathered, request, request.strategy, tools.now)
            if gathered
            else None
        )
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

    async def plan_intent(self, ask: IntentAsk) -> IntentPlan:
        """What an intention asks the company model for (LEKA-373): its kind,
        what it is about — chosen, named, or what that belongs to — when,
        where, under what constraints; the context request that makes; and
        what is missing, said rather than ignored."""
        now = datetime.now(UTC)
        kind, kind_said = kind_of(ask.text)
        profile = PROFILES[kind]

        asked = await self._graph.briefs(ask.services) if ask.services else {}
        unknown = [i for i in dict.fromkeys(ask.services) if i not in asked]
        said = words(ask.text)
        found = await self._graph.matching(expanded(said), limit=40) if said else []
        candidates = await self._graph.briefs([i for i, _, _ in found])
        readings = named(
            ask.text,
            [b for b in candidates.values() if b.lifecycle != Lifecycle.REMOVED],
        )
        sure = [n for n in readings if n.confidence >= NAMED and n.entity.id not in asked]
        sure = sure[:MAX_NAMED]
        guesses = [n for n in readings if n.confidence < NAMED]
        by_words: dict[str, list[EntityBrief]] = {}
        for reading in sure:
            by_words.setdefault(reading.said.casefold(), []).append(reading.entity)
        ambiguous = {phrase: things for phrase, things in by_words.items() if len(things) > 1}

        subjects = [
            IntentSubject(
                entity_id=brief.id,
                name=brief.name,
                type=brief.type.value,
                facet=facet_of(brief.type.value),
                how="asked",
                confidence=1.0,
            )
            for brief in (asked[i] for i in dict.fromkeys(ask.services) if i in asked)
        ] + [
            IntentSubject(
                entity_id=reading.entity.id,
                name=reading.entity.name,
                type=reading.entity.type.value,
                facet=facet_of(reading.entity.type.value),
                how="named",
                said=reading.said,
                confidence=reading.confidence,
            )
            for reading in sure
        ]
        if "business" in profile.facets:
            subjects += await self._business_of(subjects)

        period, anchor, anchored = await self._period(ask, subjects, profile.window_days, now)
        known = await self._graph.environments()
        environment: tuple[str, str] | None
        if ask.environment and ask.environment.casefold() not in {"all", "*"}:
            environment = (ask.environment, ask.environment)
            origin = "asked"
        else:
            # « postgres-prod » names a database, not where to look.
            names = {part for s in subjects for part in fold(s.name).split()}
            environment = environment_of(ask.text, known, besides=names)
            origin = "text"
        applied = environment[0] if environment and (not known or environment[0] in known) else None
        readable = await self._readable(ask.sources)
        gaps = plan_gaps(
            kind,
            subjects=sum(1 for s in subjects if s.how != "business"),
            guesses=guesses,
            ambiguous=ambiguous,
            unknown_services=unknown,
            environment=environment,
            known_environments=known,
            sources=readable,
            anchor=anchor,
            anchored=anchored,
            tried=said,
        )
        days = math.ceil((period.until - period.since) / timedelta(days=1))
        request = ContextRequest(
            roots=[s.entity_id for s in subjects][:MAX_ROOTS],
            query=ask.text,
            depth=profile.depth,
            relationships=list(profile.relationships),
            environment=applied,
            limit=ask.limit,
            window_days=max(1, min(MAX_WINDOW_DAYS, days)),
            until=period.until,
            retrievers=[],
            strategy="hybrid",
            min_relevance=MIN_RELEVANCE,
            weights=dict(profile.weights),
            sources=[s.source_id for s in readable] if ask.sources else [],
        )
        return IntentPlan(
            version=INTENT_VERSION,
            text=ask.text,
            intention_id=ask.intention_id,
            kind=kind,
            kind_said=kind_said,
            facets=list(profile.facets),
            subjects=subjects,
            period=period,
            environment=applied,
            constraints=_constraints(
                period,
                applied,
                origin,
                environment,
                list(asked.values()),
                readable if ask.sources else [],
                profile.relationships,
                profile.weights,
                kind,
                profile.window_days,
            ),
            request=request,
            gaps=gaps,
        )

    async def assemble_intent(
        self, ask: IntentAsk, *, by: uuid.UUID | None
    ) -> AssembledContext | None:
        """The context an intention asks for, assembled and kept with how it
        was read (LEKA-373). None when nothing can start it: no thing named
        or chosen, and no word that says something."""
        plan = await self.plan_intent(ask)
        request = plan.request
        if not request.roots and not words(request.query):
            return None
        body = ContextCreate(
            title=ask.title or ask.text[:300],
            purpose=ask.text,
            subject=ContextSubject(
                type="intention" if ask.intention_id else "request", id=ask.intention_id
            ),
            roots=request.roots,
            query=request.query,
            depth=request.depth,
            relationships=[RelationshipType(kind) for kind in request.relationships],
            environment=request.environment,
            limit=request.limit,
            window_days=request.window_days,
            until=request.until,
            strategy="hybrid",
            min_relevance=request.min_relevance,
            weights={
                name: weight for name, weight in request.weights.items() if name in RETRIEVERS
            },
            sources=request.sources,
        )
        return await self.create(body, by=by, intent=plan)

    async def _business_of(self, subjects: Sequence[IntentSubject]) -> list[IntentSubject]:
        """What the technical things an intention names belong to, on the
        business side — an application, a capability, a process — so that
        its context holds both, and the ways between them."""
        technical = [s.entity_id for s in subjects if s.facet == "technical"]
        if not technical:
            return []
        walked = await self._graph.walk(
            technical[:MAX_ROOTS],
            depth=2,
            entity_types=[EntityType(kind) for kind in BUSINESS],
        )
        if walked is None:
            return []
        taken = {s.entity_id for s in subjects}
        nodes = sorted(
            (
                node
                for node in walked.nodes
                if node.depth > 0
                and node.entity.type.value in BUSINESS
                and node.entity.id not in taken
            ),
            key=lambda node: (node.depth, node.entity.name.casefold(), str(node.entity.id)),
        )
        return [
            IntentSubject(
                entity_id=node.entity.id,
                name=node.entity.name,
                type=node.entity.type.value,
                facet="business",
                how="business",
                confidence=round(0.9 / node.depth, 2),
            )
            for node in nodes[:MAX_BUSINESS]
        ]

    async def _period(
        self, ask: IntentAsk, subjects: Sequence[IntentSubject], window_days: int, now: datetime
    ) -> tuple[IntentPeriod, str | None, bool]:
        """When an intention looks: asked; read from its words — or since an
        event of what it is about, found in the model; or its kind's last
        days. And the event it was read from, and whether it was found."""
        default = IntentPeriod(since=now - timedelta(days=window_days), until=now, origin="kind")
        if ask.since or ask.until:
            until = ask.until or now
            since = ask.since or until - timedelta(days=window_days)
            return IntentPeriod(since=since, until=until, origin="asked"), None, False
        read = period_of(ask.text, now)
        if read is None:
            return default, None, False
        if read.anchor is None:
            since = read.since or now - timedelta(days=window_days)
            until = min(read.until or now, now)
            if since >= until:
                return default, None, False
            return (
                IntentPeriod(since=since, until=until, origin="text", said=read.said),
                None,
                False,
            )
        about = [s.entity_id for s in subjects]
        events = (
            await self._graph.events(about, since=now - timedelta(days=MAX_WINDOW_DAYS), until=now)
            if about
            else []
        )
        latest = max(
            (at for _, at, kind, _ in events if kind.startswith(read.anchor)), default=None
        )
        if latest is None:
            return default, read.anchor, False
        return (
            IntentPeriod(since=latest, until=now, origin="model", said=read.said),
            read.anchor,
            True,
        )

    async def _readable(self, chosen: Sequence[uuid.UUID]) -> list[Readable]:
        """The sources an intention can read: connected and read — active,
        or degraded but read — the ones chosen when some were; each with
        what it was found able to read, or, never tested, what its
        connector says it can."""
        if self._sources is None:
            return []
        rows = await self._sources.list(self._sources.list_statement())
        declared = {m.key.value: frozenset(c.value for c in m.capabilities) for m in manifests()}
        wanted = set(chosen)
        return [
            Readable(
                source_id=row.id,
                name=row.name,
                kind=row.kind.value,
                capabilities=frozenset(str(c) for c in row.capabilities or [])
                or declared.get(row.kind.value, frozenset()),
            )
            for row in rows
            if row.status.value in {"active", "degraded"} and (not wanted or row.id in wanted)
        ]

    async def _assemble(
        self, gathered: Gathered, request: ContextRequest, strategy: str, now: datetime
    ) -> assembly.Assembly | None:
        """What the strategy gathered, ranked and assembled — none when every
        retriever failed."""
        if gathered.material is None:
            return None
        return assembly.assemble(
            gathered.material,
            limit=request.limit,
            strategy=strategy,
            relevance=gathered.relevance,
            anchors=gathered.anchors,
            links=await self._links(gathered.material),
            now=now,
            min_relevance=request.min_relevance,
            sources=request.sources,
        )

    async def _links(self, material: ContextMaterial) -> list[Link]:
        """What entity resolution found probably the same among what was
        gathered: folded into one (LEKA-372)."""
        if self._resolution is None:
            return []
        found = await self._resolution.links_among([item.entity.id for item in material.entities])
        return [
            Link(one=one, other=other, rule=rule, confidence=confidence, evidence=evidence)
            for one, other, rule, confidence, evidence in found
        ]

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
            ranking=_ranking(built),
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
                ranking=element.ranking.model_dump(mode="json") if element.ranking else None,
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
            left_out=built.ranking.left_out if built and built.ranking else None,
            conflicts=len(built.conflicts) if built else 0,
        )
        return version, rows


def _ranking(built: assembly.Assembly | None) -> dict[str, object] | None:
    """How a version was ranked, as it is kept: the report and the
    conflicts."""
    if built is None or built.ranking is None:
        return None
    return {
        **built.ranking.model_dump(mode="json"),
        "conflicts": [conflict.model_dump(mode="json") for conflict in built.conflicts],
    }


def _conflicts(ranking: dict[str, object] | None) -> list[ContextConflictRead]:
    said = (ranking or {}).get("conflicts")
    return [
        ContextConflictRead.model_validate(conflict)
        for conflict in (said if isinstance(said, list) else [])
        if isinstance(conflict, dict)
    ]


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
        intent=IntentPlan.model_validate(context.intent) if context.intent else None,
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
            "left_out": (row.ranking or {}).get("left_out") or {},
            "conflicts": len(_conflicts(row.ranking)),
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
    conflicts = _conflicts(version.ranking)
    retrieval = [RetrieverRunRead.model_validate(run) for run in version.retrieval]
    summary = ContextSummary.model_validate(version.summary)
    intent = None
    if context.intent:
        plan = IntentPlan.model_validate(context.intent)
        more = version_gaps(
            plan,
            retrieval=retrieval,
            by_type=summary.by_type,
            conflicts=conflicts,
            model_built_at=version.model_built_at,
            assembled_at=version.assembled_at,
        )
        intent = plan.model_copy(update={"gaps": [*plan.gaps, *more]})
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
        summary=summary,
        retrieval=retrieval,
        truncated=version.truncated,
        dropped=version.dropped,
        ranking=RankingReport.model_validate(version.ranking) if version.ranking else None,
        conflicts=conflicts,
        intent=intent,
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
        row.ranking,
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
        ranking=element.ranking,
        text=assembly.text(element),
    )


def _unknown(request: ContextRequest, strategy: Strategy | None) -> list[str]:
    """What a context asks for that LEKA no longer knows: a strategy, a kind
    of relationship — renamed since it was made."""
    known = {kind.value for kind in RelationshipType}
    unknown = [f"the strategy {request.strategy}"] if strategy is None else []
    unknown += [f"the retriever {name}" for name in request.retrievers if name not in RETRIEVERS]
    return unknown + [f"the relationship {k}" for k in request.relationships if k not in known]


def _constraints(
    period: IntentPeriod,
    environment: str | None,
    origin: str,
    said: tuple[str, str] | None,
    services: Sequence[EntityBrief],
    sources: Sequence[Readable],
    relationships: Sequence[str],
    weights: Mapping[str, float],
    kind: str,
    window_days: int,
) -> list[IntentConstraint]:
    """What an intention's context is held to, each with where it comes
    from: asked, read from its words, its kind's — or found in the model."""
    held = [
        IntentConstraint(
            kind="period",
            value={"since": period.since.isoformat(), "until": period.until.isoformat()},
            origin=period.origin,
            said=period.said or f"the last {window_days} days",
        )
    ]
    if environment:
        held.append(
            IntentConstraint(
                kind="environment",
                value=environment,
                origin="asked" if origin == "asked" else "text",
                said=said[1] if said else environment,
            )
        )
    if services:
        held.append(
            IntentConstraint(
                kind="services",
                value=[str(s.id) for s in services],
                origin="asked",
                said=", ".join(s.name for s in services),
            )
        )
    if sources:
        held.append(
            IntentConstraint(
                kind="sources",
                value=[str(s.source_id) for s in sources],
                origin="asked",
                said=", ".join(s.name for s in sources),
            )
        )
    if relationships:
        held.append(
            IntentConstraint(
                kind="relationships",
                value=list(relationships),
                origin="kind",
                said=f"the ties a {kind} intention reads",
            )
        )
    if weights:
        held.append(
            IntentConstraint(
                kind="retrievers",
                value=dict(weights),
                origin="kind",
                said=", ".join(f"{name} x{weight:g}" for name, weight in weights.items()),
            )
        )
    return held
