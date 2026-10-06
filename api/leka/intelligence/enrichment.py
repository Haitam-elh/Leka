"""Knowledge enrichment (LEKA-380): what the company model lacks that the
evidence around it says — proposed, never imposed.

Enrichment at ingestion (LEKA-359) completes each record as it comes in,
and keeps every inference it is sure enough of. This reads the whole
model, as the intelligence engine does, and PROPOSES: a relationship, an
attribute, each with how sure it is and what shows it. A proposal becomes
a candidate (models.py); a candidate is applied to the model only once it
is validated — by a person, or by the workspace's policy for what is sure
and adds without replacing — and a source's word is only replaced by a
person's decision (docs/intelligence.md § 13).

Four families, one analysis or more each:

    relationship  enrich_code       the repository whose name says it is a
                                    service's code, for a service whose
                                    code is unknown
                  enrich_runtime    the cloud resource whose name says it
                                    runs a service, for a service whose
                                    runtime is unknown
    organisation  enrich_owner      the team that owns a thing's repository,
                                    or most of the people who maintain it
                                    are members of, for a thing no one owns
    business      enrich_application  the application a service's
                                    neighbours are part of, or whose name
                                    it carries, for a service no application
                                    holds
    semantic      enrich_criticality  how critical a thing is, from the
                                    application holding it and what relies
                                    on it — above what is said, or where
                                    nothing is
                  enrich_description  a service's description, from the
                                    repository that is its code alone
                  enrich_summary    what a service does, in words, from its
                                    documents and code — model-assisted:
                                    skipped until the model gateway exists

Each proposes only where the family of sources that would say it is
connected, where one answer stands out — two repositories named alike say
nothing — and nothing a thing already has.

Pure: the material in, proposals out.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence

from leka.intelligence.analysis import (
    Analyzer,
    Evidence,
    Material,
    Method,
    Proposal,
    Reads,
    Subject,
)
from leka.intelligence.gaps import cards_of, connected_families, dependents_of
from leka.knowledge import RELIED_ON, ArchitectureCardRead, EntityBrief

# Words that say what kind of thing something is, not which: payment-api and
# payments-service are one name.
GENERIC = frozenset(
    {
        "api",
        "app",
        "application",
        "backend",
        "core",
        "frontend",
        "main",
        "server",
        "service",
        "svc",
        "web",
        "worker",
        "prod",
        "production",
        "staging",
        "stage",
        "dev",
        "test",
    }
)
# How sure a name is: the same words, or one word more.
SAME_NAME, NEAR_NAME = 0.8, 0.65
RUNTIME_SAME, RUNTIME_NEAR = 0.75, 0.6
# An owner: the team owning its repository — what the policy may apply;
# the team of its maintainers, by how many of them.
REPOSITORY_OWNER = 0.9
MAINTAINERS = 2
MAINTAINER_SHARE = 2 / 3
# An application, by its neighbours or its name.
NEIGHBOURS = 2
NEIGHBOUR_SHARE = 2 / 3
APPLICATION_NAME = 0.7
# How critical: LEKA's scale, the least first.
SCALE = ("low", "medium", "high", "critical")
RELIED_ON_HIGH = 5
FROM_APPLICATION, FROM_RELIANCE = 0.75, 0.65
DESCRIPTION = 0.7
MAX_DESCRIPTION = 500

ROLE_HOLDS = "part_of"


def words(name: str) -> frozenset[str]:
    """What a name says, without what kind of thing it is: `acme/payments`
    and `payment-api` both say `payment`."""
    last = name.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    found = set()
    for word in re.split(r"[^a-z0-9]+", last.lower()):
        if not word or word.isdigit() or word in GENERIC:
            continue
        found.add(word[:-1] if len(word) > 3 and word.endswith("s") else word)
    return frozenset(found)


def likeness(named: str, other: str) -> str | None:
    """`same` when two names say the same words, `near` when the other says
    one more — none otherwise, or when the first says nothing."""
    one, two = words(named), words(other)
    if not one:
        return None
    if one == two:
        return "same"
    if one < two and len(two - one) == 1:
        return "near"
    return None


def _subject(card: ArchitectureCardRead) -> Subject:
    return Subject(type="entity", id=card.entity_id, name=card.name, kind=card.type)


def _brief(brief: EntityBrief) -> Subject:
    return Subject(type="entity", id=brief.id, name=brief.name, kind=brief.type.value)


def _key(code: str, *parts: object) -> str:
    return ":".join([code, *(str(part) for part in parts)])


def _value_key(value: object) -> str:
    said = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(said.encode()).hexdigest()[:12]


def _entity(card: ArchitectureCardRead, detail: str) -> Evidence:
    return Evidence(kind="entity", id=str(card.entity_id), name=card.name, detail=detail)


def _sources(*cards: ArchitectureCardRead) -> tuple[str, ...]:
    return tuple(sorted({kind for card in cards for kind in card.sources}))


def _services(material: Material) -> list[ArchitectureCardRead]:
    return [c for c in cards_of(material) if c.column == "services" and c.type == "service"]


def _by_id(material: Material) -> dict[str, ArchitectureCardRead]:
    architecture = material.architecture
    return {card.id: card for card in architecture.cards} if architecture else {}


def _one(
    named: ArchitectureCardRead, others: Iterable[ArchitectureCardRead]
) -> tuple[ArchitectureCardRead, str] | None:
    """The one card whose name matches — the closest, and alone at that."""
    found: dict[str, list[ArchitectureCardRead]] = defaultdict(list)
    for other in others:
        how = likeness(named.name, other.name)
        if how:
            found[how].append(other)
    for how in ("same", "near"):
        if len(found[how]) == 1:
            return found[how][0], how
        if found[how]:
            return None
    return None


# ── relationships ──────────────────────────────────────────────────────


def enrich_code(material: Material) -> list[Proposal]:
    """The repository whose name says it is a service's code."""
    if "code" not in connected_families(material):
        return []
    repositories = [c for c in cards_of(material) if c.type == "repository"]
    proposals: list[Proposal] = []
    for service in _services(material):
        if service.repository_id is not None:
            continue
        match = _one(service, repositories)
        if match is None:
            continue
        repository, how = match
        proposals.append(
            Proposal(
                key=_key("enrichment.code", repository.entity_id, "part_of", service.entity_id),
                family="relationship",
                code="enrichment.code",
                subject=_subject(service),
                statement=f"{repository.name} is likely the code of {service.name}: its name "
                "says so.",
                confidence=SAME_NAME if how == "same" else NEAR_NAME,
                relationship="part_of",
                start=_subject(repository),
                end=_subject(service),
                params={"name": service.name, "repository": repository.name, "match": how},
                evidence=(
                    _entity(repository, f"named {repository.name}"),
                    _entity(service, "no repository is said to be its code"),
                ),
                sources=_sources(repository, service),
            )
        )
    return proposals


