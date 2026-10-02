"""What enrichment adds to documentation and business knowledge (LEKA-366).

A workspace as resolution leaves it: the Confluence space Payments, its
pages — a runbook changed last week, an architecture page untouched for two
years, an onboarding page from six months ago — written by Sara, edited by
Bob; the team Payments; the service Billing API, its Datadog catalogue
linking its runbook; the application Billing platform; a business system's
capability Invoicing, naming its data, and the tables it names.

What these protect: where a document opens and how fresh it is, as
enrichment's; a space named for a team is the team's — and its documents
are too, inherited — one named for a service documents it; a catalogue's
link found at a document's address; a document whose title names an
application or a capability describes it; the data a business system
names, found — or not, when two tables share the name; a space is a
container: its writers maintain it, its writing is expertise.
"""

from __future__ import annotations

from leka.ingestion.enrichment import enrich
from leka.ingestion.enrichment.engine import Edge, Enrichment
from tests.test_enrichment import CONFLUENCE, PAGERDUTY, World, ago

SPACE = "acme.atlassian.net/wiki/spaces/PAY"
RUNBOOK = "acme.atlassian.net/wiki/pages/1"
DESIGN = "acme.atlassian.net/wiki/pages/2"
ONBOARDING = "acme.atlassian.net/wiki/pages/3"
DECK = "microsoft_365:document:b!pay/deck"
PAYMENTS = "team:payments"
BILLING = "service:billing-api"
PLATFORM = "application:billing-platform"
INVOICING = "capability:invoicing"
SARA = "person:email:sara@acme.io"
BOB = "person:email:bob@acme.io"
INVOICES = "db:postgresql://ledger:5432/ledger/billing/invoices"
CUSTOMERS = "db:postgresql://ledger:5432/ledger/crm/customers"
OTHER_CUSTOMERS = "db:postgresql://ledger:5432/ledger/shop/customers"


def _world() -> World:
    w = World()
    w.thing(
        SPACE,
        "Payments team wiki",
        type="knowledge_space",
        sources=(CONFLUENCE,),
        links=("https://acme.atlassian.net/wiki/spaces/PAY",),
    )
    for key, title, days in (
        (RUNBOOK, "Billing API runbook", 7),
        (DESIGN, "Architecture overview", 800),
        (ONBOARDING, "Invoicing — how it works", 200),
    ):
        w.thing(
            key,
            title,
            type="document",
            sources=(CONFLUENCE,),
            links=(f"https://{key}/x",),
            updated_at=ago(days),
        )
        w.states(CONFLUENCE, key, "part_of", SPACE)
        w.states(CONFLUENCE, key, "authored_by", SARA)
    w.states(CONFLUENCE, DESIGN, "edited_by", BOB)
    w.thing(
        DECK,
        "Q3 review",
        type="document",
        sources=(CONFLUENCE,),
        links=("https://acme.sharepoint.com/sites/pay/Shared%20Documents/deck.pptx",),
        updated_at=ago(3),
        verified=False,
        next_verification_at="2026-10-15T00:00:00Z",
    )
    w.thing(PAYMENTS, "Payments", type="team", sources=(PAGERDUTY,))
    w.thing(SARA, "Sara Martin", type="person")
    w.thing(BOB, "Bob Lee", type="person")
    w.thing(
        BILLING,
        "Billing API",
        type="service",
        sources=(PAGERDUTY,),
        runbook_url="https://acme.sharepoint.com/sites/pay/Shared Documents/deck.pptx?web=1",
    )
    w.thing(PLATFORM, "Billing platform", type="application", sources=(PAGERDUTY,))
    w.thing(
        INVOICING,
        "Invoicing",
        type="business_capability",
        sources=(PAGERDUTY,),
        data_names=["billing.invoices", "customers", "ledger_entries"],
    )
    w.thing(INVOICES, "billing.invoices", type="data_object", schema_name="billing")
    w.thing(CUSTOMERS, "crm.customers", type="data_object", schema_name="crm")
    w.thing(OTHER_CUSTOMERS, "shop.customers", type="data_object", schema_name="shop")
    return w


