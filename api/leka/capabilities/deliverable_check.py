"""What an agent's deliverable must hold, checked whatever model wrote it
(2026-10-22: « whatever the model, the same deliverable — or better »).

Each agent says, in its « Ce qu'il produit », the sections of its deliverable:
`1. **Verdict** — …`, `2. **Ce qui était attendu** — …`. A section that says
when it applies — « seulement s'il est ouvert », « quand des données réelles
ont été essayées », « dès que la demande est de proposer » — may be left out;
every other one is expected.

    sections()   the sections an agent's instructions expect, and which may
                 be left out
    missing()    those its deliverable lacks — said to the model, which
                 writes it again (gateway.run_tools' judge)

A deliverable in French is read section by section, by the words of each
title; in another language, by how many sections it has: the titles are
translated, never their number.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

# Where an agent says what it produces, and how it numbers its sections.
_PRODUCES = re.compile(r"^## Ce qu.il produit\s*$(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
_SECTION = re.compile(r"^(\d+)\.\s+\*\*(.+?)\*\*\s*(?:\u2014|\u2013|-|:)?\s*(.*)$", re.MULTILINE)
# How a section says it applies only sometimes.
_WHEN = re.compile(
    r"^(?:seulement|uniquement|quand|lorsque|dès que|si |s'il|pour une application|"
    r"le cas échéant|au besoin|only|when|if )",
    re.IGNORECASE,
)
# The lines of a deliverable that open a section: a heading, a bold line, a
# numbered bold line.
_OPENS = re.compile(r"^\s*(?:#{1,6}\s+.+|\*\*.+\*\*.*|\d+\.\s+\*\*.+\*\*.*)$", re.MULTILINE)
# Words that do not tell one section from another.
_SMALL = frozenset(
    {
        "le", "la", "les", "l", "un", "une", "des", "de", "du", "d", "et", "ou", "en", "a",
        "au", "aux", "ce", "qui", "que", "quoi", "il", "elle", "est", "ete", "sa", "son",
        "ses", "sur", "par", "pour", "dans", "avec", "ne", "pas", "the", "of", "and", "to",
    }
)  # fmt: skip
# Of a deliverable in another language, the share of its sections expected.
SHARE = 0.6


@dataclass(frozen=True)
class Section:
    title: str
    optional: bool


def _plain(text: str) -> list[str]:
    flat = unicodedata.normalize("NFKD", text.lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", flat)


def sections(instructions: str) -> list[Section]:
    """The sections an agent's instructions expect of its deliverable — its
    first numbered list in « Ce qu'il produit »; none when it lists none."""
    found = _PRODUCES.search(instructions or "")
    if found is None:
        return []
    said: list[Section] = []
    for number, title, rest in _SECTION.findall(found.group(1)):
        if int(number) != len(said) + 1:
            break
        said.append(Section(title.strip(), bool(_WHEN.match(rest.strip()))))
    return said


def _covers(title: str, line: str) -> bool:
    wanted = [w for w in _plain(title) if w not in _SMALL] or _plain(title)
    have = set(_plain(line))
    return sum(w in have for w in wanted) * 2 >= len(wanted)


def missing(instructions: str, deliverable: str, *, language: str = "fr") -> list[str]:
    """What the deliverable lacks of what its agent expects — said to the
    model that wrote it; nothing when it holds every section."""
    expected = [s for s in sections(instructions) if not s.optional]
    if not expected:
        return []
    opened = _OPENS.findall(deliverable or "")
    if not language.lower().startswith("fr"):
        wanted = math.ceil(len(expected) * SHARE)
        if len(opened) >= wanted:
            return []
        return [
            f"The deliverable has {len(opened)} of the {len(expected)} sections its agent "
            f"must give: {', '.join(s.title for s in expected)} — each under its own title."
        ]
    lacking = [s.title for s in expected if not any(_covers(s.title, line) for line in opened)]
    if not lacking:
        return []
    return [
        "The deliverable lacks these sections, each to write under its own title: "
        + ", ".join(f"« {t} »" for t in lacking)
        + ". A section with nothing to say says so in one line."
    ]


__all__ = ["SHARE", "Section", "missing", "sections"]
