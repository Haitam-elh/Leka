"""What becomes of an enrichment LEKA proposes (LEKA-380): kept as a
candidate, decided, applied — or not.

    a run proposes  ──▶ candidate `proposed`        (seen again: updated;
                                                     no longer seen: withdrawn)
                    ──▶ `accepted` by the POLICY    when it is sure (0.9),
                                                     rules-made, and adds
                                                     without replacing
    a person        ──▶ accept  → `accepted`        the fact kept in
                                                     leka.knowledge; the
                                                     next build applies it
                    ──▶ reject  → `rejected`        never proposed again; an
                                                     accepted one withdrawn
                                                     from the model — the
                                                     next build undoes it
                    ──▶ reprocess                   back to its analysis:
                                                     proposed again if its
                                                     evidence holds,
                                                     withdrawn otherwise

TRUSTED INFORMATION is not overwritten without a controlled validation: a
candidate that would replace what a source says (`overrides`) is never
accepted by the policy, and a person accepts it only by saying so
(`override`). Withdrawn, the source's word comes back.

ROLLBACK is the model's own: a fact withdrawn is deleted from
model_assertions in the same transaction as the decision, and the next
build no longer applies it. A build that fails changes nothing — the
model is written in one transaction — and the sweep builds again.

Every decision is kept on the candidate (`history`): who, how, when, why.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from leka.intelligence.analysis import Analyzer, Evidence, Material, Method, Proposal, Subject
from leka.intelligence.models import EnrichmentCandidate
from leka.intelligence.repository import IntelligenceRepository
from leka.intelligence.schemas import (
    CandidateDetail,
    CandidateRead,
    EnrichmentSummary,
    EvidenceRead,
    SubjectRead,
)
from leka.knowledge import (
    RELATIONSHIP_KINDS,
    Assertion,
    AssertionRepository,
    EntityRepository,
    Lifecycle,
    RelationshipType,
)

# What the policy accepts without a person: sure, made by rules, adding.
POLICY_CONFIDENCE = 0.9
REASON = 500


class DecisionRefusedError(Exception):
    """A decision that cannot be taken, and why: `not_proposed` — decided
    already, or withdrawn; `override_required` — it replaces what a source
    says; `gone` — what it is about is no longer in the model; `invalid` —
    the relationship's contract does not take those ends; `accepted` — a
    candidate in the model is rejected before it is reprocessed."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def by_policy(analyzer: Analyzer, proposal: Proposal) -> bool:
    return (
        analyzer.method is Method.RULES
        and not proposal.overrides
        and proposal.confidence >= POLICY_CONFIDENCE
    )


def proposal_of(candidate: EnrichmentCandidate) -> Proposal:
    """A candidate still proposed, as the proposal it was: what an analysis
    a model helps with proposes again rather than ask the model twice
    (LEKA-394)."""

    def subject(kind: str | None, ident: uuid.UUID | None, name: str | None) -> Subject:
        return Subject(type="entity", id=ident, name=name or "", kind=kind)

    sources = candidate.provenance.get("sources") if candidate.provenance else None
    return Proposal(
        key=candidate.key,
        family=candidate.family,
        code=candidate.code,
        subject=subject(candidate.subject_kind, candidate.subject_id, candidate.subject_name),
        statement=candidate.statement,
        confidence=candidate.confidence,
        relationship=candidate.relationship,
        start=(
            subject(candidate.start_kind, candidate.start_id, candidate.start_name)
            if candidate.start_id
            else None
        ),
        end=(
            subject(candidate.end_kind, candidate.end_id, candidate.end_name)
            if candidate.end_id
            else None
        ),
        attribute=candidate.attribute,
        value=candidate.value,
        current=candidate.current,
        overrides=candidate.overrides,
        params=dict(candidate.params or {}),
        evidence=tuple(
            Evidence(
                kind=str(item.get("kind") or ""),
                id=str(item["id"]) if item.get("id") is not None else None,
                name=str(item.get("name") or ""),
                detail=str(item.get("detail") or ""),
            )
            for item in (candidate.evidence or [])
            if isinstance(item, dict)
        ),
        sources=tuple(str(s) for s in sources) if isinstance(sources, list) else (),
    )


