"""How the company model changes over time (LEKA-383): what changed, what
it held at a moment, and the controlled ways to change its course.

    WHAT CHANGED   each version an entity recorded (LEKA-361), against the
                   one before: created, changed, removed, back — which
                   fields, from what, to what (`diff`); each relationship
                   that appeared, changed or went (LEKA-368)
    AT A MOMENT    an entity as the version in force then said it, its
                   relationships as they stood — the ones of today, each
                   change since undone (`rewind`). As far as the history
                   goes: relationship changes are kept RELATIONSHIP_HISTORY
                   days, versions always
    SNAPSHOTS      what the model held: how many of each kind, in each
                   lifecycle, of each relationship, and how well each kind
                   is known (`measure`) — written by the build, or rebuilt
                   from the history when the build did not write one
    RESTORE        an entity's attributes put back as one of its versions
                   said them: validated facts (model_assertions) the next
                   build applies over what the sources say, the decision
                   kept in their provenance (`operation_id`) — taken back
                   by undoing the operation. Never silent, never lost: the
                   sources' values stay in provenance (`replaced`)
    REBUILD        the model built again from what it is made of, though
                   nothing new came — asked by someone, kept, its outcome
                   said

Pure functions first — tested in a millisecond — then the service.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from leka.knowledge.build import Assertion, changes
from leka.knowledge.models import (
    EntityVersion,
    Lifecycle,
    ModelOperation,
    ModelSnapshot,
    RelationshipChange,
)
from leka.knowledge.repository import (
    AssertionRepository,
    EvolutionRepository,
    OperationFilters,
)
from leka.knowledge.schemas import (
    EntityAtRead,
    EntityBrief,
    EntityChangeRead,
    EntityHistoryRead,
    EvolutionBucket,
    EvolutionCounts,
    EvolutionMaterial,
    EvolutionSummary,
    EvolvedEntity,
    EvolvedIncident,
    EvolvedTie,
    EvolvedVersion,
    FieldChange,
    OperationRead,
    RelationshipAtRead,
    RelationshipChangeRead,
    SnapshotKind,
    SnapshotRead,
)
from leka.knowledge.views import coverage

# How long the relationships' history is kept (job.py prunes it): before
# this, what a relationship was is not known.
RELATIONSHIP_HISTORY = timedelta(days=365)
# A snapshot a day at least, when builds run; kept this long, the latest
# always.
SNAPSHOT_EVERY = timedelta(days=1)
SNAPSHOT_DAYS = 400
# A workspace's first snapshot rebuilds, from its history, one a week
# for this many weeks before it.
BACKFILL_WEEKS = 12
# What a summary covers at most; its buckets are days.
MAX_SUMMARY_DAYS = 366
# What an entity's history says of its relationships at most.
HISTORY_RELATIONSHIPS = 100
HISTORY_OPERATIONS = 50
# A restore's facts: validated by someone, sure.
RESTORE_RULE = "restore"
# What the insights read of the recent course (LEKA-383): the versions and
# relationship changes of a month, the incidents of two — at most so many.
EVOLUTION_WINDOW = timedelta(days=30)
INCIDENT_WINDOW = timedelta(days=60)
MAX_EVOLUTION = 5_000
MAX_INCIDENTS = 1_000

Edge = tuple[uuid.UUID, uuid.UUID, str]


class OperationRefusedError(Exception):
    """An operation the model's state does not allow: a version that
    restores nothing, an entity removed, an operation already undone."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ── pure ─────────────────────────────────────────────────────────────────────


def _attributes(content: Mapping[str, object] | None) -> Mapping[str, object]:
    found = (content or {}).get("attributes")
    return found if isinstance(found, dict) else {}


def _value(content: Mapping[str, object] | None, field: str) -> object:
    if content is None:
        return None
    if field.startswith("attributes."):
        return _attributes(content).get(field.removeprefix("attributes."))
    return content.get(field)


def diff(before: Mapping[str, object] | None, after: Mapping[str, object]) -> list[FieldChange]:
    """What a version changed from the one before: each field — "name",
    "lifecycle", "attributes.<name>" — from what, to what. The first
    version changed nothing: it is everything."""
    if before is None:
        return []
    return [
        FieldChange(field=name, before=_value(before, name), after=_value(after, name))
        for name in changes(dict(before), dict(after))
    ]


