"""What becomes of a quality score (LEKA-381): kept as it stands, and its
changes over time.

    a run measures it    ──▶ quality_scores   rewritten: its score, level,
                                              dimensions, factors, what
                                              lowers it, where it was read
                         ──▶ quality_history  a point when first measured,
                                              and each time it moves — by
                                              MOVED or more, or to another
                                              level
    no longer measured   ──▶ forgotten as it stands; its history stays

A step that failed writes nothing: the scores stand as the last run left
them. The history is kept HISTORY_DAYS (the sweep).

Read by the API (`GET /intelligence/quality…`) and, in code, by what builds
on LEKA's knowledge (`QualityService.of`): how far to trust what it knows
of the things it looks at.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from leka.intelligence.analysis import Analyzer, Material, QualityScore
from leka.intelligence.models import QualityPoint, QualityScoreRow
from leka.intelligence.repository import QualityRepository
from leka.intelligence.schemas import (
    KnowledgeQualityDetail,
    KnowledgeQualityPoint,
    KnowledgeQualityRead,
    KnowledgeQualitySummary,
    SubjectRead,
)

# A score that moves by this much, or changes level, is a point of its history.
MOVED = 0.02
HISTORY_DAYS = 365
# What a summary names, how far back its trend goes, what its change is to.
WEAKEST = 5
TREND = timedelta(days=30)
CHANGE = timedelta(days=7)
DETAIL_HISTORY = timedelta(days=90)
DIMENSIONS = ("completeness", "freshness", "consistency", "confidence")


async def record_scores(
    repository: QualityRepository,
    run_id: uuid.UUID,
    analyzer: Analyzer,
    scores: Sequence[QualityScore],
    material: Material,
    *,
    now: datetime,
) -> dict[str, int]:
    """A run's scores kept: each rewritten as it stands, a point of history
    when it moved, those no longer measured forgotten."""
    kept = await repository.current()
    counts = {"measured": 0, "moved": 0, "unmeasured": 0}
    said: set[str] = set()
    for score in scores:
        said.add(score.key)
        row = kept.get(score.key)
        moved = row is None or abs(row.score - score.score) >= MOVED or row.level != score.level
        if row is None:
            row = QualityScoreRow(workspace_id=repository.workspace_id, key=score.key, since=now)
            repository.add(row)
        elif row.level != score.level:
            row.since = now
        _write(row, score, analyzer, material, run_id=run_id, now=now)
        counts["measured"] += 1
        if moved:
            repository.add_point(_point(score, repository.workspace_id, run_id=run_id, now=now))
            counts["moved"] += 1
    gone = [row for key, row in kept.items() if key not in said]
    await repository.forget(gone)
    counts["unmeasured"] = len(gone)
    return counts


def _write(
    row: QualityScoreRow,
    score: QualityScore,
    analyzer: Analyzer,
    material: Material,
    *,
    run_id: uuid.UUID,
    now: datetime,
) -> None:
    row.scope = score.scope
    row.subject_id = score.subject.id
    row.subject_name = score.subject.name[:500]
    row.subject_kind = score.subject.kind
    row.column = score.column
    row.score = _unit(score.score) or 0.0
    row.level = score.level
    for name in DIMENSIONS:
        setattr(row, name, _unit(score.dimensions.get(name)))
    row.factors = dict(score.factors)
    row.missing = [dict(item) for item in score.missing]
    row.areas = list(score.areas)
    row.entities = score.entities
    row.capped = score.capped
    row.provenance = {
        "analyzer": analyzer.name,
        "version": analyzer.version,
        "run_id": str(run_id),
        "model_built_at": material.built_at.isoformat() if material.built_at else None,
        "sources": list(score.sources),
        # Whether consistency read the conflicts (LEKA-382), or only the
        # model's provenance.
        "conflicts": material.disputes is not None,
    }
    row.measured_at = now
    row.run_id = run_id


def _point(
    score: QualityScore, workspace_id: uuid.UUID, *, run_id: uuid.UUID, now: datetime
) -> QualityPoint:
    return QualityPoint(
        workspace_id=workspace_id,
        key=score.key,
        scope=score.scope,
        subject_id=score.subject.id,
        score=_unit(score.score) or 0.0,
        level=score.level,
        measured_at=now,
        run_id=run_id,
        **{name: _unit(score.dimensions.get(name)) for name in DIMENSIONS},
    )


def _unit(value: float | None) -> float | None:
    return None if value is None else round(max(0.0, min(float(value), 1.0)), 4)


# ── reads ──────────────────────────────────────────────────────────────


def quality_read(row: QualityScoreRow) -> KnowledgeQualityRead:
    return KnowledgeQualityRead.model_validate(
        {
            "key": row.key,
            "scope": row.scope,
            "subject": SubjectRead(
                type=_subject_type(row.scope),
                id=row.subject_id,
                name=row.subject_name,
                kind=row.subject_kind,
            ),
            "column": row.column,
            "score": row.score,
            "level": row.level,
            **{name: getattr(row, name) for name in DIMENSIONS},
            "missing": row.missing,
            "areas": row.areas,
            "entities": row.entities,
            "capped": row.capped,
            "measured_at": row.measured_at,
            "since": row.since,
        }
    )


def quality_reads(rows: Sequence[QualityScoreRow]) -> list[KnowledgeQualityRead]:
    return [quality_read(row) for row in rows]


def _subject_type(scope: str) -> str:
    return scope if scope in ("column", "workspace") else "entity"


class QualityService:
    def __init__(self, repository: QualityRepository) -> None:
        self._repository = repository

    async def summary(self, *, now: datetime) -> KnowledgeQualitySummary:
        areas = await self._repository.areas()
        workspace = next((row for row in areas if row.scope == "workspace"), None)
        trend = await self._repository.history("workspace", since=now - TREND) if workspace else []
        then = [point for point in trend if point.measured_at <= now - CHANGE]
        counted = await self._repository.levels()
        return KnowledgeQualitySummary(
            measured_at=workspace.measured_at if workspace else None,
            workspace=quality_read(workspace) if workspace else None,
            levels={level: counted.get(level, 0) for level in ("high", "medium", "low")},
            columns=quality_reads([row for row in areas if row.scope == "column"]),
            teams=quality_reads([row for row in areas if row.scope == "team"]),
            applications=quality_reads([row for row in areas if row.scope == "application"]),
            weakest=quality_reads(await self._repository.weakest(WEAKEST)),
            trend=[KnowledgeQualityPoint.model_validate(point) for point in trend],
            change=(round(workspace.score - then[-1].score, 4) if workspace and then else None),
        )

    async def detail(self, key: str, *, now: datetime) -> KnowledgeQualityDetail | None:
        row = await self._repository.score(key)
        if row is None:
            return None
        history = await self._repository.history(key, since=now - DETAIL_HISTORY)
        return KnowledgeQualityDetail(
            **quality_read(row).model_dump(),
            factors=row.factors,
            provenance=row.provenance,
            history=[KnowledgeQualityPoint.model_validate(point) for point in history],
        )

    async def of(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, KnowledgeQualityRead]:
        """How far what LEKA knows of these things can be trusted — for what
        builds on it (an intention) to say likely rather than certain."""
        return {
            row.subject_id: quality_read(row)
            for row in await self._repository.of_subjects(ids)
            if row.subject_id is not None
        }
