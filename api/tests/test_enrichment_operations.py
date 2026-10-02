"""What enrichment adds to incidents, changes and deployments (LEKA-367).

A workspace as resolution leaves it: Billing API, part of the Billing
platform, its repository acme/billing-api; an incident on it opened at
noon, acknowledged five minutes later; a deployment of the repository at
11:40, one of Ledger's at 11:50, one canceled at 11:55, one the day before;
a change to the Billing platform at 9:00.

What these protect: every date a record gives kept as it gives it — the
model's provenance says its source's; how long an incident waited, a
deployment ran; what changed before an incident, on what it affects —
through a repository's service, or an application holding it — the nearer
the surer, never what never ran nor what touched something else; a cause a
source states wins; an incident whose title names a service affects it.
"""

from __future__ import annotations

from typing import Any

from leka.ingestion.enrichment import enrich
from leka.ingestion.enrichment.engine import Edge, Enrichment
from tests.test_enrichment import GITHUB, JIRA, PAGERDUTY, World

BILLING = "service:billing-api"
LEDGER = "service:ledger"
PLATFORM = "application:billing-platform"
REPO = "github.com/acme/billing-api"
INCIDENT = "incident:pagerduty:Q1"
NEAR = "github.com/acme/billing-api/deployments/1"
ELSEWHERE = "github.com/acme/ledger/deployments/2"
CANCELED = "github.com/acme/billing-api/deployments/3"
YESTERDAY = "github.com/acme/billing-api/deployments/4"
UPGRADE = "change:pagerduty:PCE1"


def _world() -> World:
    w = World()
    w.thing(BILLING, "Billing API", type="service", sources=(PAGERDUTY,))
    w.thing(LEDGER, "Ledger", type="service", sources=(PAGERDUTY,))
    w.thing(PLATFORM, "Billing platform", type="application", sources=(PAGERDUTY,))
    w.thing(REPO, "acme/billing-api", type="repository")
    w.states(GITHUB, REPO, "part_of", BILLING)
    w.states(PAGERDUTY, BILLING, "part_of", PLATFORM)
    w.thing(
        INCIDENT,
        "Checkout errors",
        type="incident",
        sources=(PAGERDUTY,),
        links=("https://acme.pagerduty.com/incidents/Q1",),
        created_at="2026-09-28T12:00:00Z",
        acknowledged_at="2026-09-28T12:05:00Z",
        updated_at="2026-09-28T13:00:00Z",
    )
    w.states(PAGERDUTY, INCIDENT, "affects", BILLING)
    for key, repo, created, finished, state in (
        (NEAR, REPO, "2026-09-28T11:30:00Z", "2026-09-28T11:40:00Z", "succeeded"),
        (YESTERDAY, REPO, "2026-09-27T09:00:00Z", "2026-09-27T09:10:00Z", "succeeded"),
        (CANCELED, REPO, "2026-09-28T11:55:00Z", None, "canceled"),
    ):
        dates: dict[str, Any] = {"created_at": created}
        if finished:
            dates["finished_at"] = finished
        w.thing(key, key.rsplit("/", 1)[-1], type="deployment", state=state, **dates)
        w.states(GITHUB, key, "part_of", repo)
    w.thing(
        ELSEWHERE,
        "2",
        type="deployment",
        state="succeeded",
        created_at="2026-09-28T11:50:00Z",
        finished_at="2026-09-28T11:50:00Z",
    )
    w.states(GITHUB, ELSEWHERE, "part_of", LEDGER)
    w.thing(
        UPGRADE,
        "Upgrade the platform",
        type="change",
        sources=(PAGERDUTY,),
        created_at="2026-09-28T09:00:00Z",
    )
    w.states(PAGERDUTY, UPGRADE, "affects", PLATFORM)
    return w


def _causes(enrichment: Enrichment, w: World, key: str) -> dict[str, Edge]:
    keys = {node.id: node.key for node in w.nodes.values()}
    return {
        keys[e.to_id]: e
        for e in enrichment.edges
        if e.from_id == w.id(key) and e.type == "caused_by"
    }


def _facts(enrichment: Enrichment, w: World, key: str) -> dict[str, object]:
    return {f.attribute: f.value for f in enrichment.facts if f.entity_id == w.id(key)}


def test_every_date_an_event_s_record_gives_is_kept_as_it_gives_it() -> None:
    w = _world()

    enrichment = enrich(w.snapshot())

    facts = {f.attribute: f for f in enrichment.facts if f.entity_id == w.id(INCIDENT)}
    assert (facts["created_at"].value, facts["acknowledged_at"].value) == (
        "2026-09-28T12:00:00Z",
        "2026-09-28T12:05:00Z",
    )
    assert facts["created_at"].rule == "record"
    # Its last update moves with every edit: not an event's date.
    assert "updated_at" not in facts
    assert facts["url"].value == "https://acme.pagerduty.com/incidents/Q1"


def test_how_long_an_incident_waited_and_a_deployment_ran() -> None:
    w = _world()

    enrichment = enrich(w.snapshot())

    assert _facts(enrichment, w, INCIDENT)["time_to_acknowledge_minutes"] == 5
    assert _facts(enrichment, w, NEAR)["duration_minutes"] == 10


def test_what_changed_shortly_before_an_incident_on_what_it_affects() -> None:
    w = _world()

    causes = _causes(enrich(w.snapshot()), w, INCIDENT)

    # Its repository's deployment, 20 minutes before; the platform's change,
    # three hours before — the application holding the service.
    assert set(causes) == {NEAR, UPGRADE}
    near = causes[NEAR]
    assert (near.origin, near.rule, near.confidence) == ("inferred", "preceded", 0.7)
    assert causes[UPGRADE].confidence == 0.6
    assert "20 minutes before" in near.evidence


def test_a_cause_a_source_states_wins_over_any_suspicion() -> None:
    w = _world()
    w.states(JIRA, INCIDENT, "caused_by", YESTERDAY)

    causes = _causes(enrich(w.snapshot()), w, INCIDENT)

    assert set(causes) == {YESTERDAY}
    assert causes[YESTERDAY].origin == "stated"


def test_an_incident_whose_title_names_a_service_affects_it() -> None:
    w = _world()
    w.thing("acme.atlassian.net/OPS-9", "Ledger timeouts", type="incident", sources=(JIRA,))

    enrichment = enrich(w.snapshot())

    edge = next(
        e
        for e in enrichment.edges
        if e.from_id == w.id("acme.atlassian.net/OPS-9") and e.to_id == w.id(LEDGER)
    )
    assert (edge.type, edge.rule) == ("affects", "named_in_title")
