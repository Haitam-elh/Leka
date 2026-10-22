"""The enterprise skill library (LEKA-401): what LEKA's agents, its
workflows and its analyst call to read the company model the way an expert
of each domain would — each a skill (capabilities/skills.py): its contract,
its permission, the kinds of things it reads, what must be connected, its
limits; run through the one runtime, checked and kept.

    domain                   skill                       what it gives
    repository analysis      repository-profile          what a repository is, who keeps it,
                                                         what it builds, how alive it is
    code review              change-review               a change, a merge, a deployment: what
                                                         it touched, how far it reaches, what
                                                         followed it
    testing                  test-scope                  what to test when a thing changes: its
                                                         dependents, the most critical first,
                                                         the business they carry
    security                 security-posture            what is exposed, public, unowned;
                                                         where personal data and secrets are
    documentation            documentation-coverage      how much is documented, how fresh;
                                                         the critical things without any
    architecture             blast-radius                what a failure of a thing reaches, up
                                                         to the business
    incident investigation   incident-history            a thing's incidents: how many, how
                                                         bad, how long to recover, what recurs
    infrastructure           infrastructure-inventory    the resources: where, what state,
                                                         whose; the unowned and the exposed
    data analysis            data-landscape              the databases: what they hold, who
                                                         uses them, the sensitive objects
    release and deployment   delivery-metrics            deployment frequency, change failure
                                                         rate, time to recover — DORA's tiers

Each reads; none acts. Each says what it read, citable (`cited`), and what
it concluded, as signals (`signals`): a code, a level, a sentence — what a
workflow's condition reads, what an agent weighs. Each computes from what
the connected sources gave LEKA — never a live read of a tool: what no
source says, it cannot know, and says so.

Read and judged apart: the reads (`async def`) take a session; the
judgements (`judge_*`) are pure, tested without a database.
"""

from __future__ import annotations

import re
import statistics
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol, get_args

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import (
    Assessed,
    Call,
    Cited,
    CitedSource,
    Signal,
    Skill,
    UnknownThingError,
    register,
)
from leka.connectors import Source
from leka.governance import Permission
from leka.intelligence.repository import IntelligenceRepository
from leka.knowledge import (
    DataFilters,
    DeploymentRead,
    Entity,
    EntityBrief,
    EntityRepository,
    EntityType,
    EventFilters,
    GraphRepository,
    Impact,
    IncidentRead,
    InfrastructureFilters,
    InfrastructureRead,
    KnowledgeService,
    Lifecycle,
    RelationshipType,
)

VERSION = "1.0.0"
# What a list gives back, at most; what is read to compute, at most.
MOST = 25
MOST_READ = 500
ID = "an id as a read gave it: « entity:… », « event:… », or the uuid alone."

# Connected for it to be of use.
CODE_HOSTS = ("github", "gitlab", "bitbucket")
CLOUDS = ("aws", "azure", "gcp")
DATABASES = ("postgresql", "mysql", "mariadb", "sqlserver", "oracle", "mongodb", "supabase")
DOCUMENTATION = ("confluence", "notion", "microsoft_365", "google_workspace", "guru", "slab")

# What a thing is that happens: cited as an event.
HAPPENINGS = frozenset(
    {
        EntityType.DEPLOYMENT,
        EntityType.CHANGE,
        EntityType.RELEASE,
        EntityType.PULL_REQUEST,
        EntityType.COMMIT,
        EntityType.INCIDENT,
        EntityType.ISSUE,
    }
)
# How critical, the most first; a source's own word ranks last.
CRITICALITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEVERE = frozenset({"critical", "high"})
# A resource that does not run: said, not counted as an alarm.
NOT_RUNNING = frozenset({"stopped", "stopping", "terminated", "deleted", "deleting", "disabled"})
# Data categories that are secrets, not merely personal.
SECRETS = frozenset({"secret", "credentials", "credential", "password", "token", "key"})


# ── shared ───────────────────────────────────────────────────────────────────


class Named(BaseModel):
    """A thing, as a skill names it: its id to cite, its name, its kind."""

    id: str
    name: str
    type: str


class Thing(Protocol):
    """Anything a read gives back that names a thing: its id, its name."""

    @property
    def id(self) -> uuid.UUID: ...

    @property
    def name(self) -> str: ...


def _type(thing: object, default: str = "thing") -> str:
    said = getattr(thing, "type", None)
    if said is None:
        return default
    return str(getattr(said, "value", said))


def id_of(said: object) -> uuid.UUID | None:
    """The thing an id names — « entity:… », « event:… », or the uuid alone."""
    text = str(said or "").strip()
    if ":" in text:
        text = text.split(":", 1)[1]
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def level_of(said: object) -> str | None:
    """A criticality as LEKA ranks it — critical, high, medium, low — or the
    source's own word, lower case; none when nothing is said."""
    if said is None:
        return None
    text = str(getattr(said, "level", said) or "").strip().lower()
    return text or None


def rank(level: str | None) -> int:
    return CRITICALITY.get(level or "", 4 if level else 5)


def severity_of(incident: IncidentRead) -> str:
    """How bad an incident was, in one scale whatever its tool said:
    sev1, P1, critical, highest → critical; sev2, P2, high, major → high."""
    for said in (incident.severity, incident.priority, incident.urgency):
        text = str(said or "").strip().lower().replace("-", "").replace(" ", "")
        if not text:
            continue
        if text in {"sev1", "sev0", "p1", "p0", "1", "0", "critical", "highest", "blocker"}:
            return "critical"
        if text in {"sev2", "p2", "2", "high", "major", "urgent"}:
            return "high"
        if text in {"sev3", "p3", "3", "medium", "normal", "moderate"}:
            return "medium"
        if text in {"sev4", "sev5", "p4", "p5", "4", "5", "low", "lowest", "minor", "trivial"}:
            return "low"
    return "unknown"


def signal(
    code: str, level: Literal["info", "warning", "critical"], text: str, **params: Any
) -> Signal:
    return Signal(code=code, level=level, text=text, params=params)


class Citer:
    """What one skill read, by the id it may be cited by — each thing with
    the sources that said it."""

    def __init__(self, sources: Mapping[uuid.UUID, tuple[CitedSource, ...]] | None = None) -> None:
        self.read: dict[str, Cited] = {}
        self.sources = dict(sources or {})

    def thing(self, thing: Thing, *, kind: str | None = None, detail: str | None = None) -> str:
        kind = kind or _type(thing)
        happening = kind in {t.value for t in HAPPENINGS}
        cited = Cited(
            id=f"{'event' if happening else 'entity'}:{thing.id}",
            kind="event" if happening else "entity",
            label=thing.name,
            ref_type=kind,
            ref_id=thing.id,
            sources=list(self.sources.get(thing.id, ())),
            detail=detail,
        )
        self.read.setdefault(cited.id, cited)
        return cited.id

    def named(self, thing: Thing, *, kind: str | None = None) -> Named:
        kind = kind or _type(thing)
        return Named(id=self.thing(thing, kind=kind), name=thing.name, type=kind)

    @property
    def cited(self) -> list[Cited]:
        return list(self.read.values())


async def sources_of(
    session: AsyncSession, workspace_id: uuid.UUID, entities: Iterable[Entity]
) -> dict[uuid.UUID, tuple[CitedSource, ...]]:
    """Each thing's sources, by its provenance."""
    rows = await session.execute(
        select(Source.id, Source.kind, Source.name).where(Source.workspace_id == workspace_id)
    )
    named = {ident: (kind.value, name) for ident, kind, name in rows.tuples().all()}
    found: dict[uuid.UUID, tuple[CitedSource, ...]] = {}
    for entity in entities:
        said = (entity.provenance or {}).get("sources") or []
        refs: dict[uuid.UUID, CitedSource] = {}
        for item in said if isinstance(said, list) else []:
            source = id_of(item.get("source_id") if isinstance(item, dict) else None)
            if source is not None:
                kind, name = named.get(source, (None, None))
                refs[source] = CitedSource(id=source, kind=kind, name=name)
        found[entity.id] = tuple(refs.values())
    return found


async def one(
    call: Call, said: str, types: Sequence[EntityType] = ()
) -> tuple[EntityRepository, Entity]:
    """The thing an id names — of these kinds when some are said — or
    UnknownThingError: refused, said so."""
    repository = EntityRepository(call.session, call.workspace_id)
    ident = id_of(said)
    entity = (await repository.by_ids([ident])).get(ident) if ident else None
    if entity is None or entity.lifecycle is Lifecycle.REMOVED:
        raise UnknownThingError("LEKA knows no such thing.")
    if types and entity.type not in types:
        kinds = ", ".join(t.value for t in types)
        raise UnknownThingError(f"{entity.name} is a {_type(entity)}, not a {kinds}.")
    return repository, entity


