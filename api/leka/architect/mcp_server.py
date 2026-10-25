"""The architect as an MCP server (Model Context Protocol, over stdio) — for
GitHub Copilot in VS Code (agent mode), Claude Desktop, Claude Code, Cursor
or any MCP client. One JSON-RPC 2.0 message per line, in and out.

Its tools — named for what an organisation's instructions ask of their
connector (2026-10-25: « Obtenir des espaces »…):

    list_confluence_spaces          the spaces one may read
    list_confluence_tree            the pages of a space, or under a page
    read_confluence_page            one page's text, title and link
    search_confluence_pages         a space's pages whose title says a word
    list_knowledge_files            the knowledge files given (a directory…)
    read_knowledge_file             one of them: a sheet, its rows
    generate_architecture_deck      a journey's deck — PowerPoint and PDF —
                                    from the content the client's model
                                    wrote (`deck`), or from the model
                                    configured
    analyze_architecture            the dossier, written by the configured
                                    model — or, with none configured, the
                                    pages and the instructions, for the
                                    client's own model to write it
    generate_architecture_document  the dossier in Markdown, PDF, Word and
                                    JSON, in a folder — from the configured
                                    model, or from the dossier the client's
                                    model wrote (`dossier`)

And its prompt, `architecte`: the instructions themselves — its
organisation's own when the package carries them (journey.py).

Confluence is read where the environment says (CONFLUENCE_URL, _EMAIL,
_TOKEN) or from an export (ARCHITECT_CONFLUENCE_EXPORT). Nothing else is called.
"""

from __future__ import annotations

import io
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import IO, Any

from . import __version__, journey, knowledge, prompts
from .analysis import Budget, analyse, batches
from .confluence import Client, ConfluenceError, Site, list_spaces, read_folder, read_space
from .llm import LLMError, from_env
from .model import Dossier, DossierError, dossier_of
from .pages import Page, Tree
from .write import write_dossier

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

