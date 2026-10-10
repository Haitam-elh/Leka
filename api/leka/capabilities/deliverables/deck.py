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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    channel: str = Field(description="Le canal, ex. « Espace Client TR ».")
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

    name: str = Field(description="Le nom de la brique, ex. « OCTOPUS ».")
    subtitle: str = Field(default="", description="Précision, ex. « middleware CLIP / INES ».")
    missing: bool = Field(default=False, description="Brique non documentée : en-tête orange.")


class Call(_Model):
    """A service box: where it is called, and what."""

    column: str = Field(description="Le nom exact d'une colonne du process.")
    label: str = Field(description="Le service, ex. « ws_lireCompteClient (solde) ».")
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
    front: str = Field(description="L'en-tête du canal Front, ex. « DIGITAL EC PASSERELLE ».")
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

    parcours: str = Field(description="Le nom du parcours, ex. « Paiement CB ».")
    perimetre: str = Field(
        description="« Périmètre <domaine> - <canaux / variantes> », ex. « Périmètre Digital - "
        "Espace Client TR »."
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
]
