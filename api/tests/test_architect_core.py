"""The application architect's core (leka/architect, 2026-10-25) — the same
files LEKA runs and the downloadable agent ships.

What these protect:
- A space's tree as Confluence holds it: a page and everything under it,
  its depth, where each page sits; read by the API (Cloud), or from an
  export on disk; the token never said.
- The dossier kept to what holds: ArchiMate's types, relations between
  elements it has, pages it was given — what is dropped said; an element
  nothing cites, to confirm.
- The analysis: every page in one call, or batch by batch — the same
  element named twice kept once, its pages together — then written whole;
  an unreadable answer asked once again; awaited, the same.
- The dossier written: Markdown, Word and PDF, every section, its evidence
  linked.
- Against a reference: section by section, the elements it names too.
- The models: Anthropic, OpenAI-compatible, Azure OpenAI — asked as each
  wants, refused said without the key.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import urllib.request
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from leka.architect import (
    LLM,
    SECTIONS,
    Budget,
    Client,
    ConfluenceError,
    DossierError,
    LLMError,
    Page,
    Site,
    Tree,
    analyse,
    analyse_async,
    compare,
    docx,
    dossier_of,
    from_env,
    markdown,
    merge,
    pdf,
    problems,
    read_folder,
    read_space,
    reference,
    text_of,
)

TOKEN = "atlassian-secret-token-1234567890"


def _pages() -> list[Page]:
    return [
        Page("1", "Accueil", "Le SI de facturation.", "https://x/1"),
        Page("2", "Applications", "Billing API appelle Ledger.", "https://x/2", "1"),
        Page("3", "Billing API", "Composant applicatif. Expose /invoices.", "https://x/3", "2"),
        Page("4", "Infrastructure", "Billing API tourne sur Kubernetes.", "https://x/4", "1"),
        Page("5", "Ailleurs", "Une autre page.", "https://x/5"),
    ]


# ── the tree ────────────────────────────────────────────────────────────────


def test_a_space_s_tree_as_confluence_holds_it() -> None:
    tree = Tree(_pages())
    assert [p.id for p in tree.roots] == ["1", "5"]
    assert [p.id for p in tree.under("2")] == ["2", "3"]
    assert [p.id for p in tree.under(None)] == ["1", "2", "3", "4", "5"]
    assert tree.depth() == 3
    assert tree.depth("2") == 2
    assert tree.path("3") == ["Accueil", "Applications", "Billing API"]
    # A loop in what was read never loops the reading.
    looped = Tree([Page("a", "A", parent_id="b"), Page("b", "B", parent_id="a")])
    assert len(looped.under(None)) == 0 or len(looped.under("a")) == 2


def test_a_page_s_storage_format_read_as_text() -> None:
    said = text_of(
        "<h2>Flux</h2><p>Billing&nbsp;API &amp; Ledger</p>"
        "<table><tr><th>De</th><th>Vers</th></tr><tr><td>A</td><td>B</td></tr></table>"
        '<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[GET /invoices]]>'
        "</ac:plain-text-body></ac:structured-macro>"
    )
    assert "## Flux" in said
    assert "Billing API & Ledger" in said
    assert "A | B |" in said
    assert "GET /invoices" in said


# ── Confluence, read ────────────────────────────────────────────────────────


class FakeConfluence:
    """Confluence's REST API v1, as Cloud answers it."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.status = 200

    def __call__(self, request: urllib.request.Request) -> tuple[int, Mapping[str, str], bytes]:
        url = request.full_url
        self.asked.append(url)
        assert request.get_header("Authorization", "").startswith("Basic ")
        if self.status != 200:
            return self.status, {}, b"{}"

        def page(pid: str, title: str, parents: list[str], body: str) -> dict[str, Any]:
            return {
                "id": pid,
                "title": title,
                "ancestors": [{"id": p} for p in parents],
                "version": {"when": "2026-10-20T10:00:00.000Z"},
                "body": {"storage": {"value": body}},
            }

        if "/rest/api/space/ARCHI" in url:
            return 200, {}, json.dumps({"key": "ARCHI", "name": "Architecture"}).encode()
        if "/rest/api/content/2?" in url:
            return 200, {}, json.dumps(page("2", "Applications", ["1"], "<p>Apps</p>")).encode()
        if "/rest/api/content/2/descendant/page" in url:
            found = [page("3", "Billing API", ["1", "2"], "<p>Billing</p>")]
            return 200, {}, json.dumps({"results": found}).encode()
        if "/rest/api/content?" in url:
            found = [
                page("1", "Accueil", [], "<p>Home</p>"),
                page("2", "Applications", ["1"], "<p>Apps</p>"),
                page("3", "Billing API", ["1", "2"], "<p>Billing</p>"),
            ]
            return 200, {}, json.dumps({"results": found}).encode()
        return 404, {}, b""


