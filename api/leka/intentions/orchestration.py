"""Capability orchestration (LEKA-399): the capabilities one intention calls
for, planned as one graph and run as one.

    plan()      the capabilities chosen for it (analysis.select), as a graph:
                each with what must have succeeded before it (`after`) and
                what it reads when it did (`uses`) — in levels: each level
                after the one before, its capabilities together, in
                parallel. One that a model runs reads all the others: it is
                last. A capability named that was not chosen is no
                prerequisite; a cycle is refused (OrchestrationError).
    run()       level by level, each capability isolated (analysis.execute),
                handed what the capabilities it names produced — those only,
                frozen, as they produced them (`Material.handed`):
                    a prerequisite (`after`) did not succeed     skipped,
                                                                 `upstream`
                    something it uses did not succeed            run with the
                                                                 rest, said
                                                                 `degraded`
                    it failed, and it has a `fallback`           its fallback
                                                                 run in its
                                                                 place, said
    the record  the plan — its levels, each step's prerequisites and uses —
                and each step: its level, when it started (ms after the
                analysis did), how long, what it was handed, what it ran
                without, how it ended and why — kept with the analysis
                (`IntentionAnalysis.detail["orchestration"]`, `steps`).

The conclusion is the plan's last level: the result assembled from every
capability's output, what LEKA recommends (LEKA-389), and the answer of
LEKA's analyst (analyst.py), who reads them all — run by processing.py.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from leka.intentions.analysis import Capability, Material, Output, StepOutcome, execute


class OrchestrationError(ValueError):
    """The capabilities cannot be ordered: they wait on one another."""


@dataclass(frozen=True)
class Step:
    """One capability in the plan: where it stands, what it waits on."""

    name: str
    version: int
    method: str
    level: int
    # What must have succeeded before it; what it reads when it did.
    after: tuple[str, ...] = ()
    uses: tuple[str, ...] = ()
    fallback: str | None = None


@dataclass(frozen=True)
class Plan:
    """The capabilities of one analysis, ordered."""

    steps: tuple[Step, ...]

    @property
    def levels(self) -> tuple[tuple[str, ...], ...]:
        """The steps by level: each after the one before, its own together."""
        deepest = max((s.level for s in self.steps), default=-1)
        return tuple(tuple(s.name for s in self.steps if s.level == n) for n in range(deepest + 1))

    def step(self, name: str) -> Step:
        return next(s for s in self.steps if s.name == name)

    def said(self) -> dict[str, object]:
        """As it is kept with the analysis."""
        return {
            "levels": [list(level) for level in self.levels],
            "steps": {
                s.name: {
                    "level": s.level,
                    "method": s.method,
                    "after": list(s.after),
                    "uses": list(s.uses),
                    "fallback": s.fallback,
                }
                for s in self.steps
            },
        }


def plan(capabilities: Sequence[Capability]) -> Plan:
    """The capabilities as a graph, in levels — each one's level the longest
    way to it. One a model runs reads all the others."""
    chosen = {c.name: c for c in capabilities}
    waits: dict[str, frozenset[str]] = {}
    for capability in capabilities:
        others = frozenset(chosen) - {capability.name}
        read = others if capability.method == "model" else capability.uses & others
        waits[capability.name] = (capability.after & others) | read
    level: dict[str, int] = {}
    while len(level) < len(chosen):
        ready = sorted(
            name for name, before in waits.items() if name not in level and before <= set(level)
        )
        if not ready:
            stuck = sorted(name for name in chosen if name not in level)
            msg = f"These capabilities wait on one another: {', '.join(stuck)}."
            raise OrchestrationError(msg)
        for name in ready:
            level[name] = 1 + max((level[b] for b in waits[name]), default=-1)
    order = {c.name: i for i, c in enumerate(capabilities)}
    return Plan(
        steps=tuple(
            Step(
                name=c.name,
                version=c.version,
                method=c.method,
                level=level[c.name],
                after=tuple(sorted(c.after & set(chosen))),
                uses=tuple(sorted(waits[c.name] - c.after)),
                fallback=c.fallback,
            )
            for c in sorted(capabilities, key=lambda c: (level[c.name], order[c.name]))
        )
    )


Runner = Callable[[Capability, Material], Awaitable[StepOutcome]]


def _since(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


async def run(
    the_plan: Plan,
    capabilities: Mapping[str, Capability],
    material: Material,
    *,
    side: Callable[[str], str],
    started: float,
    runner: Runner = execute,
    fallbacks: Mapping[str, Capability] | None = None,
) -> list[StepOutcome]:
    """The plan's rules, level by level — a level's capabilities together.
    What a model runs (the conclusion) is left to the caller: it reads the
    result assembled from these."""
    done: dict[str, StepOutcome] = {}

    async def one(name: str) -> tuple[list[StepOutcome], StepOutcome]:
        """What is kept of one step, and what those after it read."""
        step = the_plan.step(name)
        capability = capabilities[name]
        missing = [a for a in step.after if done.get(a) is None or done[a].status != "succeeded"]
        at = _since(started)
        if missing:
            skipped = StepOutcome(
                name,
                capability.version,
                "skipped",
                reason="upstream",
                error=", ".join(missing),
                level=step.level,
                started_ms=at,
            )
            return [skipped], skipped
        handed: dict[str, Output] = {}
        for other in (*step.after, *step.uses):
            outcome = done.get(other)
            if outcome is not None and outcome.status == "succeeded" and outcome.output:
                handed[other] = outcome.output
        without = tuple(u for u in step.uses if u not in handed)
        given = replace(material.on(capability.sides, side), handed=handed)
        names = tuple(sorted(handed))

        def placed(found: StepOutcome, *, instead_of: str | None = None) -> StepOutcome:
            return replace(
                found,
                level=step.level,
                handed=names,
                degraded=without,
                started_ms=at,
                fallback_of=instead_of,
            )

        outcome = placed(await runner(capability, given))
        fallback = (fallbacks or {}).get(step.fallback or "")
        if outcome.status in ("failed", "timed_out") and fallback is not None:
            # In its place, said so: what it was to say, said another way —
            # and what follows reads that.
            instead = placed(await runner(fallback, given), instead_of=name)
            return [outcome, instead], instead if instead.status == "succeeded" else outcome
        return [outcome], outcome

    outcomes: list[StepOutcome] = []
    for level in the_plan.levels:
        rules = [n for n in level if capabilities[n].method == "rules"]
        for name, (kept, read) in zip(
            rules, await asyncio.gather(*(one(n) for n in rules)), strict=True
        ):
            outcomes.extend(kept)
            done[name] = read
    return outcomes
