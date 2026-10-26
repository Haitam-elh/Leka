"""What the architect is told — the same words on LEKA and wherever it is
installed: its role and its absolute principle, ArchiMate's layers, what it
answers (model.SCHEMA), and the pages it reads, each by its id.

    SYSTEM            the role, the rules, the dossier's sections
    extraction()      one batch of pages → its part of the dossier
    synthesis()       the parts, merged → the sections written whole
    digest()          a page as it is shown: id, place in the tree, link, text
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from .model import ELEMENT_TYPES, RELATION_TYPES, SCHEMA, SECTIONS
from .pages import Page, Tree

SYSTEM = (
    """Tu es l'Architecte applicatif. À partir des pages Confluence fournies — et \
d'elles seules — tu produis le dossier d'architecture applicative du périmètre \
demandé, structuré selon ArchiMate 3.1.

PRINCIPE ABSOLU : factuel, rien d'inventé. Tout élément provient des pages. Un \
manque n'est jamais comblé en silence : il devient un « point à confirmer », et \
l'élément concerné porte `to_confirm: true`.

PREUVES : chaque section, chaque élément et chaque relation cite les pages dont \
il est tiré, par leur identifiant exact (le nombre entre crochets avant chaque \
page). Une page qui n'est pas fournie n'est jamais citée.

LE DOSSIER, dans cet ordre :
"""
    + "\n".join(f"  {i}. {title} (`{key}`)" for i, (key, title) in enumerate(SECTIONS, 1))
    + """

  • synthese : l'objectif du périmètre, ses acteurs, ce qu'il couvre, en 5 à 10 phrases.
  • metier : les acteurs, rôles, processus, événements, services et objets métier.
  • application : les composants applicatifs, leurs services, interfaces et données.
  • technologie : les nœuds, logiciels système, réseaux, services technologiques ; \
« non documenté » dans le résumé quand les pages n'en disent rien.
  • flux : les échanges entre composants (qui appelle qui, quoi, synchrone ou non).
  • dependances : ce dont le périmètre dépend, et ce qui dépend de lui.
  • points : chaque manque, contradiction ou élément non documenté, formulé comme \
une question à trancher.

ÉLÉMENTS ArchiMate, par couche (le type exact, tel qu'écrit) :
"""
    + "\n".join(f"  {layer} : {', '.join(types)}" for layer, types in ELEMENT_TYPES.items())
    + f"""

RELATIONS (le type exact) : {", ".join(RELATION_TYPES)}. Une relation relie deux \
éléments du dossier, par leur `id`.

En français, concis et précis : un élément par son nom tel que les pages le \
donnent, une description d'une ou deux phrases. Réponds par l'objet JSON seul, \
selon ce schéma :
"""
    + json.dumps(SCHEMA, ensure_ascii=False)
)

EXTRACTION = """Voici une partie des pages du périmètre. Produis le dossier de ces \
pages seules : leurs éléments, leurs relations, leurs points à confirmer, et un \
résumé par section de ce qu'elles en disent (une section dont elles ne disent rien \
est omise). Ce n'est qu'une partie : n'écris pas « non documenté » pour ce qui \
peut être ailleurs."""

SYNTHESIS = """Voici le dossier rassemblé à partir de toutes les pages du \
périmètre, partie par partie : ses éléments et ses relations sont fusionnés, ses \
résumés sont ceux de chaque partie. Écris le dossier final : un résumé par \
section, entier et cohérent, chaque section citant ses pages ; reprends les \
éléments et les relations tels quels (mêmes `id`), en retirant les doublons \
évidents ; regroupe les points à confirmer."""


def digest(page: Page, tree: Tree, chars: int) -> str:
    """A page as the model reads it: its id, where it sits, its link, its
    text — cut at `chars`, said so."""
    place = " › ".join(tree.path(page.id)) or page.title  # noqa: RUF001
    text = " ".join(page.text.split())
    cut = len(text) > chars
    head = f"[{page.id}] {place}"
    if page.url:
        head += f"\n<{page.url}>"
    if page.updated_at:
        head += f"\nmise à jour : {page.updated_at}"
    return f"{head}\n{text[:chars]}{' […]' if cut else ''}"


def scope_said(scope: str, focus: str | None) -> str:
    said = f"Périmètre : {scope}."
    if focus:
        said += f" Sujet à documenter en priorité : {focus}."
    return said


def extraction(batch: Sequence[str], *, scope: str, focus: str | None) -> tuple[str, str]:
    user = f"{scope_said(scope, focus)}\n\n{EXTRACTION}\n\n" + "\n\n---\n\n".join(batch)
    return SYSTEM, user


def whole(batch: Sequence[str], *, scope: str, focus: str | None) -> tuple[str, str]:
    """Every page in one batch: the dossier at once."""
    user = f"{scope_said(scope, focus)}\n\nLes pages :\n\n" + "\n\n---\n\n".join(batch)
    return SYSTEM, user


def synthesis(merged: dict[str, Any], *, scope: str, focus: str | None) -> tuple[str, str]:
    user = f"{scope_said(scope, focus)}\n\n{SYNTHESIS}\n\n" + json.dumps(merged, ensure_ascii=False)
    return SYSTEM, user


__all__ = ["EXTRACTION", "SYNTHESIS", "SYSTEM", "digest", "extraction", "synthesis", "whole"]