async def listed(session: AsyncSession, statement: Any, most: int = MOST_READ) -> list[Entity]:
    return list((await session.scalars(statement.limit(most))).all())


async def counted(session: AsyncSession, statement: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)


async def neighbours(
    call: Call, things: Sequence[uuid.UUID], kinds: frozenset[EntityType]
) -> list[Entity]:
    """What these things are tied to, of these kinds — removed things left
    out."""
    graph = GraphRepository(call.session, call.workspace_id)
    edges = await graph.around(list(things), list(RelationshipType))
    ids = {e.to_entity_id if e.from_entity_id in things else e.from_entity_id for e in edges}
    others = await EntityRepository(call.session, call.workspace_id).by_ids(list(ids - set(things)))
    return sorted(
        (o for o in others.values() if o.type in kinds and o.lifecycle is not Lifecycle.REMOVED),
        key=lambda o: o.name,
    )


def business(impact: Impact, citer: Citer) -> list[Named]:
    """The capabilities and processes a reach holds, each once."""
    found: dict[uuid.UUID, Named] = {}
    for tie in (*impact.capabilities, *impact.processes):
        found.setdefault(tie.entity.id, citer.named(tie.entity))
    return list(found.values())


class OneAsked(BaseModel):
    id: str = Field(max_length=100, description=ID)


# ── repository analysis: repository-profile ──────────────────────────────────


class RepositoryAsked(OneAsked):
    days: int = Field(default=30, ge=1, le=180, description="How far back its activity is read.")


class Activity(BaseModel):
    merges: int
    releases: int
    deployments: int
    last_at: datetime | None


class RepositoryProfile(Assessed):
    of: str
    languages: list[str]
    visibility: str | None
    default_branch: str | None
    topics: list[str]
    archived: bool
    owners: list[str]
    maintainers: list[str]
    builds: list[Named] = Field(description="The services and applications it is tied to.")
    activity: Activity
    open_findings: int


def judge_repository(profile: RepositoryProfile, days: int) -> list[Signal]:
    said: list[Signal] = []
    if profile.archived:
        said.append(signal("repository.archived", "info", f"{profile.of} is archived."))
    if (profile.visibility or "").lower() == "public":
        said.append(
            signal("repository.public", "warning", f"{profile.of} is public: anyone reads it.")
        )
    if not profile.owners and not profile.maintainers:
        said.append(
            signal("repository.unowned", "warning", f"No team or person answers for {profile.of}.")
        )
    if not profile.archived and profile.activity.merges + profile.activity.releases == 0:
        said.append(
            signal(
                "repository.inactive",
                "info",
                f"Nothing merged or released in {profile.of} in {days} days.",
                days=days,
            )
        )
    if profile.open_findings:
        said.append(
            signal(
                "repository.open_findings",
                "info",
                f"LEKA has {profile.open_findings} open point(s) on {profile.of}.",
                count=profile.open_findings,
            )
        )
    return said


async def repository_profile(asked: RepositoryAsked, call: Call) -> RepositoryProfile:
    repository, entity = await one(call, asked.id, (EntityType.REPOSITORY,))
    knowledge = KnowledgeService(repository)
    held = await knowledge.responsibility(entity)
    builds = await neighbours(
        call, [entity.id], frozenset({EntityType.SERVICE, EntityType.APPLICATION})
    )
    timeline = await knowledge.timeline(
        entity,
        since=call.now - timedelta(days=asked.days),
        until=call.now,
        kinds=[EntityType.PULL_REQUEST, EntityType.RELEASE, EntityType.DEPLOYMENT],
        limit=MOST_READ,
    )
    kinds = Counter(e.kind for e in timeline.events)
    findings = await IntelligenceRepository(call.session, call.workspace_id).about(
        [entity.id], limit=50
    )
    citer = Citer(await sources_of(call.session, call.workspace_id, [entity, *builds]))
    citer.thing(entity)
    attributes = entity.attributes or {}
    languages = attributes.get("languages") or attributes.get("language") or []
    topics = attributes.get("topics")
    profile = RepositoryProfile(
        of=entity.name,
        languages=[str(x) for x in (languages if isinstance(languages, list) else [languages])][
            :10
        ],
        visibility=str(attributes["visibility"]) if attributes.get("visibility") else None,
        default_branch=(
            str(attributes["default_branch"]) if attributes.get("default_branch") else None
        ),
        topics=[str(t) for t in topics][:10] if isinstance(topics, list) else [],
        archived=bool(attributes.get("archived")),
        owners=[t.entity.name for t in held.owners],
        maintainers=[t.entity.name for t in held.maintainers],
        builds=[citer.named(b) for b in builds[:MOST]],
        activity=Activity(
            merges=kinds["merge"],
            releases=kinds["release"],
            deployments=kinds["deployment"],
            last_at=max((e.at for e in timeline.events), default=None),
        ),
        open_findings=sum(1 for f in findings if f.status == "open"),
    )
    profile.signals = judge_repository(profile, asked.days)
    profile.cited = citer.cited
    return profile


# ── code review: change-review ───────────────────────────────────────────────


class IncidentSaid(BaseModel):
    id: str
    name: str
    severity: str
    opened_at: datetime | None
    how: Literal["caused", "followed"] = Field(
        description="caused: its source says so; followed: opened within 72 hours on what it "
        "touched."
    )


class Reach(BaseModel):
    dependents: list[Named]
    applications: list[Named]
    business: list[Named]


class ChangeReview(Assessed):
    of: str
    kind: str
    at: datetime | None
    state: str | None
    environment: str | None
    by: str | None
    touches: list[Named]
    critical_targets: list[str] = Field(description="What it touched that is critical or high.")
    reach: Reach
    incidents_after: list[IncidentSaid]


AFTER = timedelta(hours=72)


def judge_change(review: ChangeReview) -> list[Signal]:
    said: list[Signal] = []
    if review.incidents_after:
        said.append(
            signal(
                "change.followed_by_incident",
                "critical",
                f"{len(review.incidents_after)} incident(s) followed {review.of}.",
                incidents=[i.name for i in review.incidents_after],
            )
        )
    if (review.state or "") == "failed":
        said.append(signal("change.failed", "warning", f"{review.of} failed."))
    if review.critical_targets:
        said.append(
            signal(
                "change.critical_target",
                "warning",
                f"{review.of} touched what is critical: {', '.join(review.critical_targets)}.",
                targets=review.critical_targets,
            )
        )
    if len(review.reach.dependents) >= 5 or review.reach.business:
        said.append(
            signal(
                "change.wide_reach",
                "warning",
                f"{review.of} reaches {len(review.reach.dependents)} dependent(s) and "
                f"{len(review.reach.business)} business capability or process(es).",
                dependents=len(review.reach.dependents),
                business=len(review.reach.business),
            )
        )
    if (review.environment or "").lower() in ("production", "prod"):
        said.append(signal("change.production", "info", f"{review.of} went to production."))
    return said


CHANGES = (EntityType.PULL_REQUEST, EntityType.CHANGE, EntityType.DEPLOYMENT, EntityType.RELEASE)
TARGETS = frozenset({EntityType.SERVICE, EntityType.APPLICATION})


async def _incidents(
    repository: EntityRepository, filters: EventFilters, session: AsyncSession
) -> list[IncidentRead]:
    statement = repository.events(EntityType.INCIDENT, filters).order_by(
        Entity.occurred_at.desc().nulls_last()
    )
    found = await listed(session, statement)
    return await KnowledgeService(repository).incidents(found) if found else []


