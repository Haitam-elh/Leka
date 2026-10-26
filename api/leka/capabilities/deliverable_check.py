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

Framed (Karim, 2026-10-23: « pas que du texte d'analyse — un résumé et un
plan d'action concret et exécutable »): every markdown deliverable opens on
« Résumé » and ends on « Plan d'action » (runtime.FRAME_NOTE) — an agent's
own « Actions » section is that plan.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
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


# What frames every markdown deliverable (2026-10-23).
SUMMARY = Section("Résumé", optional=False)
PLAN = Section("Plan d'action", optional=False)


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


def expected(instructions: str, *, framed: bool = False) -> list[Section]:
    """The sections a deliverable must hold: its agent's — opened by the
    summary and closed by the action plan when framed, its own actions
    becoming that plan."""
    own = [s for s in sections(instructions) if not s.optional]
    if not framed:
        return own
    kept = [s for s in own if not {"action", "actions", "resume"} & set(_plain(s.title))]
    return [SUMMARY, *kept, PLAN]


def missing(
    instructions: str, deliverable: str, *, language: str = "fr", framed: bool = False
) -> list[str]:
    """What the deliverable lacks of what its agent expects — said to the
    model that wrote it; nothing when it holds every section."""
    expected_ = expected(instructions, framed=framed)
    if not expected_:
        return []
    opened = _OPENS.findall(deliverable or "")
    if not language.lower().startswith("fr"):
        wanted = math.ceil(len(expected_) * SHARE)
        if len(opened) >= wanted:
            return []
        return [
            f"The deliverable has {len(opened)} of the {len(expected_)} sections its agent "
            f"must give: {', '.join(s.title for s in expected_)} — each under its own title."
        ]
    lacking = [s.title for s in expected_ if not any(_covers(s.title, line) for line in opened)]
    if not lacking:
        return []
    return [
        "The deliverable lacks these sections, each to write under its own title: "
        + ", ".join(f"« {t} »" for t in lacking)
        + ". A section with nothing to say says so in one line."
    ]


# A file and its line, as a deliverable cites them: `api/app/main.py:42`.
_CODE = (
    "py|ts|tsx|js|jsx|mjs|cjs|go|rb|java|kt|kts|scala|cs|php|rs|swift|sql|sh|tf|"
    "yaml|yml|json|toml|ini|cfg|md|css|scss|less|html|vue|svelte|prisma|proto|graphql"
)
_CITED_LINE = re.compile(
    rf"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:{_CODE})):(\d+)(?:[-\u2013](\d+))?\b"
)


def unread(deliverable: str, files: Mapping[str, str]) -> list[str]:
    """The lines a deliverable cites in files the agent never read, or past
    their end (2026-10-23: `intentions.py:250`, `errors.py:100` — lines no
    one read) — said to the model, which reads them or cites the file
    alone. `files`: what it read, « owner/repo:path » → its text."""
    lines = {key.split(":", 1)[-1]: text.count("\n") + 1 for key, text in files.items()}
    wrong: list[str] = []
    for path, first, last in _CITED_LINE.findall(deliverable or ""):
        read = next((n for p, n in lines.items() if p == path or p.endswith(f"/{path}")), None)
        line = int(last or first)
        if read is None:
            wrong.append(f"{path}:{first} (never read)")
        elif line > read:
            wrong.append(f"{path}:{line} (it has {read} lines)")
    if not wrong:
        return []
    said = ", ".join(dict.fromkeys(wrong))
    return [
        f"These lines are cited but were not read: {said}. Read each file (read_file) and "
        "cite the line you read, or cite the file alone — never a line you did not read."
    ]


# A design implemented by halves: what of it an analysis puts off — « une
# étape suivante », « dans un second temps », « a follow-up ».
_DEFERRED = re.compile(
    r"(?:(?:étape|etape|phase|itération|iteration|pull request|PR|lot|passe)s?\s+"
    r"(?:suivantes?|ultérieures?|ulterieures?|prochaines?|future|à venir))"
    r"|(?:prochaine|seconde|deuxième|deuxieme)\s+(?:étape|etape|phase|pull request|PR|passe)"
    r"|dans un (?:second|deuxième|deuxieme) temps|ultérieurement|ulterieurement"
    r"|réservée?s? (?:pour|à) (?:une|la|plus)|reportée?s? (?:à|a|pour)"
    r"|(?:a |the )?(?:later|next|follow-up|future) (?:step|phase|pull request|PR|iteration|pass)"
    r"|in a (?:second|follow-up) (?:step|pass|pull request)",
    re.IGNORECASE,
)


def deferred(deliverable: str) -> list[str]:
    """What of a design to implement an analysis puts off (2026-10-24: asked
    to implement the chosen direction, the change did four classes and left
    the rest « for a later step ») — said to the model, which does it all."""
    found = _DEFERRED.search(deliverable or "")
    if found is None:
        return []
    return [
        f"Part of the design to implement is put off (« {found.group(0)} »). The whole chosen "
        "direction is asked now: change every file its mock-up changes, until the screen in "
        "the code looks like the mock-up; read a cut file to its end (read_file with "
        "from_line). Nothing of it is left for a later step."
    ]


__all__ = [
    "PLAN",
    "SHARE",
    "SUMMARY",
    "Section",
    "deferred",
    "expected",
    "missing",
    "sections",
    "unread",
]
