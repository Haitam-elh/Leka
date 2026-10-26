"""The architect's deck of a journey (2026-10-25), wherever it is installed:
the instructions its package carries — its organisation's own when it has
them, else LEKA's —, the Confluence pages read, the analysis, the deck's
content, then drawn by LEKA's own renderer (leka_architect.deck, shipped
with the package): an editable PowerPoint and its PDF.

    instructions()  the instructions this package carries (consignes.md)
    filled()        their {{PARAMÈTRES}} filled from what is asked
    analysis_of()   the pages (and the knowledge files) → the analysis
    deck_of()       the analysis → the deck's content, as JSON
    draw()          that content → .pptx and .pdf in a folder

The same two steps as on LEKA (capabilities/runs.py, delivery.py): the model
analyses first, then fills the deck, which LEKA's code draws — the template
is the code's, never left to the model.
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .analysis import Budget, batches
from .model import parsed
from .pages import Page, Tree

Ask = Callable[[str, str], str]

CONSIGNES = Path(__file__).resolve().parent / "consignes.md"

# Where the instructions' tool names are, here (2026-10-25): an organisation's
# prompt names its connector's actions — « Obtenir des espaces »… — and its
# knowledge files; this package's MCP tools do the same.
TOOLS_NOTE = """---

Dans cet outil (leka-architect), les libellés d'outils des consignes \
correspondent à :
- « Obtenir des espaces » → `list_confluence_spaces`
- « Obtenir les pages dans un espace » → `list_confluence_tree`
- « Obtenir le contenu de la page et les métadonnées » → `read_confluence_page`
- « Obtenir les pages » (recherche par titre) → `search_confluence_pages`
- les fichiers de Connaissances (annuaire, référentiel) → `list_knowledge_files`, \
puis `read_knowledge_file` (un onglet, des lignes)
- le PowerPoint et le PDF → `generate_architecture_deck`, quand l'analyse est \
faite : donne `parcours`, `perimetre` et `deck` (le contenu du deck, selon son \
schéma) ; il écrit les deux fichiers, au gabarit, et répond leurs chemins. Ne \
les dessine pas toi-même."""

# What the analysis is, here — LEKA's own note for its platform, made for
# the pages read by this tool (capabilities/runtime.py RENDER_NOTES).
ANALYSIS_NOTE = """---

Comment cela tourne ici (cela adapte les consignes ci-dessus à cet outil, \
sans les remplacer) :
- Tes sources sont les pages Confluence fournies ci-dessous — chacune avec son \
identifiant entre crochets, sa place dans l'arborescence et son lien — et, \
quand ils sont fournis, les extraits des fichiers de Connaissances (une ligne \
par ligne du fichier, son numéro d'abord). Les recherches que les consignes \
décrivent sont faites : ce sont ces pages et ces extraits.
- Un élément est « Documenté » seulement si une page ou un extrait fourni le \
montre : cite l'identifiant de la page [id] ou le fichier et son onglet. Sinon, \
ORANGE « À confirmer ». Jamais de brique générique qu'aucune source ne nomme.
- Une source que les consignes nomment et qui n'est pas fournie (SharePoint, un \
fichier de Connaissances absent) : une ligne « NON FOURNI » dans « Sources \
consultées et limites », ses manques en orange — jamais comblés par des \
connaissances générales.
- Cette réponse est l'analyse, en markdown, section par section dans l'ordre \
du deck : la couche métier (acteur, déclencheur, processus source et canal, \
groupings A, B, C… et leurs étapes), les six paragraphes du « Parcours en \
clair », les règles de gestion, la vue applicative si elle est demandée, la \
couche applicative de chaque sous-processus (ses briques dans l'ordre du \
premier appel, ses phases, chaque chaîne d'appels), le RACI, les points de \
contrôle, les sources.
- L'outil dessine ensuite le PowerPoint modifiable et son PDF à partir de \
cette analyse, au gabarit : ne décris pas de fichiers.
- N'écris jamais le tiret long « — » : un deux-points, une virgule, un point-virgule ou des \
parenthèses, selon la phrase."""

NOTES_NOTE = """---

Ici, tu lis UN LOT des pages du périmètre (il y en a {of}) : relève, pour le \
parcours demandé seulement, ce que ces pages disent — étapes métier, acteurs, \
déclencheur, règles de gestion, briques applicatives et leurs services, \
chaînes d'appels, flux et données, contacts, manques —, chaque fait suivi de \
l'identifiant de sa page [id]. En markdown, concis. Rien d'autre."""

PARAMETER = re.compile(r"\{\{([A-Z_]+)\}\}")
_EMPTY_AFTER = r"\s*[\u2013-]\s*\{{\{{{name}\}}\}}"


def renderer() -> Any:
    """LEKA's deck renderer, shipped beside this package (leka_architect.deck)
    — ImportError where it is not: in LEKA's own code, which draws with its
    own (capabilities/deliverables)."""
    return importlib.import_module(f"{__package__}.deck")


def instructions(path: Path = CONSIGNES) -> str | None:
    """The instructions this package carries — None in LEKA's own code, where
    the agent's are the registry's (or its organisation's)."""
    return path.read_text(encoding="utf-8") if path.is_file() else None


