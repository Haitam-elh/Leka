"""Knowledge gaps (LEKA-379), pure.

The architecture, what the model holds around each thing, the sources and
the current changes, in; gaps out — no database.

What these protect: each family of gap has its own code — a missing
entity, a missing relationship, missing or stale documentation, a stale
source or dormant knowledge, a whole family not connected — so they are
told apart; a per-thing gap is said only when the family of sources that
would fill it is connected, otherwise once, as coverage; priority is its
documented base plus what makes the thing matter — relied on, critical,
unwell, in production, changing now — capped at 1, high from 0.6, medium
from 0.35; each gap keeps the thing, the source or the census that shows
it, and the kinds of sources it rests on; a gap analysis runs without the
changes, which only weigh it.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from itertools import pairwise

import pytest

from leka.intelligence import ANALYZERS, Draft, Material, Reads, Severity, execute
from leka.intelligence.gaps import ANALYZERS as GAPS
from leka.intelligence.gaps import (
    BASE,
    coverage,
    documentation,
    missing_entities,
    missing_relationships,
    priority,
    staleness,
)
from leka.knowledge import (
    ArchitectureCardRead,
    ArchitectureLinkRead,
    ArchitectureRead,
    ChangeFootprint,
    EntityStanding,
    Lifecycle,
)
from leka.knowledge.schemas import ArchitectureSourceRead
from tests.test_intelligence_changes import footprint
from tests.test_intelligence_rules import NOW, card, link
from tests.test_intelligence_rules import material as architecture_of

CATEGORIES = {
    "datadog": "observability",
    "aws": "cloud",
    "github": "code",
    "confluence": "docs",
    "postgresql": "data",
    "jira": "project",
}
EVERY = ("datadog", "aws", "github", "postgresql")


def source(
    kind: str,
    *,
    status: str = "active",
    read: timedelta | None = timedelta(hours=1),
    entities: int = 4,
    name: str | None = None,
) -> ArchitectureSourceRead:
    return ArchitectureSourceRead(
        source_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{kind}:{name}"),
        kind=kind,
        name=name or kind,
        status=status,
        last_synced_at=NOW - read if read is not None else None,
        entities=entities,
    )


def standing(
    *,
    documents: int = 1,
    fresh: int = 1,
    last: str | None = None,
    business: bool = True,
    criticality: str | None = None,
    lifecycle: Lifecycle = Lifecycle.ACTIVE,
) -> EntityStanding:
    return EntityStanding(
        criticality=criticality,
        lifecycle=lifecycle,
        documents=documents,
        fresh_documents=fresh,
        last_documented_at=last,
        business=business,
    )


def known(
    name: str,
    *,
    host: bool = True,
    code: bool = True,
    environment: str | None = None,
    status: str | None = "operational",
    column: str = "services",
    type_: str = "service",
    tables: int = 0,
) -> ArchitectureCardRead:
    """A card whose runtime and code are known unless said otherwise."""
    return card(name, status=status, column=column, type_=type_).model_copy(
        update={
            "host_id": "cluster" if host else None,
            "repository_id": "repo" if code else None,
            "environment": environment,
            "stats": {"tables": tables} if tables else {},
        }
    )


def database(name: str = "postgres-prod", *, tables: int = 0) -> ArchitectureCardRead:
    return known(name, column="data", type_="database", tables=tables)


def world(
    cards: list[ArchitectureCardRead],
    links: list[ArchitectureLinkRead] | None = None,
    *,
    sources: tuple[str | ArchitectureSourceRead, ...] = EVERY,
    standings: dict[uuid.UUID, EntityStanding] | None = None,
    documents: int | None = 12,
    teams: int = 2,
    owners: dict[uuid.UUID, tuple[str, ...]] | None = None,
    changes: tuple[ChangeFootprint, ...] | None = None,
) -> Material:
    base = architecture_of(cards, links or [], owners=owners)
    assert base.architecture is not None
    architecture: ArchitectureRead = base.architecture.model_copy(
        update={
            "sources": [s if isinstance(s, ArchitectureSourceRead) else source(s) for s in sources],
            "figures": base.architecture.figures.model_copy(update={"teams": teams}),
        }
    )
    return Material(
        now=NOW,
        built_at=base.built_at,
        architecture=architecture,
        owners=base.owners,
        standing=(standings if standings is not None else {of(c): standing() for c in cards}),
        documents=documents,
        categories=CATEGORIES,
        changes=changes,
    )


def of(card: ArchitectureCardRead) -> uuid.UUID:
    assert card.entity_id is not None
    return card.entity_id


def codes(drafts: list[Draft]) -> list[tuple[str, str]]:
    return sorted((d.code, d.subject.name) for d in drafts)


def signals(draft: Draft) -> list[str]:
    said = draft.params["signals"]
    assert isinstance(said, list)
    return said


def tie(*cards: ArchitectureCardRead) -> list[ArchitectureLinkRead]:
    """Each card relies on the next: all of them tied."""
    return [link(a, b, "depends") for a, b in pairwise(cards)]


# ── priority, as documented ────────────────────────────────────────────────


def test_a_gaps_priority_is_its_base_and_what_makes_the_thing_matter() -> None:
    bare = priority("gap.missing_documentation")
    assert (bare.score, bare.signals, bare.severity) == (0.15, (), Severity.LOW)

    weighed = priority(
        "gap.missing_documentation",
        dependents=2,
        criticality="Critical",
        status="incident",
        production=True,
        changing=True,
    )
    # 0.15 + 2 * 0.06 + 0.2 + 0.1 + 0.1 + 0.15
    assert weighed.score == pytest.approx(0.82)
    assert weighed.signals == ("relied_on", "critical", "unwell", "production", "changing")
    assert weighed.severity is Severity.HIGH


def test_reliance_counts_up_to_its_cap_and_the_score_up_to_one() -> None:
    assert priority("gap.missing_entity.code", dependents=3).score == pytest.approx(0.38)
    assert priority("gap.missing_entity.code", dependents=40).score == pytest.approx(0.5)
    everything = priority(
        "gap.stale_source",
        dependents=40,
        criticality="tier1",
        status="attention",
        production=True,
        changing=True,
        extra=0.4,
    )
    assert everything.score == 1.0


def test_severity_turns_at_the_documented_thresholds() -> None:
    assert priority("gap.stale_source").severity is Severity.MEDIUM  # 0.35
    assert priority("gap.missing_entity.code", dependents=2).severity is Severity.LOW  # 0.32
    assert priority("gap.missing_entity.runtime", extra=0.35).severity is Severity.HIGH  # 0.6


def test_what_only_seems_critical_or_unwell_is_not() -> None:
    plain = priority("gap.missing_documentation", criticality="low", status="operational")
    assert plain.signals == ()


def test_each_coverage_family_weighs_as_coverage() -> None:
    assert priority("gap.coverage.monitoring").score == BASE["gap.coverage"]


# ── missing entities ───────────────────────────────────────────────────────


def test_a_service_without_runtime_or_code_is_a_missing_entity_each() -> None:
    lost = known("payment-api", host=False, code=False)
    fine = known("auth-service")
    drafts = missing_entities(world([lost, fine], tie(lost, fine)))
    assert codes(drafts) == [
        ("gap.missing_entity.code", "payment-api"),
        ("gap.missing_entity.runtime", "payment-api"),
    ]
    # Two gaps of one thing: two findings, told apart by their keys.
    assert len({d.key for d in drafts}) == 2
    assert {d.params["gap"] for d in drafts} == {"entity"}


def test_a_database_whose_tables_are_unknown_is_a_missing_data_model() -> None:
    empty, read = database("postgres-prod"), database("orders-db", tables=42)
    user = known("billing")
    drafts = missing_entities(world([empty, read, user], [link(user, empty), link(user, read)]))
    assert codes(drafts) == [("gap.missing_entity.data_model", "postgres-prod")]


def test_an_application_runs_as_its_services_do() -> None:
    checkout, payment = known("checkout", host=False, code=False), known("payment-api")
    checkout = checkout.model_copy(update={"type": "application"})
    assert missing_entities(world([checkout, payment], [link(payment, checkout, "part_of")])) == []


def test_what_is_tied_to_nothing_is_one_gap_not_five() -> None:
    alone = known("orphan-worker", host=False, code=False)
    a, b = known("payment-api"), known("auth-service")
    standings = {
        of(alone): standing(business=False),
        of(a): standing(business=True),
        of(b): standing(business=True),
    }
    material = world([alone, a, b], tie(a, b), standings=standings)
    assert missing_entities(material) == []
    assert codes(missing_relationships(material)) == [
        ("gap.missing_relationship.isolated", "orphan-worker")
    ]


def test_what_is_dormant_is_asked_one_question() -> None:
    old = known("ledger", host=False, code=False)
    user = known("payment-api")
    standings = {
        of(old): standing(documents=0, fresh=0, business=False, lifecycle=Lifecycle.DORMANT),
        of(user): standing(),
    }
    material = world([old, user], tie(user, old), standings=standings)
    drafts = [d for analyzer in GAPS for d in analyzer.run(material) if isinstance(d, Draft)]
    assert codes(drafts) == [("gap.stale_knowledge.dormant", "ledger")]


def test_without_the_family_that_would_say_it_no_thing_is_blamed() -> None:
    lost = known("payment-api", host=False, code=False)
    empty = database()
    unconnected = world([lost, empty], [link(lost, empty)], sources=("datadog",))
    assert missing_entities(unconnected) == []
    # Said once instead, as coverage — for all it leaves unknown.
    assert codes(coverage(unconnected)) == [
        ("gap.coverage.cloud", "cloud"),
        ("gap.coverage.code", "code"),
        ("gap.coverage.data", "data"),
    ]


def test_a_source_switched_off_does_not_connect_its_family() -> None:
    lost, fine = known("payment-api", host=False), known("auth-service")
    off = world(
        [lost, fine],
        tie(lost, fine),
        sources=("datadog", "github", source("aws", status="disabled")),
    )
    assert missing_entities(off) == []
    assert ("gap.coverage.cloud", "cloud") in codes(coverage(off))


# ── missing relationships ──────────────────────────────────────────────────


def test_what_is_tied_to_nothing_is_isolated() -> None:
    alone, a, b = known("ledger"), known("payment-api"), known("auth-service")
    drafts = missing_relationships(world([alone, a, b], tie(a, b)))
    assert codes(drafts) == [("gap.missing_relationship.isolated", "ledger")]
    assert drafts[0].params["gap"] == "relationship"


def test_a_service_no_business_holds_only_once_the_business_is_known() -> None:
    held, loose = known("payment-api"), known("auth-service")
    links = tie(held, loose)
    standings = {
        of(held): standing(business=True),
        of(loose): standing(business=False),
    }
    drafts = missing_relationships(world([held, loose], links, standings=standings))
    assert codes(drafts) == [("gap.missing_relationship.business", "auth-service")]

    # No capability, application or process known anywhere: nothing to say
    # of one service more than another.
    nowhere = {key: standing(business=False) for key in standings}
    assert missing_relationships(world([held, loose], links, standings=nowhere)) == []


# ── documentation ──────────────────────────────────────────────────────────


def test_what_no_document_describes_and_what_none_current_does() -> None:
    bare, old, fine = known("payment-api"), known("auth-service"), known("user-service")
    standings = {
        of(bare): standing(documents=0, fresh=0),
        of(old): standing(documents=2, fresh=0, last="2026-02-05T16:46:39+00:00"),
        of(fine): standing(documents=3, fresh=1),
    }
    drafts = documentation(world([bare, old, fine], tie(bare, old, fine), standings=standings))
    assert codes(drafts) == [
        ("gap.missing_documentation", "payment-api"),
        ("gap.stale_documentation", "auth-service"),
    ]
    stale = next(d for d in drafts if d.code == "gap.stale_documentation")
    assert stale.statement == (
        "No document describing auth-service is known to be current: the latest changed 2026-02-05."
    )
    assert stale.params["documents"] == 2
    assert {d.params["gap"] for d in drafts} == {"documentation"}


def test_without_any_document_it_is_one_coverage_gap() -> None:
    bare = known("payment-api")
    nothing = world([bare], standings={of(bare): standing(documents=0, fresh=0)}, documents=0)
    assert documentation(nothing) == []
    assert ("gap.coverage.documentation", "documentation") in codes(coverage(nothing))


# ── staleness ──────────────────────────────────────────────────────────────


def test_a_source_late_or_failing_is_stale_one_failing_more_so() -> None:
    sources = (
        *EVERY,
        source("confluence", name="Runbooks", read=timedelta(days=5), entities=0),
        source("jira", name="OPS", status="error", read=timedelta(hours=30), entities=6),
        source("jira", name="Draft", status="draft", read=None),
    )
    drafts = staleness(world([known("payment-api")], sources=sources))
    assert sorted(d.subject.name for d in drafts) == ["OPS", "Runbooks"]
    late = next(d for d in drafts if d.subject.name == "Runbooks")
    failing = next(d for d in drafts if d.subject.name == "OPS")
    assert late.code == failing.code == "gap.stale_source"
    assert late.subject.type == "source" and late.subject.id is not None
    assert late.statement == (
        "Runbooks (confluence) has not been read since 2026-09-30: what it shows may no "
        "longer be so."
    )
    assert failing.statement == (
        "OPS (jira) is failing — last read 2026-10-04: what it says of 6 thing(s) may no "
        "longer be so."
    )
    assert failing.score > late.score
    assert failing.evidence[0].id == str(failing.subject.id)
    assert failing.sources == ("jira",)


def test_a_source_never_read_says_so() -> None:
    never = source("confluence", name="Wiki", status="error", read=None, entities=0)
    (draft,) = staleness(world([known("payment-api")], sources=(*EVERY, never)))
    assert draft.statement == (
        "Wiki (confluence) is failing and has never been read: what it holds cannot be told "
        "current."
    )
    assert draft.params["since"] is None


def test_dormant_knowledge_is_a_gap_only_while_others_rely_on_it() -> None:
    old, user, unused = database("legacy-db", tables=3), known("billing"), database("archive")
    standings = {
        of(old): standing(lifecycle=Lifecycle.DORMANT),
        of(user): standing(),
        of(unused): standing(lifecycle=Lifecycle.DORMANT),
    }
    drafts = staleness(world([old, user, unused], tie(user, old), standings=standings))
    assert codes(drafts) == [("gap.stale_knowledge.dormant", "legacy-db")]
    assert drafts[0].params["dependents"] == 1
    assert "relied_on" in signals(drafts[0])


# ── coverage ───────────────────────────────────────────────────────────────


def test_each_family_not_connected_is_said_once() -> None:
    services = [known(f"service-{i}") for i in range(5)]
    nothing = world(
        [*services, database()],
        tie(*services),
        sources=("jira",),
        documents=0,
        teams=0,
    )
    drafts = coverage(nothing)
    assert [d.code for d in drafts] == [
        "gap.coverage.monitoring",
        "gap.coverage.cloud",
        "gap.coverage.code",
        "gap.coverage.documentation",
        "gap.coverage.data",
        "gap.coverage.organisation",
    ]
    assert [d.key for d in drafts] == [f"gap.coverage:{d.params['family']}" for d in drafts]
    monitoring = drafts[0]
    assert monitoring.subject.type == "coverage" and monitoring.subject.id is None
    assert monitoring.params["count"] == 5
    assert monitoring.evidence[0].detail == "sources connected: jira"
    # What it leaves unknown weighs: 0.3 + 5 * 0.03.
    assert monitoring.score == pytest.approx(0.45)


def test_the_organisation_is_known_once_someone_owns_something() -> None:
    service = known("payment-api")
    owned = world([service], teams=0, owners={of(service): ("nadia-k",)})
    assert "gap.coverage.organisation" not in {d.code for d in coverage(owned)}


def test_a_workspace_with_everything_connected_has_no_coverage_gap() -> None:
    services = [known("payment-api"), known("auth-service")]
    assert coverage(world([*services, database(tables=3)], tie(*services))) == []


# ── what weighs a gap, what shows it ───────────────────────────────────────


def test_a_gap_on_what_matters_ranks_higher() -> None:
    db = database("postgres-prod").model_copy(update={"environment": "production"})
    users = [known(f"service-{i}") for i in range(3)]
    standings = {
        of(db): standing(documents=0, fresh=0, criticality="critical"),
        **{of(u): standing(documents=0, fresh=0) for u in users},
    }
    drafts = documentation(world([db, *users], [link(u, db) for u in users], standings=standings))
    first = max(drafts, key=lambda d: d.rank)
    assert first.subject.name == "postgres-prod"
    assert first.params["signals"] == ["relied_on", "critical", "production"]
    assert first.params["dependents"] == 3
    # 0.15 + 3 * 0.06 + 0.2 + 0.1
    assert first.score == pytest.approx(0.63)
    assert first.severity is Severity.HIGH


def test_a_gap_on_what_a_current_change_touched_is_changing() -> None:
    payment, fine = known("payment-api", code=False), known("auth-service")
    touched = footprint(hours_ago=26)
    entity = touched.touched[0].entity.model_copy(update={"id": of(payment)})
    now = touched.model_copy(
        update={"touched": [touched.touched[0].model_copy(update={"entity": entity})]}
    )
    history = now.model_copy(update={"at": NOW - timedelta(days=10)})

    (changing,) = missing_entities(world([payment, fine], tie(payment, fine), changes=(now,)))
    (quiet,) = missing_entities(world([payment, fine], tie(payment, fine), changes=(history,)))
    assert "changing" in signals(changing)
    assert "changing" not in signals(quiet)
    assert changing.score == pytest.approx(quiet.score + 0.15)


def test_a_thing_gap_keeps_the_thing_and_its_sources() -> None:
    lost, fine = known("payment-api", code=False), known("auth-service")
    (draft,) = missing_entities(world([lost, fine], tie(lost, fine)))
    assert draft.key == f"gap.missing_entity.code:{lost.entity_id}"
    assert draft.subject.type == "entity" and draft.subject.id == lost.entity_id
    assert draft.evidence[0].id == str(lost.entity_id)
    assert (
        draft.evidence[0].detail == "no repository of a connected code host is said to be its code"
    )
    assert draft.sources == ("github",)
    assert draft.params["name"] == "payment-api"


# ── as analyses ────────────────────────────────────────────────────────────


def test_five_gap_analyses_read_the_model_and_heed_the_changes() -> None:
    assert [a.name for a in GAPS] == [
        "gaps_entities",
        "gaps_relationships",
        "gaps_documentation",
        "gaps_staleness",
        "gaps_coverage",
    ]
    assert all(a in ANALYZERS for a in GAPS)
    assert {a.category for a in GAPS} == {"gaps"}
    assert all(a.reads == {Reads.MODEL} and a.wants == {Reads.MODEL, Reads.CHANGES} for a in GAPS)


async def test_a_gap_analysis_runs_without_the_changes() -> None:
    lost, fine = known("payment-api", code=False), known("auth-service")
    outcome = await execute(GAPS[0], world([lost, fine], tie(lost, fine), changes=None))
    assert outcome.status == "succeeded"
    assert [d.code for d in outcome.drafts] == ["gap.missing_entity.code"]


async def test_without_the_model_a_gap_analysis_is_skipped() -> None:
    outcome = await execute(GAPS[4], Material(now=NOW, built_at=None))
    assert (outcome.status, outcome.reason) == ("skipped", "no_material")


def test_every_gap_code_says_its_family() -> None:
    lost = known("payment-api", host=False, code=False)
    loose = known("auth-service")
    alone = known("orphan-worker")
    old = database("legacy-db", tables=3)
    empty = database("postgres-prod")
    standings = {
        of(lost): standing(documents=0, fresh=0, business=True),
        of(loose): standing(documents=1, fresh=0, business=False),
        of(alone): standing(),
        of(old): standing(lifecycle=Lifecycle.DORMANT),
        of(empty): standing(),
    }
    material = world(
        [lost, loose, alone, old, empty],
        [link(lost, old), link(lost, empty), link(lost, loose, "calls")],
        sources=(*EVERY, source("confluence", read=timedelta(days=9))),
        standings=standings,
        teams=0,
    )
    drafts = [d for analyzer in GAPS for d in analyzer.run(material)]
    families = {
        "entity": {
            "gap.missing_entity.runtime",
            "gap.missing_entity.code",
            "gap.missing_entity.data_model",
        },
        "relationship": {"gap.missing_relationship.isolated", "gap.missing_relationship.business"},
        "documentation": {"gap.missing_documentation", "gap.stale_documentation"},
        "staleness": {"gap.stale_source", "gap.stale_knowledge.dormant"},
        "coverage": {"gap.coverage.organisation"},
    }
    found: dict[str, set[str]] = {}
    for draft in drafts:
        found.setdefault(str(draft.params["gap"]), set()).add(draft.code)
    # Every code, each under its own family — none shared.
    assert found == families
    assert len({d.key for d in drafts}) == len(drafts)


def test_modules_and_tools_are_not_what_a_gap_is_about() -> None:
    module = card("payments", type_="module")
    tool = card("terraform", type_="tool")
    assert missing_relationships(world([module, tool])) == []
