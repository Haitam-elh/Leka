"""What LEKA proposes to send out of a deliverable: tickets for Jira, pages
for Confluence (2026-10-18).

What these protect:
- Markdown becomes Jira's wiki markup and Confluence's storage format:
  headings, nested lists, code, tables, quotes, rules, bold, italic, inline
  code, links — a link that is not http(s) is dropped, text is escaped for
  Confluence, code stays code.
- Asked from a finished run, of a Jira source for a project it reads: kept,
  drafting, queued for a worker; refused, said why, for a run not finished,
  a source of the wrong kind, or a project the source does not read.
- Drafted from the run's deliverable — the model again, no tools — into
  tickets, each with an id a person chooses by.
- Accepted only by who may approve; refused before anything is sent while
  the source does not allow it (`issues`), and it stays proposed. Allowed:
  the tickets chosen are created through Jira — the project's type found,
  the description in wiki markup, labelled leka — each with its key and
  address; the others are not sent.
- Pages, the same, for Confluence: the space found by its key, the body in
  storage format; a title already taken is said for that page.
- Another workspace sees nothing.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.api import proposals as proposals_api
from leka.capabilities import AgentRun
from leka.capabilities.proposals import draft
from leka.connectors import SourceKind, SourceService
from leka.connectors.atlassian_markup import confluence_xhtml, jira_wiki
from leka.connectors.base import Connector
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import Script, gemini, leka_gemini  # noqa: F401
from tests.test_context_engine import model  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

pytestmark = pytest.mark.integration

DELIVERED = """# Revue de qualité d'interface

| # | Sévérité | Où | Constat | Correction |
| --- | --- | --- | --- | --- |
| 1 | Bloquant | `web/compact-composer.tsx:66` | une erreur réseau plante l'écran | l'intercepter |
| 2 | Important | `web/intention-composer.tsx:224` | champ en 15 px : iOS zoome | 16 px sur mobile |
"""

ISSUES = {
    "title": "Corriger l'accueil",
    "summary": "Deux corrections tirées de la revue.",
    "issues": [
        {
            "title": "Intercepter les erreurs réseau du compositeur",
            "description": "## Contexte\n\nUne erreur **réseau** fait planter l'écran.\n\n"
            "- [ ] l'erreur est affichée dans le formulaire\n\n`web/compact-composer.tsx:66`",
            "kind": "bug",
            "priority": "highest",
            "labels": ["accueil"],
        },
        {
            "title": "Passer le champ à 16 px sur mobile",
            "description": "iOS zoome sous 16 px.",
            "kind": "task",
            "priority": "high",
            "labels": [],
        },
    ],
}

PAGES = {
    "title": "La page d'accueil",
    "summary": "",
    "pages": [{"title": "Accueil — fonctionnement", "body": "# Accueil\n\nCe que fait l'écran."}],
}


# ── markdown, as Atlassian writes it ────────────────────────────────────────


def test_markdown_becomes_jira_wiki_markup_and_confluence_storage() -> None:
    md = (
        "# Titre\n\nUn **gras**, un *italique*, du `code`, [un lien](https://example.com) "
        "et [pas celui-ci](javascript:alert(1)).\n\n- un\n  - deux\n- trois\n\n1. premier\n\n"
        '```python\nif a < b and "]]>":\n    pass\n```\n\n| A | B |\n| --- | --- |\n| 1 | <b> |\n\n'
        "> citée\n\n---\n"
    )
    wiki = jira_wiki(md)
    for said in (
        "h1. Titre",
        "*gras*",
        "_italique_",
        "{{code}}",
        "[un lien|https://example.com]",
        "* un\n** deux\n* trois",
        "# premier",
        "{code:python}\nif a < b",
        "||A||B||",
        "|1|<b>|",
        "bq. citée",
        "----",
    ):
        assert said in wiki, said
    assert "javascript" not in wiki

    xhtml = confluence_xhtml(md)
    for said in (
        "<h1>Titre</h1>",
        "<strong>gras</strong>",
        "<em>italique</em>",
        "<code>code</code>",
        '<a href="https://example.com">un lien</a>',
        "<ul><li>un<ul><li>deux</li></ul></li><li>trois</li></ul>",
        "<ol><li>premier</li></ol>",
        '<ac:parameter ac:name="language">python</ac:parameter>',
        "]]]]><![CDATA[>",
        "<th>A</th>",
        "<td>&lt;b&gt;</td>",
        "<blockquote><p>citée</p></blockquote>",
        "<hr />",
    ):
        assert said in xhtml, said
    assert "javascript" not in xhtml


# ── end to end ─────────────────────────────────────────────────────────────


class Atlassian:
    """Jira and Confluence as LEKA uses them to write — every request kept."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, Any]] = []
        # Jira refusing the account (403), until told otherwise.
        self.refuse_issues = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.asked.append((request.method, path, body))
        assert request.headers["authorization"].startswith("Basic ")
        if path == "/rest/api/2/issue/createmeta/PAY/issuetypes":
            return httpx.Response(
                200,
                json={
                    "values": [
                        {"id": "3", "name": "Sous-tâche", "subtask": True},
                        {"id": "10001", "name": "Tâche", "subtask": False},
                        {"id": "10004", "name": "Bug", "subtask": False},
                    ]
                },
            )
        if request.method == "POST" and path == "/rest/api/2/issue":
            if self.refuse_issues:
                return httpx.Response(403, json={"errorMessages": ["No permission"]})
            return httpx.Response(201, json={"id": "11", "key": "PAY-24", "self": "…"})
        if path == "/wiki/api/v2/spaces":
            return httpx.Response(200, json={"results": [{"id": "98", "key": "ENG"}]})
        if request.method == "POST" and path == "/wiki/api/v2/pages":
            if body and body["title"] == "Déjà là":
                return httpx.Response(
                    400, json={"errors": [{"title": "A page with this title already exists"}]}
                )
            return httpx.Response(
                200, json={"id": "456", "_links": {"webui": "/spaces/ENG/pages/456/Accueil"}}
            )
        return httpx.Response(404)

    def writes(self) -> list[tuple[str, str, Any]]:
        return [a for a in self.asked if a[0] == "POST"]


