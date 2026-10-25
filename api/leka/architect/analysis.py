"""The architect's analysis — its steps, the same on LEKA and wherever it is
installed:

    1. the pages of the perimeter: a space, or a page and everything under it
    2. each shown as it is read (prompts.digest), in batches a model can read
    3. one batch: the dossier at once
       several: each batch's part of it, then the parts merged — the same
       element named twice kept once, its pages together — and the dossier
       written whole from them (prompts.synthesis)
    4. kept to what holds (model.dossier_of): ArchiMate's types, pages read

`analyse()` asks a model the way a terminal does, one call after another;
`analyse_async()` the way LEKA's workers do. The steps are the same
functions: the two never differ in what they ask.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from . import prompts
from .model import Dossier, DossierError, dossier_of, parsed
from .pages import Page, Tree

Ask = Callable[[str, str], str]
AskAsync = Callable[[str, str], Awaitable[str]]
Said = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class Budget:
    """What one call reads at most: a page cut beyond `page_chars`, a batch
    of pages up to `call_chars` — and `max_pages` pages in all."""

    page_chars: int = 12_000
    call_chars: int = 90_000
    max_pages: int = 600


def perimeter(tree: Tree, root: str | None) -> list[Page]:
    """The pages it reads, in reading order: `root` and everything under it,
    or the whole space."""
    return tree.under(root)


def batches(pages: Sequence[Page], tree: Tree, budget: Budget) -> list[list[str]]:
    """The pages as the model reads them, cut into batches it can read."""
    found: list[list[str]] = []
    current: list[str] = []
    size = 0
    for page in pages[: budget.max_pages]:
        text = prompts.digest(page, tree, budget.page_chars)
        if current and size + len(text) > budget.call_chars:
            found.append(current)
            current, size = [], 0
        current.append(text)
        size += len(text)
    if current:
        found.append(current)
    return found


def _key(element: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(element.get("layer", "")),
        str(element.get("type", "")).lower(),
        " ".join(str(element.get("name", "")).lower().split()),
    )


def merge(parts: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The batches' parts as one: an element named the same in the same layer
    kept once, its pages together; each relation once; each section's
    summaries, part by part, with all their pages."""
    elements: dict[tuple[str, str, str], dict[str, Any]] = {}
    sections: dict[str, dict[str, Any]] = {}
    relations: dict[tuple[str, str, str], dict[str, Any]] = {}
    points: list[str] = []
    for n, part in enumerate(parts):
        renamed: dict[str, str] = {}
        for element in part.get("elements") or []:
            if not isinstance(element, dict):
                continue
            key = _key(element)
            local = str(element.get("id", ""))
            kept = elements.get(key)
            if kept is None:
                kept = {**element, "id": f"p{n}-{local}" if local else f"p{n}-{len(elements)}"}
                kept["pages"] = list(element.get("pages") or [])
                elements[key] = kept
            else:
                kept["pages"] = list(dict.fromkeys([*kept["pages"], *(element.get("pages") or [])]))
                if len(str(element.get("description", ""))) > len(str(kept.get("description", ""))):
                    kept["description"] = element.get("description")
                kept["to_confirm"] = bool(kept.get("to_confirm")) and bool(
                    element.get("to_confirm")
                )
            renamed[local] = kept["id"]
        for relation in part.get("relations") or []:
            if not isinstance(relation, dict):
                continue
            source = renamed.get(str(relation.get("source", "")))
            target = renamed.get(str(relation.get("target", "")))
            if source is None or target is None:
                continue
            key = (source, target, str(relation.get("type", "")))
            kept = relations.setdefault(
                key, {**relation, "source": source, "target": target, "pages": []}
            )
            kept["pages"] = list(dict.fromkeys([*kept["pages"], *(relation.get("pages") or [])]))
        for section in part.get("sections") or []:
            if not isinstance(section, dict) or not section.get("key"):
                continue
            kept = sections.setdefault(
                str(section["key"]), {"key": section["key"], "summaries": [], "pages": []}
            )
            if section.get("summary"):
                kept["summaries"].append(str(section["summary"]))
            kept["pages"] = list(dict.fromkeys([*kept["pages"], *(section.get("pages") or [])]))
        for point in part.get("points") or []:
            if isinstance(point, str) and point not in points:
                points.append(point)
    return {
        "sections": list(sections.values()),
        "elements": list(elements.values()),
        "relations": list(relations.values()),
        "points": points,
    }


