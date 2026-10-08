"""What LEKA recommends (LEKA-389): from what an analysis found, what to do
next — proposed, never stated as a fact, and never done by LEKA.

    the result of an analysis (analysis.assemble, LEKA-388)
        │  findings — facts, each with its evidence
        │  causes   — hypotheses, stated or inferred, how sure
        │  impact, risk, uncertainties, what is missing
        ▼
    recommend()   one proposal per thing to do, each saying:
                    what to do (a code and its values, and in English)
                    why — the findings and causes it follows from, their
                    evidence: a proposal is traceable to what shows it
                    the action's kind — undo a change, change something,
                    watch, other — and whether it changes a customer's
                    systems (then only once a person approves, LEKA-390)
                    how risky, whether it can be undone, how urgent, how
                    sure — never surer than what it follows from

A change that came before an incident — said to have caused it, or only
suspected — is proposed undone; one only suspected is first proposed
confirmed. An incident nothing explains is proposed investigated. What
nobody owns, proposed given an owner; several owners, settled; what no
document describes, or none current, documented. A thing known poorly,
better known (its sources connected). A check a compliance question failed,
its own remedy. What it reaches, its people told. An analysis that could
not conclude, with nothing else to propose, proposes asking differently —
never a guess.

Rules over the result, pure: tested in a millisecond
(tests/test_intention_recommend.py). The interface words every proposal
from its code, and shows it apart from the findings — a recommendation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from leka.intentions.analysis import (
    Asked,
    Cause,
    ImpactItem,
    Note,
    Recommendation,
    Result,
    Statement,
    Subject,
)

# What changed and can be undone: a cause of these kinds is proposed undone.
UNDOABLE = frozenset({"deployment", "change", "release", "pull_request", "commit"})
# A cause this sure, or a source's word, is acted on; below, confirmed first
# — LEKA-388 calls an inference at 0.7 « probable, to confirm ».
SURE = 0.8
PRIORITIES = {"high": 0, "medium": 1, "low": 2}
# What a compliance check that failed proposes.
CHECKS = {
    "owner": "recommend.assign_owner",
    "documented": "recommend.update_documentation",
    "criticality": "recommend.set_criticality",
    "nothing_serious": "recommend.resolve_findings",
    "known_well": "recommend.improve_knowledge",
}


def _target(subjects: Sequence[Subject], name: object) -> ImpactItem | None:
    for subject in subjects:
        if subject.name == name:
            return ImpactItem(subject.type, subject.id, subject.name)
    return None


def _cause_target(cause: Cause) -> ImpactItem | None:
    if cause.ref_id is None or cause.ref_type is None:
        return None
    return ImpactItem(cause.ref_type, cause.ref_id, cause.label)


def _lower(confidence: float | None, *, by: float = 1.0) -> float | None:
    return None if confidence is None else round(min(confidence, 1.0) * by, 3)


class _Proposals:
    """Proposals gathered once each, in the order found."""

    def __init__(self) -> None:
        self._found: dict[str, Recommendation] = {}

    def add(self, recommendation: Recommendation) -> None:
        self._found.setdefault(recommendation.id, recommendation)

    @property
    def empty(self) -> bool:
        return not self._found

    def sorted(self) -> tuple[Recommendation, ...]:
        return tuple(
            sorted(
                self._found.values(),
                key=lambda r: (PRIORITIES[r.priority], -(r.confidence or 0.0)),
            )
        )


def _for_causes(result: Result, out: _Proposals) -> None:
    acted_on = any(area.items for area in result.impact)
    for capability, cause in result.causes:
        _ = capability
        target = _cause_target(cause)
        stated = cause.basis == "stated"
        sure = stated or (cause.confidence or 0.0) >= SURE
        if cause.ref_type in UNDOABLE:
            out.add(
                Recommendation(
                    id=f"rollback:{cause.ref_id}",
                    code="recommend.rollback",
                    text=f"Undo {cause.label}: it is "
                    + ("said to have caused" if stated else "suspected to have caused")
                    + f" {cause.params.get('incident', 'the incident')}.",
                    action="rollback",
                    changes_systems=True,
                    priority="high" if sure else "medium",
                    risk=result.risk if acted_on else "medium",
                    reversible=True,
                    confidence=_lower(cause.confidence, by=1.0 if sure else 0.8),
                    why=Note(
                        "recommend.why.cause",
                        cause.why,
                        {"cause": cause.label, "basis": cause.basis, **dict(cause.params)},
                    ),
                    params={"change": cause.label, "incident": cause.params.get("incident")},
                    basis=(cause.id,),
                    evidence=cause.evidence,
                    target=target,
                )
            )
        if not sure:
            out.add(
                Recommendation(
                    id=f"confirm:{cause.id}",
                    code="recommend.confirm_cause",
                    text=f"Confirm that {cause.label} caused "
                    f"{cause.params.get('incident', 'it')} before acting on it.",
                    action="monitor",
                    changes_systems=False,
                    priority="high",
                    risk="low",
                    reversible=None,
                    confidence=_lower(cause.confidence),
                    why=Note(
                        "recommend.why.suspected",
                        f"It is only suspected ({cause.confidence or 0:.2f}).",
                        {"cause": cause.label, "confidence": cause.confidence},
                    ),
                    params={"cause": cause.label, "incident": cause.params.get("incident")},
                    basis=(cause.id,),
                    evidence=cause.evidence,
                    target=target,
                )
            )


def _for_findings(
    findings: Iterable[tuple[str, Statement]], subjects: Sequence[Subject], out: _Proposals
) -> None:
    for _, finding in findings:
        name = finding.params.get("name")
        target = _target(subjects, name)
        key = target.ref_id if target is not None else name
        if finding.code == "compliance.check" and finding.params.get("passed") is False:
            check = str(finding.params.get("check"))
            code = CHECKS.get(check)
            if code is None:
                continue
            out.add(
                Recommendation(
                    id=f"{code.split('.', 1)[1]}:{key}",
                    code=code,
                    text=f"{name}: {check.replace('_', ' ')} — to be made so.",
                    action="change",
                    changes_systems=False,
                    priority="high" if check == "nothing_serious" else "medium",
                    risk="low",
                    reversible=True,
                    confidence=None,
                    why=Note(
                        "recommend.why.finding",
                        finding.text,
                        {**dict(finding.params), "of": finding.code},
                    ),
                    params={"name": name, "check": check},
                    basis=(finding.id,),
                    evidence=finding.evidence,
                    target=target,
                )
            )


def _for_notes(
    notes: Iterable[Note],
    findings: Sequence[tuple[str, Statement]],
    subjects: Sequence[Subject],
    out: _Proposals,
) -> None:
    for note in notes:
        name = note.params.get("name")
        target = _target(subjects, name)
        key = target.ref_id if target is not None else name
        if note.code == "ownership.several":
            # The owners said, each a finding with its evidence.
            said = [
                f
                for _, f in findings
                if f.code == "ownership.owner" and f.params.get("name") == name
            ]
            out.add(
                Recommendation(
                    id=f"settle_owner:{key}",
                    code="recommend.settle_owner",
                    text=f"Settle who owns {name}: its sources name several owners.",
                    action="change",
                    changes_systems=False,
                    priority="medium",
                    risk="low",
                    reversible=True,
                    confidence=None,
                    why=Note(
                        "recommend.why.uncertain",
                        note.text,
                        {**dict(note.params), "of": note.code},
                    ),
                    params={"name": name, "owners": note.params.get("owners")},
                    basis=tuple(f.id for f in said),
                    evidence=tuple(e for f in said for e in f.evidence),
                    target=target,
                )
            )
        elif note.code == "ownership.unknown":
            out.add(
                Recommendation(
                    id=f"assign_owner:{key}",
                    code="recommend.assign_owner",
                    text=f"Name an owner for {name}: no source names one.",
                    action="change",
                    changes_systems=False,
                    priority="medium",
                    risk="low",
                    reversible=True,
                    confidence=None,
                    why=Note(
                        "recommend.why.uncertain",
                        note.text,
                        {**dict(note.params), "of": note.code},
                    ),
                    params={"name": name},
                    target=target,
                )
            )
        elif note.code in ("documentation.none", "documentation.stale"):
            fresh = note.code == "documentation.none"
            out.add(
                Recommendation(
                    id=f"document:{key}",
                    code="recommend.document" if fresh else "recommend.update_documentation",
                    text=f"Document {name}."
                    if fresh
                    else f"Bring the documentation of {name} up to date.",
                    action="change",
                    changes_systems=False,
                    priority="low",
                    risk="low",
                    reversible=True,
                    confidence=None,
                    why=Note(
                        "recommend.why.uncertain",
                        note.text,
                        {**dict(note.params), "of": note.code},
                    ),
                    params={"name": name},
                    target=target,
                )
            )
        elif note.code == "standing.known_poorly":
            out.add(
                Recommendation(
                    id=f"improve_knowledge:{key}",
                    code="recommend.improve_knowledge",
                    text=f"Connect what knows {name}: LEKA knows it poorly.",
                    action="other",
                    changes_systems=False,
                    priority="low",
                    risk="low",
                    reversible=None,
                    confidence=None,
                    why=Note(
                        "recommend.why.uncertain",
                        note.text,
                        {**dict(note.params), "of": note.code},
                    ),
                    params={"name": name},
                    target=target,
                )
            )
        elif note.code == "incident.no_cause":
            out.add(
                Recommendation(
                    id="investigate:incident",
                    code="recommend.investigate",
                    text="Investigate what caused it: nothing says or suggests it.",
                    action="monitor",
                    changes_systems=False,
                    priority="high",
                    risk="low",
                    reversible=None,
                    confidence=None,
                    why=Note(
                        "recommend.why.uncertain",
                        note.text,
                        {**dict(note.params), "of": note.code},
                    ),
                )
            )


def _for_impact(result: Result, out: _Proposals) -> None:
    applications = next((area.items for area in result.impact if area.code == "applications"), ())
    reached = sum(len(area.items) for area in result.impact)
    if not applications or result.risk not in ("high", "medium"):
        return
    out.add(
        Recommendation(
            id="notify:impact",
            code="recommend.notify",
            text=f"Tell the people of the {len(applications)} application(s) it reaches.",
            action="other",
            changes_systems=False,
            priority="high" if result.risk == "high" else "medium",
            risk="low",
            reversible=None,
            confidence=None,
            why=Note(
                "recommend.why.impact",
                f"It reaches {reached} thing(s); the risk is {result.risk}.",
                {"count": reached, "risk": result.risk},
            ),
            params={
                "applications": [item.name for item in applications],
                "count": len(applications),
            },
        )
    )


def recommend(result: Result, asked: Asked) -> tuple[Recommendation, ...]:
    """What LEKA proposes, from what this analysis found — none from an
    analysis that failed; asking differently from one that could not
    conclude."""
    if result.status == "failed":
        return ()
    out = _Proposals()
    _for_causes(result, out)
    _for_findings(result.findings, asked.subjects, out)
    _for_notes((*result.uncertainties, *result.missing), result.findings, asked.subjects, out)
    _for_impact(result, out)
    if result.status == "inconclusive" and out.empty:
        out.add(
            Recommendation(
                id="ask_differently",
                code="recommend.ask_differently",
                text="Ask differently — name what it is about, the period — or connect "
                "what would know.",
                action="other",
                changes_systems=False,
                priority="medium",
                risk="low",
                reversible=None,
                confidence=None,
                why=Note(
                    "recommend.why.inconclusive",
                    "The analysis could not conclude.",
                    {"missing": [n.code for n in result.missing][:3]},
                ),
            )
        )
    return out.sorted()


def _json(value: object) -> object:
    """A value as JSON says it: ids and moments as text, all the way down."""
    if isinstance(value, Mapping):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_json(v) for v in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def as_mapping(recommendation: Recommendation) -> Mapping[str, object]:
    """A recommendation, as it is kept (IntentionAnalysisResult)."""
    target = recommendation.target
    return {
        "id": recommendation.id,
        "code": recommendation.code,
        "text": recommendation.text,
        "params": _json(recommendation.params),
        "action": recommendation.action,
        "changes_systems": recommendation.changes_systems,
        "priority": recommendation.priority,
        "risk": recommendation.risk,
        "reversible": recommendation.reversible,
        "confidence": recommendation.confidence,
        "why": {
            "code": recommendation.why.code,
            "text": recommendation.why.text,
            "params": _json(recommendation.why.params),
        },
        "basis": list(recommendation.basis),
        "evidence": list(recommendation.evidence),
        "target": None
        if target is None
        else {"ref_type": target.ref_type, "ref_id": str(target.ref_id), "name": target.name},
    }
