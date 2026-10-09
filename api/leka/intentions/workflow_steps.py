"""LEKA's own analyses as workflow steps (LEKA-397): one capability of the
analysis (LEKA-388) run on the workflow's intention — its understanding, its
context, the parts it reads — as the analysis runs it, isolated. What it
found becomes the step's: its codes, which a later step's condition reads.

Registered with the capabilities' workflow engine when this module is
imported, as the analyses are provided to the catalogue: capabilities sits
below intentions and never imports it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from leka.capabilities import Kind, StepCall, StepResult, register_step
from leka.db import session_factory
from leka.intentions.analysis import execute
from leka.intentions.capabilities import capability_named
from leka.intentions.grounding import side
from leka.intentions.processing import _context, _material, asked_of
from leka.intentions.repository import IntentionRepository
from leka.intentions.schemas import ContextReadiness, Understanding

# Failures trying again cannot mend.
FINAL = frozenset({"no_capability", "needs_intention", "gone", "no_material"})


async def rules_step(call: StepCall) -> StepResult:
    capability = capability_named(call.capability.key)
    if capability is None or capability.run is None:
        return StepResult("failed", error="no_capability", retryable=False)
    if call.intention_id is None:
        return StepResult("failed", error="needs_intention", retryable=False)
    now = datetime.now(UTC)
    async with session_factory() as session:
        intention = await IntentionRepository(session, call.workspace_id).intention(
            call.intention_id
        )
        if intention is None:
            return StepResult("failed", error="gone", retryable=False)
        understood = (
            Understanding.model_validate(intention.understanding)
            if intention.understanding
            else None
        )
        ready = (
            ContextReadiness.model_validate(intention.readiness) if intention.readiness else None
        )
        asked = asked_of(intention, understood, now)
        context_id = intention.context_id
    context = await _context(
        call.workspace_id, context_id, ready.version if ready is not None else None
    )
    material = await _material(call.workspace_id, asked, context, capability.reads, ready, now)
    done = await execute(capability, material.on(capability.sides, side))
    if done.status != "succeeded" or done.output is None:
        error = done.reason or done.error or done.status
        return StepResult(
            "failed",
            error=error[:60],
            output={"duration_ms": done.duration_ms},
            retryable=error not in FINAL and done.reason != "no_material",
        )
    out = done.output
    codes = tuple(dict.fromkeys(f.code for f in out.findings))
    return StepResult(
        "succeeded",
        codes=codes,
        summary=out.summary.text if out.summary is not None else None,
        output={
            "findings": len(out.findings),
            "causes": len(out.causes),
            "confidence": out.confidence,
            "duration_ms": done.duration_ms,
        },
    )


register_step(Kind.RULES, rules_step)