def assertion_of(candidate: EnrichmentCandidate) -> Assertion:
    """The fact a candidate is, once accepted."""
    provenance: dict[str, object] = {
        "candidate_id": str(candidate.id),
        "analyzer": candidate.analyzer,
        "decided_via": candidate.decided_via,
        "decided_by": str(candidate.decided_by) if candidate.decided_by else None,
        "decided_at": candidate.decided_at.isoformat() if candidate.decided_at else None,
    }
    evidence = "; ".join(
        f"{item.get('name')}: {item.get('detail')}" for item in candidate.evidence[:3]
    )
    return Assertion(
        id=candidate.id,
        kind=candidate.kind,
        rule=f"enrichment.{candidate.analyzer}",
        confidence=candidate.confidence,
        entity_id=candidate.subject_id if candidate.kind == "attribute" else None,
        attribute=candidate.attribute,
        value=candidate.value,
        overrides=candidate.overrides,
        from_id=candidate.start_id,
        to_id=candidate.end_id,
        type=candidate.relationship,
        evidence=evidence[:1000],
        provenance=provenance,
    )


# ── what a run proposes ────────────────────────────────────────────────


async def propose(
    repository: IntelligenceRepository,
    assertions: AssertionRepository | None,
    run_id: uuid.UUID,
    analyzer: Analyzer,
    proposals: Sequence[Proposal],
    material: Material,
    *,
    now: datetime,
) -> dict[str, int]:
    """An analysis's proposals, kept: new ones proposed — or accepted by the
    policy — those seen again updated, those no longer seen withdrawn. A
    decision stands: what was accepted or rejected is only seen again."""
    kept = await repository.candidates_of(analyzer.name)
    counts = {"proposed": 0, "updated": 0, "withdrawn": 0, "by_policy": 0}
    said: set[str] = set()
    for proposal in proposals:
        said.add(proposal.key)
        candidate = kept.get(proposal.key)
        if candidate is None:
            candidate = EnrichmentCandidate(
                workspace_id=repository.workspace_id,
                analyzer=analyzer.name,
                key=proposal.key,
                status="proposed",
                first_seen_at=now,
                first_run_id=run_id,
                occurrences=0,
                history=[],
            )
            repository.add_candidate(candidate)
            counts["proposed"] += 1
        elif candidate.status == "withdrawn":
            candidate.status = "proposed"
            counts["proposed"] += 1
        else:
            counts["updated"] += 1
        if candidate.status in ("proposed",):
            _write(candidate, proposal, analyzer, material, run_id=run_id, now=now)
        else:
            candidate.last_seen_at = now
            candidate.last_run_id = run_id
            candidate.occurrences += 1
        if (
            candidate.status == "proposed"
            and assertions is not None
            and by_policy(analyzer, proposal)
        ):
            await repository.flush()
            _decide(candidate, "accepted", via="policy", by=None, reason=None, now=now)
            await assertions.put(assertion_of(candidate))
            counts["by_policy"] += 1
    for key, candidate in kept.items():
        if candidate.status == "proposed" and key not in said:
            candidate.status = "withdrawn"
            _remember(candidate, "withdrawn", via=None, by=None, reason=None, now=now)
            counts["withdrawn"] += 1
    return counts


def _write(
    candidate: EnrichmentCandidate,
    proposal: Proposal,
    analyzer: Analyzer,
    material: Material,
    *,
    run_id: uuid.UUID,
    now: datetime,
) -> None:
    """What a candidate proposes, as this run saw it."""
    candidate.analyzer_version = analyzer.version
    candidate.family = proposal.family
    candidate.code = proposal.code
    candidate.method = analyzer.method.value
    candidate.kind = proposal.kind
    candidate.subject_id = proposal.subject.id
    candidate.subject_name = proposal.subject.name[:500]
    candidate.subject_kind = proposal.subject.kind
    candidate.relationship = proposal.relationship
    candidate.start_id = proposal.start.id if proposal.start else None
    candidate.start_name = proposal.start.name[:500] if proposal.start else None
    candidate.start_kind = proposal.start.kind if proposal.start else None
    candidate.end_id = proposal.end.id if proposal.end else None
    candidate.end_name = proposal.end.name[:500] if proposal.end else None
    candidate.end_kind = proposal.end.kind if proposal.end else None
    candidate.attribute = proposal.attribute
    candidate.value = proposal.value
    candidate.current = proposal.current
    candidate.overrides = proposal.overrides
    candidate.statement = proposal.statement
    candidate.params = dict(proposal.params)
    candidate.confidence = round(max(0.0, min(proposal.confidence, 1.0)), 4)
    candidate.evidence = [item.as_dict() for item in proposal.evidence]
    candidate.provenance = {
        "analyzer": analyzer.name,
        "version": analyzer.version,
        "method": analyzer.method.value,
        "run_id": str(run_id),
        "model_built_at": material.built_at.isoformat() if material.built_at else None,
        "sources": list(proposal.sources),
    }
    candidate.last_seen_at = now
    candidate.last_run_id = run_id
    candidate.occurrences += 1


