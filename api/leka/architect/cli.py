"""leka-architect — the application architect in a terminal.

    leka-architect deck     --space MO --parcours "Paiement CB" --perimetre "Digital" \\
                            [--root-page ID] [--vue-applicative] [--connaissances DIR] \\
                            --output ./rapport
    leka-architect render-deck --deck deck.json --output ./rapport
    leka-architect simulate --space ARCHI [--root-page ID] [--focus …] --output ./rapport
    leka-architect spaces
    leka-architect tree     --space ARCHI [--root-page ID]
    leka-architect pages    --space ARCHI [--root-page ID] --output pages.md
    leka-architect render   --dossier reponse.json --output ./rapport
    leka-architect compare  --dossier ./rapport --reference reference.docx [--output ./rapport]
    leka-architect mcp
    leka-architect prompts  --output ./prompts

Confluence by its API (CONFLUENCE_URL, CONFLUENCE_EMAIL, CONFLUENCE_TOKEN) or
from an export (--export, or ARCHITECT_CONFLUENCE_EXPORT); the model as llm.py
says (ARCHITECT_LLM_*). Read from the environment, or a .env file: --env, else
ARCHITECT_ENV, else ./.env, else ~/.leka-architect.env.

Nothing is sent to LEKA, nothing is measured: the pages go to the model
configured, nowhere else.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__, journey, knowledge, prompts
from .analysis import Budget, analyse, batches
from .compare import compare, reference
from .compare import markdown as comparison
from .confluence import Client, ConfluenceError, Site, list_spaces, read_folder, read_space
from .llm import LLMError, from_env
from .model import Dossier, DossierError, dossier_of, parsed
from .pages import Page, Tree
from .write import read_dossier, write_dossier


def load_env(path: Path) -> None:
    """KEY=VALUE lines, never over what the environment already says."""
    # utf-8-sig: Windows' Notepad starts what it saves with a BOM.
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _env(asked: str | None) -> None:
    for candidate in (
        asked,
        os.environ.get("ARCHITECT_ENV"),
        ".env",
        str(Path.home() / ".leka-architect.env"),
    ):
        if candidate and Path(candidate).is_file():
            load_env(Path(candidate))
            return


def _site() -> Site:
    return Site(
        url=os.environ.get("CONFLUENCE_URL", ""),
        email=os.environ.get("CONFLUENCE_EMAIL", ""),
        token=os.environ.get("CONFLUENCE_TOKEN", ""),
    )


def _pages(space: str, root: str | None, export: str | None) -> list[Page]:
    folder = export or os.environ.get("ARCHITECT_CONFLUENCE_EXPORT")
    if folder:
        found = read_folder(Path(folder))
        return Tree(found).under(root) if root else found
    return read_space(Client(_site()), space, root=root)


def _scope(space: str, root: str | None) -> str:
    return f"Espace Confluence {space}" + (f", page {root} et ses descendantes" if root else "")


def _say(text: str) -> None:
    sys.stderr.write(text + "\n")


def simulate(args: argparse.Namespace) -> int:
    # The model first: a configuration that cannot work is said before
    # Confluence is read.
    model = from_env()
    pages = _pages(args.space, args.root_page, args.export)
    _say(f"{len(pages)} pages lues ({_scope(args.space, args.root_page)}).")
    _say(f"Modèle : {model.said}.")

    def said(step: str, detail: dict[str, object]) -> None:
        if step == "batch":
            _say(f"Lot {detail['batch']} sur {detail['of']} analysé.")

    dossier = analyse(
        model, pages, scope=_scope(args.space, args.root_page), focus=args.focus, said=said
    )
    written = write_dossier(dossier, Path(args.output))
    if args.reference:
        found = compare(dossier, reference(Path(args.reference)))
        target = Path(args.output) / "comparaison.md"
        target.write_text(comparison(found, dossier.title), encoding="utf-8")
        written.append(target)
    _say(f"{len(dossier.elements)} éléments, {len(dossier.pages_read)} pages citées.")
    for path in written:
        sys.stdout.write(f"{path}\n")
    return 0


def _told(inputs: dict[str, object]) -> str:
    """The instructions it follows: its package's, their parameters filled."""
    said = journey.instructions()
    if said is None:
        raise OSError(
            "Ce paquet ne porte pas de consignes (consignes.md) : téléchargez-le depuis LEKA."
        )
    return journey.filled(said, journey.parameters(inputs))


