"""Data enrichment, the rules (LEKA-359): what resolved entities are to one
another, and what follows from it.

A representative workspace, as entity resolution leaves it — GitHub, Jira,
PagerDuty, AWS and Confluence: a repository and its pull requests, a Jira
project and issue, a PagerDuty service with its team and incidents, a
cloud instance tagged with its service, people and a bot — and what
enrichment adds to it. What these protect:

- a relationship a source states joins the ENTITIES its keys are — across
  tools — and one whose key no entity or several go by joins nothing;
- an inference (a repository and its service, a component, a title, an
  owner inherited, the maintainers, a team) says its rule, its confidence
  and its evidence, and is never made where a source said otherwise;
- what a source states is never overwritten, and an enricher that fails,
  or makes something wrong, costs only what it made.

The job and the API: test_enrichment_job.py.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from leka.ingestion.enrichment import Node, Snapshot, Stated, enrich, view
from leka.ingestion.enrichment.engine import (
    Edge,
    Enrichment,
    Fact,
    Graph,
    Made,
    activity,
    category,
    relationships,
)

GITHUB = uuid.UUID("00000000-0000-0000-0000-00000000000a")
JIRA = uuid.UUID("00000000-0000-0000-0000-00000000000b")
PAGERDUTY = uuid.UUID("00000000-0000-0000-0000-00000000000c")
AWS = uuid.UUID("00000000-0000-0000-0000-00000000000d")
CONFLUENCE = uuid.UUID("00000000-0000-0000-0000-00000000000e")
LINEAR = uuid.UUID("00000000-0000-0000-0000-00000000000f")
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
IDS = uuid.UUID("00000000-0000-0000-0000-000000000359")


def ago(days: float = 0, *, hours: float = 0) -> str:
    return (NOW - timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


class World:
    """A workspace as entity resolution leaves it: its entities, the keys
    each goes by, and what its sources stated between keys."""

    def __init__(self) -> None:
        self.nodes: dict[uuid.UUID, Node] = {}
        self.holders: dict[str, set[uuid.UUID]] = defaultdict(set)
        self.stated: list[Stated] = []

    def thing(
        self,
        key: str,
        name: str,
        *,
        type: str,  # noqa: A002 — the entity's own word
        sources: tuple[uuid.UUID, ...] = (GITHUB,),
        aliases: tuple[str, ...] = (),
        **attributes: Any,
    ) -> uuid.UUID:
        entity_id = uuid.uuid5(IDS, key)
        # Resolution keeps no dates; the job gives them from the records.
        dates = {k: v for k, v in attributes.items() if k.endswith("_at")}
        kept = {k: v for k, v in attributes.items() if k not in dates}
        self.nodes[entity_id] = Node(entity_id, type, key, name, kept, frozenset(sources), dates)
        for held in (key, *aliases):
            self.holders[held].add(entity_id)
        return entity_id

    def states(
        self,
        source: uuid.UUID,
        from_key: str,
        type: str,  # noqa: A002 — the relationship's own word
        to_key: str,
        *,
        confidence: float = 1.0,
        evidence: str = "references",
    ) -> None:
        self.stated.append(
            Stated(type, from_key, to_key, source, uuid.uuid4(), confidence, evidence)
        )

    def snapshot(self) -> Snapshot:
        return Snapshot(nodes=self.nodes, holders=dict(self.holders), stated=self.stated, now=NOW)

    def id(self, key: str) -> uuid.UUID:
        return uuid.uuid5(IDS, key)


REPO = "github.com/acme/billing-api"
SERVICE = "service:billing"
TEAM = "team:payments"
SARA = "person:email:sara@acme.io"
BOB = "person:github.com:bob"
BOT = "person:github.com:dependabot[bot]"
PR41, PR43, PR44, PR45, PR48 = (f"{REPO}#{n}" for n in (41, 43, 44, 45, 48))
PROJECT = "acme.atlassian.net/PAY"
PAY42 = "acme.atlassian.net/PAY-42"
Q1, Q2 = "incident:pagerduty:Q1", "incident:pagerduty:Q2"
INSTANCE = "aws:arn:aws:ec2:eu-central-1:1:instance/i-1"
RUNBOOK = "acme.atlassian.net/wiki/pages/1001"


def acme() -> World:
    """GitHub, Jira, PagerDuty, AWS and Confluence, resolved."""
    w = World()
    w.thing(REPO, "acme/billing-api", type="repository", updated_at=ago(2), created_at=ago(400))
    w.thing(SERVICE, "Billing", type="service", sources=(PAGERDUTY,), updated_at=ago(60))
    w.thing(TEAM, "payments", type="team", sources=(PAGERDUTY,))
    w.thing(
        SARA,
        "Sara Martin",
        type="person",
        sources=(GITHUB, JIRA),
        aliases=("person:github.com:sara",),
    )
    w.thing(BOB, "bob", type="person")
    w.thing(BOT, "dependabot[bot]", type="person")
    w.thing(
        PR41,
        "Fix retry on billing webhook",
        type="pull_request",
        state="merged",
        created_at=ago(3),
        updated_at=ago(2),
        merged_at=ago(2),
    )
    w.thing(PR43, "Add invoice export", type="pull_request", state="open", updated_at=ago(40))
    w.thing(
        PR44,
        "Bump lodash",
        type="pull_request",
        state="merged",
        category="maintenance",
        updated_at=ago(5),
    )
    w.thing(PR45, "Ledger rounding", type="pull_request", state="merged", updated_at=ago(10))
    w.thing(PR48, "Ledger exports", type="pull_request", state="merged", updated_at=ago(12))
    w.thing(PROJECT, "Payments", type="project", sources=(JIRA,), updated_at=ago(1))
    w.thing(
        PAY42,
        "Invoices are sent twice",
        type="issue",
        sources=(JIRA,),
        aliases=("ticket:PAY-42",),
        state="closed",
        components=["Billing"],
        created_at=ago(5),
        updated_at=ago(1),
        resolved_at=ago(1),
    )
    w.thing(
        Q1,
        "Billing API 500s",
        type="incident",
        sources=(PAGERDUTY,),
        state="closed",
        created_at=ago(10),
        resolved_at=ago(10, hours=-1.5),
    )
    w.thing(
        Q2, "Checkout slow", type="incident", sources=(PAGERDUTY,), state="open", created_at=ago(1)
    )
    w.thing(INSTANCE, "billing-api-prod-1", type="infra_resource", sources=(AWS,))
    w.thing(RUNBOOK, "Billing runbook", type="document", sources=(CONFLUENCE,), updated_at=ago(20))

    for pr in (PR41, PR43, PR44, PR45, PR48):
        w.states(GITHUB, pr, "part_of", REPO, evidence="container")
    w.states(GITHUB, PR41, "authored_by", "person:github.com:sara")
    w.states(GITHUB, PR43, "authored_by", "person:github.com:sara")
    w.states(GITHUB, PR44, "authored_by", BOT)
    w.states(GITHUB, PR45, "authored_by", BOB)
    w.states(GITHUB, PR48, "authored_by", BOB)
    w.states(GITHUB, PR41, "resolves", "ticket:PAY-42", confidence=0.9, evidence="parsing")
    w.states(JIRA, PAY42, "part_of", PROJECT, evidence="container")
    w.states(JIRA, PAY42, "assigned_to", SARA)
    w.states(PAGERDUTY, SERVICE, "owned_by", TEAM)
    w.states(PAGERDUTY, Q1, "affects", SERVICE)
    w.states(PAGERDUTY, Q2, "affects", SERVICE)
    w.states(AWS, INSTANCE, "part_of", SERVICE, confidence=0.95, evidence="tags")
    return w


def edge(result: Enrichment, w: World, a: str, kind: str, b: str) -> Edge | None:
    return next(
        (e for e in result.edges if (e.from_id, e.to_id, e.type) == (w.id(a), w.id(b), kind)),
        None,
    )


def fact(result: Enrichment, w: World, key: str, attribute: str) -> Fact | None:
    return next(
        (f for f in result.facts if (f.entity_id, f.attribute) == (w.id(key), attribute)), None
    )


def the[T](found: T | None) -> T:
    assert found is not None
    return found


# ── 1. relationships, stated ─────────────────────────────────────────────────


def test_a_pull_request_resolving_a_jira_issue_joins_two_tools_things() -> None:
    w = acme()
    result = enrich(w.snapshot())

    found = edge(result, w, PR41, "resolves", PAY42)
    assert found is not None
    assert (found.origin, found.rule, found.confidence) == ("stated", "stated", 0.9)
    assert found.cross_source  # a GitHub pull request, a Jira issue
    assert found.sources == {GITHUB}
    assert found.provenance[0]["source_id"] == str(GITHUB)
    assert found.provenance[0]["evidence"] == "parsing"
    uuid.UUID(found.provenance[0]["record_id"])
    assert "parsing" in found.evidence


def test_a_key_is_followed_to_its_entity_whichever_key_it_is() -> None:
    """The pull request names Sara by her login; she is one entity with her
    address — the edge ends at her."""
    w = acme()
    result = enrich(w.snapshot())

    authored = edge(result, w, PR41, "authored_by", SARA)
    assert authored is not None
    assert not authored.cross_source  # Sara is shown by GitHub too


def test_what_no_entity_or_several_entities_go_by_joins_nothing() -> None:
    w = acme()
    w.thing(
        "acme.atlassian.net/ENG-42",
        "Jira's",
        type="issue",
        sources=(JIRA,),
        aliases=("ticket:ENG-42",),
    )
    w.thing(
        "linear.app/acme/ENG-42",
        "Linear's",
        type="issue",
        sources=(LINEAR,),
        aliases=("ticket:ENG-42",),
    )
    w.states(GITHUB, PR43, "mentions", "ticket:ENG-42")
    w.states(GITHUB, PR43, "resolves", "ticket:OPS-9")  # a tool not connected

    result = enrich(w.snapshot())

    assert result.counts["relationships.ambiguous"] == 1
    assert result.counts["relationships.unresolved"] == 1
    assert not [
        e for e in result.edges if e.from_id == w.id(PR43) and e.type in ("mentions", "resolves")
    ]


def test_two_keys_of_one_thing_are_not_a_relationship() -> None:
    w = acme()
    w.states(GITHUB, "person:github.com:sara", "mentions", SARA)

    result = enrich(w.snapshot())

    assert result.counts["relationships.within"] == 1
    assert edge(result, w, SARA, "mentions", SARA) is None


def test_one_relationship_stated_by_several_records_is_one_edge_its_records_kept() -> None:
    w = acme()
    for _ in range(7):
        w.states(GITHUB, PR41, "mentions", PR43, confidence=0.7)
    w.states(GITHUB, PR41, "mentions", PR43, confidence=0.8)

    found = edge(enrich(w.snapshot()), w, PR41, "mentions", PR43)

    assert found is not None
    assert found.confidence == 0.8  # the surest statement
    assert len(found.provenance) == 5  # the first few records, not all


# ── 2. links, inferred ───────────────────────────────────────────────────────


def test_a_repository_is_part_of_the_service_of_its_name() -> None:
    w = acme()
    found = edge(enrich(w.snapshot()), w, REPO, "part_of", SERVICE)

    assert found is not None
    assert (found.origin, found.rule, found.confidence) == ("inferred", "same_name", 0.8)
    assert found.cross_source  # GitHub and PagerDuty
    assert "billing" in found.evidence


def test_a_repository_whose_name_two_services_share_is_linked_to_neither() -> None:
    w = acme()
    w.thing("service:billing-svc", "billing-svc", type="service", sources=(AWS,))

    assert edge(enrich(w.snapshot()), w, REPO, "part_of", SERVICE) is None


def test_a_repository_a_source_already_places_is_not_placed_again() -> None:
    w = acme()
    w.thing("service:ledger", "Ledger", type="service", sources=(PAGERDUTY,))
    w.states(GITHUB, REPO, "part_of", "service:ledger", evidence="mapping.services")

    result = enrich(w.snapshot())

    assert edge(result, w, REPO, "part_of", "service:ledger") is not None
    assert edge(result, w, REPO, "part_of", SERVICE) is None


def test_a_jira_component_names_its_service() -> None:
    w = acme()
    found = edge(enrich(w.snapshot()), w, PAY42, "part_of", SERVICE)

    assert found is not None
    assert (found.rule, found.confidence) == ("component", 0.85)


def test_a_label_names_its_service_less_surely() -> None:
    w = acme()
    w.thing("github.com/acme/web#7", "Totals are wrong", type="issue", labels=["billing", "bug"])

    found = edge(enrich(w.snapshot()), w, "github.com/acme/web#7", "part_of", SERVICE)

    assert found is not None
    assert (found.rule, found.confidence) == ("label", 0.7)


def test_a_service_named_in_a_title_is_mentioned_not_owned() -> None:
    w = acme()
    result = enrich(w.snapshot())

    runbook = edge(result, w, RUNBOOK, "mentions", SERVICE)
    assert runbook is not None
    assert (runbook.rule, runbook.confidence) == ("named_in_title", 0.6)
    # An incident a source says affects the service is not "mentioned" too.
    assert edge(result, w, Q1, "mentions", SERVICE) is None


def test_a_service_name_in_too_many_titles_is_a_word_not_a_service() -> None:
    w = acme()
    for n in range(25):
        w.thing(f"github.com/acme/web#{100 + n}", f"Billing page {n}", type="issue")

    result = enrich(w.snapshot())

    assert result.counts["links.too_common"] == 1
    assert edge(result, w, RUNBOOK, "mentions", SERVICE) is None


def test_a_word_inside_another_is_no_mention() -> None:
    w = acme()
    w.thing("github.com/acme/web#8", "Rebillings are slow", type="issue")

    assert edge(enrich(w.snapshot()), w, "github.com/acme/web#8", "mentions", SERVICE) is None


# ── 3. ownership ─────────────────────────────────────────────────────────────


def test_a_team_is_inherited_from_the_container_a_little_less_sure_each_step() -> None:
    w = acme()
    result = enrich(w.snapshot())

    repository = edge(result, w, REPO, "owned_by", TEAM)
    assert repository is not None
    assert (repository.origin, repository.rule) == ("inferred", "inherited")
    assert repository.confidence == pytest.approx(0.8 * 0.9, abs=0.01)
    assert repository.provenance == [{"entity_id": str(w.id(SERVICE))}]
    # A pull request: its repository, then the service — two steps.
    pull_request = edge(result, w, PR41, "owned_by", TEAM)
    assert pull_request is not None
    assert pull_request.confidence == pytest.approx(0.8 * 0.9**2, abs=0.01)
    instance = edge(result, w, INSTANCE, "owned_by", TEAM)
    assert instance is not None
    assert instance.confidence == pytest.approx(0.95 * 0.9, abs=0.01)


def test_an_owner_a_source_states_is_never_replaced() -> None:
    w = acme()
    w.thing("team:platform", "platform", type="team", sources=(AWS,))
    w.states(AWS, INSTANCE, "owned_by", "team:platform", confidence=0.95, evidence="tags")

    result = enrich(w.snapshot())

    assert the(edge(result, w, INSTANCE, "owned_by", "team:platform")).origin == "stated"
    assert edge(result, w, INSTANCE, "owned_by", TEAM) is None
    assert the(edge(result, w, SERVICE, "owned_by", TEAM)).origin == "stated"


def test_two_teams_equally_near_are_neither_team() -> None:
    w = acme()
    w.thing("service:ledger", "Ledger", type="service", sources=(PAGERDUTY,))
    w.thing("team:finance", "finance", type="team", sources=(PAGERDUTY,))
    w.states(PAGERDUTY, "service:ledger", "owned_by", "team:finance")
    w.thing("aws:arn:aws:s3:::shared", "shared", type="infra_resource", sources=(AWS,))
    w.states(AWS, "aws:arn:aws:s3:::shared", "part_of", SERVICE)
    w.states(AWS, "aws:arn:aws:s3:::shared", "part_of", "service:ledger")

    result = enrich(w.snapshot())

    assert result.counts["ownership.tied"] >= 1
    assert not [
        e
        for e in result.edges
        if e.from_id == w.id("aws:arn:aws:s3:::shared") and e.type == "owned_by"
    ]


def test_maintainers_are_the_most_active_never_a_bot() -> None:
    w = acme()
    result = enrich(w.snapshot())

    sara = edge(result, w, REPO, "maintained_by", SARA)
    bob = edge(result, w, REPO, "maintained_by", BOB)
    assert sara is not None
    assert bob is not None
    # Two pull requests each: half the work each.
    assert sara.confidence == bob.confidence == pytest.approx(0.4 + 0.6 * 0.5)
    assert "50 %" in sara.evidence
    assert {p["entity_id"] for p in sara.provenance} == {str(w.id(PR41)), str(w.id(PR43))}
    assert edge(result, w, REPO, "maintained_by", BOT) is None


def test_one_item_is_not_enough_to_maintain_anything() -> None:
    w = acme()
    result = enrich(w.snapshot())

    # Sara's one Jira issue in the project.
    assert edge(result, w, PROJECT, "maintained_by", SARA) is None


# ── 4. membership ────────────────────────────────────────────────────────────


def test_a_person_works_with_the_team_most_of_their_work_belongs_to() -> None:
    w = acme()
    result = enrich(w.snapshot())

    sara = edge(result, w, SARA, "member_of", TEAM)
    assert sara is not None
    assert (sara.origin, sara.rule) == ("inferred", "works_with")
    assert sara.confidence == pytest.approx(0.85)  # all three of her items
    assert edge(result, w, BOT, "member_of", TEAM) is None


def test_a_person_split_between_teams_is_in_neither() -> None:
    w = acme()
    w.thing("team:finance", "finance", type="team", sources=(PAGERDUTY,))
    for n in range(3):
        key = f"github.com/acme/ledger#{n}"
        w.thing(key, f"Ledger change {n}", type="pull_request")
        w.states(GITHUB, key, "owned_by", "team:finance", evidence="mapping.owners")
        w.states(GITHUB, key, "authored_by", "person:github.com:sara")

    assert edge(enrich(w.snapshot()), w, SARA, "member_of", TEAM) is None


# ── 5. activity ──────────────────────────────────────────────────────────────


def test_how_alive_a_repository_and_a_person_are() -> None:
    w = acme()
    result = enrich(w.snapshot())

    assert the(fact(result, w, REPO, "last_activity_at")).value == ago(2)
    assert the(fact(result, w, REPO, "activity_90d")).value == 5
    assert the(fact(result, w, REPO, "lifecycle")).value == "active"
    assert the(fact(result, w, SARA, "last_activity_at")).value == ago(1)
    assert isinstance(team := the(fact(result, w, TEAM, "activity_90d")).value, int)
    assert team >= 1


def test_a_container_nobody_touched_for_months_is_dormant_an_archived_one_is_not_measured() -> None:
    w = acme()
    w.thing("github.com/acme/old", "acme/old", type="repository", updated_at=ago(400))
    w.thing(
        "github.com/acme/gone",
        "acme/gone",
        type="repository",
        state="archived",
        updated_at=ago(400),
    )

    result = enrich(w.snapshot())

    assert the(fact(result, w, "github.com/acme/old", "lifecycle")).value == "dormant"
    assert fact(result, w, "github.com/acme/gone", "lifecycle") is None


def test_how_long_work_took_and_what_is_left_open() -> None:
    w = acme()
    result = enrich(w.snapshot())

    assert the(fact(result, w, PR41, "cycle_time_hours")).value == 24.0
    assert the(fact(result, w, PAY42, "cycle_time_hours")).value == 96.0
    stale = fact(result, w, PR43, "stale")
    assert stale is not None
    assert (stale.value, stale.confidence) == (True, 0.8)
    assert "40 days" in stale.evidence


def test_a_service_s_incidents_and_their_time_to_resolve() -> None:
    w = acme()
    result = enrich(w.snapshot())

    assert the(fact(result, w, Q1, "duration_minutes")).value == 90
    assert the(fact(result, w, SERVICE, "incidents_90d")).value == 2
    assert the(fact(result, w, SERVICE, "open_incidents")).value == 1
    assert the(fact(result, w, SERVICE, "mttr_minutes")).value == 90


def test_a_date_in_the_future_or_unreadable_is_not_activity() -> None:
    w = World()
    w.thing(REPO, "acme/billing-api", type="repository", updated_at="someday")
    w.thing(PR41, "Something", type="pull_request", updated_at=ago(-30))
    w.states(GITHUB, PR41, "part_of", REPO)

    result = enrich(w.snapshot())

    assert fact(result, w, REPO, "last_activity_at") is None
    assert the(fact(result, w, REPO, "activity_90d")).value == 0


# ── 6. category ──────────────────────────────────────────────────────────────


def test_the_kind_of_work_a_title_says_where_parsing_said_none() -> None:
    w = acme()
    w.thing(f"{REPO}@abc123", "Corrige le plantage au démarrage", type="commit")
    w.thing(f"{REPO}#60", "Fix typo in docs", type="pull_request")
    result = enrich(w.snapshot())

    assert the(fact(result, w, PR41, "category")).value == "bug"
    assert the(fact(result, w, PR43, "category")).value == "feature"
    french = fact(result, w, f"{REPO}@abc123", "category")
    assert french is not None
    assert (french.value, french.confidence, french.rule) == ("bug", 0.6, "title_words")
    assert fact(result, w, PR44, "category") is None  # parsing's stands
    assert fact(result, w, f"{REPO}#60", "category") is None  # a bug or docs: a tie


# ── what is added, never overwritten; what fails, costs only itself ─────────


def test_an_attribute_a_source_states_is_never_enriched() -> None:
    w = acme()
    w.thing(
        "github.com/acme/kept",
        "acme/kept",
        type="repository",
        lifecycle="sunset",
        updated_at=ago(1),
    )

    result = enrich(w.snapshot())

    assert fact(result, w, "github.com/acme/kept", "lifecycle") is None
    assert result.counts["rejected"] >= 1


def test_a_stated_edge_is_never_replaced_an_inferred_one_by_a_surer_one() -> None:
    w = acme()
    graph = Graph(w.snapshot())
    a, b = w.id(PR41), w.id(SERVICE)
    stated = Edge(a, b, "mentions", "stated", "stated", 0.5, "")
    assert graph.add(stated)
    assert not graph.add(Edge(a, b, "mentions", "inferred", "named_in_title", 0.9, ""))
    assert graph.edges[(a, b, "mentions")] is stated

    c = w.id(PR43)
    assert graph.add(Edge(c, b, "mentions", "inferred", "x", 0.6, ""))
    assert graph.add(Edge(c, b, "mentions", "inferred", "y", 0.8, ""))
    assert graph.edges[(c, b, "mentions")].rule == "y"
    assert len(graph.out(c, {"mentions"})) == 1


def test_an_enricher_that_fails_costs_only_its_own_output() -> None:
    w = acme()

    def broken(graph: Graph) -> Made:
        half = Made(facts=[Fact(w.id(REPO), "half_made", 1, 1.0, "broken", "")])
        if graph.nodes:
            raise ZeroDivisionError("half-way through")
        return half

    result = enrich(
        w.snapshot(),
        [
            ("relationships", relationships),
            ("broken", broken),
            ("activity", activity),
            ("category", category),
        ],
    )

    assert result.failures == [{"enricher": "broken", "error": "ZeroDivisionError"}]
    assert result.counts["failed"] == 1
    assert edge(result, w, PR41, "resolves", PAY42) is not None
    assert fact(result, w, REPO, "half_made") is None
    assert fact(result, w, PR41, "cycle_time_hours") is not None
    assert fact(result, w, PR41, "category") is not None


def test_what_an_enricher_makes_is_checked_before_it_is_kept() -> None:
    w = acme()
    repo, pr = w.id(REPO), w.id(PR41)

    def careless(graph: Graph) -> Made:
        return Made(
            edges=[
                Edge(repo, uuid.uuid4(), "part_of", "inferred", "x", 0.9, ""),  # no such entity
                Edge(repo, repo, "part_of", "inferred", "x", 0.9, ""),  # to itself
                Edge(repo, pr, "part_of", "inferred", "x", 1.5, ""),  # a confidence above 1
                Edge(repo, pr, "Part Of", "inferred", "x", 0.9, ""),  # not a type
                Edge(pr, repo, "depends_on", "inferred", "kept", 0.9, ""),
            ],
            facts=[
                Fact(repo, "score", math.nan, 1.0, "x", ""),  # not JSON
                Fact(repo, "score", None, 1.0, "x", ""),  # nothing
                Fact(repo, "score", {1, 2}, 1.0, "x", ""),  # not JSON either
                Fact(repo, "updated_at", "2026-01-01", 1.0, "x", ""),  # stated by its source
                Fact(repo, "Bad Name", 1, 1.0, "x", ""),  # not an attribute name
                Fact(repo, "score", 3, float("inf"), "x", ""),  # no confidence
                Fact(repo, "score", 3, 0.7, "kept", ""),
            ],
        )

    result = enrich(w.snapshot(), [("careless", careless)])

    assert result.counts["rejected"] == 10
    assert [(e.rule, e.type) for e in result.edges] == [("kept", "depends_on")]
    assert [(f.attribute, f.value) for f in result.facts] == [("score", 3)]


def test_the_same_workspace_is_enriched_the_same_way() -> None:
    def signature(result: Enrichment) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
        return (
            sorted((e.from_id, e.to_id, e.type, e.rule, e.confidence) for e in result.edges),
            sorted((f.entity_id, f.attribute, str(f.value)) for f in result.facts),
        )

    assert signature(enrich(acme().snapshot())) == signature(enrich(acme().snapshot()))


def test_the_counts_say_what_was_added() -> None:
    w = acme()
    result = enrich(w.snapshot())

    assert result.counts["relationships"] == len(result.edges)
    assert result.counts["stated"] + result.counts["inferred"] == len(result.edges)
    assert result.counts["cross_source"] == sum(1 for e in result.edges if e.cross_source)
    assert result.counts["attributes"] == len(result.facts)
    assert result.counts["failed"] == 0
    assert result.failures == []


# ── the environment screens' states (mockup 10's legend) ─────────────────────


def _thing(type_: str, key: str = "k", **attributes: Any) -> view.Thing:
    facts = attributes.pop("facts", {})
    kinds = attributes.pop("kinds", frozenset())
    return view.Thing(uuid.uuid4(), type_, key, key, attributes, facts, kinds)


WATCHED = frozenset({"pagerduty", "datadog", "grafana"})


@pytest.mark.parametrize(
    ("thing", "hit", "expected"),
    [
        (
            _thing("service", facts={"open_incidents": 2}, kinds=frozenset({"pagerduty"})),
            False,
            "incident",
        ),
        (_thing("service", kinds=frozenset({"pagerduty"})), True, "attention"),
        (_thing("service", kinds=frozenset({"datadog", "github"})), False, "operational"),
        (_thing("service", kinds=frozenset({"github"})), False, "unmonitored"),
        (_thing("infra_resource", state="running"), False, "operational"),
        (_thing("database", state="stopped"), False, "attention"),
        (_thing("infra_resource", state="failed"), False, "incident"),
        (_thing("infra_resource"), False, None),
        (_thing("incident", state="in_progress"), False, "incident"),
        (_thing("incident", state="closed"), False, "operational"),
        (_thing("repository"), False, None),
    ],
)
def test_each_thing_s_state_says_where_it_comes_from(
    thing: view.Thing, hit: bool, expected: str | None
) -> None:
    assert view.status(thing, monitoring=WATCHED, recently_hit=hit) == expected


def test_cloud_resources_are_boxed_by_provider_and_region_in_their_worst_state() -> None:
    service = _thing("service", "service:billing")
    one = _thing("infra_resource", "aws:arn:aws:ec2:eu-west-1:1:instance/i-1", state="running")
    two = _thing("infra_resource", "aws:arn:aws:rds:eu-west-1:1:db:x", state="failed")
    blob = _thing("infra_resource", "azure:/subscriptions/s/b", region="westeurope")
    links = [view.Link(one.id, service.id, "part_of"), view.Link(two.id, service.id, "part_of")]
    statuses = {one.id: "operational", two.id: "incident", blob.id: None, service.id: None}

    nodes, edges, layers = view.layout([service, one, two, blob], links, statuses)

    boxes = {n.id: n for n in nodes if n.type == "provider"}
    aws = boxes["provider:aws:eu-west-1"]
    assert (aws.count, aws.status, aws.detail) == (2, "incident", "eu-west-1")
    assert boxes["provider:azure:westeurope"].count == 1
    assert [(e.from_id, e.to_id, e.status) for e in edges] == [
        ("provider:aws:eu-west-1", str(service.id), "incident")
    ]
    assert layers == {"services": 1, "infrastructure": 3}
    assert view.provider_of(_thing("infra_resource", "gcp:projects/p/zones/z/instances/i")) == (
        "gcp",
        None,
    )


def test_what_moved_shows_as_what_it_is_now() -> None:
    assert view.event_kind(_thing("incident", state="open")) == "incident"
    assert view.event_kind(_thing("incident", state="closed")) == "resolved"
    assert view.event_kind(_thing("issue", facts={"stale": True})) == "attention"
    assert view.event_kind(_thing("pull_request")) == "change"
    assert view.event_kind(_thing("document")) == "information"
