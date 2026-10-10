"""LEKA's analyst: an intention answered by a language model that knows
what LEKA is, reads what the question needs through LEKA's own reads — its
skills, to read, never to act — and answers as a senior colleague would,
every point resting on something it read.

    the question as understood, what LEKA's rules found (analysis.py), the
    context assembled for it, the sources LEKA reads
            │
            ▼
    the model, told what LEKA is and how it knows what it knows, given
    LEKA's reads as tools (skills.py, LEKA-396):
        find           things by name or words
        describe       one thing: what it is, its state, owners, ties, sources
        dependencies   what it depends on, what depends on it
        happened       what happened in a period — deployments, merges,
                       releases, changes, incidents — everywhere, in one
                       environment, or around one thing
        incident       one incident: what it reached, what caused it
        learned        what LEKA's model gained, changed, lost in a period
        sources        what LEKA reads, and when it last read it
        insights       what LEKA already concluded and is still open
        overview       what the model holds: how many of each kind
    each call through the skill runtime: what the model asks checked against
    what the read takes, with what the person who asked may read, the
    database holding it read only — and kept, about the intention
            │  a few rounds at most; the last one must answer
            ▼
    its answer, checked: each point cites what a read returned, what the
    rules found, or the context — a point citing nothing is dropped; an
    answer resting on nothing, when there was something to rest on, is not
    kept. What it cites becomes the analysis's evidence (Preuves).

Through the LLM runtime (LEKA-429): the workspace's model, routed, every
call kept, its cost said. Read only: a tool that would change anything
cannot be given to a model (RuntimeTool). The rules stay the analysis's
skeleton — its risk, its recommendations; the analyst is its intelligence.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from leka.capabilities import (
    Cited,
    ContextPack,
    Execution,
    LLMRuntime,
    Needs,
    RuntimeTool,
    SkillRuntime,
    Task,
    Tier,
)
from leka.intelligence import LIBRARY
from leka.intentions.analysis import Answer, Asked, Evidence, Point, Result, SourceRef
from leka.intentions.skills import READS
from leka.intentions.writing import Written, known_ids, material

# What the analyst asks of a model: tools, a structured answer, good analysis.
NEEDS = Needs(structured=True, tools=True, quality=2)
# Seconds for all of it; rounds of tools at most, the last one answering.
BUDGET = 120.0
ROUNDS = 6
# Room for its thinking and its answer: Gemini counts both.
MOST_TOKENS = 8000
# Where LEKA's customers are, until a workspace says its own zone.
TIMEZONE = "Europe/Paris"
# The context it is given to start from: the best of it, not all.
CONTEXT_CHARACTERS = 8000

PLATFORM = """You are LEKA's analyst. LEKA is a platform an IT department \
connects to its tools — GitHub or GitLab, its cloud (AWS, Azure, Google \
Cloud), its databases, its documentation (Confluence, Notion…), its ticketing \
and incident tools (Jira, PagerDuty…), its monitoring — and that reads them \
continuously to keep a living model of the company's systems:

- THINGS: services, applications, code repositories, databases, schemas and \
tables, infrastructure resources, cloud accounts, environments (production, \
staging…), teams, people, documents, business capabilities and processes.
- EVENTS: deployments, merged pull requests, releases, change requests, \
incidents — each dated, often tied to what it touched.
- RELATIONSHIPS: depends_on, part_of, deployed_to, runs_on, owns, \
maintains, documents, affects, caused_by…
- Every fact has its sources and a confidence: STATED by a source, or \
INFERRED by LEKA's rules. A state (up, down, degraded) is measured only when \
a monitoring tool is connected; otherwise it is read from a resource or \
deduced — say so, never present it as measured.