async def change_review(asked: OneAsked, call: Call) -> ChangeReview:
    repository, entity = await one(call, asked.id, CHANGES)
    knowledge = KnowledgeService(repository)
    attributes = entity.attributes or {}
    at = entity.occurred_at
    state = str(attributes["state"]) if attributes.get("state") else None
    environment = str(attributes["environment"]) if attributes.get("environment") else None
    by = str(attributes["author"]) if attributes.get("author") else None
    caused: list[IncidentRead] = []
    touched: Sequence[EntityBrief | Entity]
    if entity.type is EntityType.DEPLOYMENT:
        detail = await knowledge.deployment(entity)
        touched = list(detail.services)
        state, environment = detail.state or state, detail.environment or environment
        by = detail.deployer.name if detail.deployer else by
        at = detail.deployed_at or at
    elif entity.type is EntityType.CHANGE:
        [change] = await knowledge.changes([entity])
        touched = list(change.affects)
        state, environment = change.state or state, change.environment or environment
        who = change.assignee or change.requester
        by = who.name if who else by
        at = change.changed_at or at
    else:
        repositories = await neighbours(call, [entity.id], frozenset({EntityType.REPOSITORY}))
        touched = await neighbours(call, [r.id for r in repositories] or [entity.id], TARGETS)
    caused = await _incidents(repository, EventFilters(cause_id=entity.id), call.session)
    targets = await repository.by_ids([t.id for t in touched])
    followed: list[IncidentRead] = []
    if at is not None:
        for target in list(targets.values())[:10]:
            followed += await _incidents(
                repository,
                EventFilters(service_id=target.id, since=at, until=at + AFTER),
                call.session,
            )
    impact = await knowledge.impact([t.id for t in touched]) if touched else None
    citer = Citer(await sources_of(call.session, call.workspace_id, [entity, *targets.values()]))
    citer.thing(entity)
    said: dict[uuid.UUID, IncidentSaid] = {}
    for incident, how in [*((i, "caused") for i in caused), *((i, "followed") for i in followed)]:
        if incident.id in said:
            continue
        said[incident.id] = IncidentSaid(
            id=f"event:{incident.id}",
            name=incident.name,
            severity=severity_of(incident),
            opened_at=incident.opened_at,
            how=how,
        )
    review = ChangeReview(
        of=entity.name,
        kind=_type(entity),
        at=at,
        state=state,
        environment=environment,
        by=by,
        touches=[citer.named(t) for t in touched[:MOST]],
        critical_targets=sorted(
            t.name
            for t in targets.values()
            if level_of((t.attributes or {}).get("criticality")) in SEVERE
        ),
        reach=Reach(
            dependents=[citer.named(d) for d in impact.dependents[:MOST]] if impact else [],
            applications=[citer.named(a) for a in impact.applications[:MOST]] if impact else [],
            business=business(impact, citer)[:MOST] if impact else [],
        ),
        incidents_after=list(said.values())[:MOST],
    )
    review.signals = judge_change(review)
    review.cited = citer.cited
    return review


# ── testing: test-scope ──────────────────────────────────────────────────────


class ScopeAsked(OneAsked):
    environment: str | None = Field(
        default=None, max_length=50, description="Only what runs there: production, staging…"
    )


class ToTest(Named):
    steps: int = Field(description="1: it depends on it directly; 2: through another.")
    criticality: str | None
    incidents_30d: int


class ScopeToTest(Assessed):
    of: str
    to_test: list[ToTest] = Field(description="The most critical first, then the nearest.")
    total: int = Field(description="How many depend on it, two steps at most.")
    applications: list[Named]
    business: list[Named]


def judge_scope(scope: ScopeToTest) -> list[Signal]:
    said: list[Signal] = []
    if not scope.total:
        said.append(
            signal("test.isolated", "info", f"Nothing LEKA knows depends on {scope.of}: test it.")
        )
    critical = [t.name for t in scope.to_test if (t.criticality or "") in SEVERE]
    if critical:
        said.append(
            signal(
                "test.critical_dependents",
                "warning",
                f"What depends on {scope.of} includes what is critical: {', '.join(critical)}.",
                dependents=critical,
            )
        )
    fragile = [t.name for t in scope.to_test if t.incidents_30d]
    if fragile:
        said.append(
            signal(
                "test.fragile_dependents",
                "warning",
                f"Had incidents in 30 days: {', '.join(fragile)}.",
                dependents=fragile,
            )
        )
    if scope.business:
        said.append(
            signal(
                "test.business_flows",
                "info",
                f"It carries {len(scope.business)} business capability or process(es).",
                business=[b.name for b in scope.business],
            )
        )
    return said


SCOPED = (
    EntityType.SERVICE,
    EntityType.APPLICATION,
    EntityType.REPOSITORY,
    EntityType.DATABASE,
    EntityType.INFRA_RESOURCE,
)


async def testing_scope(asked: ScopeAsked, call: Call) -> ScopeToTest:
    repository, entity = await one(call, asked.id, SCOPED)
    roots = (
        [s.id for s in await neighbours(call, [entity.id], TARGETS)] or [entity.id]
        if entity.type is EntityType.REPOSITORY
        else [entity.id]
    )
    depth: dict[uuid.UUID, int] = {}
    for root in roots:
        found, _ = await repository.dependencies(
            root, downstream=False, depth=2, environment=asked.environment, limit=200
        )
        for ident, steps in found.items():
            if ident not in roots and steps > 0:
                depth[ident] = min(steps, depth.get(ident, steps))
    things = await repository.by_ids(list(depth))
    ranked = sorted(
        things.values(),
        key=lambda t: (
            rank(level_of((t.attributes or {}).get("criticality"))),
            depth[t.id],
            t.name,
        ),
    )[:MOST]
    since = call.now - timedelta(days=30)
    citer = Citer(await sources_of(call.session, call.workspace_id, [entity, *ranked]))
    citer.thing(entity)
    to_test = []
    for thing in ranked:
        incidents = await counted(
            call.session,
            repository.events(EntityType.INCIDENT, EventFilters(service_id=thing.id, since=since)),
        )
        named = citer.named(thing)
        to_test.append(
            ToTest(
                **named.model_dump(),
                steps=depth[thing.id],
                criticality=level_of((thing.attributes or {}).get("criticality")),
                incidents_30d=incidents,
            )
        )
    impact = await KnowledgeService(repository).impact(roots)
    scope = ScopeToTest(
        of=entity.name,
        to_test=to_test,
        total=len(depth),
        applications=[citer.named(a) for a in impact.applications[:MOST]],
        business=business(impact, citer)[:MOST],
    )
    scope.signals = judge_scope(scope)
    scope.cited = citer.cited
    return scope


# ── security: security-posture ───────────────────────────────────────────────


class PostureAsked(BaseModel):
    service: str | None = Field(
        default=None, max_length=100, description=f"Only around one service: {ID}"
    )
    environment: str | None = Field(default=None, max_length=50, description="Only there.")


class Exposed(Named):
    kind: str | None
    provider: str | None
    criticality: str | None
    owned: bool


class Sensitive(Named):
    classification: str | None
    categories: list[str]
    personal: bool
    owned: bool


class SecurityPosture(Assessed):
    public_resources: list[Exposed]
    public_repositories: list[Named]
    sensitive_data: list[Sensitive]


def judge_posture(posture: SecurityPosture) -> list[Signal]:
    said: list[Signal] = []
    critical = [r.name for r in posture.public_resources if (r.criticality or "") in SEVERE]
    unowned = [r.name for r in posture.public_resources if not r.owned]
    if critical:
        said.append(
            signal(
                "security.public_critical",
                "critical",
                f"Reachable from the internet and critical: {', '.join(critical)}.",
                resources=critical,
            )
        )
    if unowned:
        said.append(
            signal(
                "security.unowned_exposed",
                "critical",
                f"Reachable from the internet, and no one answers for: {', '.join(unowned)}.",
                resources=unowned,
            )
        )
    if posture.public_resources:
        said.append(
            signal(
                "security.public_resources",
                "warning",
                f"{len(posture.public_resources)} resource(s) reachable from the internet.",
                count=len(posture.public_resources),
            )
        )
    if posture.public_repositories:
        said.append(
            signal(
                "security.public_repositories",
                "warning",
                f"{len(posture.public_repositories)} public repository(ies): anyone reads their "
                "code.",
                repositories=[r.name for r in posture.public_repositories],
            )
        )
    secrets = [d.name for d in posture.sensitive_data if set(d.categories) & SECRETS]
    if secrets:
        said.append(
            signal(
                "security.secrets_stored",
                "warning",
                f"Secrets are stored in: {', '.join(secrets)}.",
                stores=secrets,
            )
        )
    personal = [d.name for d in posture.sensitive_data if d.personal]
    if personal:
        said.append(
            signal(
                "security.personal_data",
                "info",
                f"Personal data is held in: {', '.join(personal)}.",
                stores=personal,
            )
        )
    if not said:
        said.append(
            signal(
                "security.nothing_exposed",
                "info",
                "Nothing the sources describe is public, and no sensitive data is said to be held.",
            )
        )
    return said


