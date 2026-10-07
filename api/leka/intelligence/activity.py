"""What happened, and what LEKA did (LEKA-383): Activité.

Every source of the period, as one course:

    information   the model built — what it created, changed, brought back,
                  the relationships that came and went, said once per build
                  — a thing no source shows any more; a deployment, a
                  change, a release in the company's systems; a source
                  added, tested, synchronised (LEKA-344) — an alert when it
                  fails
    action        an analysis LEKA ran; a proposal it made (LEKA-380); a
                  decision — a person's or the workspace's policy — on a
                  proposal, a conflict (LEKA-382), a restore or a rebuild
    alert         a finding LEKA raised (LEKA-377 and after); a conflict
                  between sources it found
    incident      an incident in the company's systems

Each counts as many events as it stands for: a build, its changes. Over
the period, and over the one before, as long: how many, of what, day by day
in the reader's zone; the services and applications most concerned; who
decided most. Nothing is invented: what happened is what the model, the
analyses and the decisions kept.

Pure first — the assembly — then the service that reads each source.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from leka.connectors import Source, SourceEvent
from leka.intelligence.models import EnrichmentCandidate, Finding, KnowledgeConflict
from leka.intelligence.repository import ActivityRepository
from leka.intelligence.schemas import (
    ActivityBucket,
    ActivityCount,
    ActivityItem,
    ActivityPerson,
    ActivityRead,
    ActivityStats,
    ActivityTop,
    SubjectRead,
)
from leka.knowledge import Entity, EntityType, EvolutionRepository

# What each source gives at most, for a period and the one before.
MAX_READ = 2_000
MAX_LATEST = 100
TOP = 5
# What "Top services concernés" is about.
CONCERNED = frozenset({"service", "application"})
EVENTS = (EntityType.INCIDENT, EntityType.DEPLOYMENT, EntityType.CHANGE, EntityType.RELEASE)
CATEGORIES = ("information", "action", "alert", "incident")
# What a build's item names of what it changed, at most.
NAMED = 3


@dataclass(frozen=True)
class Happening:
    """One thing that happened, before it is assembled."""

    key: str
    at: datetime
    category: str
    kind: str
    subject: SubjectRead | None = None
    params: Mapping[str, object] = field(default_factory=dict)
    count: int = 1
    by: uuid.UUID | None = None
    via: str = "leka"
    # The services and applications it concerns.
    concerns: tuple[SubjectRead, ...] = ()


# ── pure ─────────────────────────────────────────────────────────────────────


def _day(at: datetime, tz: object) -> date:
    return at.astimezone(tz).date()  # type: ignore[arg-type]


def assemble(
    happenings: Iterable[Happening],
    *,
    since: datetime,
    until: datetime,
    tz: object,
    days: Sequence[date],
    waiting: int,
    people: Mapping[uuid.UUID, tuple[str, str | None]],
    limit: int,
) -> ActivityRead:
    """The period's activity — and the period before, as long, read from
    the same happenings."""
    span = until - since
    now = [h for h in happenings if since <= h.at < until]
    before = [h for h in happenings if since - span <= h.at < since]

    def total(listed: Iterable[Happening], category: str | None = None) -> int:
        return sum(h.count for h in listed if category is None or h.category == category)

    def leka(listed: Iterable[Happening]) -> int:
        """What LEKA did — its policy's decisions with it; not people's."""
        return sum(h.count for h in listed if h.category == "action" and h.via != "person")

    def deciders(listed: Iterable[Happening]) -> Counter[uuid.UUID]:
        return Counter(h.by for h in listed if h.by is not None and h.via == "person")

    buckets: dict[date, Counter[str]] = {day: Counter() for day in days}
    for happening in now:
        day = _day(happening.at, tz)
        if day in buckets:
            buckets[day][happening.category] += happening.count
    concerned_now, concerned_before = _concerned(now), _concerned(before)
    deciding_now, deciding_before = deciders(now), deciders(before)
    top = sorted(concerned_now.items(), key=lambda item: (-item[1][1], item[1][0].name))[:TOP]
    return ActivityRead(
        since=since,
        until=until,
        timezone=str(tz),
        stats=ActivityStats(
            events=ActivityCount(value=total(now), previous=total(before)),
            actions=ActivityCount(value=leka(now), previous=leka(before)),
            incidents=ActivityCount(
                value=total(now, "incident"), previous=total(before, "incident")
            ),
            waiting=waiting,
            people=ActivityCount(value=len(deciding_now), previous=len(deciding_before)),
        ),
        buckets=[
            ActivityBucket(day=day, **{c: counted[c] for c in CATEGORIES})
            for day, counted in buckets.items()
        ],
        categories={category: total(now, category) for category in CATEGORIES},
        latest=[
            _item(h, people) for h in sorted(now, key=lambda h: (h.at, h.key), reverse=True)[:limit]
        ],
        top=[
            ActivityTop(
                subject=subject,
                count=count,
                previous=concerned_before.get(key, (subject, 0))[1],
            )
            for key, (subject, count) in top
        ],
        people=[
            ActivityPerson(
                user_id=user,
                name=people.get(user, ("", None))[0] or str(user),
                role=people.get(user, ("", None))[1],
                count=count,
                previous=deciding_before.get(user, 0),
            )
            for user, count in sorted(
                deciding_now.items(), key=lambda item: (-item[1], str(item[0]))
            )[:TOP]
        ],
    )


def _concerned(listed: Iterable[Happening]) -> dict[str, tuple[SubjectRead, int]]:
    counted: dict[str, tuple[SubjectRead, int]] = {}
    for happening in listed:
        for subject in {s.id: s for s in happening.concerns}.values():
            key = str(subject.id)
            held = counted.get(key)
            counted[key] = (subject, (held[1] if held else 0) + happening.count)
    return counted


def _item(happening: Happening, people: Mapping[uuid.UUID, tuple[str, str | None]]) -> ActivityItem:
    by = happening.by
    return ActivityItem(
        id=happening.key,
        at=happening.at,
        category=happening.category,
        kind=happening.kind,
        count=happening.count,
        subject=happening.subject,
        params=dict(happening.params),
        by=by,
        by_name=people.get(by, (None, None))[0] if by else None,
        via=happening.via,
    )


def _subject(entity: Entity | None) -> SubjectRead | None:
    if entity is None:
        return None
    return SubjectRead(type="entity", id=entity.id, name=entity.name, kind=entity.type.value)


def _moment(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _user(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


# ── what each source says ────────────────────────────────────────────────────


@dataclass
class _Build:
    """What one build changed, gathered."""

    at: datetime
    counts: Counter[str] = field(default_factory=Counter)
    names: list[str] = field(default_factory=list)
    concerns: dict[str, SubjectRead] = field(default_factory=dict)


def builds(
    versions: Sequence[
        tuple[uuid.UUID, uuid.UUID, int, str, list[str], datetime, uuid.UUID | None]
    ],
    ties: Sequence[tuple[str, datetime, uuid.UUID | None]],
    entities: Mapping[uuid.UUID, Entity],
) -> list[Happening]:
    """What each build changed, as one item — and each thing no source
    shows any more, as its own."""
    grouped: dict[str, _Build] = {}
    happenings: list[Happening] = []

    def of(run: uuid.UUID | None, at: datetime) -> _Build:
        build = grouped.setdefault(str(run or at.isoformat()), _Build(at=at))
        build.at = max(build.at, at)
        return build

    for row, entity_id, number, kind, _, at, run in versions:
        entity = entities.get(entity_id)
        if kind == "removed":
            happenings.append(
                Happening(
                    key=f"removed:{row}",
                    at=at,
                    category="information",
                    kind="entity_removed",
                    subject=_subject(entity),
                    params={"name": entity.name if entity else "", "version": number},
                    via="source",
                    concerns=_concerns(entity),
                )
            )
            continue
        build = of(run, at)
        build.counts[kind] += 1
        if entity is not None and len(build.names) < NAMED and entity.name not in build.names:
            build.names.append(entity.name)
        for subject in _concerns(entity):
            build.concerns[str(subject.id)] = subject
    for change, at, run in ties:
        of(run, at).counts[f"relationships_{change}"] += 1
    happenings += [
        Happening(
            key=f"model:{key}",
            at=build.at,
            category="information",
            kind="model_built",
            params={**dict(sorted(build.counts.items())), "names": build.names},
            count=sum(build.counts.values()),
            via="source",
            concerns=tuple(build.concerns.values()),
        )
        for key, build in grouped.items()
    ]
    return happenings


# What happens to a source that is an alert, not news.
SOURCE_ALERTS = frozenset({"test_failed", "sync_failed", "health_changed", "disabled"})


def source_events(found: Sequence[tuple[SourceEvent, Source | None]]) -> list[Happening]:
    """What happened to the sources: added, tested, synchronised — failing,
    an alert."""
    return [
        Happening(
            key=f"source_event:{event.id}",
            at=event.created_at,
            category="alert" if event.type.value in SOURCE_ALERTS else "information",
            kind="source_event",
            subject=SubjectRead(
                type="source",
                id=event.source_id,
                name=source.name if source else "",
                kind=source.kind.value if source else None,
            ),
            params={"type": event.type.value, "name": source.name if source else ""},
            by=event.actor_user_id,
            via="person" if event.actor_user_id else "source",
        )
        for event, source in found
    ]


def _concerns(entity: Entity | None) -> tuple[SubjectRead, ...]:
    if entity is None or entity.type.value not in CONCERNED:
        return ()
    subject = _subject(entity)
    return (subject,) if subject else ()


def events(
    found: Sequence[tuple[Entity, list[uuid.UUID]]], others: Mapping[uuid.UUID, Entity]
) -> list[Happening]:
    """The incidents, deployments, changes and releases of the company's
    systems — each about what it affects, or belongs to."""
    happenings: list[Happening] = []
    for event, concerning in found:
        if event.occurred_at is None:
            continue
        about = [others[i] for i in concerning if i in others]
        main = next((e for e in about if e.type.value in CONCERNED), about[0] if about else None)
        attributes = event.attributes or {}
        happenings.append(
            Happening(
                key=f"{event.type.value}:{event.id}",
                at=event.occurred_at,
                category="incident" if event.type is EntityType.INCIDENT else "information",
                kind=event.type.value,
                subject=_subject(main) or _subject(event),
                params={
                    "name": event.name,
                    "event_id": str(event.id),
                    **{
                        k: attributes[k]
                        for k in ("state", "severity", "priority", "environment", "version")
                        if isinstance(attributes.get(k), str | int | float)
                    },
                },
                via="source",
                concerns=tuple(s for e in about for s in _concerns(e)),
            )
        )
    return happenings


def _finding_subject(row: Finding | EnrichmentCandidate | KnowledgeConflict) -> SubjectRead | None:
    kind = getattr(row, "subject_type", "entity")
    if kind not in ("entity", "context", "source", "coverage", "column", "workspace"):
        return None
    return SubjectRead(
        type=kind,
        id=row.subject_id,
        name=row.subject_name,
        kind=row.subject_kind,
    )


def _entity_concerns(subject: SubjectRead | None) -> tuple[SubjectRead, ...]:
    return (subject,) if subject and subject.type == "entity" and subject.kind in CONCERNED else ()


def findings(found: Sequence[Finding]) -> list[Happening]:
    """What LEKA raised: a finding, as Insights words it."""
    return [
        Happening(
            key=f"finding:{f.id}",
            at=f.first_seen_at,
            category="alert",
            kind="finding",
            subject=(subject := _finding_subject(f)),
            params={
                "code": f.code,
                "category": f.category,
                "severity": f.severity,
                "statement": f.statement,
                "finding_id": str(f.id),
                "params": dict(f.params or {}),
            },
            concerns=_entity_concerns(subject),
        )
        for f in found
    ]


def candidates(found: Sequence[EnrichmentCandidate]) -> list[Happening]:
    """What LEKA proposed, and what was decided of it — each in its period."""
    happenings: list[Happening] = []
    for c in found:
        subject = SubjectRead(
            type="entity", id=c.subject_id, name=c.subject_name, kind=c.subject_kind
        )
        said = {
            "family": c.family,
            "code": c.code,
            "statement": c.statement,
            "candidate_id": str(c.id),
            "attribute": c.attribute,
            "relationship": c.relationship,
        }
        happenings.append(
            Happening(
                key=f"proposal:{c.id}",
                at=c.first_seen_at,
                category="action",
                kind="proposal",
                subject=subject,
                params=said,
                concerns=_entity_concerns(subject),
            )
        )
        if c.decided_at is not None and c.status in ("accepted", "rejected"):
            happenings.append(
                Happening(
                    key=f"decision:{c.id}",
                    at=c.decided_at,
                    category="action",
                    kind="decision",
                    subject=subject,
                    params={**said, "status": c.status},
                    by=c.decided_by,
                    via="policy" if c.decided_via == "policy" else "person",
                    concerns=_entity_concerns(subject),
                )
            )
    return happenings


def conflicts(found: Sequence[KnowledgeConflict]) -> list[Happening]:
    """What the sources disagree on, found — and each decision on it."""
    happenings: list[Happening] = []
    for c in found:
        subject = SubjectRead(
            type="entity", id=c.subject_id, name=c.subject_name, kind=c.subject_kind
        )
        said = {"about": c.about, "statement": c.statement, "conflict_id": str(c.id)}
        happenings.append(
            Happening(
                key=f"conflict:{c.id}",
                at=c.first_seen_at,
                category="alert",
                kind="conflict",
                subject=subject,
                params=said,
                concerns=_entity_concerns(subject),
            )
        )
        for n, entry in enumerate(c.history or []):
            at = _moment(entry.get("at"))
            if at is None or entry.get("via") != "person":
                continue
            happenings.append(
                Happening(
                    key=f"conflict_decision:{c.id}:{n}",
                    at=at,
                    category="action",
                    kind="conflict_decision",
                    subject=subject,
                    params={
                        **said,
                        "status": str(entry.get("status") or ""),
                        **({"value": entry["value"]} if "value" in entry else {}),
                    },
                    by=_user(entry.get("by")),
                    via="person",
                    concerns=_entity_concerns(subject),
                )
            )
    return happenings


# ── the service ──────────────────────────────────────────────────────────────


class ActivityService:
    """Reads each source of the period and the one before, and assembles
    them. Reads only."""

    def __init__(self, repository: ActivityRepository, evolution: EvolutionRepository) -> None:
        self._repository = repository
        self._evolution = evolution

    async def read(
        self, *, since: datetime, until: datetime, tz: object, days: Sequence[date], limit: int
    ) -> ActivityRead:
        start = since - (until - since)
        happenings: list[Happening] = []

        versions = await self._evolution.recorded_between(since=start, until=until, limit=MAX_READ)
        ties = await self._evolution.changes_between(since=start, until=until, limit=MAX_READ)
        happened = await self._evolution.events_between(
            since=start, until=until, kinds=EVENTS, limit=MAX_READ
        )
        operated = await self._evolution.operations_between(since=start, until=until)
        named = await self._evolution.by_ids(
            list(
                {v[1] for v in versions}
                | {i for _, about in happened for i in about}
                | {o.entity_id for o in operated if o.entity_id}
            )
        )
        happenings += builds(versions, [(t.change, t.recorded_at, t.run_id) for t in ties], named)
        happenings += events(happened, named)

        for run in await self._repository.runs_between(since=start, until=until):
            if run.finished_at is None:
                continue
            happenings.append(
                Happening(
                    key=f"analysis:{run.id}",
                    at=run.finished_at,
                    category="action",
                    kind="analysis",
                    params={
                        "trigger": run.trigger,
                        **{k: int(v) for k, v in (run.counts or {}).items() if isinstance(v, int)},
                    },
                    by=run.requested_by,
                )
            )
        happenings += source_events(
            await self._repository.source_events_between(since=start, until=until, limit=MAX_READ)
        )
        happenings += findings(
            await self._repository.findings_between(since=start, until=until, limit=MAX_READ)
        )
        happenings += candidates(
            await self._repository.candidates_between(since=start, until=until, limit=MAX_READ)
        )
        happenings += conflicts(
            await self._repository.conflicts_between(since=start, until=until, limit=MAX_READ)
        )
        for operation in operated:
            entity = named.get(operation.entity_id) if operation.entity_id else None
            subject = _subject(entity) or (
                SubjectRead(
                    type="entity",
                    id=operation.entity_id,
                    name=operation.entity_name or "",
                    kind=None,
                )
                if operation.entity_id
                else None
            )
            said = {
                "operation_id": str(operation.id),
                "status": operation.status,
                "version": operation.version,
                "name": operation.entity_name,
            }
            happenings.append(
                Happening(
                    key=f"{operation.kind}:{operation.id}",
                    at=operation.created_at,
                    category="action",
                    kind=operation.kind,
                    subject=subject,
                    params=said,
                    by=operation.requested_by,
                    via="person",
                )
            )
            if operation.undone_at is not None:
                happenings.append(
                    Happening(
                        key=f"undo:{operation.id}",
                        at=operation.undone_at,
                        category="action",
                        kind="undo",
                        subject=subject,
                        params=said,
                        by=operation.undone_by,
                        via="person",
                    )
                )

        people = await self._repository.people(list({h.by for h in happenings if h.by is not None}))
        return assemble(
            happenings,
            since=since,
            until=until,
            tz=tz,
            days=days,
            waiting=await self._repository.waiting(),
            people=people,
            limit=limit,
        )