@pytest.fixture
def atlassian(monkeypatch: pytest.MonkeyPatch) -> Atlassian:
    fake = Atlassian()

    def http(
        self: Connector[Any, Any], base_url: str, headers: dict[str, str] | None = None
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url, headers=headers or {}, transport=httpx.MockTransport(fake)
        )

    monkeypatch.setattr(Connector, "http", http)
    return fake


@pytest.fixture
def drafted(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """No worker here: the tests draft each proposal themselves."""
    asked: list[uuid.UUID] = []

    async def queue(workspace_id: uuid.UUID, proposal_id: uuid.UUID) -> bool:
        asked.append(proposal_id)
        return True

    monkeypatch.setattr(proposals_api, "queue_draft", queue)
    return asked


async def _source(workspace: uuid.UUID, kind: SourceKind, config: dict[str, object]) -> uuid.UUID:
    with workspace_scope(workspace):
        async with session_factory() as session:
            created = await SourceService(session, workspace, actor_user_id=None).create(
                kind,
                f"{kind.value} {uuid.uuid4().hex[:6]}",
                {"site": "acme", **config},
                {"token": "t" * 24, "email": "lecteur@acme.example"},
            )
            await session.execute(
                text("UPDATE sources SET status = 'active' WHERE id = :s"), {"s": created.id}
            )
            await session.commit()
            return created.id


async def _allow(workspace: uuid.UUID, source_id: uuid.UUID, flag: str) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE sources SET config = config"
                    " || jsonb_build_object(CAST(:f AS text), true) WHERE id = :s"
                ),
                {"f": flag, "s": source_id},
            )
            await session.commit()


async def _run(workspace: uuid.UUID, *, status: str = "succeeded") -> uuid.UUID:
    with workspace_scope(workspace):
        async with session_factory() as session:
            run = AgentRun(
                workspace_id=workspace,
                key="ui-quality-review",
                version="1.1.0",
                status=status,
                format="markdown",
                output=DELIVERED if status == "succeeded" else None,
                queued_at=datetime.now(UTC),
            )
            session.add(run)
            await session.commit()
            return run.id