def _completed(final: dict[str, Any], merged: dict[str, Any]) -> dict[str, Any]:
    """The written dossier, its elements and relations the merged ones when
    the model left them out, its points with every part's."""
    done = dict(final)
    if not done.get("elements"):
        done["elements"] = merged["elements"]
        done["relations"] = merged["relations"]
    done["points"] = list(dict.fromkeys([*(done.get("points") or []), *merged["points"]]))
    return done


def _retold(user: str, error: DossierError) -> str:
    return (
        f"{user}\n\nTa réponse précédente n'a pas pu être lue ({error}). "
        "Réponds par l'objet JSON seul, selon le schéma."
    )


def analyse(
    ask: Ask,
    pages: Sequence[Page],
    *,
    scope: str,
    focus: str | None = None,
    budget: Budget | None = None,
    said: Said | None = None,
) -> Dossier:
    """The dossier of these pages — one call after another."""
    budget = budget or Budget()
    tree = Tree(pages)
    read = list(pages[: budget.max_pages])
    cut = batches(read, tree, budget)
    if not cut:
        raise DossierError("no page to read")

    def asked(system: str, user: str) -> dict[str, Any]:
        try:
            return parsed(ask(system, user))
        except DossierError as error:
            return parsed(ask(system, _retold(user, error)))

    if said:
        said("pages", {"pages": len(read), "batches": len(cut)})
    if len(cut) == 1:
        answer = asked(*prompts.whole(cut[0], scope=scope, focus=focus))
        return dossier_of(answer, read, scope=scope)
    parts = []
    for n, batch in enumerate(cut, 1):
        parts.append(asked(*prompts.extraction(batch, scope=scope, focus=focus)))
        if said:
            said("batch", {"batch": n, "of": len(cut)})
    merged = merge(parts)
    final = asked(*prompts.synthesis(merged, scope=scope, focus=focus))
    return dossier_of(_completed(final, merged), read, scope=scope)


async def analyse_async(
    ask: AskAsync,
    pages: Sequence[Page],
    *,
    scope: str,
    focus: str | None = None,
    budget: Budget | None = None,
    said: Said | None = None,
) -> Dossier:
    """The dossier of these pages — the same steps, awaited."""
    budget = budget or Budget()
    tree = Tree(pages)
    read = list(pages[: budget.max_pages])
    cut = batches(read, tree, budget)
    if not cut:
        raise DossierError("no page to read")

    async def asked(system: str, user: str) -> dict[str, Any]:
        try:
            return parsed(await ask(system, user))
        except DossierError as error:
            return parsed(await ask(system, _retold(user, error)))

    if said:
        said("pages", {"pages": len(read), "batches": len(cut)})
    if len(cut) == 1:
        answer = await asked(*prompts.whole(cut[0], scope=scope, focus=focus))
        return dossier_of(answer, read, scope=scope)
    parts = []
    for n, batch in enumerate(cut, 1):
        parts.append(await asked(*prompts.extraction(batch, scope=scope, focus=focus)))
        if said:
            said("batch", {"batch": n, "of": len(cut)})
    merged = merge(parts)
    final = await asked(*prompts.synthesis(merged, scope=scope, focus=focus))
    return dossier_of(_completed(final, merged), read, scope=scope)


__all__ = ["Budget", "analyse", "analyse_async", "batches", "merge", "perimeter"]
