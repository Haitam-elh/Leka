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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from leka.architect import package
from leka.capabilities import sync_catalogue
from tests.conftest import FakeIdentity
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

API = "/api/v1"
ARCHITECT = "application-architecture"
CORE = Path(package.__file__).resolve().parent
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


@pytest.fixture
def model() -> Iterator[tuple[str, list[str]]]:
    """An OpenAI-compatible model on this machine: it cites the pages it is
    shown. Answers its address, and every path it was asked."""
    asked: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            asked.append(self.path)
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            user = body["messages"][-1]["content"]
            ids = re.findall(r"^\[([^\]]+)\]", user, re.MULTILINE)
            said = json.dumps({"choices": [{"message": {"content": json.dumps(_dossier(ids))}}]})
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
    with zipfile.ZipFile(io.BytesIO(package.build_zip())) as zipped:
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
    ):
        assert (unpacked / shipped).is_file(), shipped
    assert 'requires-python = ">=3.9"' in (unpacked / "pyproject.toml").read_text()
    # No secret in it: the example's keys are empty.
    for line in (unpacked / ".env.example").read_text().splitlines():
        if re.match(r"^[A-Z_]*(TOKEN|KEY)=", line):
            assert line.endswith("="), line
    copilot = json.loads((unpacked / "mcp/vscode-copilot.json").read_text())
    assert copilot["servers"]["leka-architect"]["args"] == ["mcp"]
    pack = (unpacked / "prompts/instructions-systeme.md").read_text()
    assert "PRINCIPE ABSOLU" in pack and "Couche technologie" in pack
    readme = (unpacked / "README.md").read_text()
    assert "Rien ne passe par LEKA" in readme and "leka-architect simulate" in readme


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


def test_the_mcp_server_over_stdio(unpacked: Path, export: Path, tmp_path: Path) -> None:
    out = tmp_path / "mcp-rapport"
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
    ]
    served = subprocess.run(
        [sys.executable, "-m", "leka_architect", "mcp"],
        input="\n".join(json.dumps(m) for m in messages) + "\n",
        env=_env(unpacked, ARCHITECT_CONFLUENCE_EXPORT=str(export)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert served.returncode == 0, served.stderr
    answers = {a["id"]: a for a in map(json.loads, served.stdout.splitlines())}
    assert set(answers) == {1, 2, 3, 4, 5, 6, 7}  # the notification answered nothing
    assert answers[1]["result"]["protocolVersion"] == "2025-06-18"
    assert answers[1]["result"]["serverInfo"]["name"] == "leka-architect"
    assert [t["name"] for t in answers[2]["result"]["tools"]] == [
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
    assert "PRINCIPE ABSOLU" in answers[6]["result"]["messages"][0]["content"]["text"]
    assert answers[7]["error"]["code"] == -32601


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
    # Another organisation's: as if it did not exist.
    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/capabilities/{ARCHITECT}/package")).status_code == 404
    # An agent without a package: none.
    _as(identity, acme, "member")
    assert (await client.get(f"{API}/capabilities/code-review/package")).status_code == 404
    _as(identity, acme, "admin")
    trail = (await client.get(f"{API}/governance/audit", params={"category": "ai"})).json()
    downloaded = [e for e in trail["events"] if e["action"] == "agent.package_downloaded"]
    assert len(downloaded) == 1 and downloaded[0]["target_label"] == ARCHITECT