def deck(args: argparse.Namespace) -> int:
    """The deck of a journey: the pages read, the analysis, the deck's
    content, drawn — an editable PowerPoint and its PDF."""
    shipped = journey.renderer()
    inputs: dict[str, object] = {
        "parcours": args.parcours,
        "perimetre": args.perimetre,
        "organisation": args.organisation or "",
        "entite": args.entite or "",
        "service": args.service or "",
        "vue_applicative": bool(args.vue_applicative),
    }
    told = _told(inputs)
    model = from_env()
    pages = _pages(args.space, args.root_page, args.export)
    _say(f"{len(pages)} pages lues ({_scope(args.space, args.root_page)}).")
    _say(f"Modèle : {model.said}.")
    folder = Path(args.connaissances or os.environ.get("ARCHITECT_KNOWLEDGE_DIR", "connaissances"))
    found = knowledge.tables(folder)
    corpus = "\n".join(f"{p.title}\n{p.text}" for p in pages)
    extracts = knowledge.relevant(found, corpus) if found else ""
    if found:
        _say(f"Connaissances : {len({f for f, _, _ in found})} fichiers lus ({folder}).")
    analysis = journey.analysis_of(model, told, pages, inputs, knowledge=extracts, said=_say)
    _say("Analyse faite ; le deck s'écrit.")
    content = journey.deck_of(
        model,
        told,
        analysis,
        inputs,
        rules=shipped.DECK_RULES,
        schema=shipped.ArchitectureDeck.model_json_schema(),
        check=shipped.ArchitectureDeck.model_validate,
    )
    folder_out = Path(args.output)
    folder_out.mkdir(parents=True, exist_ok=True)
    (folder_out / "analyse.md").write_text(analysis, encoding="utf-8")
    for path in [*journey.draw(content, folder_out), folder_out / "analyse.md"]:
        sys.stdout.write(f"{path}\n")
    return 0


def render_deck(args: argparse.Namespace) -> int:
    """A deck's content (JSON) drawn — one any model wrote after the prompt pack."""
    raw = parsed(Path(args.deck).read_text(encoding="utf-8"))
    for path in journey.draw(raw, Path(args.output)):
        sys.stdout.write(f"{path}\n")
    return 0


def spaces(_: argparse.Namespace) -> int:
    for space in list_spaces(Client(_site())):
        sys.stdout.write(f"{space['key']}\t{space['name']}\n")
    return 0


def tree(args: argparse.Namespace) -> int:
    pages = _pages(args.space, args.root_page, args.export)
    found = Tree(pages)
    sys.stdout.write(f"{len(found)} pages, profondeur {found.depth()}\n")

    def walk(nodes: Sequence[object]) -> None:
        for node in nodes:
            sys.stdout.write(f"{'  ' * node.depth}{node.page.title} [{node.page.id}]\n")  # type: ignore[attr-defined]
            walk(node.children)  # type: ignore[attr-defined]

    walk(found.nodes())
    return 0


def pages(args: argparse.Namespace) -> int:
    """The pages as the model reads them, in one file — to attach to a chat
    model without tools (the prompt pack)."""
    read = _pages(args.space, args.root_page, args.export)
    cut = batches(read, Tree(read), Budget(call_chars=10**9))
    Path(args.output).write_text(
        prompts.scope_said(_scope(args.space, args.root_page), None)
        + "\n\n"
        + "\n\n---\n\n".join(cut[0] if cut else []),
        encoding="utf-8",
    )
    sys.stdout.write(f"{args.output}\n")
    return 0


def render(args: argparse.Namespace) -> int:
    """A dossier's JSON rendered: Markdown, PDF, Word — one this tool wrote,
    or one any model wrote after the prompt pack (its pages then read again,
    from --space or --export, to keep its evidence)."""
    raw = parsed(Path(args.dossier).read_text(encoding="utf-8"))
    if "pages_read" in raw:
        dossier = Dossier.from_json(raw)
    else:
        if not (args.space or args.export):
            _say("Sans --space ni --export, les pages citées ne peuvent pas être vérifiées.")
        read = (
            _pages(args.space or "", args.root_page, args.export)
            if (args.space or args.export)
            else []
        )
        dossier = dossier_of(raw, read, scope=_scope(args.space or "?", args.root_page))
    for path in write_dossier(dossier, Path(args.output)):
        sys.stdout.write(f"{path}\n")
    return 0


def compared(args: argparse.Namespace) -> int:
    dossier = read_dossier(Path(args.dossier))
    found = compare(dossier, reference(Path(args.reference)))
    said = comparison(found, dossier.title)
    if args.output:
        target = Path(args.output)
        target.mkdir(parents=True, exist_ok=True)
        (target / "comparaison.md").write_text(said, encoding="utf-8")
        sys.stdout.write(f"{target / 'comparaison.md'}\n")
    else:
        sys.stdout.write(said)
    return 0


def mcp(_: argparse.Namespace) -> int:
    from .mcp_server import main as serve

    return serve()