You answer a person of that company who asked LEKA a question. Work like a \
senior engineer who knows their systems:
1. Understand what is really asked, and over which period and environment.
2. Read what answers it with your tools — what changed, what happened, what \
depends on what, who owns what, what LEKA already concluded. Start from \
what you are given (what LEKA's rules already found, the context); fetch \
what is missing. A few precise calls, not every tool. When the question \
asks for an assessment — how a team ships, what a failure would reach, \
what to test, what is exposed, what is documented, a change reviewed — \
the skill that computes it answers better than reads put together: use it, \
and rest on the signals it gives.
3. Cross-check: a deployment just before an incident on the same thing is a \
probable cause, not a proven one.
4. Answer.

How you answer:
- The answer first, in its first sentence, plainly — then the specifics: \
names, versions, counts, dates and hours in the asker's time zone \
(« hier à 15h57 »), who or what is involved, what followed.
- Facts and inferences apart: what a source states is a fact; what you \
conclude is said as likely, with why.
- When nothing is found, say exactly what you checked — which sources, \
which period, when they were last read — so « nothing changed » can be \
trusted; and what LEKA cannot see (no monitoring connected, a source in \
error, a source never read).
- Never invent: no name, date, figure, owner or cause that your tools, the \
rules or the context did not give you.
- No internal words: say « LEKA », never « entity », « context element », \
« company model », « finding id ».
- In the language of the question (French when asked in French), in the \
tone of a colleague: precise, brief, no filler. Two to six sentences of \
answer, then at most eight points.
- Each point cites the ids it rests on, exactly as given by your tools, the \
rules or the context (« event:… », « entity:… », « finding:… », \
« source:… », « context:… », or a rule's finding id). A point you cannot \
cite is not written.
- You never act on the company's systems and never tell anyone to run \
something in production: a person decides, through LEKA."""


# ── what it read ─────────────────────────────────────────────────────────────


def evidence_of(cited: Cited) -> Evidence:
    """Something a skill read, as the analysis keeps it."""
    return Evidence(
        id=cited.id,
        kind=cited.kind,
        label=cited.label,
        ref_type=cited.ref_type,
        ref_id=cited.ref_id,
        sources=tuple(SourceRef(s.id, s.kind, s.name) for s in cited.sources),
        origin=cited.origin,
        detail=cited.detail,
        at=cited.at,
        params=dict(cited.params),
    )


class Reading:
    """What the analyst read, by the id it may cite: every thing, event,
    source or conclusion a skill returned — the evidence its answer rests on
    when it cites it."""

    def __init__(self) -> None:
        self.read: dict[str, Evidence] = {}

    def keep(self, cited: Sequence[Cited]) -> None:
        for item in cited:
            self.read.setdefault(item.id, evidence_of(item))


LIBRARY_KEYS = tuple(skill.key for skill in LIBRARY)
# What it may call: LEKA's reads, then its skill library (LEKA-401) — the
# assessments an expert of each domain would make.
ANALYST_SKILLS = (*READS, *LIBRARY_KEYS)


def tools(skills: SkillRuntime, asked: Asked, reading: Reading) -> list[RuntimeTool]:
    """LEKA's reads and its library (skills.py, intelligence/library.py), as
    the model may call them — each run through the skill runtime: checked,
    read only, kept. What the question already says, the model may leave
    out: its period, its environment."""
    period: dict[str, object] = {"since": asked.since, "until": asked.until}
    where: dict[str, object] = {"environment": asked.environment}
    fills: dict[str, dict[str, object]] = {
        "happened": period,
        "learned": period,
        "dependencies": where,
        "delivery-metrics": where,
        "test-scope": where,
        "security-posture": where,
        "infrastructure-inventory": where,
    }
    return [skills.tool(key, fill=fills.get(key), cited=reading.keep) for key in ANALYST_SKILLS]


# ── what it is given, what it gives back ─────────────────────────────────────


def given(asked: Asked, result: Result, now: datetime, watched: object) -> dict[str, Any]:
    """What the analyst starts from: what LEKA's rules found, in the shape
    the synthesis has always been given (writing.material) — and when it is,
    in which zone, what LEKA reads."""
    zone = ZoneInfo(TIMEZONE)
    said = material(asked, result)
    for end in ("since", "until"):
        moment = getattr(asked, end)
        said["period"][end] = (
            moment.astimezone(zone).isoformat(timespec="minutes") if moment else None
        )
    return {
        "now": now.astimezone(zone).isoformat(timespec="minutes"),
        "time_zone": TIMEZONE,
        **said,
        "understood": {"mode": asked.mode, "kind": asked.kind, "acting": asked.acting},
        "environment": asked.environment,
        "about": [{"id": f"entity:{s.id}", "name": s.name, "type": s.type} for s in asked.subjects],
        "summary": [n.text for n in result.summary],
        "sources": watched,
    }


def grounded(written: Written, known: frozenset[str]) -> tuple[tuple[Point, ...], frozenset[str]]:
    """The points that cite what it read or was given, and every id they
    cite."""
    points = tuple(
        Point(text=p.text.strip(), cites=cites)
        for p in written.points
        if p.text.strip() and (cites := tuple(dict.fromkeys(c for c in p.cites if c in known)))
    )
    return points, frozenset(c for p in points for c in p.cites)


async def answer(
    runtime: LLMRuntime,
    skills: SkillRuntime,
    asked: Asked,
    result: Result,
    context: ContextPack,
    *,
    now: datetime,
) -> tuple[Execution, Answer | None, tuple[Evidence, ...]]:
    """The question answered by LEKA's analyst, through the runtime with
    LEKA's reads: its answer and the evidence it cites — none, said why,
    when no model gave one it could keep."""
    reading = Reading()
    watched = await skills.run("sources", {})
    reading.keep(watched.cited)
    pack = ContextPack.of(context.items, ref=context.ref, characters=CONTEXT_CHARACTERS)

    def known() -> frozenset[str]:
        return known_ids(result, pack) | frozenset(reading.read)

    def check(written: Any, _given: ContextPack) -> list[str]:
        if not isinstance(written, Written) or not written.answer.strip():
            return ["no answer"]
        points, _ = grounded(written, known())
        held = bool(result.findings or result.causes or reading.read)
        return [] if points or not held else ["it cites nothing it read or was given"]

    done = await runtime.run(
        Task(
            purpose="capability.synthesis",
            instructions=PLATFORM,
            input=given(asked, result, now, watched.said()),
            context=pack,
            output=Written,
            check=check,
            needs=NEEDS,
            tier=Tier.FAST,
            max_tokens=MOST_TOKENS,
            budget=BUDGET,
            tools=tools(skills, asked, reading),
            rounds=ROUNDS,
            conclude=True,
            ref=f"intention:{asked.id}",
        )
    )
    if not done.ok:
        return done, None, ()
    written: Written = done.value
    points, cited = grounded(written, known())
    evidence = tuple(reading.read[c] for c in cited if c in reading.read)
    return (
        done,
        Answer(
            text=written.answer.strip(),
            points=points,
            caveats=tuple(c.strip() for c in written.caveats if c.strip()),
            provider=done.provider or "",
            model=done.model or "",
            version=done.version or "",
        ),
        evidence,
    )
