"""Skills (LEKA-396): the operations LEKA's capabilities are made of — one
read of the company model, one lookup, one check — each defined once, with
its contract, and run one way by whoever needs it: LEKA's analyst today,
the agents and the workflows next (LEKA-397, LEKA-400, LEKA-401).

    a Skill      its key and version (semver); its title, what it does and
                 when to use it — what a model reads to choose it; its
                 category; what it takes and what it gives — pydantic models,
                 its contract; who may run it — a governance permission; what
                 it does — it reads, nothing else; where it stands — draft,
                 review, active, deprecated, retired; how long it may take;
                 what it cannot do
    registered   by the module that has it (register), when it is imported —
                 as capabilities are (registry.provide). A version is its
                 contract: the same version said otherwise is refused
                 (SkillError) — a new contract is a new version
    run          SkillRuntime.run — the one way, for every caller:
        1. which: the version asked (1.2.0; or 1, 1.2 — the latest of them),
           else the latest that runs. Draft, review, retired never run;
           deprecated runs, said
        2. may they: the permission it needs, among the caller's — a
           person's role as it is now (permitted)
        3. what it is given, checked against what it takes — refused, each
           error said
        4. run in its own session, in the workspace's scope, the transaction
           READ ONLY — the database refuses a write — within its time
        5. what it gives, checked against what it promised — a skill that
           breaks its contract fails, said so
        6. kept, whatever came of it (skill_runs): which skill, version and
           contract (its fingerprint), called by what about what, for whom,
           given what, what it gave, how it ended, how long
    to a model   SkillRuntime.tool: a RuntimeTool its key names, what it
                 takes the parameters — each call through run(): checked and
                 kept. What the skill read, citable (`cited`), goes to the
                 caller, not to the model

Nothing a skill does changes anything: what would is not a skill — an
action goes through a person's decision (LEKA-390), through the systems
they authorized (LEKA-391).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.definition import (
    CATEGORIES,
    KEY,
    RUNNABLE,
    Definition,
    DefinitionError,
    Lifecycle,
    semver,
)
from leka.capabilities.gateway import plain_schema
from leka.capabilities.llm import RuntimeTool
from leka.capabilities.models import SkillRun
from leka.capabilities.repository import WorkspaceCatalogueRepository
from leka.capabilities.runtime import AgentTool, Withheld
from leka.capabilities.schemas import SkillRead, SkillRunError, SkillRunRead, SkillVersionRead
from leka.capabilities.tools import Answer
from leka.connectors import SourceKind
from leka.db import session_factory, workspace_scope
from leka.governance import ROLE_PERMISSIONS, Permission
from leka.knowledge import EntityType
from leka.platform import MembershipRepository, Role

logger = structlog.get_logger(__name__)

# What a skill does. It reads: what changes a system is an action, and an
# action is a person's decision (LEKA-390).
EFFECTS = ("read",)
PERMISSIONS = frozenset(p.value for p in Permission)
ENTITY_TYPES = frozenset(t.value for t in EntityType)
SOURCE_KINDS = frozenset(k.value for k in SourceKind)
# A tool's name, for every provider: 64 characters at most.
LONGEST_KEY = 64
# Seconds a skill may take, at most.
MOST_TIME = 120.0
# What is kept of what it was given, and of what it gave (characters).
INPUTS_KEPT = 4_000
OUTPUT_KEPT = 50_000

# What any member may do: what LEKA itself reads with, for no one in
# particular — an intention its sources raised.
LEKA = frozenset(p.value for p in ROLE_PERMISSIONS[Role.MEMBER])


def clock() -> datetime:
    """Now, as a skill reads it — what a test stands in for."""
    return datetime.now(UTC)


class SkillError(ValueError):
    """A skill that cannot be registered as said."""


class UnknownThingError(LookupError):
    """What a skill was given names nothing LEKA knows: refused, said so."""


# ── what a skill read, citable ───────────────────────────────────────────────


class CitedSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID | None = None
    kind: str | None = None
    name: str | None = None


class Cited(BaseModel):
    """Something a skill read, as an answer cites it: its id — « entity:… »,
    « event:… », « source:… », « finding:… » — what it is, where it came
    from."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str = Field(description="entity, event, record, inference.")
    label: str
    ref_type: str | None = None
    ref_id: uuid.UUID | None = None
    sources: list[CitedSource] = Field(default_factory=list)
    origin: str | None = None
    detail: str | None = None
    at: datetime | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class Citing(BaseModel):
    """What a skill gives that says what it read. A model is given the rest:
    the ids are in it; what they are is its caller's."""

    cited: list[Cited] = Field(default_factory=list)


