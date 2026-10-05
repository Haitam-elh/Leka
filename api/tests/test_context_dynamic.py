"""A context keeping up with the company (LEKA-374) — the decisions, pure:
leka/context/dynamic.py.

What these protect: a build's change is news to the contexts that hold
what changed — an entity, or an end of a relationship — and to those whose
words name a new thing, never to one that already read that build; each
change is said once however often it is told, the latest kept, all of them
counted; a context is active, dormant, off or archived, fresh or behind and
why; widened, it goes one step — a step further, twice the budget and the
window — or as asked, never narrower, never past its bounds; compressed, it
keeps half its budget or as asked, never fewer than its roots; and what of a
request or an intention changed is said field by field.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from leka.context.dynamic import (
    MAX_PENDING,
    RefusedError,
    change_of,
    following,
    freshness,
    intent_changes,
    narrowed,
    pending,
    request_changes,
    touched,
    widened,
)
from leka.context.schemas import (
    ContextChange,
    ContextCompress,
    ContextExpand,
    ContextFreshness,
    ContextRequest,
    IntentPeriod,
    IntentPlan,
    IntentSubject,
)
from leka.knowledge import ModelChange, RelationshipType

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
BEFORE = NOW - timedelta(hours=2)
BUILT = NOW - timedelta(hours=1)

BILLING, CHECKOUT, PAYMENTS, LEDGER = (uuid.uuid4() for _ in range(4))
ONE, TWO, THREE = (uuid.uuid4() for _ in range(3))


def _entity(entity: uuid.UUID, name: str, change: str = "changed", **more: object) -> ModelChange:
    return ModelChange.model_validate(
        {
            "kind": "entity",
            "change": change,
            "entity_id": entity,
            "type": "service",
            "name": name,
            "at": BUILT,
            "run_id": None,
            **more,
        }
    )


def _edge(one: uuid.UUID, other: uuid.UUID, change: str = "added") -> ModelChange:
    return ModelChange.model_validate(
        {
            "kind": "relationship",
            "change": change,
            "from_id": one,
            "to_id": other,
            "type": "depends_on",
            "name": "Checkout → Billing API",
            "at": BUILT,
            "run_id": None,
        }
    )


def _request(**over: object) -> ContextRequest:
    return ContextRequest.model_validate(
        {
            "roots": [str(BILLING)],
            "depth": 1,
            "relationships": [],
            "environment": None,
            "limit": 100,
            "strategy": "hybrid",
            **over,
        }
    )


# ── what is news to whom ────────────────────────────────────────────────────


def test_a_change_is_news_to_the_contexts_holding_it_or_an_end() -> None:
    changes = [
        _entity(BILLING, "Billing API", fields=["lifecycle"]),
        _edge(CHECKOUT, PAYMENTS),
        _entity(uuid.uuid4(), "Nobody's"),
    ]
    news = touched(
        changes,
        held={BILLING: [ONE], PAYMENTS: [TWO, THREE]},
        checked={ONE: BEFORE, TWO: BEFORE, THREE: NOW},
    )

    assert set(news) == {ONE, TWO}
    [said] = news[ONE]
    assert (said.kind, said.change, said.ref_id, said.fields, said.touches) == (
        "entity",
        "changed",
        BILLING,
        ["lifecycle"],
        "held",
    )
    assert [(c.kind, c.from_id, c.to_id) for c in news[TWO]] == [
        ("relationship", CHECKOUT, PAYMENTS)
    ]
    # THREE read a build made after: it already holds that.


def test_a_new_thing_its_words_name_is_news_and_nothing_else() -> None:
    changes = [
        _entity(LEDGER, "Ledger", change="added"),
        _entity(uuid.uuid4(), "Ledger reconciliation job", change="added"),
        _entity(uuid.uuid4(), "Payroll", change="added"),
    ]
    news = touched(
        changes,
        held={},
        checked={ONE: BEFORE, TWO: BEFORE},
        worded={ONE: "Why is the ledger slow?", TWO: "Who owns payments?"},
    )

    assert list(news) == [ONE]
    [said] = news[ONE]
    assert (said.ref_id, said.change, said.touches) == (LEDGER, "added", "words")


def test_each_change_is_said_once_the_latest_kept_all_counted() -> None:
    first = change_of(_entity(BILLING, "Billing API", fields=["name"]), "held")
    behind, count = pending([], [first], 0)
    assert (behind, count) == ([first], 1)

    # Told again — a build followed twice — it is the same change.
    assert pending(behind, [first], count) == ([first], 1)

    many = [
        change_of(_entity(uuid.uuid4(), f"S{i}", at=BUILT + timedelta(seconds=i)), "held")
        for i in range(MAX_PENDING + 5)
    ]
    kept, total = pending(behind, many, count)
    assert total == MAX_PENDING + 6
    assert len(kept) == MAX_PENDING
    assert kept[-1] == many[-1]
    assert first not in kept


# ── up to date, followed ────────────────────────────────────────────────────


def test_a_context_is_active_dormant_off_or_archived() -> None:
    lately = NOW - timedelta(days=2)
    long_ago = NOW - timedelta(days=30)

    def state(
        status: str = "assembled", follow: bool = True, used_at: datetime | None = lately
    ) -> str:
        return following(
            status=status, follow=follow, used_at=used_at, created_at=long_ago, now=NOW
        )

    assert state() == "active"
    assert state(used_at=None) == "dormant"
    assert state(used_at=long_ago) == "dormant"
    assert state(follow=False) == "off"
    assert state(status="archived") == "archived"


def test_a_context_is_fresh_or_says_why_it_is_behind_and_since_when() -> None:
    def read(
        status: str, since: datetime | None, behind: list[ContextChange], count: int
    ) -> ContextFreshness:
        return freshness(
            status=status,
            follow=True,
            used_at=NOW,
            created_at=NOW,
            stale_since=since,
            behind=behind,
            behind_count=count,
            checked_at=BEFORE,
            checked_model_at=BEFORE,
            now=NOW,
        )

    fresh = read("assembled", None, [], 0)
    assert (fresh.state, fresh.reasons, fresh.changes, fresh.following) == (
        "fresh",
        [],
        0,
        "active",
    )

    change = change_of(_entity(BILLING, "Billing API", fields=["lifecycle"]), "held")
    behind = read("failed", BUILT, [change], 3)
    assert (behind.state, behind.reasons, behind.since, behind.changes) == (
        "stale",
        ["changes", "failed"],
        BUILT,
        3,
    )
    assert behind.pending == [change]


# ── wider, narrower ─────────────────────────────────────────────────────────


def test_widened_one_step_further_twice_the_budget_and_window_as_far_as_each_goes() -> None:
    request = _request()
    wider = widened(request, ContextExpand())
    assert (wider.depth, wider.limit, wider.window_days) == (2, 200, 28)

    near_the_end = _request(depth=3, limit=400, window_days=300)
    capped = widened(near_the_end, ContextExpand())
    assert (capped.depth, capped.limit, capped.window_days) == (3, 500, 365)

    with pytest.raises(RefusedError, match="as wide as it goes"):
        widened(capped, ContextExpand())


def test_widened_as_asked_never_narrower() -> None:
    request = _request(relationships=["owned_by"], min_relevance=0.2)
    wider = widened(
        request,
        ContextExpand(
            depth=2,
            roots=[CHECKOUT],
            relationships=[RelationshipType.DEPENDS_ON],
            min_relevance=0.05,
        ),
    )
    assert wider.roots == [BILLING, CHECKOUT]
    assert wider.relationships == ["depends_on", "owned_by"]
    assert (wider.depth, wider.limit, wider.min_relevance) == (2, 100, 0.05)
    # Every kind already: more kinds widen nothing.
    assert (
        widened(
            _request(), ContextExpand(relationships=[RelationshipType.OWNS], depth=2)
        ).relationships
        == []
    )

    with pytest.raises(RefusedError, match="only widens: limit"):
        widened(request, ContextExpand(limit=50))
    with pytest.raises(RefusedError, match="only widens: min_relevance"):
        widened(request, ContextExpand(min_relevance=0.5))
    with pytest.raises(RefusedError, match="Nothing to widen"):
        widened(request, ContextExpand(depth=1))
    with pytest.raises(RefusedError, match="10 roots at most"):
        widened(request, ContextExpand(roots=[uuid.uuid4() for _ in range(10)]))


def test_compressed_to_half_its_budget_its_roots_kept_or_as_asked() -> None:
    assert narrowed(_request(), ContextCompress()).limit == 50
    roots = [str(uuid.uuid4()) for _ in range(3)]
    assert narrowed(_request(roots=roots, limit=5), ContextCompress()).limit == 3
    with pytest.raises(RefusedError, match="as narrow as it goes"):
        narrowed(_request(roots=roots, limit=3), ContextCompress())

    narrower = narrowed(_request(depth=2), ContextCompress(depth=1, min_relevance=0.3))
    assert (narrower.depth, narrower.limit, narrower.min_relevance) == (1, 100, 0.3)
    with pytest.raises(RefusedError, match="only narrows: window_days"):
        narrowed(_request(), ContextCompress(window_days=30))
    with pytest.raises(RefusedError, match="budget of 3 at least"):
        narrowed(_request(roots=roots), ContextCompress(limit=2))


# ── what changed of a request, of an intention ──────────────────────────────


def test_what_of_a_request_or_an_intention_changed_is_said_field_by_field() -> None:
    before = _request()
    after = widened(before, ContextExpand())
    assert [(c.kind, c.field, c.before, c.after) for c in request_changes(before, after)] == [
        ("request", "depth", 1, 2),
        ("request", "limit", 100, 200),
        ("request", "window_days", 14, 28),
    ]

    def plan(text: str, kind: str, names: list[str]) -> IntentPlan:
        return IntentPlan.model_validate(
            {
                "version": 1,
                "text": text,
                "intention_id": None,
                "kind": kind,
                "kind_said": [],
                "facets": ["technical"],
                "subjects": [
                    IntentSubject(
                        entity_id=uuid.uuid4(),
                        name=name,
                        type="service",
                        facet="technical",
                        how="named",
                        confidence=1,
                    )
                    for name in names
                ],
                "period": IntentPeriod(since=BEFORE, until=NOW, origin="kind"),
                "environment": None,
                "constraints": [],
                "request": before,
                "gaps": [],
            }
        )

    was = plan("Why is Billing API slow?", "diagnose", ["Billing API"])
    now = plan("What changed on Checkout?", "change", ["Checkout"])
    said = {c.field: (c.before, c.after) for c in intent_changes(was, now)}
    assert said == {
        "text": ("Why is Billing API slow?", "What changed on Checkout?"),
        "kind": ("diagnose", "change"),
        "subjects": (["Billing API"], ["Checkout"]),
    }
    assert intent_changes(was, was) == []