def test_a_space_read_by_its_api_its_tree_kept_its_token_never_said() -> None:
    fake = FakeConfluence()
    client = Client(Site("https://acme.atlassian.net", "a@acme.example", TOKEN), fake, pause=0)
    pages = read_space(client, "ARCHI")
    assert [(p.id, p.parent_id) for p in pages] == [("1", None), ("2", "1"), ("3", "2")]
    assert pages[2].url == "https://acme.atlassian.net/wiki/pages/viewpage.action?pageId=3"
    assert pages[2].text == "Billing"
    assert pages[0].space == "ARCHI" and pages[0].updated_at.startswith("2026-10-20")
    # A page and everything under it: the root on top.
    under = read_space(client, "ARCHI", root="2")
    assert [(p.id, p.parent_id) for p in under] == [("2", None), ("3", "2")]
    fake.status = 401
    with pytest.raises(ConfluenceError) as refused:
        read_space(client, "ARCHI")
    assert "e-mail" in str(refused.value) and TOKEN not in str(refused.value)
    with pytest.raises(ConfluenceError):
        Client(Site("http://acme.example", token=TOKEN))


def test_a_space_read_from_an_export_or_from_files(tmp_path: Path) -> None:
    export = tmp_path / "export"
    for pid, title, parent in (("1", "Accueil", None), ("2", "Billing API", "1")):
        folder = export / "pages" / pid
        folder.mkdir(parents=True)
        (folder / "page.json").write_text(
            json.dumps({"id": pid, "title": title, "parent_id": parent}), encoding="utf-8"
        )
        (folder / "body.xml").write_text(f"<p>{title} décrit.</p>", encoding="utf-8")
    (export / "space.json").write_text(
        json.dumps({"key": "ARCHI", "name": "Archi", "site": "https://acme.atlassian.net/wiki"}),
        encoding="utf-8",
    )
    pages = read_folder(export)
    assert [(p.id, p.parent_id, p.text) for p in pages] == [
        ("1", None, "Accueil décrit."),
        ("2", "1", "Billing API décrit."),
    ]
    assert pages[1].url.endswith("viewpage.action?pageId=2")
    files = tmp_path / "files"
    (files / "Applications").mkdir(parents=True)
    (files / "Applications.md").write_text("# Les applications\nTout.", encoding="utf-8")
    (files / "Applications" / "Billing.md").write_text("Billing.", encoding="utf-8")
    found = {p.title: p for p in read_folder(files)}
    assert found["Billing"].parent_id == found["Les applications"].id


# ── the dossier ─────────────────────────────────────────────────────────────


def _answer(ids: list[str], *, prefix: str = "") -> dict[str, Any]:
    """What a model answers, citing these pages."""
    first, rest = ids[0], ids[1:] or ids
    return {
        "title": "Dossier Facturation",
        "sections": [
            {"key": key, "summary": f"{prefix}{title} lue.", "pages": [first]}
            for key, title in SECTIONS
        ],
        "elements": [
            {
                "id": "b",
                "layer": "application",
                "type": "Composant applicatif",
                "name": "Billing API",
                "pages": rest,
            },
            {
                "id": "l",
                "layer": "application",
                "type": "Composant applicatif",
                "name": "Ledger",
                "pages": [first],
            },
            {
                "id": "k",
                "layer": "technologie",
                "type": "Nœud",
                "name": "Kubernetes",
                "pages": rest,
            },
        ],
        "relations": [
            {"source": "b", "target": "l", "type": "Flux", "label": "écritures", "pages": rest}
        ],
        "points": ["Qui exploite Ledger ?"],
    }