class Signal(BaseModel):
    """Something a skill concluded, by its code — what a workflow's condition
    reads (`found`, LEKA-397), what an agent weighs: how much it matters,
    said in a sentence, with the values it rests on."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(description="domain.signal, e.g. delivery.high_failure_rate.")
    level: Literal["info", "warning", "critical"]
    text: str
    params: dict[str, Any] = Field(default_factory=dict)


class Assessed(Citing):
    """What an analysing skill gives: what it read, citable, and what it
    concluded, as signals."""

    signals: list[Signal] = Field(default_factory=list)


# ── a skill ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Call:
    """What a skill runs with: where, when, for whom, called by what — and
    the session it reads through, read only."""

    workspace_id: uuid.UUID
    session: AsyncSession
    now: datetime
    by: uuid.UUID | None
    caller: str


Run = Callable[[Any, Call], Awaitable[BaseModel]]


@dataclass(frozen=True)
class Skill:
    """One skill, one version."""

    key: str
    version: str
    title: str
    # What it does and when to use it: what a model reads to choose it.
    summary: str
    category: str
    input: type[BaseModel]
    output: type[BaseModel]
    run: Run
    permission: str = Permission.WORKSPACE_READ.value
    effect: str = "read"
    lifecycle: Lifecycle = Lifecycle.ACTIVE
    timeout: float = 20.0
    origin: str = "internal"
    # What it cannot do, what it needs to be of use.
    limitations: tuple[str, ...] = ()
    # The kinds of things it reads (LEKA-401): an agent is offered it only
    # when it may read all of them. None said: it reads anything.
    reads: tuple[str, ...] = ()
    # What must be connected for it to be of use: one source kind of each
    # group (`("github", "gitlab", "bitbucket")`). Checked when it runs.
    sources: tuple[tuple[str, ...], ...] = ()

    def contract(self) -> dict[str, Any]:
        """What it takes and what it gives, as JSON schemas."""
        return {"input": plain_schema(self.input), "output": plain_schema(self.output)}

    def fingerprint(self) -> str:
        """What it is and does, hashed: everything but where it stands in its
        lifecycle — moving it needs no new version; changing it does."""
        said = {
            "key": self.key,
            "version": self.version,
            "title": self.title,
            "summary": self.summary,
            "category": self.category,
            "contract": self.contract(),
            "permission": self.permission,
            "effect": self.effect,
            "timeout": self.timeout,
            "origin": self.origin,
            "limitations": list(self.limitations),
        }
        # Added with the library (LEKA-401): none said, nothing new — what
        # was registered before stays what it is.
        if self.reads:
            said["reads"] = list(self.reads)
        if self.sources:
            said["sources"] = [list(group) for group in self.sources]
        canonical = json.dumps(said, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()


def tool_schema(model: type[BaseModel]) -> dict[str, Any]:
    """What a skill takes, as a model is told it: references inlined, and a
    value it may leave out said not required — rather than « or null »,
    which not every provider reads."""
    schema = plain_schema(model)
    properties: dict[str, Any] = schema.setdefault("properties", {})
    for name, said in list(properties.items()):
        options = said.get("anyOf")
        if not isinstance(options, list):
            continue
        kept = [option for option in options if option != {"type": "null"}]
        if len(kept) == 1 < len(options):
            rest = {k: v for k, v in said.items() if k not in ("anyOf", "default")}
            properties[name] = {**kept[0], **rest}
    return schema


def checked(skill: Skill) -> Skill:
    """The skill, if it can be registered as said — else SkillError, every
    problem said."""
    problems: list[str] = []
    if not KEY.match(skill.key) or len(skill.key) > LONGEST_KEY:
        problems.append(f"key: lowercase words joined by hyphens, {LONGEST_KEY} characters at most")
    try:
        semver(skill.version)
    except DefinitionError as error:
        problems.append(str(error))
    if not skill.title.strip():
        problems.append("a title")
    if not skill.summary.strip() or len(skill.summary) > 1000:
        problems.append("a summary, 1000 characters at most")
    if skill.category not in CATEGORIES:
        problems.append(f"category {skill.category!r}: one of {', '.join(CATEGORIES)}")
    if skill.effect not in EFFECTS:
        problems.append(
            f"effect {skill.effect!r}: a skill reads — what changes a system is an action, "
            "a person's decision (LEKA-390)"
        )
    if skill.permission not in PERMISSIONS:
        problems.append(f"unknown permission {skill.permission!r}")
    if not 0 < skill.timeout <= MOST_TIME:
        problems.append(f"timeout: more than 0, {MOST_TIME:g} s at most")
    unknown_types = sorted(set(skill.reads) - ENTITY_TYPES)
    if unknown_types:
        problems.append(f"reads unknown kinds {unknown_types}")
    for group in skill.sources:
        if not group or set(group) - SOURCE_KINDS:
            problems.append(f"sources {list(group)}: kinds of source LEKA connects")
    # What it is said to take and give, as it may come: anything.
    sides: tuple[tuple[str, object], ...] = (("input", skill.input), ("output", skill.output))
    for side, model in sides:
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            problems.append(f"{side}: a pydantic model")
    if problems:
        raise SkillError(f"{skill.key} {skill.version}: {'; '.join(problems)}")
    try:
        skill.contract()
    except ValueError as error:
        raise SkillError(f"{skill.key} {skill.version}: {error}") from error
    return skill


class SkillRegistry:
    """Every skill LEKA has, every version of each."""

    def __init__(self) -> None:
        self._skills: dict[str, dict[str, Skill]] = {}

    def register(self, *skills: Skill) -> None:
        """Each checked. A version already registered as something else is
        refused; the same again — a module imported twice, a skill moved in
        its lifecycle — stands in for it."""
        for skill in skills:
            checked(skill)
            held = self._skills.get(skill.key, {}).get(skill.version)
            if held is not None and held.fingerprint() != skill.fingerprint():
                msg = (
                    f"{skill.key} {skill.version} is registered already, as something else: "
                    "a new contract is a new version"
                )
                raise SkillError(msg)
        for skill in skills:
            self._skills.setdefault(skill.key, {})[skill.version] = skill

    def versions(self, key: str) -> list[Skill]:
        """Every version of one, the latest first."""
        return sorted(
            self._skills.get(key, {}).values(), key=lambda s: semver(s.version), reverse=True
        )

    def find(self, key: str, version: str | None = None) -> Skill | None:
        """The version asked — 1.2.0; or 1, 1.2: the latest of them — or,
        none asked, the one a caller gets: the latest active, else the
        latest deprecated, else the latest, to say it does not run."""
        held = self.versions(key)
        if version:
            wanted = version.split(".")
            held = [s for s in held if s.version.split(".")[: len(wanted)] == wanted]
        for runs in (Lifecycle.ACTIVE, Lifecycle.DEPRECATED):
            for skill in held:
                if skill.lifecycle is runs:
                    return skill
        return held[0] if held else None

    def skills(self) -> list[Skill]:
        """Each skill, as a caller gets it — by key."""
        return [s for key in sorted(self._skills) if (s := self.find(key)) is not None]


REGISTRY = SkillRegistry()


def register(*skills: Skill) -> None:
    """A module's own skills, registered with LEKA's when it is imported."""
    REGISTRY.register(*skills)


def find_skill(key: str, version: str | None = None) -> Skill | None:
    return REGISTRY.find(key, version)


def all_skills() -> list[Skill]:
    return REGISTRY.skills()


def skill_versions(key: str) -> list[Skill]:
    return REGISTRY.versions(key)


async def connected_sources(session: AsyncSession, workspace_id: uuid.UUID) -> frozenset[str]:
    """The kinds of source a workspace reads from, as the catalogue says."""
    return frozenset(await WorkspaceCatalogueRepository(session, workspace_id).connected())


def missing_sources(skill: Skill, connected: Collection[str]) -> list[tuple[str, ...]]:
    """Each group of its prerequisites none of which is connected."""
    return [group for group in skill.sources if not set(group) & set(connected)]


async def permitted(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID | None
) -> frozenset[str]:
    """What a person may do here, their role read now — nothing once they
    have no seat. For no one: what LEKA reads with, a member's."""
    if user_id is None:
        return LEKA
    seat = await MembershipRepository(session, workspace_id).get_for_user(user_id)
    if seat is None:
        return frozenset()
    return frozenset(p.value for p in ROLE_PERMISSIONS[seat.role])


