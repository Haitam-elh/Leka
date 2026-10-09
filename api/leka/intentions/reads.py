"""What an analysis and LEKA's analyst both read the same way: where a
change happened, and what LEKA learned in a period.

    same_environment   « prod » is production
    in_environment     a change in the environment asked — one that says
                       none (a merge, a release) may be anywhere
    learned_between    what LEKA's model gained, changed, lost between two
                       dates (LEKA-383): the things, not the events
"""

from __future__ import annotations

import uuid
from datetime import datetime

from leka.context.intent import ENVIRONMENT_WORDS
from leka.intentions.analysis import Learned
from leka.knowledge import EntityBrief, EntityType, EvolutionRepository

# What a thing is that changes or happens: told by the changes and the
# incidents, never as something LEKA learned.
HAPPENINGS = frozenset(
    {
        EntityType.DEPLOYMENT,
        EntityType.CHANGE,
        EntityType.RELEASE,
        EntityType.PULL_REQUEST,
        EntityType.COMMIT,
        EntityType.INCIDENT,
        EntityType.ISSUE,
    }
)
# What a version's kind is called, as the analysis says it.
LEARNED_AS = {
    "created": "appeared",
    "changed": "changed",
    "removed": "went",
    "returned": "came_back",
}
MAX_LEARNED = 30


def same_environment(one: str, other: str) -> bool:
    """« prod » is production: two names of one environment."""

    def canonical(name: str) -> str:
        word = name.strip().lower()
        return next(
            (named for named, words in ENVIRONMENT_WORDS.items() if word in (named, *words)),
            word,
        )

    return canonical(one) == canonical(other)


def in_environment(said: str | None, asked: str | None) -> bool:
    """Whether a change said to be in `said` is in the environment asked:
    every one when none is asked, and one that says none — a merge, a
    release — may be anywhere."""
    if not asked or not said:
        return True
    return same_environment(said, asked)


async def learned_between(
    repository: EvolutionRepository,
    ids: set[uuid.UUID],
    *,
    since: datetime,
    until: datetime,
    types: frozenset[EntityType] = frozenset(),
    most: int = MAX_LEARNED,
) -> list[Learned]:
    """What LEKA's model gained, changed, lost between two dates: the
    things themselves — services, repositories, databases, resources,
    teams, documents — not the events, which the changes and incidents
    tell. Of `ids` only when some are given; of `types` only when some are."""
    recorded = await repository.recorded_between(since=since, until=until, limit=most * 8)
    first: dict[uuid.UUID, tuple[str, list[str], datetime]] = {}
    # The latest first: what it became, then — further down — what it was
    # first in the period. Appeared, then changed, is something that appeared.
    for _row, entity, _number, kind, changed, at, _run in recorded:
        if ids and entity not in ids:
            continue
        held = first.get(entity)
        if held is None:
            first[entity] = (kind, list(changed), at)
        else:
            first[entity] = (kind if kind == "created" else held[0], held[1] + changed, held[2])
    things = await repository.by_ids(list(first))
    learned = [
        Learned(
            thing=EntityBrief.model_validate(things[ident]),
            change=LEARNED_AS.get(kind, kind),
            fields=() if kind == "created" else tuple(dict.fromkeys(fields))[:8],
            at=at,
        )
        for ident, (kind, fields, at) in first.items()
        if ident in things
        and things[ident].type not in HAPPENINGS
        and (not types or things[ident].type in types)
    ]
    learned.sort(key=lambda item: item.at, reverse=True)
    return learned[:most]