async def test_tickets_drafted_from_a_deliverable_and_created_in_jira_once_accepted(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    atlassian: Atlassian,
    drafted: list[uuid.UUID],
) -> None:
    workspace = acme["acme"]
    jira = await _source(workspace, SourceKind.JIRA, {"projects": ["PAY"]})
    confluence = await _source(workspace, SourceKind.CONFLUENCE, {"spaces": ["ENG"]})
    run_id = await _run(workspace)
    _as(identity, acme, "member")
    ask = f"/api/v1/agent-runs/{run_id}/proposals"

    # Refused, said why: a project it does not read, a source of the wrong
    # kind, a run not finished.
    wrong = await client.post(ask, json={"kind": "issues", "source_id": str(jira), "target": "OPS"})
    assert (wrong.status_code, wrong.json()["error"]["details"][0]["message"]) == (
        422,
        "out_of_scope",
    )
    kind = await client.post(
        ask, json={"kind": "issues", "source_id": str(confluence), "target": "ENG"}
    )
    assert kind.json()["error"]["details"][0]["message"] == "wrong_source"
    # Never anything but a key: it goes into an address — even when the
    # source reads every project.
    every = await _source(workspace, SourceKind.JIRA, {})
    odd = await client.post(
        ask, json={"kind": "issues", "source_id": str(every), "target": "../../admin"}
    )
    assert (odd.status_code, odd.json()["error"]["details"][0]) == (
        422,
        {"field": "target", "message": "out_of_scope"},
    )
    waiting = await _run(workspace, status="running")
    unfinished = await client.post(
        f"/api/v1/agent-runs/{waiting}/proposals",
        json={"kind": "issues", "source_id": str(jira), "target": "PAY"},
    )
    assert unfinished.status_code == 409
    assert unfinished.json()["error"]["details"][0]["field"] == "run_id"
    assert drafted == []

    # Asked: drafting, queued.
    asked = await client.post(ask, json={"kind": "issues", "source_id": str(jira), "target": "pay"})
    assert asked.status_code == 202, asked.text
    proposal = asked.json()
    assert (proposal["status"], proposal["target"], proposal["items"]) == ("drafting", "PAY", [])
    assert drafted == [uuid.UUID(proposal["id"])]

    # Drafted from the deliverable, no tools.
    script = leka_gemini(gemini(json.dumps(ISSUES)))
    assert await draft(workspace, uuid.UUID(proposal["id"])) == {"status": "proposed"}
    material = json.loads(script.asked[0]["contents"][-1]["parts"][0]["text"])
    assert material["deliverable"] == DELIVERED and material["target"] == "PAY"
    assert "tools" not in script.asked[0]
    [read] = (await client.get("/api/v1/proposals", params={"run_id": str(run_id)})).json()
    assert (read["status"], read["title"], read["allowed"]) == (
        "proposed",
        "Corriger l'accueil",
        False,
    )
    first, _second = read["items"]
    assert (first["kind"], first["priority"], first["labels"]) == ("bug", "highest", ["accueil"])

    # Only who may approve decides; the source does not allow it yet.
    accept = f"/api/v1/proposals/{read['id']}/accept"
    assert (await client.post(accept, json={"items": [first["id"]]})).status_code == 403
    _as(identity, acme, "admin")
    off = await client.post(accept, json={"items": [first["id"]]})
    assert (off.status_code, off.json()["error"]["details"][0]["message"]) == (409, "issues_off")
    assert atlassian.writes() == []
    assert (await client.get(f"/api/v1/proposals/{read['id']}")).json()["status"] == "proposed"

    # Allowed, but Jira refuses the account: nothing sent, it stays
    # proposed, said why — to try again.
    await _allow(workspace, jira, "issues")
    atlassian.refuse_issues = True
    refused = await client.post(accept, json={"items": [first["id"]]})
    assert (refused.status_code, refused.json()["error"]["details"][0]["message"]) == (
        409,
        "not_allowed",
    )
    still = (await client.get(f"/api/v1/proposals/{read['id']}")).json()
    assert (still["status"], still["error"], still["items"][0]["error"]) == (
        "proposed",
        "not_allowed",
        "not_allowed",
    )

    # Then: the one chosen created, the other not sent.
    atlassian.refuse_issues = False
    done = await client.post(accept, json={"items": [first["id"]], "note": "go"})
    assert done.status_code == 200, done.text
    sent = done.json()
    assert (sent["status"], sent["note"]) == ("applied", "go")
    one, other = sent["items"]
    assert (one["key"], one["url"]) == ("PAY-24", "https://acme.atlassian.net/browse/PAY-24")
    assert (other["key"], other["url"]) == (None, None)
    # The one refused, then the one created.
    assert len(atlassian.writes()) == 2
    _, path, body = atlassian.writes()[-1]
    fields = body["fields"]
    assert path == "/rest/api/2/issue"
    assert (fields["project"], fields["issuetype"]) == ({"key": "PAY"}, {"id": "10004"})
    assert fields["summary"] == "Intercepter les erreurs réseau du compositeur"
    assert "h2. Contexte" in fields["description"] and "*réseau*" in fields["description"]
    assert fields["labels"] == ["leka", "accueil"]
    # Decided once.
    again = await client.post(accept, json={})
    assert again.status_code == 409

    # Another workspace sees nothing.
    _as(identity, acme, "other_admin")
    assert (await client.get(f"/api/v1/proposals/{read['id']}")).status_code == 404
    assert (await client.get("/api/v1/proposals", params={"run_id": str(run_id)})).json() == []


