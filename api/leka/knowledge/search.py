"""Finding things in the company model by what they are called (LEKA-369).

Each entity carries two texts for search, written at each build:

    search_name   its name, and what else it is called: a display name,
                  a repository's short name — each once, NAMES_APART
    search_text   what else says what it is: its key's words, its
                  description, an email, a title, labels, topics, languages,
                  where it runs, of what class it is

both FOLDED — lower case, accents off, ligatures opened, words split at
whatever is not a letter or a digit, of any script — so "Équipe Données" is
found by "equipe donnees", main-d'œuvre by "oeuvre", nora@acme.io by
"nora". A word's case changes are not where it breaks — PostgreSQL is
"postgresql", GitHub "github" — but its pieces are words too, in the text:
PaymentApi is found by "paymentapi", by "payment api" and by "api".

PostgreSQL's full-text search reads them (docs/adr/001-postgresql.md: no
second store): the 'simple' dictionary — no stemming, names are not prose
and the company speaks French and English — the name weighted A, the rest
B. Every word typed is a prefix: "pay" finds Payment API as it is typed.

Pure: the build calls fields(), the repository query() — and any_of(),
for a sentence searched by any of its words (leka.context, LEKA-371).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping

# What a query keeps: past this many words, the rest says nothing more.
MAX_WORDS = 8
# What a sentence is searched by, at most: its words and their synonyms
# (leka.context, LEKA-371).
MAX_ANY = 24
# A search text's length, at most: a description is read for its words, not
# kept whole.
MAX_TEXT = 4000
MAX_DESCRIPTION = 1500

# The attributes whose words say what a thing is.
SAID = (
    "email",
    "title",
    "department",
    "job_title",
    "category",
    "service_type",
    "resource_class",
    "resource_type",
    "engine",
    "provider",
    "region",
    "environment",
    "language",
    "classification",
    "object_type",
)
LISTED = ("labels", "topics", "components", "languages", "environments", "tags")

# Where a word's case changes: paymentApi, HTTPResponse.
_CASE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# What separates words: anything but a letter or a digit — of any script,
# so that Москва and 東京 are words — and the underscore.
_NOT_A_WORD = re.compile(r"[\W_]+")
# Between an entity's names: no folded word holds it, and PostgreSQL's
# parser reads it as a space — the repository finds the very name typed
# among them.
NAMES_APART = " | "
# The letters NFKD does not take apart: main-d'œuvre is found by "oeuvre".
_LIGATURES = str.maketrans({"œ": "oe", "æ": "ae", "ß": "ss", "ø": "o", "ł": "l", "đ": "d"})


def fold(text: str, *, cases: bool = False) -> str:
    """Lower case, accents off, one space between words: "Équipe
    Données" → "equipe donnees", "PaymentAPI/v2" → "paymentapi v2" — and
    "payment api v2" when its case changes break words too (`cases`)."""
    split = _CASE.sub(" ", text) if cases else text
    plain = "".join(c for c in unicodedata.normalize("NFKD", split) if not unicodedata.combining(c))
    return _NOT_A_WORD.sub(" ", plain.lower().translate(_LIGATURES)).strip()


def pieces(text: str, besides: Iterable[str] = ()) -> list[str]:
    """The words a text's case changes make, that its words are not:
    "postgre" and "sql" of PostgreSQL — none of `besides`."""
    known = {*fold(text).split(), *besides}
    return [word for word in dict.fromkeys(fold(text, cases=True).split()) if word not in known]


def fields(key: str, name: str, attributes: Mapping[str, object]) -> tuple[str, str]:
    """An entity's two search texts: its names, and what else says what
    it is."""
    names = [name]
    display = attributes.get("display_name")
    if isinstance(display, str):
        names.append(display)
    # A repository's own name: payment-api of acme/payment-api.
    if "/" in name:
        names.append(name.rsplit("/", 1)[-1])
    # Each name once — the name and its display name often fold alike —
    # apart: the very name typed weighs most (repository.search).
    folded = [one for one in dict.fromkeys(fold(n) for n in names) if one]
    said: list[str] = [key]
    description = attributes.get("description")
    if isinstance(description, str):
        said.append(description[:MAX_DESCRIPTION])
    for attribute in SAID:
        value = attributes.get(attribute)
        if isinstance(value, str):
            said.append(value)
    for attribute in LISTED:
        value = attributes.get(attribute)
        if isinstance(value, list):
            said += [v for v in value if isinstance(v, str)]
    text = " ".join(said)
    named = NAMES_APART.join(folded)
    # The pieces last: a text cut short loses them before its own words.
    words = [fold(text), *pieces(" ".join(names), " ".join(folded).split()), *pieces(text)]
    return named[:MAX_TEXT], " ".join(w for w in words if w)[:MAX_TEXT]


def any_of(words: Iterable[str]) -> str | None:
    """Words, any of them, each a prefix, as a tsquery: what a sentence is
    searched by — "why is billing slow" — the more of them a thing holds,
    the higher it ranks. None when none is searchable."""
    kept = list(dict.fromkeys(w for word in words for w in fold(word).split()))[:MAX_ANY]
    return " | ".join(f"{word}:*" for word in kept) or None


def query(typed: str) -> str | None:
    """What was typed, as a tsquery: every word a prefix, all of them
    needed — or, where its case changes break words, all of those —
    None when nothing searchable was typed. Folded words are letters and
    digits only, of any script: nothing in them is tsquery syntax."""
    whole = fold(typed).split()[:MAX_WORDS]
    if not whole:
        return None
    split = fold(typed, cases=True).split()[:MAX_WORDS]
    found = " & ".join(f"{word}:*" for word in whole)
    if split == whole:
        return found
    return f"({found}) | ({' & '.join(f'{word}:*' for word in split)})"
