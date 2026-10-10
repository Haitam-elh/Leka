"""AI governance (LEKA-406): what a workspace allows its models to do, and
for whom — decided where a model is called (the gateway) and where an agent
is asked to run, every outcome kept.

    model_access   which models may answer: by provider, by whose account
                   (LEKA's, the workspace's own) — or none at all
    usage_limit    how much may be asked in a day, a month: calls, tokens,
                   cost — for the workspace, or for each person
    output_check   what an answer may not carry — secrets, personal data —
                   redacted, refused, or only flagged
    approval       an agent at or above a risk does not run until someone
                   who may approve says so — never the one who asked

Each control covers what it names: purposes — the work a model is asked to
do, "agent:security-review", "intention.*" (none: all of it) — and roles —
"member", "admin", a role of the workspace's own (none: everyone). Work
done for nobody in particular is covered only by controls naming no role.

Who the work is for is set where it is known — the request's principal, the
person a worker acts for (hidden_on_behalf) — and read where the model is
called (current_actor).

Pure: no database here. Kept and changed by AIControlService (ai_service.py).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta
from fnmatch import fnmatchcase

from leka.governance.policy import RISKS, Subject

KINDS = ("model_access", "usage_limit", "output_check", "approval")
OWNERS = ("leka", "workspace")
PERIODS: Mapping[str, timedelta] = {"day": timedelta(days=1), "month": timedelta(days=30)}
PER = ("workspace", "person")
DETECTS = ("secrets", "personal_data")
ON_FINDING = ("redact", "block", "flag")
# What a control did, as the audit says it.
OUTCOMES = (
    "refused",  # no model it allows could answer
    "limited",  # past a usage limit
    "redacted",  # what an answer carried, taken out
    "blocked",  # an answer refused for what it carried
    "flagged",  # an answer kept, what it carried said
    "held",  # an agent run waiting for approval
    "approved",
    "rejected",
)
REDACTED = "[redacted]"


class ControlError(ValueError):
    """A control that cannot be kept as given: which field, and why."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


# ── who the work is for ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Actor:
    """The person the work is done for, as the controls read them: their
    roles — the seat's, and a role of the workspace's own."""

    user_id: uuid.UUID
    roles: frozenset[str]

    @classmethod
    def of(cls, subject: Subject) -> Actor:
        roles = {subject.role.value}
        if subject.custom_role:
            roles.add(subject.custom_role)
        return cls(subject.user_id, frozenset(roles))


_actor: ContextVar[Actor | None] = ContextVar("ai_actor", default=None)


@contextmanager
def acting(actor: Actor | None) -> Iterator[None]:
    """The work inside is done for `actor`."""
    token = _actor.set(actor)
    try:
        yield
    finally:
        _actor.reset(token)


def act_for(actor: Actor | None) -> None:
    """The rest of this job is done for `actor` — a worker's job is its own
    task: it ends with it."""
    _actor.set(actor)


def current_actor() -> Actor | None:
    return _actor.get()


# ── a control ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Control:
    name: str
    kind: str
    purposes: tuple[str, ...] = ()
    roles: frozenset[str] = frozenset()
    id: uuid.UUID | None = None
    # model_access: allowed providers and accounts (none: any); or none at all.
    providers: frozenset[str] = frozenset()
    owners: frozenset[str] = frozenset()
    block: bool = False
    # usage_limit
    period: str = "day"
    per: str = "workspace"
    max_calls: int | None = None
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    # output_check
    detect: frozenset[str] = frozenset()
    on_finding: str = "redact"
    # approval
    risk_at_least: str = "high"

    def config(self) -> dict[str, object]:
        """What is kept of it, its kind's own."""
        if self.kind == "model_access":
            return {
                "providers": sorted(self.providers),
                "owners": sorted(self.owners),
                "block": self.block,
            }
        if self.kind == "usage_limit":
            return {
                "period": self.period,
                "per": self.per,
                "max_calls": self.max_calls,
                "max_tokens": self.max_tokens,
                "max_cost_usd": self.max_cost_usd,
            }
        if self.kind == "output_check":
            return {"detect": sorted(self.detect), "on_finding": self.on_finding}
        return {"risk_at_least": self.risk_at_least}


