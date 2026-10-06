"""Knowledge conflicts (LEKA-382): what the model's sources disagree on,
how much each is to be believed, and what LEKA recommends — never decided
in silence.

Resolution (LEKA-357) chooses a value when the sources of one thing
disagree — the most recent, then the surest — and keeps every value. The
context engine (LEKA-372) says the disagreements of what a context holds.
This finds them across the whole model, weighs each side, recommends one,
and leaves the decision to a person (arbitration.py).

WHAT IS A CONFLICT

    attribute     the sources of one thing say two values or more:
                  payment-api's SLA is 99.95 to GitHub, 99.9 to Datadog
    relationship  a thing has one of something and is said to have
                  several: two owners, two managers, two parents

Of what runs, keeps data or is the company's (knowledge.graph.DISPUTED):
a ticket's or a commit's disagreements follow theirs.

HOW MUCH A SOURCE IS TO BE BELIEVED — authority, from 0 to 1. By default,
from its family (its connector's category) and what is disagreed on: the
monitoring tool on a state, the cloud on where a thing runs, the code host
on who owns what, the catalogue (a custom source) on how critical. The
workspace overrides it (AUTHORITY RULES): on an attribute — or everything,
`*` — a source preferred is believed at 1, one avoided at 0.1.

EACH SIDE, scored:

    authority      its most believed source's — x 0.6 for an inferred tie
    freshness      its most recent: 7 days 1, 30 days 0.8, 90 days 0.5,
                   older 0.3, unknown 0.5 — x 0.6 for a source in error,
                   x 0.3 for one disabled
    corroboration  how many sources say it: a third each, up to 1

    score = 0.55 x authority + 0.3 x freshness + 0.15 x corroboration

THE RECOMMENDATION: the best side, and how strongly — `rule` when a rule
the workspace set makes it, `clear` ahead by 0.1 or more, `weak` ahead by
less, `none` tied: no recommendation. With its reasons: rule, authority,
fresher, corroborated, chosen (what the model shows already).

Pure: the material in, conflicts out.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from leka.intelligence.analysis import (
    Analyzer,
    Authority,
    ConflictDraft,
    Material,
    Method,
    Reads,
    Subject,
)
from leka.knowledge import Dispute, DisputeSide, DisputeSource

# What a disagreement is about, by the attribute (or role) disagreed on.
DOMAINS: dict[str, frozenset[str]] = {
    "operations": frozenset(
        {"status", "state", "health", "open_incidents", "incidents_90d", "mttr_minutes"}
        | {"deployment", "severity", "priority"}
    ),
    "runtime": frozenset(
        {"environment", "environments", "region", "zone", "instance_type", "runtime"}
        | {"image", "hosting", "account", "engine", "version", "provider", "public_url"}
    ),
    "organisation": frozenset(
        {"owner", "manager", "lead", "parent", "team", "email", "title", "department"}
        | {"location", "point_of_contact"}
    ),
    "business": frozenset(
        {"criticality", "criticality_raw", "tier", "sla", "stage", "description", "category"}
    ),
}
# Who is believed first on each, by connector category.
ORDER: dict[str | None, tuple[str, ...]] = {
    "operations": ("observability", "cloud", "code", "project", "docs", "data", "custom"),
    "runtime": ("cloud", "code", "observability", "data", "project", "docs", "custom"),
    "organisation": ("code", "project", "docs", "observability", "cloud", "data", "custom"),
    "business": ("custom", "code", "observability", "docs", "project", "cloud", "data"),
    None: ("code", "cloud", "observability", "project", "docs", "data", "custom"),
}
RANKS = (1.0, 0.85, 0.7, 0.6, 0.5, 0.4, 0.35)
UNKNOWN_AUTHORITY = 0.3
PREFERRED, AVOIDED = 1.0, 0.1
INFERRED = 0.6
FRESH = ((timedelta(days=7), 1.0), (timedelta(days=30), 0.8), (timedelta(days=90), 0.5))
STALE, UNDATED = 0.3, 0.5
STATUS = {"error": 0.6, "degraded": 0.8, "disabled": 0.3}
WEIGHTS = {"authority": 0.55, "freshness": 0.3, "corroboration": 0.15}
CLEAR = 0.1
REASON_GAP = 0.1


def domain(about: str) -> str | None:
    return next((name for name, held in DOMAINS.items() if about in held), None)


def default_authority(category: str | None, about: str) -> float:
    """How much a source of this family is to be believed on this, by
    default."""
    order = ORDER[domain(about)]
    if category not in order:
        return UNKNOWN_AUTHORITY
    return RANKS[order.index(category)]


def stance(rules: Sequence[Authority], source: DisputeSource, about: str) -> str | None:
    """What the workspace says of this source on this: the rule on the
    attribute first, then the rule on everything."""
    if source.source_id is None:
        return None
    for wanted in (about, "*"):
        for rule in rules:
            if rule.source_id == source.source_id and rule.about == wanted:
                return rule.stance
    return None


def freshness(source: DisputeSource, now: datetime) -> float:
    if source.observed_at is None:
        fresh = UNDATED
    else:
        age = now - source.observed_at
        fresh = next((score for within, score in FRESH if age <= within), STALE)
    return round(fresh * STATUS.get(source.status or "", 1.0), 3)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def assess(
    dispute: Dispute,
    material: Material,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Every side, scored; and the recommendation."""
    sides: list[dict[str, object]] = []
    for side in dispute.sides:
        sides.append(_side(side, dispute, material))
    ranked = sorted(range(len(sides)), key=lambda i: -float(str(sides[i]["score"])))
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    margin = (
        float(str(sides[best]["score"])) - float(str(sides[second]["score"]))
        if second is not None
        else 1.0
    )
    ruled = bool(sides[best]["ruled"]) and (second is None or not sides[second]["ruled"])
    if margin <= 0 and not ruled:
        return sides, {"side": None, "strength": "none", "reasons": [], "margin": 0.0}
    strength = "rule" if ruled else "clear" if margin >= CLEAR else "weak"
    return sides, {
        "side": best,
        "strength": strength,
        "reasons": _reasons(sides, best, second, dispute),
        "margin": round(margin, 3),
    }