def prompt_pack(args: argparse.Namespace) -> int:
    from .distribution import prompt_pack as pack

    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    written = pack(journey.instructions())
    try:
        schema = journey.renderer().ArchitectureDeck.model_json_schema()
    except ImportError:
        pass
    else:
        written["schema-deck.json"] = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    for name, text in written.items():
        (folder / name).write_text(text, encoding="utf-8")
        sys.stdout.write(f"{folder / name}\n")
    return 0


def parser() -> argparse.ArgumentParser:
    found = argparse.ArgumentParser(
        prog="leka-architect",
        description="L'Architecte applicatif de LEKA : "
        "Confluence → deck d'architecture d'un parcours, dossier ArchiMate.",
    )
    found.add_argument("--version", action="version", version=f"leka-architect {__version__}")
    found.add_argument("--env", help="un fichier .env à lire")
    commands = found.add_subparsers(dest="command", required=True)

    def perimeter(command: argparse.ArgumentParser, required: bool = True) -> None:
        command.add_argument("--space", required=required, help="la clé de l'espace, ex. ARCHI")
        command.add_argument("--root-page", help="l'identifiant d'une page racine")
        command.add_argument("--export", help="un export Confluence (dossier) plutôt que l'API")

    journey_ = commands.add_parser("deck", help="le deck d'un parcours : PowerPoint et PDF")
    perimeter(journey_)
    journey_.add_argument("--parcours", required=True, help="ex. « Paiement CB »")
    journey_.add_argument("--perimetre", required=True, help="ex. « Digital - Espace Client »")
    journey_.add_argument("--organisation")
    journey_.add_argument("--entite")
    journey_.add_argument("--service")
    journey_.add_argument(
        "--vue-applicative", action="store_true", help="ajouter la vue applicative"
    )
    journey_.add_argument(
        "--connaissances", help="le dossier des fichiers de Connaissances (./connaissances)"
    )
    journey_.add_argument("--output", default="rapport", help="le dossier où écrire (./rapport)")
    journey_.set_defaults(handler=deck)

    drawn_deck = commands.add_parser(
        "render-deck", help="dessiner un deck JSON : PowerPoint et PDF"
    )
    drawn_deck.add_argument("--deck", required=True)
    drawn_deck.add_argument("--output", default="rapport")
    drawn_deck.set_defaults(handler=render_deck)

    listed_spaces = commands.add_parser("spaces", help="les espaces Confluence lisibles")
    listed_spaces.set_defaults(handler=spaces)

    run = commands.add_parser("simulate", help="produire le dossier d'architecture")
    perimeter(run)
    run.add_argument("--focus", help="le sujet à documenter en priorité")
    run.add_argument("--output", default="rapport", help="le dossier où écrire (./rapport)")
    run.add_argument("--reference", help="un document de référence à comparer")
    run.set_defaults(handler=simulate)

    shown = commands.add_parser("tree", help="afficher l'arborescence lue")
    perimeter(shown)
    shown.set_defaults(handler=tree)

    listed = commands.add_parser("pages", help="les pages en un fichier, pour un LLM sans outils")
    perimeter(listed)
    listed.add_argument("--output", default="pages.md")
    listed.set_defaults(handler=pages)

    drawn = commands.add_parser("render", help="écrire un dossier JSON en Markdown, PDF, Word")
    perimeter(drawn, required=False)
    drawn.add_argument("--dossier", required=True)
    drawn.add_argument("--output", default="rapport")
    drawn.set_defaults(handler=render)

    against = commands.add_parser("compare", help="comparer à un document de référence")
    against.add_argument(
        "--dossier", required=True, help="dossier-architecture.json, ou son dossier"
    )
    against.add_argument("--reference", required=True)
    against.add_argument("--output")
    against.set_defaults(handler=compared)

    served = commands.add_parser("mcp", help="le serveur MCP (stdio)")
    served.set_defaults(handler=mcp)

    pack = commands.add_parser("prompts", help="écrire le pack de prompts")
    pack.add_argument("--output", default="prompts")
    pack.set_defaults(handler=prompt_pack)
    return found


def main(argv: Sequence[str] | None = None) -> int:
    # Written to a file or a pipe on Windows (cp1252), a « → » never stops it.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
    args = parser().parse_args(argv)
    _env(args.env)
    try:
        return int(args.handler(args))
    except (ConfluenceError, LLMError, DossierError, OSError, knowledge.KnowledgeError) as error:
        _say(f"Erreur : {error}")
        return 1
    except ImportError as error:
        # The renderer's own packages (pydantic, python-pptx): an install gone wrong.
        _say(f"Erreur : {error} — réinstallez : pip install ./leka-architect")
        return 1
    except ValueError as error:
        # A deck's content the template refuses (pydantic's ValidationError).
        _say(f"Erreur : {error}")
        return 1


if __name__ == "__main__":  # pragma: no cover - the process itself
    sys.exit(main())