def change_kind(
    version: int, before: Mapping[str, object] | None, after: Mapping[str, object]
) -> str:
    """What a version was: the thing created, removed — no source shows it
    any more — back after that, or changed."""
    if version == 1 or before is None:
        return "created"
    then, now = before.get("lifecycle"), after.get("lifecycle")
    if now == Lifecycle.REMOVED.value and then != now:
        return "removed"
    if then == Lifecycle.REMOVED.value and now != then:
        return "returned"
    return "changed"


@dataclass(frozen=True)
class Moved:
    """A relationship change, as rewinding reads it."""

    from_id: uuid.UUID
    to_id: uuid.UUID
    type: str
    change: str
    before: Mapping[str, object] | None


def rewind(
    now: Mapping[Edge, Mapping[str, object]], since: Iterable[Moved]
) -> dict[Edge, Mapping[str, object]]:
    """The relationships as they stood before these changes — given the
    latest first: each undone, an addition taken away, a removal or a
    change put back as it was."""
    state = dict(now)
    for moved in since:
        key = (moved.from_id, moved.to_id, moved.type)
        if moved.change == "added":
            state.pop(key, None)
        else:
            state[key] = dict(moved.before or {})
    return state


@dataclass(frozen=True)
class Thing:
    """An entity, as a snapshot counts it."""

    id: uuid.UUID
    type: str
    lifecycle: str
    bot: bool = False
    # How many sources say it; None when not known — rebuilt from history.
    sources: int | None = None


@dataclass(frozen=True)
class Measured:
    """What a snapshot holds."""

    types: dict[str, int]
    lifecycles: dict[str, int]
    relationships: dict[str, int]
    kinds: dict[str, dict[str, int | None]]

    def counts(self) -> dict[str, object]:
        return {
            "types": self.types,
            "lifecycles": self.lifecycles,
            "relationships": self.relationships,
        }


def measure(things: Iterable[Thing], edges: Iterable[Edge]) -> Measured:
    """What the model holds: how many of each kind — the removed left out —
    in each lifecycle, of each relationship; and how well each kind is
    known, as the coverage counts it (GET /knowledge/coverage): the bots
    left out, how many have an owner, a document, two sources, a tie."""
    listed = list(things)
    ties = list(edges)
    present = [t for t in listed if t.lifecycle != Lifecycle.REMOVED.value]
    owned = {a for a, _, kind in ties if kind == "owned_by"}
    described = {b for _, b, kind in ties if kind == "describes"}
    connected = {end for a, b, _ in ties for end in (a, b)}
    tally: dict[str, Counter[str]] = {}
    unknown: set[str] = set()
    for thing in present:
        if thing.bot:
            continue
        row = tally.setdefault(thing.type, Counter())
        row["total"] += 1
        row["owned"] += thing.id in owned
        row["documented"] += thing.id in described
        row["corroborated"] += (thing.sources or 0) >= 2
        row["connected"] += thing.id in connected
        if thing.sources is None:
            unknown.add(thing.type)
    kinds: dict[str, dict[str, int | None]] = {}
    rows = [
        (kind, n["total"], n["owned"], n["documented"], n["corroborated"], n["connected"])
        for kind, n in sorted(tally.items())
    ]
    for known in coverage(rows):
        kinds[known.type] = {
            "total": known.total,
            "owned": known.owned,
            "documented": known.documented,
            "corroborated": None if known.type in unknown else known.corroborated,
            "connected": known.connected,
        }
    return Measured(
        types=dict(sorted(Counter(t.type for t in present).items())),
        lifecycles=dict(sorted(Counter(t.lifecycle for t in listed).items())),
        relationships=dict(sorted(Counter(kind for _, _, kind in ties).items())),
        kinds=kinds,
    )


def restorable(
    version: Mapping[str, object], current: Mapping[str, object], chosen: Sequence[str] | None
) -> tuple[dict[str, dict[str, object]], list[str]]:
    """What restoring a version would change: each attribute it said that
    the model says otherwise now — {name: {before: now, after: then}} — of
    those chosen, every one when none is; and the attributes the model has
    now that it did not, which a restore cannot take away."""
    then = _attributes(version)
    restored = {
        name: {"before": current.get(name), "after": value}
        for name, value in sorted(then.items())
        if current.get(name) != value and (not chosen or name in chosen)
    }
    kept = sorted(name for name in current if name not in then and (not chosen or name in chosen))
    return restored, kept


def zone(name: str | None) -> ZoneInfo:
    """A time zone by its IANA name; UTC when none or unknown."""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def days_between(since: datetime, until: datetime, tz: ZoneInfo) -> list[date]:
    """The days, in this zone, from `since` to `until`, both included."""
    first, last = since.astimezone(tz).date(), until.astimezone(tz).date()
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


