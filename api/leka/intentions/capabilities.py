"""LEKA's own capabilities (LEKA-388): rules over the company model and an
intention's context, one for each thing an intention may need answered.

    standing        every intention: each thing it is about — its state,
                    its lifecycle, how well LEKA knows it, what LEKA already
                    concluded about it
    ownership       who owns it, maintains it, leads its teams, knows it
    dependencies    what it depends on, what depends on it, what that
                    reaches: applications, the business — and how bad
    incidents       its incidents in the period, what is said or suspected
                    to have caused them, what changed just before
    changes         what changed on it, or on what it is made of and depends
                    on, in the period — and what followed; everywhere in the
                    environment it says when it names nothing
    evolution       what LEKA learned in the period: things that appeared,
                    changed, went
    documentation   what describes it, and whether that is current
    compliance      what a thing of its kind should have: an owner, a
                    current document, its criticality said, nothing serious
                    left open, knowledge good enough
    migration       where to, what relies on it, what it relies on
    action          an action asked on systems: what it would reach, the
                    constraints it must hold to, the last deployment — and
                    that a person decides, never LEKA
    synthesis       the analysis answered in words, by a language model,
                    from what the others found (LEKA-394, writing.py)

Each says what it found as facts — every one with the evidence it rests
on — what it suspects as causes, what it reaches, what it does not know,
and how sure; never what to do (LEKA-389), never doing it (LEKA-391).
Pure functions of the material (analysis.py).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta

from leka.capabilities import Contract, Definition, Kind, Lifecycle, ModelNeed, provide
from leka.context import ContextElementRead
from leka.intentions.analysis import (
    Capability,
    Cause,
    ImpactArea,
    ImpactItem,
    Material,
    Note,
    Output,
    Part,
    Proofs,
    Statement,
    Subject,
    names,
)
from leka.intentions.writing import NEEDS as WRITING
from leka.knowledge import EntityBrief, EntityType, IncidentDetail

VERSION = 1
# How sure a fact a source states is; an inference, its own confidence.
STATED = 0.9
# A change this close before an incident is a probable cause; further, one
# to confirm.
CLOSE = timedelta(hours=6)
NEAR = timedelta(hours=24)
# What a thing of its kind should have, before it is called compliant.
DOCUMENTED = frozenset({"service", "application", "database", "repository"})
SEVERE = frozenset({"sev0", "sev1", "p0", "p1", "critical", "highest", "urgent", "blocker"})
SERIOUS = frozenset({"sev2", "p2", "high", "major"})


def _kind(thing: EntityBrief | Subject) -> str:
    kind = thing.type
    return kind.value if hasattr(kind, "value") else str(kind)


def _risk_of(severity: str | None) -> str:
    word = (severity or "").lower().replace(" ", "").replace("_", "").replace("-", "")
    if word in SEVERE:
        return "high"
    if word in SERIOUS:
        return "medium"
    return "low" if word else "unknown"


# The goals that are about one thing or a few, named: without one, nothing
# answers them.
ABOUT_ONE = frozenset(
    {"find_owner", "map_dependencies", "assess_impact", "plan_migration", "check_compliance"}
)


def _none(material: Material) -> Output:
    return Output(
        missing=(
            Note(
                "analysis.no_subject",
                "It names nothing the company model holds: nothing to read.",
            ),
        )
    )


# ── standing ─────────────────────────────────────────────────────────────────


def standing(material: Material) -> Output:
    """Each thing it is about: its state, its lifecycle, how well LEKA
    knows it, what LEKA already concluded about it. Naming nothing is
    missing something only for a goal about one thing — « who owns it »;
    « what changed in production » is about all of it."""
    subjects = material.asked.subjects
    if not subjects:
        return _none(material) if material.asked.goal in ABOUT_ONE else Output()
    proofs = Proofs(material)
    findings: list[Statement] = []
    uncertainties: list[Note] = []
    sure: list[float] = []
    for subject in subjects:
        held = material.standing.get(subject.id)
        state = material.status.get(subject.id)
        lifecycle = held.lifecycle.value if held is not None else subject.lifecycle
        evidence = proofs.entity(subject)
        findings.append(
            Statement(
                id=f"standing:{subject.id}",
                code="standing.state",
                text=(
                    f"{subject.name} ({subject.type}) is {lifecycle or 'known'}"
                    + (f", {state}" if state else "")
                    + (f", criticality {held.criticality}" if held and held.criticality else "")
                    + "."
                ),
                params={
                    "name": subject.name,
                    "type": subject.type,
                    "lifecycle": lifecycle,
                    "status": state,
                    "criticality": held.criticality if held else None,
                },
                evidence=(evidence,),
            )
        )
        if lifecycle in ("dormant", "archived", "removed"):
            uncertainties.append(
                Note(
                    "standing.inactive",
                    f"{subject.name} is {lifecycle}: what is said of it may be out of date.",
                    {"name": subject.name, "lifecycle": lifecycle},
                )
            )
        quality = material.quality.get(subject.id)
        if quality is not None:
            sure.append(quality.score)
            findings.append(
                Statement(
                    id=f"quality:{subject.id}",
                    code="standing.quality",
                    text=(
                        f"What LEKA knows of {subject.name} is {quality.level}"
                        f" ({quality.score:.2f})."
                    ),
                    params={
                        "name": subject.name,
                        "level": quality.level,
                        "score": round(quality.score, 3),
                        "missing": [m.get("code") for m in quality.missing[:3]],
                    },
                    evidence=(evidence,),
                )
            )
            if quality.level == "low":
                uncertainties.append(
                    Note(
                        "standing.known_poorly",
                        f"LEKA knows {subject.name} poorly: read what follows as likely.",
                        {"name": subject.name, "score": round(quality.score, 3)},
                    )
                )
        elif held is not None:
            sure.append(held.confidence)
        open_ = [f for f in material.findings if f.subject_id == subject.id]
        if open_:
            findings.append(
                Statement(
                    id=f"findings:{subject.id}",
                    code="standing.findings",
                    text=(
                        f"LEKA already has {len(open_)} open point(s) on {subject.name}"
                        f", {sum(f.severity == 'high' for f in open_)} important."
                    ),
                    params={
                        "name": subject.name,
                        "count": len(open_),
                        "high": sum(f.severity == "high" for f in open_),
                        "codes": [f.code for f in open_[:5]],
                    },
                    evidence=tuple(proofs.finding(f) for f in open_[:5]),
                )
            )
    return Output(
        findings=tuple(findings),
        uncertainties=tuple(uncertainties),
        confidence=round(sum(sure) / len(sure), 3) if sure else 0.8,
        evidence=proofs.all,
    )


# ── ownership ────────────────────────────────────────────────────────────────


def ownership(material: Material) -> Output:
    """Who owns each thing — a team or a person a source names — who
    maintains it, leads its teams, knows it, and how to escalate."""
    subjects = material.asked.subjects
    if not subjects:
        return _none(material)
    proofs = Proofs(material)
    findings: list[Statement] = []
    uncertainties: list[Note] = []
    summary: Note | None = None
    sure: list[float] = []
    for subject in subjects:
        owners = list(material.owners.get(subject.id, ()))
        held = material.responsibility.get(subject.id)
        if owners:
            evidence = tuple(
                proofs.tie(subject, owner, "owned_by", origin="stated")
                if (subject.id, owner.id, "owned_by") in _ties(material)
                else proofs.tie(owner, subject, "owns", origin="stated")
                for owner in owners
            )
            said = names(owners)
            findings.append(
                Statement(
                    id=f"owner:{subject.id}",
                    code="ownership.owner",
                    text=f"{subject.name} is owned by {', '.join(said)}.",
                    params={"name": subject.name, "owners": said, "count": len(owners)},
                    evidence=evidence,
                )
            )
            sure.append(STATED)
            summary = summary or Note(
                "ownership.summary",
                f"{subject.name} is owned by {', '.join(said)}.",
                {"name": subject.name, "owners": said},
            )
            if len(owners) > 1:
                uncertainties.append(
                    Note(
                        "ownership.several",
                        f"Several owners are named for {subject.name}: which one decides is "
                        "not said.",
                        {"name": subject.name, "owners": said},
                    )
                )
        if held is not None:
            for code, ties, kind in (
                ("ownership.maintainers", held.maintainers, "maintained_by"),
                ("ownership.experts", held.experts, "contributes_to"),
            ):
                if not ties:
                    continue
                said = names(t.entity for t in ties)
                findings.append(
                    Statement(
                        id=f"{code}:{subject.id}",
                        code=code,
                        text=(
                            f"{subject.name} is maintained by {', '.join(said)}."
                            if kind == "maintained_by"
                            else f"{', '.join(said)} know {subject.name} from their work."
                        ),
                        params={"name": subject.name, "people": said, "count": len(ties)},
                        evidence=tuple(
                            proofs.tie(
                                subject if kind == "maintained_by" else t.entity,
                                t.entity if kind == "maintained_by" else subject,
                                kind,
                                origin=t.origin,
                                confidence=t.confidence,
                            )
                            for t in ties[:5]
                        ),
                    )
                )
                sure.append(max(t.confidence for t in ties))
            if held.leads:
                said = names(held.leads)
                findings.append(
                    Statement(
                        id=f"leads:{subject.id}",
                        code="ownership.leads",
                        text=f"Its owning teams are led by {', '.join(said)}.",
                        params={"name": subject.name, "people": said},
                        evidence=tuple(proofs.entity(lead) for lead in held.leads[:5]),
                    )
                )
            if held.escalation_policy:
                findings.append(
                    Statement(
                        id=f"escalation:{subject.id}",
                        code="ownership.escalation",
                        text=f"{subject.name} escalates through {held.escalation_policy}.",
                        params={"name": subject.name, "policy": held.escalation_policy},
                        evidence=(proofs.entity(subject),),
                    )
                )
        if not owners:
            uncertainties.append(
                Note(
                    "ownership.unknown",
                    f"No source names an owner for {subject.name}.",
                    {"name": subject.name},
                )
            )
    return Output(
        findings=tuple(findings),
        uncertainties=tuple(uncertainties),
        summary=summary
        or Note(
            "ownership.none",
            "No owner is named for what it asks about.",
            {"names": names(subjects)},
        ),
        confidence=round(sum(sure) / len(sure), 3) if sure else None,
        evidence=proofs.all,
    )


def _ties(material: Material) -> set[tuple[object, object, str]]:
    return {
        (e.relationship.start.id, e.relationship.end.id, e.relationship.type)
        for e in material.elements
        if e.kind == "relationship" and e.relationship is not None
    }


# ── dependencies ─────────────────────────────────────────────────────────────


def dependencies(material: Material) -> Output:
    """What each thing depends on, what depends on it, and what that
    reaches: the applications holding them, the business relying on
    them — and how bad that would be."""
    subjects = material.asked.subjects
    if not subjects:
        return _none(material)
    proofs = Proofs(material)
    findings: list[Statement] = []
    uncertainties: list[Note] = []
    critical = False
    relying = 0
    for subject in subjects:
        below = material.downstream.get(subject.id)
        above = material.upstream.get(subject.id)
        for walked, code, verb in (
            (below, "dependency.depends_on", "depends on"),
            (above, "dependency.relied_on", "is relied on by"),
        ):
            if walked is None or not walked.nodes:
                continue
            nodes = walked.nodes
            near = [n.entity for n in nodes if n.depth == 1]
            said = names(n.entity for n in nodes)
            evidence = tuple(
                proofs.tie(subject, thing, "depends_on")
                if code == "dependency.depends_on"
                else proofs.tie(thing, subject, "depends_on")
                for thing in near[:5]
            )
            findings.append(
                Statement(
                    id=f"{code}:{subject.id}",
                    code=code,
                    text=f"{subject.name} {verb} {len(nodes)} thing(s): {', '.join(said)}.",
                    params={
                        "name": subject.name,
                        "count": len(nodes),
                        "direct": len(near),
                        "names": said,
                        "truncated": walked.truncated,
                    },
                    evidence=evidence or (proofs.entity(subject),),
                )
            )
            if code == "dependency.relied_on":
                relying += len(nodes)
                critical = critical or any(
                    (n.criticality or "").lower() in ("critical", "high") for n in nodes
                )
        if (below is None or not below.nodes) and (above is None or not above.nodes):
            uncertainties.append(
                Note(
                    "dependency.none",
                    f"Nothing is known to depend on {subject.name}, nor it on anything.",
                    {"name": subject.name},
                )
            )
    areas: list[ImpactArea] = []
    impact = material.impact
    business = 0
    if impact is not None:
        for code, things in (
            ("dependents", impact.dependents),
            ("applications", impact.applications),
            ("capabilities", [t.entity for t in impact.capabilities]),
            ("processes", [t.entity for t in impact.processes]),
        ):
            if things:
                areas.append(
                    ImpactArea(
                        code,
                        tuple(ImpactItem(_kind(t), t.id, t.name) for t in things),
                    )
                )
        business = len(impact.capabilities) + len(impact.processes)
    risk = "high" if critical or business else "medium" if relying >= 3 else "low"
    basis = Note(
        "dependency.risk",
        f"{relying} thing(s) rely on it"
        + (", some critical" if critical else "")
        + (f", {business} business capability or process" if business else "")
        + ".",
        {"relying": relying, "critical": critical, "business": business},
    )
    return Output(
        findings=tuple(findings),
        impact=tuple(areas),
        risk=risk,
        risk_basis=basis,
        uncertainties=tuple(uncertainties),
        summary=Note(
            "dependency.summary",
            f"{relying} thing(s) rely on what it asks about.",
            {"relying": relying, "names": names(subjects)},
        ),
        confidence=0.85 if findings else None,
        evidence=proofs.all,
    )


# ── incidents ────────────────────────────────────────────────────────────────


def _close(before: timedelta) -> float:
    if before <= CLOSE:
        return 0.7
    if before <= NEAR:
        return 0.55
    return 0.4


def incidents(material: Material) -> Output:
    """Its incidents in the period: what is said or suspected to have
    caused each, what changed just before it opened, what it reached."""
    asked = material.asked
    subjects = {s.id for s in asked.subjects}
    proofs = Proofs(material)
    findings: list[Statement] = []
    causes: dict[str, Cause] = {}
    areas: dict[str, dict[object, ImpactItem]] = {}
    risk = "unknown"
    worst = 0
    for incident in material.incidents:
        opened = incident.opened_at
        if asked.since and opened and opened < asked.since:
            continue
        on = [t.entity for t in incident.affected]
        if subjects and not subjects & {t.id for t in on}:
            continue
        said = incident.severity or incident.priority
        level = _risk_of(said)
        score = {"high": 3, "medium": 2, "low": 1}.get(level, 0)
        if score > worst:
            worst, risk = score, level
        evidence = proofs.event(incident_brief(incident), at=opened, detail=said)
        findings.append(
            Statement(
                id=f"incident:{incident.id}",
                code="incident.seen",
                text=(
                    f"{incident.name} on {', '.join(names(on)) or 'it'}"
                    + (f", {said}" if said else "")
                    + (f", {incident.state}" if incident.state else "")
                    + "."
                ),
                params={
                    "name": incident.name,
                    "on": names(on),
                    "severity": said,
                    "state": incident.state,
                    "opened_at": opened.isoformat() if opened else None,
                },
                evidence=(evidence,),
            )
        )
        for tie in incident.suspected_causes:
            stated = tie.origin == "stated"
            cause_id = f"cause:{tie.entity.id}"
            causes[cause_id] = Cause(
                id=cause_id,
                code="cause.said" if stated else "cause.suspected",
                label=tie.entity.name,
                basis="stated" if stated else "inferred",
                why=(
                    f"Its source says {incident.name} was caused by it."
                    if stated
                    else f"It came just before {incident.name} ({tie.rule})."
                ),
                confidence=round(tie.confidence, 3),
                ref_type=_kind(tie.entity),
                ref_id=tie.entity.id,
                params={"incident": incident.name, "rule": tie.rule},
                evidence=(
                    proofs.tie(
                        incident_brief(incident),
                        tie.entity,
                        "caused_by",
                        origin=tie.origin,
                        confidence=tie.confidence,
                    ),
                    evidence,
                ),
            )
        for change in incident.changed_before:
            cause_id = f"cause:{change.entity.id}"
            if cause_id in causes or opened is None:
                continue
            before = opened - change.at
            causes[cause_id] = Cause(
                id=cause_id,
                code="cause.changed_before",
                label=change.entity.name,
                basis="inferred",
                why=(
                    f"{change.entity.name} changed {round(before.total_seconds() / 3600, 1)} "
                    f"hour(s) before {incident.name} opened, on what it affects."
                ),
                confidence=_close(before),
                ref_type=_kind(change.entity),
                ref_id=change.entity.id,
                params={
                    "incident": incident.name,
                    "hours": round(before.total_seconds() / 3600, 1),
                    "kind": change.kind,
                },
                evidence=(proofs.event(change.entity, at=change.at, detail=change.kind), evidence),
            )
        for code, things in (
            ("dependents", incident.impact.dependents),
            ("applications", incident.impact.applications),
            ("capabilities", [t.entity for t in incident.impact.capabilities]),
            ("processes", [t.entity for t in incident.impact.processes]),
        ):
            for thing in things:
                areas.setdefault(code, {}).setdefault(
                    thing.id, ImpactItem(_kind(thing), thing.id, thing.name)
                )
    # What `changes` found, handed (LEKA-399): a change whose reach — what
    # depends on what it touched — holds what an incident affects is a cause
    # its incident's own record does not tie to it.
    seen = {f.params.get("name") for f in findings}
    for cause in material.handed["changes"].causes if "changes" in material.handed else ():
        if cause.params.get("incident") in seen and cause.id not in causes:
            causes[cause.id] = replace(
                cause, why=f"{cause.why} (found with the changes of the period)"
            )
    ordered = sorted(causes.values(), key=lambda c: (c.basis != "stated", -(c.confidence or 0)))
    if not findings:
        where = _where(material)
        return Output(
            uncertainties=(
                Note(
                    "incident.none",
                    f"No incident is known {where} in the period.",
                    {"names": names(asked.subjects), "where": where},
                ),
            ),
            summary=Note(
                "incident.none",
                f"No incident is known {where} in the period.",
                {"names": names(asked.subjects), "where": where},
            ),
            confidence=0.6,
            evidence=proofs.all,
        )
    top = ordered[0] if ordered else None
    return Output(
        findings=tuple(findings),
        causes=tuple(ordered),
        impact=tuple(ImpactArea(code, tuple(items.values())) for code, items in areas.items()),
        risk=risk,
        risk_basis=Note("incident.risk", "Read from the severity its source declares.", {}),
        uncertainties=()
        if top
        else (Note("incident.no_cause", "Nothing is said or suspected to have caused it.", {}),),
        summary=Note(
            "incident.summary",
            f"{len(findings)} incident(s)"
            + (f"; the likeliest cause: {top.label} ({top.basis})" if top else "")
            + ".",
            {
                "count": len(findings),
                "cause": top.label if top else None,
                "basis": top.basis if top else None,
            },
        ),
        confidence=round(top.confidence or 0.5, 3) if top else 0.5,
        evidence=proofs.all,
    )


def _where(material: Material) -> str:
    """Where it looked, in words: on what it names, or in the environment
    it says, or everywhere."""
    asked = material.asked
    if asked.subjects:
        return "on " + ", ".join(names(asked.subjects))
    if asked.environment:
        return f"in {asked.environment}"
    return "in the workspace"


def _freshness(element: ContextElementRead) -> str | None:
    said = element.entity.attributes.get("freshness") if element.entity else None
    return said if isinstance(said, str) else None


def incident_brief(incident: IncidentDetail) -> EntityBrief:
    return EntityBrief(
        id=incident.id,
        type=EntityType.INCIDENT,
        key=incident.key,
        name=incident.name,
        lifecycle=incident.lifecycle,
    )


# ── changes ──────────────────────────────────────────────────────────────────


def changes(material: Material) -> Output:
    """What changed on it — or on what it is made of and depends on — in
    the period, what each reached, and the incidents that followed."""
    proofs = Proofs(material)
    findings: list[Statement] = []
    causes: list[Cause] = []
    reached: dict[object, ImpactItem] = {}
    for footprint in material.changes:
        change = footprint.change
        evidence = proofs.event(change, at=footprint.at, detail=footprint.kind)
        findings.append(
            Statement(
                id=f"change:{change.id}",
                code="change.made",
                text=(
                    f"{footprint.kind} {change.name} on {footprint.at:%Y-%m-%d %H:%M}"
                    + (f" in {footprint.environment}" if footprint.environment else "")
                    + f": it reaches {len(footprint.reached)} thing(s)"
                    + (
                        f", {len(footprint.incidents)} incident(s) followed"
                        if footprint.incidents
                        else ""
                    )
                    + "."
                ),
                params={
                    "name": change.name,
                    "kind": footprint.kind,
                    "at": footprint.at.isoformat(),
                    "state": footprint.state,
                    "environment": footprint.environment,
                    "touched": names(t.entity for t in footprint.touched),
                    "reached": len(footprint.reached),
                    "incidents": len(footprint.incidents),
                },
                evidence=(evidence,),
            )
        )
        for reach in footprint.reached:
            reached.setdefault(
                reach.entity.id, ImpactItem(_kind(reach.entity), reach.entity.id, reach.entity.name)
            )
        for followed in footprint.incidents:
            causes.append(
                Cause(
                    id=f"cause:{change.id}",
                    code="cause.said" if followed.stated else "cause.followed",
                    label=change.name,
                    basis="stated" if followed.stated else "inferred",
                    why=(
                        f"Its source says {followed.entity.name} was caused by it."
                        if followed.stated
                        else f"{followed.entity.name} opened after it, on what it touched."
                    ),
                    confidence=STATED if followed.stated else 0.55,
                    ref_type=_kind(change),
                    ref_id=change.id,
                    params={"incident": followed.entity.name, "kind": footprint.kind},
                    evidence=(evidence, proofs.event(followed.entity, at=followed.opened_at)),
                )
            )
    where = _where(material)
    if not findings:
        return Output(
            uncertainties=(
                Note("change.none", f"No change is known {where} in the period.", {"where": where}),
            ),
            summary=Note(
                "change.none", f"Nothing changed {where} in the period.", {"where": where}
            ),
            confidence=0.6,
            evidence=proofs.all,
        )
    unique = list({c.id: c for c in causes}.values())
    return Output(
        findings=tuple(findings),
        causes=tuple(unique),
        impact=(ImpactArea("dependents", tuple(reached.values())),) if reached else (),
        summary=Note(
            "change.summary",
            f"{len(findings)} change(s) {where} in the period"
            + (f", {len(unique)} followed by an incident" if unique else "")
            + ".",
            {"count": len(findings), "followed": len(unique), "where": where},
        ),
        confidence=0.85,
        evidence=proofs.all,
    )


# ── documentation ────────────────────────────────────────────────────────────


def documentation(material: Material) -> Output:
    """What describes each thing, in its context, and whether that is
    current."""
    subjects = material.asked.subjects
    if not subjects:
        return _none(material)
    proofs = Proofs(material)
    findings: list[Statement] = []
    uncertainties: list[Note] = []
    documents = {
        e.ref_id: e for e in material.elements if e.kind == "entity" and e.ref_type == "document"
    }
    describing: dict[uuid.UUID, list[uuid.UUID]] = {}
    for element in material.elements:
        tie = element.relationship
        if element.kind == "relationship" and tie is not None and tie.type == "describes":
            describing.setdefault(tie.end.id, []).append(tie.start.id)
    counted = 0
    for subject in subjects:
        held = material.standing.get(subject.id)
        found = [documents[d] for d in describing.get(subject.id, []) if d in documents]
        counted += len(found)
        if found:
            said = [d.label for d in found][:5]
            findings.append(
                Statement(
                    id=f"documents:{subject.id}",
                    code="documentation.found",
                    text=f"{subject.name} is described by {', '.join(said)}.",
                    params={"name": subject.name, "documents": said, "count": len(found)},
                    evidence=tuple(
                        proofs.entity(
                            EntityBrief(
                                id=d.ref_id,
                                type="document",
                                key=d.entity.key if d.entity else "",
                                name=d.label,
                                lifecycle=d.entity.lifecycle if d.entity else "active",
                            ),
                            detail=_freshness(d),
                        )
                        for d in found[:5]
                    ),
                )
            )
        if held is not None and held.documents and not held.fresh_documents:
            uncertainties.append(
                Note(
                    "documentation.stale",
                    f"No document describing {subject.name} is known to be current.",
                    {"name": subject.name, "last": held.last_documented_at},
                )
            )
        if (held is None or not held.documents) and not found:
            uncertainties.append(
                Note(
                    "documentation.none",
                    f"No document is known to describe {subject.name}.",
                    {"name": subject.name},
                )
            )
    return Output(
        findings=tuple(findings),
        uncertainties=tuple(uncertainties),
        summary=Note(
            "documentation.summary",
            f"{counted} document(s) describe it.",
            {"count": counted},
        ),
        confidence=0.8 if findings else 0.6,
        evidence=proofs.all,
    )


# ── compliance ───────────────────────────────────────────────────────────────


def compliance(material: Material) -> Output:
    """What a thing of its kind should have — an owner, a current
    document, its criticality said, nothing serious left open, knowledge
    good enough — checked, each with what shows it."""
    subjects = material.asked.subjects
    if not subjects:
        return _none(material)
    proofs = Proofs(material)
    findings: list[Statement] = []
    failed = 0
    for subject in subjects:
        held = material.standing.get(subject.id)
        quality = material.quality.get(subject.id)
        serious = [
            f for f in material.findings if f.subject_id == subject.id and f.severity == "high"
        ]
        checks: list[tuple[str, bool | None]] = [
            ("owner", bool(material.owners.get(subject.id))),
            (
                "documented",
                None if subject.type not in DOCUMENTED else bool(held and held.fresh_documents),
            ),
            ("criticality", bool(held and held.criticality)),
            ("nothing_serious", not serious),
            ("known_well", None if quality is None else quality.level != "low"),
        ]
        for check, passed in checks:
            if passed is None:
                continue
            failed += not passed
            findings.append(
                Statement(
                    id=f"check:{check}:{subject.id}",
                    code="compliance.check",
                    text=f"{subject.name}: {check.replace('_', ' ')} — "
                    + ("yes." if passed else "no."),
                    params={"name": subject.name, "check": check, "passed": passed},
                    evidence=tuple(proofs.finding(f) for f in serious[:3])
                    if check == "nothing_serious" and serious
                    else (proofs.entity(subject),),
                )
            )
    return Output(
        findings=tuple(findings),
        risk="high" if failed >= 3 else "medium" if failed else "low",
        risk_basis=Note(
            "compliance.risk",
            f"{failed} check(s) of {len(findings)} fail.",
            {"failed": failed, "checks": len(findings)},
        ),
        summary=Note(
            "compliance.summary",
            f"{len(findings) - failed} of {len(findings)} check(s) pass.",
            {"passed": len(findings) - failed, "checks": len(findings)},
        ),
        confidence=0.8,
        evidence=proofs.all,
    )


# ── migration ────────────────────────────────────────────────────────────────


def migration(material: Material) -> Output:
    """A migration's ground: where to, what relies on what moves, what it
    relies on."""
    asked = material.asked
    if not asked.subjects:
        return _none(material)
    proofs = Proofs(material)
    findings: list[Statement] = []
    missing: list[Note] = []
    target = next((value for kind, value, _ in asked.constraints if kind == "target"), None)
    if target:
        findings.append(
            Statement(
                id="migration:target",
                code="migration.target",
                text=f"It moves to {target}.",
                params={"target": target},
                evidence=tuple(proofs.entity(s) for s in asked.subjects[:3]),
            )
        )
    else:
        missing.append(Note("migration.no_target", "Where it moves to is not said.", {}))
    for subject in asked.subjects:
        above = material.upstream.get(subject.id)
        below = material.downstream.get(subject.id)
        relying = len(above.nodes) if above else 0
        relied = len(below.nodes) if below else 0
        findings.append(
            Statement(
                id=f"migration:{subject.id}",
                code="migration.ties",
                text=(
                    f"Moving {subject.name}: {relying} thing(s) rely on it, it relies on {relied}."
                ),
                params={"name": subject.name, "relying": relying, "relied": relied},
                evidence=(proofs.entity(subject),),
            )
        )
    return Output(
        findings=tuple(findings),
        missing=tuple(missing),
        summary=Note(
            "migration.summary",
            "What moves, and what it touches." if target else "Where it moves to is missing.",
            {"target": target},
        ),
        confidence=0.75 if target else 0.5,
        evidence=proofs.all,
    )


# ── action ───────────────────────────────────────────────────────────────────


def action(material: Material) -> Output:
    """An action asked on systems: what it would reach, the constraints it
    must hold to, the last deployment — said, never done: a person
    approves (LEKA-390), LEKA acts after (LEKA-391)."""
    asked = material.asked
    acts = [code for code, changes in asked.actions if changes]
    if not acts:
        return Output()
    proofs = Proofs(material)
    findings: list[Statement] = [
        Statement(
            id=f"action:{code}",
            code="action.asked",
            text=(
                f"It asks to {code} {', '.join(names(asked.subjects)) or 'something'}: "
                "a person must approve it first."
            ),
            params={"action": code, "on": names(asked.subjects)},
            evidence=tuple(proofs.entity(s) for s in asked.subjects[:3]),
        )
        for code in acts
    ]
    reach: dict[object, ImpactItem] = {}
    for subject in asked.subjects:
        above = material.upstream.get(subject.id)
        for node in above.nodes if above else []:
            reach.setdefault(
                node.entity.id, ImpactItem(_kind(node.entity), node.entity.id, node.entity.name)
            )
        last = next(
            (
                f
                for f in sorted(material.changes, key=lambda f: f.at, reverse=True)
                if f.kind == "deployment" and subject.id in {t.entity.id for t in f.touched}
            ),
            None,
        )
        if last is not None:
            findings.append(
                Statement(
                    id=f"action:last:{subject.id}",
                    code="action.last_deployment",
                    text=f"The last deployment of {subject.name} was {last.change.name}.",
                    params={
                        "name": subject.name,
                        "deployment": last.change.name,
                        "at": last.at.isoformat(),
                    },
                    evidence=(proofs.event(last.change, at=last.at, detail=last.kind),),
                )
            )
    # Handed (LEKA-399): who answers for what it acts on — whom the person
    # deciding should hear — and what depends on it, beyond its own read.
    owning = material.handed.get("ownership")
    told = sorted(
        {
            str(name)
            for f in (owning.findings if owning else ())
            if f.code == "ownership.owner"
            for name in f.params.get("owners") or []  # type: ignore[attr-defined]
        }
    )
    if told:
        findings.append(
            Statement(
                id="action:inform",
                code="action.inform",
                text=f"Before it is done, {', '.join(told)} should be told: they own it.",
                params={"owners": told},
                evidence=tuple(e for f in owning.findings for e in f.evidence)[:5]
                if owning
                else (),
            )
        )
    relying = material.handed.get("dependencies")
    for area in relying.impact if relying else ():
        for item in area.items:
            reach.setdefault(item.ref_id, item)
    if reach:
        findings.append(
            Statement(
                id="action:reach",
                code="action.reach",
                text=f"{len(reach)} thing(s) depend on what it would act on.",
                params={"count": len(reach), "names": [i.name for i in reach.values()][:5]},
                evidence=tuple(proofs.entity(s) for s in asked.subjects[:3]),
            )
        )
    for kind, value, hard in asked.constraints:
        if not hard or kind in ("services", "sources"):
            continue
        findings.append(
            Statement(
                id=f"action:constraint:{kind}",
                code="action.constraint",
                text=f"It must hold to: {kind.replace('_', ' ')}"
                + (f" ({value})" if value not in (None, True) else "")
                + ".",
                params={
                    "kind": kind,
                    "value": value if isinstance(value, str | int | float | bool) else None,
                },
                evidence=(),
            )
        )
    return Output(
        findings=tuple(findings),
        impact=(ImpactArea("dependents", tuple(reach.values())),) if reach else (),
        risk="high" if len(reach) >= 3 else "medium",
        risk_basis=Note(
            "action.risk",
            f"An action on systems, {len(reach)} thing(s) depending on its target.",
            {"relying": len(reach)},
        ),
        summary=Note(
            "action.summary",
            f"{', '.join(acts)} asked: a person decides before anything is done.",
            {"actions": acts, "relying": len(reach)},
        ),
        confidence=0.85,
        evidence=proofs.all,
    )


# ── evolution ────────────────────────────────────────────────────────────────


def evolution(material: Material) -> Output:
    """What LEKA learned in the period: the things that appeared in what its
    sources say, changed, went or came back — services, repositories,
    databases, resources, teams, documents (LEKA-383)."""
    proofs = Proofs(material)
    findings: list[Statement] = []
    counts: dict[str, int] = {}
    for item in material.evolution:
        thing = item.thing
        counts[item.change] = counts.get(item.change, 0) + 1
        evidence = proofs.entity(thing, detail=item.change)
        findings.append(
            Statement(
                id=f"learned:{thing.id}",
                code=f"learned.{item.change}",
                text=(
                    f"{thing.name} ({_kind(thing)}) {item.change.replace('_', ' ')}"
                    f" on {item.at:%Y-%m-%d %H:%M}"
                    + (f": {', '.join(item.fields[:4])}" if item.fields else "")
                    + "."
                ),
                params={
                    "name": thing.name,
                    "type": _kind(thing),
                    "change": item.change,
                    "fields": list(item.fields[:6]),
                    "at": item.at.isoformat(),
                },
                evidence=(evidence,),
            )
        )
    where = _where(material)
    if not findings:
        return Output(
            summary=Note(
                "learned.none",
                f"LEKA learned nothing new {where} in the period.",
                {"where": where},
            ),
            confidence=0.7,
            evidence=proofs.all,
        )
    return Output(
        findings=tuple(findings),
        summary=Note(
            "learned.summary",
            f"LEKA learned {len(findings)} thing(s) {where} in the period: "
            + ", ".join(f"{n} {change.replace('_', ' ')}" for change, n in sorted(counts.items()))
            + ".",
            {"count": len(findings), **counts, "where": where},
        ),
        confidence=0.85,
        evidence=proofs.all,
    )


# ── the catalogue ────────────────────────────────────────────────────────────

CAPABILITIES: Sequence[Capability] = (
    Capability(
        "standing",
        VERSION,
        "Each thing it is about: its state, lifecycle, how well it is known, what LEKA "
        "already concluded.",
        goals=frozenset(),
        reads=frozenset({Part.STANDING, Part.FINDINGS, Part.QUALITY}),
        run=standing,
        always=True,
    ),
    Capability(
        "ownership",
        VERSION,
        "Who owns it, maintains it, leads its teams, knows it.",
        goals=frozenset({"find_owner", "act"}),
        kinds=frozenset({"ownership"}),
        sides=frozenset({"organizational", "technical"}),
        reads=frozenset({Part.OWNERS, Part.RESPONSIBILITY}),
        run=ownership,
    ),
    Capability(
        "dependencies",
        VERSION,
        "What it depends on, what depends on it, and what that reaches.",
        goals=frozenset({"map_dependencies", "assess_impact", "plan_migration"}),
        kinds=frozenset({"dependency", "migration"}),
        sides=frozenset({"technical", "business"}),
        reads=frozenset({Part.DOWNSTREAM, Part.UPSTREAM, Part.IMPACT}),
        run=dependencies,
    ),
    Capability(
        "incidents",
        VERSION,
        "Its incidents in the period, their causes said or suspected, what changed before.",
        goals=frozenset({"explain_cause", "investigate", "find_change"}),
        kinds=frozenset({"diagnose", "change"}),
        sides=frozenset({"temporal", "technical"}),
        reads=frozenset({Part.INCIDENTS}),
        run=incidents,
        # The causes the changes of the period reach (LEKA-399).
        uses=frozenset({"changes"}),
    ),
    Capability(
        "changes",
        VERSION,
        "What changed on it or around it in the period, what each reached, what followed.",
        goals=frozenset({"find_change", "explain_cause", "act"}),
        kinds=frozenset({"change", "diagnose"}),
        sides=frozenset({"temporal", "technical"}),
        reads=frozenset({Part.CHANGES}),
        run=changes,
    ),
    Capability(
        "evolution",
        VERSION,
        "What LEKA learned in the period: the things that appeared, changed, went.",
        goals=frozenset({"find_change", "investigate"}),
        kinds=frozenset({"change"}),
        sides=frozenset({"temporal", "technical", "organizational", "business"}),
        reads=frozenset({Part.EVOLUTION}),
        run=evolution,
    ),
    Capability(
        "documentation",
        VERSION,
        "What describes it, and whether that is current.",
        goals=frozenset({"find_knowledge", "check_compliance"}),
        kinds=frozenset({"knowledge", "compliance"}),
        sides=frozenset({"technical", "business"}),
        reads=frozenset({Part.STANDING}),
        run=documentation,
    ),
    Capability(
        "compliance",
        VERSION,
        "What a thing of its kind should have, checked.",
        goals=frozenset({"check_compliance"}),
        kinds=frozenset({"compliance"}),
        reads=frozenset({Part.STANDING, Part.OWNERS, Part.FINDINGS, Part.QUALITY}),
        run=compliance,
    ),
    Capability(
        "migration",
        VERSION,
        "Where it moves to, what relies on it, what it relies on.",
        goals=frozenset({"plan_migration"}),
        kinds=frozenset({"migration"}),
        reads=frozenset({Part.UPSTREAM, Part.DOWNSTREAM}),
        run=migration,
    ),
    Capability(
        "action",
        VERSION,
        "An action asked on systems: what it reaches, its constraints, the last deployment.",
        goals=frozenset({"act"}),
        reads=frozenset({Part.UPSTREAM, Part.CHANGES}),
        run=action,
        # Who to tell, what it reaches (LEKA-399).
        uses=frozenset({"ownership", "dependencies"}),
    ),
    # Written by a language model, from what the ones above found
    # (writing.py, LEKA-394): run after them, when a model can.
    Capability(
        "synthesis",
        VERSION,
        "The analysis answered in words, each point citing what it rests on — written by a "
        "language model from what LEKA's rules found, and nothing else.",
        goals=frozenset(),
        method="model",
        always=True,
    ),
)


def capability_named(name: str) -> Capability | None:
    return next((c for c in CAPABILITIES if c.name == name), None)


# ── in the catalogue (LEKA-393) ──────────────────────────────────────────────

# What each is about, what it is called, how people ask for it.
CATALOGUE: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "synthesis": ("knowledge", "Synthesis", ("Pourquoi payment-api est lent depuis ce matin ?",)),
    "standing": ("knowledge", "Standing", ("Où en est Billing API ?",)),
    "ownership": ("knowledge", "Ownership", ("Qui est responsable de payment-api ?",)),
    "dependencies": ("architecture", "Dependencies", ("De quoi dépend Billing API ?",)),
    "incidents": ("operations", "Incidents", ("Pourquoi Billing API est lente depuis hier ?",)),
    "changes": ("operations", "Changes", ("Qu'est-ce qui a changé sur checkout cette semaine ?",)),
    "evolution": ("knowledge", "Evolution", ("Quoi de neuf depuis hier en production ?",)),
    "documentation": ("documentation", "Documentation", ("Où est documenté auth-service ?",)),
    "compliance": ("compliance", "Compliance", ("auth-service est-il conforme ?",)),
    "migration": ("architecture", "Migration", ("Migrer Billing API vers Kubernetes",)),
    "action": ("operations", "Action reach", ("Redémarre auth-service en production",)),
}


def definitions() -> list[Definition]:
    """LEKA's own analyses, as the catalogue holds them: rules, active,
    run on an intention's context — asking is what uses them."""
    found: list[Definition] = []
    for capability in CAPABILITIES:
        category, title, examples = CATALOGUE[capability.name]
        written = capability.method == "model"
        found.append(
            Definition(
                key=capability.name,
                title=title,
                summary=capability.summary,
                category=category,
                kind=Kind.MODEL if written else Kind.RULES,
                version=f"{capability.version}.0.0",
                lifecycle=Lifecycle.ACTIVE,
                contract=Contract(output="analysis", formats=("json",)),
                model=written,
                # What it asks of the model that writes it: the router picks.
                model_needs=(
                    ModelNeed(structured=WRITING.structured, quality=WRITING.quality)
                    if written
                    else ModelNeed()
                ),
                permission="intention:create",
                goals=capability.goals,
                kinds=capability.kinds,
                examples=examples,
                always=capability.always,
            )
        )
    return found


provide("intentions.analysis", definitions)
