"""An intention's context (LEKA-387): assembled from its structured scope,
and judged ready — or not — to ground its analysis.

    refined()    the ask the context engine reads, as the scope settled it:
                 what it excludes is never held (« sauf … » — leka.context
                 leaves it out, `excluded`); where it is held to by its
                 words (« uniquement en staging ») is where it looks
    readiness()  whether the context can ground an analysis — read from the
                 context's own quality (LEKA-375), gaps and conflicts
                 (LEKA-372), never judged again:
                     blocked  an action asked, and a critical gap or
                              conflict — nothing named, two owners of what
                              it acts on — to resolve before anything is
                              proposed
                     limited  a question, and something critical in the
                              way — said, and answered anyway: LEKA's
                              analyst looks for itself, and says what its
                              sources disagree on; or warnings
                     ready    nothing in the way
                 with what it holds by side — technical, business,
                 organizational, temporal — and how many sources say it

Pure. The service keeps the readiness with the intention, says it in the
move to `analysing`, and gives downstream capabilities the context itself
(IntentionService.context, GET /intentions/{id}/context).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from leka.context import AssembledContext, IntentAsk, facet_of
from leka.intentions.schemas import ContextReadiness, ReadinessIssue, Understanding

# What happened, rather than what is: the temporal side of a context.
EVENTS = frozenset(
    {"incident", "deployment", "change", "release", "pull_request", "commit", "alert"}
)


def refined(ask: IntentAsk, understanding: Understanding | None) -> IntentAsk:
    """The ask, as its scope settled it (LEKA-386)."""
    scope = understanding.scope if understanding is not None else None
    if scope is None:
        return ask
    update: dict[str, object] = {}
    if scope.excluded:
        update["exclude"] = list(
            dict.fromkeys([*ask.exclude, *(thing.entity_id for thing in scope.excluded)])
        )
    if scope.environment_origin == "constraint" and scope.environments and not ask.environment:
        update["environment"] = scope.environments[0]
    return ask.model_copy(update=update) if update else ask


def side(entity_type: str) -> str:
    return "temporal" if entity_type in EVENTS else facet_of(entity_type)


# What an action must rest on (LEKA-436): the capabilities whose evidence it
# needs before it may be proposed as grounded — what it is on and what it
# reaches, always; past medium risk, what changed on it last and who owns it
# too. A context gone stale is evidence missing.
ACTION_EVIDENCE = ("standing", "action")
RISKY_EVIDENCE = ("standing", "action", "changes", "ownership")
RISKY = frozenset({"high", "critical"})
STALE = frozenset({"model_stale", "stale_evidence"})


@dataclass(frozen=True)
class Grounding:
    """Whether what an action rests on held: the capabilities it needs that
    did not succeed, what in its context is stale — and so its gate:
    `blocked` (high or critical risk: not approvable until analysed again),
    `validation` (one more approval, the reason said), none."""

    missing: tuple[str, ...]
    stale: tuple[str, ...]
    risky: bool

    @property
    def gate(self) -> str | None:
        if not self.missing and not self.stale:
            return None
        return "blocked" if self.risky else "validation"

    def as_dict(self) -> dict[str, object]:
        return {"gate": self.gate, "missing": list(self.missing), "stale": list(self.stale)}


def action_grounding(
    steps: Mapping[str, str], readiness: ContextReadiness | None, *, risk: str
) -> Grounding:
    """`steps`: each capability run, by name, and how it ended."""
    risky = risk in RISKY
    needed = RISKY_EVIDENCE if risky else ACTION_EVIDENCE
    issues = [*readiness.critical, *readiness.warnings] if readiness is not None else []
    return Grounding(
        missing=tuple(name for name in needed if steps.get(name) != "succeeded"),
        stale=tuple(dict.fromkeys(i.kind for i in issues if i.kind in STALE)),
        risky=risky,
    )


def acting(understood: Understanding | None) -> bool:
    """Whether it asks to change systems — what a person must decide on."""
    if understood is None:
        return False
    return understood.goal.code == "act" or any(a.changes_systems for a in understood.actions)


def readiness(context: AssembledContext, *, acts: bool = False) -> ContextReadiness:
    """Whether this context can ground an analysis, and why not. Only an
    action is blocked: a question is answered with what is in the way said."""
    quality = context.quality
    issues: list[ReadinessIssue] = []
    if quality is not None:
        issues += [
            ReadinessIssue(
                origin="gap",
                kind=gap.kind,
                severity=gap.severity,
                said=gap.said,
                refs=gap.refs,
                gap_origin=gap.origin,
                detail=dict(gap.detail),
            )
            for gap in quality.gaps
        ]
        issues += [
            ReadinessIssue(
                origin="conflict",
                kind=conflict.kind,
                severity=conflict.severity,
                said=conflict.said,
                refs=conflict.refs,
                label=conflict.label,
                about=conflict.about,
            )
            for conflict in quality.conflicts
        ]
    critical = [issue for issue in issues if issue.severity == "critical"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    held = [e for e in context.elements if e.kind == "entity"]
    facets = Counter(side(e.ref_type) for e in held)
    if (critical or not held) and acts:
        status = "blocked"
    elif critical or not held or warnings or (quality is not None and quality.level == "low"):
        status = "limited"
    else:
        status = "ready"
    return ContextReadiness(
        status=status,
        context_id=context.context_id,
        version=context.version,
        level=quality.level if quality is not None else "low",
        score=quality.score if quality is not None else None,
        elements=len(context.elements),
        facets={
            name: facets.get(name, 0)
            for name in ("technical", "business", "organizational", "temporal")
        },
        sources=quality.support.sources if quality is not None else 0,
        critical=critical,
        warnings=warnings,
    )