# ── running one ──────────────────────────────────────────────────────────────

MESSAGES = {
    "not_found": "No such skill, or no such version.",
    "not_runnable": "This version does not run: it is {lifecycle}.",
    "not_permitted": "Running it takes the permission {permission}.",
    "unavailable": "It needs a source connected: {missing}.",
    "invalid_input": "What it was given is not what it takes.",
    "invalid_output": "It gave something other than what it promised.",
    "timed_out": "No answer in {timeout:g} s.",
    "error": "It failed ({error}).",
}


@dataclass(frozen=True)
class SkillOutcome:
    """What came of running a skill."""

    # succeeded, refused, failed, timed_out
    status: str
    key: str
    version: str | None = None
    output: BaseModel | None = None
    reason: str | None = None
    message: str | None = None
    errors: tuple[Mapping[str, str], ...] = ()
    deprecated: bool = False
    latency_ms: int = 0
    run_id: uuid.UUID | None = None

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"

    @property
    def cited(self) -> tuple[Cited, ...]:
        found = getattr(self.output, "cited", None) if self.ok else None
        return tuple(found or ())

    @property
    def signals(self) -> tuple[Signal, ...]:
        found = getattr(self.output, "signals", None) if self.ok else None
        return tuple(found or ())

    def said(self) -> dict[str, Any]:
        """As a model reads it: what it gave, but what it cited — or why
        not, each error said."""
        if self.ok and self.output is not None:
            return self.output.model_dump(mode="json", exclude={"cited"})
        said: dict[str, Any] = {"error": self.message or self.reason or self.status}
        if self.errors:
            said["errors"] = [dict(e) for e in self.errors]
        return said


