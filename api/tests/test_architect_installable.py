"""The downloadable architect (2026-10-25): leka-architect, the same agent
on a customer's machine — its terminal, its MCP server, its prompt pack.

What these protect:
- The package: LEKA's own code, renamed — the same files, byte for byte —,
  its pyproject, its README, an .env.example without a secret, a Dockerfile,
  an MCP configuration for each client, the prompt pack written from the
  same instructions. Downloaded only by an organisation the agent is
  dedicated to; audited.
- End to end, unpacked as a customer would: `simulate` on a simulated
  Confluence export and a simulated OpenAI-compatible model — the four
  files, each section citing its pages; `tree`; `compare` against a
  reference; `render` of what a chat model wrote. Nothing called but the
  model configured.
- MCP over stdio: initialize, the four tools, the tree, the dossier written
  from the client's own model's JSON, the instructions as a prompt.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import threading
import uuid
import zipfile
from collections.abc import Iterator
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from leka.architect import package
from leka.capabilities import sync_catalogue
from leka.capabilities.dedicated import instruct
from leka.capabilities.registry import find
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

API = "/api/v1"
ARCHITECT = "application-architecture"
CORE = Path(package.__file__).resolve().parent
# An organisation's own instructions, as LEKA is given them — never a real
# one in the code (2026-10-25).
OWN = (
    "PROMPT SYSTÈME — AGENT « ARCHITECTE APPLICATIF » — consignes du client\n"
    "PRINCIPE ABSOLU : factuel, rien d'inventé.\n"
    "7.1 « Obtenir des espaces » -> « Obtenir les pages dans un espace ».\n"
    "□ Rien ne dépasse du cadre ⇒ PPTX + PDF livrés."
)
# What the model was told, call by call: (system, user).
TOLD: list[tuple[str, str]] = []

PAGES = [
    ("100", "Accueil", None, "<p>Le SI de facturation.</p>"),
    ("101", "Applications", "100", "<p>Billing API appelle Ledger.</p>"),
    ("102", "Billing API", "101", "<p>Composant applicatif.</p>"),
]


def _dossier(ids: list[str]) -> dict[str, Any]:
    return {
        "title": "Dossier d'architecture — Facturation",
        "sections": [
            {"key": "synthese", "summary": "La facturation.", "pages": ids[:1]},
            {"key": "application", "summary": "Billing API et Ledger.", "pages": ids[1:]},
        ],
        "elements": [
            {
                "id": "b",
                "layer": "application",
                "type": "Composant applicatif",
                "name": "Billing API",
                "pages": ids[1:],
            },
            {
                "id": "l",
                "layer": "application",
                "type": "Composant applicatif",
                "name": "Ledger",
                "pages": ids[1:2],
            },
        ],
        "relations": [
            {"source": "b", "target": "l", "type": "Flux", "label": "factures", "pages": ids[1:2]}
        ],
        "points": ["Qui exploite Ledger ?"],
    }


def _deck() -> dict[str, Any]:
    """A deck's content, as a model fills it from the analysis."""
    return {
        "parcours": "Facturation",
        "perimetre": "Périmètre Digital - Espace Client",
        "business": {
            "actor": "Client",
            "trigger": "Demande sa facture",
            "process_name": "Facturation",
            "channel": "Espace Client",
            "groupings": [
                {"letter": "A", "label": "Consultation", "steps": [{"label": "Ouvre ses factures"}]}
            ],
        },
        "processes": [
            {
                "letter": "A",
                "label": "Consultation",
                "front": "DIGITAL",
                "columns": [{"name": "Billing API"}, {"name": "Ledger"}],
                "bands": [
                    {
                        "title": "Lecture",
                        "lines": [
                            {
                                "calls": [
                                    {"column": "Billing API", "label": "GET /invoices"},
                                    {"column": "Ledger", "label": "lireFactures"},
                                ]
                            }
                        ],
                    }
                ],
            }
        ],
        "raci": [{"application": "Billing API", "contact": "Ada Lovelace", "statut": "Documenté"}],
        "sources": [{"source": "Espace ARCHI", "elements": "3 pages", "statut": "Consulté"}],
    }