def _decide(
    candidate: EnrichmentCandidate,
    status: str,
    *,
    via: str,
    by: uuid.UUID | None,
    reason: str | None,
    now: datetime,
) -> None:
    candidate.status = status
    candidate.decided_via = via
    candidate.decided_by = by
    candidate.decided_at = now
    candidate.reason = reason[:REASON] if reason else None
    _remember(candidate, status, via=via, by=by, reason=reason, now=now)


def _remember(
    candidate: EnrichmentCandidate,
    status: str,
    *,
    via: str | None,
    by: uuid.UUID | None,
    reason: str | None,
    now: datetime,
) -> None:
    candidate.history = [
        *candidate.history,
        {
            "status": status,
            "via": via,
            "by": str(by) if by else None,
            "at": now.isoformat(),
            "reason": reason[:REASON] if reason else None,
        },
    ]


# ── decisions ──────────────────────────────────────────────────────────


class EnrichmentService:
    """The candidates of a workspace: read, accepted, rejected, sent back."""

    def __init__(
        self,
        repository: IntelligenceRepository,
        assertions: AssertionRepository,
        entities: EntityRepository,
    ) -> None:
        self._repository = repository
        self._assertions = assertions
        self._entities = entities

    async def accept(
        self,
        candidate_id: uuid.UUID,
        *,
        by: uuid.UUID,
        override: bool,
        reason: str | None,
        now: datetime,
    ) -> EnrichmentCandidate | None:
        """Validated by a person: the fact kept, applied by the next build."""
        candidate = await self._repository.candidate(candidate_id, for_update=True)
        if candidate is None:
            return None
        if candidate.status != "proposed":
            raise DecisionRefusedError("not_proposed", f"This candidate is {candidate.status}.")
        if candidate.overrides and not override:
            raise DecisionRefusedError(
                "override_required",
                "Accepting it replaces what a source says: say so with `override`.",
            )
        await self._still_holds(candidate)
        _decide(candidate, "accepted", via="person", by=by, reason=reason, now=now)
        await self._assertions.put(assertion_of(candidate))
        return candidate

    async def reject(
        self,
        candidate_id: uuid.UUID,
        *,
        by: uuid.UUID,
        reason: str | None,
        now: datetime,
    ) -> tuple[EnrichmentCandidate, bool] | None:
        """No: never proposed again — and, if it was accepted, withdrawn from
        the model. Whether it was in the model, beside it."""
        candidate = await self._repository.candidate(candidate_id, for_update=True)
        if candidate is None:
            return None
        if candidate.status not in ("proposed", "accepted"):
            raise DecisionRefusedError("not_proposed", f"This candidate is {candidate.status}.")
        applied = candidate.status == "accepted"
        if applied:
            await self._assertions.remove(candidate.id)
        _decide(candidate, "rejected", via="person", by=by, reason=reason, now=now)
        return candidate, applied

    async def reprocess(
        self, candidate_id: uuid.UUID, *, by: uuid.UUID, now: datetime
    ) -> EnrichmentCandidate | None:
        """Back to its analysis: a rejected or withdrawn candidate proposed
        again — the next run of its analysis keeps it if its evidence
        holds, withdraws it otherwise. One in the model is rejected first."""
        candidate = await self._repository.candidate(candidate_id, for_update=True)
        if candidate is None:
            return None
        if candidate.status == "accepted":
            raise DecisionRefusedError("accepted", "It is in the model: reject it first.")
        if candidate.status != "proposed":
            candidate.status = "proposed"
            candidate.decided_via = None
            candidate.decided_by = None
            candidate.decided_at = None
            candidate.reason = None
            _remember(candidate, "reprocessed", via="person", by=by, reason=None, now=now)
        return candidate

    async def _still_holds(self, candidate: EnrichmentCandidate) -> None:
        """What it is about is still in the model, and a relationship's
        contract takes its ends."""
        ends = (
            [candidate.start_id, candidate.end_id]
            if candidate.kind == "relationship"
            else [candidate.subject_id]
        )
        wanted = [end for end in ends if end is not None]
        found = await self._entities.by_ids(wanted)
        if len(wanted) != len(ends) or any(
            end not in found or found[end].lifecycle is Lifecycle.REMOVED for end in wanted
        ):
            raise DecisionRefusedError(
                "gone", "What it is about is no longer in the company model."
            )
        if candidate.kind != "relationship" or candidate.start_id is None:
            return
        try:
            contract = RELATIONSHIP_KINDS[RelationshipType(str(candidate.relationship))]
        except (KeyError, ValueError) as error:
            raise DecisionRefusedError("invalid", "LEKA has no such relationship.") from error
        start, end = found[candidate.start_id], found[wanted[-1]]
        if (contract.sources is not None and start.type not in contract.sources) or (
            contract.targets is not None and end.type not in contract.targets
        ):
            raise DecisionRefusedError("invalid", "This relationship cannot join these two things.")

    async def summary(self) -> EnrichmentSummary:
        counts: Counter[str] = Counter()
        families: Counter[str] = Counter()
        policy = 0
        for status, family, via, n in await self._repository.candidate_counts():
            counts[status] += n
            if status == "proposed":
                families[family] += n
            if status == "accepted" and via == "policy":
                policy += n
        return EnrichmentSummary(
            proposed=counts["proposed"],
            accepted=counts["accepted"],
            rejected=counts["rejected"],
            withdrawn=counts["withdrawn"],
            by_policy=policy,
            families=dict(sorted(families.items())),
        )


