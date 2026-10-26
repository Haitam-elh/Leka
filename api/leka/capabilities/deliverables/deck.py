"""What an application architecture deck says — the content the architect
agent delivers, before LEKA draws it (layout.py) into a PowerPoint and a
PDF. Shaped on the agent's own template (agents/architecture/application-
architecture/SKILL.md): the business layer in ArchiMate 3.0.1, the
application layer as sequence diagrams, the rules, the RACI, the points to
confirm, the sources.

Every text is the model's, from the sources; what it could not find is
`missing` — drawn in orange, listed among the points to confirm.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# What the deck writer is told, before the agent's own instructions — on
# LEKA (delivery.py) and in the downloadable architect, which ships this file.
DECK_RULES = """You are LEKA's deck writer for the agent whose instructions \
follow. From its analysis — and from nothing else — fill the content of its \
deck, each part as its template defines it:
- Only what the analysis holds: no application, service, rule, name or \
contact of your own. What the template needs and the analysis lacks is \
`missing: true` (drawn in orange) or « À confirmer », and is one of the \
points to confirm (`controls`), with where it is (« Process C - bande 2 », \
« Transverse »).
- business: the actor (« Client » or « Conseiller », with « ? » when \
uncertain), the trigger, the source process and its channel, the groupings \
A, B, C… each with its steps — on the baseline (`branch: main`), \
alternatives above or below it.
- processes: one per grouping, same letter and label; its columns in the \
order of their first call; its bands are its phases; each line is one \
chain of calls read left to right, each call naming its column exactly.
- organisation: « <organisation> - <entite> - <service> » from the inputs, \
else as the analysis names them; empty when neither says — never invented.
- app_view: only when the inputs ask for it (vue_applicative true), else \
null; one box per application, flows aggregated, numbered in order.
- raci: one row per brick and role found; a contact is a name from the \
analysis, else « À confirmer ».
- sources: each source consulted, one row « Requêtes restées SANS \
RÉSULTAT », one row « Couche infrastructure » (« NON DOCUMENTÉ » when \
absent).
- In French, as short as the template wants it: a step in a few words, a \
service by its name and a precision in parentheses.
Answer with the JSON object only.