def totals(buckets: Iterable[EvolutionBucket]) -> EvolutionCounts:
    listed = list(buckets)
    return EvolutionCounts(
        **{name: sum(getattr(b, name) for b in listed) for name in EvolutionCounts.model_fields}
    )


# ── the service ──────────────────────────────────────────────────────────────


def _brief(entity: object) -> EntityBrief | None:
    return EntityBrief.model_validate(entity) if entity is not None else None


def operation_read(operation: ModelOperation, entity: EntityBrief | None = None) -> OperationRead:
    return OperationRead(
        id=operation.id,
        kind=operation.kind,
        status=operation.status,
        entity_id=operation.entity_id,
        entity_name=operation.entity_name,
        entity=entity,
        version=operation.version,
        detail=dict(operation.detail or {}),
        reason=operation.reason,
        requested_by=operation.requested_by,
        created_at=operation.created_at,
        finished_at=operation.finished_at,
        run_id=operation.run_id,
        undone_by=operation.undone_by,
        undone_at=operation.undone_at,
    )


def snapshot_read(snapshot: ModelSnapshot) -> SnapshotRead:
    counts = dict(snapshot.counts or {})

    def _ints(name: str) -> dict[str, int]:
        found = counts.get(name)
        return {str(k): int(v) for k, v in found.items()} if isinstance(found, dict) else {}

    kinds = [
        SnapshotKind(
            type=kind, **{k: v for k, v in values.items() if k in SnapshotKind.model_fields}
        )
        for kind, values in sorted((snapshot.measures or {}).items())
        if isinstance(values, dict)
    ]
    return SnapshotRead(
        id=snapshot.id,
        built_at=snapshot.built_at,
        run_id=snapshot.run_id,
        reconstructed=snapshot.reconstructed,
        types=_ints("types"),
        lifecycles=_ints("lifecycles"),
        relationships=_ints("relationships"),
        kinds=kinds,
    )


