"""Knowledge enrichment (LEKA-380), the proposals, pure.

The architecture, its owners, its maintainers' teams and what the model
holds around each thing, in; proposals out — no database.

What these protect: a name says what it is without what kind of thing it
is — payment-api, acme/payments and payments-service are one; a service
whose code is unknown gets the repository of its name, one whose runtime
is unknown the resource of its name — only where that family is
connected, and only when one answer stands out; a thing no one owns gets
the team owning its repository — sure enough for the policy — or the team
most of its maintainers are in, by how many; a service no application
holds gets the application its neighbours are part of, or whose name it
carries; how critical a thing is comes from the application holding it or
from what relies on it — proposed where nothing is said, above what is,
replacing a source's word only as an override; a service gets its
repository's description when that repository is its alone; nothing is
proposed of what a thing already has; the model-assisted analysis is
skipped without a model — given one (LEKA-394), it describes what lacks a
description from what LEKA knows of it, each description citing its facts,
never twice, never what was decided; the policy takes only what is sure,
rules-made and adds.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from leka.intelligence import ANALYZERS, Material, Method, Proposal, Subject, execute
from leka.intelligence.analysis import ModelWork
from leka.intelligence.curation import by_policy
from leka.intelligence.enrichment import (
    ANALYZERS as ENRICHMENT,
)
from leka.intelligence.enrichment import (
    enrich_application,
    enrich_code,
    enrich_criticality,
    enrich_description,
    enrich_owner,
    enrich_runtime,
    enrich_summary,
    likeness,
    summary_key,
    words,
)
from leka.knowledge import ArchitectureCardRead, EntityBrief, EntityStanding, EntityType, Lifecycle
from tests.test_intelligence_gaps import EVERY, database, known, of, tie, world
from tests.test_intelligence_rules import NS, card, link


def repository(name: str, *, description: str | None = None) -> ArchitectureCardRead:
    return card(name, column="code", type_="repository", kind="repository").model_copy(
        update={"description": description}
    )


def resource(name: str) -> ArchitectureCardRead:
    return card(name, column="cloud", type_="infra_resource", kind="cluster")


def application(name: str) -> ArchitectureCardRead:
    return card(name, type_="application", kind="application")


def team(name: str) -> EntityBrief:
    return EntityBrief(
        id=uuid.uuid5(NS, f"team:{name}"),
        type=EntityType.TEAM,
        key=f"team:{name}",
        name=name,
        lifecycle=Lifecycle.ACTIVE,
    )


def held(
    *,
    criticality: str | None = None,
    stated: tuple[str, ...] = (),
    business: bool = False,
) -> EntityStanding:
    return EntityStanding(
        criticality=criticality,
        stated=stated,
        lifecycle=Lifecycle.ACTIVE,
        documents=1,
        fresh_documents=1,
        last_documented_at=None,
        business=business,
    )


def with_(material: Material, **parts: object) -> Material:
    return dataclasses.replace(material, **parts)  # type: ignore[arg-type]


def other(proposal: Proposal) -> object:
    """A relationship's other end than the thing it enriches; an
    attribute's value."""
    if proposal.start is None or proposal.end is None:
        return proposal.value
    return proposal.start.name if proposal.end.id == proposal.subject.id else proposal.end.name


def said(proposals: list[Proposal]) -> list[tuple[str, str, str | None, object]]:
    """(code, subject, relationship or attribute, the other end or value)."""
    return sorted(
        (p.code, p.subject.name, p.relationship or p.attribute, other(p)) for p in proposals
    )


# ── names ──────────────────────────────────────────────────────────────────


def test_a_name_says_what_it_is_not_what_kind_of_thing() -> None:
    assert words("payment-api") == words("acme/payments") == words("payments-service")
    assert words("payment-api") == frozenset({"payment"})
    assert words("ecs-prod-cluster") == frozenset({"ecs", "cluster"})
    assert likeness("payment-api", "acme/payments") == "same"
    assert likeness("payment-api", "payment-gateway") == "near"
    assert likeness("payment-api", "acme/backend") is None
    # A name that says nothing but its kind matches nothing.
    assert likeness("api", "acme/api") is None


# ── relationships ──────────────────────────────────────────────────────────


def test_a_service_whose_code_is_unknown_gets_the_repository_of_its_name() -> None:
    payment = known("payment-api", code=False)
    auth = known("auth-service")
    repos = [repository("acme/payments"), repository("acme/backend")]
    (proposal,) = enrich_code(world([payment, auth, *repos], tie(payment, auth)))

    # The repository is part of the service: from it, to the service.
    assert proposal.relationship == "part_of"
    assert proposal.start is not None and proposal.start.name == "acme/payments"
    assert proposal.end == proposal.subject
    assert proposal.subject.id == of(payment)
    assert (proposal.family, proposal.confidence, proposal.kind) == (
        "relationship",
        0.8,
        "relationship",
    )
    assert proposal.evidence[0].name == "acme/payments"
    assert proposal.key == f"enrichment.code:{of(repos[0])}:part_of:{of(payment)}"


