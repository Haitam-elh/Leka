"""The architecture dossier the architect delivers — structured as ArchiMate
3: its business, application and technology layers, their elements, the
relations between them, the flows — every section citing the Confluence
pages it was read from.

    Dossier          the whole document
    Section          one layer, or the flows, the dependencies, the points to
                     confirm: what it says, its elements, its evidence
    Element          one ArchiMate element: its type, its name, what it is
    Relation         one ArchiMate relation between two elements
    Evidence         one page cited: its title, its link

`dossier_of()` reads what a model answered — JSON, as SCHEMA asks — and
keeps only what holds: an element of a type ArchiMate has, a relation
between two elements the dossier holds, a page the model was given. What it
drops is said (`dropped`): never silently.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .pages import Page

# The sections, in reading order — what « structured ArchiMate » means here.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("synthese", "Synthèse"),
    ("metier", "Couche métier"),
    ("application", "Couche application"),
    ("technologie", "Couche technologie"),
    ("flux", "Flux et échanges"),
    ("dependances", "Dépendances"),
    ("points", "Points à confirmer"),
)
LAYERS = ("metier", "application", "technologie")

# The ArchiMate 3.1 element types of each layer, as the model may name them.
ELEMENT_TYPES: dict[str, tuple[str, ...]] = {
    "metier": (
        "Acteur métier",
        "Rôle métier",
        "Processus métier",
        "Fonction métier",
        "Événement métier",
        "Service métier",
        "Objet métier",
        "Interface métier",
    ),
    "application": (
        "Composant applicatif",
        "Service applicatif",
        "Interface applicative",
        "Fonction applicative",
        "Processus applicatif",
        "Objet de données",
    ),
    "technologie": (
        "Nœud",
        "Logiciel système",
        "Service technologique",
        "Interface technologique",
        "Réseau de communication",
        "Artefact",
        "Équipement",
    ),
}
RELATION_TYPES = (
    "Composition",
    "Agrégation",
    "Affectation",
    "Réalisation",
    "Service",
    "Accès",
    "Influence",
    "Déclenchement",
    "Flux",
    "Spécialisation",
    "Association",
)


@dataclass(frozen=True)
class Evidence:
    page_id: str
    title: str
    url: str = ""


@dataclass(frozen=True)
class Element:
    id: str
    layer: str
    type: str
    name: str
    description: str = ""
    evidence: tuple[Evidence, ...] = ()
    to_confirm: bool = False


@dataclass(frozen=True)
class Relation:
    source: str
    target: str
    type: str
    label: str = ""
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    summary: str = ""
    evidence: tuple[Evidence, ...] = ()


@dataclass
class Dossier:
    title: str
    scope: str
    sections: list[Section] = field(default_factory=list)
    elements: list[Element] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    points: list[str] = field(default_factory=list)
    pages_read: list[Evidence] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    def section(self, key: str) -> Section | None:
        return next((s for s in self.sections if s.key == key), None)

    def of_layer(self, layer: str) -> list[Element]:
        return [e for e in self.elements if e.layer == layer]

    def element(self, element_id: str) -> Element | None:
        return next((e for e in self.elements if e.id == element_id), None)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Dossier:
        """A dossier as to_json() wrote it — read back, its evidence with it."""

        def cited(said: Any) -> tuple[Evidence, ...]:
            return tuple(
                Evidence(str(e.get("page_id", "")), str(e.get("title", "")), str(e.get("url", "")))
                for e in said or []
                if isinstance(e, dict)
            )

        return cls(
            title=str(data.get("title") or ""),
            scope=str(data.get("scope") or ""),
            sections=[
                Section(
                    str(s["key"]),
                    str(s.get("title") or s["key"]),
                    str(s.get("summary") or ""),
                    cited(s.get("evidence")),
                )
                for s in data.get("sections") or []
                if isinstance(s, dict) and s.get("key")
            ],
            elements=[
                Element(
                    str(e["id"]),
                    str(e.get("layer") or ""),
                    str(e.get("type") or ""),
                    str(e.get("name") or ""),
                    str(e.get("description") or ""),
                    cited(e.get("evidence")),
                    bool(e.get("to_confirm")),
                )
                for e in data.get("elements") or []
                if isinstance(e, dict) and e.get("id")
            ],
            relations=[
                Relation(
                    str(r.get("source") or ""),
                    str(r.get("target") or ""),
                    str(r.get("type") or ""),
                    str(r.get("label") or ""),
                    cited(r.get("evidence")),
                )
                for r in data.get("relations") or []
                if isinstance(r, dict)
            ],
            points=[str(p) for p in data.get("points") or []],
            pages_read=list(cited(data.get("pages_read"))),
            dropped=[str(d) for d in data.get("dropped") or []],
        )

    def to_json(self) -> dict[str, Any]:
        def cited(evidence: Iterable[Evidence]) -> list[dict[str, str]]:
            return [{"page_id": e.page_id, "title": e.title, "url": e.url} for e in evidence]

        return {
            "title": self.title,
            "scope": self.scope,
            "sections": [
                {
                    "key": s.key,
                    "title": s.title,
                    "summary": s.summary,
                    "evidence": cited(s.evidence),
                }
                for s in self.sections
            ],
            "elements": [
                {
                    "id": e.id,
                    "layer": e.layer,
                    "type": e.type,
                    "name": e.name,
                    "description": e.description,
                    "to_confirm": e.to_confirm,
                    "evidence": cited(e.evidence),
                }
                for e in self.elements
            ],
            "relations": [
                {
                    "source": r.source,
                    "target": r.target,
                    "type": r.type,
                    "label": r.label,
                    "evidence": cited(r.evidence),
                }
                for r in self.relations
            ],
            "points": list(self.points),
            "pages_read": cited(self.pages_read),
            "dropped": list(self.dropped),
        }


# What the model is asked to answer: one JSON object, its pages by id.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["title", "sections", "elements", "relations", "points"],
    "properties": {
        "title": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "summary", "pages"],
                "properties": {
                    "key": {"type": "string", "enum": [key for key, _ in SECTIONS]},
                    "summary": {"type": "string"},
                    "pages": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "layer", "type", "name", "pages"],
                "properties": {
                    "id": {"type": "string"},
                    "layer": {"type": "string", "enum": list(LAYERS)},
                    "type": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "to_confirm": {"type": "boolean"},
                    "pages": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source", "target", "type"],
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "type": {"type": "string", "enum": list(RELATION_TYPES)},
                    "label": {"type": "string"},
                    "pages": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "points": {"type": "array", "items": {"type": "string"}},
    },
}

_FENCED = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


class DossierError(ValueError):
    """What a model answered is not a dossier: said why."""


def parsed(answer: str) -> dict[str, Any]:
    """The JSON object of an answer — bare, or fenced in a code block."""
    text = answer.strip()
    fenced = _FENCED.search(text)
    if fenced:
        text = fenced.group(1)
    elif not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise DossierError("no JSON object in the answer")
        text = text[start : end + 1]
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise DossierError(f"the answer is not JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise DossierError("the answer is not a JSON object")
    return value


def _text(value: Any, limit: int = 4000) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) else ""


def _type_of(layer: str, said: str) -> str | None:
    """Its ArchiMate type, as the layer knows it — case and accents aside."""

    def plain(text: str) -> str:
        return text.lower().replace("é", "e").replace("è", "e").replace("œ", "oe").strip()

    for known in ELEMENT_TYPES[layer]:
        if plain(known) == plain(said):
            return known
    return None


def dossier_of(answer: str | Mapping[str, Any], pages: Sequence[Page], *, scope: str) -> Dossier:
    """The dossier a model answered, kept to what holds — DossierError when
    nothing does."""
    raw = parsed(answer) if isinstance(answer, str) else dict(answer)
    known = {page.id: page for page in pages}
    dropped: list[str] = []

    def cited(ids: Any, where: str) -> tuple[Evidence, ...]:
        found: list[Evidence] = []
        for page_id in ids if isinstance(ids, list) else []:
            page = known.get(str(page_id))
            if page is None:
                dropped.append(f"{where} : page {page_id} citée mais non lue")
                continue
            if all(e.page_id != page.id for e in found):
                found.append(Evidence(page.id, page.title, page.url))
        return tuple(found)

    titles = dict(SECTIONS)
    sections: list[Section] = []
    for said in raw.get("sections") or []:
        if not isinstance(said, dict) or said.get("key") not in titles:
            continue
        key = str(said["key"])
        if any(s.key == key for s in sections):
            continue
        sections.append(
            Section(
                key, titles[key], _text(said.get("summary")), cited(said.get("pages"), titles[key])
            )
        )
    sections.sort(key=lambda s: [k for k, _ in SECTIONS].index(s.key))

    elements: list[Element] = []
    for said in raw.get("elements") or []:
        if not isinstance(said, dict):
            continue
        layer, name = str(said.get("layer", "")), _text(said.get("name"), 300)
        if layer not in LAYERS or not name:
            dropped.append(f"élément « {name or '?'} » : couche inconnue")
            continue
        kind = _type_of(layer, str(said.get("type", "")))
        if kind is None:
            dropped.append(f"élément « {name} » : type « {said.get('type')} » hors ArchiMate")
            continue
        element_id = _text(said.get("id"), 120) or f"{layer}-{len(elements) + 1}"
        if any(e.id == element_id for e in elements):
            element_id = f"{element_id}-{len(elements) + 1}"
        evidence = cited(said.get("pages"), f"élément « {name} »")
        elements.append(
            Element(
                element_id,
                layer,
                kind,
                name,
                _text(said.get("description"), 1000),
                evidence,
                # Nothing read says it: to confirm, whatever the model said.
                bool(said.get("to_confirm")) or not evidence,
            )
        )
    ids = {e.id for e in elements}
    relations: list[Relation] = []
    for said in raw.get("relations") or []:
        if not isinstance(said, dict):
            continue
        source, target = str(said.get("source", "")), str(said.get("target", ""))
        kind = str(said.get("type", ""))
        if source not in ids or target not in ids:
            dropped.append(f"relation {source} → {target} : élément absent du dossier")
            continue
        if kind not in RELATION_TYPES:
            dropped.append(f"relation {source} → {target} : type « {kind} » hors ArchiMate")
            continue
        relations.append(
            Relation(
                source,
                target,
                kind,
                _text(said.get("label"), 300),
                cited(said.get("pages"), f"relation {source} → {target}"),
            )
        )
    points = [_text(p, 500) for p in raw.get("points") or [] if _text(p, 500)]
    if not elements and not sections:
        raise DossierError("the answer holds no section and no element")
    used = {e.page_id for s in sections for e in s.evidence} | {
        e.page_id for el in elements for e in el.evidence
    }
    return Dossier(
        title=_text(raw.get("title"), 300) or "Dossier d'architecture applicative",
        scope=scope,
        sections=sections,
        elements=elements,
        relations=relations,
        points=points,
        pages_read=[Evidence(p.id, p.title, p.url) for p in pages if p.id in used],
        dropped=dropped,
    )


def problems(dossier: Dossier) -> list[str]:
    """What a dossier lacks to be whole: a section missing, a section or
    an element that cites nothing. Empty: it is whole."""
    said: list[str] = []
    for key, title in SECTIONS:
        section = dossier.section(key)
        if section is None:
            said.append(f"section manquante : {title}")
        elif key not in ("points", "synthese") and not section.evidence:
            said.append(f"section sans preuve : {title}")
    for element in dossier.elements:
        if not element.evidence:
            said.append(f"élément sans preuve : {element.name}")
    return said


__all__ = [
    "ELEMENT_TYPES",
    "LAYERS",
    "RELATION_TYPES",
    "SCHEMA",
    "SECTIONS",
    "Dossier",
    "DossierError",
    "Element",
    "Evidence",
    "Relation",
    "Section",
    "dossier_of",
    "parsed",
    "problems",
]
