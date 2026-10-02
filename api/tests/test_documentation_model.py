"""Documentation and business knowledge, as normalisation writes them (LEKA-366).

From the connectors' payloads through extraction, parsing and
normalisation: where each tool keeps its documents — a Confluence space, a
Notion database, a Slab topic, a Guru collection, a shared drive, a
SharePoint library — and the documents in them, their people and their
links; a catalogue's documentation link; a business system's capabilities,
processes and activities, what supports them, what they use.

What these protect: a space keyed as its documents name it, so they are
part of it; who wrote, owns and last changed a document; what it links to,
read as the thing it opens; a capability and a process keyed by name — an
activity by its path — so two systems naming one meet; and a custom source
may declare every entity normalisation makes.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest

from leka.connectors import Capability, Mapping, SourceKind
from leka.connectors.custom.definition import Entity as Declarable
from leka.ingestion.normalisation import NormalisedRecord, normalise
from leka.ingestion.normalisation import identifiers as ids
from leka.ingestion.normalisation.mapping import CUSTOM_ENTITIES
from leka.ingestion.parsing import ParsedRecord, parse
from tests.test_confluence_connector import ENG
from tests.test_extraction import _extract
from tests.test_guru_connector import ONBOARDING, card

C = Capability
K = SourceKind
SITE = "acme.atlassian.net"
DATABASE = "2f26ee68-df30-4251-aad4-8ddc420cba3d"


def _normalised(
    kind: SourceKind,
    capability: Capability,
    payload: dict[str, Any],
    mapping: Mapping | None = None,
    **extra: Any,
) -> NormalisedRecord:
    extracted = _extract(kind, capability, payload, **extra)
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord)
    result = normalise(extracted, parsed, mapping)
    assert isinstance(result, NormalisedRecord), result
    return result


def _edges(record: NormalisedRecord) -> set[tuple[str, str, str]]:
    return {(r.from_key, r.type, r.to_key) for r in record.relationships}


def _page(**extra: Any) -> dict[str, Any]:
    return {
        "id": "1001",
        "title": "Billing runbook",
        "spaceId": "98304",
        "parentId": "999",
        "authorId": "u-sara",
        "ownerId": "u-nora",
        "version": {"number": 4, "createdAt": "2026-09-20T10:00:00Z", "authorId": "u-bob"},
        "body": {
            "storage": {
                "value": "<p>Restart it. The code: "
                '<a href="https://github.com/acme/billing-api/tree/main/deploy">billing-api</a>; '
                "on call: <a href='https://acme.atlassian.net/wiki/spaces/OPS/pages/2002/On+call'>"
                "the rota</a>; the bug: "
                '<a href="https://acme.atlassian.net/browse/PAY-42">PAY-42</a>.</p>'
            }
        },
        "web_url": f"https://{SITE}/wiki/spaces/ENG/pages/1001/Billing+runbook",
        **extra,
    }


# ── where documents are kept ─────────────────────────────────────────────────


def test_a_confluence_space_is_keyed_by_its_site_and_key_as_its_pages_name_it() -> None:
    space = _normalised(
        K.CONFLUENCE,
        C.SPACES,
        {**ENG, "web_url": f"https://{SITE}/wiki/spaces/ENG"},
        external_id="98304",
        container=None,
    )
    page = _normalised(K.CONFLUENCE, C.PAGES, _page(), external_id="1001", container="ENG")

    entity = space.entity
    assert (entity.type, entity.key, entity.name) == (
        "knowledge_space",
        f"{SITE}/wiki/spaces/ENG",
        "Engineering",
    )
    a = entity.attributes
    assert (a["space_kind"], a["space_type"], a["space_key"], a["description"]) == (
        "space",
        "global",
        "ENG",
        "How we build",
    )
    assert ("part_of", f"{SITE}/wiki/spaces/ENG") in {(k, t) for _, k, t in _edges(page)}


@pytest.mark.parametrize(
    ("kind", "capability", "payload", "own_id", "key", "space_kind"),
    [
        (K.SLAB, C.SPACES, {"id": "t-1", "name": "Engineering"}, "t-1", "slab:space:t-1", "topic"),
        (K.GURU, C.SPACES, ONBOARDING, "c-onboard", "guru:space:c-onboard", "collection"),
        (
            K.GOOGLE_WORKSPACE,
            C.DRIVES,
            {"id": "0AEng", "name": "Engineering"},
            "0AEng",
            "google_workspace:space:0AEng",
            "shared_drive",
        ),
        (
            K.MICROSOFT_365,
            C.DRIVES,
            {"id": "b!docs", "name": "Documents", "driveType": "documentLibrary"},
            "b!docs",
            "microsoft_365:space:b!docs",
            "document_library",
        ),
        (
            K.NOTION,
            C.DATABASES,
            {"id": "db-1", "title": [{"plain_text": "Specs"}]},
            "db-1",
            "notion:space:db-1",
            "database",
        ),
    ],
)
def test_every_tool_s_space_is_a_knowledge_space(
    kind: SourceKind,
    capability: Capability,
    payload: dict[str, Any],
    own_id: str,
    key: str,
    space_kind: str,
) -> None:
    space = _normalised(kind, capability, payload, external_id=own_id, container=None)

    assert (space.entity.type, space.entity.key) == ("knowledge_space", key)
    assert space.entity.attributes["space_kind"] == space_kind


def test_a_notion_database_goes_by_its_page_key_too_and_holds_its_pages() -> None:
    database = _normalised(
        K.NOTION,
        C.DATABASES,
        {"id": "db-1", "title": [{"plain_text": "Specs"}]},
        external_id="db-1",
        container=None,
    )
    page = _normalised(
        K.NOTION,
        C.PAGES,
        {
            "id": "p-1",
            "url": "https://www.notion.so/Spec-p1",
            "properties": {"Name": {"type": "title", "title": [{"plain_text": "Ledger spec"}]}},
            "parent": {"type": "database_id", "database_id": "db-1"},
            "created_by": {"id": "n-sara"},
            "last_edited_by": {"id": "n-bob"},
        },
        external_id="p-1",
        container="db-1",
    )

    # A link to a database reads as a link to a page.
    assert database.entity.aliases == ["notion:document:db-1"]
    edges = _edges(page)
    assert ("notion:document:p-1", "part_of", "notion:space:db-1") in edges
    assert not any(kind == "child_of" for _, kind, _ in edges)
    # Its creator wrote it; who last changed it edited it.
    assert {(kind, to) for _, kind, to in edges} >= {
        ("authored_by", "person:notion.so:n-sara"),
        ("edited_by", "person:notion.so:n-bob"),
    }


def test_a_sharepoint_library_is_its_group_s_a_onedrive_its_person_s() -> None:
    library = _normalised(
        K.MICROSOFT_365,
        C.DRIVES,
        {
            "id": "b!pay",
            "name": "Payments documents",
            "driveType": "documentLibrary",
            "owner": {"group": {"id": "g-1", "displayName": "Payments"}},
        },
        external_id="b!pay",
        container=None,
    )
    onedrive = _normalised(
        K.MICROSOFT_365,
        C.DRIVES,
        {
            "id": "b!sara",
            "name": "OneDrive",
            "driveType": "business",
            "owner": {"user": {"id": "u-sara", "displayName": "Sara", "email": "sara@acme.io"}},
        },
        external_id="b!sara",
        container=None,
    )

    assert ("microsoft_365:space:b!pay", "owned_by", "team:payments") in _edges(library)
    assert onedrive.entity.attributes["space_kind"] == "onedrive"
    assert ("microsoft_365:space:b!sara", "owned_by", "person:email:sara@acme.io") in _edges(
        onedrive
    )


def test_google_s_own_drive_is_no_space() -> None:
    file = _normalised(
        K.GOOGLE_WORKSPACE,
        C.FILES,
        {"id": "f-1", "name": "Notes", "mimeType": "text/plain"},
        external_id="f-1",
        container="user",
    )

    assert not any(kind == "part_of" for _, kind, _ in _edges(file))


def test_the_source_s_mapping_says_what_a_space_documents_and_whose_it_is() -> None:
    mapping = Mapping.model_validate(
        {
            "services": [{"match": "PAY", "service": "Billing API"}],
            "owners": [{"match": "PAY", "team": "Payments"}],
        }
    )

    space = _normalised(
        K.CONFLUENCE,
        C.SPACES,
        {"id": "7", "key": "PAY", "name": "Payments", "type": "global"},
        mapping,
        external_id="7",
        container=None,
    )
    page = _normalised(K.CONFLUENCE, C.PAGES, _page(), mapping, external_id="1001", container="PAY")

    key = space.entity.key
    assert {(key, "describes", "service:billing-api"), (key, "owned_by", "team:payments")} <= (
        _edges(space)
    )
    # A document is not part of its service: it describes it.
    assert (f"{SITE}/wiki/pages/1001", "describes", "service:billing-api") in _edges(page)
    assert (f"{SITE}/wiki/pages/1001", "part_of", "service:billing-api") not in _edges(page)


# ── documents ────────────────────────────────────────────────────────────────


def test_a_page_s_people_who_wrote_owns_and_last_changed_it() -> None:
    page = _normalised(K.CONFLUENCE, C.PAGES, _page(), external_id="1001", container="ENG")

    key = f"{SITE}/wiki/pages/1001"
    assert page.entity.attributes["document_kind"] == "page"
    assert page.entity.attributes["version"] == 4
    assert _edges(page) >= {
        (key, "authored_by", f"person:{SITE}:u-sara"),
        (key, "owned_by", f"person:{SITE}:u-nora"),
        (key, "edited_by", f"person:{SITE}:u-bob"),
        (key, "child_of", f"{SITE}/wiki/pages/999"),
    }


def test_a_page_s_links_are_what_they_open() -> None:
    page = _normalised(K.CONFLUENCE, C.PAGES, _page(), external_id="1001", container="ENG")

    key = f"{SITE}/wiki/pages/1001"
    assert _edges(page) >= {
        (key, "mentions", "github.com/acme/billing-api"),
        (key, "references", f"{SITE}/wiki/pages/2002"),
        (key, "mentions", "ticket:PAY-42"),
    }
    # Read, not kept: the links are relationships.
    assert "links" not in page.entity.attributes


def test_a_guru_card_says_whether_it_is_verified_and_goes_by_its_slug() -> None:
    payload = {
        **card(1),
        "slug": "cdkRAp6i",
        "verificationState": "NEEDS_VERIFICATION",
        "lastModifiedBy": {"email": "bob@acme.io", "firstName": "Bob", "lastName": "Lee"},
        "nextVerificationDate": "2026-10-15T00:00:00.000+0000",
    }

    found = _normalised(K.GURU, C.PAGES, payload, external_id="card-1", container="c-onboard")

    entity = found.entity
    assert (entity.attributes["verified"], entity.attributes["document_kind"]) == (False, "card")
    assert "guru:card:cdkRAp6i" in entity.aliases
    assert entity.attributes["next_verification_at"] == "2026-10-15T00:00:00Z"
    assert _edges(found) >= {
        ("guru:document:card-1", "part_of", "guru:space:c-onboard"),
        ("guru:document:card-1", "edited_by", "person:email:bob@acme.io"),
    }


def test_a_slab_post_s_links_and_a_notion_page_s() -> None:
    slab = _normalised(
        K.SLAB,
        C.PAGES,
        {
            "id": "p1",
            "title": "Deploying",
            "content": [
                {"insert": "See "},
                {
                    "insert": "the spec",
                    "attributes": {"link": "https://docs.google.com/document/d/1AbC/edit"},
                },
            ],
        },
        external_id="p1",
        container="t-1",
    )
    notion = _normalised(
        K.NOTION,
        C.PAGES,
        {
            "id": "p-2",
            "properties": {"Name": {"type": "title", "title": [{"plain_text": "Runbooks"}]}},
            "blocks": [
                {
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "plain_text": "Ledger spec",
                                "href": "https://www.notion.so/Ledger-59833787a2cf4fdf8782e53db20768a5",
                            }
                        ]
                    },
                },
                {
                    "type": "link_to_page",
                    "link_to_page": {"type": "database_id", "database_id": DATABASE},
                },
            ],
        },
        external_id="p-2",
        container=None,
    )

    assert ("slab:document:p1", "part_of", "slab:space:t-1") in _edges(slab)
    assert ("slab:document:p1", "references", "google_workspace:document:1AbC") in _edges(slab)
    assert _edges(notion) >= {
        (
            "notion:document:p-2",
            "references",
            "notion:document:59833787-a2cf-4fdf-8782-e53db20768a5",
        ),
        ("notion:document:p-2", "references", f"notion:document:{DATABASE}"),
    }


@pytest.mark.parametrize(
    ("url", "found"),
    [
        (
            f"https://{SITE}/wiki/spaces/ENG/pages/1001/Runbook",
            ("document", f"{SITE}/wiki/pages/1001"),
        ),
        (
            f"https://{SITE}/wiki/pages/viewpage.action?pageId=1001",
            ("document", f"{SITE}/wiki/pages/1001"),
        ),
        (
            f"https://{SITE}/wiki/spaces/eng/overview",
            ("knowledge_space", f"{SITE}/wiki/spaces/ENG"),
        ),
        (
            "https://docs.google.com/spreadsheets/d/1XyZ/edit#gid=0",
            ("document", "google_workspace:document:1XyZ"),
        ),
        ("https://drive.google.com/file/d/1F/view", ("document", "google_workspace:document:1F")),
        (
            "https://drive.google.com/drive/folders/0AEng",
            ("knowledge_space", "google_workspace:space:0AEng"),
        ),
        ("https://acme.slab.com/posts/deploying-ab12cd34", ("document", "slab:document:ab12cd34")),
        ("https://app.getguru.com/card/cdkRAp6i/Refunds", ("document", "guru:card:cdkRAp6i")),
        (
            "https://gitlab.com/acme/pay/ledger/-/blob/main/README.md",
            ("repository", "gitlab.com/acme/pay/ledger"),
        ),
        ("https://github.com/orgs/acme/teams", None),
        ("https://example.com/wiki", None),
    ],
)
def test_a_link_is_read_as_the_thing_it_opens(url: str, found: tuple[str, str] | None) -> None:
    assert ids.linked(url) == found


def test_a_catalogue_s_documentation_link_describes_its_service() -> None:
    service = _normalised(
        K.DATADOG,
        C.SERVICES,
        {
            "attributes": {
                "schema": {
                    "dd-service": "billing-api",
                    "team": "payments",
                    "links": [
                        {
                            "type": "doc",
                            "url": f"https://{SITE}/wiki/spaces/PAY/pages/3003/Billing",
                        },
                        {"type": "runbook", "url": f"https://{SITE}/wiki/spaces/PAY/pages/3004"},
                        {"type": "repo", "url": "https://github.com/acme/billing-api"},
                    ],
                }
            }
        },
        external_id="billing-api",
        container=None,
    )

    assert _edges(service) >= {
        (f"{SITE}/wiki/pages/3003", "describes", "service:billing-api"),
        (f"{SITE}/wiki/pages/3004", "describes", "service:billing-api"),
    }
    assert not any(t == "describes" and f.startswith("github.com") for f, t, _ in _edges(service))


# ── a business system ────────────────────────────────────────────────────────


def _business(
    entity: str, record_id: str, title: str, metadata: dict[str, Any]
) -> NormalisedRecord:
    return _normalised(
        K.CUSTOM_REST,
        C.RECORDS,
        {
            "resource": f"{entity}s",
            "entity": entity,
            "fields": {"id": record_id, "title": title, "metadata": metadata},
        },
        external_id=f"{entity}s:{record_id}",
    )


def test_a_capability_its_parent_processes_support_data_owners_and_documentation() -> None:
    invoicing = _business(
        "business_capability",
        "c-2",
        "Invoicing",
        {
            "parent": "Finance",
            "level": "L2",
            "applications": "Billing platform",
            "services": ["Ledger"],
            "processes": "Order to cash",
            "data": "billing.invoices, customers",
            "owner": "Sara@acme.io",
            "team": "Finance Ops",
            "criticality": "Tier 1",
            "documentation": f"https://{SITE}/wiki/spaces/FIN/pages/3005",
        },
    )

    entity = invoicing.entity
    key = "capability:invoicing"
    assert (entity.type, entity.key) == ("business_capability", key)
    a = entity.attributes
    assert (a["level"], a["criticality"], a["data_names"]) == (
        2,
        "critical",
        ["billing.invoices", "customers"],
    )
    assert {"parent", "applications", "processes", "data", "owner", "team"}.isdisjoint(a)
    assert _edges(invoicing) >= {
        (key, "child_of", "capability:finance"),
        (key, "supported_by", "application:billing-platform"),
        (key, "supported_by", "service:ledger"),
        ("process:order-to-cash", "realizes", key),
        (key, "owned_by", "person:email:sara@acme.io"),
        (key, "owned_by", "team:finance-ops"),
        (f"{SITE}/wiki/pages/3005", "describes", key),
    }


def test_an_activity_is_keyed_by_its_path_under_its_process() -> None:
    send = _business(
        "business_process",
        "a-7",
        "Send invoice",
        {
            "parent": "Order to cash/Invoicing",
            "step": "2",
            "type": "Activity",
            "services": "Mailer",
        },
    )
    process = _business(
        "business_process", "p-1", "Order to cash", {"capabilities": "Invoicing, Payments"}
    )

    key = "process:order-to-cash/invoicing/send-invoice"
    assert (send.entity.key, send.entity.attributes["step"]) == (key, 2)
    assert send.entity.attributes["process_type"] == "activity"
    assert _edges(send) >= {
        (key, "part_of", "process:order-to-cash/invoicing"),
        (key, "supported_by", "service:mailer"),
    }
    assert _edges(process) >= {
        ("process:order-to-cash", "realizes", "capability:invoicing"),
        ("process:order-to-cash", "realizes", "capability:payments"),
    }


def test_an_application_says_the_capabilities_it_supports() -> None:
    application = _business(
        "application", "a-1", "Billing platform", {"capabilities": "Invoicing", "team": "Payments"}
    )

    assert ("capability:invoicing", "supported_by", "application:billing-platform") in _edges(
        application
    )


def test_a_custom_source_may_declare_every_entity_normalisation_makes() -> None:
    assert set(get_args(Declarable)) == CUSTOM_ENTITIES