def _side(side: DisputeSide, dispute: Dispute, material: Material) -> dict[str, object]:
    rules = material.authority
    sources: list[dict[str, object]] = []
    authorities: list[float] = []
    fresh: list[float] = []
    ruled = False
    for source in side.sources:
        said = stance(rules, source, dispute.about)
        category = material.categories.get(source.kind or "")
        trust = (
            PREFERRED
            if said == "prefer"
            else AVOIDED
            if said == "avoid"
            else default_authority(category, dispute.about)
        )
        ruled = ruled or said == "prefer"
        authorities.append(trust)
        fresh.append(freshness(source, material.now))
        sources.append(
            {
                "source_id": str(source.source_id) if source.source_id else None,
                "kind": source.kind,
                "name": source.name,
                "status": source.status,
                "observed_at": source.observed_at.isoformat() if source.observed_at else None,
                "authority": round(trust, 3),
                "rule": said,
            }
        )
    origin = 1.0 if side.origin in (None, "stated", "accepted") else INFERRED
    authority = round((max(authorities) if authorities else UNKNOWN_AUTHORITY) * origin, 3)
    freshest = max(fresh) if fresh else UNDATED
    corroboration = round(min(1.0, len(side.sources) / 3), 3)
    score = round(
        WEIGHTS["authority"] * authority
        + WEIGHTS["freshness"] * freshest
        + WEIGHTS["corroboration"] * corroboration,
        3,
    )
    return {
        "value": side.value,
        "ref_id": str(side.ref_id) if side.ref_id else None,
        "origin": side.origin,
        "sources": sources,
        "authority": authority,
        "freshness": freshest,
        "corroboration": corroboration,
        "score": score,
        "ruled": ruled,
        "edges": list(side.edges),
    }


def _reasons(
    sides: list[dict[str, object]], best: int, second: int | None, dispute: Dispute
) -> list[str]:
    reasons: list[str] = []
    top = sides[best]
    if top["ruled"]:
        reasons.append("rule")
    if second is not None:
        other = sides[second]
        if float(str(top["authority"])) - float(str(other["authority"])) >= REASON_GAP:
            reasons.append("authority")
        if float(str(top["freshness"])) - float(str(other["freshness"])) >= REASON_GAP:
            reasons.append("fresher")
        if float(str(top["corroboration"])) > float(str(other["corroboration"])):
            reasons.append("corroborated")
    if dispute.kind == "attribute" and _canonical(top["value"]) == _canonical(dispute.chosen):
        reasons.append("chosen")
    return reasons


def _short(value: object) -> str:
    said = value if isinstance(value, str) else json.dumps(value, default=str)
    return said if len(said) <= 60 else said[:57] + "…"


def _who(side: Mapping[str, object]) -> str:
    sources = side.get("sources")
    names = [
        str(s.get("name") or s.get("kind") or "a source")
        for s in (sources if isinstance(sources, list) else [])
        if isinstance(s, dict)
    ]
    return ", ".join(names) or "no source named"


def statement(
    dispute: Dispute, sides: list[dict[str, object]], recommended: Mapping[str, object]
) -> str:
    what = (
        f"{dispute.entity.name}'s sources disagree on {dispute.about}"
        if dispute.kind == "attribute"
        else f"{dispute.entity.name} has one {dispute.about} and is said to have {len(sides)}"
    )
    said = "; ".join(f"{_short(side['value'])} ({_who(side)})" for side in sides)
    index = recommended.get("side")
    if not isinstance(index, int):
        return f"{what}: {said}. No side stands out."
    reasons = recommended.get("reasons")
    why = ", ".join(str(r) for r in reasons) if isinstance(reasons, list) and reasons else ""
    return (
        f"{what}: {said}. LEKA recommends {_short(sides[index]['value'])}"
        + (f" ({why})" if why else "")
        + "."
    )


def key_of(dispute: Dispute) -> str:
    return f"conflict.{dispute.kind}:{dispute.entity.id}:{dispute.about}"


def find_conflicts(material: Material) -> list[ConflictDraft]:
    """Every disagreement of the model, assessed."""
    found: list[ConflictDraft] = []
    for dispute in material.disputes or ():
        sides, recommended = assess(dispute, material)
        kinds = sorted(
            {
                str(source.get("kind"))
                for side in sides
                for source in side["sources"]  # type: ignore[attr-defined]
                if isinstance(source, dict) and source.get("kind")
            }
        )
        found.append(
            ConflictDraft(
                key=key_of(dispute),
                kind=dispute.kind,
                subject=Subject(
                    type="entity",
                    id=dispute.entity.id,
                    name=dispute.entity.name,
                    kind=dispute.entity.type.value,
                ),
                about=dispute.about,
                relationship=dispute.relationship,
                chosen=dispute.chosen,
                sides=tuple(sides),
                recommendation=recommended,
                statement=statement(dispute, sides, recommended),
                settled=dispute.settled,
                sources=tuple(kinds),
            )
        )
    return found


ANALYZER = Analyzer(
    name="conflicts",
    version=1,
    category="conflicts",
    method=Method.RULES,
    reads=frozenset({Reads.CONFLICTS}),
    summary="What the model's sources disagree on: each side weighed, one recommended.",
    run=find_conflicts,
)