def _xlsx(path: Path, rows: list[list[str]], sheet: str = "Annuaire global") -> None:
    """A workbook as Excel writes one: its sheets, its shared strings."""
    strings = sorted({cell for row in rows for cell in row})
    index = {text: n for n, text in enumerate(strings)}
    cells = "".join(
        f'<row r="{n}">'
        + "".join(
            f'<c r="{chr(65 + i)}{n}" t="s"><v>{index[cell]}</v></c>' for i, cell in enumerate(row)
        )
        + "</row>"
        for n, row in enumerate(rows, 1)
    )
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rels = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path, "w") as book:
        book.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{main}" xmlns:r="{rels}"><sheets>'
            f'<sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        book.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rels}/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        book.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{main}">'
            + "".join(f"<si><t>{escape(text)}</t></si>" for text in strings)
            + "</sst>",
        )
        book.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{main}"><sheetData>{cells}</sheetData></worksheet>',
        )


@pytest.fixture
def knowledge(tmp_path: Path) -> Path:
    """The knowledge files: a directory of contacts — its first row dates,
    its headers on the second, as the client's."""
    folder = tmp_path / "connaissances"
    folder.mkdir()
    _xlsx(
        folder / "annuaire.xlsx",
        [
            ["MAJ 01/09/2026"],
            ["Application", "Nom\\Prénom", "Mail contact"],
            ["Billing API", "Ada Lovelace", "ada@acme.example"],
            ["Payroll", "Bob Martin", "bob@acme.example"],
        ],
    )
    (tmp_path / "secret.txt").write_text("hors du dossier", encoding="utf-8")
    return folder