Never write the em dash « — »: a colon, a comma, a semicolon or \
parentheses, as the sentence needs."""


_DASH = "\u2014"
_ASIDE = re.compile(r" \u2014 ([^\u2014]{1,160}?) \u2014(?=[,.;:)\s]|$)")


_FR = re.compile(
    r"[éèêàçùôîûâ]|\b(le|la|les|des|du|de|par|pour|et|un|une|en|au|aux|sur|avec|sans)\b", re.I
)
_EN = re.compile(r"\b(the|and|of|by|for|with|without|to|in|on|an|a)\b", re.I)


def _french(text: str) -> bool:
    return len(_FR.findall(text)) >= len(_EN.findall(text))


def plain(text: str) -> str:
    """A model's « — » as the punctuation it stands for (2026-10-26: on a
    client's slide it reads as a machine's): an aside between two → in
    parentheses; one alone → a colon, or a comma where a colon came before;
    alone in a cell → « - »."""
    if _DASH not in text:
        return text
    if text.strip() == _DASH:
        return "-"
    text = _ASIDE.sub(lambda m: f" ({m.group(1).strip()})", text)
    colon = " : " if _french(text) else ": "
    head, *rest = text.split(_DASH)
    out = head.rstrip()
    for part in rest:
        tail = part.lstrip()
        if not out:
            out = tail
        elif tail[:1] in (",", ".", ";", ":", ")"):
            out += tail
        else:
            out += (", " if ":" in out.split(".")[-1] else colon) + tail
    return out


def _plained(value: Any) -> Any:
    if isinstance(value, str):
        return plain(value)
    if isinstance(value, list):
        return [_plained(v) for v in value]
    if isinstance(value, dict):
        return {k: _plained(v) for k, v in value.items()}
    return value


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class Step(_Model):
    """One step of the business layer."""

    label: str = Field(description="L'étape, courte : « Saisit les données de carte ».")
    kind: Literal["process", "event"] = Field(
        default="process", description="process : une étape ; event : un événement métier."
    )
    # Where it sits: on the common baseline, or on a branch above / below it.
    branch: Literal["main", "above", "below"] = "main"
    missing: bool = Field(default=False, description="Absente des sources : en orange.")


class Grouping(_Model):
    """A sub-process of the journey: A, B, C…"""

    letter: str = Field(description="A, B, C…")
    label: str = Field(description="Son libellé, ex. « Initialisation du paiement ».")
    steps: list[Step] = Field(default_factory=list)


class BusinessLayer(_Model):
    actor: str = Field(description="« Client », « Conseiller », ou « Client ? » si incertain.")
    trigger: str = Field(description="L'événement déclencheur, ex. « Choisit de payer par CB ».")
    process_name: str = Field(description="Le nom du processus source.")
    channel: str = Field(description="Le canal, ex. « Espace Client ».")
    groupings: list[Grouping] = Field(default_factory=list)


class Overview(_Model):
    """« Le parcours en clair »: six paragraphs."""

    objectif: str = ""
    declencheur_acteurs: str = ""
    deroule: str = ""
    regles_cles: str = ""
    donnees_flux: str = ""
    points_attention: str = ""


class Rule(_Model):
    etape: str = Field(description="« A - … » ou « Transverse - … ».")
    regle: str
    exception: str = ""
    source: str = ""
    statut: Literal["Documenté", "À confirmer"] = "À confirmer"


class Column(_Model):
    """A brick of the application layer, as a sequence diagram column."""

    name: str = Field(description="Le nom de la brique, ex. « NEXUS ».")
    subtitle: str = Field(default="", description="Précision, ex. « middleware d'échanges ».")
    missing: bool = Field(default=False, description="Brique non documentée : en-tête orange.")


class Call(_Model):
    """A service box: where it is called, and what."""

    column: str = Field(description="Le nom exact d'une colonne du process.")
    label: str = Field(description="Le service, ex. « ws_lireSolde (solde) ».")
    missing: bool = Field(default=False, description="Non documenté : boîte orange « … ? ».")


class Line(_Model):
    """One chain of calls, read left to right, started by the front."""

    calls: list[Call] = Field(default_factory=list)


class Band(_Model):
    title: str = Field(description="La phase, ex. « Vérification du solde ».")
    lines: list[Line] = Field(default_factory=list)


class ProcessView(_Model):
    """The slide of one sub-process: its application layer."""

    letter: str
    label: str
    front: str = Field(description="L'en-tête du canal Front, ex. « DIGITAL ESPACE CLIENT ».")
    front_label: str = Field(default="FRONT", description="Le libellé du bloc Front.")
    channel_label: str = Field(default="", description="Le canal sous l'en-tête Front.")
    columns: list[Column] = Field(default_factory=list)
    bands: list[Band] = Field(default_factory=list)


class Contact(_Model):
    application: str
    domaine: str = ""
    int_ext: str = Field(default="", description="« Int. », « Ext. » ou vide.")
    role: str = ""
    raci: str = Field(default="", description="R, A, C ou I.")
    contact: str = Field(default="À confirmer", description="Un nom des sources, jamais inventé.")
    coordonnees: str = ""
    source: str = ""
    statut: Literal["Documenté", "À mettre à jour", "À confirmer"] = "À confirmer"


class Control(_Model):
    manque: str
    localisation: str = ""
    question: str = ""


class SourceRow(_Model):
    source: str
    elements: str = ""
    statut: str = ""


class AppBox(_Model):
    name: str
    role: str = ""
    kind: Literal["perimetre", "connexe", "externe", "middleware", "a_confirmer"] = "perimetre"
    stores: list[str] = Field(default_factory=list)


class Flow(_Model):
    n: str = Field(description="1, 2, 1'…")
    source: str
    target: str
    interface: str = ""
    mode: Literal["sync", "async"] = "sync"
    data: str = ""
    status: Literal["Existant", "Nouveau", "À confirmer"] = "Existant"


class AppView(_Model):
    apps: list[AppBox] = Field(default_factory=list)
    flows: list[Flow] = Field(default_factory=list)


class ArchitectureDeck(_Model):
    """An application architecture deck, as the template wants it."""

    @model_validator(mode="before")
    @classmethod
    def _no_dash(cls, data: Any) -> Any:
        """Every text as drawn: no « — » (plain)."""
        return _plained(data)

    parcours: str = Field(description="Le nom du parcours, ex. « Paiement CB ».")
    organisation: str = Field(
        default="",
        description="« <Organisation> - <Entité> - <Service> » as the inputs or the sources "
        "say them; empty when they do not — never invented.",
    )
    perimetre: str = Field(
        description="« Périmètre <domaine> - <canaux / variantes> », ex. « Périmètre Digital - "
        "Espace Client »."
    )
    business: BusinessLayer
    overview: Overview = Field(default_factory=Overview)
    rules: list[Rule] = Field(default_factory=list)
    app_view: AppView | None = Field(default=None, description="La vue applicative, si demandée.")
    processes: list[ProcessView] = Field(default_factory=list)
    raci: list[Contact] = Field(default_factory=list)
    raci_notes: str = ""
    controls: list[Control] = Field(default_factory=list)
    sources: list[SourceRow] = Field(default_factory=list)


__all__ = [
    "DECK_RULES",
    "AppBox",
    "AppView",
    "ArchitectureDeck",
    "Band",
    "BusinessLayer",
    "Call",
    "Column",
    "Contact",
    "Control",
    "Flow",
    "Grouping",
    "Line",
    "Overview",
    "ProcessView",
    "Rule",
    "SourceRow",
    "Step",
    "plain",
]
