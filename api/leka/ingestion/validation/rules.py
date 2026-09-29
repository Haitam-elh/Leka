"""What makes a processed record trustworthy (LEKA-358): pure rules.

A normalised record (docs/normalisation.md) in; out, whether it may become
the company's knowledge, why not, and how good it is:

    status      valid        nothing wrong
                warning      usable, with what is doubtful said
                quarantined  an error: kept out of entity resolution — and so
                             of the company model — until it is corrected
    issues      {code, severity, field, message, remediation}: what, where,
                and what a person does about it — never a value of the record
    scores      completeness, consistency, freshness, confidence, and the
                quality they make together — 0 for a quarantined record

THE CHECKS, in order:

    schema        the record is a NormalisedRecord: types, required fields,
                  confidences within 0 and 1                       error
    keys          a key has its type's shape: a person's `person:…`, an
                  address that is one, a commit's sha, a service's slug,
                  an ARN, no spaces                                  error
    values        a state, a priority on LEKA's scale               warning
                  a date that reads, a link that is http(s)          error / warning
                  a date in the future, before 1990, updated before
                  created                                            warning
    relationships a person's relationship ends at a person; a type LEKA
                  knows; no thing related to itself                  error / warning
    completeness  what a thing of its type is expected to say — an issue's
                  state, dates, author, link…                        info
    consistency   the same entity made twice by one source; what the vendor
                  wrote that no scale knows                          warning
    freshness     when a pass last saw it: fine for 8 days, worth nothing
                  after 30 — a weekly full pass sees everything      warning

An error quarantines, a warning flags, an info only lowers a score. Rules:
docs/validation.md. Raised VALIDATOR_VERSION: everything is validated again.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import ValidationError

from leka.ingestion.normalisation.contract import NormalisedRecord

VALIDATOR_VERSION = 1

WORK_STATES = frozenset({"open", "in_progress", "closed", "merged"})
INCIDENT_STATES = frozenset({"open", "in_progress", "closed"})
RESOURCE_STATES = frozenset({"running", "starting", "stopping", "stopped", "deleting", "failed"})
PRIORITIES = frozenset({"highest", "high", "medium", "low", "lowest"})
STATES: dict[str, frozenset[str]] = {
    "issue": WORK_STATES,
    "pull_request": WORK_STATES,
    "incident": INCIDENT_STATES,
    "infra_resource": RESOURCE_STATES,
}
# What a relationship of each type points at.
PEOPLE_RELATIONSHIPS = frozenset(
    {
        "authored_by",
        "committed_by",
        "assigned_to",
        "reviewed_by",
        "reported_by",
        "created_by",
        "led_by",
    }
)
RELATIONSHIPS = PEOPLE_RELATIONSHIPS | {
    "part_of",
    "child_of",
    "affects",
    "resolves",
    "mentions",
    "implements",
    "merges",
    "owned_by",
    "in_network",
}
KEY_SHAPES: dict[str, re.Pattern[str]] = {
    # An address that is one, or an account on its host — `email` is no host.
    "person": re.compile(r"^person:(email:[^@\s:]+@[^@\s]+\.[^@\s]+|(?!email:)[^:\s]+:[^\s]+)$"),
    "service": re.compile(r"^service:[a-z0-9]+(-[a-z0-9]+)*$"),
    "team": re.compile(r"^team:[a-z0-9]+(-[a-z0-9]+)*$"),
    # A sha as git abbreviates it (4 at least), up to SHA-256's 64.
    "commit": re.compile(r"@[0-9a-f]{4,64}$"),
    "incident": re.compile(r"^incident:[a-z0-9_]+:[^\s]+$"),
    "infra_resource": re.compile(r"^(aws|azure|gcp):[^\s]+$"),
}
# What a thing of each type is expected to say. "author": a person
# related by one of PEOPLE_RELATIONSHIPS; "part_of", "affects", "owned_by":
# a relationship of that type; anything else: an attribute.
EXPECTED: dict[str, tuple[str, ...]] = {
    "issue": ("url", "state", "created_at", "updated_at", "author"),
    "pull_request": ("url", "state", "created_at", "updated_at", "author", "part_of"),
    "commit": ("created_at", "author", "part_of"),
    "branch": ("part_of",),
    "release": ("created_at", "part_of"),
    "repository": ("url", "updated_at"),
    "project": ("url",),
    "incident": ("url", "state", "created_at", "affects"),
    "document": ("url", "updated_at", "author"),
    "infra_resource": ("state", "environment"),
    "service": ("url",),
    "person": ("email",),
}
FRESH_DAYS = 8
STALE_DAYS = 30
EARLIEST = datetime(1990, 1, 1, tzinfo=UTC)
# The weights of the quality score: what is missing weighs most, then what
# contradicts itself, then age, then how sure the source was.
WEIGHTS = {"completeness": 0.35, "consistency": 0.3, "freshness": 0.2, "confidence": 0.15}
CONSISTENCY_COST = 0.25

Status = Literal["valid", "warning", "quarantined"]


class Severity(enum.StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    field: str
    message: str
    remediation: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "field": self.field,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass
class Validation:
    status: Status
    issues: list[Issue] = field(default_factory=list)
    completeness: float = 0.0
    consistency: float = 0.0
    freshness: float = 0.0
    confidence: float = 0.0
    quality: float = 0.0


# The remediation each code carries: what a person does about it.
REMEDIES = {
    "schema": "Un défaut de LEKA, pas de la source : il est à signaler au support, avec la source.",
    "bad_key": "Un défaut de LEKA ou un identifiant inattendu chez l'éditeur : à signaler au "
    "support.",
    "bad_related_key": "Un défaut de LEKA ou un identifiant inattendu chez l'éditeur : à signaler "
    "au support.",
    "bad_date": "Vérifiez le champ de date dans le mapping de la source (connecteur sur mesure), "
    "ou signalez-le au support.",
    "future_date": "L'horloge de l'outil, ou un champ qui n'est pas une date de création ou de "
    "modification : vérifiez le mapping.",
    "ancient_date": "Un champ de date qui n'en est pas un, ou une valeur par défaut chez l'éditeur "
    ": vérifiez le mapping.",
    "dates_out_of_order": "Modifié avant d'être créé : vérifiez quels champs le mapping lit.",
    "bad_url": "Le lien lu n'est pas une adresse web : vérifiez le champ du lien dans le mapping.",
    "unknown_state": "Donnez à cet état sa place sur l'échelle de LEKA dans le mapping de la "
    "source (Périmètre et mapping → états).",
    "unknown_priority": "Donnez à cette priorité sa place sur l'échelle de LEKA dans le mapping de "
    "la source (Périmètre et mapping → priorités).",
    "person_relationship_to_non_person": "Un défaut de LEKA : à signaler au support.",
    "unknown_relationship": "Un défaut de LEKA : à signaler au support.",
    "self_relationship": "Un lien d'un élément vers lui-même : vérifiez les champs de référence du "
    "mapping.",
    "duplicate_in_source": "La source donne deux éléments pour une même chose : vérifiez son "
    "périmètre (deux ressources qui se recoupent ?).",
    "vendor_word": "Donnez à ce mot sa place dans le mapping de la source.",
    "incomplete": "Complétez le mapping de la source si l'outil connaît ces champs ; sinon, rien à "
    "faire.",
    "stale": "Les passes complètes de la source ne réussissent plus : voyez son historique de "
    "synchronisation.",
}


def _issue(code: str, severity: Severity, where: str, message: str) -> Issue:
    return Issue(code, severity, where, message, REMEDIES[code])


def validate(
    result: object,
    *,
    seen_at: datetime | None,
    now: datetime,
    duplicate: bool = False,
) -> Validation:
    """One normalised record, validated. `seen_at`: when a pass last saw its
    record (source_records.last_seen_at); `duplicate`: another record of the
    same source makes the same entity."""
    try:
        record = NormalisedRecord.model_validate(result)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(step) for step in first["loc"]) or "record"
        return Validation(
            "quarantined",
            [
                _issue(
                    "schema",
                    Severity.ERROR,
                    where,
                    f"Pas un enregistrement normalisé : {where} — {first['type']}.",
                )
            ],
        )
    issues: list[Issue] = []
    entity = record.entity
    _key(entity.type, entity.key, "entity.key", "bad_key", issues)
    for position, named in enumerate(record.related):
        _key(named.type, named.key, f"related.{position}.key", "bad_related_key", issues)
    _attributes(entity.type, entity.attributes, now, issues)
    _relationships(record, issues)
    for said in record.diagnostics:
        code = (
            "unknown_state"
            if said.startswith("unknown state")
            else "unknown_priority"
            if said.startswith("unknown priority")
            else None
        )
        if code and not any(i.code == code for i in issues):
            issues.append(_issue(code, Severity.WARNING, "entity.attributes", said))
        elif code is None:
            issues.append(_issue("vendor_word", Severity.INFO, "diagnostics", said))
    if duplicate:
        issues.append(
            _issue(
                "duplicate_in_source",
                Severity.WARNING,
                "entity.key",
                "Un autre élément de la même source donne cette même entité.",
            )
        )
    missing = _missing(record)
    expected = EXPECTED.get(entity.type, ())
    completeness = 1.0 if not expected else (len(expected) - len(missing)) / len(expected)
    if missing:
        issues.append(
            _issue(
                "incomplete",
                Severity.INFO,
                "entity",
                f"Attendu d'un élément « {entity.type} », absent : {', '.join(missing)}.",
            )
        )
    freshness = _freshness(seen_at or record.provenance.fetched_at, now, issues)
    consistency = max(
        0.0,
        1.0
        - CONSISTENCY_COST
        * sum(1 for i in issues if i.severity is Severity.WARNING and i.code not in ("stale",)),
    )
    quality_of_parse = entity.attributes.get("quality")
    confidence = entity.confidence * (
        float(quality_of_parse) if isinstance(quality_of_parse, int | float) else 1.0
    )
    status: Status = (
        "quarantined"
        if any(i.severity is Severity.ERROR for i in issues)
        else "warning"
        if any(i.severity is Severity.WARNING for i in issues)
        else "valid"
    )
    scores = {
        "completeness": round(completeness, 2),
        "consistency": round(consistency, 2),
        "freshness": round(freshness, 2),
        "confidence": round(min(max(confidence, 0.0), 1.0), 2),
    }
    quality = 0.0 if status == "quarantined" else sum(scores[k] * w for k, w in WEIGHTS.items())
    return Validation(status, issues, quality=round(quality, 2), **scores)


# ── the checks ───────────────────────────────────────────────────────────────


def _key(kind: str, key: str, where: str, code: str, issues: list[Issue]) -> None:
    shape = KEY_SHAPES.get(kind)
    if re.search(r"\s", key) or (shape is not None and not shape.search(key)):
        issues.append(
            _issue(code, Severity.ERROR, where, f"Une clé qui n'a pas la forme d'un « {kind} ».")
        )


def _attributes(
    kind: str, attributes: dict[str, object], now: datetime, issues: list[Issue]
) -> None:
    scale = STATES.get(kind)
    state = attributes.get("state")
    if scale is not None and isinstance(state, str) and state not in scale:
        issues.append(
            _issue(
                "unknown_state",
                Severity.WARNING,
                "entity.attributes.state",
                f"Un état hors de l'échelle de LEKA pour un « {kind} ».",
            )
        )
    priority = attributes.get("priority")
    if isinstance(priority, str) and priority not in PRIORITIES:
        issues.append(
            _issue(
                "unknown_priority",
                Severity.WARNING,
                "entity.attributes.priority",
                "Une priorité hors de l'échelle de LEKA.",
            )
        )
    moments: dict[str, datetime] = {}
    for name, value in attributes.items():
        if not name.endswith("_at") or value is None:
            continue
        where = f"entity.attributes.{name}"
        moment = _moment(value)
        if moment is None:
            issues.append(_issue("bad_date", Severity.ERROR, where, "Une date qui ne se lit pas."))
            continue
        moments[name] = moment
        if moment > now + timedelta(days=1):
            issues.append(_issue("future_date", Severity.WARNING, where, "Une date dans le futur."))
        elif moment < EARLIEST:
            issues.append(_issue("ancient_date", Severity.WARNING, where, "Une date d'avant 1990."))
    created, updated = moments.get("created_at"), moments.get("updated_at")
    if created and updated and updated < created - timedelta(minutes=1):
        issues.append(
            _issue(
                "dates_out_of_order",
                Severity.WARNING,
                "entity.attributes.updated_at",
                "Modifié avant d'être créé.",
            )
        )
    url = attributes.get("url")
    if url is not None and not (isinstance(url, str) and re.match(r"^https?://[^\s/]+", url)):
        issues.append(
            _issue(
                "bad_url",
                Severity.WARNING,
                "entity.attributes.url",
                "Un lien qui n'est pas une adresse web.",
            )
        )


def _relationships(record: NormalisedRecord, issues: list[Issue]) -> None:
    people = {n.key for n in record.related if n.type == "person"}
    for position, edge in enumerate(record.relationships):
        where = f"relationships.{position}"
        if edge.type not in RELATIONSHIPS:
            issues.append(
                _issue(
                    "unknown_relationship",
                    Severity.WARNING,
                    where,
                    f"Un lien « {edge.type} » que LEKA ne connaît pas.",
                )
            )
        if edge.from_key == edge.to_key:
            issues.append(
                _issue("self_relationship", Severity.WARNING, where, "Un lien vers lui-même.")
            )
        if edge.type in PEOPLE_RELATIONSHIPS and not (
            edge.to_key.startswith("person:") or edge.to_key in people
        ):
            issues.append(
                _issue(
                    "person_relationship_to_non_person",
                    Severity.ERROR,
                    where,
                    f"Un lien « {edge.type} » qui ne mène pas à une personne.",
                )
            )


def _missing(record: NormalisedRecord) -> list[str]:
    entity = record.entity
    kinds = {edge.type for edge in record.relationships if edge.from_key == entity.key}
    missing = []
    for expected in EXPECTED.get(entity.type, ()):
        if expected == "author":
            present = bool(kinds & PEOPLE_RELATIONSHIPS)
        elif expected in ("part_of", "affects", "owned_by"):
            present = expected in kinds
        elif expected == "email":
            present = entity.key.startswith("person:email:") or any(
                alias.startswith("person:email:") for alias in entity.aliases
            )
        else:
            present = entity.attributes.get(expected) not in (None, "", [])
        if not present:
            missing.append(expected)
    return missing


def _freshness(seen: datetime | None, now: datetime, issues: list[Issue]) -> float:
    if seen is None:
        return 0.0
    seen = seen if seen.tzinfo else seen.replace(tzinfo=UTC)
    age = (now - seen).total_seconds() / 86_400
    if age <= FRESH_DAYS:
        return 1.0
    issues.append(
        _issue(
            "stale",
            Severity.WARNING,
            "record",
            f"Pas revu par une synchronisation depuis {int(age)} jours.",
        )
    )
    return max(0.0, 1 - (age - FRESH_DAYS) / (STALE_DAYS - FRESH_DAYS))


def _moment(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        found = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)