def _errors(error: ValidationError) -> tuple[Mapping[str, str], ...]:
    return tuple(
        {
            "field": ".".join(str(part) for part in e["loc"]) or "(all)",
            "code": e["type"],
            "message": e["msg"],
        }
        for e in error.errors()[:10]
    )


def _said_as_text(value: object) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _json(value: object) -> Any:
    """As JSON keeps it: dates in ISO 8601, ids as text."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=_said_as_text))


class SkillRuntime:
    """Skills run for one caller — a person's request, LEKA's analyst on an
    intention — with what that caller may do. Every run kept in `session`;
    each skill reads in its own."""

    def __init__(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        *,
        permissions: Collection[str],
        by: uuid.UUID | None,
        caller: str,
        ref: str | None = None,
        now: datetime | None = None,
        registry: SkillRegistry = REGISTRY,
    ) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._permissions = frozenset(permissions)
        self._by = by
        self._caller = caller
        self._ref = ref
        self._now = now
        self._registry = registry
        self._kept: dict[uuid.UUID, SkillRun] = {}
        self._connected: frozenset[str] | None = None

    async def connected(self) -> frozenset[str]:
        """The kinds of source the workspace reads from — read once."""
        if self._connected is None:
            self._connected = await connected_sources(self._session, self._workspace_id)
        return self._connected

    def kept(self, run_id: uuid.UUID) -> SkillRun | None:
        """A run this runtime kept, as it is kept."""
        return self._kept.get(run_id)

    async def run(
        self,
        key: str,
        inputs: Mapping[str, Any] | BaseModel,
        *,
        version: str | None = None,
    ) -> SkillOutcome:
        """The skill run, or why not, as a status — never raises for what
        the skill did; kept, whatever came of it."""
        at = datetime.now(UTC)
        started = time.monotonic()
        given = _json(
            inputs.model_dump(mode="json") if isinstance(inputs, BaseModel) else dict(inputs)
        )
        skill = self._registry.find(key, version)
        outcome = await self._outcome(key, skill, given)
        outcome = replace(
            outcome,
            latency_ms=max(0, round((time.monotonic() - started) * 1000)),
            run_id=uuid.uuid4(),
        )
        await self._keep(skill, outcome, given, at)
        return outcome

    async def _outcome(
        self, key: str, skill: Skill | None, given: Mapping[str, Any]
    ) -> SkillOutcome:
        def said(status: str, reason: str, **values: object) -> SkillOutcome:
            errors = values.pop("errors", ())
            return SkillOutcome(
                status,
                key,
                skill.version if skill is not None else None,
                reason=reason,
                message=MESSAGES.get(reason, "{error}").format(**values),
                errors=errors,  # type: ignore[arg-type]
            )

        if skill is None:
            return said("refused", "not_found")
        if skill.lifecycle not in RUNNABLE:
            return said("refused", "not_runnable", lifecycle=skill.lifecycle.value)
        if skill.permission not in self._permissions:
            return said("refused", "not_permitted", permission=skill.permission)
        missing = missing_sources(skill, await self.connected()) if skill.sources else []
        if missing:
            return said(
                "refused",
                "unavailable",
                missing="; ".join(" or ".join(group) for group in missing),
                errors=tuple(
                    {
                        "field": "sources",
                        "code": "missing_source",
                        "message": f"one of {', '.join(group)}",
                    }
                    for group in missing
                ),
            )
        try:
            value = skill.input.model_validate(given)
        except ValidationError as error:
            return said("refused", "invalid_input", errors=_errors(error))
        try:
            output = await asyncio.wait_for(self._call(skill, value), timeout=skill.timeout)
        except UnknownThingError as error:
            return said("refused", "unknown", error=str(error) or "LEKA knows no such thing.")
        except TimeoutError:
            return said("timed_out", "timed_out", timeout=skill.timeout)
        except Exception as error:
            logger.exception("skill_failed", skill=skill.key, version=skill.version)
            return said("failed", "error", error=type(error).__name__)
        try:
            kept = skill.output.model_validate(
                output.model_dump() if isinstance(output, BaseModel) else output
            )
        except ValidationError as error:
            logger.warning("skill_broke_its_contract", skill=skill.key, version=skill.version)
            return said("failed", "invalid_output", errors=_errors(error))
        return SkillOutcome(
            "succeeded",
            key,
            skill.version,
            output=kept,
            deprecated=skill.lifecycle is Lifecycle.DEPRECATED,
        )

    async def _call(self, skill: Skill, given: BaseModel) -> BaseModel:
        """In its own session, in the workspace's scope — read only, as the
        database holds the transaction: a skill changes nothing."""
        with workspace_scope(self._workspace_id):
            async with session_factory() as session:
                await session.execute(text("SET TRANSACTION READ ONLY"))
                try:
                    return await skill.run(
                        given,
                        Call(
                            self._workspace_id,
                            session,
                            self._now or clock(),
                            self._by,
                            self._caller,
                        ),
                    )
                finally:
                    await session.rollback()

    async def _keep(
        self,
        skill: Skill | None,
        outcome: SkillOutcome,
        given: Mapping[str, Any],
        at: datetime,
    ) -> None:
        output = (
            outcome.output.model_dump(mode="json", exclude={"cited"})
            if outcome.output is not None
            else None
        )
        size = len(json.dumps(output, ensure_ascii=False)) if output is not None else 0
        asked = len(json.dumps(given, ensure_ascii=False))
        detail = {
            "message": outcome.message,
            "errors": [dict(e) for e in outcome.errors],
            "cited": len(outcome.cited),
            "size": size,
            "deprecated": outcome.deprecated,
        }
        row = SkillRun(
            workspace_id=self._workspace_id,
            id=outcome.run_id,
            key=outcome.key[:100],
            version=outcome.version,
            fingerprint=skill.fingerprint() if skill is not None else None,
            status=outcome.status,
            reason=outcome.reason,
            caller=self._caller[:100],
            ref=self._ref[:100] if self._ref else None,
            run_by=self._by,
            inputs=dict(given) if asked <= INPUTS_KEPT else {"left_out": asked},
            output=output if size <= OUTPUT_KEPT else None,
            detail={k: v for k, v in detail.items() if v},
            latency_ms=outcome.latency_ms,
            at=at,
        )
        self._session.add(row)
        self._kept[row.id] = row
        await self._session.flush()

    def tool(
        self,
        key: str,
        *,
        fill: Mapping[str, Any] | None = None,
        cited: Callable[[Sequence[Cited]], None] | None = None,
    ) -> RuntimeTool:
        """The skill as a model may call it — each call through run():
        checked, kept. `fill`: what the caller knows that the model may
        leave out (the period asked…). What it read, citable, to `cited`."""
        skill = self._registry.find(key)
        if skill is None:
            msg = f"No skill {key!r}."
            raise SkillError(msg)
        version = skill.version

        async def handler(arguments: Mapping[str, Any]) -> str:
            given = dict(arguments)
            for name, value in (fill or {}).items():
                if given.get(name) is None and value is not None:
                    given[name] = value
            outcome = await self.run(key, given, version=version)
            if cited is not None and outcome.cited:
                cited(outcome.cited)
            return json.dumps(outcome.said(), ensure_ascii=False, default=str)

        return RuntimeTool(
            skill.key, skill.summary, tool_schema(skill.input), handler, skill.effect
        )


async def skill_runs(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    key: str | None = None,
    ref: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
) -> list[SkillRun]:
    """The workspace's skill runs, the latest first: of one skill, about one
    thing, in a period."""
    query = select(SkillRun).where(SkillRun.workspace_id == workspace_id)
    if key is not None:
        query = query.where(SkillRun.key == key)
    if ref is not None:
        query = query.where(SkillRun.ref == ref)
    if since is not None:
        query = query.where(SkillRun.at >= since)
    if until is not None:
        query = query.where(SkillRun.at <= until)
    rows = await session.execute(query.order_by(SkillRun.at.desc()).limit(limit))
    return list(rows.scalars())


# ── as they are read ─────────────────────────────────────────────────────────


def skill_read(
    skill: Skill, permissions: Collection[str], connected: Collection[str] = ()
) -> SkillRead:
    """A skill as a person reads it — whether they may run it here: their
    permission, its lifecycle, its prerequisites connected."""
    contract = skill.contract()
    missing = missing_sources(skill, connected)
    return SkillRead(
        key=skill.key,
        version=skill.version,
        title=skill.title,
        summary=skill.summary,
        category=skill.category,
        effect=skill.effect,
        permission=skill.permission,
        usable=skill.permission in permissions and skill.lifecycle in RUNNABLE and not missing,
        lifecycle=skill.lifecycle.value,
        timeout=skill.timeout,
        origin=skill.origin,
        limitations=list(skill.limitations),
        reads=list(skill.reads),
        sources=[list(group) for group in skill.sources],
        missing_sources=[list(group) for group in missing],
        fingerprint=skill.fingerprint(),
        input_schema=contract["input"],
        output_schema=contract["output"],
        versions=[
            SkillVersionRead(
                version=s.version, lifecycle=s.lifecycle.value, fingerprint=s.fingerprint()
            )
            for s in REGISTRY.versions(skill.key)
        ],
    )


def run_read(
    run: SkillRun, *, by: uuid.UUID | None, output: dict[str, Any] | None = None
) -> SkillRunRead:
    """A skill run as a person reads it — `output`: what it gave, when it
    was too large to keep."""
    detail = run.detail or {}
    errors = detail.get("errors")
    return SkillRunRead(
        id=run.id,
        key=run.key,
        version=run.version,
        status=run.status,
        reason=run.reason,
        message=str(detail["message"]) if detail.get("message") else None,
        errors=[SkillRunError.model_validate(e) for e in errors]
        if isinstance(errors, list)
        else [],
        caller=run.caller,
        ref=run.ref,
        run_by=run.run_by,
        mine=by is not None and run.run_by == by,
        inputs=run.inputs,
        output=output if output is not None else run.output,
        cited=int(str(detail.get("cited") or 0)),
        deprecated=bool(detail.get("deprecated")),
        latency_ms=run.latency_ms,
        at=run.at,
    )


# ── to an agent (LEKA-401) ───────────────────────────────────────────────────


def agent_skill_tools(
    definition: Definition, registry: SkillRegistry = REGISTRY
) -> tuple[list[AgentTool], list[Withheld]]:
    """The skills an agent names, as tools it may be offered — each under
    its key, needing its permission. One LEKA does not have, or that reads a
    kind of thing the agent may not (or anything at all), is withheld, said
    why: an agent reads only what its front matter says it is about."""
    given: list[AgentTool] = []
    kept: list[Withheld] = []
    mine = set(definition.entity_types)
    for key in definition.skills:
        skill = registry.find(key)
        if skill is None or skill.lifecycle not in RUNNABLE:
            kept.append(Withheld(key, "unknown"))
        elif not skill.reads or not set(skill.reads) <= mine:
            kept.append(Withheld(key, "out_of_scope"))
        else:
            given.append(
                AgentTool(
                    name=skill.key,
                    description=skill.summary,
                    parameters=tool_schema(skill.input),
                    permission=skill.permission,
                    effect="read",
                )
            )
    return given, kept


def skill_handlers(
    runtime: SkillRuntime, keys: Sequence[str]
) -> dict[str, Callable[[Mapping[str, Any]], Awaitable[Answer]]]:
    """Each skill, as an agent's tool calls it: through the runtime —
    checked, kept — answering as a tool does."""

    def bind(key: str) -> Callable[[Mapping[str, Any]], Awaitable[Answer]]:
        async def call(arguments: Mapping[str, Any]) -> Answer:
            outcome = await runtime.run(key, arguments)
            said = json.dumps(outcome.said(), ensure_ascii=False, default=str)
            if outcome.ok:
                return Answer(said, "ok")
            return Answer(
                said, "refused" if outcome.status == "refused" else "failed", outcome.reason
            )

        return call

    return {key: bind(key) for key in keys}
