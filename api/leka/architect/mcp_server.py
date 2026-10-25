"""The architect as an MCP server (Model Context Protocol, over stdio) — for
GitHub Copilot in VS Code (agent mode), Claude Desktop, Claude Code, Cursor
or any MCP client. One JSON-RPC 2.0 message per line, in and out.

Its tools:

    list_confluence_tree            the pages of a space, or under a page
    read_confluence_page            one page's text, title and link
    analyze_architecture            the dossier, written by the configured
                                    model — or, with none configured, the
                                    pages and the instructions, for the
                                    client's own model to write it
    generate_architecture_document  the dossier in Markdown, PDF, Word and
                                    JSON, in a folder — from the configured
                                    model, or from the dossier the client's
                                    model wrote (`dossier`)

And its prompt, `architecte`: the instructions themselves.

Confluence is read where the environment says (CONFLUENCE_URL, _EMAIL,
_TOKEN) or from an export (ARCHITECT_CONFLUENCE_EXPORT). Nothing else is called.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import IO, Any

from . import __version__, prompts
from .analysis import Budget, analyse, batches
from .confluence import Client, ConfluenceError, Site, read_folder, read_space
from .llm import LLMError, from_env
from .model import Dossier, DossierError, dossier_of
from .pages import Page, Tree
from .write import write_dossier

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_confluence_tree",
        "description": "Liste l'arborescence des pages d'un espace Confluence (ou d'une page et de ses descendantes), avec leurs identifiants.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "space": {"type": "string", "description": "La clé de l'espace, ex. ARCHI."},
                "root_page": {
                    "type": "string",
                    "description": "L'identifiant d'une page racine (facultatif).",
                },
            },
            "required": ["space"],
        },
    },
    {
        "name": "read_confluence_page",
        "description": "Lit une page Confluence : son titre, son lien et son texte.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "space": {"type": "string"},
                "page_id": {"type": "string"},
            },
            "required": ["space", "page_id"],
        },
    },
    {
        "name": "analyze_architecture",
        "description": "Analyse l'architecture applicative d'un espace Confluence et produit le dossier ArchiMate (couches métier, application, technologie ; flux ; dépendances ; points à confirmer), chaque section citant ses pages. Sans modèle configuré, renvoie les pages et les consignes pour que vous rédigiez le dossier vous-même.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "space": {"type": "string"},
                "root_page": {"type": "string"},
                "focus": {
                    "type": "string",
                    "description": "Le sujet à documenter en priorité (facultatif).",
                },
            },
            "required": ["space"],
        },
    },
    {
        "name": "generate_architecture_document",
        "description": "Écrit le dossier d'architecture en Markdown, PDF, Word et JSON dans un dossier local. Donnez `dossier` (le JSON que vous avez rédigé selon les consignes) pour l'écrire tel quel ; sinon le modèle configuré le rédige.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "space": {"type": "string"},
                "root_page": {"type": "string"},
                "focus": {"type": "string"},
                "output_dir": {
                    "type": "string",
                    "description": "Où écrire, par défaut ./rapport-architecture.",
                },
                "dossier": {
                    "type": "object",
                    "description": "Le dossier JSON déjà rédigé (facultatif).",
                },
            },
            "required": ["space"],
        },
    },
]


class Server:
    def __init__(
        self,
        read: Callable[[str, str | None], list[Page]] | None = None,
        ask: Callable[[str, str], str] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.env = dict(os.environ if environ is None else environ)
        self._read = read
        self._ask = ask
        self._cache: dict[tuple[str, str | None], list[Page]] = {}

    # ── Confluence and the model, as configured ─────────────────────────────

    def pages(self, space: str, root: str | None) -> list[Page]:
        key = (space, root)
        if key not in self._cache:
            if self._read is not None:
                self._cache[key] = self._read(space, root)
            elif self.env.get("ARCHITECT_CONFLUENCE_EXPORT"):
                found = read_folder(Path(self.env["ARCHITECT_CONFLUENCE_EXPORT"]))
                self._cache[key] = Tree(found).under(root) if root else found
            else:
                site = Site(
                    url=self.env.get("CONFLUENCE_URL", ""),
                    email=self.env.get("CONFLUENCE_EMAIL", ""),
                    token=self.env.get("CONFLUENCE_TOKEN", ""),
                )
                self._cache[key] = read_space(Client(site), space, root=root)
        return self._cache[key]

    def model(self) -> Callable[[str, str], str] | None:
        if self._ask is not None:
            return self._ask
        if not self.env.get("ARCHITECT_LLM_MODEL"):
            return None
        return from_env(self.env)

    # ── its tools ────────────────────────────────────────────────────────────

    def list_confluence_tree(self, space: str, root_page: str | None = None) -> str:
        pages = self.pages(space, root_page)
        tree = Tree(pages)
        lines = [f"{len(pages)} pages, profondeur {tree.depth()} :"]

        def walk(nodes: list[Any]) -> None:
            for node in nodes:
                lines.append(f"{'  ' * node.depth}- {node.page.title} [{node.page.id}]")
                walk(node.children)

        walk(tree.nodes())
        return "\n".join(lines)

    def read_confluence_page(self, space: str, page_id: str) -> str:
        page = next((p for p in self.pages(space, None) if p.id == page_id), None)
        if page is None:
            raise ValueError(f"Aucune page {page_id} dans l'espace {space}.")
        return f"# {page.title}\n<{page.url}>\n\n{page.text}"

    def _scope(self, space: str, root: str | None) -> str:
        return f"Espace Confluence {space}" + (f", page {root} et ses descendantes" if root else "")

    def analyze_architecture(
        self, space: str, root_page: str | None = None, focus: str | None = None
    ) -> str:
        pages = self.pages(space, root_page)
        ask = self.model()
        if ask is None:
            tree = Tree(pages)
            cut = batches(pages, tree, Budget())
            said = [
                "Aucun modèle n'est configuré ici : rédigez le dossier vous-même, en suivant ces "
                "consignes, à partir des pages ci-dessous ; puis appelez "
                "generate_architecture_document avec `dossier` pour l'écrire.",
                "",
                prompts.SYSTEM,
                "",
                prompts.scope_said(self._scope(space, root_page), focus),
                "",
            ]
            said += ["\n\n---\n\n".join(batch) for batch in cut]
            return "\n".join(said)
        dossier = analyse(ask, pages, scope=self._scope(space, root_page), focus=focus)
        return json.dumps(dossier.to_json(), ensure_ascii=False, indent=2)

    def generate_architecture_document(
        self,
        space: str,
        root_page: str | None = None,
        focus: str | None = None,
        output_dir: str | None = None,
        dossier: dict[str, Any] | None = None,
    ) -> str:
        pages = self.pages(space, root_page)
        scope = self._scope(space, root_page)
        written: Dossier
        if dossier is not None:
            written = dossier_of(dossier, pages, scope=scope)
        else:
            ask = self.model()
            if ask is None:
                raise ValueError(
                    "Aucun modèle n'est configuré : appelez d'abord analyze_architecture, rédigez "
                    "le dossier, puis donnez-le ici dans `dossier`."
                )
            written = analyse(ask, pages, scope=scope, focus=focus)
        folder = Path(output_dir or "rapport-architecture")
        files = write_dossier(written, folder)
        return "Dossier écrit :\n" + "\n".join(f"- {f}" for f in files)

    # ── the protocol ─────────────────────────────────────────────────────────

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        method, ident = message.get("method"), message.get("id")
        params = message.get("params") or {}
        if ident is None:
            return None  # a notification: nothing answered
        try:
            result = self._result(str(method), params)
        except _UnknownMethodError:
            return {
                "jsonrpc": "2.0",
                "id": ident,
                "error": {"code": -32601, "message": f"Méthode inconnue : {method}"},
            }
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    def _result(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            asked = str(params.get("protocolVersion") or PROTOCOLS[-1])
            return {
                "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {}, "prompts": {}},
                "serverInfo": {"name": "leka-architect", "version": __version__},
                "instructions": "L'Architecte applicatif : lit Confluence et produit le dossier d'architecture ArchiMate, chaque section citant ses pages.",
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "prompts/list":
            return {
                "prompts": [
                    {
                        "name": "architecte",
                        "description": "Les consignes de l'Architecte applicatif.",
                    }
                ]
            }
        if method == "prompts/get":
            return {
                "description": "Les consignes de l'Architecte applicatif.",
                "messages": [{"role": "user", "content": {"type": "text", "text": prompts.SYSTEM}}],
            }
        if method == "tools/call":
            name = str(params.get("name"))
            arguments = dict(params.get("arguments") or {})
            tool = getattr(self, name, None) if name in {t["name"] for t in TOOLS} else None
            if tool is None:
                return {
                    "content": [{"type": "text", "text": f"Outil inconnu : {name}"}],
                    "isError": True,
                }
            try:
                text = tool(**arguments)
            except (
                ConfluenceError,
                LLMError,
                DossierError,
                ValueError,
                TypeError,
                OSError,
            ) as error:
                return {"content": [{"type": "text", "text": str(error)}], "isError": True}
            return {"content": [{"type": "text", "text": text}], "isError": False}
        raise _UnknownMethodError(method)

    def serve(self, stdin: IO[str], stdout: IO[str]) -> None:
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                answer: dict[str, Any] | None = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "JSON illisible"},
                }
            else:
                answer = self.handle(message) if isinstance(message, dict) else None
            if answer is not None:
                stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
                stdout.flush()


class _UnknownMethodError(Exception):
    pass


def main() -> int:
    Server().serve(sys.stdin, sys.stdout)
    return 0


__all__ = ["TOOLS", "Server", "main"]
