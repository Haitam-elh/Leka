"""What becomes of a conflict (LEKA-382): kept, settled by someone, applied
— never overwritten in silence.

    a run finds it        ──▶ `open`        (seen again: updated; no longer
                                              disagreed on: gone)
    someone keeps a side  ──▶ `resolved`    an attribute: the value kept,
                                              shown by the model whoever
                                              says otherwise; a relationship
                                              it has one of: the others
                                              refuted — left out by the build
    someone dismisses it  ──▶ `dismissed`   no contradiction: the model
                                              goes on as resolution chose
    someone reopens it    ──▶ `open`        the decision withdrawn: the
                                              model as before it

A decided conflict REOPENS when a value appears that no one decided on —
the decision stands meanwhile: the model goes on showing what was kept
until someone decides again.

THE DECISION'S FACTS are the model's own (leka.knowledge, model_assertions,
`provenance.conflict_id`), written or withdrawn in the decision's
transaction; the next build applies them, its fingerprint saying it must
run. Keeping a side may also say which source to prefer on this from now
on: an authority rule, which LEKA's next recommendations follow.

Every decision is kept on the conflict (`history`): what, who, when, why.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import datetime

from leka.intelligence.analysis import Analyzer, ConflictDraft, Material
from leka.intelligence.curation import DecisionRefusedError
from leka.intelligence.models import AuthorityRule, KnowledgeConflict
from leka.intelligence.repository import IntelligenceRepository
from leka.intelligence.schemas import (
    AuthorityRuleRead,
    ConflictDetail,
    ConflictRead,
    ConflictSummary,
)
from leka.knowledge import Assertion, AssertionRepository, EntityRepository, Lifecycle

REASON = 500
# The rule a decision's facts carry in the model.
RULE = "conflict.resolution"


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


# ── what a run finds ───────────────────────────────────────────────────


async def observe(
    repository: IntelligenceRepository,
    run_id: uuid.UUID,
    analyzer: Analyzer,
    drafts: Sequence[ConflictDraft],
    material: Material,
    *,
    now: datetime,
) -> dict[str, int]:
    """The conflicts a run found, kept: new ones opened, those seen again
    updated, those decided reopened when a value no one decided on
    appears, those open no longer seen gone."""
    kept = await repository.all_conflicts()
    counts = {"opened": 0, "updated": 0, "reopened": 0, "gone": 0}
    said: set[str] = set()
    for draft in drafts:
        said.add(draft.key)
        conflict = kept.get(draft.key)
        values = {canonical(side.get("value")) for side in draft.sides}
        if conflict is None:
            conflict = KnowledgeConflict(
                workspace_id=repository.workspace_id,
                key=draft.key,
                status="open",
                first_seen_at=now,
                first_run_id=run_id,
                occurrences=0,
                history=[],
                decided_values=[],
            )
            repository.add_conflict(conflict)
            counts["opened"] += 1
        elif conflict.status == "gone":
            conflict.status = "open"
            _remember(conflict, "reopened", now=now, reason="disagreed on again")
            counts["reopened"] += 1
        elif conflict.status in ("resolved", "dismissed") and not values <= set(
            conflict.decided_values
        ):
            conflict.status = "open"
            _remember(conflict, "reopened", now=now, reason="a value no one decided on")
            counts["reopened"] += 1
        else:
            counts["updated"] += 1
        _write(conflict, draft, analyzer, material, run_id=run_id, now=now)
    for key, conflict in kept.items():
        if conflict.status == "open" and key not in said:
            conflict.status = "gone"
            _remember(conflict, "gone", now=now, reason="no longer disagreed on")
            counts["gone"] += 1
    return counts


def _write(
    conflict: KnowledgeConflict,
    draft: ConflictDraft,
    analyzer: Analyzer,
    material: Material,
    *,
    run_id: uuid.UUID,
    now: datetime,
) -> None:
    conflict.kind = draft.kind
    conflict.subject_id = draft.subject.id
    conflict.subject_name = draft.subject.name[:500]
    conflict.subject_kind = draft.subject.kind
    conflict.about = draft.about[:100]
    conflict.relationship = draft.relationship
    conflict.chosen = draft.chosen
    conflict.sides = [dict(side) for side in draft.sides]
    conflict.recommendation = dict(draft.recommendation)
    conflict.statement = draft.statement
    conflict.provenance = {
        "analyzer": analyzer.name,
        "version": analyzer.version,
        "run_id": str(run_id),
        "model_built_at": material.built_at.isoformat() if material.built_at else None,
        "sources": list(draft.sources),
        **({"settled": dict(draft.settled)} if draft.settled else {}),
    }
    conflict.last_seen_at = now
    conflict.last_run_id = run_id
    conflict.occurrences += 1


def _remember(
    conflict: KnowledgeConflict,
    status: str,
    *,
    now: datetime,
    via: str | None = None,
    by: uuid.UUID | None = None,
    reason: str | None = None,
    value: object = None,
) -> None:
    conflict.history = [
        *conflict.history,
        {
            "status": status,
            "via": via,
            "by": str(by) if by else None,
            "at": now.isoformat(),
            "reason": reason[:REASON] if reason else None,
            **({"value": value} if value is not None else {}),
        },
    ]


# ── decisions ──────────────────────────────────────────────────────────


class ArbitrationService:
    """The conflicts of a workspace: settled, dismissed, reopened — and the
    workspace's word on its sources."""

    def __init__(
        self,
        repository: IntelligenceRepository,
        assertions: AssertionRepository,
        entities: EntityRepository,
    ) -> None:
        self._repository = repository
        self._assertions = assertions
        self._entities = entities

    async def resolve(
        self,
        conflict_id: uuid.UUID,
        *,
        side: int,
        by: uuid.UUID,
        reason: str | None,
        remember: bool,
        now: datetime,
    ) -> KnowledgeConflict | None:
        """Keep one side: the facts that make the model show it written,
        those of an earlier decision withdrawn — and, asked, its source
        preferred on this from now on."""
        conflict = await self._repository.conflict(conflict_id, for_update=True)
        if conflict is None:
            return None
        if conflict.status == "gone":
            raise DecisionRefusedError("not_open", "It is no longer disagreed on.")
        if side >= len(conflict.sides):
            raise DecisionRefusedError("invalid", "This conflict has no such side.")
        if conflict.subject_id is not None:
            found = await self._entities.by_ids([conflict.subject_id])
            thing = found.get(conflict.subject_id)
            if thing is None or thing.lifecycle is Lifecycle.REMOVED:
                raise DecisionRefusedError(
                    "gone", "What it is about is no longer in the company model."
                )
        kept = conflict.sides[side]
        await self._assertions.remove_for(conflict.id)
        for fact in _facts(conflict, side, by=by, now=now):
            await self._assertions.put(fact)
        conflict.status = "resolved"
        conflict.resolution = {
            "side": side,
            "value": kept.get("value"),
            "via": "person",
            "by": str(by),
            "at": now.isoformat(),
            "reason": reason[:REASON] if reason else None,
        }
        conflict.decided_values = sorted({canonical(s.get("value")) for s in conflict.sides})
        _remember(
            conflict,
            "resolved",
            now=now,
            via="person",
            by=by,
            reason=reason,
            value=kept.get("value"),
        )
        if remember:
            await self._prefer(conflict, kept, by=by, now=now)
        return conflict

    async def dismiss(
        self, conflict_id: uuid.UUID, *, by: uuid.UUID, reason: str | None, now: datetime
    ) -> KnowledgeConflict | None:
        """No contradiction: the model goes on as resolution chose; an
        earlier decision's facts withdrawn."""
        conflict = await self._repository.conflict(conflict_id, for_update=True)
        if conflict is None:
            return None
        if conflict.status == "gone":
            raise DecisionRefusedError("not_open", "It is no longer disagreed on.")
        await self._assertions.remove_for(conflict.id)
        conflict.status = "dismissed"
        conflict.resolution = {
            "side": None,
            "value": None,
            "via": "person",
            "by": str(by),
            "at": now.isoformat(),
            "reason": reason[:REASON] if reason else None,
        }
        conflict.decided_values = sorted({canonical(s.get("value")) for s in conflict.sides})
        _remember(conflict, "dismissed", now=now, via="person", by=by, reason=reason)
        return conflict

    async def reopen(
        self, conflict_id: uuid.UUID, *, by: uuid.UUID, now: datetime
    ) -> tuple[KnowledgeConflict, bool] | None:
        """The decision withdrawn: open again, its facts gone — the model as
        before it at the next build. Whether facts were withdrawn, beside."""
        conflict = await self._repository.conflict(conflict_id, for_update=True)
        if conflict is None:
            return None
        if conflict.status not in ("resolved", "dismissed"):
            raise DecisionRefusedError("not_decided", f"This conflict is {conflict.status}.")
        withdrawn = await self._assertions.remove_for(conflict.id)
        conflict.status = "open"
        conflict.resolution = None
        conflict.decided_values = []
        _remember(conflict, "reopened", now=now, via="person", by=by)
        return conflict, withdrawn > 0

    async def _prefer(
        self, conflict: KnowledgeConflict, side: dict[str, object], *, by: uuid.UUID, now: datetime
    ) -> None:
        sources = side.get("sources")
        first = next(
            (
                s
                for s in (sources if isinstance(sources, list) else [])
                if isinstance(s, dict) and s.get("source_id")
            ),
            None,
        )
        if first is None:
            return
        await self.set_rule(
            about=conflict.about,
            source_id=uuid.UUID(str(first["source_id"])),
            stance="prefer",
            reason=f"Kept on {conflict.subject_name}'s {conflict.about}",
            by=by,
        )

    async def summary(self) -> ConflictSummary:
        counts = await self._repository.conflict_counts()
        return ConflictSummary(
            open=counts.get("open", 0),
            resolved=counts.get("resolved", 0),
            dismissed=counts.get("dismissed", 0),
            gone=counts.get("gone", 0),
        )

    # ── the workspace's word on its sources ──

    async def rules(self) -> list[AuthorityRuleRead]:
        return [
            _rule_read(rule, source) for rule, source in await self._repository.authority_rules()
        ]

    async def set_rule(
        self,
        *,
        about: str,
        source_id: uuid.UUID,
        stance: str,
        reason: str | None,
        by: uuid.UUID,
    ) -> AuthorityRule:
        """Prefer or avoid a source on something: said again, replaced."""
        if await self._repository.source(source_id) is None:
            raise DecisionRefusedError("gone", "No such source in this workspace.")
        rule = await self._repository.authority_rule(about=about, source_id=source_id)
        if rule is None:
            rule = AuthorityRule(
                workspace_id=self._repository.workspace_id, about=about, source_id=source_id
            )
            self._repository.add_rule(rule)
        rule.stance = stance
        rule.reason = reason[:REASON] if reason else None
        rule.created_by = by
        await self._repository.flush()
        return rule

    async def delete_rule(self, rule_id: uuid.UUID) -> bool:
        rule = await self._repository.authority_rule(rule_id=rule_id)
        if rule is None:
            return False
        await self._repository.delete_rule(rule)
        return True

    async def rule_read(self, rule: AuthorityRule) -> AuthorityRuleRead:
        return _rule_read(rule, await self._repository.source(rule.source_id))