async def security_posture(asked: PostureAsked, call: Call) -> SecurityPosture:
    repository = EntityRepository(call.session, call.workspace_id)
    knowledge = KnowledgeService(repository)
    service: Entity | None = None
    if asked.service:
        _, service = await one(call, asked.service, (EntityType.SERVICE, EntityType.APPLICATION))
    resources = await listed(
        call.session,
        repository.infrastructure(
            InfrastructureFilters(
                exposure="public",
                environment=asked.environment,
                service_id=service.id if service else None,
            )
        ),
        200,
    )
    exposed = await knowledge.infrastructure(resources) if resources else []
    public_repos = await listed(
        call.session,
        repository.select(Entity).where(
            Entity.type == EntityType.REPOSITORY,
            Entity.lifecycle != Lifecycle.REMOVED,
            func.lower(Entity.attributes["visibility"].astext) == "public",
        ),
        200,
    )
    if service is not None:
        around = {
            r.id for r in await neighbours(call, [service.id], frozenset({EntityType.REPOSITORY}))
        }
        public_repos = [r for r in public_repos if r.id in around]
    stores = {
        e.id: e
        for personal, classification in ((True, None), (None, "restricted"))
        for e in await listed(
            call.session,
            repository.databases(
                lifecycle=None,
                engine=None,
                classification=classification,
                personal_data=personal,
                environment=asked.environment,
                team_id=None,
                q=None,
            ),
            100,
        )
    }
    databases = await knowledge.databases(list(stores.values())) if stores else []
    citer = Citer(
        await sources_of(
            call.session, call.workspace_id, [*resources, *public_repos, *stores.values()]
        )
    )
    posture = SecurityPosture(
        public_resources=[
            Exposed(
                **citer.named(r).model_dump(),
                kind=r.resource_kind,
                provider=r.provider,
                criticality=level_of(r.criticality),
                owned=bool(r.owners or r.services or r.applications),
            )
            for r in sorted(exposed, key=lambda r: (rank(level_of(r.criticality)), r.name))[:MOST]
        ],
        public_repositories=[citer.named(r) for r in public_repos[:MOST]],
        sensitive_data=[
            Sensitive(
                **citer.named(d, kind="database").model_dump(),
                classification=d.holds.classification,
                categories=list(d.holds.data_categories),
                personal=d.holds.personal_data,
                owned=bool(d.owners),
            )
            for d in databases[:MOST]
        ],
    )
    posture.signals = judge_posture(posture)
    posture.cited = citer.cited
    return posture


# ── documentation: documentation-coverage ────────────────────────────────────

DOCUMENTED_KINDS = Literal[
    "service", "application", "repository", "database", "business_capability", "business_process"
]


class CoverageAsked(BaseModel):
    kind: DOCUMENTED_KINDS | None = Field(
        default=None, description="Only this kind of thing; every kind if none."
    )
    critical_only: bool = Field(default=False, description="Only what is critical or high.")


class KindCoverage(BaseModel):
    type: str
    total: int
    documented: int
    fresh: int
    percent: int = Field(description="Documented, of the total.")


class Gap(Named):
    criticality: str | None
    owners: list[str]
    documents: int
    last_documented_at: str | None


class DocumentationCoverageSaid(Assessed):
    documents: int
    spaces: int
    freshness: dict[str, int]
    coverage: list[KindCoverage]
    undocumented: list[Gap] = Field(description="No document or space describes them.")
    stale: list[Gap] = Field(description="Only stale documents describe them.")


def judge_coverage(said: DocumentationCoverageSaid) -> list[Signal]:
    signals: list[Signal] = []
    if not said.documents:
        signals.append(
            signal("docs.none", "info", "LEKA reads no document: nothing is documented yet.")
        )
    critical = [g.name for g in said.undocumented if (g.criticality or "") in SEVERE]
    if critical:
        signals.append(
            signal(
                "docs.critical_undocumented",
                "warning",
                f"Critical and undocumented: {', '.join(critical)}.",
                things=critical,
            )
        )
    low = [k.type for k in said.coverage if k.total and k.percent < 50]
    if low:
        signals.append(
            signal(
                "docs.low_coverage",
                "warning",
                f"Less than half documented: {', '.join(low)}.",
                kinds=low,
            )
        )
    if said.undocumented:
        signals.append(
            signal(
                "docs.gaps",
                "info",
                f"{len(said.undocumented)} thing(s) no document describes, "
                f"{len(said.stale)} only stale ones do.",
                undocumented=len(said.undocumented),
                stale=len(said.stale),
            )
        )
    fresh = said.freshness.get("fresh", 0)
    stale = said.freshness.get("stale", 0)
    if stale > fresh:
        signals.append(
            signal(
                "docs.mostly_stale",
                "info",
                f"More stale documents ({stale}) than fresh ones ({fresh}).",
                stale=stale,
                fresh=fresh,
            )
        )
    return signals


async def documentation_coverage(asked: CoverageAsked, call: Call) -> DocumentationCoverageSaid:
    repository = EntityRepository(call.session, call.workspace_id)
    knowledge = KnowledgeService(repository)
    coverage = await knowledge.coverage()
    kinds = [EntityType(k) for k in ([asked.kind] if asked.kind else get_args(DOCUMENTED_KINDS))]
    levels: Sequence[str | None] = ("critical", "high") if asked.critical_only else (None,)

    async def gaps(stale: bool) -> list[Any]:
        found: dict[uuid.UUID, Entity] = {}
        for kind in kinds:
            for level in levels:
                for e in await listed(
                    call.session,
                    repository.gaps(
                        kind, stale=stale, lifecycle=None, criticality=level, team_id=None, q=None
                    ),
                    100,
                ):
                    found.setdefault(e.id, e)
        rows = await knowledge.gaps(list(found.values())) if found else []
        return sorted(rows, key=lambda g: (rank(level_of(g.criticality)), g.entity.name))[:MOST]

    undocumented, stale = await gaps(False), await gaps(True)
    citer = Citer()

    def gap(row: Any) -> Gap:
        return Gap(
            **citer.named(row.entity).model_dump(),
            criticality=level_of(row.criticality),
            owners=[o.name for o in row.owners],
            documents=row.documents,
            last_documented_at=row.last_documented_at,
        )

    said = DocumentationCoverageSaid(
        documents=coverage.documents,
        spaces=coverage.spaces,
        freshness=dict(coverage.freshness),
        coverage=[
            KindCoverage(
                type=c.type.value if hasattr(c.type, "value") else str(c.type),
                total=c.total,
                documented=c.documented,
                fresh=c.fresh,
                percent=round(100 * c.documented / c.total) if c.total else 0,
            )
            for c in coverage.coverage
        ],
        undocumented=[gap(g) for g in undocumented],
        stale=[gap(g) for g in stale],
    )
    said.signals = judge_coverage(said)
    said.cited = citer.cited
    return said


# ── architecture: blast-radius ───────────────────────────────────────────────


class BlastRadius(Assessed):
    of: str
    type: str
    criticality: str | None
    owners: list[str]
    direct: list[Named] = Field(description="What depends on it directly.")
    indirect: list[Named] = Field(
        description="What depends on it through another, 3 steps at most."
    )
    applications: list[Named]
    business: list[Named]
    depends_on: int = Field(description="How many things it depends on itself.")


def judge_radius(radius: BlastRadius) -> list[Signal]:
    said: list[Signal] = []
    if len(radius.direct) >= 3:
        said.append(
            signal(
                "architecture.concentration",
                "warning",
                f"{len(radius.direct)} things depend on {radius.of} directly: a failure of it "
                "stops them all.",
                dependents=len(radius.direct),
            )
        )
    if radius.business:
        said.append(
            signal(
                "architecture.business_critical",
                "warning",
                f"A failure of {radius.of} reaches the business: "
                f"{', '.join(b.name for b in radius.business)}.",
                business=[b.name for b in radius.business],
            )
        )
    if not radius.owners:
        critical = (radius.criticality or "") in SEVERE
        said.append(
            signal(
                "architecture.unowned_critical" if critical else "architecture.unowned",
                "critical" if critical else "warning",
                f"No team or person answers for {radius.of}.",
            )
        )
    if not radius.direct:
        said.append(signal("architecture.leaf", "info", f"Nothing depends on {radius.of}."))
    return said


async def blast_radius(asked: OneAsked, call: Call) -> BlastRadius:
    repository, entity = await one(call, asked.id)
    knowledge = KnowledgeService(repository)
    upstream, _ = await repository.dependencies(
        entity.id, downstream=False, depth=3, environment=None, limit=300
    )
    downstream, _ = await repository.dependencies(
        entity.id, downstream=True, depth=1, environment=None, limit=300
    )
    depth = {i: s for i, s in upstream.items() if i != entity.id and s > 0}
    things = await repository.by_ids(list(depth))
    impact = await knowledge.impact([entity.id])
    held = await knowledge.responsibility(entity)
    citer = Citer(await sources_of(call.session, call.workspace_id, [entity, *things.values()]))
    citer.thing(entity)
    ordered = sorted(
        things.values(),
        key=lambda t: (rank(level_of((t.attributes or {}).get("criticality"))), t.name),
    )
    radius = BlastRadius(
        of=entity.name,
        type=_type(entity),
        criticality=level_of((entity.attributes or {}).get("criticality")),
        owners=[t.entity.name for t in held.owners],
        direct=[citer.named(t) for t in ordered if depth[t.id] == 1][:MOST],
        indirect=[citer.named(t) for t in ordered if depth[t.id] > 1][:MOST],
        applications=[citer.named(a) for a in impact.applications[:MOST]],
        business=business(impact, citer)[:MOST],
        depends_on=len([i for i, s in downstream.items() if i != entity.id and s > 0]),
    )
    radius.signals = judge_radius(radius)
    radius.cited = citer.cited
    return radius


