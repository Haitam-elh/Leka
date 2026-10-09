"""The analysis, answered in words (LEKA-394): the « synthesis » capability
— written by a language model, through the gateway, from what LEKA's rules
found, and from nothing else.

    the result (assemble())  ──▶  the question, what the rules found — facts,
                                  causes, what it reaches, what is unknown —
                                  each with its id, and the evidence
                             ──▶  the model, asked for a short answer in the
                                  asker's language and the points it rests
                                  on, each citing ids
                             ──▶  checked: a point citing nothing the result
                                  holds is dropped; an answer resting on
                                  nothing, when there was something, is not
                                  kept

Through the LLM runtime (LEKA-429): the context the Context Engine assembled
for the intention goes with it — its elements, what an answer may also
cite — and the answer is checked before it is used.

The rules stay what the analysis is: its status, its confidence, its
evidence are theirs. The answer only says it — and says who wrote it. No
model, or none answering: no answer, said, and the analysis is what it was.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from leka.capabilities import ContextPack, Execution, LLMRuntime, Needs, Task, Tier
from leka.intentions.analysis import Answer, Asked, Point, Result

# What the synthesis asks of a model: a structured answer, good analysis.
NEEDS = Needs(structured=True, quality=2)
# How long an analysis waits for its answer, at most.
BUDGET = 60.0
# What is sent, at most: the result's best, not all of a large one.
MOST = {"findings": 40, "causes": 15, "evidence": 60, "notes": 15}
LONGEST = 400

SYSTEM = """You are LEKA, the assistant of an IT department. You answer a \
question asked about the company's systems, using ONLY the analysis given \
(the task: its findings — facts — its probable causes, what it reaches, \
what is uncertain or missing, the evidence behind them) and the LEKA context \
it was made from.

Rules:
- Never state anything the analysis does not hold: no name, date, figure, \
cause or owner of your own. If the analysis does not answer, say what is \
missing to answer it.
- A probable cause is said as probable, with its confidence.
- Each point cites the ids (findings, causes, evidence, context elements) \
it rests on, as given. A point you cannot cite is not written.
- Answer in the language of the question. Be brief: the answer in two to \
five sentences, at most six points, each one sentence.
- Never recommend doing something to production systems: people decide."""


class WrittenPoint(BaseModel):
    text: str = Field(max_length=800)
    cites: list[str] = Field(max_length=12)


class Written(BaseModel):
    """What the model is asked to give back."""

    answer: str = Field(max_length=3000)
    points: list[WrittenPoint] = Field(max_length=10)
    caveats: list[str] = Field(default_factory=list, max_length=5)


def _cut(text: str | None) -> str | None:
    if text is None:
        return None
    return text if len(text) <= LONGEST else text[: LONGEST - 1] + "…"


def material(asked: Asked, result: Result) -> dict[str, Any]:
    """What the model reads: the question and the result, ids kept."""
    return {
        "question": asked.text,
        "goal": asked.goal,
        "about": [{"name": s.name, "type": s.type} for s in asked.subjects],
        "period": {
            "since": asked.since.isoformat() if asked.since else None,
            "until": asked.until.isoformat() if asked.until else None,
        },
        "status": result.status,
        "confidence": result.confidence,
        "risk": result.risk,
        "findings": [
            {"id": s.id, "text": _cut(s.text), "evidence": list(s.evidence)}
            for _, s in result.findings[: MOST["findings"]]
        ],
        "causes": [
            {
                "id": c.id,
                "label": _cut(c.label),
                "why": _cut(c.why),
                "basis": c.basis,
                "confidence": c.confidence,
                "evidence": list(c.evidence),
            }
            for _, c in result.causes[: MOST["causes"]]
        ],
        "reaches": [
            {"kind": area.code, "things": [item.name for item in area.items[:10]]}
            for area in result.impact
        ],
        "uncertain": [_cut(n.text) for n in result.uncertainties[: MOST["notes"]]],
        "missing": [_cut(n.text) for n in result.missing[: MOST["notes"]]],
        "evidence": [
            {
                "id": e.id,
                "kind": e.kind,
                "label": _cut(e.label),
                "detail": _cut(e.detail),
                "at": e.at.isoformat() if e.at else None,
                "sources": [s.kind or s.name for s in e.sources if s.kind or s.name],
            }
            for e in result.evidence[: MOST["evidence"]]
        ],
    }


def known_ids(result: Result, context: ContextPack) -> frozenset[str]:
    """What an answer may cite: the result's findings, causes, evidence —
    and the context's elements."""
    return frozenset(
        {s.id for _, s in result.findings}
        | {c.id for _, c in result.causes}
        | {e.id for e in result.evidence}
        | context.ids
    )


def grounded(
    written: Written, result: Result, context: ContextPack = ContextPack()
) -> tuple[tuple[Point, ...], bool]:
    """The points that cite what the result or its context holds — and
    whether the answer rests on anything, when the result held something to
    rest on."""
    known = known_ids(result, context)
    points = tuple(
        Point(text=p.text.strip(), cites=cites)
        for p in written.points
        if p.text.strip() and (cites := tuple(dict.fromkeys(c for c in p.cites if c in known)))
    )
    held = bool(result.findings or result.causes)
    return points, bool(points) or not held


def task_of(asked: Asked, result: Result, context: ContextPack) -> Task:
    """The synthesis, as the LLM runtime is given it: the analysis to say,
    the context it was made from to rest on, the shape — and the check that
    it rests on what they hold."""

    def check(written: Any, given: ContextPack) -> list[str]:
        if not isinstance(written, Written) or not written.answer.strip():
            return ["no answer"]
        _, rests = grounded(written, result, given)
        return [] if rests else ["it cites nothing the analysis or its context holds"]

    return Task(
        purpose="capability.synthesis",
        instructions=SYSTEM,
        input=material(asked, result),
        context=context,
        output=Written,
        check=check,
        needs=NEEDS,
        # Little thinking — the rules did the analysis — and room for it:
        # Gemini counts its thinking in the tokens it may write, and an
        # answer cut short is no answer, paid for.
        tier=Tier.FAST,
        max_tokens=6000,
        budget=BUDGET,
        ref=f"intention:{asked.id}",
    )


async def write(
    runtime: LLMRuntime,
    asked: Asked,
    result: Result,
    context: ContextPack = ContextPack(),
) -> tuple[Execution, Answer | None]:
    """The answer, written and checked by the runtime — none, said why, when
    no model wrote one it could keep."""
    done = await runtime.run(task_of(asked, result, context))
    if not done.ok:
        return done, None
    written: Written = done.value
    points, _ = grounded(written, result, context)
    return done, Answer(
        text=written.answer.strip(),
        points=points,
        caveats=tuple(c.strip() for c in written.caveats if c.strip()),
        provider=done.provider or "",
        model=done.model or "",
        version=done.version or "",
    )
