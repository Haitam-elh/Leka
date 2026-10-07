"""An intention's context, judged (LEKA-387), pure.

What these protect: the ask the context engine reads is the one the scope
settled — what it excludes, the environment its words hold it to — and
nothing else changed; whether a context can ground an analysis is read from
its own quality, gaps and conflicts: a critical one blocks, a context
holding nothing blocks, warnings or a low level limit, nothing in the way
is ready — with what it holds by side and how many sources say it.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel

from leka.context import AssembledContext, IntentAsk
from leka.context.schemas import (
    ContextElementRead,
    ContextQuality,
    QualityConflict,
    QualityGap,
    QualitySupport,
)
from leka.intentions import Understanding, readiness, refined
from leka.intentions.schemas import GoalRead, IntentScope, ScopedEntity


def _construct[M: BaseModel](model: type[M], **fields: Any) -> M:
    """A part of an assembled context, with only what the judgement reads."""
    return model.model_construct(**fields)


CHECKOUT = uuid.uuid5(uuid.NAMESPACE_URL, "checkout")
CONTEXT = uuid.uuid5(uuid.NAMESPACE_URL, "context")


def understanding(*, excluded: bool = False, only: str | None = None) -> Understanding:
    scope = IntentScope(
        entities=[],
        excluded=[
            ScopedEntity(
                entity_id=CHECKOUT,
                name="Checkout",
                type="service",
                how="named",
                said="checkout",
                confidence=1.0,
                lifecycle="active",
            )
        ]
        if excluded
        else [],
        environments=[only] if only else [],
        environment_origin="constraint" if only else None,
        period=None,
        sources=[],
        constraints=[],
        missing=[],
    )
    return Understanding(
        version=2,
        text="…",
        mode="question",
        mode_said="?",
        kind="dependency",
        goal=GoalRead(code="map_dependencies", said=["depend"], confidence=0.6),
        actions=[],
        entities=[],
        period=None,
        environment=None,
        ambiguities=[],
        clear=True,
        scope=scope,
    )


def test_the_ask_is_the_one_its_scope_settled() -> None:
    ask = IntentAsk(text="Qu'est-ce qui dépend de Billing API, sauf Checkout ?")
    assert refined(ask, understanding(excluded=True)).exclude == [CHECKOUT]
    held = refined(
        IntentAsk(text="Redémarre-le uniquement en staging"), understanding(only="staging")
    )
    assert held.environment == "staging"
    # Asked by the form: the form's word stands.
    asked = IntentAsk(text="Redémarre-le", environment="production")
    assert refined(asked, understanding(only="staging")).environment == "production"
    # Nothing settled: the very same ask.
    assert refined(ask, understanding()) is ask
    assert refined(ask, None) is ask


def element(ref_type: str) -> ContextElementRead:
    return _construct(ContextElementRead, kind="entity", ref_type=ref_type, ref_id=uuid.uuid4())


def context(
    *,
    elements: list[ContextElementRead] | None = None,
    gaps: list[QualityGap] | None = None,
    conflicts: list[QualityConflict] | None = None,
    level: str = "high",
) -> AssembledContext:
    quality = _construct(
        ContextQuality,
        score=0.9 if level == "high" else 0.5,
        level=level,
        gaps=gaps or [],
        conflicts=conflicts or [],
        support=_construct(QualitySupport, sources=2),
    )
    return _construct(
        AssembledContext,
        context_id=CONTEXT,
        version=3,
        elements=elements
        if elements is not None
        else [element("service"), element("team"), element("application"), element("deployment")],
        quality=quality,
    )


def gap(kind: str, severity: str) -> QualityGap:
    return _construct(
        QualityGap, kind=kind, severity=severity, said=kind, refs=[], origin="quality", detail={}
    )


def test_nothing_in_the_way_is_ready_with_what_it_holds_by_side() -> None:
    ready = readiness(context())
    assert ready.status == "ready"
    assert (ready.context_id, ready.version, ready.level, ready.sources) == (CONTEXT, 3, "high", 2)
    assert ready.facets == {"technical": 1, "business": 1, "organizational": 1, "temporal": 1}
    assert ready.elements == 4


def test_a_critical_gap_or_conflict_blocks() -> None:
    blocked = readiness(
        context(gaps=[gap("model_not_built", "critical"), gap("unwatched", "info")])
    )
    assert blocked.status == "blocked"
    assert [(i.origin, i.kind, i.gap_origin) for i in blocked.critical] == [
        ("gap", "model_not_built", "quality")
    ]
    conflict = _construct(
        QualityConflict,
        kind="competing",
        severity="critical",
        said="two owners",
        refs=[CHECKOUT],
        label="Checkout",
        about="owner",
    )
    owners = readiness(context(conflicts=[conflict]))
    assert owners.status == "blocked"
    assert [(i.origin, i.kind, i.refs, i.label, i.about) for i in owners.critical] == [
        ("conflict", "competing", [CHECKOUT], "Checkout", "owner")
    ]


def test_a_context_holding_nothing_blocks() -> None:
    assert readiness(context(elements=[])).status == "blocked"


def test_warnings_or_a_low_level_limit() -> None:
    warned = readiness(context(gaps=[gap("stale_evidence", "warning")]))
    assert warned.status == "limited"
    assert [i.kind for i in warned.warnings] == ["stale_evidence"]
    assert readiness(context(level="low")).status == "limited"