def test_the_dossier_kept_to_what_holds_what_is_dropped_said() -> None:
    pages = _pages()
    raw = _answer(["1", "3"])
    raw["elements"] += [
        {
            "id": "x",
            "layer": "application",
            "type": "Microservice",
            "name": "Hors type",
            "pages": ["3"],
        },
        {"id": "y", "layer": "metier", "type": "Acteur métier", "name": "Client", "pages": ["99"]},
    ]
    raw["relations"].append({"source": "b", "target": "ghost", "type": "Flux"})
    dossier = dossier_of(json.dumps(raw), pages, scope="Espace ARCHI")
    assert [e.name for e in dossier.elements] == ["Billing API", "Ledger", "Kubernetes", "Client"]
    client = dossier.element("y")
    assert client is not None and client.to_confirm and client.evidence == ()
    billing = dossier.element("b")
    assert billing is not None and [e.title for e in billing.evidence] == ["Billing API"]
    assert len(dossier.relations) == 1
    assert any("Microservice" in d for d in dossier.dropped)
    assert any("99" in d for d in dossier.dropped)
    assert any("ghost" in d for d in dossier.dropped)
    assert problems(dossier) == ["élément sans preuve : Client"]
    with pytest.raises(DossierError):
        dossier_of("pas de JSON ici", pages, scope="x")
    # Fenced, as models often answer.
    fenced = dossier_of(
        "Voici :\n```json\n" + json.dumps(_answer(["1"])) + "\n```", pages, scope="x"
    )
    assert fenced.title == "Dossier Facturation"


# ── the analysis ────────────────────────────────────────────────────────────


class Model:
    """A model that cites the pages it was shown."""

    def __init__(self, garbled: int = 0) -> None:
        self.calls: list[str] = []
        self.garbled = garbled

    def __call__(self, system: str, user: str) -> str:
        assert "PRINCIPE ABSOLU" in system
        self.calls.append(user)
        if self.garbled:
            self.garbled -= 1
            return "désolé"
        if "Écris le dossier final" in user:
            merged = json.loads(user[user.index("{") :])
            return json.dumps(
                {
                    "title": "Dossier Facturation",
                    "sections": [
                        {"key": s["key"], "summary": " ".join(s["summaries"]), "pages": s["pages"]}
                        for s in merged["sections"]
                    ],
                    "points": ["Qui exploite Ledger ?"],
                }
            )
        ids = re.findall(r"^\[([^\]]+)\]", user, re.MULTILINE)
        return json.dumps(_answer(ids, prefix=f"lot {len(self.calls)} : "))


def test_every_page_in_one_call_when_they_fit() -> None:
    model = Model()
    dossier = analyse(model, _pages(), scope="Espace ARCHI", focus="Facturation")
    assert len(model.calls) == 1
    assert "Sujet à documenter en priorité : Facturation" in model.calls[0]
    assert "[3] Accueil › Applications › Billing API" in model.calls[0]  # noqa: RUF001
    assert [s.key for s in dossier.sections] == [key for key, _ in SECTIONS]
    assert dossier.pages_read and all(e.url for e in dossier.pages_read)
    assert problems(dossier) == []


def test_batch_by_batch_then_written_whole_the_same_element_kept_once() -> None:
    model = Model()
    said: list[str] = []
    dossier = analyse(
        model,
        _pages(),
        scope="Espace ARCHI",
        budget=Budget(page_chars=200, call_chars=150),
        said=lambda step, detail: said.append(step),
    )
    # One call per batch, then the synthesis.
    assert len(model.calls) >= 3 and "Écris le dossier final" in model.calls[-1]
    assert said[0] == "pages" and "batch" in said
    names = [e.name for e in dossier.elements]
    assert names.count("Billing API") == 1
    billing = next(e for e in dossier.elements if e.name == "Billing API")
    assert len(billing.evidence) > 1
    assert dossier.points == ["Qui exploite Ledger ?"]
    merged = merge([_answer(["1"]), _answer(["2"])])
    assert len(merged["elements"]) == 3 and len(merged["relations"]) == 1


def test_an_unreadable_answer_asked_once_again_awaited_the_same() -> None:
    model = Model(garbled=1)
    dossier = analyse(model, _pages(), scope="Espace ARCHI")
    assert len(model.calls) == 2 and "n'a pas pu être lue" in model.calls[1]
    assert dossier.elements

    async def ask(system: str, user: str) -> str:
        return Model()(system, user)

    waited = asyncio.run(analyse_async(ask, _pages(), scope="Espace ARCHI"))
    assert [e.name for e in waited.elements] == [e.name for e in dossier.elements]
    with pytest.raises(DossierError):
        analyse(Model(garbled=2), _pages(), scope="x")


# ── written ─────────────────────────────────────────────────────────────────