class EvolutionService:
    """The model's course: what changed, what it was, what it held — and
    the operations that change it, kept. Reads and writes in the caller's
    transaction; the caller commits, then queues the build an operation
    needs (job.queue_model_build)."""

    def __init__(self, repository: EvolutionRepository, assertions: AssertionRepository) -> None:
        self._repository = repository
        self._assertions = assertions

    # What changed ─────────────────────────────────────────────────────────

    async def entity_changes(self, found: Sequence[EntityVersion]) -> list[EntityChangeRead]:
        """A page of the entities' versions, each against the one before."""
        before = await self._repository.previous_contents(found)
        entities = await self._repository.by_ids([v.entity_id for v in found])
        return [
            self._change(version, before.get((version.entity_id, version.version - 1)), entities)
            for version in found
        ]

    @staticmethod
    def _change(
        version: EntityVersion,
        before: Mapping[str, object] | None,
        entities: Mapping[uuid.UUID, object],
    ) -> EntityChangeRead:
        content = dict(version.content or {})
        return EntityChangeRead(
            id=version.id,
            entity=_brief(entities.get(version.entity_id)),
            entity_id=version.entity_id,
            name=str(content.get("name") or ""),
            version=version.version,
            change=change_kind(version.version, before, content),
            fields=diff(before, content),
            recorded_at=version.recorded_at,
            run_id=version.run_id,
        )

    async def summary(
        self, *, since: datetime, until: datetime, timezone: str | None
    ) -> EvolutionSummary:
        """Day by day, in the reader's zone: how many things appeared,
        changed, went, came back; how many relationships appeared, changed,
        went — and the same counts over the period just before, as long."""
        tz = zone(timezone)
        span = until - since
        rows = await self._repository.daily(since=since - span, until=until, tz=str(tz))
        counted: dict[date, Counter[str]] = {}
        for day, kind, n in rows:
            counted.setdefault(day, Counter())[kind] += n
        days = days_between(since, until - timedelta(microseconds=1), tz)
        buckets = [_bucket(day, counted.get(day, Counter())) for day in days]
        before = [
            _bucket(day, counted.get(day, Counter()))
            for day in days_between(since - span, since - timedelta(microseconds=1), tz)
            if day < days[0]
        ]
        return EvolutionSummary(
            since=since,
            until=until,
            timezone=str(tz),
            buckets=buckets,
            totals=totals(buckets),
            previous=totals(before),
        )

    async def material(self, *, now: datetime) -> EvolutionMaterial:
        """The model's recent course, as the insights read it: the versions
        and relationship changes of EVOLUTION_WINDOW, the incidents of
        INCIDENT_WINDOW, and every thing they name as it is now."""
        since, incidents_since = now - EVOLUTION_WINDOW, now - INCIDENT_WINDOW
        recorded = await self._repository.recorded_between(
            since=since, until=now, limit=MAX_EVOLUTION + 1
        )
        moved = await self._repository.changes_between(
            since=since, until=now, limit=MAX_EVOLUTION + 1
        )
        happened = await self._repository.incidents_since(incidents_since, limit=MAX_INCIDENTS)
        truncated = len(recorded) > MAX_EVOLUTION or len(moved) > MAX_EVOLUTION
        versions = [
            EvolvedVersion(
                id=row,
                entity_id=entity,
                version=number,
                change=kind,
                fields=changed,
                recorded_at=at,
                run_id=run,
            )
            for row, entity, number, kind, changed, at, run in recorded[:MAX_EVOLUTION]
        ]
        ties = [
            EvolvedTie(
                id=c.id,
                type=c.type,
                change=c.change,
                from_id=c.from_entity_id,
                to_id=c.to_entity_id,
                recorded_at=c.recorded_at,
                run_id=c.run_id,
            )
            for c in moved[:MAX_EVOLUTION]
        ]
        incidents = [
            EvolvedIncident(id=row, name=name, occurred_at=at, severity=severity, affects=affects)
            for row, name, at, severity, affects in happened
        ]
        named = {
            *(v.entity_id for v in versions),
            *(i for t in ties for i in (t.from_id, t.to_id)),
            *(a for i in incidents for a in i.affects),
        }
        standing = await self._repository.standing_of(named)
        entities = {
            entity.id: EvolvedEntity(
                id=entity.id,
                type=entity.type.value,
                name=entity.name,
                lifecycle=entity.lifecycle.value,
                criticality=_text(entity.attributes.get("criticality")),
                dependents=dependents,
                dependencies=dependencies,
                owners=owners,
            )
            for entity, dependents, dependencies, owners in standing.values()
        }
        return EvolutionMaterial(
            since=since,
            incidents_since=incidents_since,
            until=now,
            began_at=await self._repository.began_at(),
            versions=versions,
            ties=ties,
            incidents=incidents,
            entities=entities,
            truncated=truncated,
        )

    # What it was ──────────────────────────────────────────────────────────

    async def history(self, entity_id: uuid.UUID) -> EntityHistoryRead | None:
        """An entity's whole course: every version against the one before,
        the latest first; its relationships that appeared, changed or went;
        the operations on it."""
        entity = await self._repository.entity(entity_id)
        if entity is None:
            return None
        versions = list(await self._repository.versions_of(entity_id))
        by_number = {v.version: dict(v.content or {}) for v in versions}
        entities = {entity.id: entity}
        changed = [self._change(v, by_number.get(v.version - 1), entities) for v in versions]
        moved = await self._repository.changes_touching(entity_id, limit=HISTORY_RELATIONSHIPS)
        ends = await self._repository.by_ids(
            [i for c in moved for i in (c.from_entity_id, c.to_entity_id)]
        )
        operations = await self._repository.operations_on(entity_id, limit=HISTORY_OPERATIONS)
        return EntityHistoryRead(
            entity=EntityBrief.model_validate(entity),
            versions=changed,
            relationships=[_relationship_change(c, ends) for c in moved],
            operations=[operation_read(o) for o in operations],
            horizon=await self._repository.horizon(),
        )

    async def at(self, entity_id: uuid.UUID, moment: datetime) -> EntityAtRead | None:
        """An entity as it was at a moment: the version in force then, its
        relationships as they stood — `complete` when the history reaches
        that far. None when it does not exist."""
        entity = await self._repository.entity(entity_id)
        if entity is None:
            return None
        version = await self._repository.version_at(entity_id, moment)
        now = {
            (e.from_entity_id, e.to_entity_id, e.type.value): {
                "confidence": e.confidence,
                "origin": e.origin,
            }
            for e in await self._repository.edges_touching(entity_id)
        }
        since = await self._repository.changes_after(moment, entity_id=entity_id)
        then = rewind(now, (_moved(c) for c in since))
        ends = await self._repository.by_ids([i for key in then for i in key[:2]])
        horizon = await self._repository.horizon()
        relationships = sorted(
            (
                RelationshipAtRead(
                    type=kind,
                    direction="outgoing" if start == entity_id else "incoming",
                    other=_brief(ends.get(end if start == entity_id else start)),
                    origin=_text(said.get("origin")),
                    confidence=_number(said.get("confidence")),
                )
                for (start, end, kind), said in then.items()
            ),
            key=lambda r: (r.type, r.direction, r.other.name if r.other else ""),
        )
        before = (
            await self._repository.version_number(entity_id, version.version - 1)
            if version is not None and version.version > 1
            else None
        )
        return EntityAtRead(
            entity=EntityBrief.model_validate(entity),
            moment=moment,
            existed=version is not None
            and version.content.get("lifecycle") != Lifecycle.REMOVED.value,
            version=(
                self._change(version, before.content if before else None, {entity.id: entity})
                if version is not None
                else None
            ),
            content=dict(version.content) if version is not None else None,
            relationships=relationships if version is not None else [],
            complete=horizon is None or moment >= horizon,
        )

    # What it held ─────────────────────────────────────────────────────────

    async def snapshots(
        self, *, since: datetime | None, until: datetime | None, limit: int
    ) -> list[SnapshotRead]:
        return [
            snapshot_read(s)
            for s in await self._repository.snapshots(since=since, until=until, limit=limit)
        ]

    async def snapshot_at(self, moment: datetime) -> SnapshotRead | None:
        """What the model held at a moment: the snapshot in force then —
        or, when none was written by then, one rebuilt from the history,
        if it reaches that far."""
        found = await self._repository.snapshot_at(moment)
        if found is not None:
            return snapshot_read(found)
        rebuilt = await self.rebuild_snapshot(moment)
        if rebuilt is None:
            return None
        return SnapshotRead(
            id=None,
            built_at=moment,
            run_id=None,
            reconstructed=True,
            types=rebuilt.types,
            lifecycles=rebuilt.lifecycles,
            relationships=rebuilt.relationships,
            kinds=[SnapshotKind(type=kind, **values) for kind, values in rebuilt.kinds.items()],
        )

    async def rebuild_snapshot(self, moment: datetime) -> Measured | None:
        """What the model held at a moment, from its history: each entity as
        its version then said it, its relationships rewound. None when the
        history does not reach that far — no version by then, or the
        relationships' history pruned."""
        horizon = await self._repository.horizon()
        if horizon is not None and moment < horizon:
            return None
        things = [
            Thing(id=entity, type=kind, lifecycle=lifecycle, bot=bot)
            for entity, kind, lifecycle, bot in await self._repository.things_at(moment)
        ]
        if not things:
            return None
        now: dict[Edge, Mapping[str, object]] = {
            key: {} for key in await self._repository.edge_keys()
        }
        since = await self._repository.changes_after(moment)
        edges = rewind(now, (_moved(c) for c in since))
        return measure(things, edges)

    async def record(self, *, now: datetime, run_id: uuid.UUID | None) -> ModelSnapshot:
        """What the model holds now, written down — and, the first time, the
        weeks before, rebuilt from its history."""
        first = await self._repository.latest_snapshot() is None
        measured = measure(
            (
                Thing(id=entity, type=kind, lifecycle=lifecycle, bot=bot, sources=sources)
                for entity, kind, lifecycle, bot, sources in await self._repository.things_now()
            ),
            await self._repository.edge_keys(),
        )
        if first:
            await self.backfill(now=now)
        return await self._repository.put_snapshot(
            measured.counts(), measured.kinds, at=now, run_id=run_id
        )

    async def backfill(self, *, now: datetime, weeks: int = BACKFILL_WEEKS) -> int:
        """A snapshot a week, rebuilt from the history, for the weeks before
        the first one written — what a workspace's course shows from its
        first day with LEKA-383. Those the history does not reach are not
        written. For a workspace with no snapshot yet."""
        written = 0
        for week in range(weeks, 0, -1):
            moment = now - timedelta(weeks=week)
            measured = await self.rebuild_snapshot(moment)
            if measured is None:
                continue
            await self._repository.put_snapshot(
                measured.counts(), measured.kinds, at=moment, run_id=None, reconstructed=True
            )
            written += 1
        return written

    # The operations ───────────────────────────────────────────────────────

    async def operations(self, filters: OperationFilters, *, limit: int) -> list[OperationRead]:
        found = await self._repository.operations(filters, limit=limit)
        entities = await self._repository.by_ids([o.entity_id for o in found if o.entity_id])
        return [
            operation_read(o, _brief(entities.get(o.entity_id)) if o.entity_id else None)
            for o in found
        ]

    async def restore(
        self,
        entity_id: uuid.UUID,
        version: int,
        *,
        attributes: Sequence[str] | None,
        reason: str | None,
        by: uuid.UUID | None,
        now: datetime,
    ) -> OperationRead | None:
        """Put an entity's attributes back as a version said them: a fact
        validated for each, which the next build applies over what the
        sources say — an earlier restore of the same attribute replaced.
        None when the entity or the version does not exist; refused when
        the entity is removed, or the version restores nothing."""
        entity = await self._repository.entity(entity_id)
        if entity is None:
            return None
        found = await self._repository.version_number(entity_id, version)
        if found is None:
            return None
        if entity.lifecycle is Lifecycle.REMOVED:
            raise OperationRefusedError("removed")
        if version == entity.version:
            raise OperationRefusedError("current")
        restored, kept = restorable(found.content, dict(entity.attributes), attributes)
        if not restored:
            raise OperationRefusedError("nothing_to_restore")
        operation = ModelOperation(
            kind="restore",
            status="applied",
            entity_id=entity.id,
            entity_name=entity.name[:500],
            version=version,
            detail={"attributes": restored, "not_restored": kept, "from_version": entity.version},
            reason=reason,
            requested_by=by,
            created_at=now,
            finished_at=now,
        )
        await self._repository.add_operation(operation)
        for name, values in restored.items():
            # One restore holds an attribute at a time: the latest.
            await self._assertions.remove_restores(entity.id, name)
            await self._assertions.put(
                Assertion(
                    id=uuid.uuid4(),
                    kind="attribute",
                    rule=RESTORE_RULE,
                    confidence=1.0,
                    entity_id=entity.id,
                    attribute=name,
                    value=values["after"],
                    overrides=True,
                    evidence=f"{entity.name} as version {version} said it",
                    provenance={
                        "operation_id": str(operation.id),
                        "decided_via": "restore",
                        "decided_at": now.isoformat(),
                        "decided_by": str(by) if by else None,
                        "version": version,
                    },
                )
            )
        return operation_read(operation, EntityBrief.model_validate(entity))

    async def undo(
        self,
        operation_id: uuid.UUID,
        *,
        reason: str | None,
        by: uuid.UUID | None,
        now: datetime,
    ) -> OperationRead | None:
        """A restore taken back: its facts withdrawn — the next build shows
        what the sources say. Refused for a rebuild, or one already undone."""
        operation = await self._repository.operation(operation_id)
        if operation is None:
            return None
        if operation.kind != "restore":
            raise OperationRefusedError("not_undoable")
        if operation.status != "applied":
            raise OperationRefusedError("already_undone")
        await self._assertions.remove_for_operation(operation.id)
        operation.status = "undone"
        if reason:
            operation.detail = {**dict(operation.detail or {}), "undo_reason": reason}
        operation.undone_by = by
        operation.undone_at = now
        await self._repository.flush()
        entity = await self._repository.entity(operation.entity_id) if operation.entity_id else None
        return operation_read(operation, _brief(entity))

    async def rebuild(
        self, *, reason: str | None, by: uuid.UUID | None, now: datetime
    ) -> OperationRead:
        """The model built again, though nothing new came: queued — the
        next build takes it, done or failed, and says what it did. One
        already queued answers."""
        queued = await self._repository.queued_rebuild()
        if queued is not None:
            return operation_read(queued)
        operation = ModelOperation(
            kind="rebuild",
            status="queued",
            reason=reason,
            requested_by=by,
            detail={},
            created_at=now,
        )
        await self._repository.add_operation(operation)
        return operation_read(operation)


def _bucket(day: date, counted: Mapping[str, int]) -> EvolutionBucket:
    return EvolutionBucket(
        day=day,
        **{name: int(counted.get(name, 0)) for name in EvolutionCounts.model_fields},
    )


def _moved(change: RelationshipChange) -> Moved:
    return Moved(
        from_id=change.from_entity_id,
        to_id=change.to_entity_id,
        type=change.type,
        change=change.change,
        before=change.before,
    )


def _relationship_change(
    change: RelationshipChange, ends: Mapping[uuid.UUID, object]
) -> RelationshipChangeRead:
    return RelationshipChangeRead(
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


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def utc(moment: datetime) -> datetime:
    """A moment without a zone is UTC's."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