# ── incident investigation: incident-history ─────────────────────────────────


class HistoryAsked(BaseModel):
    id: str | None = Field(
        default=None, max_length=100, description=f"Only those affecting one thing: {ID}"
    )
    days: int = Field(default=90, ge=1, le=365, description="How far back.")


class IncidentBrief(BaseModel):
    id: str
    name: str
    severity: str
    state: str | None
    opened_at: datetime | None
    minutes: int | None


class Recurring(BaseModel):
    cause: str
    count: int


class IncidentHistory(Assessed):
    of: str | None
    since: datetime
    total: int
    open: int
    by_severity: dict[str, int]
    mttr_minutes: int | None = Field(description="Median time to resolve, of the closed ones.")
    longest_minutes: int | None
    recurring_causes: list[Recurring]
    latest: list[IncidentBrief]


def judge_history(history: IncidentHistory, days: int) -> list[Signal]:
    said: list[Signal] = []
    where = f" on {history.of}" if history.of else ""
    if not history.total:
        said.append(signal("incident.quiet", "info", f"No incident{where} in {days} days."))
        return said
    if history.by_severity.get("critical"):
        said.append(
            signal(
                "incident.severe",
                "critical",
                f"{history.by_severity['critical']} critical incident(s){where} in {days} days.",
                count=history.by_severity["critical"],
            )
        )
    if history.open:
        said.append(
            signal("incident.open", "warning", f"{history.open} incident(s){where} still open.")
        )
    if history.total >= 3:
        said.append(
            signal(
                "incident.recurring",
                "warning",
                f"{history.total} incidents{where} in {days} days.",
                count=history.total,
            )
        )
    if history.mttr_minutes is not None and history.mttr_minutes > 240:
        said.append(
            signal(
                "incident.slow_recovery",
                "warning",
                f"Half the incidents{where} took more than {history.mttr_minutes} minutes to "
                "resolve.",
                minutes=history.mttr_minutes,
            )
        )
    return said


def history_of(
    incidents: Sequence[IncidentRead], *, of: str | None, since: datetime
) -> IncidentHistory:
    """What a list of incidents comes to — pure."""
    durations = [
        i.duration_minutes
        for i in incidents
        if i.duration_minutes is not None and (i.state or "") == "closed"
    ]
    causes = Counter(c.name for i in incidents for c in i.causes)
    return IncidentHistory(
        of=of,
        since=since,
        total=len(incidents),
        open=sum(1 for i in incidents if (i.state or "open") != "closed"),
        by_severity=dict(Counter(severity_of(i) for i in incidents)),
        mttr_minutes=round(statistics.median(durations)) if durations else None,
        longest_minutes=max(durations, default=None),
        recurring_causes=[
            Recurring(cause=name, count=count) for name, count in causes.most_common() if count > 1
        ][:10],
        latest=[
            IncidentBrief(
                id=f"event:{i.id}",
                name=i.name,
                severity=severity_of(i),
                state=i.state,
                opened_at=i.opened_at,
                minutes=i.duration_minutes,
            )
            for i in incidents[:MOST]
        ],
    )


async def incident_history(asked: HistoryAsked, call: Call) -> IncidentHistory:
    repository = EntityRepository(call.session, call.workspace_id)
    thing: Entity | None = None
    if asked.id:
        _, thing = await one(call, asked.id)
    since = call.now - timedelta(days=asked.days)
    incidents = await _incidents(
        repository,
        EventFilters(service_id=thing.id if thing else None, since=since, until=call.now),
        call.session,
    )
    found = await repository.by_ids([i.id for i in incidents[:MOST]])
    citer = Citer(await sources_of(call.session, call.workspace_id, [*found.values()]))
    if thing is not None:
        citer.thing(thing)
    for incident in found.values():
        citer.thing(incident)
    history = history_of(incidents, of=thing.name if thing else None, since=since)
    history.signals = judge_history(history, asked.days)
    history.cited = citer.cited
    return history


# ── infrastructure: infrastructure-inventory ─────────────────────────────────


class InventoryAsked(BaseModel):
    account: str | None = Field(
        default=None, max_length=100, description=f"Only in one account, or group: {ID}"
    )
    service: str | None = Field(
        default=None, max_length=100, description=f"Only what one service runs on: {ID}"
    )
    environment: str | None = Field(default=None, max_length=50, description="Only there.")


class Resource(Named):
    kind: str | None
    provider: str | None
    region: str | None
    state: str | None
    exposure: str | None
    criticality: str | None
    owned: bool


class Inventory(Assessed):
    total: int
    by_provider: dict[str, int]
    by_kind: dict[str, int]
    by_region: dict[str, int]
    by_state: dict[str, int]
    public: int
    unowned: int
    notable: list[Resource] = Field(
        description="The critical, public, unowned, failed or not running — the most critical "
        "first."
    )


def inventory_of(resources: Sequence[InfrastructureRead], citer: Citer) -> Inventory:
    """What a list of resources comes to — pure but for the citations."""

    def counts(values: Iterable[str | None]) -> dict[str, int]:
        return dict(Counter(v or "unknown" for v in values).most_common())

    rows = [
        Resource(
            **citer.named(r).model_dump(),
            kind=r.resource_kind,
            provider=r.provider,
            region=r.region,
            state=r.state,
            exposure=r.exposure,
            criticality=level_of(r.criticality),
            owned=bool(r.owners or r.services or r.applications),
        )
        for r in resources
    ]
    notable = [
        r
        for r in rows
        if not r.owned
        or (r.exposure or "") == "public"
        or (r.criticality or "") in SEVERE
        or (r.state or "") == "failed"
        or (r.state or "") in NOT_RUNNING
    ]
    return Inventory(
        total=len(rows),
        by_provider=counts(r.provider for r in rows),
        by_kind=counts(r.kind for r in rows),
        by_region=counts(r.region for r in rows),
        by_state=counts(r.state for r in rows),
        public=sum(1 for r in rows if (r.exposure or "") == "public"),
        unowned=sum(1 for r in rows if not r.owned),
        notable=sorted(notable, key=lambda r: (rank(r.criticality), r.name))[:MOST],
    )


def judge_inventory(inventory: Inventory) -> list[Signal]:
    said: list[Signal] = []
    if not inventory.total:
        return [signal("infra.empty", "info", "LEKA knows no resource here.")]
    critical = [
        r.name for r in inventory.notable if not r.owned and (r.criticality or "") in SEVERE
    ]
    if critical:
        said.append(
            signal(
                "infra.unowned_critical",
                "critical",
                f"Critical, and no one answers for: {', '.join(critical)}.",
                resources=critical,
            )
        )
    if inventory.unowned:
        said.append(
            signal(
                "infra.unowned",
                "warning",
                f"{inventory.unowned} resource(s) of {inventory.total} belong to no service, "
                "application, team or person.",
                count=inventory.unowned,
            )
        )
    failed = inventory.by_state.get("failed", 0)
    if failed:
        said.append(
            signal("infra.failed", "warning", f"{failed} resource(s) failed.", count=failed)
        )
    resting = sum(inventory.by_state.get(s, 0) for s in NOT_RUNNING)
    if resting:
        said.append(
            signal(
                "infra.not_running",
                "info",
                f"{resting} resource(s) stopped or gone.",
                count=resting,
            )
        )
    if inventory.public:
        said.append(
            signal(
                "infra.public",
                "info",
                f"{inventory.public} resource(s) reachable from the internet.",
                count=inventory.public,
            )
        )
    return said


async def infrastructure_inventory(asked: InventoryAsked, call: Call) -> Inventory:
    repository = EntityRepository(call.session, call.workspace_id)
    account = service = None
    if asked.account:
        _, account = await one(
            call, asked.account, (EntityType.CLOUD_ACCOUNT, EntityType.RESOURCE_GROUP)
        )
    if asked.service:
        _, service = await one(call, asked.service, (EntityType.SERVICE, EntityType.APPLICATION))
    found = await listed(
        call.session,
        repository.infrastructure(
            InfrastructureFilters(
                account_id=account.id if account else None,
                service_id=service.id if service else None,
                environment=asked.environment,
            )
        ),
    )
    resources = await KnowledgeService(repository).infrastructure(found) if found else []
    citer = Citer(await sources_of(call.session, call.workspace_id, found))
    scoped = {citer.thing(scope) for scope in (account, service) if scope is not None}
    inventory = inventory_of(resources, citer)
    inventory.signals = judge_inventory(inventory)
    # What it cites: where it looked, and what it points out — not the rest.
    shown = scoped | {r.id for r in inventory.notable}
    inventory.cited = [c for c in citer.cited if c.id in shown]
    return inventory


# ── data analysis: data-landscape ────────────────────────────────────────────


