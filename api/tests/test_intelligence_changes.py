"""Change and impact, judged (LEKA-378), pure.

Footprints as the company model reads them, in; signals, significance,
ranked impacts and findings out — no database.

What these protect: a change is notable for what is true of it — in
production, failed, followed by an incident, said by its source to have
caused one, reaching widely, held by the business, touching something
critical — and matters by that, a change made to nothing known by a third;
what is within 72 hours is current, older is history; what an incident hit
ranks first, then what it was made to, then the nearer; only current
changes that matter, or that an incident followed, become findings — high
when an incident followed, sure when the source says so, likely when only
time ties them — about the service it was made to, with what shows it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from leka.intelligence import Draft, Material, Severity
from leka.intelligence.changes import (
    change_impact,
    current,
    impacts,
    signals,
    significance,
)
from leka.knowledge import (
    BusinessTie,
    ChangeFootprint,
    ChangeIncident,
    ChangeReach,
    ChangeTouch,
    EntityBrief,
    EntityType,
    Lifecycle,
    RelationshipType,
)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
NS = uuid.UUID("00000000-0000-0000-0000-000000000378")


def brief(name: str, type_: EntityType = EntityType.SERVICE) -> EntityBrief:
    return EntityBrief(
        id=uuid.uuid5(NS, name),
        type=type_,
        key=f"{type_}:{name}",
        name=name,
        lifecycle=Lifecycle.ACTIVE,
    )


AUTH = brief("auth-service")
PAYMENT = brief("payment-api")
USERS = brief("user-service")
CHECKOUT = brief("checkout", EntityType.APPLICATION)
REPO = brief("acme/auth", EntityType.REPOSITORY)


def incident(
    name: str, *, on: EntityBrief | None, stated: bool = False, hours: float = 2
) -> ChangeIncident:
    return ChangeIncident(
        entity=brief(name, EntityType.INCIDENT),
        opened_at=NOW - timedelta(hours=26) + timedelta(hours=hours),
        severity="sev2",
        state="open",
        on=on,
        stated=stated,
    )


def footprint(
    *,
    kind: str = "deployment",
    hours_ago: float = 26,
    environment: str | None = "production",
    state: str | None = "succeeded",
    touched: tuple[EntityBrief, ...] = (AUTH,),
    reached: tuple[tuple[EntityBrief, int], ...] = ((PAYMENT, 1), (USERS, 2)),
    applications: tuple[EntityBrief, ...] = (),
    capabilities: tuple[str, ...] = (),
    incidents: tuple[ChangeIncident, ...] = (),
    criticality: str | None = None,
) -> ChangeFootprint:
    return ChangeFootprint(
        change=brief(f"{kind} {hours_ago}", EntityType.DEPLOYMENT),
        kind=kind,
        at=NOW - timedelta(hours=hours_ago),
        state=state,
        environment=environment,
        details={"ref": "v2.8.4", "commit": "4f2a1c9"},
        sources=["github"],
        source_ids=[],
        touched=[ChangeTouch(entity=t, how="part_of", criticality=criticality) for t in touched],
        reached=[
            ChangeReach(entity=r, distance=d, through=touched[0], criticality=None)
            for r, d in reached
        ],
        applications=list(applications),
        capabilities=[
            BusinessTie(
                entity=brief(c, EntityType.BUSINESS_CAPABILITY),
                relation=RelationshipType.SUPPORTED_BY,
                via=None,
                path="direct",
                origin="stated",
                rule="stated",
                confidence=1.0,
            )
            for c in capabilities
        ],
        processes=[],
        incidents=list(incidents),
    )


def judged(*footprints: ChangeFootprint) -> list[Draft]:
    return change_impact(Material(now=NOW, built_at=None, changes=footprints))


# ── signals and significance ───────────────────────────────────────────


def test_a_change_is_notable_for_what_is_true_of_it() -> None:
    plain = footprint(environment="staging", reached=())
    assert signals(plain) == ()

    loud = footprint(
        state="failed",
        applications=(CHECKOUT,),
        capabilities=("Payments",),
        incidents=(incident("OPS-1", on=PAYMENT), incident("OPS-2", on=None, stated=True)),
        criticality="critical",
    )
    assert signals(loud) == (
        "production",
        "failed",
        "incident_after",
        "stated_cause",
        "wide",
        "business",
        "critical",
    )


def test_it_matters_by_what_it_is_and_what_is_true_of_it() -> None:
    pull_request = footprint(kind="pull_request", environment=None, reached=())
    deployment = footprint()
    followed = footprint(incidents=(incident("OPS-1", on=PAYMENT),))

    assert significance(pull_request) < 0.4 <= significance(deployment) < significance(followed)
    # Made to nothing the model knows: a third.
    assert significance(footprint(touched=(), reached=())) < significance(footprint(reached=()))


def test_within_72_hours_it_is_current_older_is_history() -> None:
    assert current(footprint(hours_ago=71), NOW)
    assert not current(footprint(hours_ago=73), NOW)


# ── impact ─────────────────────────────────────────────────────────────


def test_what_an_incident_hit_ranks_first_then_what_it_was_made_to_then_the_nearer() -> None:
    ranked = impacts(footprint(applications=(CHECKOUT,), incidents=(incident("OPS-1", on=USERS),)))

    assert [item.subject.name for item in ranked] == [
        "user-service",  # two steps away, but an incident hit it
        "auth-service",  # what it was made to
        "payment-api",
        "checkout",
    ]
    assert ranked[0].reasons == ("depends_on:auth-service", "incident")
    assert ranked[-1].reasons == ("holds",)


# ── the analysis ───────────────────────────────────────────────────────


def test_a_change_an_incident_followed_is_high_about_what_it_was_made_to() -> None:
    [found] = judged(footprint(incidents=(incident("OPS-1841", on=PAYMENT),)))

    assert found.code == "change.impact"
    assert found.severity is Severity.HIGH
    assert found.subject.name == "auth-service"
    # Tied by time only: likely, not proven.
    assert found.confidence == 0.7
    assert found.params["incidents"] == 1
    assert found.params["top"] == ["payment-api", "auth-service", "user-service"]
    kinds = [e.kind for e in found.evidence]
    assert kinds[0] == "change" and "incident" in kinds
    said = next(e for e in found.evidence if e.kind == "incident")
    assert said.detail == "opened 2 h after, on payment-api"
    assert "v2.8.4" in found.evidence[0].detail


def test_a_change_its_source_says_caused_an_incident_is_sure() -> None:
    [found] = judged(footprint(incidents=(incident("OPS-9", on=None, stated=True, hours=60),)))

    assert (found.severity, found.confidence) == (Severity.HIGH, 1.0)
    assert next(e for e in found.evidence if e.kind == "incident").detail == (
        "its source says this change caused it"
    )


def test_production_reaching_is_medium_failed_production_reaching_is_high() -> None:
    [medium] = judged(footprint())
    [high] = judged(footprint(state="failed"))

    assert medium.severity is Severity.MEDIUM
    assert high.severity is Severity.HIGH


def test_history_and_changes_that_do_not_matter_make_no_finding() -> None:
    assert (
        judged(
            footprint(hours_ago=100, incidents=(incident("OPS-1", on=PAYMENT),)),
            footprint(kind="pull_request", environment=None, reached=()),
            footprint(environment="staging", reached=()),
        )
        == []
    )


def test_each_change_is_its_own_finding() -> None:
    found = judged(footprint(hours_ago=26), footprint(hours_ago=5))

    assert len({draft.key for draft in found}) == 2