def test_two_repositories_named_alike_say_nothing() -> None:
    payment = known("payment-api", code=False)
    repos = [repository("acme/payments"), repository("legacy/payment")]
    assert enrich_code(world([payment, *repos])) == []


def test_without_a_code_host_no_repository_is_proposed() -> None:
    payment = known("payment-api", code=False)
    assert enrich_code(world([payment, repository("acme/payments")], sources=("aws",))) == []


def test_a_service_whose_runtime_is_unknown_gets_the_resource_of_its_name() -> None:
    payment = known("payment-api", host=False)
    cloud = [resource("payment-api-prod"), resource("ecs-prod-cluster")]
    (proposal,) = enrich_runtime(world([payment, *cloud]))

    assert proposal.relationship == "deployed_to"
    assert proposal.start is not None and proposal.start.id == of(payment)
    assert proposal.end is not None and proposal.end.name == "payment-api-prod"
    assert proposal.confidence == 0.75
    # Already known to run somewhere: nothing.
    assert enrich_runtime(world([known("payment-api"), *cloud])) == []


# ── organisation ───────────────────────────────────────────────────────────


def test_a_thing_no_one_owns_gets_the_team_owning_its_repository() -> None:
    code = repository("acme/payments")
    payment = known("payment-api").model_copy(update={"repository_id": code.id})
    payments = team("Payments")
    material = with_(world([payment, code]), owned_by={of(code): (payments,)})
    (proposal,) = enrich_owner(material)

    assert (proposal.code, proposal.family, proposal.relationship) == (
        "enrichment.owner",
        "organisation",
        "owned_by",
    )
    assert proposal.end is not None and proposal.end.id == payments.id
    assert proposal.confidence == 0.9
    assert proposal.params["how"] == "repository"
    # Owned already: nothing to propose.
    owned = with_(material, owned_by={of(code): (payments,), of(payment): (team("Core"),)})
    assert enrich_owner(owned) == []


def test_or_the_team_most_of_its_maintainers_are_members_of() -> None:
    payment = card("payment-api", maintainers=("nadia", "thomas", "mei"))
    ids = {m.name: m.id for m in payment.maintainers}
    payments, platform = team("Payments"), team("Platform")
    material = with_(
        world([payment]),
        memberships={
            ids["nadia"]: (payments,),
            ids["thomas"]: (payments,),
            ids["mei"]: (platform,),
        },
    )
    (proposal,) = enrich_owner(material)

    assert proposal.end is not None and proposal.end.name == "Payments"
    assert proposal.params["members"] == 2
    # Two of three: 0.5 + 0.35 x 2/3.
    assert proposal.confidence == 0.73
    assert {e.name for e in proposal.evidence} == {"nadia", "thomas"}
    assert not by_policy(ENRICHMENT[2], proposal)


def test_maintainers_split_between_teams_say_nothing() -> None:
    payment = card("payment-api", maintainers=("nadia", "mei"))
    ids = {m.name: m.id for m in payment.maintainers}
    material = with_(
        world([payment]),
        memberships={ids["nadia"]: (team("Payments"),), ids["mei"]: (team("Platform"),)},
    )
    assert enrich_owner(material) == []


# ── business ───────────────────────────────────────────────────────────────


def test_a_service_no_application_holds_gets_the_one_its_neighbours_are_part_of() -> None:
    checkout = application("checkout")
    cart, pay, orders = known("cart"), known("payment-api"), known("order-service")
    links = [link(cart, checkout, "part_of"), link(pay, checkout, "part_of")]
    links += [link(orders, cart, "calls"), link(orders, pay, "depends")]
    cards = [checkout, cart, pay, orders]
    material = world(cards, links, standings={of(c): held() for c in cards})
    (proposal,) = enrich_application(material)

    assert (proposal.subject.name, proposal.relationship) == ("order-service", "part_of")
    assert proposal.end is not None and proposal.end.name == "checkout"
    assert proposal.family == "business"
    assert proposal.params["neighbours"] == ["cart", "payment-api"]
    assert proposal.confidence == 0.8