class DataAsked(BaseModel):
    id: str | None = Field(default=None, max_length=100, description=f"Only one database: {ID}")


class Store(Named):
    engine: str | None
    schemas: int
    objects: int
    classification: str | None
    categories: list[str]
    personal: bool
    owners: list[str]
    services: list[str]


class SensitiveObject(Named):
    database: str | None
    classification: str | None
    categories: list[str]


class DataLandscape(Assessed):
    databases: list[Store]
    sensitive_objects: list[SensitiveObject] = Field(
        description="The tables, views and collections holding personal data or secrets."
    )


def judge_data(landscape: DataLandscape) -> list[Signal]:
    said: list[Signal] = []
    secrets = sorted(
        {d.name for d in landscape.databases if set(d.categories) & SECRETS}
        | {o.database or o.name for o in landscape.sensitive_objects if set(o.categories) & SECRETS}
    )
    if secrets:
        said.append(
            signal(
                "data.secrets",
                "warning",
                f"Secrets are stored in: {', '.join(secrets)}.",
                stores=secrets,
            )
        )
    personal = [d.name for d in landscape.databases if d.personal]
    if personal:
        said.append(
            signal(
                "data.personal",
                "info",
                f"Personal data is held in: {', '.join(personal)}.",
                stores=personal,
            )
        )
    unowned = [d.name for d in landscape.databases if not d.owners]
    if unowned:
        said.append(
            signal(
                "data.unowned",
                "warning",
                f"No team or person answers for: {', '.join(unowned)}.",
                stores=unowned,
            )
        )
    shared = [d.name for d in landscape.databases if len(d.services) >= 3]
    if shared:
        said.append(
            signal(
                "data.shared",
                "info",
                f"Used by three services or more: {', '.join(shared)}.",
                stores=shared,
            )
        )
    if not landscape.databases:
        said.append(signal("data.none", "info", "LEKA knows no database here."))
    return said


async def data_landscape(asked: DataAsked, call: Call) -> DataLandscape:
    repository = EntityRepository(call.session, call.workspace_id)
    knowledge = KnowledgeService(repository)
    if asked.id:
        _, database = await one(call, asked.id, (EntityType.DATABASE,))
        found = [database]
    else:
        found = await listed(
            call.session,
            repository.databases(
                lifecycle=None,
                engine=None,
                classification=None,
                personal_data=None,
                environment=None,
                team_id=None,
                q=None,
            ),
            200,
        )
    databases = await knowledge.databases(found) if found else []
    objects = {
        e.id: e
        for personal, category in ((True, None), *((None, c) for c in sorted(SECRETS)))
        for e in await listed(
            call.session,
            repository.data_objects(
                DataFilters(
                    database_id=found[0].id if asked.id and found else None,
                    personal_data=personal,
                    category=category,
                )
            ),
            100,
        )
    }
    sensitive = await knowledge.data_objects(list(objects.values())) if objects else []
    citer = Citer(await sources_of(call.session, call.workspace_id, [*found, *objects.values()]))
    landscape = DataLandscape(
        databases=[
            Store(
                **citer.named(d, kind="database").model_dump(),
                engine=d.engine,
                schemas=d.schema_count,
                objects=d.object_count,
                classification=d.holds.classification,
                categories=list(d.holds.data_categories),
                personal=d.holds.personal_data,
                owners=[o.name for o in d.owners],
                services=[s.name for s in d.services],
            )
            for d in databases[:MOST]
        ],
        sensitive_objects=[
            SensitiveObject(
                **citer.named(o, kind="data_object").model_dump(),
                database=o.database.name if o.database else None,
                classification=o.holds.classification,
                categories=list(o.holds.data_categories),
            )
            for o in sensitive[:MOST]
        ],
    )
    landscape.signals = judge_data(landscape)
    landscape.cited = citer.cited
    return landscape


# ── database review: schema-health (2026-10-22) ──────────────────────────────

# The columns money is kept in, by their names; the types that round it.
MONEY = re.compile(
    r"(^|_)(amount|price|total|cost|balance|fee|tax|salary|montant|prix|solde|cout)(_|$)"
)
FLOATING = frozenset(
    {
        "real",
        "double precision",
        "float",
        "float4",
        "float8",
        "double",
        "binary_float",
        "binary_double",
    }
)
ZONELESS = frozenset({"timestamp", "timestamp without time zone"})
TABLES = frozenset({"table", "partitioned table", "base table"})
MOST_TABLES = 2_000


class SchemaAsked(BaseModel):
    id: str = Field(max_length=100, description=f"The database: {ID}")


class TableNote(Named):
    rows: int | None
    size_bytes: int | None
    detail: str | None = Field(default=None, description="What is found, as the catalogue says it.")


class SchemaHealth(Assessed):
    database: str
    engine: str | None
    tables: int
    structured: int = Field(description="Tables whose columns' types, keys and indexes LEKA read.")
    largest: list[TableNote]
    without_primary_key: list[TableNote]
    unindexed_foreign_keys: list[TableNote] = Field(
        description="A foreign key no index starts with: every join, every delete of the "
        "parent, reads the whole table."
    )
    duplicate_indexes: list[TableNote]
    floating_money: list[TableNote]
    timestamps_without_zone: list[TableNote]


def index_columns(definition: str) -> tuple[str, ...]:
    """An index's key columns, in order, as its definition writes them —
    `CREATE INDEX i ON s.t USING btree (a, b DESC) WHERE …` → (a, b);
    an expression stays one, as written."""
    text = definition
    on = text.upper().find(" ON ")
    start = text.find("(", on if on >= 0 else 0)
    if start < 0:
        return ()
    depth, parts, word = 0, [], ""
    for char in text[start + 1 :]:
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                break
            depth -= 1
        if char == "," and depth == 0:
            parts.append(word)
            word = ""
        else:
            word += char
    parts.append(word)
    found = []
    for part in parts:
        said = part.strip().strip('"`[]')
        if "(" not in said:
            said = said.split()[0].strip('"`[]') if said.split() else ""
        if said:
            found.append(said.lower())
    return tuple(found)


def _foreign_key(said: str) -> tuple[tuple[str, ...], str]:
    """« customer_id, day → billing.customers(id, day) » → its columns and all of it."""
    columns, _, _ = said.partition(" → ")
    return tuple(c.strip().strip('"`[]').lower() for c in columns.split(",") if c.strip()), said


def _strings(value: object) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def schema_of(
    tables: Sequence[tuple[Named, Mapping[str, Any]]], *, database: str, engine: str | None
) -> SchemaHealth:
    """What a database's structure shows (pure): each table's attributes as
    the model holds them — read by the database source, never a row."""

    def note(named: Named, a: Mapping[str, Any], detail: str | None = None) -> TableNote:
        rows, size = a.get("estimated_rows"), a.get("size_bytes")
        return TableNote(
            **named.model_dump(),
            rows=rows if isinstance(rows, int) else None,
            size_bytes=size if isinstance(size, int) else None,
            detail=detail,
        )

    real = [(n, a) for n, a in tables if str(a.get("object_kind") or "table").lower() in TABLES]
    structured = [(n, a) for n, a in real if "indexes" in a or "column_types" in a]
    unkeyed, unindexed, twice, floating, zoneless = [], [], [], [], []
    for named, a in real:
        key = tuple(c.lower() for c in _strings(a.get("primary_key")))
        if not key:
            unkeyed.append(note(named, a))
        if (named, a) not in structured:
            continue
        whole = [
            (d, index_columns(d)) for d in _strings(a.get("indexes")) if " WHERE " not in d.upper()
        ]
        starts = [cols for _, cols in whole] + ([key] if key else [])
        for said in _strings(a.get("foreign_keys")):
            columns, _ = _foreign_key(said)
            if columns and not any(
                len(cols) >= len(columns) and set(cols[: len(columns)]) == set(columns)
                for cols in starts
            ):
                unindexed.append(note(named, a, said))
        seen: dict[tuple[str, ...], str] = {}
        for definition, cols in whole:
            if not cols:
                continue
            if cols in seen:
                twice.append(note(named, a, f"{seen[cols]} | {definition}"))
            else:
                seen[cols] = definition
        typed = [c.split(" ", 1) for c in _strings(a.get("column_types")) if " " in c]
        money = [n for n, t in typed if MONEY.search(n.lower()) and t.lower() in FLOATING]
        if money:
            floating.append(note(named, a, ", ".join(money)))
        if (engine or "") == "postgresql":
            stamps = [n for n, t in typed if t.lower() in ZONELESS]
            if stamps:
                zoneless.append(note(named, a, ", ".join(stamps)))

    def size(t: TableNote) -> tuple[int, int]:
        return (-(t.rows or 0), -(t.size_bytes or 0))

    largest = sorted((note(n, a) for n, a in real), key=size)
    health = SchemaHealth(
        database=database,
        engine=engine,
        tables=len(real),
        structured=len(structured),
        largest=[t for t in largest if t.rows or t.size_bytes][:10],
        without_primary_key=sorted(unkeyed, key=size)[:MOST],
        unindexed_foreign_keys=sorted(unindexed, key=size)[:MOST],
        duplicate_indexes=sorted(twice, key=size)[:MOST],
        floating_money=sorted(floating, key=size)[:MOST],
        timestamps_without_zone=sorted(zoneless, key=size)[:MOST],
    )
    health.signals = judge_schema(health)
    return health


