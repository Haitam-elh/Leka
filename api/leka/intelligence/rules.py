"""The first analyses (LEKA-377): rules over what a run read, one for each
part of the material — the shape of the company model, who owns it, the
contexts built on it. The tickets after this one (LEKA-378 to 383) add
theirs beside them: an analysis is a function and a line in ANALYZERS.

    dependency_concentration   what many things rely on — and whether it is
                               watched, whether it is well
    ownership                  what runs or keeps data with no owner named
                               for it — no team, no person
    context_health             the contexts people use that failed, fell
                               behind the model or were judged weak

Every one reads the company model as the architecture does
(GraphService.architecture, detailed): the same cards, states, teams and
links the screen draws, so a finding never disagrees with what the person
sees. Words are English here; the interface words a finding from its code
and values.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta

from leka.intelligence.analysis import (
    Analyzer,
    ContextStanding,
    Draft,
    Evidence,
    Material,
    Method,
    Reads,
    Severity,
    Subject,
)
from leka.intelligence.changes import ANALYZER as CHANGE_IMPACT
from leka.intelligence.conflicts import ANALYZER as CONFLICTS
from leka.intelligence.enrichment import ANALYZERS as ENRICHMENT
from leka.intelligence.evolution import ANALYZERS as EVOLUTION
from leka.intelligence.gaps import ANALYZERS as GAPS
from leka.intelligence.quality import ANALYZER as QUALITY
from leka.knowledge import RELIED_ON, ArchitectureCardRead, ArchitectureLinkRead

# What relies on a thing, before it is a concentration worth saying.
MIN_DEPENDENTS = 3
# From this many, it weighs whatever else is true of it.
MANY_DEPENDENTS = 5
# The dependents, the links, a finding names at most.
MAX_NAMED = 10
# Of the cards, those that run or keep something: what a team owns.
OWNED_COLUMNS = frozenset({"services", "data"})
# A context used this recently is in use; this long behind is behind.
USED_RECENTLY = timedelta(days=7)
USED_AT_ALL = timedelta(days=30)
BEHIND_AFTER = timedelta(days=1)
# An owner may exist that no source names: what the model does not say is
# not proof it is not so.
NO_OWNER_CONFIDENCE = 0.9

# The states something that watches a thing — a monitoring tool, its
# provider — reports. None, `unmonitored`, or deduced from what runs it:
# nothing watches it.
KNOWN_STATES = frozenset({"operational", "attention", "incident"})


def _dependents(
    links: Sequence[ArchitectureLinkRead],
) -> dict[str, list[ArchitectureLinkRead]]:
    """What relies on each card: the links that point at it, by role."""
    found: dict[str, list[ArchitectureLinkRead]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for link in links:
        if link.role not in RELIED_ON or link.from_id == link.to_id:
            continue
        if (link.from_id, link.to_id) in seen:
            continue
        seen.add((link.from_id, link.to_id))
        found[link.to_id].append(link)
    return found


def _subject(card: ArchitectureCardRead) -> Subject:
    """The entity a card is: its type as `kind` — what its sheet's address
    is made of; the card's own kind (api, cache…) is in the params."""
    return Subject(type="entity", id=card.entity_id, name=card.name, kind=card.type)


def _cards(material: Material) -> dict[str, ArchitectureCardRead]:
    architecture = material.architecture
    if architecture is None:
        return {}
    return {
        card.id: card
        for card in architecture.cards
        if card.entity_id is not None and card.type not in ("module", "tool")
    }


def _watched(card: ArchitectureCardRead) -> bool:
    return card.status in KNOWN_STATES and not card.deduced


# ── dependency concentration ───────────────────────────────────────────