def enrich_runtime(material: Material) -> list[Proposal]:
    """The cloud resource whose name says it runs a service."""
    if "cloud" not in connected_families(material):
        return []
    resources = [c for c in cards_of(material) if c.column == "cloud"]
    proposals: list[Proposal] = []
    for service in _services(material):
        if service.host_id is not None:
            continue
        match = _one(service, resources)
        if match is None:
            continue
        resource, how = match
        proposals.append(
            Proposal(
                key=_key(
                    "enrichment.runtime", service.entity_id, "deployed_to", resource.entity_id
                ),
                family="relationship",
                code="enrichment.runtime",
                subject=_subject(service),
                statement=f"{service.name} likely runs on {resource.name}: its name says so.",
                confidence=RUNTIME_SAME if how == "same" else RUNTIME_NEAR,
                relationship="deployed_to",
                start=_subject(service),
                end=_subject(resource),
                params={"name": service.name, "resource": resource.name, "match": how},
                evidence=(
                    _entity(resource, f"named {resource.name}"),
                    _entity(service, "no resource is said to run it"),
                ),
                sources=_sources(resource, service),
            )
        )
    return proposals


# ── organisation ───────────────────────────────────────────────────────


def enrich_owner(material: Material) -> list[Proposal]:
    """For a thing no one owns: the team owning its repository — or the team
    most of the people who maintain it are members of."""
    cards = _by_id(material)
    proposals: list[Proposal] = []
    for card in cards_of(material):
        if card.column not in ("services", "data") or card.entity_id is None:
            continue
        if material.owned_by.get(card.entity_id):
            continue
        proposal = _owner_from_repository(material, card, cards) or _owner_from_maintainers(
            material, card
        )
        if proposal is not None:
            proposals.append(proposal)
    return proposals