# A table this big without what it needs is felt on every read.
BIG_TABLE = 1_000_000


def judge_schema(health: SchemaHealth) -> list[Signal]:
    said: list[Signal] = []

    def named(notes: Sequence[TableNote]) -> list[str]:
        return [t.name for t in notes]

    if health.tables and not health.structured:
        said.append(
            signal(
                "schema.not_read",
                "info",
                f"LEKA has not read {health.database}'s columns' types, keys and indexes yet: "
                "its source must sync again.",
            )
        )
    if health.unindexed_foreign_keys:
        big = any((t.rows or 0) >= BIG_TABLE for t in health.unindexed_foreign_keys)
        said.append(
            signal(
                "schema.unindexed_foreign_key",
                "critical" if big else "warning",
                f"{len(health.unindexed_foreign_keys)} foreign keys no index starts with.",
                tables=named(health.unindexed_foreign_keys),
            )
        )
    if health.without_primary_key:
        said.append(
            signal(
                "schema.no_primary_key",
                "warning",
                f"{len(health.without_primary_key)} tables without a primary key.",
                tables=named(health.without_primary_key),
            )
        )
    if health.floating_money:
        said.append(
            signal(
                "schema.floating_money",
                "warning",
                "Money kept in a floating type, which rounds it.",
                tables=named(health.floating_money),
            )
        )
    if health.duplicate_indexes:
        said.append(
            signal(
                "schema.duplicate_index",
                "info",
                "Indexes on the same columns: each slows every write, one serves.",
                tables=named(health.duplicate_indexes),
            )
        )
    if health.timestamps_without_zone:
        said.append(
            signal(
                "schema.timestamp_without_zone",
                "info",
                "Dates kept without their time zone.",
                tables=named(health.timestamps_without_zone),
            )
        )
    if not health.tables:
        said.append(signal("schema.empty", "info", "LEKA knows no table in this database."))
    return said


async def schema_health(asked: SchemaAsked, call: Call) -> SchemaHealth:
    repository, database = await one(call, asked.id, (EntityType.DATABASE,))
    found = await listed(
        call.session,
        repository.data_objects(DataFilters(database_id=database.id)),
        MOST_TABLES,
    )
    citer = Citer(await sources_of(call.session, call.workspace_id, [database, *found]))
    engine = database.attributes.get("engine")
    health = schema_of(
        [(citer.named(e, kind="data_object"), dict(e.attributes)) for e in found],
        database=database.name,
        engine=str(engine) if engine else None,
    )
    said = citer.named(database, kind="database")
    # What it cites: the database, and the tables it points out.
    shown = {said.id} | {
        t.id
        for notes in (
            health.largest,
            health.without_primary_key,
            health.unindexed_foreign_keys,
            health.duplicate_indexes,
            health.floating_money,
            health.timestamps_without_zone,
        )
        for t in notes
    }
    health.cited = [c for c in citer.cited if c.id in shown]
    return health


# ── release and deployment: delivery-metrics ─────────────────────────────────

Tier = Literal["elite", "high", "medium", "low", "unknown"]


class DeliveryAsked(BaseModel):
    id: str | None = Field(
        default=None, max_length=100, description=f"Only one service or repository: {ID}"
    )
    environment: str | None = Field(
        default="production", max_length=50, description="Only there; production if none said."
    )
    days: int = Field(default=30, ge=7, le=180, description="How far back.")


class Tiers(BaseModel):
    frequency: Tier
    failure_rate: Tier
    recovery: Tier


class DeploymentBrief(BaseModel):
    id: str
    name: str
    state: str | None
    at: datetime | None
    incidents: int


class DeliveryMetrics(Assessed):
    of: str | None
    environment: str | None
    since: datetime
    deployments: int
    per_week: float
    failed: int
    followed_by_incident: int
    change_failure_rate: float | None = Field(description="Failed or followed by an incident, 0-1.")
    mttr_minutes: int | None = Field(description="Median time to resolve its incidents.")
    last_deployment_at: datetime | None
    days_since_last: int | None
    tiers: Tiers = Field(description="DORA's: elite, high, medium, low.")
    latest: list[DeploymentBrief]


def frequency_tier(per_week: float) -> Tier:
    if per_week >= 7:
        return "elite"
    if per_week >= 1:
        return "high"
    if per_week >= 0.25:
        return "medium"
    return "low"


def failure_tier(rate: float | None) -> Tier:
    if rate is None:
        return "unknown"
    if rate <= 0.05:
        return "elite"
    if rate <= 0.10:
        return "high"
    if rate <= 0.15:
        return "medium"
    return "low"


def recovery_tier(minutes: int | None) -> Tier:
    if minutes is None:
        return "unknown"
    if minutes < 60:
        return "elite"
    if minutes < 24 * 60:
        return "high"
    if minutes < 7 * 24 * 60:
        return "medium"
    return "low"


def delivery_of(
    deployments: Sequence[DeploymentRead],
    incidents: Sequence[IncidentRead],
    *,
    of: str | None,
    environment: str | None,
    since: datetime,
    now: datetime,
    days: int,
) -> DeliveryMetrics:
    """What deployments and the incidents of the same period come to — pure."""
    failed = {d.id for d in deployments if (d.state or "") == "failed"}
    followed = {d.id for d in deployments if d.incident_count > 0}
    rate = len(failed | followed) / len(deployments) if deployments else None
    durations = [
        i.duration_minutes
        for i in incidents
        if i.duration_minutes is not None and (i.state or "") == "closed"
    ]
    mttr = round(statistics.median(durations)) if durations else None
    last = max((d.deployed_at for d in deployments if d.deployed_at), default=None)
    per_week = round(len(deployments) / (days / 7), 2)
    return DeliveryMetrics(
        of=of,
        environment=environment,
        since=since,
        deployments=len(deployments),
        per_week=per_week,
        failed=len(failed),
        followed_by_incident=len(followed),
        change_failure_rate=round(rate, 3) if rate is not None else None,
        mttr_minutes=mttr,
        last_deployment_at=last,
        days_since_last=(now - last).days if last else None,
        tiers=Tiers(
            frequency=frequency_tier(per_week) if deployments else "low",
            failure_rate=failure_tier(rate),
            recovery=recovery_tier(mttr),
        ),
        latest=[
            DeploymentBrief(
                id=f"event:{d.id}",
                name=d.name,
                state=d.state,
                at=d.deployed_at,
                incidents=d.incident_count,
            )
            for d in sorted(deployments, key=lambda d: d.deployed_at or since, reverse=True)[:MOST]
        ],
    )


def judge_delivery(metrics: DeliveryMetrics, days: int) -> list[Signal]:
    said: list[Signal] = []
    where = f" of {metrics.of}" if metrics.of else ""
    if not metrics.deployments:
        return [signal("delivery.none", "info", f"No deployment{where} in {days} days.")]
    rate = metrics.change_failure_rate or 0
    if rate > 0.15:
        said.append(
            signal(
                "delivery.high_failure_rate",
                "critical" if rate > 0.30 else "warning",
                f"{round(rate * 100)} % of the deployments{where} failed or were followed by an "
                "incident.",
                rate=rate,
            )
        )
    if metrics.failed:
        said.append(
            signal(
                "delivery.failed_deployments",
                "warning",
                f"{metrics.failed} deployment(s){where} failed.",
                count=metrics.failed,
            )
        )
    if metrics.mttr_minutes is not None and metrics.mttr_minutes > 24 * 60:
        said.append(
            signal(
                "delivery.slow_recovery",
                "warning",
                f"Recovering from an incident{where} takes more than a day.",
                minutes=metrics.mttr_minutes,
            )
        )
    if metrics.days_since_last is not None and metrics.days_since_last > 14:
        said.append(
            signal(
                "delivery.stale",
                "info",
                f"Last deployment{where} {metrics.days_since_last} days ago.",
                days=metrics.days_since_last,
            )
        )
    return said