def dependency_concentration(material: Material) -> list[Draft]:
    """What MIN_DEPENDENTS things or more rely on: high when it is unwell,
    or when many rely on it and nothing watches it."""
    architecture = material.architecture
    if architecture is None:
        return []
    cards = _cards(material)
    drafts: list[Draft] = []
    for card_id, links in _dependents(architecture.links).items():
        card = cards.get(card_id)
        if card is None:
            continue
        users = [cards[link.from_id] for link in links if link.from_id in cards]
        count = len(users)
        if count < MIN_DEPENDENTS:
            continue
        watched = _watched(card)
        if card.status in ("incident", "attention") or (not watched and count >= MANY_DEPENDENTS):
            severity = Severity.HIGH
        elif not watched or count >= MANY_DEPENDENTS:
            severity = Severity.MEDIUM
        else:
            severity = Severity.LOW
        state = card.status or "unknown"
        said = (
            "it is in incident"
            if state == "incident"
            else "it needs attention"
            if state == "attention"
            else "nothing watches it — its state is deduced"
            if card.deduced
            else "nothing watches it"
            if not watched
            else "it is watched"
        )
        named = {link.from_id: link for link in links}
        evidence = [
            Evidence(
                kind="entity",
                id=str(card.entity_id),
                name=card.name,
                detail=f"{card.kind}, state {state}" + (" (deduced)" if card.deduced else ""),
            ),
            *(
                Evidence(
                    kind="relationship",
                    id=None,
                    name=f"{user.name} → {card.name}",
                    detail=named[user.id].role
                    + (f": {named[user.id].evidence}" if named[user.id].evidence else "")
                    + (" (inferred)" if named[user.id].origin == "inferred" else ""),
                )
                for user in users[:MAX_NAMED]
            ),
        ]
        confidences = [named[user.id].confidence for user in users]
        drafts.append(
            Draft(
                key=f"entity:{card.entity_id}",
                code="dependency.concentration",
                severity=severity,
                subject=_subject(card),
                statement=f"{_things(count)} on {card.name} ({card.kind}); {said}.",
                params={
                    "name": card.name,
                    "kind": card.kind,
                    "dependents": count,
                    "status": state,
                    "watched": watched,
                    "deduced": card.deduced,
                    "users": [user.name for user in users[:MAX_NAMED]],
                },
                score=min(1.0, count / 10),
                confidence=round(sum(confidences) / len(confidences), 3),
                related=tuple(_subject(user) for user in users[:MAX_NAMED]),
                evidence=tuple(evidence),
                sources=tuple(sorted({*card.sources, *(s for u in users for s in u.sources)})),
            )
        )
    return drafts


# ── ownership ──────────────────────────────────────────────────────────


def ownership(material: Material) -> list[Draft]:
    """What runs or keeps data and has no owner named for it — no team, no
    person a source says owns it: graver the more rely on it, or when it is
    in incident; one step lighter when people maintain it by their work."""
    architecture = material.architecture
    if architecture is None:
        return []
    cards = _cards(material)
    relied = _dependents(architecture.links)
    drafts: list[Draft] = []
    for card in cards.values():
        if card.column not in OWNED_COLUMNS or card.team is not None:
            continue
        if card.entity_id is not None and material.owners.get(card.entity_id):
            continue
        count = sum(1 for link in relied.get(card.id, []) if link.from_id in cards)
        if count >= MIN_DEPENDENTS or card.status == "incident":
            severity = Severity.HIGH
        elif card.column == "services" or count >= 1:
            severity = Severity.MEDIUM
        else:
            severity = Severity.LOW
        maintainers = [person.name for person in card.maintainers]
        if maintainers:
            severity = Severity.MEDIUM if severity is Severity.HIGH else Severity.LOW
        statement = f"No team or person is named as owner of {card.name} ({card.kind})"
        if count:
            statement += f"; {_things(count)} on it"
        if maintainers:
            statement += f"; {', '.join(maintainers[:3])} maintain it by their work"
        drafts.append(
            Draft(
                key=f"entity:{card.entity_id}",
                code="ownership.no_owner",
                severity=severity,
                subject=_subject(card),
                statement=statement + ".",
                params={
                    "name": card.name,
                    "kind": card.kind,
                    "dependents": count,
                    "maintainers": maintainers[:MAX_NAMED],
                },
                score=min(1.0, count / 10),
                confidence=NO_OWNER_CONFIDENCE,
                related=tuple(
                    Subject(type="entity", id=person.id, name=person.name, kind="person")
                    for person in card.maintainers[:MAX_NAMED]
                ),
                evidence=(
                    Evidence(
                        kind="entity",
                        id=str(card.entity_id),
                        name=card.name,
                        detail="no source names a team or a person that owns it",
                    ),
                ),
                sources=tuple(sorted(card.sources)),
            )
        )
    return drafts


def _things(count: int) -> str:
    """One or more: "1 thing relies", "3 things rely"."""
    return "1 thing relies" if count == 1 else f"{count} things rely"