def _owner_from_repository(
    material: Material, card: ArchitectureCardRead, cards: dict[str, ArchitectureCardRead]
) -> Proposal | None:
    repository = cards.get(card.repository_id) if card.repository_id else None
    if repository is None or repository.entity_id is None:
        return None
    teams = [o for o in material.owned_by.get(repository.entity_id, ()) if o.type.value == "team"]
    if len(teams) != 1:
        return None
    team = teams[0]
    return _owns(
        card,
        team,
        confidence=REPOSITORY_OWNER,
        statement=f"{team.name} likely owns {card.name}: it owns {repository.name}, its code.",
        params={"how": "repository", "repository": repository.name},
        evidence=(_entity(repository, f"owned by {team.name}; the code of {card.name}"),),
        sources=_sources(repository, card),
    )


def _owner_from_maintainers(material: Material, card: ArchitectureCardRead) -> Proposal | None:
    if len(card.maintainers) < MAINTAINERS:
        return None
    teams: Counter[str] = Counter()
    named: dict[str, EntityBrief] = {}
    members: dict[str, list[str]] = defaultdict(list)
    for person in card.maintainers:
        for team in material.memberships.get(person.id, ()):
            teams[str(team.id)] += 1
            named[str(team.id)] = team
            members[str(team.id)].append(person.name)
    if not teams:
        return None
    ranked = teams.most_common(2)
    best, count = ranked[0]
    if len(ranked) > 1 and ranked[1][1] == count:
        return None
    share = count / len(card.maintainers)
    if share < MAINTAINER_SHARE:
        return None
    team = named[best]
    return _owns(
        card,
        team,
        confidence=round(0.5 + 0.35 * share, 2),
        statement=f"{team.name} likely owns {card.name}: {count} of the "
        f"{len(card.maintainers)} people who maintain it are its members.",
        params={
            "how": "maintainers",
            "members": count,
            "maintainers": len(card.maintainers),
            "people": members[best][:5],
        },
        evidence=tuple(
            Evidence(
                kind="entity",
                id=str(person.id),
                name=person.name,
                detail=f"maintains {card.name}; a member of {team.name}",
            )
            for person in card.maintainers
            if person.name in members[best]
        )[:5],
        sources=_sources(card),
    )


def _owns(
    card: ArchitectureCardRead,
    team: EntityBrief,
    *,
    confidence: float,
    statement: str,
    params: dict[str, object],
    evidence: tuple[Evidence, ...],
    sources: tuple[str, ...],
) -> Proposal:
    return Proposal(
        key=_key("enrichment.owner", card.entity_id, "owned_by", team.id),
        family="organisation",
        code="enrichment.owner",
        subject=_subject(card),
        statement=statement,
        confidence=confidence,
        relationship="owned_by",
        start=_subject(card),
        end=_brief(team),
        params={"name": card.name, "team": team.name, **params},
        evidence=evidence,
        sources=sources,
    )


# ── business ───────────────────────────────────────────────────────────


def enrich_application(material: Material) -> list[Proposal]:
    """For a service no application holds: the application its neighbours
    are part of — or, failing that, whose name it carries."""
    architecture = material.architecture
    if architecture is None:
        return []
    cards = _by_id(material)
    applications = [c for c in cards_of(material) if c.type == "application"]
    if not applications:
        return []
    apps = {a.id for a in applications}
    held: dict[str, set[str]] = defaultdict(set)
    near: dict[str, set[str]] = defaultdict(set)
    for link in architecture.links:
        if link.role == ROLE_HOLDS and link.to_id in apps:
            held[link.from_id].add(link.to_id)
        elif link.role in RELIED_ON and link.from_id != link.to_id:
            near[link.from_id].add(link.to_id)
            near[link.to_id].add(link.from_id)
    proposals: list[Proposal] = []
    for service in _services(material):
        standing = material.standing.get(service.entity_id) if service.entity_id else None
        if held.get(service.id) or (standing is not None and standing.business):
            continue
        proposal = _by_neighbours(service, near, held, cards) or _by_name(service, applications)
        if proposal is not None:
            proposals.append(proposal)
    return proposals