def parameters(inputs: Mapping[str, object]) -> dict[str, str]:
    """What the instructions' {{PARAMÈTRES}} are here: what is asked, and
    where this tool reads — never invented; one unknown is left out."""

    def said(key: str) -> str:
        value = inputs.get(key)
        return value.strip() if isinstance(value, str) else ""

    return {
        "ORGANISATION": said("organisation"),
        "ENTITE": said("entite"),
        "SERVICE": said("service"),
        "COULEUR_PRINCIPALE": "#1F3864",
        "GABARIT_REFERENCE": "le gabarit décrit au §5",
        "ESPACES_CONFLUENCE": "l'espace Confluence lu par cet outil",
        "SITES_SHAREPOINT": "",
        "ANNUAIRE_CONTACTS": "les fichiers de Connaissances fournis",
        "REFERENTIEL_APPLICATIF": "les fichiers de Connaissances fournis",
        "DOMAINES_INTERNES": "les domaines des adresses des personnes de l'organisation",
        "SEUIL_FRAICHEUR": "12 mois",
    }


def filled(text: str, values: Mapping[str, str]) -> str:
    """The instructions with each parameter's value; an empty one goes with
    the dash before it, any other left unknown goes."""
    for name, value in values.items():
        if not value:
            text = re.sub(_EMPTY_AFTER.format(name=name), "", text)
    return PARAMETER.sub(lambda m: values.get(m.group(1), ""), text)


def _asked(inputs: Mapping[str, object]) -> str:
    return json.dumps({k: v for k, v in inputs.items() if v not in (None, "")}, ensure_ascii=False)


def analysis_of(
    ask: Ask,
    told: str,
    pages: Sequence[Page],
    inputs: Mapping[str, object],
    *,
    knowledge: str = "",
    budget: Budget | None = None,
    said: Callable[[str], None] = lambda _: None,
) -> str:
    """The analysis, section by section in the deck's order: from the pages
    in one call when they fit, else each batch's facts first, then the
    analysis from them."""
    tree = Tree(pages)
    cut = batches(list(pages), tree, budget or Budget())
    system = f"{told}\n\n{ANALYSIS_NOTE}"
    extra = f"\n\n# Extraits des fichiers de Connaissances\n\n{knowledge}" if knowledge else ""
    if len(cut) <= 1:
        material = "\n\n---\n\n".join(cut[0]) if cut else "(aucune page)"
        return ask(system, f"La demande : {_asked(inputs)}\n\n# Les pages\n\n{material}{extra}")
    notes: list[str] = []
    for n, batch in enumerate(cut, 1):
        said(f"Lot {n} sur {len(cut)} lu.")
        notes.append(
            ask(
                f"{told}\n\n{NOTES_NOTE.format(of=len(cut))}",
                f"La demande : {_asked(inputs)}\n\n# Les pages (lot {n})\n\n"
                + "\n\n---\n\n".join(batch),
            )
        )
    return ask(
        system,
        f"La demande : {_asked(inputs)}\n\n# Ce que les pages disent, lot par lot\n\n"
        + "\n\n---\n\n".join(notes)
        + extra,
    )


def deck_of(
    ask: Ask,
    told: str,
    analysis: str,
    inputs: Mapping[str, object],
    *,
    rules: str,
    schema: Mapping[str, Any],
    check: Callable[[dict[str, Any]], object],
) -> dict[str, Any]:
    """The deck's content, as the deck writer fills it from the analysis —
    checked (`check` raises on what the template refuses), asked once more
    with why when it is not."""
    system = (
        f"{rules}\n\n---\n\n{told}\n\n---\n\nRéponds par l'objet JSON seul, selon ce schéma :\n"
        + json.dumps(schema, ensure_ascii=False)
    )
    user = json.dumps({"inputs": dict(inputs), "analysis": analysis}, ensure_ascii=False)
    answer = ask(system, user)
    try:
        found = parsed(answer)
        check(found)
        return found
    except Exception as error:
        again = ask(
            system,
            user + f"\n\nTa réponse précédente n'a pas pu être lue : {str(error)[:1500]}\n"
            "Réponds par l'objet JSON seul, complet, selon le schéma.",
        )
        found = parsed(again)
        check(found)
        return found


def draw(content: Mapping[str, Any], folder: Path) -> list[Path]:
    """The deck drawn by LEKA's renderer: <parcours>.pptx and .pdf in `folder`."""
    shipped = renderer()
    deck = shipped.ArchitectureDeck.model_validate(dict(content))
    drawn = shipped.render(deck)
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w.-]+", "-", f"architecture-{deck.parcours}".lower()).strip("-")[:80]
    written = []
    for fmt in ("pptx", "pdf"):
        target = folder / f"{name}.{fmt}"
        target.write_bytes(drawn.of(fmt))
        written.append(target)
    (folder / f"{name}.json").write_text(
        json.dumps(deck.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    written.append(folder / f"{name}.json")
    return written


def tools_prompt(told: str) -> str:
    """The instructions as an MCP client's model reads them: its tools named,
    and the deck's schema when this package can draw it."""
    text = f"{told}\n\n{TOOLS_NOTE}"
    try:
        schema = renderer().ArchitectureDeck.model_json_schema()
    except ImportError:
        return text
    return f"{text}\n\nLe schéma de `deck` :\n" + json.dumps(schema, ensure_ascii=False)


__all__ = [
    "ANALYSIS_NOTE",
    "CONSIGNES",
    "TOOLS_NOTE",
    "analysis_of",
    "deck_of",
    "draw",
    "filled",
    "instructions",
    "parameters",
    "renderer",
    "tools_prompt",
]