def _facts(
    conflict: KnowledgeConflict, side: int, *, by: uuid.UUID, now: datetime
) -> list[Assertion]:
    """What makes the model show the side kept: for an attribute, its value
    over whatever a source says; for a relationship, the others refuted."""
    provenance: dict[str, object] = {
        "conflict_id": str(conflict.id),
        "decided_via": "person",
        "decided_by": str(by),
        "decided_at": now.isoformat(),
    }
    kept = conflict.sides[side]
    if conflict.kind == "attribute":
        return [
            Assertion(
                id=uuid.uuid5(conflict.id, "attribute"),
                kind="attribute",
                rule=RULE,
                confidence=1.0,
                entity_id=conflict.subject_id,
                attribute=conflict.about,
                value=kept.get("value"),
                overrides=True,
                evidence=f"kept among {len(conflict.sides)} values its sources say",
                provenance=provenance,
            )
        ]
    facts: list[Assertion] = []
    for index, other in enumerate(conflict.sides):
        if index == side:
            continue
        edges = other.get("edges")
        for edge in edges if isinstance(edges, list) else []:
            if not isinstance(edge, dict):
                continue
            start, end, kind = edge.get("from"), edge.get("to"), edge.get("type")
            if not (start and end and kind):
                continue
            facts.append(
                Assertion(
                    id=uuid.uuid5(conflict.id, f"{start}:{kind}:{end}"),
                    kind="absence",
                    rule=RULE,
                    confidence=1.0,
                    from_id=uuid.UUID(str(start)),
                    to_id=uuid.UUID(str(end)),
                    type=str(kind),
                    evidence=f"refuted: {kept.get('value')} kept as {conflict.about}",
                    provenance=provenance,
                )
            )
    return facts