async def test_pages_drafted_from_a_deliverable_and_published_in_confluence(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    atlassian: Atlassian,
    drafted: list[uuid.UUID],
) -> None:
    workspace = acme["acme"]
    confluence = await _source(workspace, SourceKind.CONFLUENCE, {"spaces": ["ENG"], "pages": True})
    run_id = await _run(workspace)
    _as(identity, acme, "admin")
    asked = await client.post(
        f"/api/v1/agent-runs/{run_id}/proposals",
        json={"kind": "pages", "source_id": str(confluence), "target": "ENG"},
    )
    assert asked.status_code == 202, asked.text
    proposal_id = uuid.UUID(asked.json()["id"])
    both = {**PAGES, "pages": [*PAGES["pages"], {"title": "Déjà là", "body": "Texte."}]}
    leka_gemini(gemini(json.dumps(both)))
    assert await draft(workspace, proposal_id) == {"status": "proposed"}

    done = await client.post(f"/api/v1/proposals/{proposal_id}/accept", json={})
    assert done.status_code == 200, done.text
    sent = done.json()
    assert sent["status"] == "partly"
    published, taken = sent["items"]
    assert published["url"] == "https://acme.atlassian.net/wiki/spaces/ENG/pages/456/Accueil"
    assert (taken["url"], taken["error"]) == (None, "title_taken")
    page = atlassian.writes()[0][2]
    assert (page["spaceId"], page["status"], page["title"]) == (
        "98",
        "current",
        "Accueil — fonctionnement",
    )
    assert page["body"] == {
        "representation": "storage",
        "value": "<h1>Accueil</h1><p>Ce que fait l'écran.</p>",
    }

    # A rejected proposal is said rejected, with why.
    again = await client.post(
        f"/api/v1/agent-runs/{run_id}/proposals",
        json={"kind": "pages", "source_id": str(confluence), "target": "ENG"},
    )
    rejected_id = again.json()["id"]
    leka_gemini(gemini(json.dumps(PAGES)))
    await draft(workspace, uuid.UUID(rejected_id))
    rejected = await client.post(
        f"/api/v1/proposals/{rejected_id}/reject", json={"note": "Pas maintenant"}
    )
    assert (rejected.json()["status"], rejected.json()["note"]) == ("rejected", "Pas maintenant")