def test_or_the_one_whose_name_it_carries() -> None:
    checkout = application("checkout")
    worker = known("checkout-worker")
    loose = {of(worker): held(), of(checkout): held()}
    (proposal,) = enrich_application(world([checkout, worker], standings=loose))
    assert (proposal.params["how"], proposal.confidence) == ("name", 0.7)
    # One the business already holds is not asked.
    standing = {of(worker): held(business=True), of(checkout): held()}
    assert enrich_application(world([checkout, worker], standings=standing)) == []


# ── semantic ───────────────────────────────────────────────────────────────


def test_a_service_held_by_a_critical_application_is_proposed_critical() -> None:
    checkout = application("checkout")
    pay = known("payment-api")
    links = [link(pay, checkout, "part_of")]
    standings = {of(checkout): held(criticality="critical"), of(pay): held()}
    (proposal,) = enrich_criticality(world([checkout, pay], links, standings=standings))

    assert (proposal.attribute, proposal.value, proposal.current) == (
        "criticality",
        "critical",
        None,
    )
    assert (proposal.kind, proposal.family, proposal.overrides) == ("attribute", "semantic", False)
    assert proposal.confidence == 0.75
    assert proposal.evidence[0].name == "checkout"


def test_above_what_a_source_says_it_is_an_override() -> None:
    checkout = application("checkout")
    pay, auth = known("payment-api"), known("auth-service")
    links = [link(pay, checkout, "part_of"), link(auth, checkout, "part_of")]
    standings = {
        of(checkout): held(criticality="high"),
        # Its catalogue says low; enrichment guessed auth-service medium.
        of(pay): held(criticality="low", stated=("criticality",)),
        of(auth): held(criticality="medium"),
    }
    proposals = enrich_criticality(world([checkout, pay, auth], links, standings=standings))
    by = {p.subject.name: p for p in proposals}

    assert (by["payment-api"].current, by["payment-api"].overrides) == ("low", True)
    assert (by["auth-service"].current, by["auth-service"].overrides) == ("medium", False)
    assert "not low" in by["payment-api"].statement
    # An override is never the policy's.
    assert not by_policy(ENRICHMENT[4], dataclasses.replace(by["payment-api"], confidence=1.0))


def test_what_many_rely_on_is_proposed_high_and_nothing_below_what_is_said() -> None:
    core = database("postgres-prod")
    users = [known(f"service-{i}") for i in range(5)]
    (proposal,) = enrich_criticality(world([core, *users], [link(u, core) for u in users]))
    assert (proposal.subject.name, proposal.value, proposal.confidence) == (
        "postgres-prod",
        "high",
        0.65,
    )
    said_critical = {of(core): held(criticality="critical"), **{of(u): held() for u in users}}
    assert (
        enrich_criticality(
            world([core, *users], [link(u, core) for u in users], standings=said_critical)
        )
        == []
    )


def test_a_service_gets_its_repository_s_description_when_it_is_its_alone() -> None:
    code = repository("acme/payments", description="Card payments and refunds")
    pay = known("payment-api").model_copy(update={"repository_id": code.id})
    (proposal,) = enrich_description(world([pay, code]))
    assert (proposal.attribute, proposal.value) == ("description", "Card payments and refunds")

    # A repository holding two services says what they are together.
    auth = known("auth-service").model_copy(update={"repository_id": code.id})
    assert enrich_description(world([pay, auth, code])) == []
    # Described already: nothing.
    described = pay.model_copy(update={"description": "Payments"})
    assert enrich_description(world([described, code])) == []


# ── as analyses ────────────────────────────────────────────────────────────


def test_the_enrichment_analyses_propose_and_one_waits_for_a_model() -> None:
    assert [a.name for a in ENRICHMENT] == [
        "enrich_code",
        "enrich_runtime",
        "enrich_owner",
        "enrich_application",
        "enrich_criticality",
        "enrich_description",
        "enrich_summary",
    ]
    assert all(a in ANALYZERS for a in ENRICHMENT)
    assert {a.category for a in ENRICHMENT} == {"enrichment"}
    assert [a.name for a in ENRICHMENT if a.method is Method.MODEL] == ["enrich_summary"]


async def test_an_analysis_s_proposals_are_proposals_not_findings() -> None:
    payment = known("payment-api", code=False)
    outcome = await execute(ENRICHMENT[0], world([payment, repository("acme/payments")]))
    assert outcome.status == "succeeded"
    assert outcome.drafts == ()
    assert [p.code for p in outcome.proposals] == ["enrichment.code"]

    skipped = await execute(ENRICHMENT[-1], world([payment]))
    assert (skipped.status, skipped.reason) == ("skipped", "no_model")