def _rule_read(rule: AuthorityRule, source: object) -> AuthorityRuleRead:
    return AuthorityRuleRead(
        id=rule.id,
        about=rule.about,
        source_id=rule.source_id,
        source_name=getattr(source, "name", None),
        source_kind=getattr(getattr(source, "kind", None), "value", None),
        stance=rule.stance,
        reason=rule.reason,
        created_by=rule.created_by,
        created_at=rule.created_at,
    )


# ── reads ──────────────────────────────────────────────────────────────


def conflict_read(conflict: KnowledgeConflict) -> ConflictRead:
    return ConflictRead.model_validate(
        {
            "id": conflict.id,
            "kind": conflict.kind,
            "subject": {
                "type": "entity",
                "id": conflict.subject_id,
                "name": conflict.subject_name,
                "kind": conflict.subject_kind,
            },
            "about": conflict.about,
            "relationship": conflict.relationship,
            "chosen": conflict.chosen,
            "sides": conflict.sides,
            "recommendation": conflict.recommendation
            or {"side": None, "strength": "none", "reasons": [], "margin": 0.0},
            "statement": conflict.statement,
            "status": conflict.status,
            "resolution": conflict.resolution,
            "first_seen_at": conflict.first_seen_at,
            "last_seen_at": conflict.last_seen_at,
            "occurrences": conflict.occurrences,
        }
    )


def conflict_reads(conflicts: Sequence[KnowledgeConflict]) -> list[ConflictRead]:
    return [conflict_read(conflict) for conflict in conflicts]


def conflict_detail(conflict: KnowledgeConflict) -> ConflictDetail:
    return ConflictDetail(
        **conflict_read(conflict).model_dump(),
        provenance=conflict.provenance,
        history=list(conflict.history),
    )