def _by_neighbours(
    service: ArchitectureCardRead,
    near: dict[str, set[str]],
    held: dict[str, set[str]],
    cards: dict[str, ArchitectureCardRead],
) -> Proposal | None:
    holding: Counter[str] = Counter()
    with_one = [n for n in near.get(service.id, ()) if held.get(n)]
    for neighbour in with_one:
        holding.update(held[neighbour])
    if len(with_one) < NEIGHBOURS or not holding:
        return None
    ranked = holding.most_common(2)
    best, count = ranked[0]
    if len(ranked) > 1 and ranked[1][1] == count:
        return None
    share = count / len(with_one)
    application = cards[best]
    if share < NEIGHBOUR_SHARE:
        return None
    names = sorted(cards[n].name for n in with_one if best in held[n])
    return _part_of(
        service,
        application,
        confidence=round(0.5 + 0.3 * share, 2),
        statement=f"{service.name} is likely part of {application.name}: {count} of the "
        f"{len(with_one)} services it works with are.",
        params={"how": "neighbours", "neighbours": names[:5], "count": count, "of": len(with_one)},
        evidence=tuple(
            _entity(cards[n], f"works with {service.name}; part of {application.name}")
            for n in sorted(with_one, key=lambda n: cards[n].name)
            if best in held[n]
        )[:5],
    )


def _by_name(
    service: ArchitectureCardRead, applications: Sequence[ArchitectureCardRead]
) -> Proposal | None:
    found = [a for a in applications if words(a.name) and words(a.name) <= words(service.name)]
    if len(found) != 1:
        return None
    application = found[0]
    return _part_of(
        service,
        application,
        confidence=APPLICATION_NAME,
        statement=f"{service.name} is likely part of {application.name}: its name says so.",
        params={"how": "name"},
        evidence=(_entity(application, f"named {application.name}"),),
    )


def _part_of(
    service: ArchitectureCardRead,
    application: ArchitectureCardRead,
    *,
    confidence: float,
    statement: str,
    params: dict[str, object],
    evidence: tuple[Evidence, ...],
) -> Proposal:
    return Proposal(
        key=_key("enrichment.application", service.entity_id, "part_of", application.entity_id),
        family="business",
        code="enrichment.application",
        subject=_subject(service),
        statement=statement,
        confidence=confidence,
        relationship="part_of",
        start=_subject(service),
        end=_subject(application),
        params={"name": service.name, "application": application.name, **params},
        evidence=evidence,
        sources=_sources(service, application),
    )


# ── semantic ───────────────────────────────────────────────────────────


def enrich_criticality(material: Material) -> list[Proposal]:
    """How critical a thing is, from the application holding it and what
    relies on it: proposed where nothing is said, or above what is."""
    architecture = material.architecture
    if architecture is None:
        return []
    cards = _by_id(material)
    holders: dict[str, list[ArchitectureCardRead]] = defaultdict(list)
    for link in architecture.links:
        holder = cards.get(link.to_id)
        if link.role == ROLE_HOLDS and holder is not None and holder.type == "application":
            holders[link.from_id].append(holder)
    dependents = dependents_of(material)
    proposals: list[Proposal] = []
    for card in cards_of(material):
        if card.column not in ("services", "data") or card.entity_id is None:
            continue
        standing = material.standing.get(card.entity_id)
        current = standing.criticality if standing else None
        level, confidence, evidence, how, why = _level(material, card, holders, dependents[card.id])
        if level is None or _rank(current) >= _rank(level):
            continue
        overrides = (
            current is not None and standing is not None and "criticality" in standing.stated
        )
        proposals.append(
            Proposal(
                key=_key("enrichment.criticality", card.entity_id, "criticality", level),
                family="semantic",
                code="enrichment.criticality",
                subject=_subject(card),
                statement=f"{card.name} is likely {level}"
                + (f", not {current}" if current else "")
                + f": {how}.",
                confidence=confidence,
                attribute="criticality",
                value=level,
                current=current,
                overrides=overrides,
                params={"name": card.name, "level": level, "current": current, **why},
                evidence=evidence,
                sources=_sources(card),
            )
        )
    return proposals