# ── context health ─────────────────────────────────────────────────────


def _context_subject(context: ContextStanding) -> Subject:
    return Subject(type="context", id=context.id, name=context.title, kind="context")


def _context_evidence(context: ContextStanding) -> Evidence:
    quality = f"judged {context.level}" if context.level else "not judged"
    return Evidence(
        kind="context",
        id=str(context.id),
        name=context.title,
        detail=f"version {context.version}, {quality}, {context.pending} model changes pending",
    )


def context_health(material: Material) -> list[Draft]:
    """The contexts in use that failed, fell behind the model, or whose
    latest version was judged weak."""
    if material.contexts is None:
        return []
    now = material.now
    drafts: list[Draft] = []
    for context in material.contexts:
        if context.status == "archived" or context.used_at is None:
            continue
        idle = now - context.used_at
        if idle > USED_AT_ALL:
            continue
        recent = idle <= USED_RECENTLY

        def draft(
            issue: str,
            code: str,
            severity: Severity,
            statement: str,
            params: dict[str, object],
            score: float,
            context: ContextStanding = context,
        ) -> Draft:
            return Draft(
                key=f"context:{context.id}:{issue}",
                code=code,
                severity=severity,
                subject=_context_subject(context),
                statement=statement,
                params={"title": context.title, "version": context.version, **params},
                score=score,
                evidence=(_context_evidence(context),),
                context_version=context.version,
            )

        if context.status == "failed":
            drafts.append(
                draft(
                    "failed",
                    "context.failed",
                    Severity.HIGH if recent else Severity.MEDIUM,
                    f"The context “{context.title}” could not be assembled again.",
                    {},
                    1.0 if recent else 0.5,
                )
            )
            continue
        since = context.stale_since
        if (
            context.follow
            and since is not None
            and context.pending > 0
            and now - since >= BEHIND_AFTER
        ):
            drafts.append(
                draft(
                    "behind",
                    "context.behind",
                    Severity.MEDIUM if recent else Severity.LOW,
                    f"The context “{context.title}” is behind the company model since "
                    f"{since.date().isoformat()}: {context.pending} changes not taken in.",
                    {"pending": context.pending, "since": since.isoformat()},
                    min(1.0, context.pending / 20),
                )
            )
        if context.level == "low":
            scored = "nothing" if context.score is None else f"{context.score:.2f}"
            drafts.append(
                draft(
                    "weak",
                    "context.weak",
                    Severity.MEDIUM if recent else Severity.LOW,
                    f"The context “{context.title}” was judged weak: its version "
                    f"{context.version} scored {scored}.",
                    {"score": context.score},
                    1.0 - (context.score or 0.0),
                )
            )
    return drafts


# Every analysis LEKA runs: these, and the epic's after them (LEKA-378 on).
ANALYZERS: tuple[Analyzer, ...] = (
    Analyzer(
        name="dependency_concentration",
        version=1,
        category="architecture",
        method=Method.RULES,
        reads=frozenset({Reads.MODEL}),
        summary="What many things rely on, and whether it is watched and well.",
        run=dependency_concentration,
    ),
    Analyzer(
        name="ownership",
        version=1,
        category="organisation",
        method=Method.RULES,
        reads=frozenset({Reads.MODEL}),
        summary="What runs or keeps data with no owner named for it, team or person.",
        run=ownership,
    ),
    Analyzer(
        name="context_health",
        version=1,
        category="context",
        method=Method.RULES,
        reads=frozenset({Reads.CONTEXT}),
        summary="The contexts in use that failed, fell behind the model or were judged weak.",
        run=context_health,
    ),
    # Change and impact (LEKA-378): changes.py.
    CHANGE_IMPACT,
    # Knowledge gaps (LEKA-379): gaps.py.
    *GAPS,
    # Knowledge enrichment (LEKA-380): enrichment.py — proposals, not findings.
    *ENRICHMENT,
    # Knowledge conflicts (LEKA-382): conflicts.py — disagreements to settle.
    CONFLICTS,
    # Knowledge quality (LEKA-381): quality.py — scores, and what is weak.
    QUALITY,
    # Knowledge evolution (LEKA-383): evolution.py — what the course says.
    *EVOLUTION,
)


def analyzer_named(name: str) -> Analyzer | None:
    return next((analyzer for analyzer in ANALYZERS if analyzer.name == name), None)
