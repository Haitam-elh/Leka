"""The project and documentation tools' records, extracted (LEKA-346 → LEKA-354).

The payloads are the ones each connector stores — built by their stand-ins
in tests/test_*_connector.py and tests/test_*_resources.py. What matters:
every capability of the eleven comes out with a title and its text, the
tool's own key and people, and a document's text read out of its markup —
Confluence's XHTML, Guru's HTML, Notion's blocks, Slab's Quill delta.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction import FailureCode
from leka.ingestion.extraction.fields import delta_text, markup_text
from tests.test_asana_connector import LAUNCH
from tests.test_asana_resources import _task as asana_task
from tests.test_clickup_resources import _task as clickup_task
from tests.test_confluence_connector import ENG
from tests.test_confluence_resources import _page as confluence_page
from tests.test_extraction import SECRET, _extract, _failure
from tests.test_google_workspace_connector import ENGINEERING, drive_file
from tests.test_guru_connector import ONBOARDING, card
from tests.test_microsoft_365_connector import DOCS as M365_DOCS
from tests.test_microsoft_365_connector import DRIVES as M365_DRIVES
from tests.test_microsoft_365_resources import item as m365_item
from tests.test_monday_connector import ROADMAP as MONDAY_ROADMAP
from tests.test_monday_resources import _item as monday_item
from tests.test_notion_connector import WIKI, page
from tests.test_slab_connector import ENGINEERING as SLAB_TOPIC
from tests.test_trello_connector import ROADMAP as TRELLO_ROADMAP
from tests.test_trello_resources import _card as trello_card

C = Capability
K = SourceKind

LINEAR_ISSUE: dict[str, Any] = {
    "id": "issue-uuid-42",
    "identifier": "ENG-42",
    "title": "Retry the payment webhook",
    "description": "Fixes the **timeouts**.",
    "priorityLabel": "High",
    "url": "https://linear.app/acme/issue/ENG-42/retry-the-payment-webhook",
    "createdAt": "2026-09-20T08:00:00.000Z",
    "updatedAt": "2026-09-21T12:05:00.000Z",
    "state": {"name": "In Review", "type": "started"},
    "team": {"key": "ENG"},
    "project": {"id": "proj-1", "name": "Payments"},
    "parent": {"identifier": "ENG-40"},
    "assignee": {"id": "u-1", "name": "Nora", "email": "nora@acme.test"},
    "labels": {"nodes": [{"name": "bug"}]},
    "relations": {"nodes": [{"type": "blocks", "relatedIssue": {"identifier": "OPS-1"}}]},
}
LINEAR_PROJECT: dict[str, Any] = {
    "id": "proj-1",
    "name": "Payments",
    "slugId": "payments-1a2b",
    "status": {"name": "In progress", "type": "started"},
    "lead": {"id": "u-1", "name": "Nora", "email": "nora@acme.test"},
    "updatedAt": "2026-09-22T10:00:00.000Z",
}
NOTION_PAGE = page(
    WIKI,
    "Wiki",
    "2026-09-21T12:05:00.000Z",
    {"type": "page_id", "page_id": "parent-page"},
    created_by={"id": "user-7"},
    blocks=[
        {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "On call"}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Page the owner."}]}},
        {"type": "child_page", "child_page": {"title": "Runbooks"}},
    ],
)
SLAB_POST = {
    "id": "p1",
    "title": "Deploying",
    "content": json.dumps([{"insert": "Ship on "}, {"insert": "Tuesdays\n"}]),
    "insertedAt": "2026-09-01T08:00:00Z",
    "updatedAt": "2026-09-21T12:05:00Z",
    "publishedAt": "2026-09-01T09:00:00Z",
}

# Every capability of the eleven: a payload, and the title it must give.
EVERY = [
    (K.LINEAR, C.PROJECTS, LINEAR_PROJECT, "Payments"),
    (K.LINEAR, C.ISSUES, LINEAR_ISSUE, "Retry the payment webhook"),
    (K.ASANA, C.PROJECTS, LAUNCH, "Launch"),
    (K.ASANA, C.ISSUES, asana_task("7", "1001"), "Task 7"),
    (K.TRELLO, C.PROJECTS, TRELLO_ROADMAP, "Roadmap"),
    (K.TRELLO, C.ISSUES, trello_card(3), "Card 3"),
    (K.CLICKUP, C.PROJECTS, {"id": "l-1", "name": "Launch", "task_count": 4}, "Launch"),
    (K.CLICKUP, C.ISSUES, clickup_task(1), "Task 1"),
    (K.MONDAY, C.PROJECTS, MONDAY_ROADMAP, "Roadmap"),
    (K.MONDAY, C.ISSUES, monday_item(1), "Item 1"),
    (K.CONFLUENCE, C.SPACES, ENG, "Engineering"),
    (K.CONFLUENCE, C.PAGES, confluence_page(1, "2026-09-21T12:05:00Z"), "Runbook 1"),
    (K.NOTION, C.PAGES, NOTION_PAGE, "Wiki"),
    (
        K.NOTION,
        C.DATABASES,
        {"id": "db-1", "title": [{"plain_text": "Specs"}], "properties": {"Owner": {}}},
        "Specs",
    ),
    (K.SLAB, C.SPACES, SLAB_TOPIC, "Engineering"),
    (K.SLAB, C.PAGES, SLAB_POST, "Deploying"),
    (K.GURU, C.SPACES, ONBOARDING, "Onboarding"),
    (K.GURU, C.PAGES, card(1), "Card 1"),
    (K.GOOGLE_WORKSPACE, C.DRIVES, ENGINEERING, "Engineering"),
    (
        K.GOOGLE_WORKSPACE,
        C.FILES,
        {**drive_file("spec"), "content": "Every call is a GET."},
        "spec.doc",
    ),
    (K.MICROSOFT_365, C.DRIVES, M365_DRIVES[M365_DOCS], "Documents"),
    (
        K.MICROSOFT_365,
        C.FILES,
        {**m365_item("report", name="Report.docx"), "content": "Q3"},
        "Report.docx",
    ),
]


@pytest.mark.parametrize(("kind", "capability", "payload", "title"), EVERY)
def test_every_capability_of_the_eleven_is_extracted(
    kind: SourceKind, capability: Capability, payload: dict[str, Any], title: str
) -> None:
    found = _extract(kind, capability, payload)

    assert found.title == title
    assert found.extractor == f"{kind.value}.{capability.value}"


# ── project tools ────────────────────────────────────────────────────────────


def test_a_linear_issue_keeps_its_key_its_state_s_class_and_its_links() -> None:
    issue = _extract(K.LINEAR, C.ISSUES, LINEAR_ISSUE)

    assert (issue.metadata["key"], issue.metadata["status_category"]) == ("ENG-42", "started")
    assert (issue.state, issue.metadata["priority"]) == ("in review", "High")
    assert issue.content[0].format == "markdown"
    refs = {(r.role, r.kind, r.external_id or r.email) for r in issue.references}
    assert refs >= {
        ("assignee", "person", "u-1"),
        ("project", "project", "proj-1"),
        ("parent", "issue", "ENG-40"),
        ("related", "issue", "OPS-1"),
    }


def test_a_clickup_task_s_dates_are_read_from_milliseconds() -> None:
    task = _extract(K.CLICKUP, C.ISSUES, clickup_task(1))

    assert task.updated_at == datetime.fromtimestamp(1_790_000_000, tz=UTC)


def test_a_monday_item_s_state_is_its_status_column() -> None:
    item = {
        **monday_item(1),
        "column_values": [
            {"id": "person", "type": "people", "text": "Nora"},
            {"id": "status", "type": "status", "text": "Working on it"},
        ],
    }

    assert _extract(K.MONDAY, C.ISSUES, item).state == "working on it"


def test_an_asana_task_is_closed_when_completed_and_names_its_projects() -> None:
    task = _extract(K.ASANA, C.ISSUES, {**asana_task("9", "1001", "2001"), "completed": True})

    assert task.state == "closed"
    assert [r.external_id for r in task.references if r.kind == "project"] == ["1001", "2001"]


# ── documents ────────────────────────────────────────────────────────────────


def test_a_confluence_page_s_xhtml_is_read_as_text() -> None:
    payload = {
        **confluence_page(1, "2026-09-21T12:05:00Z"),
        "body": {
            "storage": {
                "value": "<h1>Restart</h1><p>Run <code>kubectl rollout</code>&nbsp;now.</p>"
                "<ac:structured-macro ac:name='info'><ac:rich-text-body><p>Careful</p>"
                "</ac:rich-text-body></ac:structured-macro>"
            }
        },
        "authorId": "5b10ac8d",
        "web_url": "https://acme.atlassian.net/wiki/spaces/ENG/pages/1001/Runbook",
    }

    found = _extract(K.CONFLUENCE, C.PAGES, payload)

    # A non-breaking space is a space, in text.
    assert found.content[0].text == "Restart\nRun kubectl rollout now.\nCareful"
    assert found.url == payload["web_url"]
    assert ("author", "5b10ac8d") in {(r.role, r.external_id) for r in found.references}


def test_a_notion_page_is_its_blocks_a_line_each() -> None:
    found = _extract(K.NOTION, C.PAGES, NOTION_PAGE)

    assert found.content[0].text == "On call\nPage the owner.\nRunbooks"
    assert ("parent", "document", "parent-page") in {
        (r.role, r.kind, r.external_id) for r in found.references
    }


def test_a_slab_post_is_the_text_its_delta_inserts() -> None:
    found = _extract(K.SLAB, C.PAGES, SLAB_POST)

    assert (found.content[0].text, found.state) == ("Ship on Tuesdays", "published")


def test_a_guru_card_s_html_is_read_as_text() -> None:
    found = _extract(K.GURU, C.PAGES, card(2, "c-sales"))

    assert found.content[0].text == "Card 2"
    assert found.metadata["collection"] == "c-sales"


def test_a_file_s_text_is_its_body() -> None:
    payload = {**drive_file("spec"), "content": "Every call is a GET.", "content_truncated": True}

    found = _extract(K.GOOGLE_WORKSPACE, C.FILES, payload)

    assert found.content[-1].text == "Every call is a GET."
    assert found.metadata["content_truncated"] is True


def test_markup_is_read_never_run() -> None:
    markup = "<script>alert(1)</script><style>p{}</style><p>kept &amp; clean</p>"

    assert markup_text(markup) == "kept & clean"
    assert markup_text("   ") is None


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ('[{"insert": "a"}, {"insert": "b\\n"}]', "ab"),
        ({"ops": [{"insert": "c"}, {"insert": {"image": "x"}}]}, "c"),
        ("plain words", "plain words"),
        (42, None),
    ],
)
def test_a_quill_delta_in_every_shape_slab_sends(value: object, text: str | None) -> None:
    assert delta_text(value) == text


def test_a_page_without_a_title_is_malformed_and_nothing_of_it_leaks() -> None:
    failure = _failure(K.CONFLUENCE, C.PAGES, {"id": "1", "body": SECRET})

    assert failure.code is FailureCode.MALFORMED