def test_the_dossier_written_markdown_word_pdf_every_section_its_evidence() -> None:
    dossier = analyse(Model(), _pages(), scope="Espace ARCHI")
    said = markdown(dossier)
    for n, (_, title) in enumerate(SECTIONS, 1):
        assert f"## {n}. {title}" in said
    assert "| Composant applicatif | Billing API |" in said
    assert "[Billing API](https://x/3)" in said
    assert "| Billing API | Flux | Ledger | écritures |" in said
    assert "1. Qui exploite Ledger ?" in said
    assert "## Pages consultées" in said

    word = zipfile.ZipFile(io.BytesIO(docx(dossier)))
    document = word.read("word/document.xml").decode()
    assert "Couche application" in document and "Billing API" in document
    assert 'w:pStyle w:val="Heading1"' in document
    assert "https://x/3" in word.read("word/_rels/document.xml.rels").decode()

    drawn = pdf(dossier)
    assert drawn.startswith(b"%PDF") and len(drawn) > 2000


def test_against_a_reference_section_by_section(tmp_path: Path) -> None:
    dossier = analyse(Model(), _pages(), scope="Espace ARCHI")
    ref = tmp_path / "reference.md"
    ref.write_text(
        "# Architecture - Parcours Facturation\n## Couche métier\nTexte.\n"
        "## Règles de gestion\n## Couche applicative\nBilling API et Ledger.\n"
        "## Contacts et responsabilités (RACI)\n## Annexe libre\n",
        encoding="utf-8",
    )
    found = compare(dossier, reference(ref))
    rows = {row.key: row for row in found.rows}
    assert rows["metier"].status == "couverte des deux côtés"
    assert rows["application"].theirs == ["Couche applicative"]
    assert rows["technologie"].status == "en plus chez LEKA"
    assert dict(found.others)["Règles de gestion"] == ["Règles de gestion"]
    assert "Annexe libre" in found.unmatched
    assert found.found == ["Billing API", "Ledger"] and found.absent == ["Kubernetes"]
    assert found.coverage == 100


# ── the models ──────────────────────────────────────────────────────────────


class Poster:
    def __init__(self, *answers: tuple[int, dict[str, Any]]) -> None:
        self.answers = list(answers)
        self.sent: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    def __call__(self, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        self.sent.append((url, headers, json.loads(body)))
        status, said = self.answers.pop(0)
        return status, json.dumps(said).encode()


def test_claude_asked_as_anthropic_wants() -> None:
    post = Poster((429, {}), (200, {"content": [{"type": "text", "text": "{}"}]}))
    model = LLM("anthropic", "claude-sonnet-5", api_key="sk-ant-secret", post=post, pause=0)
    assert model("règles", "pages") == "{}"
    url, headers, body = post.sent[-1]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "sk-ant-secret"
    assert (body["system"], body["messages"]) == ("règles", [{"role": "user", "content": "pages"}])
    assert len(post.sent) == 2  # 429: asked again


def test_an_openai_compatible_model_and_azure() -> None:
    post = Poster((200, {"choices": [{"message": {"content": "ok"}}]}))
    local = LLM("openai", "mistral-large", base_url="http://localhost:11434/v1", post=post)
    assert local("s", "u") == "ok"
    url, headers, body = post.sent[0]
    assert url == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in headers and body["model"] == "mistral-large"
    assert body["messages"][0] == {"role": "system", "content": "s"}

    post = Poster((401, {"error": "bad key"}))
    azure = LLM(
        "azure",
        "architecte-gpt",
        api_key="azure-secret",
        base_url="https://client.openai.azure.com",
        api_version="2024-10-21",
        post=post,
    )
    with pytest.raises(LLMError) as refused:
        azure("s", "u")
    url, headers, _ = post.sent[0]
    assert url == (
        "https://client.openai.azure.com/openai/deployments/architecte-gpt/chat/completions"
        "?api-version=2024-10-21"
    )
    assert headers["api-key"] == "azure-secret"
    assert "azure-secret" not in str(refused.value)
    with pytest.raises(LLMError, match="ARCHITECT_LLM_MODEL"):
        from_env({"ARCHITECT_LLM_PROVIDER": "openai"})
    assert (
        from_env(
            {
                "ARCHITECT_LLM_PROVIDER": "anthropic",
                "ARCHITECT_LLM_MODEL": "m",
                "ARCHITECT_LLM_API_KEY": "k",
            }
        ).said
        == "anthropic · m"
    )