# ── reads ──────────────────────────────────────────────────────────────


def _thing(type_: str, id_: uuid.UUID | None, name: str | None, kind: str | None) -> SubjectRead:
    return SubjectRead.model_validate({"type": type_, "id": id_, "name": name or "", "kind": kind})


def candidate_read(candidate: EnrichmentCandidate) -> CandidateRead:
    return CandidateRead.model_validate(
        {
            "id": candidate.id,
            "analyzer": candidate.analyzer,
            "family": candidate.family,
            "code": candidate.code,
            "method": candidate.method,
            "kind": candidate.kind,
            "subject": _thing(
                "entity", candidate.subject_id, candidate.subject_name, candidate.subject_kind
            ),
            "relationship": candidate.relationship,
            "start": (
                _thing("entity", candidate.start_id, candidate.start_name, candidate.start_kind)
                if candidate.start_id
                else None
            ),
            "end": (
                _thing("entity", candidate.end_id, candidate.end_name, candidate.end_kind)
                if candidate.end_id
                else None
            ),
            "attribute": candidate.attribute,
            "value": candidate.value,
            "current": candidate.current,
            "overrides": candidate.overrides,
            "statement": candidate.statement,
            "params": candidate.params,
            "confidence": candidate.confidence,
            "status": candidate.status,
            "decided_via": candidate.decided_via,
            "decided_at": candidate.decided_at,
            "first_seen_at": candidate.first_seen_at,
            "last_seen_at": candidate.last_seen_at,
            "occurrences": candidate.occurrences,
        }
    )


def candidate_reads(candidates: Sequence[EnrichmentCandidate]) -> list[CandidateRead]:
    return [candidate_read(candidate) for candidate in candidates]


def candidate_detail(candidate: EnrichmentCandidate) -> CandidateDetail:
    return CandidateDetail(
        **candidate_read(candidate).model_dump(),
        evidence=[EvidenceRead.model_validate(item) for item in candidate.evidence],
        provenance=candidate.provenance,
        decided_by=candidate.decided_by,
        reason=candidate.reason,
        history=list(candidate.history),
    )