def _level(
    material: Material,
    card: ArchitectureCardRead,
    holders: dict[str, list[ArchitectureCardRead]],
    relying: int,
) -> tuple[str | None, float, tuple[Evidence, ...], str, dict[str, object]]:
    """The level the evidence says, how sure, what shows it — in a sentence
    and in values: `from` application (its name) or reliance (how many)."""
    inherited: list[tuple[str, ArchitectureCardRead]] = []
    for application in holders.get(card.id, ()):
        said = material.standing.get(application.entity_id) if application.entity_id else None
        if said is not None and said.criticality in ("high", "critical"):
            inherited.append((said.criticality, application))
    if inherited:
        level, application = max(inherited, key=lambda found: _rank(found[0]))
        return (
            level,
            FROM_APPLICATION,
            (_entity(application, f"said {level}; holds {card.name}"),),
            f"{application.name}, which holds it, is said {level}",
            {"from": "application", "application": application.name},
        )
    if relying >= RELIED_ON_HIGH:
        return (
            "high",
            FROM_RELIANCE,
            (_entity(card, f"{relying} things rely on it"),),
            f"{relying} things rely on it",
            {"from": "reliance", "relying": relying},
        )
    return None, 0.0, (), "", {}


def _rank(level: str | None) -> int:
    return SCALE.index(level) if level in SCALE else -1


def enrich_description(material: Material) -> list[Proposal]:
    """A service's description, from the repository that is its code — and
    its alone: a repository holding several says what they are together."""
    cards = _by_id(material)
    services = _services(material)
    served = Counter(s.repository_id for s in services if s.repository_id)
    proposals: list[Proposal] = []
    for service in services:
        repository = cards.get(service.repository_id) if service.repository_id else None
        if (
            service.description
            or repository is None
            or not repository.description
            or served[repository.id] != 1
        ):
            continue
        text = repository.description.strip()[:MAX_DESCRIPTION]
        proposals.append(
            Proposal(
                key=_key(
                    "enrichment.description", service.entity_id, "description", _value_key(text)
                ),
                family="semantic",
                code="enrichment.description",
                subject=_subject(service),
                statement=f"{service.name} may be described as its repository {repository.name} "
                f"is: “{text}”.",
                confidence=DESCRIPTION,
                attribute="description",
                value=text,
                params={"name": service.name, "repository": repository.name},
                evidence=(_entity(repository, f"its description; the code of {service.name}"),),
                sources=_sources(repository),
            )
        )
    return proposals


def enrich_summary(material: Material) -> list[Proposal]:
    """Model-assisted: declared, skipped until the model gateway exists —
    the frame does not change the day one runs."""
    return []


def _analyzer(
    name: str,
    summary: str,
    run: Callable[[Material], Sequence[Proposal]],
    *,
    method: Method = Method.RULES,
) -> Analyzer:
    return Analyzer(
        name=name,
        version=1,
        category="enrichment",
        method=method,
        reads=frozenset({Reads.MODEL}),
        summary=summary,
        run=run,
    )


ANALYZERS: tuple[Analyzer, ...] = (
    _analyzer(
        "enrich_code",
        "The repository whose name says it is a service's code.",
        enrich_code,
    ),
    _analyzer(
        "enrich_runtime",
        "The cloud resource whose name says it runs a service.",
        enrich_runtime,
    ),
    _analyzer(
        "enrich_owner",
        "The team owning a thing's repository, or most of its maintainers' team.",
        enrich_owner,
    ),
    _analyzer(
        "enrich_application",
        "The application a service's neighbours are part of, or whose name it carries.",
        enrich_application,
    ),
    _analyzer(
        "enrich_criticality",
        "How critical a thing is, from the application holding it and what relies on it.",
        enrich_criticality,
    ),
    _analyzer(
        "enrich_description",
        "A service's description, from the repository that is its code alone.",
        enrich_description,
    ),
    _analyzer(
        "enrich_summary",
        "What a service does, in words, from its documents and its code.",
        enrich_summary,
        method=Method.MODEL,
    ),
)