@pytest.fixture
def model() -> Iterator[tuple[str, list[str]]]:
    """An OpenAI-compatible model on this machine: it cites the pages it is
    shown. Answers its address, and every path it was asked."""
    asked: list[str] = []
    TOLD.clear()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            asked.append(self.path)
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            system = body["messages"][0]["content"]
            user = body["messages"][-1]["content"]
            TOLD.append((system, user))
            ids = re.findall(r"^\[([^\]]+)\]", user, re.MULTILINE)
            # The deck writer, the analysis of a journey, else the dossier.
            if "deck writer" in system:
                content = json.dumps(_deck())
            elif "Comment cela tourne ici" in system:
                content = (
                    "## Couche métier\nLe client consulte ses factures [101].\n"
                    "## RACI\nBilling API : Ada Lovelace."
                )
            else:
                content = json.dumps(_dossier(ids))
            said = json.dumps({"choices": [{"message": {"content": content}}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(said.encode())

        def log_message(self, *_: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1", asked
    server.shutdown()


@pytest.fixture
def unpacked(tmp_path: Path) -> Path:
    """The zip LEKA hands out, unpacked: its folder."""
    with zipfile.ZipFile(io.BytesIO(package.build_zip(OWN))) as zipped:
        zipped.extractall(tmp_path / "download")
    return tmp_path / "download" / "leka-architect"


@pytest.fixture
def export(tmp_path: Path) -> Path:
    """A Confluence space exported to disk (the copy tool's format)."""
    folder = tmp_path / "export"
    for pid, title, parent, body in PAGES:
        here = folder / "pages" / pid
        here.mkdir(parents=True)
        (here / "page.json").write_text(
            json.dumps({"id": pid, "title": title, "parent_id": parent})
        )
        (here / "body.xml").write_text(body, encoding="utf-8")
    (folder / "space.json").write_text(
        json.dumps(
            {"key": "ARCHI", "name": "Architecture", "site": "https://acme.atlassian.net/wiki"}
        )
    )
    return folder


def _env(unpacked: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ARCHITECT_", "CONFLUENCE_"))}
    return {**env, "PYTHONPATH": str(unpacked), "HOME": str(unpacked), **extra}


def _cli(unpacked: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - this interpreter, the package's own module
        [sys.executable, "-m", "leka_architect", *args],
        cwd=unpacked.parent,
        env=_env(unpacked, **env),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_the_package_is_leka_s_own_code_and_what_ships_with_it(unpacked: Path) -> None:
    for source in CORE.glob("*.py"):
        assert (unpacked / "leka_architect" / source.name).read_bytes() == source.read_bytes(), (
            source.name
        )
    for shipped in (
        "pyproject.toml",
        "README.md",
        ".env.example",
        "Dockerfile",
        "mcp/vscode-copilot.json",
        "mcp/claude-desktop.json",
        "mcp/cursor.json",
        "mcp/docker.json",
        "mcp/claude-code.txt",
        "prompts/instructions-systeme.md",
        "prompts/modele-livrable.md",
        "prompts/mode-emploi.md",
        "prompts/consignes-architecte.md",
        "mcp/vscode-copilot-windows.json",
        "leka_architect/deck/__init__.py",
    ):
        assert (unpacked / shipped).is_file(), shipped
    pyproject = (unpacked / "pyproject.toml").read_text()
    assert 'requires-python = ">=3.10"' in pyproject and '"leka_architect.deck"' in pyproject
    # LEKA's deck renderer, the same files, their imports made relative.
    for name in package.DECK_FILES:
        shipped_deck = (unpacked / "leka_architect" / "deck" / name).read_text()
        assert shipped_deck == package.relative((package.DECK / name).read_text()), name
        assert "from leka." not in shipped_deck, name
    # The organisation's own instructions: what it follows, everywhere.
    assert (unpacked / "leka_architect" / "consignes.md").read_text() == OWN
    assert (unpacked / "prompts/consignes-architecte.md").read_text().strip() == OWN
    prompt = (unpacked / "copilot/.github/prompts/architecte-applicatif.prompt.md").read_text()
    assert prompt.startswith("---\nmode: agent\n") and OWN in prompt
    assert "`list_confluence_spaces`" in prompt and "`generate_architecture_deck`" in prompt
    windows = json.loads((unpacked / "mcp/vscode-copilot-windows.json").read_text())
    assert windows["servers"]["leka-architect"]["command"] == (
        "${workspaceFolder}\\.venv\\Scripts\\leka-architect.exe"
    )
    # No secret in it: the example's keys are empty.
    for line in (unpacked / ".env.example").read_text().splitlines():
        if re.match(r"^[A-Z_]*(TOKEN|KEY)=", line):
            assert line.endswith("="), line
    copilot = json.loads((unpacked / "mcp/vscode-copilot.json").read_text())
    assert copilot["servers"]["leka-architect"]["args"] == ["mcp"]
    assert (
        copilot["servers"]["leka-architect"]["command"]
        == "${workspaceFolder}/.venv/bin/leka-architect"
    )
    pack = (unpacked / "prompts/instructions-systeme.md").read_text()
    assert "PRINCIPE ABSOLU" in pack and "Couche technologie" in pack
    readme = (unpacked / "README.md").read_text()
    assert "Rien ne passe par LEKA" in readme and "leka-architect simulate" in readme
    # Installed on each system, its commands said.
    for said in (
        "### Windows (PowerShell)",
        "### macOS (Terminal)",
        "### Linux",
        "leka-architect deck",
    ):
        assert said in readme, said
    # Without instructions of its own: none of its organisation's.
    with zipfile.ZipFile(io.BytesIO(package.build_zip())) as zipped:
        assert "leka-architect/leka_architect/consignes.md" not in zipped.namelist()


def test_simulate_tree_compare_render_on_a_simulated_confluence_and_model(
    unpacked: Path, export: Path, model: tuple[str, list[str]], tmp_path: Path
) -> None:
    address, asked = model
    llm = {
        "ARCHITECT_LLM_PROVIDER": "openai",
        "ARCHITECT_LLM_MODEL": "local-model",
        "ARCHITECT_LLM_BASE_URL": address,
        "ARCHITECT_CONFLUENCE_EXPORT": str(export),
    }
    shown = _cli(unpacked, "tree", "--space", "ARCHI", **llm)
    assert shown.returncode == 0, shown.stderr
    assert "3 pages, profondeur 3" in shown.stdout and "Billing API [102]" in shown.stdout

    out = tmp_path / "rapport"
    done = _cli(
        unpacked,
        "simulate",
        "--space",
        "ARCHI",
        "--focus",
        "Facturation",
        "--output",
        str(out),
        **llm,
    )
    assert done.returncode == 0, done.stderr
    assert "3 pages lues" in done.stderr and "openai · local-model" in done.stderr
    for name in ("md", "pdf", "docx", "json"):
        assert (out / f"dossier-architecture.{name}").is_file(), name
    said = (out / "dossier-architecture.md").read_text()
    assert "## 3. Couche application" in said
    assert "[Billing API](https://acme.atlassian.net/wiki/pages/viewpage.action?pageId=102)" in said
    # Only the model configured was called.
    assert asked == ["/v1/chat/completions"]

    reference = tmp_path / "reference.md"
    reference.write_text(
        "# Ref\n## Couche métier\n## Couche applicative\nBilling API.\n", encoding="utf-8"
    )
    against = _cli(
        unpacked,
        "compare",
        "--dossier",
        str(out),
        "--reference",
        str(reference),
        "--output",
        str(out),
    )
    assert against.returncode == 0, against.stderr
    assert "couverte des deux côtés" in (out / "comparaison.md").read_text()

    # A chat model's answer, after the prompt pack: rendered, its pages checked.
    answer = tmp_path / "reponse.json"
    answer.write_text(json.dumps(_dossier(["100", "999"])), encoding="utf-8")
    drawn = _cli(
        unpacked, "render", "--dossier", str(answer), "--output", str(tmp_path / "rendu"), **llm
    )
    assert drawn.returncode == 0, drawn.stderr
    rendered = (tmp_path / "rendu" / "dossier-architecture.md").read_text()
    assert "page 999 citée mais non lue" in rendered

    refused = _cli(
        unpacked,
        "simulate",
        "--space",
        "ARCHI",
        "--output",
        str(out),
        ARCHITECT_LLM_PROVIDER="openai",
    )
    assert refused.returncode == 1 and "ARCHITECT_LLM_MODEL" in refused.stderr


def test_the_deck_of_a_journey_on_its_own_instructions(
    unpacked: Path, export: Path, knowledge: Path, model: tuple[str, list[str]], tmp_path: Path
) -> None:
    address, asked = model
    out = tmp_path / "deck"
    done = _cli(
        unpacked,
        "deck",
        "--space",
        "ARCHI",
        "--parcours",
        "Facturation",
        "--perimetre",
        "Digital - Espace Client",
        "--connaissances",
        str(knowledge),
        "--output",
        str(out),
        ARCHITECT_LLM_PROVIDER="openai",
        ARCHITECT_LLM_MODEL="local-model",
        ARCHITECT_LLM_BASE_URL=address,
        ARCHITECT_CONFLUENCE_EXPORT=str(export),
    )
    assert done.returncode == 0, done.stderr
    assert "3 pages lues" in done.stderr and "Connaissances : 1 fichiers lus" in done.stderr
    pptx = (out / "architecture-facturation.pptx").read_bytes()
    assert pptx[:2] == b"PK" and b"ppt/slides/slide1.xml" in pptx
    assert (out / "architecture-facturation.pdf").read_bytes()[:4] == b"%PDF"
    assert "Ada Lovelace" in (out / "analyse.md").read_text()
    # Two calls: the analysis, then the deck — both on the organisation's
    # own instructions; the pages and the directory's row naming a brick
    # given to the analysis, not another's.
    assert asked == ["/v1/chat/completions", "/v1/chat/completions"]
    (analysis_system, analysis_user), (deck_system, _) = TOLD
    assert analysis_system.startswith(OWN) and "Comment cela tourne ici" in analysis_system
    assert "[102]" in analysis_user and "Ada Lovelace" in analysis_user
    assert "Payroll" not in analysis_user
    assert "deck writer" in deck_system and OWN in deck_system

    # Its content, drawn again — as one any model wrote after the prompt pack.
    again = _cli(
        unpacked,
        "render-deck",
        "--deck",
        str(out / "architecture-facturation.json"),
        "--output",
        str(tmp_path / "again"),
    )
    assert again.returncode == 0, again.stderr
    assert (tmp_path / "again" / "architecture-facturation.pptx").is_file()


def test_the_mcp_server_over_stdio(
    unpacked: Path, export: Path, knowledge: Path, tmp_path: Path
) -> None:
    out = tmp_path / "mcp-rapport"
    deck_out = tmp_path / "mcp-deck"
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_confluence_tree", "arguments": {"space": "ARCHI"}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "analyze_architecture", "arguments": {"space": "ARCHI"}},
        },
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "generate_architecture_document",
                "arguments": {
                    "space": "ARCHI",
                    "output_dir": str(out),
                    "dossier": _dossier(["100", "102"]),
                },
            },
        },
        {"jsonrpc": "2.0", "id": 6, "method": "prompts/get", "params": {"name": "architecte"}},
        {"jsonrpc": "2.0", "id": 7, "method": "nope"},
        *(
            {
                "jsonrpc": "2.0",
                "id": n,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
            for n, (name, arguments) in enumerate(
                [
                    ("search_confluence_pages", {"space": "ARCHI", "title": "billing"}),
                    ("list_knowledge_files", {}),
                    ("read_knowledge_file", {"file": "annuaire.xlsx", "contains": "billing"}),
                    ("read_knowledge_file", {"file": "../secret.txt"}),
                    (
                        "generate_architecture_deck",
                        {
                            "parcours": "Facturation",
                            "perimetre": "Digital",
                            "deck": _deck(),
                            "output_dir": str(deck_out),
                        },
                    ),
                    ("list_confluence_spaces", {}),
                ],
                start=8,
            )
        ),
    ]
    served = subprocess.run(
        [sys.executable, "-m", "leka_architect", "mcp"],
        input="\n".join(json.dumps(m) for m in messages) + "\n",
        env=_env(
            unpacked,
            ARCHITECT_CONFLUENCE_EXPORT=str(export),
            ARCHITECT_KNOWLEDGE_DIR=str(knowledge),
            # A pipe on Windows: its streams cp1252 — the server speaks UTF-8.
            PYTHONIOENCODING="cp1252",
        ),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert served.returncode == 0, served.stderr
    answers = {a["id"]: a for a in map(json.loads, served.stdout.splitlines())}
    assert set(answers) == set(range(1, 14))  # the notification answered nothing
    assert answers[1]["result"]["protocolVersion"] == "2025-06-18"
    assert answers[1]["result"]["serverInfo"]["name"] == "leka-architect"
    assert [t["name"] for t in answers[2]["result"]["tools"]] == [
        "list_confluence_spaces",
        "search_confluence_pages",
        "list_knowledge_files",
        "read_knowledge_file",
        "generate_architecture_deck",
        "list_confluence_tree",
        "read_confluence_page",
        "analyze_architecture",
        "generate_architecture_document",
    ]
    tree = answers[3]["result"]["content"][0]["text"]
    assert "3 pages, profondeur 3" in tree and "Applications [101]" in tree
    # No model configured: the client's own model is given the pages and the instructions.
    analysed = answers[4]["result"]["content"][0]["text"]
    assert "Aucun modèle n'est configuré ici" in analysed and "[102]" in analysed
    assert answers[5]["result"]["isError"] is False
    assert (out / "dossier-architecture.docx").is_file()
    # Its organisation's instructions, its tools named, the deck's schema.
    told = answers[6]["result"]["messages"][0]["content"]["text"]
    assert told.startswith(OWN) and "`search_confluence_pages`" in told
    assert "Le schéma de `deck`" in told and "ProcessView" in told
    assert answers[7]["error"]["code"] == -32601

    def text(n: int) -> str:
        return str(answers[n]["result"]["content"][0]["text"])

    assert "Billing API [102]" in text(8) and "Applications" not in text(8)
    assert "annuaire.xlsx" in text(9)
    # The directory's row naming the brick, its headers kept — not another's.
    assert "3 | Billing API | Ada Lovelace | ada@acme.example" in text(10)
    assert "2 | Application" in text(10) and "Payroll" not in text(10)
    # Nothing outside its folder.
    assert answers[11]["result"]["isError"] is True and "secret" not in text(11).replace(
        "../secret.txt", ""
    )
    assert answers[12]["result"]["isError"] is False, text(12)
    assert (deck_out / "architecture-facturation.pptx").read_bytes()[:2] == b"PK"
    assert (deck_out / "architecture-facturation.pdf").read_bytes()[:4] == b"%PDF"
    assert "un seul espace" in text(13)


async def test_downloaded_only_where_it_is_dedicated_audited(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    await sync_catalogue()
    _as(identity, acme, "member")
    found = await client.get(f"{API}/capabilities/{ARCHITECT}/package")
    assert found.status_code == 200, found.text
    assert found.headers["content-type"] == "application/zip"
    assert 'filename="leka-architect-' in found.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(found.content)) as zipped:
        assert "leka-architect/leka_architect/cli.py" in zipped.namelist()
        # No instructions of its own: LEKA's, the registry's.
        told = zipped.read("leka-architect/leka_architect/consignes.md").decode()
    assert told == find(ARCHITECT).instructions  # type: ignore[union-attr]
    # Its own, given by LEKA: those, in what it downloads — its own only.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            assert await instruct(session, acme["acme"], ARCHITECT, OWN)
            await session.commit()
    found = await client.get(f"{API}/capabilities/{ARCHITECT}/package")
    with zipfile.ZipFile(io.BytesIO(found.content)) as zipped:
        assert zipped.read("leka-architect/leka_architect/consignes.md").decode() == OWN
        names = zipped.namelist()
    assert "leka-architect/copilot/.github/prompts/architecte-applicatif.prompt.md" in names
    # Another organisation's: as if it did not exist.
    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/capabilities/{ARCHITECT}/package")).status_code == 404
    # An agent without a package: none.
    _as(identity, acme, "member")
    assert (await client.get(f"{API}/capabilities/code-review/package")).status_code == 404
    _as(identity, acme, "admin")
    trail = (await client.get(f"{API}/governance/audit", params={"category": "ai"})).json()
    downloaded = [e for e in trail["events"] if e["action"] == "agent.package_downloaded"]
    assert len(downloaded) == 2 and downloaded[0]["target_label"] == ARCHITECT
