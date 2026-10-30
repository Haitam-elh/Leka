"""The languages LEKA offers, read from languages.yaml — the one source of
truth — and checked when they are read.

    match(tag)               the catalogue's language for a tag as a browser
                             or a person says it: zh-TW is Traditional
                             Chinese, pt-BR Portuguese, iw Hebrew
    negotiate(header)        the first language of an Accept-Language header
                             LEKA offers
    chain(tag, workspace=)   where a missing translation is looked up next:
                             the language, its parent, its base, the
                             workspace's, then English
    shown(surface, tag, workspace=)
                             the language a surface actually speaks for that
                             person — the first of the chain translated there
    locale(tag, region)      the formatting locale: pt + BR → pt-BR

A language and a region are two settings: the region formats dates,
numbers and currencies, and never chooses the language.

Pure: no database, no network. The web reads the same catalogue from
web/public/languages.json, which `python -m leka.core.languages` writes.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

CATALOGUE_FILE = Path(__file__).resolve().parent / "languages.yaml"
# Every word of the interface in English, flat — "nav.home": "Home" — as
# web/ writes it from its dictionary (`npm run i18n:export`): what LEKA
# translates into a language that has no dictionary (2026-10-30).
INTERFACE_FILE = Path(__file__).resolve().parent / "interface_en.json"

Surface = Literal["app", "site", "emails"]
SURFACES: tuple[Surface, ...] = ("app", "site", "emails")
Status = Literal["reviewed", "translated", "partial"]
Direction = Literal["ltr", "rtl"]

# Scripts written right to left (ISO 15924).
RTL_SCRIPTS = frozenset({"Arab", "Hebr", "Thaa", "Syrc", "Nkoo", "Adlm", "Rohg", "Mand"})

# BCP 47, as far as LEKA reads it: a language (2 or 3 letters), an optional
# script (4 letters), an optional region (2 letters or 3 digits), then
# variants. Extensions and private use are not languages anyone picks.
_TAG = re.compile(
    r"^(?P<language>[a-z]{2,3})"
    r"(?:-(?P<script>[a-z]{4}))?"
    r"(?:-(?P<region>[a-z]{2}|\d{3}))?"
    r"(?:-(?:[a-z\d]{5,8}|\d[a-z\d]{3}))*$"
)
_QUALITY = re.compile(r"^q=(?P<q>0(?:\.\d{0,3})?|1(?:\.0{0,3})?)$")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Language(_Model):
    tag: str
    english: str = Field(min_length=1)
    native: str = Field(min_length=1)
    script: str = Field(pattern=r"^[A-Z][a-z]{3}$")
    dir: Direction = "ltr"
    parent: str | None = None
    ai: Literal["strong", "good", "limited"]
    ui: dict[Surface, Status] = Field(default_factory=dict)


class Catalogue(_Model):
    version: date
    default: str
    languages: tuple[Language, ...]
    aliases: dict[str, str]
    regions: tuple[str, ...]

    @model_validator(mode="after")
    def _coherent(self) -> Catalogue:
        tags = [language.tag for language in self.languages]
        if len(set(tags)) != len(tags):
            msg = "a language is listed twice"
            raise ValueError(msg)
        known = set(tags)
        for language in self.languages:
            parts = _TAG.match(language.tag.lower())
            if parts is None or canonical(language.tag) != language.tag:
                msg = f"{language.tag}: not a canonical BCP 47 tag"
                raise ValueError(msg)
            if parts["region"]:
                msg = f"{language.tag}: a region is a setting of its own, never part of a language"
                raise ValueError(msg)
            if (language.dir == "rtl") != (language.script in RTL_SCRIPTS):
                msg = f"{language.tag}: {language.script} is not written {language.dir}"
                raise ValueError(msg)
            if language.parent is not None and (
                language.parent not in known or language.parent == language.tag
            ):
                msg = f"{language.tag}: parent {language.parent} is not another listed language"
                raise ValueError(msg)
        for alias, target in self.aliases.items():
            if canonical(alias) != alias or alias in known or target not in known:
                msg = f"alias {alias} → {target}: an alias names a language the catalogue lists"
                raise ValueError(msg)
        if self.default not in known:
            msg = f"the default {self.default} is not listed"
            raise ValueError(msg)
        last = next(language for language in self.languages if language.tag == self.default)
        if any(last.ui.get(surface) != "reviewed" for surface in SURFACES):
            # Every chain ends here: it must have every word, approved.
            msg = f"the default {self.default} is not reviewed on every surface"
            raise ValueError(msg)
        if len(set(self.regions)) != len(self.regions) or not all(
            re.fullmatch(r"[A-Z]{2}", region) for region in self.regions
        ):
            msg = "regions are ISO 3166-1 alpha-2 codes, each once"
            raise ValueError(msg)
        return self


@cache
def catalogue() -> Catalogue:
    with CATALOGUE_FILE.open(encoding="utf-8") as stream:
        return Catalogue.model_validate(yaml.safe_load(stream))


@cache
def _by_tag() -> dict[str, Language]:
    return {language.tag: language for language in catalogue().languages}


def canonical(tag: str) -> str | None:
    """A tag in BCP 47's canonical case — fr, zh-Hant, pt-BR — or None when
    it is not one. Underscores, as some systems write them, are read as
    hyphens."""
    lowered = tag.strip().replace("_", "-").lower()
    parts = _TAG.match(lowered)
    if parts is None:
        return None
    out = [parts["language"]]
    rest = lowered.split("-")[1:]
    if parts["script"]:
        out.append(parts["script"].title())
        rest = rest[1:]
    if parts["region"]:
        out.append(parts["region"].upper())
        rest = rest[1:]
    return "-".join([*out, *rest])


def language(tag: str) -> Language | None:
    """The catalogue's entry for exactly this tag."""
    return _by_tag().get(tag)


