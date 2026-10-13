"""What an approved decision becomes (LEKA-391), pure: a plan, checked
before it runs, each step run by the system the workspace authorized — or
by a person — and what came of each, said as it is.

    approved decision (LEKA-390)
      ──▶ plan_of()      one step per action approved: who runs it — an
                         endpoint the workspace authorized for that action,
                         in that environment, on that target; else a person
      ──▶ checks()       before anything runs: still approved, its approvers
                         still allowed, what the workspace's governance says
                         now (LEKA-404: no freeze, the approval not expired,
                         the policy still met), the endpoint still
                         authorizing it, inside the window asked, before the
                         deadline, the target still there — one failing,
                         nothing runs
      ──▶ outcome_of()   what the system answered, by the contract (LEKA-435):
                         `{"status": "succeeded"}` done; accepted, pending,
                         running — or anything else, an empty or unreadable
                         answer included — a person confirms it, never
                         assumed done; failed

AUTHORIZED SYSTEMS. LEKA holds no write access to a customer's systems: it
calls the endpoints an admin registered — their own automation, a CI job,
a runbook — each saying which actions, in which environments, it accepts.
Every call is signed (sign()) so the endpoint can tell it is LEKA, this
workspace, now; it goes through the connectors' transport (https, public
addresses only).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

ANY = "*"
SIGNATURE = "X-Leka-Signature"
DELIVERY = "X-Leka-Delivery"
# What is kept of what a system answered.
EXCERPT = 2000


@dataclass(frozen=True)
class Endpoint:
    """An authorized system, as the planner reads it."""

    id: uuid.UUID
    name: str
    actions: frozenset[str]
    environments: frozenset[str]
    targets: frozenset[uuid.UUID] = frozenset()
    enabled: bool = True

    def allows(self, action: str, environment: str | None, targets: Sequence[uuid.UUID]) -> bool:
        if not self.enabled:
            return False
        if ANY not in self.actions and action not in self.actions:
            return False
        if ANY not in self.environments and (environment or "") not in self.environments:
            return False
        return not self.targets or all(target in self.targets for target in targets)


@dataclass(frozen=True)
class StepPlan:
    """One action to run: what, on what, where, by whom."""

    position: int
    proposal_id: str
    action: str
    targets: tuple[dict[str, str], ...]
    environment: str | None
    constraints: tuple[dict[str, object], ...]
    executor: str  # webhook | manual
    endpoint_id: uuid.UUID | None


def plan_of(
    proposals: Sequence[Mapping[str, object]], endpoints: Sequence[Endpoint]
) -> tuple[StepPlan, ...]:
    """One step per action approved, run by the first endpoint authorized
    for it — or by a person when none is."""
    steps: list[StepPlan] = []
    for position, proposal in enumerate(proposals, start=1):
        action = str(proposal["action"])
        environment = proposal.get("environment")
        targets = tuple(
            {k: str(v) for k, v in t.items()}
            for t in cast("list[Mapping[str, object]]", proposal.get("targets") or [])
        )
        ids = [uuid.UUID(str(t["id"])) for t in targets]
        endpoint = next(
            (
                e
                for e in endpoints
                if e.allows(action, str(environment) if environment else None, ids)
            ),
            None,
        )
        steps.append(
            StepPlan(
                position=position,
                proposal_id=str(proposal["id"]),
                action=action,
                targets=targets,
                environment=None if environment is None else str(environment),
                constraints=tuple(
                    dict(c)
                    for c in cast("list[Mapping[str, object]]", proposal.get("constraints") or [])
                ),
                executor="webhook" if endpoint else "manual",
                endpoint_id=endpoint.id if endpoint else None,
            )
        )
    return tuple(steps)


# ── windows and deadlines (LEKA-386's constraints) ──────────────────────────

# When each window said opens and closes, in the plan's time zone.
NIGHT = (time(22, 0), time(6, 0))
BUSINESS = (time(8, 0), time(19, 0))
EVENING = time(18, 0)
# An hour said: « 22h », « 22h30 », « 10pm », « 9:30 am » (LEKA-440).
HOUR = re.compile(r"(\d{1,2})(?: ?h(\d{2})?|(?::(\d{2}))? ?(am|pm))")


def _hours(said: str) -> list[time]:
    found: list[time] = []
    for match in HOUR.finditer(said.casefold()):
        hour, minutes = int(match.group(1)), int(match.group(2) or match.group(3) or 0)
        if match.group(4) == "pm" and hour < 12:
            hour += 12
        elif match.group(4) == "am" and hour == 12:
            hour = 0
        if hour < 24 and minutes < 60:
            found.append(time(hour, minutes))
    return found


def _between(at: time, opens: time, closes: time) -> bool:
    """Within [opens, closes), across midnight when it closes earlier."""
    if opens <= closes:
        return opens <= at < closes
    return at >= opens or at < closes


def _window_kind(said: str) -> str | None:
    folded = said.casefold()
    hours = _hours(folded)
    if len(hours) >= 2 and ("entre" in folded or "between" in folded):
        return "between"
    if hours and ("apres" in folded or "après" in folded or "after" in folded):
        return "after"
    if "week" in folded:
        return "weekend"
    if "nuit" in folded or "night" in folded or "tonight" in folded:
        return "night"
    if "heures ouvr" in folded or "business hours" in folded:
        return "off_hours"
    if "ce soir" in folded:
        return "evening"
    return None


def in_window(said: str, moment: datetime, zone: ZoneInfo) -> bool | None:
    """Whether a moment falls in the window its words say — None when the
    words say no window LEKA can tell."""
    kind = _window_kind(said)
    if kind is None:
        return None
    local = moment.astimezone(zone)
    weekend = local.weekday() >= 5
    if kind == "weekend":
        return weekend
    at = local.time()
    night = at >= NIGHT[0] or at < NIGHT[1]
    if kind == "night":
        return night
    if kind == "between":
        opens, closes = _hours(said)[:2]
        return _between(at, opens, closes)
    if kind == "after":
        # « Après 22h »: until the night ends — never the next morning's.
        opens = _hours(said)[0]
        return _between(at, opens, NIGHT[1] if opens >= EVENING else time(23, 59, 59))
    if kind == "evening":
        return _between(at, EVENING, time(23, 59, 59))
    return weekend or not (BUSINESS[0] <= at < BUSINESS[1])


def next_window(said: str, moment: datetime, zone: ZoneInfo) -> datetime | None:
    """When the window its words say next opens — the moment itself when
    it is open; None when LEKA cannot tell."""
    if in_window(said, moment, zone) is None:
        return None
    if in_window(said, moment, zone):
        return moment
    local = moment.astimezone(zone).replace(second=0, microsecond=0)
    # Within a week every window opens: by the quarter hour, the first open.
    candidate = local + timedelta(minutes=15 - local.minute % 15)
    for _ in range(7 * 24 * 4):
        if in_window(said, candidate, zone):
            return candidate.astimezone(UTC)
        candidate += timedelta(minutes=15)
    return None


def deadline_of(value: object, zone: ZoneInfo) -> datetime | None:
    """A deadline said as a day: the end of that day."""
    if not isinstance(value, str):
        return None
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return None
    return datetime.combine(day + timedelta(days=1), time(0, 0), zone).astimezone(UTC)


def scheduled_for(steps: Sequence[StepPlan], now: datetime, zone: ZoneInfo) -> datetime | None:
    """When the plan should run: at the next opening of the window its
    actions were asked in — None to run now."""
    for step in steps:
        for constraint in step.constraints:
            if constraint.get("kind") == "window" and isinstance(constraint.get("value"), str):
                opens = next_window(str(constraint["value"]), now, zone)
                if opens is not None and opens > now:
                    return opens
    return None


# ── checks before anything runs ─────────────────────────────────────────────


@dataclass(frozen=True)
class Check:
    code: str
    passed: bool
    detail: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "passed": self.passed, "detail": dict(self.detail)}


@dataclass(frozen=True)
class Situation:
    """What the checks read, gathered by the service."""

    decision_status: str
    decision_revision: int
    plan_revision: int
    approvers: tuple[uuid.UUID, ...]
    allowed: frozenset[uuid.UUID]  # who may approve, today
    required: int
    endpoints: Mapping[uuid.UUID, Endpoint]
    present: frozenset[uuid.UUID]  # targets still in the company model
    now: datetime
    zone: ZoneInfo
    # What the workspace's governance says now (LEKA-404, governance.py).
    policy: Sequence[Check] = ()


def checks(steps: Sequence[StepPlan], situation: Situation) -> list[Check]:
    """Everything that must hold before an action runs — each said, passed
    or not."""
    s = situation
    found = [
        Check(
            "decision_approved",
            s.decision_status == "approved" and s.decision_revision == s.plan_revision,
            {"status": s.decision_status, "revision": s.decision_revision},
        ),
    ]
    still = [a for a in s.approvers if a in s.allowed]
    found.append(
        Check(
            "approvers_allowed",
            len(still) >= s.required,
            {"approvers": len(s.approvers), "still_allowed": len(still), "required": s.required},
        )
    )
    found.extend(s.policy)
    for step in steps:
        ids = [uuid.UUID(str(t["id"])) for t in step.targets]
        if step.executor == "webhook":
            endpoint = s.endpoints.get(step.endpoint_id) if step.endpoint_id else None
            found.append(
                Check(
                    "endpoint_allows",
                    endpoint is not None and endpoint.allows(step.action, step.environment, ids),
                    {"step": step.position, "endpoint": endpoint.name if endpoint else None},
                )
            )
        missing = [str(i) for i in ids if i not in s.present]
        found.append(
            Check("targets_present", not missing, {"step": step.position, "missing": missing})
        )
        for constraint in step.constraints:
            kind, value = constraint.get("kind"), constraint.get("value")
            if kind == "window" and isinstance(value, str):
                inside = in_window(value, s.now, s.zone)
                if inside is not None:
                    found.append(
                        Check("in_window", inside, {"step": step.position, "window": value})
                    )
            if kind == "deadline":
                ends = deadline_of(value, s.zone)
                if ends is not None:
                    found.append(
                        Check(
                            "before_deadline",
                            s.now < ends,
                            {"step": step.position, "deadline": ends.isoformat()},
                        )
                    )
    return found


def blocking(found: Sequence[Check]) -> list[Check]:
    return [check for check in found if not check.passed]


# ── calling an authorized system ─────────────────────────────────────────────


def body_of(payload: Mapping[str, object]) -> bytes:
    """What is sent, exactly as signed: compact, keys sorted."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode()


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """`t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<body>">` — the endpoint
    recomputes it with its secret, and refuses an old timestamp."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def verify(secret: str, header: str, body: bytes, *, now: int, tolerance: int = 300) -> bool:
    """What an endpoint does with the header — here for the tests and the
    docs, so both sides read the same rule."""
    parts = dict(part.split("=", 1) for part in header.split(",") if "=" in part)
    try:
        timestamp = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs(now - timestamp) > tolerance:
        return False
    expected = sign(secret, timestamp, body).split("v1=", 1)[1]
    return hmac.compare_digest(expected, parts.get("v1", ""))


# The executor's contract (LEKA-435): what a 2xx answer says it did.
DONE = frozenset({"succeeded"})
WORKING = frozenset({"accepted", "pending", "running", "queued"})


@dataclass(frozen=True)
class Outcome:
    """What came of a call: succeeded, awaiting a person's confirmation,
    or failed — and why."""

    status: str  # succeeded | awaiting | failed
    reason: str | None = None
    detail: str | None = None
    ref: str | None = None
    # What the system measured once it acted (LEKA-392): name → value.
    metrics: Mapping[str, object] = field(default_factory=dict)


def outcome_of(status_code: int, body: bytes) -> Outcome:
    """What a system's answer means, by the contract (LEKA-435): done only
    when a 2xx says `{"status": "succeeded"}`; failed when it is not a 2xx
    or says `failed`; 202 or accepted, pending, running, queued waits for a
    person to confirm it — and so does any other 2xx: empty, unreadable, a
    status the contract does not know. It may have acted: never said done,
    never retried as failed."""
    said: Mapping[str, object] = {}
    try:
        parsed = json.loads(body) if body else {}
        if isinstance(parsed, dict):
            said = parsed
    except (ValueError, UnicodeDecodeError):
        said = {}
    state = str(said.get("status", "")).casefold()
    detail = said.get("detail")
    ref = said.get("ref")
    measured = said.get("metrics")
    metrics = (
        {
            str(name)[:100]: value
            for name, value in list(measured.items())[:50]
            if isinstance(value, int | float | str) and not isinstance(value, bool)
        }
        if isinstance(measured, Mapping)
        else {}
    )
    extra: dict[str, Any] = {
        "detail": str(detail)[:500] if detail is not None else None,
        "ref": str(ref)[:200] if ref is not None else None,
        "metrics": metrics,
    }
    if not 200 <= status_code < 300:
        return Outcome("failed", reason=f"http_{status_code}", **extra)
    if state == "failed":
        return Outcome("failed", reason="reported_failed", **extra)
    if status_code == 202 or state in WORKING:
        return Outcome("awaiting", reason="accepted", **extra)
    if state in DONE:
        return Outcome("succeeded", **extra)
    return Outcome("awaiting", reason="unconfirmed", **extra)


def excerpt(body: bytes) -> str:
    return body[:EXCERPT].decode("utf-8", errors="replace")
