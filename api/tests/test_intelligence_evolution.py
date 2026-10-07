"""What the model's recent course says (LEKA-383): pure, no database.

One month of a company, written as leka.knowledge reads it. payment-api
came to depend on three more things; user-service went from Nadia to
Thomas; the billing queue lost its owner; redis-sessions went from every
source while auth-service relied on it — and mysql-legacy went too, but
user-service moved to postgres-prod in the same build; three things
appeared; checkout had four incidents this month and one the month before;
the feature-flags service changed five times; what LEKA knows of the
company, of a team, of an application, can be trusted less than a month
ago.

What these protect: each insight is found on what shows it, and only
then — under its threshold, it is not; what the first build made is no
change; a removed thing's dependents that moved are no risk; an event is
not volatile; every finding carries its insight, its recommendation and
the changes that show it; without the material, nothing runs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from leka.intelligence.analysis import (
    Draft,
    Material,
    QualityMove,
    Reads,
    Severity,
    Subject,
    skip_reason,
)
from leka.intelligence.evolution import (
    ANALYZERS,
    architecture,
    dependencies,
    incidents,
    ownership,
    quality,
    removals,
    volatility,
)
from leka.knowledge import (
    EvolutionMaterial,
    EvolvedEntity,
    EvolvedIncident,
    EvolvedTie,
    EvolvedVersion,
)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
BEGAN = NOW - timedelta(days=40)
RUN = uuid.uuid4()


def _id() -> uuid.UUID:
    return uuid.uuid4()


def thing(
    name: str,
    kind: str = "service",
    *,
    lifecycle: str = "active",
    criticality: str | None = None,
    dependents: int = 0,
    dependencies: int = 0,
    owners: tuple[str, ...] = (),
) -> EvolvedEntity:
    return EvolvedEntity(
        id=_id(),
        type=kind,
        name=name,
        lifecycle=lifecycle,
        criticality=criticality,
        dependents=dependents,
        dependencies=dependencies,
        owners=list(owners),
    )


PAYMENT = thing("payment-api", criticality="critical", dependents=2, dependencies=5)
AUTH = thing("auth-service", dependents=3)
USERS = thing("user-service", owners=("Thomas Berger",))
QUEUE = thing("billing-queue", "infra_resource")
REDIS = thing("redis-sessions", "infra_resource", lifecycle="removed")
MYSQL = thing("mysql-legacy", "database", lifecycle="removed")
POSTGRES = thing("postgres-prod", "database", dependents=2)
NADIA, THOMAS, PLATFORM = (
    thing("Nadia K", "person"),
    thing("Thomas Berger", "person"),
    thing("Platform", "team"),
)
LEDGER, FX, TAX = thing("ledger-api"), thing("fx-rates"), thing("tax-service")
CHECKOUT = thing("checkout")
ORDERS = thing("orders", criticality="high")
FLAGS = thing("feature-flags")
INCIDENT = thing("OPS-1", "incident")
EVERY = (
    PAYMENT, AUTH, USERS, QUEUE, REDIS, MYSQL, POSTGRES, NADIA, THOMAS, PLATFORM,
    LEDGER, FX, TAX, CHECKOUT, ORDERS, FLAGS, INCIDENT,
)  # fmt: skip


def tie(
    start: EvolvedEntity,
    kind: str,
    end: EvolvedEntity,
    change: str = "added",
    *,
    days: float = 5,
    run: uuid.UUID = RUN,
) -> EvolvedTie:
    return EvolvedTie(
        id=_id(),
        type=kind,
        change=change,
        from_id=start.id,
        to_id=end.id,
        recorded_at=NOW - timedelta(days=days),
        run_id=run,
    )


def version(
    entity: EvolvedEntity,
    change: str,
    *,
    days: float = 5,
    number: int = 2,
    fields: tuple[str, ...] = (),
) -> EvolvedVersion:
    return EvolvedVersion(
        id=_id(),
        entity_id=entity.id,
        version=number,
        change=change,
        fields=list(fields),
        recorded_at=NOW - timedelta(days=days),
        run_id=RUN,
    )


def incident(name: str, days: float, *affects: EvolvedEntity) -> EvolvedIncident:
    return EvolvedIncident(
        id=_id(),
        name=name,
        occurred_at=NOW - timedelta(days=days),
        severity="sev2",
        affects=[a.id for a in affects],
    )


MOVED = _id()
TIES = [
    # payment-api: three more dependencies.
    tie(PAYMENT, "depends_on", LEDGER, days=20),
    tie(PAYMENT, "depends_on", FX, days=12),
    tie(PAYMENT, "depends_on", TAX, days=3),
    # user-service: Nadia to Thomas; the billing queue: its owner went.
    tie(NADIA, "owns", USERS, "removed", days=14),
    tie(THOMAS, "owns", USERS, days=14),
    tie(QUEUE, "owned_by", PLATFORM, "removed", days=9),
    # redis-sessions went; auth-service relied on it, and on nothing new.
    tie(AUTH, "depends_on", REDIS, "removed", days=6),
    # mysql-legacy went; user-service moved to postgres-prod in that build.
    tie(USERS, "depends_on", MYSQL, "removed", days=8, run=MOVED),
    tie(USERS, "depends_on", POSTGRES, days=8, run=MOVED),
    # What the first build made is no change.
    tie(FLAGS, "depends_on", LEDGER, days=40),
    tie(FLAGS, "depends_on", FX, days=40),
    tie(FLAGS, "depends_on", TAX, days=40),
]
VERSIONS = [
    version(REDIS, "removed", days=6, number=4),
    version(MYSQL, "removed", days=8, number=7),
    version(LEDGER, "created", days=20, number=1),
    version(FX, "created", days=12, number=1),
    version(TAX, "created", days=3, number=1),
    *(version(FLAGS, "changed", days=d, number=n, fields=("attributes.version",)) for n, d in
      enumerate((25, 18, 11, 6, 2), start=2)),
    *(version(INCIDENT, "changed", days=d, number=n, fields=("attributes.state",)) for n, d in
      enumerate((9, 8, 7, 6), start=2)),
    version(POSTGRES, "created", days=40, number=1),
]  # fmt: skip
INCIDENTS = [
    *(incident(f"checkout {n}", d, CHECKOUT) for n, d in enumerate((2, 9, 15, 27))),
    incident("checkout earlier", 45, CHECKOUT),
    incident("payment once", 4, PAYMENT),
]


def material(**overrides: object) -> Material:
    said: dict[str, object] = {
        "since": NOW - timedelta(days=30),
        "incidents_since": NOW - timedelta(days=60),
        "until": NOW,
        "began_at": BEGAN,
        "versions": VERSIONS,
        "ties": TIES,
        "incidents": INCIDENTS,
        "entities": {e.id: e for e in EVERY},
        "truncated": False,
        **overrides,
    }
    return Material(now=NOW, built_at=NOW, evolution=EvolutionMaterial.model_validate(said))


def by_subject(drafts: list[Draft]) -> dict[str, Draft]:
    return {d.subject.name: d for d in drafts}


def test_what_depends_on_more_than_a_month_ago() -> None:
    found = by_subject(dependencies(material()))

    payment = found.pop("payment-api")
    assert found == {}  # feature-flags' were its first build's
    assert payment.code == "evolution.dependencies_grew"
    assert payment.severity is Severity.MEDIUM  # critical
    assert payment.params["added"] == 3
    assert payment.params["names"] == ["fx-rates", "ledger-api", "tax-service"]
    assert (payment.params["insight"], payment.params["recommendation"]) == (
        "dependency",
        "review_dependencies",
    )
    assert {e.kind for e in payment.evidence} == {"relationship_change"}
    assert len(payment.evidence) == 3

    # Two more, one gone: one more, under the threshold.
    fewer = [*TIES[:2], tie(PAYMENT, "depends_on", POSTGRES, "removed")]
    assert dependencies(material(ties=fewer)) == []


def test_an_owner_lost_and_an_owner_changed() -> None:
    found = by_subject(ownership(material()))

    lost, changed = found["billing-queue"], found["user-service"]
    assert (lost.code, lost.severity, lost.params["before"]) == (
        "evolution.owner_lost",
        Severity.MEDIUM,
        ["Platform"],
    )
    assert lost.params["recommendation"] == "name_owner"
    assert (changed.code, changed.severity) == ("evolution.owner_changed", Severity.LOW)
    assert (changed.params["before"], changed.params["after"]) == (["Nadia K"], ["Thomas Berger"])
    assert changed.params["insight"] == "organisational"
    assert len(changed.evidence) == 2


def test_what_went_while_things_relied_on_it() -> None:
    found = by_subject(removals(material()))

    # mysql-legacy went, but user-service moved to postgres-prod: no risk.
    assert set(found) == {"redis-sessions"}
    redis = found["redis-sessions"]
    assert redis.code == "evolution.removed_relied"
    assert redis.severity is Severity.MEDIUM
    assert (redis.params["names"], redis.params["recommendation"]) == (
        ["auth-service"],
        "confirm_removal",
    )
    assert [e.kind for e in redis.evidence] == ["version", "relationship_change"]

    # Relied on by a critical thing: high.
    critical = [*TIES, tie(ORDERS, "depends_on", REDIS, "removed", days=6)]
    [high] = removals(material(ties=critical))
    assert high.severity is Severity.HIGH


def test_the_architecture_moved_said_once_for_the_workspace() -> None:
    [moved] = architecture(material())

    assert moved.subject.type == "workspace"
    assert (moved.params["created"], moved.params["removed"]) == (3, 2)
    assert moved.params["appeared"] == ["fx-rates", "ledger-api", "tax-service"]
    assert moved.params["went"] == ["mysql-legacy", "redis-sessions"]
    # postgres-prod came with the first build: not counted.
    assert "postgres-prod" not in moved.params["appeared"]
    assert architecture(material(versions=VERSIONS[2:4])) == []


def test_incidents_rising_twice_the_month_before() -> None:
    [checkout] = incidents(material())

    assert checkout.subject.name == "checkout"
    assert (checkout.params["recent"], checkout.params["before"]) == (4, 1)
    assert (checkout.severity, checkout.params["recommendation"]) == (
        Severity.MEDIUM,
        "investigate_incidents",
    )
    assert len(checkout.evidence) == 4
    # Three before: not twice.
    many_before = [*INCIDENTS, *(incident("old", d, CHECKOUT) for d in (40, 50))]
    assert incidents(material(incidents=many_before)) == []


def test_what_changed_again_and_again_and_not_an_event() -> None:
    [flags] = volatility(material())

    assert flags.subject.name == "feature-flags"
    assert (flags.params["changes"], flags.params["fields"]) == (5, ["attributes.version"])
    assert flags.params["insight"] == "risk"


def _move(
    before: float, after: float, levels: tuple[str, str], scope: str = "workspace"
) -> QualityMove:
    return QualityMove(
        key=scope if scope == "workspace" else f"{scope}:{PAYMENT.id}",
        scope=scope,
        subject=Subject(type=scope if scope == "workspace" else "entity", id=None, name="Acme"),
        column=None,
        before=before,
        after=after,
        level_before=levels[0],
        level_after=levels[1],
        since=NOW - timedelta(days=30),
    )


def test_what_lost_knowledge_quality_this_month() -> None:
    moves = (
        _move(0.82, 0.70, ("medium", "medium")),  # fell .12
        _move(0.88, 0.84, ("high", "medium"), scope="team"),  # a level lower
        _move(0.70, 0.55, ("medium", "low"), scope="application"),  # to low
        _move(0.70, 0.66, ("medium", "medium"), scope="column"),  # too little
        _move(0.60, 0.80, ("medium", "medium"), scope="column"),  # better
    )
    found = quality(
        Material(now=NOW, built_at=NOW, evolution=material().evolution, quality_moves=moves)
    )

    assert [(d.params["scope"], d.severity) for d in found] == [
        ("workspace", Severity.LOW),
        ("team", Severity.LOW),
        ("application", Severity.MEDIUM),
    ]
    workspace = found[0]
    assert workspace.code == "evolution.quality_fell"
    assert (workspace.params["before"], workspace.params["after"]) == (0.82, 0.7)
    assert (workspace.params["insight"], workspace.params["recommendation"]) == (
        "risk",
        "review_quality",
    )
    assert workspace.subject.type == "workspace"
    assert [e.kind for e in workspace.evidence] == ["quality"]


def test_without_the_material_nothing_runs() -> None:
    bare = Material(now=NOW, built_at=NOW)
    for analyzer in ANALYZERS:
        assert analyzer.reads == frozenset({Reads.EVOLUTION})
        assert analyzer.category == "evolution"
        assert skip_reason(analyzer, bare) == "no_material"
        assert analyzer.run(bare) == []


@pytest.mark.parametrize("analyzer", ANALYZERS, ids=lambda a: a.name)
def test_every_finding_says_its_insight_and_what_to_do(analyzer: object) -> None:
    for draft in analyzer.run(material()):  # type: ignore[attr-defined]
        assert draft.code.startswith("evolution.")
        assert draft.params["insight"] in {
            "dependency",
            "architecture",
            "operational",
            "organisational",
            "risk",
        }
        assert draft.params["recommendation"]
        assert draft.evidence
        assert 0 <= draft.score <= 1
