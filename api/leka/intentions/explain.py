"""On what an analysis rests (LEKA-441): what LEKA understood, what it
really read and in what state, what did not answer and what that leaves
unknown, how sure it is and why, the figures a screen may say with what
they count, what disagrees, what is stale, its limits — and what to do next.

    the result (analysis.assemble, recommend)
    what ran (each capability's outcome)
    the context it read — its sources, its conflicts, its version
    each source's state when it read (connectors)
        ▼
    explain()   one AnalysisExplanation, kept with the result — and the
                result's status and confidence held to it: never « complete »
                while a source it read from was still syncing or failing,
                never surer than what it rests on

How sure, by defined criteria — never a decorative figure:

    what it rests on          a cause its source states       high
                              a cause LEKA infers, probable   medium
                              only a correlation in time      low
                              findings, two sources or more   high
                              findings, one source            medium
                              nothing found                   low
                              it could not run                unknown
    what caps it              a capability that did not answer, a context
                              limited, a conflict, a source failing, syncing
                              or stale                         medium at most
                              a name LEKA does not know        low at most

The figures (claims), each counted from the result, each with what it was
counted from — a figure nothing counts is not said: no « utilisateurs
impactés » unless a source states how many.

Pure: tested in a millisecond on the ticket's scenarios
(tests/test_intention_explain.py); docs/intentions.md § 12 ter.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from leka.intentions.analysis import Asked, Note, Result, StepOutcome, strength_of
from leka.intentions.schemas import (
    AnalysisClaim,
    AnalysisExplanation,
    AnalysisNextStep,
    AnalysisNote,
    ConfidenceReason,
    ExplainedCapability,
    ExplainedConfidence,
    ExplainedConflict,
    ExplainedSource,
    Understanding,
)
from leka.knowledge import fold

# A source not synced for this long: what it says may be out of date.
STALE_DAYS = 7
LEVELS = ("unknown", "low", "medium", "high")
# What a confidence in words allows of the figure kept beside it: a level
# and a figure never disagree.
CEILING = {"unknown": None, "low": 0.59, "medium": 0.84, "high": 1.0}
# Where a cause comes from (analysis.strength_of) → how sure it makes it.
FROM_CAUSE = {"confirmed": "high", "probable": "medium", "correlated": "low"}
# What a capability that did not answer leaves unknown.
LEAVES = {
    "standing": "Its state, and how well LEKA knows it, are not known.",
    "ownership": "Who owns it is not known.",
    "dependencies": "What it depends on, and what depends on it, are not known.",
    "incidents": "Its incidents in the period are not known.",
    "changes": "What changed in the period is not known: a cause may be missing.",
    "evolution": "What LEKA learned in the period is not known.",
    "documentation": "Whether it is documented, and how recently, is not known.",
    "compliance": "Whether it meets the rules is not known.",
    "migration": "Where it moves to, and what that reaches, are not known.",
    "action": "What the action reaches, and what limits it, are not known.",
    "synthesis": "No answer was written: the findings are shown as they are.",
}
# What its incidents' sources may call the people reached.
USERS = ("impacted_users", "users_impacted", "affected_users", "users_affected")


@dataclass(frozen=True)
class SourceState:
    """A source, as the connectors hold it when the analysis reads."""

    status: str  # draft, tested, active, degraded, error, disabled
    sync_status: str  # never, idle, running, failed
    health: str  # unknown, healthy, degraded, unhealthy
    last_synced_at: datetime | None


@dataclass(frozen=True)
class ContextRead:
    """What the analysis read of its context: its version, its sources and
    how much each brought, what they disagree on."""

    version: int | None
    sources: Sequence[tuple[uuid.UUID, str | None, str | None, int]]  # id, kind, name, elements
    conflicts: Sequence[Mapping[str, object]]  # id, kind, subject, label, about, values, said


def _note(code: str, text: str, **params: object) -> AnalysisNote:
    return AnalysisNote(code=code, text=text, params=_json(params))


def _json(value: object) -> dict[str, object]:
    def one(v: object) -> object:
        if isinstance(v, Mapping):
            return {str(k): one(x) for k, x in v.items()}
        if isinstance(v, list | tuple | set | frozenset):
            return [one(x) for x in v]
        if v is None or isinstance(v, str | int | float | bool):
            return v
        return str(v)

    out = one(value)
    return out if isinstance(out, dict) else {}


# ── what it understood ───────────────────────────────────────────────────────


def understood_of(asked: Asked, understanding: Understanding | None) -> AnalysisNote:
    """What LEKA understood it asks, from what the analysis read."""
    names = [s.name for s in asked.subjects]
    scope = understanding.scope if understanding is not None else None
    excluded = [e.name for e in scope.excluded] if scope is not None else []
    period = scope.period if scope is not None else None
    restated = understanding.restated if understanding is not None else None
    about = names or [f"{n} (unknown to LEKA)" for n in asked.unknown]
    text = f"{asked.goal.replace('_', ' ')}" + (f" about {', '.join(about)}" if about else "")
    if asked.environment:
        text += f", in {asked.environment}"
    if excluded:
        text += f", except {', '.join(excluded)}"
    return _note(
        "explanation.understood",
        (restated or text[:1].upper() + text[1:]) + ".",
        goal=asked.goal,
        mode=asked.mode,
        names=names,
        unknown=list(asked.unknown),
        environment=asked.environment,
        excluded=excluded,
        since=asked.since.isoformat() if asked.since else None,
        until=asked.until.isoformat() if asked.until else None,
        period_said=bool(period and period.explicit),
        actions=[code for code, _ in asked.actions],
        restated=restated,
    )


# ── what it read ─────────────────────────────────────────────────────────────


def _state(seen: SourceState | None, now: datetime) -> str:
    if seen is None:
        return "gone"
    if seen.status == "disabled":
        return "disabled"
    if seen.status == "error" or seen.sync_status == "failed" or seen.health == "unhealthy":
        return "error"
    if seen.sync_status == "running":
        return "syncing"
    if seen.status == "degraded" or seen.health == "degraded":
        return "degraded"
    if seen.last_synced_at is None or now - seen.last_synced_at > timedelta(days=STALE_DAYS):
        return "stale"
    return "read"


SAID = {
    "read": "Read: synced {ago}.",
    "error": "Failing: what it said is as of its last sync{since}.",
    "degraded": "Degraded: what it said may be incomplete{since}.",
    "stale": "Not synced for {ago}: what it said may be out of date.",
    "syncing": "Still syncing when LEKA read: what it is bringing was not read.",
    "disabled": "Turned off: what it said is as of its last sync{since}.",
    "gone": "Deleted since: what it said stays, its source no longer there.",
}


def _ago(at: datetime | None, now: datetime) -> str:
    if at is None:
        return "never"
    hours = max(0, round((now - at).total_seconds() / 3600))
    return f"{hours} hour(s) ago" if hours < 48 else f"{hours // 24} day(s)"


def consulted_of(
    context: ContextRead | None, states: Mapping[uuid.UUID, SourceState], now: datetime
) -> list[ExplainedSource]:
    out: list[ExplainedSource] = []
    for source_id, kind, name, elements in context.sources if context is not None else ():
        seen = states.get(source_id)
        state = _state(seen, now)
        synced = seen.last_synced_at if seen is not None else None
        out.append(
            ExplainedSource(
                source_id=source_id,
                kind=kind,
                name=name,
                elements=elements,
                state=state,
                last_synced_at=synced,
                said=SAID[state].format(
                    ago=_ago(synced, now),
                    since=f", {_ago(synced, now)}" if synced is not None else "",
                ),
            )
        )
    return out


def capabilities_of(
    outcomes: Sequence[StepOutcome], background: Collection[str]
) -> list[ExplainedCapability]:
    out: list[ExplainedCapability] = []
    for outcome in outcomes:
        if outcome.status == "skipped" and outcome.reason in ("not_called", "disabled"):
            continue
        answered = outcome.status == "succeeded"
        out.append(
            ExplainedCapability(
                name=outcome.name,
                status=outcome.status,
                reason=outcome.error or outcome.reason,
                leaves=None
                if answered
                else _note(
                    f"limit.capability.{outcome.name}",
                    LEAVES.get(outcome.name, f"What {outcome.name} reads is not known."),
                    capability=outcome.name,
                    status=outcome.status,
                    background=outcome.name in background,
                ),
            )
        )
    return out


# ── what it may say, counted ─────────────────────────────────────────────────


def _cited(result: Result) -> list[str]:
    """The evidence its findings, its causes and its answer cite, in order,
    once — an answer resting on files a model read rests on their sources
    (2026-10-14: « 0 source à l'appui » with GitHub read)."""
    ids = [e for _, s in result.findings for e in s.evidence]
    ids += [e for _, c in result.causes for e in c.evidence]
    if result.answer is not None:
        ids += [e for p in result.answer.points for e in p.cites]
    return list(dict.fromkeys(ids))


def claims_of(result: Result, conflicts: Sequence[ExplainedConflict]) -> list[AnalysisClaim]:
    evidence = {e.id: e for e in result.evidence}
    sources: dict[str, None] = {}
    for item in _cited(result):
        for source in evidence[item].sources if item in evidence else ():
            if source.id is not None:
                sources.setdefault(str(source.id))
    correlated = list(
        dict.fromkeys(
            str(c.ref_id)
            for _, c in result.causes
            if c.ref_id is not None and strength_of(c) != "confirmed"
        )
    )
    claims = [
        AnalysisClaim(
            code="sources",
            count=len(sources),
            holds=bool(sources),
            definition="Distinct sources the evidence of its findings, causes and answer was "
            "read from.",
            refs=list(sources),
        ),
        AnalysisClaim(
            code="correlated_events",
            count=len(correlated),
            holds=bool(correlated),
            definition="Changes tied to an incident by time alone or by LEKA's inference — "
            "none of them confirmed by a source as its cause.",
            refs=correlated,
        ),
        AnalysisClaim(
            code="contradictions",
            count=len(conflicts),
            holds=not conflicts,
            definition="What the sources of its context disagree on.",
            refs=[c.id for c in conflicts],
        ),
    ]
    stated = [
        (s.id, s.params[key])
        for _, s in result.findings
        for key in USERS
        if isinstance(s.params.get(key), int)
    ]
    if stated:
        claims.append(
            AnalysisClaim(
                code="impacted_users",
                count=max(int(n) for _, n in stated),  # type: ignore[call-overload]
                holds=True,
                definition="The people reached, as a source states them — never estimated.",
                refs=[i for i, _ in stated],
            )
        )
    return claims


def conflicts_of(context: ContextRead | None, asked: Asked) -> list[ExplainedConflict]:
    """What its sources disagree on about what it asks — what they disagree
    on about anything else in its context does not weigh on it."""
    about = {str(s.id) for s in asked.subjects}
    out: list[ExplainedConflict] = []
    for conflict in context.conflicts if context is not None else ():
        if about and str(conflict.get("subject")) not in about:
            continue
        values = conflict.get("values")
        out.append(
            ExplainedConflict(
                id=str(conflict.get("id")),
                label=str(conflict.get("label") or ""),
                about=str(conflict.get("about") or ""),
                values=[
                    {"value": str(v.get("value")), "by": list(v.get("by") or [])}
                    for v in values
                    if isinstance(v, Mapping)
                ]
                if isinstance(values, list)
                else [],
                said=str(conflict.get("said") or ""),
            )
        )
    return out


# ── how sure ─────────────────────────────────────────────────────────────────


def _at_most(level: str, cap: str) -> str:
    return level if LEVELS.index(level) <= LEVELS.index(cap) else cap


def confidence_of(
    result: Result,
    asked: Asked,
    *,
    readiness: str,
    consulted: Sequence[ExplainedSource],
    capabilities: Sequence[ExplainedCapability],
    conflicts: Sequence[ExplainedConflict],
    sources: int,
) -> ExplainedConfidence:
    reasons: list[ConfidenceReason] = []

    def say(code: str, effect: str, text: str, **params: object) -> None:
        reasons.append(ConfidenceReason(code=code, effect=effect, text=text, params=_json(params)))

    strengths = [strength_of(c) for _, c in result.causes]
    if result.status == "failed":
        say("confidence.failed", "base", "It could not run: nothing to be sure of.")
        return ExplainedConfidence(level="unknown", reasons=reasons)
    if asked.unknown and not asked.subjects:
        say(
            "confidence.unknown_subject",
            "base",
            f"LEKA knows nothing called {', '.join(asked.unknown)}: what it read is around it.",
            names=list(asked.unknown),
        )
        level = "low"
    elif strengths:
        top = max(strengths, key=lambda s: LEVELS.index(FROM_CAUSE[s]))
        level = FROM_CAUSE[top]
        say(
            f"confidence.cause_{top}",
            "base",
            {
                "confirmed": "Its likeliest cause is stated by a source.",
                "probable": "Its likeliest cause is inferred by LEKA, not stated by a source.",
                "correlated": "Only time ties its likeliest cause to what happened.",
            }[top],
            strength=top,
        )
    elif result.findings and result.status != "inconclusive":
        level = "high" if sources >= 2 else "medium"
        say(
            "confidence.sources_agree" if sources >= 2 else "confidence.one_source",
            "base",
            f"What it found is read from {sources} source(s)."
            if sources >= 2
            else "What it found rests on a single source.",
            count=sources,
        )
    else:
        level = "low"
        say("confidence.nothing_found", "base", "It found nothing that answers the question.")
    failed = [c for c in capabilities if c.status != "succeeded" and c.name != "synthesis"]
    if failed:
        level = _at_most(level, "medium")
        say(
            "confidence.capability_failed",
            "caps",
            f"{', '.join(c.name for c in failed)} did not answer.",
            capabilities=[c.name for c in failed],
        )
    if readiness == "limited":
        level = _at_most(level, "medium")
        say("confidence.context_limited", "caps", "Its context lacks something it needs.")
    if conflicts:
        level = _at_most(level, "medium")
        say(
            "confidence.conflicts",
            "caps",
            f"Its sources disagree on {len(conflicts)} thing(s).",
            count=len(conflicts),
            about=[c.label for c in conflicts][:3],
        )
    unsure = [s for s in consulted if s.state != "read"]
    if unsure:
        level = _at_most(level, "medium")
        say(
            "confidence.sources_unsure",
            "caps",
            f"{len(unsure)} source(s) it read from are failing, syncing or out of date.",
            sources=[s.name or str(s.source_id) for s in unsure],
            states=sorted({s.state for s in unsure}),
        )
    return ExplainedConfidence(level=level, reasons=reasons)


# ── what to do next ──────────────────────────────────────────────────────────


def next_of(
    result: Result,
    asked: Asked,
    *,
    consulted: Sequence[ExplainedSource],
    capabilities: Sequence[ExplainedCapability],
    conflicts: Sequence[ExplainedConflict],
) -> AnalysisNextStep:
    def step(code: str, text: str, why: AnalysisNote, **params: object) -> AnalysisNextStep:
        return AnalysisNextStep(code=code, text=text, why=why, params=_json(params))

    failing = [s for s in consulted if s.state in ("error", "syncing")]
    if result.status == "failed":
        if failing:
            names = [s.name or str(s.source_id) for s in failing]
            return step(
                "fix_source",
                f"Repair {', '.join(names)}, then analyse again.",
                _note(
                    "why.failed_sources", "It could not run, and those sources fail.", sources=names
                ),
                sources=names,
            )
        return step(
            "rerun",
            "Analyse again.",
            _note("why.failed", "No capability answered."),
        )
    syncing = [s for s in consulted if s.state == "syncing"]
    if syncing:
        names = [s.name or str(s.source_id) for s in syncing]
        return step(
            "rerun",
            f"Analyse again once {', '.join(names)} has synced.",
            _note(
                "why.syncing",
                "It finished before those sources did: what they bring was not read.",
                sources=names,
            ),
            sources=names,
        )
    if asked.unknown and not asked.subjects:
        names = list(asked.unknown)
        return step(
            "ask_differently",
            "Name it as LEKA knows it, or connect the source that knows it.",
            _note(
                "why.unknown_subject",
                f"LEKA knows nothing called {', '.join(names)}.",
                names=names,
            ),
            names=names,
        )
    words = fold(asked.text)
    asked_about = next((c for c in conflicts if c.about and fold(c.about) in words.split()), None)
    if asked_about is not None:
        # « Quel est le SLA ? », its sources disagreeing on it: settled first.
        return step(
            "settle_conflict",
            f"Settle what its sources disagree on: {asked_about.label}'s {asked_about.about}.",
            _note("why.conflict_asked", asked_about.said, conflict=asked_about.id),
            conflict=asked_about.id,
        )
    first = result.recommendations[0] if result.recommendations else None
    if first is not None:
        why = _note(
            "why.recommendation",
            first.why.text,
            recommendation=first.code,
            basis=list(first.basis),
        )
        if first.changes_systems and not first.executable:
            unmet = [p for p in first.preconditions if p.blocking and not p.met]
            return step(
                "prepare",
                f"Before deciding, settle what {first.code} needs.",
                _note(
                    "why.preconditions",
                    "It cannot be carried out as it stands: " + "; ".join(p.text for p in unmet),
                    preconditions=[p.code for p in unmet],
                    recommendation=first.code,
                ),
                recommendation=first.id,
                preconditions=[p.code for p in unmet],
            )
        if first.changes_systems:
            return step(
                "decide", "Decide on it: approve, change or refuse.", why, recommendation=first.id
            )
        if first.code == "recommend.confirm_cause":
            return step("confirm_cause", first.text, why, recommendation=first.id)
        if first.code == "recommend.ask_differently":
            return step("ask_differently", first.text, why, recommendation=first.id)
        return step("act", first.text, why, recommendation=first.id)
    if conflicts:
        return step(
            "settle_conflict",
            f"Settle what its sources disagree on: {conflicts[0].label}.",
            _note("why.conflict", conflicts[0].said, conflict=conflicts[0].id),
            conflict=conflicts[0].id,
        )
    silent = [c for c in capabilities if c.status != "succeeded" and c.name != "synthesis"]
    if silent:
        names = [c.name for c in silent]
        return step(
            "rerun",
            "Analyse again: what did not answer may change the answer.",
            _note("why.partial", f"{', '.join(names)} did not answer.", capabilities=names),
            capabilities=names,
        )
    if result.status == "inconclusive":
        return step(
            "ask_differently",
            "Ask differently: name what it is about, or the period.",
            _note("why.inconclusive", "It found nothing that answers the question."),
        )
    return step(
        "nothing", "Nothing to do: it is answered.", _note("why.answered", "It is answered.")
    )


# ── the whole ────────────────────────────────────────────────────────────────


def explain(
    result: Result,
    asked: Asked,
    understanding: Understanding | None,
    outcomes: Sequence[StepOutcome],
    *,
    context: ContextRead | None,
    states: Mapping[uuid.UUID, SourceState],
    readiness: str,
    now: datetime,
    background: Collection[str] = (),
    unread: Sequence[str] = (),
) -> tuple[Result, AnalysisExplanation]:
    """The explanation — and the result held to it: partial while a source
    it read from was failing or syncing, its confidence never above its
    level's."""
    consulted = consulted_of(context, states, now)
    capabilities = capabilities_of(outcomes, background)
    conflicts = conflicts_of(context, asked)
    claims = claims_of(result, conflicts)
    sources = next((c.count for c in claims if c.code == "sources"), 0)
    confidence = confidence_of(
        result,
        asked,
        readiness=readiness,
        consulted=consulted,
        capabilities=capabilities,
        conflicts=conflicts,
        sources=sources,
    )
    limits: list[AnalysisNote] = [c.leaves for c in capabilities if c.leaves is not None]
    pending = [s for s in consulted if s.state in ("error", "syncing", "degraded")]
    for source in pending:
        limits.append(
            _note(
                f"limit.source_{source.state}",
                f"{source.name or source.source_id}: {source.said}",
                source=source.name,
                state=source.state,
            )
        )
    for name in unread:
        limits.append(
            _note(
                "limit.source_unread",
                f"{name}: connected, not read yet — the answer may be incomplete.",
                source=name,
            )
        )
    if readiness == "limited":
        limits.append(
            _note("limit.context_limited", "Its context lacks something it needs: said below.")
        )
    stale = [
        _note(
            "stale.source",
            f"{s.name or s.source_id}: {s.said}",
            source=s.name,
            state=s.state,
            last_synced_at=s.last_synced_at.isoformat() if s.last_synced_at else None,
        )
        for s in consulted
        if s.state in ("stale", "error", "degraded", "disabled", "gone")
    ]
    stale += [
        AnalysisNote(code=n.code, text=n.text, params=_json(dict(n.params)))
        for n in result.uncertainties
        if n.code.endswith(".stale") or n.code == "standing.inactive"
    ]
    held = result
    if result.status == "complete" and pending:
        names = [s.name or str(s.source_id) for s in pending]
        held = replace(
            result,
            status="partial",
            missing=(
                *result.missing,
                Note(
                    "analysis.sources_pending",
                    f"Not every source answered: {', '.join(names)}.",
                    {"sources": names},
                ),
            ),
        )
    ceiling = CEILING[confidence.level]
    held = replace(
        held,
        confidence=None
        if ceiling is None or held.confidence is None
        else round(min(held.confidence, ceiling), 3),
    )
    explanation = AnalysisExplanation(
        understood=understood_of(asked, understanding),
        consulted=consulted,
        capabilities=capabilities,
        confidence=confidence,
        claims=claims,
        conflicts=conflicts,
        stale=stale,
        limits=limits,
        next=next_of(
            held, asked, consulted=consulted, capabilities=capabilities, conflicts=conflicts
        ),
        context_version=context.version if context is not None else None,
    )
    return held, explanation
