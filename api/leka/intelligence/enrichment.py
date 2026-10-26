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
                  enrich_summary    what a thing does, in words, written by
                                    a language model from what LEKA knows of
                                    it — model-assisted (LEKA-394): each
                                    sentence citing the facts it rests on

Each proposes only where the family of sources that would say it is
connected, where one answer stands out — two repositories named alike say
nothing — and nothing a thing already has.

Pure: the material in, proposals out — enrich_summary aside, which asks a
model through the gateway (ModelWork) and is a person's to validate, always:
the policy accepts only what rules propose (curation.by_policy).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence

from pydantic import BaseModel, Field

from leka.capabilities import ContextItem, ContextPack, Needs, Task, Tier
from leka.intelligence.analysis import (
    Analyzer,
    Evidence,
    Material,
    Method,
    ModelWork,
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


# ── model-assisted (LEKA-394) ───────────────────────────────────────────────

# What a description asks of a model: a structured answer, good analysis.
SUMMARY_NEEDS = Needs(structured=True, quality=2)
# How sure a description a model wrote is, at most: a person validates it.
SUMMARY = 0.6
# Things described in one run, at most — the others the next run.
SUMMARY_MOST = 12
SUMMARY_PURPOSE = "enrichment.summary"
SUMMARY_KINDS = {"service": 0, "repository": 1, "database": 2}

SUMMARY_SYSTEM = """You describe the systems of a company's IT for its \
architecture map. For each thing given, write what it is and what it does, \
in one or two plain sentences, from ITS FACTS ONLY — never a name, a purpose, \
a user or a technology the facts do not say. Write in the language you are \
told to write in. Say how sure you are, 0 to 1: low \
when the facts say little. Cite the ids of the facts each description rests \
on. A thing the facts say too little about: leave it out.

Never write the em dash « — »: a colon, a comma, a semicolon or \
parentheses, as the sentence needs."""


class Described(BaseModel):
    id: str
    description: str = Field(max_length=400)
    confidence: float = Field(ge=0, le=1)
    uses: list[str] = Field(max_length=12)


class Descriptions(BaseModel):
    """What the model is asked to give back."""

    things: list[Described] = Field(max_length=SUMMARY_MOST)


def digest_of(facts: Sequence[tuple[str, str]]) -> str:
    """What a thing's facts are, in 16 characters: the same facts, the same
    digest — whatever order they come in."""
    said = "\n".join(sorted(f"{fact}={text}" for fact, text in facts))
    return hashlib.sha256(said.encode()).hexdigest()[:16]


def _card_of(cards: Sequence[ArchitectureCardRead], ident: str) -> ArchitectureCardRead | None:
    return next((card for card in cards if card.id == ident), None)


def summary_key(card: ArchitectureCardRead) -> str:
    """One proposal per thing, whatever the words: a model words it anew
    each time — the thing is what is proposed for."""
    return _key("enrichment.summary", card.entity_id, "description")


def facts_of(
    card: ArchitectureCardRead,
    cards: dict[str, ArchitectureCardRead],
    links: Sequence[tuple[str, str, str]],
) -> list[tuple[str, str]]:
    """What LEKA knows of a thing, each fact with an id to cite."""
    found: list[tuple[str, str]] = [
        (f"{card.id}:what", f"A {card.type} ({card.kind}), from {card.group}.")
    ]
    if card.technology:
        found.append((f"{card.id}:technology", "Technology: " + ", ".join(card.technology[:8])))
    if card.environment:
        found.append((f"{card.id}:environment", f"Environment: {card.environment}"))
    if card.url:
        found.append((f"{card.id}:url", f"Reached at: {card.url}"))
    if card.team:
        found.append((f"{card.id}:team", f"Owned by the team {card.team.name}"))
    repository = cards.get(card.repository_id) if card.repository_id else None
    if repository is not None:
        said = f"Its code is the repository {repository.name}"
        if repository.description:
            said += f", described as: {repository.description[:300]}"
        found.append((f"{card.id}:code", said))
    host = cards.get(card.host_id) if card.host_id else None
    if host is not None:
        found.append((f"{card.id}:host", f"Runs on {host.name} ({host.kind})"))
    parts = [str(p.get("name") or p.get("path") or "") for p in card.parts[:12]]
    if any(parts):
        found.append((f"{card.id}:parts", "Its parts: " + ", ".join(p for p in parts if p)))
    if card.files:
        found.append((f"{card.id}:files", "Its files: " + ", ".join(card.files[:15])))
    if card.evidence:
        found.append(
            (f"{card.id}:evidence", "What says what it is: " + "; ".join(card.evidence[:5]))
        )
    for key, value in list(card.facts.items())[:6]:
        found.append((f"{card.id}:fact:{key}", f"{key}: {str(value)[:200]}"))
    outgoing = sorted(
        {f"{role} {cards[to].name}" for frm, to, role in links if frm == card.id and to in cards}
    )
    if outgoing:
        found.append((f"{card.id}:uses", "It " + "; ".join(outgoing[:10])))
    incoming = sorted(
        {
            f"{cards[frm].name} {role} it"
            for frm, to, role in links
            if to == card.id and frm in cards
        }
    )
    if incoming:
        found.append((f"{card.id}:used_by", "; ".join(incoming[:10])))
    return found


async def enrich_summary(material: Material, work: ModelWork) -> list[Proposal]:
    """What a thing is and does, in words — written by a model from what
    LEKA knows of it, each description citing its facts; for the things
    without a description, a dozen a run. What it already proposed stands
    as it was, never asked twice; what was decided is never asked again."""
    cards = _by_id(material)
    architecture = material.architecture
    links = (
        [(link.from_id, link.to_id, link.role) for link in architecture.links]
        if architecture
        else []
    )
    wanting = sorted(
        (
            c
            for c in cards.values()
            if c.entity_id and not (c.description or "").strip() and c.type in SUMMARY_KINDS
        ),
        key=lambda c: (SUMMARY_KINDS[c.type], c.name.lower()),
    )
    proposals: list[Proposal] = []
    open_: list[ArchitectureCardRead] = []
    for card in wanting:
        key = summary_key(card)
        if key in work.decided:
            continue
        if key in work.kept:
            proposals.append(work.kept[key])
            continue
        open_.append(card)
    if not open_:
        return proposals
    # Asked already on the very same facts — described, or left out for
    # saying too little: not asked again, never paid for twice. A thing
    # whose facts changed is.
    every = {card.id: facts_of(card, cards, links) for card in open_}
    digests = {summary_key(card): digest_of(every[card.id]) for card in open_}
    before = await work.asked(SUMMARY_PURPOSE, list(digests)) if work.asked else {}
    asking = [
        card for card in open_ if before.get(summary_key(card)) != digests[summary_key(card)]
    ][:SUMMARY_MOST]
    if not asking:
        return proposals
    facts = {card.id: every[card.id] for card in asking}
    # What LEKA knows of them, from the company model: the context it rests
    # on, each fact with the id it cites.
    context = ContextPack.of(
        [ContextItem(id=f, kind="fact", text=t) for card in asking for f, t in facts[card.id]],
        ref="company-model",
        characters=40_000,
    )
    done = await work.run(
        Task(
            purpose=SUMMARY_PURPOSE,
            instructions=SUMMARY_SYSTEM,
            input={
                "things": [
                    {"id": card.id, "name": card.name, "facts": [f for f, _ in facts[card.id]]}
                    for card in asking
                ]
            },
            context=context,
            output=Descriptions,
            check=_rests,
            needs=SUMMARY_NEEDS,
            # Describing is no deep work; its thinking counts in its tokens.
            tier=Tier.FAST,
            max_tokens=6000,
            budget=100.0,
            # The workspace's language: a description is for everyone in it.
            language=work.language,
        )
    )
    if done.status in ("succeeded", "invalid") and work.remember is not None:
        # A model answered — usably or not: what it was asked, kept.
        said_of = (
            {summary_key(by) for d in done.value.things if (by := _card_of(asking, d.id))}
            if done.ok
            else set()
        )
        await work.remember(
            SUMMARY_PURPOSE,
            {summary_key(card): digests[summary_key(card)] for card in asking},
            said_of,
        )
    if not done.ok:
        # No model, none in time, nothing usable: what stands, nothing new.
        return proposals
    written: Descriptions = done.value
    model = str(done.model or "")
    by_id = {card.id: card for card in asking}
    for described in written.things:
        found = by_id.get(described.id)
        text = described.description.strip()[:MAX_DESCRIPTION]
        if found is None or not text:
            continue
        card = found
        known = {f: t for f, t in facts[card.id] if f in context.ids}
        uses = [f for f in dict.fromkeys(described.uses) if f in known]
        if not uses:
            # Resting on nothing LEKA knows of it: not proposed.
            continue
        proposals.append(
            Proposal(
                key=summary_key(card),
                family="semantic",
                code="enrichment.summary",
                subject=_subject(card),
                statement=f"{card.name} may be described as: “{text}”.",
                confidence=round(min(described.confidence, SUMMARY), 3),
                attribute="description",
                value=text,
                params={"name": card.name, "model": model, "facts": len(uses)},
                evidence=tuple(
                    Evidence(kind="fact", id=fact, name=card.name, detail=known[fact][:300])
                    for fact in uses
                ),
                sources=_sources(card),
            )
        )
    return proposals


def _rests(written: object, context: ContextPack) -> list[str]:
    """A model's descriptions are used only if one at least rests on a fact
    it was given."""
    if not isinstance(written, Descriptions):
        return ["not descriptions"]
    if any(set(d.uses) & context.ids for d in written.things):
        return []
    return ["no description cites a fact it was given"]


def _no_rules(material: Material) -> list[Proposal]:
    """A model-assisted analysis has no rules of its own."""
    return []


def _analyzer(
    name: str,
    summary: str,
    run: Callable[[Material], Sequence[Proposal]],
    *,
    method: Method = Method.RULES,
    version: int = 1,
    **more: object,
) -> Analyzer:
    return Analyzer(
        name=name,
        version=version,
        category="enrichment",
        method=method,
        reads=frozenset({Reads.MODEL}),
        summary=summary,
        run=run,
        **more,  # type: ignore[arg-type]
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
        "What a thing is and does, in words, written by a model from what LEKA knows of it.",
        _no_rules,
        method=Method.MODEL,
        # 2: written by a model through the gateway (LEKA-394).
        version=2,
        needs=SUMMARY_NEEDS,
        write=enrich_summary,
        budget=120.0,
    ),
)