def match(tag: str) -> Language | None:
    """The language LEKA offers for a tag as said anywhere — a browser, an
    old system, a person — or None when it offers none.

    Longest first, and an alias before the tag's own base: fa-AF is Dari,
    not Persian, and zh-TW Traditional Chinese, not "zh".
    """
    said = canonical(tag)
    if said is None:
        return None
    parts = said.split("-")
    aliases = catalogue().aliases
    for length in range(len(parts), 0, -1):
        candidate = "-".join(parts[:length])
        if candidate in aliases:
            return _by_tag()[aliases[candidate]]
        if candidate in _by_tag():
            return _by_tag()[candidate]
    return None


def listed(tag: str) -> str:
    """The catalogue's own tag for a language a person picked — fr, zh-Hant
    — or ValueError: what is stored is always one LEKA offers."""
    said = canonical(tag)
    if said is None or said not in _by_tag():
        msg = f"{tag!r} is not a language LEKA offers"
        raise ValueError(msg)
    return said


def listed_region(region: str) -> str:
    """An ISO 3166-1 country the catalogue lists, upper case — or ValueError."""
    said = region.strip().upper()
    if said not in catalogue().regions:
        msg = f"{region!r} is not a region"
        raise ValueError(msg)
    return said


def region_of(tag: str) -> str | None:
    """The region a tag carries, when the catalogue lists it: pt-BR → BR."""
    said = canonical(tag)
    if said is None:
        return None
    parts = _TAG.match(said.lower())
    region = parts["region"].upper() if parts and parts["region"] else None
    return region if region in catalogue().regions else None


def preferences(header: str | None) -> list[str]:
    """An Accept-Language header's tags, most wanted first, in the order
    given when equally wanted. A tag refused (q=0) and the wildcard are
    left out; a malformed part is skipped, not fatal."""
    weighted: list[tuple[float, int, str]] = []
    for position, part in enumerate((header or "").split(",")):
        pieces = [piece.strip() for piece in part.split(";")]
        tag, quality = pieces[0], 1.0
        for parameter in pieces[1:]:
            said = _QUALITY.match(parameter.replace(" ", ""))
            if said is None:
                tag = ""
                break
            quality = float(said["q"])
        if not tag or tag == "*" or quality <= 0:
            continue
        weighted.append((-quality, position, tag))
    return [tag for _, _, tag in sorted(weighted)]


def negotiate(said: str | Iterable[str] | None) -> Language | None:
    """The first language of a person's preferences LEKA offers — from an
    Accept-Language header, or from a browser's list."""
    tags = preferences(said) if isinstance(said, str) or said is None else list(said)
    for tag in tags:
        found = match(tag)
        if found is not None:
            return found
    return None


def chain(tag: str, *, workspace: str | None = None) -> list[str]:
    """Where a missing translation is looked up, in order, each once: the
    language, its parents, its base language, the workspace's language,
    then the catalogue's default."""
    out: list[str] = []

    def add(candidate: str | None) -> None:
        while candidate is not None and candidate not in out and candidate in _by_tag():
            out.append(candidate)
            candidate = _by_tag()[candidate].parent

    add(tag)
    add(tag.split("-")[0])
    add(workspace)
    add(catalogue().default)
    return out


def status(surface: Surface, tag: str) -> Status | None:
    """How far a surface is translated into a language: reviewed,
    translated, or None — not translated."""
    found = _by_tag().get(tag)
    return found.ui.get(surface) if found else None


def shown(surface: Surface, tag: str | None, *, workspace: str | None = None) -> str:
    """The language a surface speaks to a person who chose `tag`: the first
    of its chain translated there. Never empty: the default is reviewed
    everywhere."""
    start = tag if tag is not None and tag in _by_tag() else (workspace or catalogue().default)
    for candidate in chain(start, workspace=workspace):
        if status(surface, candidate) is not None:
            return candidate
    return catalogue().default  # pragma: no cover - the default is reviewed everywhere


def direction(tag: str) -> Direction:
    found = _by_tag().get(tag)
    return found.dir if found else "ltr"


def locale(tag: str, region: str | None = None) -> str:
    """The locale that formats for a language in a region: pt + BR →
    pt-BR, zh-Hant + HK → zh-Hant-HK, fr alone → fr."""
    return f"{tag}-{region}" if region else tag


def describe(tag: str) -> str:
    """A language as a language model is told it: "French (Français, fr)"."""
    found = _by_tag().get(tag) or _by_tag()[catalogue().default]
    if found.native == found.english:
        return f"{found.english} ({found.tag})"
    return f"{found.english} ({found.native}, {found.tag})"


def writing_rule(tag: str) -> str:
    """What a language model is told about the language to write in: the
    person's (or, for what a workspace shares, the workspace's) — whatever
    language the question, the context or the sources are in — unless the
    request itself asks for another. Whichever model, whichever provider."""
    return (
        f"Write every word meant to be read in {describe(tag)}, whatever language the "
        "question, the context or the sources are in. Names, ids, quotations and code "
        "stay as they are. If the request itself explicitly asks for another language, "
        "write in that one."
    )


@cache
def interface_english() -> dict[str, str]:
    """The interface's words in English, by key, in the dictionary's order."""
    with INTERFACE_FILE.open(encoding="utf-8") as stream:
        words: dict[str, str] = json.load(stream)
    return words


def export() -> dict[str, object]:
    """The catalogue as the web reads it (web/public/languages.json)."""
    return catalogue().model_dump(mode="json")


if __name__ == "__main__":
    sys.stdout.write(json.dumps(export(), ensure_ascii=False, indent=1) + "\n")
