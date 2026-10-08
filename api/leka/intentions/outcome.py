"""What came of it (LEKA-392), pure: what was expected before it ran, what
is observed after, and the verdict — met, partly, or not.

    planned ──▶ expected     what should be true once it ran: the target
                             healthy, its incidents resolved, a metric within
                             bounds — as the company model or the system that
                             acted says it — or a person's confirmation
    succeeded ─▶ observed    read again until met, or the deadline: each
                             expectation met, not met, unknown, or awaiting
                             a person
              ──▶ verdict    all met: succeeded; some: partial; none: failed

Nothing is said met that was not observed or confirmed: what LEKA cannot
read stays unknown, and is not met at the deadline.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

# Let what was done settle before it is read.
SETTLE = timedelta(minutes=10)
# Read again until then; then concluded with what was observed.
WINDOW = timedelta(hours=24)

KINDS = ("healthy", "incident_resolved", "metric", "confirmed")
COMPARATORS = ("lt", "lte", "eq", "gte", "gt")
SOURCES = ("model", "system")
# The actions after which the thing acted on should be healthy.
HEALING = frozenset({"restart", "rollback", "deploy", "fix", "scale", "update"})
# An incident's states that are not resolved (normalised, LEKA-347).
OPEN = frozenset({"open", "in_progress"})
# What a thing's state says of its health: a resource's, normalised
# (LEKA-363) — running; failed, stopped, terminated — a service's, as its
# tool says it (PagerDuty: active; warning, critical, disabled; a status
# page: operational; degraded, partial or major outage). The rest — on its
# way, in maintenance — is read again.
HEALTHY = frozenset({"running", "active", "operational", "healthy", "ok", "up"})
DOWN = frozenset(
    {
        "failed",
        "stopped",
        "terminated",
        "warning",
        "critical",
        "disabled",
        "degraded",
        "down",
        "error",
        "partial_outage",
        "major_outage",
    }
)


class ExpectationError(ValueError):
    """An expectation that cannot be checked as said."""


class Seen(enum.StrEnum):
    MET = "met"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"
    AWAITING = "awaiting"


@dataclass(frozen=True)
class Expectation:
    """What should be true once it ran."""

    id: str
    kind: str
    target: Mapping[str, str] | None = None
    name: str | None = None
    comparator: str | None = None
    value: object = None
    source: str = "model"
    said: str | None = None
    incidents: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "target": dict(self.target) if self.target else None,
            "name": self.name,
            "comparator": self.comparator,
            "value": self.value,
            "source": self.source,
            "said": self.said,
            "incidents": list(self.incidents),
        }

    @classmethod
    def from_dict(cls, said: Mapping[str, object]) -> Expectation:
        target = said.get("target")
        incidents = said.get("incidents") or []
        return cls(
            id=str(said["id"]),
            kind=str(said["kind"]),
            target={str(k): str(v) for k, v in target.items()}
            if isinstance(target, Mapping)
            else None,
            name=None if said.get("name") is None else str(said["name"]),
            comparator=None if said.get("comparator") is None else str(said["comparator"]),
            value=said.get("value"),
            source=str(said.get("source") or "model"),
            said=None if said.get("said") is None else str(said["said"]),
            incidents=tuple(str(i) for i in incidents),  # type: ignore[attr-defined]
        )


def validated(expectation: Expectation) -> Expectation:
    """An expectation as it can be checked — ExpectationError otherwise."""
    if expectation.kind not in KINDS:
        raise ExpectationError(f"Unknown kind: {expectation.kind}.")
    if (
        expectation.kind in ("healthy", "incident_resolved", "metric")
        and expectation.source == "model"
    ):
        if not expectation.target or "id" not in expectation.target:
            raise ExpectationError("What it is about is missing.")
        try:
            uuid.UUID(expectation.target["id"])
        except ValueError as error:
            raise ExpectationError("What it is about is not a thing of the model.") from error
    if expectation.kind == "metric":
        if not expectation.name:
            raise ExpectationError("A metric needs its name.")
        if expectation.comparator not in COMPARATORS:
            raise ExpectationError("A metric needs a comparison: lt, lte, eq, gte, gt.")
        if expectation.source not in SOURCES:
            raise ExpectationError("A metric is read from the model or from the system.")
        if expectation.comparator != "eq" and not _number(expectation.value):
            raise ExpectationError("Only a number is compared.")
    if expectation.kind == "confirmed" and not (expectation.said or "").strip():
        raise ExpectationError("Say what a person confirms.")
    return expectation


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def expected_for(
    steps: Sequence[Mapping[str, object]],
    open_incidents: Mapping[str, Sequence[str]],
) -> list[Expectation]:
    """What an action should leave true, by default: what it acted on
    healthy, after an action that heals; the incidents open on it at the
    time, resolved. Once per thing."""
    found: dict[str, Expectation] = {}
    for step in steps:
        action = str(step.get("action"))
        for target in step.get("targets") or []:  # type: ignore[attr-defined]
            thing = {k: str(v) for k, v in dict(target).items()}
            key = thing["id"]
            if action in HEALING and f"healthy:{key}" not in found:
                found[f"healthy:{key}"] = Expectation(
                    id=f"healthy:{key}", kind="healthy", target=thing
                )
            incidents = tuple(open_incidents.get(key, ()))
            if incidents and f"incidents:{key}" not in found:
                found[f"incidents:{key}"] = Expectation(
                    id=f"incidents:{key}",
                    kind="incident_resolved",
                    target=thing,
                    incidents=incidents,
                )
    return list(found.values())


@dataclass(frozen=True)
class Thing:
    """What the model holds of something now — and the incidents open on
    it, that affect it."""

    type: str
    lifecycle: str
    attributes: Mapping[str, object] = field(default_factory=dict)
    open_incidents: tuple[str, ...] = ()
    # When a source last showed it.
    seen_at: datetime | None = None


@dataclass(frozen=True)
class Observed:
    """What verification reads: the model's things, what the systems that
    acted reported — and whether the model holds incidents at all: only
    then does none open on a thing say something."""

    things: Mapping[str, Thing] = field(default_factory=dict)
    metrics: Mapping[str, object] = field(default_factory=dict)
    incidents_known: bool = False
    # When what was done ended: what the model held of a thing before, a
    # source not having shown it since, says nothing of what came of it.
    since: datetime | None = None


@dataclass(frozen=True)
class Result:
    expectation_id: str
    seen: Seen
    value: object = None
    detail: str | None = None
    reported: Mapping[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "expectation_id": self.expectation_id,
            "seen": self.seen.value,
            "value": self.value,
            "detail": self.detail,
            "reported": dict(self.reported) if self.reported else None,
        }

    @classmethod
    def from_dict(cls, said: Mapping[str, object]) -> Result:
        reported = said.get("reported")
        return cls(
            expectation_id=str(said["expectation_id"]),
            seen=Seen(str(said["seen"])),
            value=said.get("value"),
            detail=None if said.get("detail") is None else str(said["detail"]),
            reported=dict(reported) if isinstance(reported, Mapping) else None,
        )


def _compare(observed: object, comparator: str, expected: object) -> bool:
    if comparator == "eq":
        return str(observed) == str(expected)
    if not (_number(observed) and _number(expected)):
        return False
    a, b = float(observed), float(expected)  # type: ignore[arg-type]
    return {
        "lt": a < b,
        "lte": a <= b,
        "gte": a >= b,
        "gt": a > b,
    }[comparator]


def check(expectation: Expectation, observed: Observed) -> Result:
    """One expectation against what is observed now — met only when what
    says so was shown since it ran."""
    result = _check(expectation, observed)
    if result.seen is not Seen.MET or observed.since is None:
        return result
    e = expectation
    if e.kind in ("healthy", "metric") and e.source == "model":
        thing = observed.things.get((e.target or {}).get("id", ""))
        if thing is None or thing.seen_at is None or thing.seen_at < observed.since:
            return replace(result, seen=Seen.UNKNOWN, detail="not_seen_since")
    return result


def _check(expectation: Expectation, observed: Observed) -> Result:
    e = expectation
    if e.kind == "confirmed":
        return Result(e.id, Seen.AWAITING)
    if e.kind == "metric" and e.source == "system":
        name = e.name or ""
        if name not in observed.metrics:
            return Result(e.id, Seen.UNKNOWN, detail="not_reported")
        value = observed.metrics[name]
        met = _compare(value, e.comparator or "eq", e.value)
        return Result(e.id, Seen.MET if met else Seen.NOT_MET, value=value)
    thing = observed.things.get((e.target or {}).get("id", ""))
    if e.kind == "incident_resolved":
        states = [observed.things.get(i) for i in e.incidents]
        if any(s is None for s in states):
            return Result(e.id, Seen.UNKNOWN, detail="incident_unknown")
        still = [
            i
            for i, s in zip(e.incidents, states, strict=True)
            if s and str(s.attributes.get("state")) in OPEN
        ]
        return Result(
            e.id,
            Seen.NOT_MET if still else Seen.MET,
            value=len(still),
            detail="still_open" if still else None,
        )
    if thing is None:
        return Result(e.id, Seen.UNKNOWN, detail="not_in_model")
    if thing.lifecycle == "removed":
        return Result(e.id, Seen.NOT_MET, detail="removed")
    if e.kind == "healthy":
        # Healthy: no incident open on it, and — when the model holds its
        # state — running. A state on its way is read again.
        state = thing.attributes.get("state")
        if thing.open_incidents:
            return Result(e.id, Seen.NOT_MET, value=len(thing.open_incidents), detail="incidents")
        if state in DOWN:
            return Result(e.id, Seen.NOT_MET, value=state, detail="state")
        if state in HEALTHY:
            return Result(e.id, Seen.MET, value=state, detail="state")
        if state is None and observed.incidents_known:
            return Result(e.id, Seen.MET, value=0, detail="incidents")
        return Result(e.id, Seen.UNKNOWN, value=state, detail="no_health")
    # A metric the model holds.
    if e.name not in thing.attributes:
        return Result(e.id, Seen.UNKNOWN, detail="not_in_model")
    value = thing.attributes[e.name or ""]
    met = _compare(value, e.comparator or "eq", e.value)
    return Result(e.id, Seen.MET if met else Seen.NOT_MET, value=value)


def observe(
    expectations: Sequence[Expectation],
    observed: Observed,
    earlier: Mapping[str, Result] | None = None,
) -> list[Result]:
    """Every expectation checked again — what a person reported kept."""
    kept = earlier or {}
    results: list[Result] = []
    for expectation in expectations:
        before = kept.get(expectation.id)
        if before is not None and before.reported:
            results.append(before)
            continue
        results.append(check(expectation, observed))
    return results


def verdict(results: Sequence[Result], *, final: bool) -> str:
    """Where the outcome stands: succeeded when every expectation is met;
    otherwise still verifying until final — then partial when some are,
    failed when none is. With nothing expected, what ran is the outcome."""
    if all(r.seen is Seen.MET for r in results):
        return "succeeded"
    if not final:
        return "verifying"
    met = sum(r.seen is Seen.MET for r in results)
    return "partial" if met else "failed"


def reported(result: Result, *, met: bool, note: str, link: str | None, by: str, at: str) -> Result:
    """A person's word on an expectation."""
    return replace(
        result,
        seen=Seen.MET if met else Seen.NOT_MET,
        reported={"by": by, "at": at, "note": note, "link": link},
    )