def control_of(
    name: str,
    kind: str,
    config: Mapping[str, object],
    *,
    purposes: Sequence[str] = (),
    roles: Sequence[str] = (),
    control_id: uuid.UUID | None = None,
) -> Control:
    """A control as kept — read leniently: what is not understood is left
    at its default."""

    def words(key: str) -> frozenset[str]:
        value = config.get(key)
        return frozenset(str(v) for v in value) if isinstance(value, list) else frozenset()

    def number(key: str) -> float | None:
        value = config.get(key)
        return float(value) if isinstance(value, int | float) and value >= 0 else None

    calls, tokens = number("max_calls"), number("max_tokens")
    return Control(
        name=name,
        kind=kind,
        purposes=tuple(purposes),
        roles=frozenset(roles),
        id=control_id,
        providers=words("providers"),
        owners=words("owners"),
        block=config.get("block") is True,
        period=str(config.get("period", "day")),
        per=str(config.get("per", "workspace")),
        max_calls=int(calls) if calls is not None else None,
        max_tokens=int(tokens) if tokens is not None else None,
        max_cost_usd=number("max_cost_usd"),
        detect=words("detect"),
        on_finding=str(config.get("on_finding", "redact")),
        risk_at_least=str(config.get("risk_at_least", "high")),
    )


def checked_control(control: Control) -> Control:
    """The control, or ControlError saying what is wrong with it."""
    if not control.name.strip():
        raise ControlError("name", "Name the control.")
    if control.kind not in KINDS:
        raise ControlError("kind", "No such kind of control.")
    for pattern in control.purposes:
        if not pattern or len(pattern) > 100 or any(c.isspace() for c in pattern):
            raise ControlError("purposes", f"Not a purpose: {pattern!r}.")
    if control.kind == "model_access":
        if control.owners - set(OWNERS):
            raise ControlError("owners", "An account is LEKA's or the workspace's own.")
        if not control.block and not control.providers and not control.owners:
            raise ControlError("providers", "Say which models it allows, or that it allows none.")
    elif control.kind == "usage_limit":
        if control.period not in PERIODS:
            raise ControlError("period", "A day or a month.")
        if control.per not in PER:
            raise ControlError("per", "For the workspace, or for each person.")
        if (
            control.max_calls is None
            and control.max_tokens is None
            and (control.max_cost_usd is None)
        ):
            raise ControlError("max_calls", "Say what it limits: calls, tokens or cost.")
    elif control.kind == "output_check":
        if not control.detect or control.detect - set(DETECTS):
            raise ControlError("detect", "Say what it looks for: secrets, personal data.")
        if control.on_finding not in ON_FINDING:
            raise ControlError("on_finding", "Redact, block or flag.")
    elif control.risk_at_least not in RISKS:
        raise ControlError("risk_at_least", "A risk: low, medium or high.")
    return control


def covers(control: Control, purpose: str, actor: Actor | None) -> bool:
    """Whether the control applies to this work, done for this person."""
    if control.purposes and not any(fnmatchcase(purpose, p) for p in control.purposes):
        return False
    if not control.roles:
        return True
    return actor is not None and bool(actor.roles & control.roles)


# ── which model ────────────────────────────────────────────────────────────


def refusing(
    controls: Sequence[Control],
    purpose: str,
    actor: Actor | None,
    *,
    provider: str,
    owner: str,
) -> Control | None:
    """The model-access control that refuses this model for this work, if
    one does: every one that covers it must allow it."""
    for control in controls:
        if control.kind != "model_access" or not covers(control, purpose, actor):
            continue
        if (
            control.block
            or (control.providers and provider not in control.providers)
            or (control.owners and owner not in control.owners)
        ):
            return control
    return None


# ── how much ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Used:
    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0


def limits(controls: Sequence[Control], purpose: str, actor: Actor | None) -> list[Control]:
    return [c for c in controls if c.kind == "usage_limit" and covers(c, purpose, actor)]