_JOURNEY = {
    "parcours": {"type": "string", "description": "Le parcours, ex. « Paiement CB »."},
    "perimetre": {"type": "string", "description": "Le périmètre et ses canaux."},
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_confluence_spaces",
        "description": "Obtenir des espaces : les espaces Confluence lisibles, leur clé et leur nom.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_confluence_pages",
        "description": "Obtenir les pages : les pages d'un espace dont le titre contient ces mots.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "space": {"type": "string"},
                "title": {"type": "string", "description": "Un ou plusieurs mots du titre."},
            },
            "required": ["space", "title"],
        },
    },
    {
        "name": "list_knowledge_files",
        "description": "Les fichiers de Connaissances fournis (annuaire des contacts, référentiel applicatif…) et leurs onglets.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_knowledge_file",
        "description": "Lit un fichier de Connaissances : un onglet d'un classeur Excel (ou un CSV, un texte), ses lignes numérotées. `contains` ne garde que les lignes qui le contiennent (casse ignorée), les deux premières (en-têtes) toujours.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Son nom, tel que listé."},
                "sheet": {"type": "string", "description": "L'onglet (facultatif)."},
                "contains": {"type": "string", "description": "Un mot à chercher (facultatif)."},
                "first_row": {
                    "type": "integer",
                    "description": "La première ligne (1 par défaut).",
                },
            },
            "required": ["file"],
        },
    },
    {
        "name": "generate_architecture_deck",
        "description": "Écrit le deck d'architecture du parcours — PowerPoint modifiable et PDF, au gabarit — dans un dossier local. Donnez `deck` (le contenu que vous avez rédigé, selon le schéma de la consigne `architecte`) ; sans lui, le modèle configuré lit l'espace et le rédige.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_JOURNEY,
                "deck": {"type": "object", "description": "Le contenu du deck (facultatif)."},
                "space": {"type": "string", "description": "L'espace à lire, sans `deck`."},
                "root_page": {"type": "string"},
                "vue_applicative": {"type": "boolean"},
                "output_dir": {
                    "type": "string",
                    "description": "Où écrire, par défaut ./rapport-architecture.",
                },
            },
            "required": ["parcours", "perimetre"],
        },
    },
    {
        "name": "list_confluence_tree",
        "description": "Obtenir les pages dans un espace : l'arborescence des pages d'un espace Confluence (ou d'une page et de ses descendantes), avec leurs identifiants.",
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
        "description": "Obtenir le contenu de la page et les métadonnées : son titre, son lien, sa place dans l'arborescence et son texte.",
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
                self._cache[key] = read_space(Client(self.site()), space, root=root)
        return self._cache[key]

    def site(self) -> Site:
        return Site(
            url=self.env.get("CONFLUENCE_URL", ""),
            email=self.env.get("CONFLUENCE_EMAIL", ""),
            token=self.env.get("CONFLUENCE_TOKEN", ""),
        )

    def knowledge_dir(self) -> Path:
        return Path(self.env.get("ARCHITECT_KNOWLEDGE_DIR") or "connaissances")

    def told(self) -> str | None:
        """The instructions the package carries — its organisation's, or LEKA's."""
        return journey.instructions()

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
        pages = self.pages(space, None)
        page = next((p for p in pages if p.id == page_id), None)
        if page is None:
            raise ValueError(f"Aucune page {page_id} dans l'espace {space}.")
        where = " > ".join(Tree(pages).path(page.id))
        return f"# {page.title} [{page.id}]\n<{page.url}>\n{where}\n\n{page.text}"

    def list_confluence_spaces(self) -> str:
        if self.env.get("ARCHITECT_CONFLUENCE_EXPORT"):
            return (
                "Un export est configuré (ARCHITECT_CONFLUENCE_EXPORT) : un seul espace, le sien."
            )
        found = list_spaces(Client(self.site()))
        return "\n".join(f"- {s['key']} : {s['name']}" for s in found) or "Aucun espace lisible."

    def search_confluence_pages(self, space: str, title: str) -> str:
        words = [w.lower() for w in title.split() if w]
        found = [p for p in self.pages(space, None) if all(w in p.title.lower() for w in words)]
        if not found:
            return f"Aucune page de {space} dont le titre contient « {title} »."
        return "\n".join(f"- {p.title} [{p.id}] <{p.url}>" for p in found[:50])

    def list_knowledge_files(self) -> str:
        folder = self.knowledge_dir()
        found = knowledge.files(folder)
        if not found:
            return f"Aucun fichier de Connaissances dans {folder} (ARCHITECT_KNOWLEDGE_DIR)."
        lines = []
        for path in found:
            name = str(path.relative_to(folder))
            try:
                tabs = list(knowledge.rows_of(path))
            except (knowledge.KnowledgeError, OSError):
                tabs = []
            lines.append(f"- {name}" + (f" — onglets : {', '.join(tabs)}" if len(tabs) > 1 else ""))
        return "\n".join(lines)

    def read_knowledge_file(
        self,
        file: str,
        sheet: str | None = None,
        contains: str | None = None,
        first_row: int = 1,
    ) -> str:
        tables = knowledge.rows_of(knowledge.inside(self.knowledge_dir(), file))
        name = sheet or next(iter(tables), "")
        if name not in tables:
            raise ValueError(f"Aucun onglet « {name} » ; onglets : {', '.join(tables)}.")
        rows = tables[name]
        if contains:
            word = contains.lower()
            kept = [
                (n, r) for n, r in enumerate(rows, 1) if n <= 2 or any(word in c.lower() for c in r)
            ]
            return f"## {name}\n" + "\n".join(f"{n} | " + " | ".join(r) for n, r in kept[:300])
        return knowledge.said(name, rows, first=max(first_row, 1) - 1)

    def generate_architecture_deck(
        self,
        parcours: str,
        perimetre: str,
        deck: dict[str, Any] | None = None,
        space: str | None = None,
        root_page: str | None = None,
        vue_applicative: bool = False,
        output_dir: str | None = None,
    ) -> str:
        folder = Path(output_dir or "rapport-architecture")
        if deck is None:
            ask, told = self.model(), self.told()
            if ask is None or told is None or not space:
                raise ValueError(
                    "Donnez `deck` : le contenu que vous avez rédigé selon la consigne "
                    "`architecte` (sans modèle configuré ici, c'est le vôtre qui le rédige)."
                )
            shipped = journey.renderer()
            inputs: dict[str, object] = {
                "parcours": parcours,
                "perimetre": perimetre,
                "vue_applicative": vue_applicative,
            }
            told = journey.filled(told, journey.parameters(inputs))
            pages = self.pages(space, root_page)
            found = knowledge.tables(self.knowledge_dir())
            corpus = "\n".join(f"{p.title}\n{p.text}" for p in pages)
            analysis = journey.analysis_of(
                ask, told, pages, inputs, knowledge=knowledge.relevant(found, corpus)
            )
            deck = journey.deck_of(
                ask,
                told,
                analysis,
                inputs,
                rules=shipped.DECK_RULES,
                schema=shipped.ArchitectureDeck.model_json_schema(),
                check=shipped.ArchitectureDeck.model_validate,
            )
        content = {"parcours": parcours, "perimetre": perimetre, **deck}
        files = journey.draw(content, folder)
        return "Deck écrit :\n" + "\n".join(f"- {f}" for f in files)

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
                "instructions": "L'Architecte applicatif : lit Confluence (et les fichiers de Connaissances) et produit le deck d'architecture d'un parcours — PowerPoint et PDF — ou le dossier ArchiMate d'un espace. Ses consignes : la consigne `architecte`.",
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
            told = self.told()
            text = journey.tools_prompt(told) if told else prompts.SYSTEM
            return {
                "description": "Les consignes de l'Architecte applicatif.",
                "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
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
                knowledge.KnowledgeError,
                ValueError,
                TypeError,
                OSError,
                ImportError,
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
    # UTF-8 both ways, as MCP says — on Windows a pipe would be cp1252 and an
    # « □ » of the instructions would stop the server (2026-10-25).
    for stream in (sys.stdin, sys.stdout):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    Server().serve(sys.stdin, sys.stdout)
    return 0


__all__ = ["TOOLS", "Server", "main"]
