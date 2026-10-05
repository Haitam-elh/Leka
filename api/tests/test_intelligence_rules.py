"""The intelligence engine's frame and its first analyses (LEKA-377), pure.

Cards and links as the architecture reads them, in; drafts out — no
database.

What these protect: what three things or more rely on is a concentration —
low when watched and well, medium unwatched, high when many rely on it and
nothing watches it or when it is unwell — counted once per thing, by the
roles that are reliance, with each dependent and the file that says so;
what runs or keeps data with no team is said — graver the more rely on it,
lighter when people maintain it; the contexts in use that failed, fell
behind or were judged weak are said, and only those. And the frame: an
analysis that raises is `failed`, one too slow `timed_out`, one that needs
a model or material it does not have `skipped` — never the run's error; a
key said twice is one finding; severity orders before score; a new
version is a new catalogue.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

from leka.intelligence import (
    ANALYZERS,
    Analyzer,
    ContextStanding,
    Draft,
    Material,
    Method,
    Reads,
    Severity,
    Subject,
    catalogue_hash,
    execute,
)
from leka.intelligence.rules import context_health, dependency_concentration, ownership
from leka.knowledge import (
    ArchitectureCardRead,
    ArchitectureLinkRead,
    ArchitectureRead,
    EntityBrief,
    EntityType,
    Lifecycle,
)
from leka.knowledge.schemas import ArchitectureFiguresRead

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
NS = uuid.UUID("00000000-0000-0000-0000-000000000377")


def card(
    name: str,
    *,
    kind: str = "api",
    column: str = "services",
    status: str | None = "operational",
    deduced: bool = False,
    team: str | None = None,
    maintainers: tuple[str, ...] = (),
    sources: tuple[str, ...] = ("github",),
    type_: str = "service",
) -> ArchitectureCardRead:
    entity = uuid.uuid5(NS, name)
    return ArchitectureCardRead(
        id=str(entity),
        column=column,
        group="github",
        kind=kind,
        type=type_,
        name=name,
        entity_id=entity,
        key=f"service:{name}",
        status=status,
        deduced=deduced,
        why=None,
        technology=[],
        description=None,
        environment=None,
        region=None,
        url=None,
        team=_brief(team, EntityType.TEAM) if team else None,
        repository_id=None,
        host_id=None,
        deployment=None,
        stats={},
        evidence=[],
        sources=list(sources),
        facts={},
        parts=[],
        files=[],
        maintainers=[_brief(person, EntityType.PERSON) for person in maintainers],
    )


def _brief(name: str, type_: EntityType) -> EntityBrief:
    return EntityBrief(
        id=uuid.uuid5(NS, f"{type_}:{name}"),
        type=type_,
        key=f"{type_}:{name}",
        name=name,
        lifecycle=Lifecycle.ACTIVE,
    )


def link(
    a: ArchitectureCardRead,
    b: ArchitectureCardRead,
    role: str = "stores",
    *,
    origin: str = "stated",
    confidence: float = 1.0,
    evidence: str | None = None,
) -> ArchitectureLinkRead:
    return ArchitectureLinkRead(
        from_id=a.id,
        to_id=b.id,
        role=role,
        origin=origin,
        rule="stated" if origin == "stated" else "deployed_together",
        confidence=confidence,
        evidence=evidence,
        status=None,
    )


def material(
    cards: list[ArchitectureCardRead],
    links: list[ArchitectureLinkRead],
    contexts: tuple[ContextStanding, ...] | None = None,
    owners: dict[uuid.UUID, tuple[str, ...]] | None = None,
) -> Material:
    return Material(
        now=NOW,
        built_at=NOW - timedelta(minutes=5),
        owners=owners or {},
        architecture=ArchitectureRead(
            built_at=NOW - timedelta(minutes=5),
            environment=None,
            environments=[],
            groups=[],
            cards=cards,
            links=links,
            bundles=[],
            figures=ArchitectureFiguresRead(
                services=0,
                applications=0,
                repositories=0,
                databases=0,
                stores=0,
                cloud_resources=0,
                providers={},
                external=0,
                teams=0,
                tables=0,
            ),
            health={},
            services_by_status={},
            top_dependencies=[],
            detailed=True,
            flows=[],
            checks=[],
            sources=[],
        ),
        contexts=contexts,
    )


def _store(**kwargs: object) -> ArchitectureCardRead:
    return card("postgresql", kind="database", column="data", type_="database", **kwargs)  # type: ignore[arg-type]


def _users(n: int) -> list[ArchitectureCardRead]:
    return [card(f"service-{i}", team="Platform") for i in range(n)]


# ── dependency concentration ───────────────────────────────────────────


def test_what_three_things_rely_on_is_said_low_when_watched_and_well() -> None:
    store = _store(team="Data", sources=("github", "datadog"))
    users = _users(3)

    [found] = dependency_concentration(
        material(
            [store, *users],
            [link(u, store, evidence="compose.yml:12 — DATABASE_URL") for u in users],
        )
    )

    assert found.code == "dependency.concentration"
    assert found.severity is Severity.LOW
    assert found.subject == Subject(
        type="entity", id=store.entity_id, name="postgresql", kind="database"
    )
    assert found.params["dependents"] == 3
    assert found.key == f"entity:{store.entity_id}"
    # Each dependent, with the file and line that says so.
    assert [e.name for e in found.evidence[1:]] == [f"service-{i} → postgresql" for i in range(3)]
    assert found.evidence[1].detail == "stores: compose.yml:12 — DATABASE_URL"
    assert set(found.sources) == {"github", "datadog"}


def test_two_are_not_a_concentration() -> None:
    store = _store()
    users = _users(2)

    assert (
        dependency_concentration(material([store, *users], [link(u, store) for u in users])) == []
    )


def test_unwatched_it_weighs_more_and_many_unwatched_is_high() -> None:
    deduced = _store(deduced=True)
    three = _users(3)
    [medium] = dependency_concentration(
        material([deduced, *three], [link(u, deduced) for u in three])
    )
    assert medium.severity is Severity.MEDIUM
    assert "deduced" in medium.statement

    # No state known at all: nothing watches it either.
    [unknown] = dependency_concentration(
        material([_store(status=None), *three], [link(u, _store(status=None)) for u in three])
    )
    assert (unknown.severity, unknown.params["watched"]) == (Severity.MEDIUM, False)

    five = _users(5)
    unwatched = _store(status="unmonitored")
    [high] = dependency_concentration(
        material([unwatched, *five], [link(u, unwatched) for u in five])
    )
    assert high.severity is Severity.HIGH


def test_unwell_it_is_high_whatever_else() -> None:
    store = _store(status="incident", team="Data")
    users = _users(3)

    [found] = dependency_concentration(material([store, *users], [link(u, store) for u in users]))

    assert found.severity is Severity.HIGH
    assert "incident" in found.statement


def test_only_reliance_counts_and_each_dependent_once() -> None:
    store = _store()
    users = _users(3)
    links = [
        link(users[0], store, "stores"),
        link(users[0], store, "cache"),  # the same dependent again
        link(users[1], store, "monitored_by"),  # not reliance
        link(users[2], store, "part_of"),  # not reliance
    ]

    assert dependency_concentration(material([store, *users], links)) == []


def test_an_inferred_link_makes_it_less_sure() -> None:
    store = _store()
    users = _users(3)
    links = [
        link(users[0], store, origin="inferred", confidence=0.4),
        *(link(u, store) for u in users[1:]),
    ]

    [found] = dependency_concentration(material([store, *users], links))

    assert found.confidence == 0.8
    assert found.evidence[1].detail.endswith("(inferred)")


# ── ownership ──────────────────────────────────────────────────────────


def test_what_runs_with_no_owner_is_said_and_with_a_team_or_a_person_is_not() -> None:
    lone = card("billing")
    owned = card("ledger", team="Finance")
    # A person a source says owns it — `owns`, not a team: it has an owner.
    personal = card("payment-api")
    assert personal.entity_id is not None

    [found] = ownership(
        material([lone, owned, personal], [], owners={personal.entity_id: ("Nadia Kowalski",)})
    )

    assert found.code == "ownership.no_owner"
    assert found.subject.name == "billing"
    assert found.severity is Severity.MEDIUM
    assert found.confidence == 0.9


def test_a_store_with_no_owner_is_lighter_and_heavier_the_more_rely_on_it() -> None:
    store = _store()
    [alone] = ownership(material([store], []))
    assert alone.severity is Severity.LOW

    users = _users(3)
    [relied] = ownership(material([store, *users], [link(u, store) for u in users]))
    assert relied.severity is Severity.HIGH
    assert relied.params["dependents"] == 3
    assert "3 things rely on it" in relied.statement
    [one] = ownership(material([store, users[0]], [link(users[0], store)]))
    assert "1 thing relies on it" in one.statement


def test_people_who_maintain_it_make_it_one_step_lighter() -> None:
    lone = card("billing", maintainers=("Nora", "Karim"))

    [found] = ownership(material([lone], []))

    assert found.severity is Severity.LOW
    assert found.params["maintainers"] == ["Nora", "Karim"]
    assert "Nora, Karim maintain it" in found.statement
    assert [s.name for s in found.related] == ["Nora", "Karim"]


def test_code_cloud_modules_and_tools_are_not_asked_for_an_owner() -> None:
    things = [
        card("acme/shop", column="code", kind="repository", type_="repository"),
        card("i-0leka", column="cloud", kind="instance", type_="infra_resource"),
        card("shop/api", kind="module", type_="module"),
    ]

    assert ownership(material(things, [])) == []


# ── context health ─────────────────────────────────────────────────────


def context(
    title: str,
    *,
    status: str = "assembled",
    follow: bool = True,
    used: timedelta | None = timedelta(days=1),
    stale: timedelta | None = None,
    pending: int = 0,
    level: str | None = "high",
    score: float | None = 0.9,
) -> ContextStanding:
    return ContextStanding(
        id=uuid.uuid5(NS, title),
        title=title,
        status=status,
        follow=follow,
        version=3,
        used_at=NOW - used if used is not None else None,
        stale_since=NOW - stale if stale is not None else None,
        pending=pending,
        level=level,
        score=score,
    )


def _health(*contexts: ContextStanding) -> dict[str, Draft]:
    found = context_health(Material(now=NOW, built_at=None, contexts=contexts))
    return {draft.key.rsplit(":", 1)[1] + ":" + draft.subject.name: draft for draft in found}


def test_a_context_in_use_that_failed_is_high() -> None:
    found = _health(context("Payment API", status="failed"))

    assert found["failed:Payment API"].severity is Severity.HIGH
    assert found["failed:Payment API"].context_version == 3


def test_a_context_in_use_behind_the_model_is_said_with_how_far() -> None:
    found = _health(context("Payment API", stale=timedelta(days=2), pending=6))

    behind = found["behind:Payment API"]
    assert behind.severity is Severity.MEDIUM
    assert behind.params["pending"] == 6
    assert behind.subject.type == "context"


def test_not_following_just_behind_or_unused_is_not_said() -> None:
    assert (
        _health(
            context("chosen", follow=False, stale=timedelta(days=2), pending=6),
            context("just now", stale=timedelta(hours=2), pending=6),
            context("old", used=timedelta(days=40), status="failed"),
            context("never used", used=None, status="failed"),
            context("archived", status="archived", level="low"),
        )
        == {}
    )


def test_a_weak_context_is_said_lighter_when_little_used() -> None:
    found = _health(
        context("Payment API", level="low", score=0.42),
        context("Orders", level="low", score=0.2, used=timedelta(days=12)),
    )

    assert found["weak:Payment API"].severity is Severity.MEDIUM
    assert "0.42" in found["weak:Payment API"].statement
    assert found["weak:Orders"].severity is Severity.LOW


# ── the frame ──────────────────────────────────────────────────────────


def _analyzer(run: object, **overrides: object) -> Analyzer:
    fields: dict[str, object] = {
        "name": "probe",
        "version": 1,
        "category": "test",
        "method": Method.RULES,
        "reads": frozenset(),
        "summary": "A probe.",
        "run": run,
        "budget": 5.0,
    }
    fields |= overrides
    return Analyzer(**fields)  # type: ignore[arg-type]


def _draft(key: str, severity: Severity = Severity.LOW, score: float = 0.0) -> Draft:
    return Draft(
        key=key,
        code="probe.found",
        severity=severity,
        subject=Subject(type="entity", id=None, name=key),
        statement=key,
        score=score,
    )


async def test_an_analysis_that_raises_is_failed_not_the_run_s_error() -> None:
    def broken(_: Material) -> list[Draft]:
        raise KeyError("missing")

    outcome = await execute(_analyzer(broken), Material(now=NOW, built_at=None))

    assert (outcome.status, outcome.error, outcome.drafts) == ("failed", "KeyError", ())


async def test_an_analysis_past_its_budget_is_timed_out() -> None:
    def slow(_: Material) -> list[Draft]:
        time.sleep(0.3)
        return [_draft("late")]

    outcome = await execute(_analyzer(slow, budget=0.05), Material(now=NOW, built_at=None))

    assert (outcome.status, outcome.error) == ("timed_out", "TimeoutError")


async def test_what_cannot_run_here_is_skipped_and_says_why() -> None:
    nothing = Material(now=NOW, built_at=None)

    model = await execute(_analyzer(lambda _: [], method=Method.MODEL), nothing)
    unread = await execute(_analyzer(lambda _: [], reads=frozenset({Reads.MODEL})), nothing)

    assert (model.status, model.reason) == ("skipped", "no_model")
    assert (unread.status, unread.reason) == ("skipped", "no_material")


async def test_a_key_said_twice_is_one_finding_the_last_said() -> None:
    outcome = await execute(
        _analyzer(lambda _: [_draft("a", Severity.LOW), _draft("a", Severity.HIGH)]),
        Material(now=NOW, built_at=None),
    )

    assert [(d.key, d.severity) for d in outcome.drafts] == [("a", Severity.HIGH)]


def test_severity_orders_before_score() -> None:
    assert _draft("x", Severity.HIGH, 0.0).rank > _draft("y", Severity.MEDIUM, 1.0).rank
    assert _draft("x", Severity.MEDIUM, 0.9).rank > _draft("y", Severity.MEDIUM, 0.1).rank
    assert _draft("x", Severity.LOW, 5.0).rank == 199


def test_a_new_version_is_a_new_catalogue_and_each_analysis_is_named_once() -> None:
    names = [analyzer.name for analyzer in ANALYZERS]
    assert len(names) == len(set(names))
    assert all(analyzer.summary and analyzer.category for analyzer in ANALYZERS)

    bumped = [
        _analyzer(a.run, name=a.name, version=a.version + (a.name == "ownership"))
        for a in ANALYZERS
    ]
    assert catalogue_hash(bumped) != catalogue_hash(ANALYZERS)
    assert catalogue_hash(list(reversed(ANALYZERS))) == catalogue_hash(ANALYZERS)