def _edge(enrichment: Enrichment, w: World, a: str, kind: str, b: str) -> Edge | None:
    return next(
        (e for e in enrichment.edges if (e.from_id, e.type, e.to_id) == (w.id(a), kind, w.id(b))),
        None,
    )


def _facts(enrichment: Enrichment, w: World, key: str) -> dict[str, object]:
    return {f.attribute: f.value for f in enrichment.facts if f.entity_id == w.id(key)}


def test_a_document_opens_somewhere_and_is_fresh_aging_or_stale() -> None:
    w = _world()

    enrichment = enrich(w.snapshot())

    assert [_facts(enrichment, w, k)["freshness"] for k in (RUNBOOK, ONBOARDING, DESIGN)] == [
        "fresh",
        "aging",
        "stale",
    ]
    runbook = _facts(enrichment, w, RUNBOOK)
    assert runbook["url"] == f"https://{RUNBOOK}/x"
    assert _facts(enrichment, w, SPACE)["url"] == "https://acme.atlassian.net/wiki/spaces/PAY"
    deck = _facts(enrichment, w, DECK)
    assert deck["verification_due_at"] == "2026-10-15T00:00:00Z"


def test_a_space_named_for_a_team_is_its_and_its_documents_are_too() -> None:
    w = _world()

    enrichment = enrich(w.snapshot())

    owned = _edge(enrichment, w, SPACE, "owned_by", PAYMENTS)
    assert owned is not None
    assert (owned.origin, owned.rule, owned.confidence) == ("inferred", "same_name", 0.7)
    inherited = _edge(enrichment, w, RUNBOOK, "owned_by", PAYMENTS)
    assert inherited is not None
    assert inherited.rule == "inherited"


def test_a_space_named_for_a_service_documents_it() -> None:
    w = _world()
    w.thing("acme.atlassian.net/wiki/spaces/BIL", "Billing API docs", type="knowledge_space")

    enrichment = enrich(w.snapshot())

    found = _edge(enrichment, w, "acme.atlassian.net/wiki/spaces/BIL", "describes", BILLING)
    assert found is not None
    assert found.rule == "same_name"


def test_a_catalogue_s_runbook_link_is_found_at_its_document_s_address() -> None:
    w = _world()

    enrichment = enrich(w.snapshot())

    found = _edge(enrichment, w, DECK, "describes", BILLING)
    assert found is not None
    assert (found.rule, found.confidence) == ("linked", 0.95)


def test_a_document_describes_what_its_title_names() -> None:
    w = _world()

    enrichment = enrich(w.snapshot())

    service = _edge(enrichment, w, RUNBOOK, "describes", BILLING)
    capability = _edge(enrichment, w, ONBOARDING, "describes", INVOICING)
    assert service is not None
    assert capability is not None
    assert capability.rule == "named_in_title"
    # "Billing" alone names the application too: its core.
    assert _edge(enrichment, w, RUNBOOK, "describes", PLATFORM) is not None


def test_the_data_a_business_system_names_is_found_unless_two_share_the_name() -> None:
    w = _world()

    enrichment = enrich(w.snapshot())

    invoices = _edge(enrichment, w, INVOICING, "uses", INVOICES)
    assert invoices is not None
    assert (invoices.rule, invoices.confidence) == ("named", 0.9)
    # Two tables are called customers: neither is said.
    assert _edge(enrichment, w, INVOICING, "uses", CUSTOMERS) is None
    assert _edge(enrichment, w, INVOICING, "uses", OTHER_CUSTOMERS) is None
    assert enrichment.counts["knowledge.data_ambiguous"] == 1
    assert enrichment.counts["knowledge.data_unfound"] == 1


def test_a_space_s_writers_maintain_it_and_know_it() -> None:
    w = _world()

    enrichment = enrich(w.snapshot())

    assert _edge(enrichment, w, SPACE, "maintained_by", SARA) is not None
    assert _edge(enrichment, w, SARA, "contributes_to", SPACE) is not None
    expertise = _facts(enrichment, w, SARA)["expertise"]
    assert isinstance(expertise, list)
    space = next(area for area in expertise if area["key"] == SPACE)
    assert (space["items"], space["roles"]) == (3, {"authored": 3})
    # A space is a container: its activity is its documents'.
    assert _facts(enrichment, w, SPACE)["last_activity_at"] == ago(7)