async def delivery_metrics(asked: DeliveryAsked, call: Call) -> DeliveryMetrics:
    repository = EntityRepository(call.session, call.workspace_id)
    knowledge = KnowledgeService(repository)
    thing: Entity | None = None
    if asked.id:
        _, thing = await one(
            call, asked.id, (EntityType.SERVICE, EntityType.APPLICATION, EntityType.REPOSITORY)
        )
    since = call.now - timedelta(days=asked.days)
    of_repository = thing is not None and thing.type is EntityType.REPOSITORY
    statement = repository.events(
        EntityType.DEPLOYMENT,
        EventFilters(
            service_id=thing.id if thing is not None and not of_repository else None,
            repository_id=thing.id if of_repository and thing is not None else None,
            environment=asked.environment,
            since=since,
            until=call.now,
        ),
    ).order_by(Entity.occurred_at.desc().nulls_last())
    found = await listed(call.session, statement)
    deployments = await knowledge.deployments(found) if found else []
    incidents = await _incidents(
        repository,
        EventFilters(
            service_id=thing.id if thing is not None and not of_repository else None,
            since=since,
            until=call.now,
        ),
        call.session,
    )
    citer = Citer(await sources_of(call.session, call.workspace_id, found[:MOST]))
    if thing is not None:
        citer.thing(thing)
    for deployment in found[:MOST]:
        citer.thing(deployment)
    metrics = delivery_of(
        deployments,
        incidents,
        of=thing.name if thing else None,
        environment=asked.environment,
        since=since,
        now=call.now,
        days=asked.days,
    )
    metrics.signals = judge_delivery(metrics, asked.days)
    metrics.cited = citer.cited
    return metrics


# ── registered ───────────────────────────────────────────────────────────────

LIMITED = "Computed from what the connected sources gave LEKA, never a live read of a tool."

LIBRARY = (
    Skill(
        key="repository-profile",
        version=VERSION,
        title="Repository profile",
        summary="One code repository: its languages, visibility and topics, who owns and "
        "maintains it, the services and applications it builds, its merges, releases and "
        "deployments over a period, LEKA's open points on it.",
        category="development",
        input=RepositoryAsked,
        output=RepositoryProfile,
        run=repository_profile,
        reads=(
            "repository",
            "service",
            "application",
            "pull_request",
            "release",
            "deployment",
            "team",
            "person",
        ),
        sources=(CODE_HOSTS,),
        limitations=(LIMITED, "No code is read: no lines, no diff, no dependency manifest."),
    ),
    Skill(
        key="change-review",
        version=VERSION,
        title="Change review",
        summary="One change — a merged pull request, a change request, a deployment, a release: "
        "what it touched, how critical that is, how far it reaches (dependents, applications, "
        "business), and the incidents it caused or that followed it within 72 hours.",
        category="development",
        input=OneAsked,
        output=ChangeReview,
        run=change_review,
        reads=(
            "pull_request",
            "change",
            "deployment",
            "release",
            "repository",
            "service",
            "application",
            "incident",
            "business_capability",
            "business_process",
        ),
        limitations=(
            LIMITED,
            "No diff is read: what a change touched is what its source ties it to.",
            "An incident within 72 hours is said to follow it, not to be caused by it.",
        ),
    ),
    Skill(
        key="test-scope",
        version=VERSION,
        title="Test scope",
        summary="What to test when a service, application, repository, database or resource "
        "changes: what depends on it, two steps, the most critical first, those with incidents "
        "in 30 days, and the applications and business it carries.",
        category="development",
        input=ScopeAsked,
        output=ScopeToTest,
        run=testing_scope,
        reads=(
            "service",
            "application",
            "repository",
            "database",
            "infra_resource",
            "incident",
            "business_capability",
            "business_process",
        ),
        limitations=(
            LIMITED,
            "Reads no test, no coverage, no pipeline: only what depends on what.",
        ),
    ),
    Skill(
        key="security-posture",
        version=VERSION,
        title="Security posture",
        summary="What the sources say is exposed: resources reachable from the internet (the "
        "critical and the unowned first), public repositories, the databases holding personal "
        "data or secrets — everywhere, around one service, or in one environment.",
        category="security",
        input=PostureAsked,
        output=SecurityPosture,
        run=security_posture,
        reads=("infra_resource", "repository", "database", "service", "application", "team"),
        limitations=(
            LIMITED,
            "No vulnerability scan, no IAM policy, no secret scan of code: only exposure, "
            "visibility and classification as the sources describe them.",
        ),
    ),
    Skill(
        key="documentation-coverage",
        version=VERSION,
        title="Documentation coverage",
        summary="How much of the company is documented and how fresh: documents, spaces, "
        "coverage by kind of thing, and the services, applications, repositories, databases, "
        "capabilities and processes no document describes — or only stale ones — the most "
        "critical first.",
        category="documentation",
        input=CoverageAsked,
        output=DocumentationCoverageSaid,
        run=documentation_coverage,
        reads=(
            "document",
            "knowledge_space",
            "service",
            "application",
            "repository",
            "database",
            "business_capability",
            "business_process",
            "team",
        ),
        sources=(DOCUMENTATION,),
        limitations=(LIMITED, "Says what is documented, never whether what is written is true."),
    ),
    Skill(
        key="blast-radius",
        version=VERSION,
        title="Blast radius",
        summary="What a failure of one thing reaches: what depends on it directly and through "
        "others (three steps), the applications and the business capabilities and processes "
        "it carries, who answers for it.",
        category="architecture",
        input=OneAsked,
        output=BlastRadius,
        run=blast_radius,
        reads=(
            "service",
            "application",
            "database",
            "infra_resource",
            "repository",
            "business_capability",
            "business_process",
            "team",
            "person",
        ),
        limitations=(LIMITED, "Knows no redundancy: a dependency is counted, not its failover."),
    ),
    Skill(
        key="incident-history",
        version=VERSION,
        title="Incident history",
        summary="The incidents of a period, everywhere or on one thing: how many, how severe, "
        "how many still open, the median time to resolve, the longest, the causes that recur, "
        "the latest.",
        category="operations",
        input=HistoryAsked,
        output=IncidentHistory,
        run=incident_history,
        reads=("incident", "service", "application", "change", "deployment", "team", "person"),
        limitations=(
            LIMITED,
            "Severities are read from each tool's own words, mapped to critical, high, medium, "
            "low.",
        ),
    ),
    Skill(
        key="infrastructure-inventory",
        version=VERSION,
        title="Infrastructure inventory",
        summary="The cloud resources, in one account, of one service, or in one environment: "
        "how many by provider, kind, region and state; those no one owns, those reachable from "
        "the internet, those failed or stopped.",
        category="infrastructure",
        input=InventoryAsked,
        output=Inventory,
        run=infrastructure_inventory,
        reads=(
            "infra_resource",
            "cloud_account",
            "resource_group",
            "database",
            "service",
            "application",
            "team",
        ),
        sources=(CLOUDS,),
        limitations=(LIMITED, "No cost, no metric, no configuration drift."),
    ),
    Skill(
        key="data-landscape",
        version=VERSION,
        title="Data landscape",
        summary="The databases: their engine, schemas and objects, how sensitive what they hold "
        "is, who owns them, which services use them — and the tables, views and collections "
        "holding personal data or secrets.",
        category="data",
        input=DataAsked,
        output=DataLandscape,
        run=data_landscape,
        reads=("database", "schema", "data_object", "service", "team", "infra_resource"),
        sources=(DATABASES,),
        permission=Permission.WORKSPACE_READ.value,
        limitations=(
            LIMITED,
            "What a column holds is read from its name and comment, never from a value.",
        ),
    ),
    Skill(
        key="schema-health",
        version=VERSION,
        title="Schema health",
        summary="One database's structure, as its catalogue says it: its largest tables, the "
        "tables without a primary key, the foreign keys no index starts with, indexes on the "
        "same columns, money kept in a floating type, dates without their time zone.",
        category="data",
        input=SchemaAsked,
        output=SchemaHealth,
        run=schema_health,
        reads=("database", "schema", "data_object"),
        sources=(DATABASES,),
        permission=Permission.WORKSPACE_READ.value,
        limitations=(
            LIMITED,
            "The catalogue's structure and estimated sizes only: no query, no plan, no row.",
            "A foreign key is said unindexed when no index starts with its columns.",
        ),
    ),
    Skill(
        key="delivery-metrics",
        version=VERSION,
        title="Delivery metrics",
        summary="How a team ships, in DORA's terms, over a period, everywhere or for one "
        "service or repository, in production by default: deployment frequency, change failure "
        "rate, time to recover from incidents, and the tier of each — elite, high, medium, low.",
        category="operations",
        input=DeliveryAsked,
        output=DeliveryMetrics,
        run=delivery_metrics,
        reads=("deployment", "incident", "service", "application", "repository"),
        limitations=(
            LIMITED,
            "No lead time for changes: LEKA does not tie a commit to the deployment shipping it.",
            "A deployment counts as a failure when it failed, or when its source says it caused "
            "an incident.",
        ),
    ),
)
KEYS = tuple(skill.key for skill in LIBRARY)

register(*LIBRARY)