def spent(control: Control, used: Used) -> str | None:
    """What of the limit is reached — calls, tokens, cost — or None."""
    if control.max_calls is not None and used.calls >= control.max_calls:
        return "calls"
    if control.max_tokens is not None and used.tokens >= control.max_tokens:
        return "tokens"
    if control.max_cost_usd is not None and used.cost_usd >= control.max_cost_usd:
        return "cost"
    return None


# ── what an answer carries ─────────────────────────────────────────────────

# Each pattern: what it finds — the value alone when it has a group.
PATTERNS: Mapping[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    "secrets": (
        ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
        ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
        ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
        ("api_key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
        ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
        ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
        ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
        (
            "password",
            re.compile(
                r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token)\b"
                r"\\?[\"']?\s*[:=]\s*\\?[\"']?([^\s\"'\\,;]{6,})"
            ),
        ),
    ),
    "personal_data": (
        ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
        ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")),
        ("card", re.compile(r"\b(?:\d[ -]?){12,18}\d\b")),
        ("phone", re.compile(r"(?<![\w+])(?:\+|00)[1-9]\d{0,2}(?:[ .-]?\d){8,12}\b")),
        ("phone", re.compile(r"\b0[1-9](?:[ .-]?\d{2}){4}\b")),
    ),
}


def _luhn(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


@dataclass(frozen=True)
class Finding:
    detect: str  # secrets, personal_data
    what: str  # aws_key, email…
    start: int
    end: int


def scan(text: str, detect: frozenset[str]) -> list[Finding]:
    """What the text carries of what is looked for — never what it is."""
    found: list[Finding] = []
    for family in DETECTS:
        if family not in detect:
            continue
        for what, pattern in PATTERNS[family]:
            for match in pattern.finditer(text):
                start, end = match.span(1) if pattern.groups else match.span()
                if what == "card" and not _luhn(re.sub(r"\D", "", match.group())):
                    continue
                found.append(Finding(family, what, start, end))
    return sorted(found, key=lambda f: (f.start, -f.end))


def redacted(text: str, found: Sequence[Finding]) -> str:
    """The text, what was found replaced — overlaps once."""
    out: list[str] = []
    at = 0
    for f in sorted(found, key=lambda f: f.start):
        if f.end <= at:
            continue
        out.append(text[at : max(at, f.start)])
        out.append(REDACTED)
        at = f.end
    out.append(text[at:])
    return "".join(out)


@dataclass(frozen=True)
class Checked:
    """An answer, through the output checks that cover it."""

    text: str
    # Each control that found something, what it did, what it found.
    outcomes: tuple[tuple[Control, str, tuple[str, ...]], ...] = field(default=())

    @property
    def blocked_by(self) -> Control | None:
        return next((c for c, outcome, _ in self.outcomes if outcome == "blocked"), None)


def check_output(
    controls: Sequence[Control], purpose: str, actor: Actor | None, text: str
) -> Checked:
    """The answer through every output check that covers it: a block wins;
    redactions are made one after the other; a flag keeps it as it is."""
    outcomes: list[tuple[Control, str, tuple[str, ...]]] = []
    for control in controls:
        if control.kind != "output_check" or not covers(control, purpose, actor):
            continue
        found = scan(text, control.detect)
        if not found:
            continue
        what = tuple(sorted({f.what for f in found}))
        if control.on_finding == "block":
            outcomes.append((control, "blocked", what))
        elif control.on_finding == "redact":
            text = redacted(text, found)
            outcomes.append((control, "redacted", what))
        else:
            outcomes.append((control, "flagged", what))
    return Checked(text, tuple(outcomes))


# ── approval ───────────────────────────────────────────────────────────────


def holding(
    controls: Sequence[Control], key: str, risk: str, actor: Actor | None
) -> Control | None:
    """The approval control an agent run waits on, if one covers it: the
    agent at or above its risk, asked for one of its roles."""
    level = RISKS.index(risk) if risk in RISKS else len(RISKS) - 1
    for control in controls:
        if control.kind != "approval" or not covers(control, f"agent:{key}", actor):
            continue
        if level >= RISKS.index(control.risk_at_least):
            return control
    return None
