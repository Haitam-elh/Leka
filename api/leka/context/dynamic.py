"""A context keeping up with the company (LEKA-374) — the decisions, pure.

The company model is built again whenever the sources say something new,
and each build records what it changed: the entities added, changed — and
what of them — or removed, the relationships that appeared, changed or
went (leka.knowledge). A context holds a copy of some of that. What this
module decides:

    touched()        which of a build's changes are news to which context:
                     something it holds — an entity, an end of a
                     relationship — or a new thing its words name; only
                     what was recorded after the build it last read
    pending()        what a context is behind on, the news added — each
                     change once, however many times it is told — the
                     latest MAX_PENDING kept, all of them counted
    following()      whether it is made again on its own: `active` when it
                     follows the model and was used in the last ACTIVE_DAYS,
                     `dormant` when not used since — made again when asked —
                     `off` when it follows nothing, `archived`
    freshness()      whether it is up to date, and if not why and since when
    widened()        its request expanded — as asked, or one step: a step
                     further, twice the budget, twice the window
    narrowed()       its request compressed — as asked, or half its budget,
                     the most relevant kept
    request_changes(), intent_changes()
                     what of a request or an intention changed, said as
                     changes: what a version made by them says made it

Spending is adaptive: a context in use is made again as soon as what it
holds changes; one nobody reads is only marked — what it is behind on is
said, and it is made again when someone asks. Nothing here reads the
database or the clock: service.py and job.py do, and call these.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta

from leka.context.intent import NAMED, named
from leka.context.schemas import (
    MAX_BUDGET,
    MAX_DEPTH,
    MAX_ROOTS,
    MAX_WINDOW_DAYS,
    ContextChange,
    ContextCompress,
    ContextExpand,
    ContextFreshness,
    ContextRequest,
    Following,
    IntentPlan,
)
from leka.knowledge import EntityBrief, EntityType, Lifecycle, ModelChange

# Not used for this long: no longer made again on its own.
ACTIVE_DAYS = 14
# What a context, a version or a check keeps of the changes: the latest.
MAX_PENDING = 50
# A read says a context is in use at most this often: one write an hour.
USED_EVERY = timedelta(hours=1)

TYPES = frozenset(kind.value for kind in EntityType)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# The request's fields, in the order a change to them is said.
REQUEST_FIELDS = (
    "roots",
    "query",
    "depth",
    "relationships",
    "environment",
    "limit",
    "window_days",
    "until",
    "min_relevance",
    "weights",
    "sources",
)


class RefusedError(ValueError):
    """A request that cannot be widened or narrowed as asked."""


# ── what is news to whom ────────────────────────────────────────────────────


def change_of(change: ModelChange, touches: str) -> ContextChange:
    """A change of the model, as a context says it."""
    return ContextChange(
        kind=change.kind,
        change=change.change,
        ref_id=change.entity_id,
        from_id=change.from_id,
        to_id=change.to_id,
        type=change.type,
        name=change.name,
        fields=list(change.fields),
        at=change.at,
        touches="held" if touches == "held" else "words",
    )


def touched(
    changes: Sequence[ModelChange],
    *,
    held: Mapping[uuid.UUID, Iterable[uuid.UUID]],
    checked: Mapping[uuid.UUID, datetime | None],
    worded: Mapping[uuid.UUID, str] | None = None,
) -> dict[uuid.UUID, list[ContextChange]]:
    """Which changes are news to which contexts.

    `held` is, for each entity some contexts hold, those contexts; `checked`
    the build each context last read — what was recorded before it, it
    already holds; `worded` each context's words, for the new things they
    name (as an intention names what it is about: every word of a name,
    LEKA-373). A relationship touches the contexts that hold either end.
    """
    news: dict[uuid.UUID, list[ContextChange]] = {}

    def tell(context_id: uuid.UUID, change: ModelChange, touches: str) -> None:
        last = checked.get(context_id)
        if last is not None and change.at <= last:
            return
        said = news.setdefault(context_id, [])
        if not any(_key(c) == _key(change_of(change, touches)) for c in said):
            said.append(change_of(change, touches))

    added: list[ModelChange] = []
    for change in changes:
        if change.kind == "entity" and change.entity_id is not None:
            for context_id in held.get(change.entity_id, ()):
                tell(context_id, change, "held")
            if change.change == "added":
                added.append(change)
        else:
            ends = {change.from_id, change.to_id} - {None}
            for context_id in {c for end in ends if end for c in held.get(end, ())}:
                tell(context_id, change, "held")

    if worded and added:
        briefs = {brief.id: (brief, change) for change in added if (brief := _brief(change))}
        for context_id, text in worded.items():
            for reading in named(text, [brief for brief, _ in briefs.values()]):
                if reading.confidence >= NAMED:
                    tell(context_id, briefs[reading.entity.id][1], "words")
    return news


def _brief(change: ModelChange) -> EntityBrief | None:
    """A new entity, as named() reads one."""
    if change.entity_id is None or change.type not in TYPES:
        return None
    return EntityBrief(
        id=change.entity_id,
        type=EntityType(change.type),
        key=change.name,
        name=change.name,
        lifecycle=Lifecycle.ACTIVE,
    )


def _key(change: ContextChange) -> tuple[object, ...]:
    """A change, once: told twice — a build followed again — it is one."""
    return (
        change.kind,
        change.change,
        change.ref_id,
        change.from_id,
        change.to_id,
        change.type,
        change.field,
        change.at,
    )


def pending(
    behind: Sequence[ContextChange], news: Sequence[ContextChange], count: int
) -> tuple[list[ContextChange], int]:
    """What a context is behind on, with the news: each change once, the
    latest MAX_PENDING kept, and how many in all."""
    known = {_key(change) for change in behind}
    fresh = [change for change in news if _key(change) not in known]
    kept = sorted([*behind, *fresh], key=lambda c: c.at or EPOCH)[-MAX_PENDING:]
    return kept, count + len(fresh)


# ── up to date, followed ────────────────────────────────────────────────────


def following(
    *,
    status: str,
    follow: bool,
    used_at: datetime | None,
    created_at: datetime,
    now: datetime,
) -> Following:
    """Whether a context is made again on its own."""
    if status == "archived":
        return "archived"
    if not follow:
        return "off"
    if (used_at or created_at) < now - timedelta(days=ACTIVE_DAYS):
        return "dormant"
    return "active"


def freshness(
    *,
    status: str,
    follow: bool,
    used_at: datetime | None,
    created_at: datetime,
    stale_since: datetime | None,
    behind: Sequence[ContextChange],
    behind_count: int,
    checked_at: datetime | None,
    checked_model_at: datetime | None,
    now: datetime,
) -> ContextFreshness:
    """Whether a context is up to date: `stale` when the model changed what
    it holds since its last check, or when that check failed."""
    reasons: list[str] = []
    if stale_since is not None or behind_count:
        reasons.append("changes")
    if status == "failed":
        reasons.append("failed")
    return ContextFreshness.model_validate(
        {
            "state": "stale" if reasons else "fresh",
            "reasons": reasons,
            "since": stale_since,
            "changes": behind_count,
            "pending": list(behind),
            "checked_at": checked_at,
            "checked_model_at": checked_model_at,
            "following": following(
                status=status, follow=follow, used_at=used_at, created_at=created_at, now=now
            ),
        }
    )


# ── wider, narrower ─────────────────────────────────────────────────────────


def widened(request: ContextRequest, ask: ContextExpand) -> ContextRequest:
    """The request expanded as asked — each field only wider — or, nothing
    asked, one step: a step further, twice the budget and the window, as
    far as each goes. Refused when it widens nothing."""
    asked = (
        ask.depth is not None
        or ask.limit is not None
        or ask.window_days is not None
        or ask.min_relevance is not None
        or bool(ask.roots)
        or bool(ask.relationships)
    )
    if not asked:
        wider = request.model_copy(
            update={
                "depth": min(MAX_DEPTH, request.depth + 1),
                "limit": min(MAX_BUDGET, request.limit * 2),
                "window_days": min(MAX_WINDOW_DAYS, request.window_days * 2),
            }
        )
        if wider == request:
            raise RefusedError("This context is as wide as it goes.")
        return wider
    for name, value, now in (
        ("depth", ask.depth, request.depth),
        ("limit", ask.limit, request.limit),
        ("window_days", ask.window_days, request.window_days),
    ):
        if value is not None and value < now:
            raise RefusedError(f"Expanding only widens: {name} is {now}, not more than {value}.")
    if ask.min_relevance is not None and ask.min_relevance > request.min_relevance:
        raise RefusedError(
            f"Expanding only widens: min_relevance is {request.min_relevance:g}, "
            f"not less than {ask.min_relevance:g}."
        )
    roots = list(dict.fromkeys([*request.roots, *ask.roots]))
    if len(roots) > MAX_ROOTS:
        raise RefusedError(f"A context starts from {MAX_ROOTS} roots at most.")
    relationships = (
        sorted({*request.relationships, *(kind.value for kind in ask.relationships)})
        if request.relationships
        else []
    )
    wider = request.model_copy(
        update={
            "roots": roots,
            "depth": ask.depth if ask.depth is not None else request.depth,
            "limit": ask.limit if ask.limit is not None else request.limit,
            "window_days": (
                ask.window_days if ask.window_days is not None else request.window_days
            ),
            "min_relevance": (
                ask.min_relevance if ask.min_relevance is not None else request.min_relevance
            ),
            "relationships": relationships,
        }
    )
    if wider == request:
        raise RefusedError("Nothing to widen: it already holds that much.")
    return wider


def narrowed(request: ContextRequest, ask: ContextCompress) -> ContextRequest:
    """The request compressed as asked — each field only narrower — or,
    nothing asked, half its budget: the most relevant half. Its roots are
    always kept. Refused when it narrows nothing."""
    floor = max(1, len(request.roots))
    asked = (
        ask.depth is not None
        or ask.limit is not None
        or ask.window_days is not None
        or ask.min_relevance is not None
    )
    if not asked:
        narrower = request.model_copy(update={"limit": max(floor, request.limit // 2)})
        if narrower == request:
            raise RefusedError("This context is as narrow as it goes.")
        return narrower
    for name, value, now in (
        ("depth", ask.depth, request.depth),
        ("limit", ask.limit, request.limit),
        ("window_days", ask.window_days, request.window_days),
    ):
        if value is not None and value > now:
            raise RefusedError(f"Compressing only narrows: {name} is {now}, not less than {value}.")
    if ask.min_relevance is not None and ask.min_relevance < request.min_relevance:
        raise RefusedError(
            f"Compressing only narrows: min_relevance is {request.min_relevance:g}, "
            f"not more than {ask.min_relevance:g}."
        )
    if ask.limit is not None and ask.limit < floor:
        raise RefusedError(f"It keeps its {floor} roots: a budget of {floor} at least.")
    narrower = request.model_copy(
        update={
            "depth": ask.depth if ask.depth is not None else request.depth,
            "limit": ask.limit if ask.limit is not None else request.limit,
            "window_days": (
                ask.window_days if ask.window_days is not None else request.window_days
            ),
            "min_relevance": (
                ask.min_relevance if ask.min_relevance is not None else request.min_relevance
            ),
        }
    )
    if narrower == request:
        raise RefusedError("Nothing to narrow: it already holds that little.")
    return narrower


# ── what changed of a request, of an intention ──────────────────────────────


def request_changes(before: ContextRequest, after: ContextRequest) -> list[ContextChange]:
    """What of a request changed, field by field."""
    was = before.model_dump(mode="json")
    now = after.model_dump(mode="json")
    return [
        ContextChange(
            kind="request", change="changed", field=name, before=was[name], after=now[name]
        )
        for name in REQUEST_FIELDS
        if was.get(name) != now.get(name)
    ]


def intent_changes(before: IntentPlan | None, after: IntentPlan) -> list[ContextChange]:
    """What LEKA reads differently of an intention asked again: its words,
    its kind, what it is about, when, where."""

    def said(plan: IntentPlan | None) -> dict[str, object]:
        if plan is None:
            return {}
        return {
            "text": plan.text,
            "kind": plan.kind,
            "subjects": [subject.name for subject in plan.subjects],
            "period": {
                "since": plan.period.since.isoformat(),
                "until": plan.period.until.isoformat(),
            },
            "environment": plan.environment,
        }

    was, now = said(before), said(after)
    return [
        ContextChange(
            kind="intent", change="changed", field=name, before=was.get(name), after=now[name]
        )
        for name in now
        if was.get(name) != now[name]
    ]