def test_the_policy_takes_only_what_is_sure_rules_made_and_adds() -> None:
    code = repository("acme/payments")
    payment = known("payment-api").model_copy(update={"repository_id": code.id})
    material = with_(world([payment, code]), owned_by={of(code): (team("Payments"),)})
    (sure,) = enrich_owner(material)
    owner = ENRICHMENT[2]

    assert by_policy(owner, sure)
    assert not by_policy(owner, dataclasses.replace(sure, confidence=0.89))
    assert not by_policy(owner, dataclasses.replace(sure, overrides=True))
    assert not by_policy(ENRICHMENT[-1], sure)


def test_every_proposal_keeps_what_shows_it_and_where_it_was_read() -> None:
    payment = known("payment-api", code=False, host=False)
    cards = [payment, repository("acme/payments"), resource("payment-api-prod")]
    proposals = [
        p
        for a in ENRICHMENT[:2]
        for p in a.run(world(cards, sources=EVERY))
        if isinstance(p, Proposal)
    ]
    assert said(proposals) == [
        ("enrichment.code", "payment-api", "part_of", "acme/payments"),
        ("enrichment.runtime", "payment-api", "deployed_to", "payment-api-prod"),
    ]
    for proposal in proposals:
        assert proposal.evidence and proposal.sources == ("github",)
        assert 0 < proposal.confidence <= 1


# ── written by a model (LEKA-394) ──────────────────────────────────────────


class Scripted:
    """A model that answers what it is told to, and keeps what it was asked."""

    def __init__(self, answer: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.answer = answer
        self.asked: list[dict[str, Any]] = []

    async def __call__(self, request: Any, shape: Any, needs: Any) -> Any:
        said = json.loads(request.messages[-1].content)
        self.asked.append(said)
        return SimpleNamespace(
            value=shape.model_validate(self.answer(said)),
            completion=SimpleNamespace(model="gemini-3.8-flash"),
        )


def first_fact(said: dict[str, Any]) -> dict[str, Any]:
    return {
        "things": [
            {
                "id": t["id"],
                "description": f"{t['name']} handles card payments.",
                "confidence": 0.9,
                "uses": [t["facts"][0]["id"], "invented"],
            }
            for t in said["things"]
        ]
    }


async def test_a_model_describes_from_what_leka_knows_each_sentence_citing_it() -> None:
    code = repository("acme/payments", description="Card payments and refunds")
    pay = known("payment-api").model_copy(
        update={"repository_id": code.id, "technology": ["python", "fastapi"]}
    )
    auth = known("auth-service").model_copy(update={"description": "Signs people in"})
    model = Scripted(first_fact)
    proposals = await enrich_summary(world([pay, auth, code], tie(pay, auth)), ModelWork(ask=model))

    # Only what lacks a description is asked of — once, with its facts.
    [asked] = model.asked
    assert [t["name"] for t in asked["things"]] == ["payment-api"]
    facts = [f["text"] for f in asked["things"][0]["facts"]]
    assert "Technology: python, fastapi" in facts
    assert (
        "Its code is the repository acme/payments, described as: Card payments and refunds" in facts
    )
    assert any(fact.startswith("It depends auth-service") for fact in facts)

    (proposal,) = proposals
    assert (proposal.code, proposal.attribute, proposal.value) == (
        "enrichment.summary",
        "description",
        "payment-api handles card payments.",
    )
    assert proposal.key == summary_key(pay)
    # Capped: never what the policy takes.
    assert proposal.confidence == 0.6
    assert not by_policy(next(a for a in ENRICHMENT if a.name == "enrich_summary"), proposal)
    # What it cited that LEKA never gave it: not evidence.
    assert [e.id for e in proposal.evidence] == [f"{pay.id}:what"]


async def test_what_was_proposed_or_decided_is_never_asked_again() -> None:
    pay = known("payment-api")
    cart = known("cart")
    kept = Proposal(
        key=summary_key(pay),
        family="semantic",
        code="enrichment.summary",
        subject=Subject(type="entity", id=of(pay), name="payment-api"),
        statement="kept",
        confidence=0.6,
        attribute="description",
        value="Kept as it was.",
    )
    model = Scripted(first_fact)
    work = ModelWork(ask=model, kept={kept.key: kept}, decided=frozenset({summary_key(cart)}))
    assert await enrich_summary(world([pay, cart]), work) == [kept]
    assert model.asked == []

    # A description resting on nothing LEKA gave: not proposed.
    vague = Scripted(
        lambda said: {
            "things": [
                {"id": t["id"], "description": "Something.", "confidence": 0.9, "uses": ["x"]}
                for t in said["things"]
            ]
        }
    )
    assert await enrich_summary(world([pay]), ModelWork(ask=vague)) == []
