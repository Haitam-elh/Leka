"""Workflows (LEKA-397), pure: several capabilities composed into one
controlled, multi-step execution — what a workflow is, how it is checked,
in what order its steps run, which run, and what a run's state is.

    a workflow      key, title, when to use it, version, its lifecycle, what
                    it takes, its steps — a capability catalogue entry of
                    kind `workflow`, so its versions are kept like any other
    a step          an id; the capability it uses — or a skill,
                    `skill:<key>` (LEKA-401); what it is given (the
                    workflow's inputs, or literals); the steps it runs after;
                    the condition it runs on; how often it is retried; what
                    its failure does to the workflow
    a condition     structured, never code: a step's status, a code a step
                    found, an input's value — and all, any, not of them
    the order       its steps in the order of their dependencies — a cycle,
                    a step after one that does not exist, a capability
                    LEKA does not have: refused when it loads

    a run           queued ─▶ running ─▶ succeeded · failed · cancelled
    a step's run    pending ─▶ running ─▶ succeeded · failed
                       │         └─▶ (retried while attempts remain)
                       ├─▶ skipped      its condition does not hold
                       └─▶ not_reached  the workflow stopped before it

A step runs once every step it runs after has ended — succeeded, failed
and continued past, or skipped — and when its condition holds. One that
fails, its attempts spent, stops the workflow (`on_failure: stop`, the
default) or is passed (`continue`). A failed run is retried from where it
failed: what succeeded stays.

Nothing here reads a file, a database or a model: loader reads the files,
workflow_runs.py runs them.
"""

from __future__ import annotations

import enum
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from leka.capabilities.definition import (
    CATEGORIES,
    KEY,
    WORD,
    Contract,
    Definition,
    DefinitionError,
    Input,
    Kind,
    Lifecycle,
    semver,
)
from leka.capabilities.skills import find_skill

STEP = re.compile(r"^[a-z][a-z0-9_]*$")
MOST_STEPS = 20
MOST_ATTEMPTS = 3
FAILURE_POLICIES = ("stop", "continue")
STATUSES_SAID = ("succeeded", "failed", "skipped")


class WorkflowError(DefinitionError):
    """A workflow that cannot be registered as said."""


# A step that uses a skill (LEKA-401) names it so: `uses: skill:<key>`.
SKILL = "skill:"


def skill_of(uses: str) -> str | None:
    """The skill a step uses — none when it uses a capability."""
    return uses.removeprefix(SKILL) if uses.startswith(SKILL) else None


# ── conditions ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Condition:
    """When a step runs — structured, never code.

    `step` + `status`: that step ended so (succeeded, failed, skipped) ·
    `step` + `found`: that step found this code · `input` + `equals`: the
    workflow was given this · `all`, `any`: each, one of · `negate`: not.
    """

    step: str | None = None
    status: tuple[str, ...] = ()
    found: str | None = None
    input: str | None = None
    equals: object = None
    all: tuple[Condition, ...] = ()
    any: tuple[Condition, ...] = ()
    negate: Condition | None = None

    def refs(self) -> set[str]:
        """The steps it reads."""
        found = {self.step} if self.step else set()
        for part in (*self.all, *self.any, *((self.negate,) if self.negate else ())):
            found |= part.refs()
        return found

    def inputs(self) -> set[str]:
        found = {self.input} if self.input else set()
        for part in (*self.all, *self.any, *((self.negate,) if self.negate else ())):
            found |= part.inputs()
        return found


def condition_of(said: object, where: str) -> Condition:
    """A condition as a file says it."""
    if not isinstance(said, Mapping) or not said:
        msg = f"{where}: a condition is an object"
        raise WorkflowError(msg)
    known = {"step", "status", "found", "input", "equals", "all", "any", "not"}
    unknown = set(said) - known
    if unknown:
        msg = f"{where}: unknown {sorted(unknown)} in a condition"
        raise WorkflowError(msg)
    if "all" in said or "any" in said:
        key = "all" if "all" in said else "any"
        parts = said[key]
        if not isinstance(parts, list) or not parts or len(said) != 1:
            msg = f"{where}: {key} is a non-empty list, alone"
            raise WorkflowError(msg)
        found = tuple(condition_of(p, f"{where}.{key}") for p in parts)
        return Condition(all=found) if key == "all" else Condition(any=found)
    if "not" in said:
        if len(said) != 1:
            msg = f"{where}: not is alone"
            raise WorkflowError(msg)
        return Condition(negate=condition_of(said["not"], f"{where}.not"))
    if "step" in said:
        status = said.get("status")
        statuses = tuple(status) if isinstance(status, list) else (status,) if status else ()
        if bool(statuses) == ("found" in said) or set(said) - {"step", "status", "found"}:
            msg = f"{where}: a step condition says its status, or a code it found"
            raise WorkflowError(msg)
        if not set(statuses) <= set(STATUSES_SAID):
            msg = f"{where}: a status is one of {STATUSES_SAID}"
            raise WorkflowError(msg)
        return Condition(step=str(said["step"]), status=statuses, found=said.get("found"))
    if "input" in said and "equals" in said and len(said) == 2:
        return Condition(input=str(said["input"]), equals=said["equals"])
    msg = f"{where}: a condition reads a step, an input, or combines others"
    raise WorkflowError(msg)


@dataclass(frozen=True)
class Ended:
    """A step, as conditions read it once it ended."""

    status: str
    codes: frozenset[str] = frozenset()


def holds(
    condition: Condition | None, ended: Mapping[str, Ended], inputs: Mapping[str, object]
) -> bool:
    if condition is None:
        return True
    c = condition
    if c.all:
        return all(holds(p, ended, inputs) for p in c.all)
    if c.any:
        return any(holds(p, ended, inputs) for p in c.any)
    if c.negate is not None:
        return not holds(c.negate, ended, inputs)
    if c.step is not None:
        said = ended.get(c.step)
        if said is None:
            return False
        if c.found is not None:
            return c.found in said.codes
        return said.status in c.status
    return inputs.get(c.input or "") == c.equals


# ── a workflow ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Value:
    """What a step is given: one of the workflow's inputs, or a literal."""

    input: str | None = None
    literal: object = None


@dataclass(frozen=True)
class Step:
    id: str
    uses: str  # a capability's key
    after: tuple[str, ...] = ()
    when: Condition | None = None
    given: Mapping[str, Value] = field(default_factory=dict)
    attempts: int = 1
    on_failure: str = "stop"
    title: str | None = None


@dataclass(frozen=True)
class Workflow:
    key: str
    title: str
    summary: str
    category: str
    version: str
    lifecycle: Lifecycle
    steps: tuple[Step, ...]
    inputs: tuple[Input, ...] = ()
    permission: str = "intention:create"
    goals: frozenset[str] = frozenset()
    kinds: frozenset[str] = frozenset()
    entity_types: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    path: str | None = None

    def step(self, step_id: str) -> Step:
        return next(s for s in self.steps if s.id == step_id)

    def spec(self) -> dict[str, Any]:
        """What it is, canonically — what its version stands for."""
        return {
            "steps": [
                {
                    "id": s.id,
                    "uses": s.uses,
                    "after": list(s.after),
                    "when": _said(s.when),
                    "given": {k: _said(v) for k, v in sorted(s.given.items())},
                    "attempts": s.attempts,
                    "on_failure": s.on_failure,
                    "title": s.title,
                }
                for s in self.steps
            ],
        }

    def digest(self) -> str:
        canonical = json.dumps(self.spec(), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def definition(self) -> Definition:
        """It, as the catalogue holds it: a capability of kind workflow —
        registered, versioned, available or not, routed to, like any other.
        Its steps are its instructions: fingerprinted, a change without a
        new version refused."""
        return Definition(
            key=self.key,
            title=self.title,
            summary=self.summary,
            category=self.category,
            kind=Kind.WORKFLOW,
            version=self.version,
            lifecycle=self.lifecycle,
            origin="internal",
            contract=Contract(inputs=self.inputs, output="analysis", formats=("json",)),
            permission=self.permission,
            goals=self.goals,
            kinds=self.kinds,
            entity_types=self.entity_types,
            examples=self.examples,
            instructions=json.dumps(self.spec(), sort_keys=True, ensure_ascii=False),
            uses=tuple(dict.fromkeys(s.uses for s in self.steps)),
            path=self.path,
        )


def _said(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Value):
        return {"input": value.input} if value.input is not None else {"value": value.literal}
    if isinstance(value, Condition):
        if value.all:
            return {"all": [_said(p) for p in value.all]}
        if value.any:
            return {"any": [_said(p) for p in value.any]}
        if value.negate is not None:
            return {"not": _said(value.negate)}
        if value.step is not None:
            said: dict[str, object] = {"step": value.step}
            if value.found is not None:
                said["found"] = value.found
            else:
                said["status"] = list(value.status)
            return said
        return {"input": value.input, "equals": value.equals}
    return value


# ── the builder ─────────────────────────────────────────────────────────────


def _value(said: object, where: str) -> Value:
    if isinstance(said, Mapping):
        if set(said) == {"input"}:
            return Value(input=str(said["input"]))
        if set(said) == {"value"}:
            return Value(literal=said["value"])
        msg = f"{where}: a value is {{input: name}}, {{value: literal}} or a literal"
        raise WorkflowError(msg)
    return Value(literal=said)


def step_of(said: Mapping[str, Any], where: str) -> Step:
    known = {"id", "uses", "after", "when", "with", "retry", "on_failure", "title"}
    unknown = set(said) - known
    if unknown:
        msg = f"{where}: unknown {sorted(unknown)} in a step"
        raise WorkflowError(msg)
    retry = said.get("retry") or {}
    if not isinstance(retry, Mapping) or set(retry) - {"attempts"}:
        msg = f"{where}: retry is {{attempts: n}}"
        raise WorkflowError(msg)
    given = said.get("with") or {}
    if not isinstance(given, Mapping):
        msg = f"{where}: with is an object"
        raise WorkflowError(msg)
    after = said.get("after") or []
    return Step(
        id=str(said.get("id") or ""),
        uses=str(said.get("uses") or ""),
        after=tuple(str(a) for a in (after if isinstance(after, list) else [after])),
        when=condition_of(said["when"], f"{where}.when") if "when" in said else None,
        given={str(k): _value(v, f"{where}.with.{k}") for k, v in given.items()},
        attempts=int(retry.get("attempts", 1)),
        on_failure=str(said.get("on_failure") or "stop"),
        title=str(said["title"]) if said.get("title") else None,
    )


def build(said: Mapping[str, Any], *, path: str | None = None) -> Workflow:
    """A workflow from what a file (or a module) says — WorkflowError when
    it cannot be what it says. Its capabilities are checked against the
    catalogue by `validated`."""
    where = path or str(said.get("key") or "workflow")
    known = {
        "key",
        "title",
        "summary",
        "category",
        "version",
        "lifecycle",
        "inputs",
        "steps",
        "permission",
        "goals",
        "kinds",
        "entity_types",
        "examples",
    }
    unknown = set(said) - known
    if unknown:
        msg = f"{where}: unknown {sorted(unknown)}"
        raise WorkflowError(msg)
    steps = said.get("steps")
    if not isinstance(steps, list) or not steps:
        msg = f"{where}: a workflow has steps"
        raise WorkflowError(msg)
    try:
        lifecycle = Lifecycle(str(said.get("lifecycle") or "draft"))
    except ValueError as error:
        msg = f"{where}: unknown lifecycle {said.get('lifecycle')!r}"
        raise WorkflowError(msg) from error
    inputs = tuple(
        Input(
            name=str(i.get("name")),
            type=str(i.get("type") or "text"),
            required=bool(i.get("required", True)),
            description=str(i.get("description") or ""),
            choices=tuple(i.get("choices") or ()),
        )
        for i in (said.get("inputs") or [])
    )
    return Workflow(
        key=str(said.get("key") or ""),
        title=str(said.get("title") or ""),
        summary=str(said.get("summary") or ""),
        category=str(said.get("category") or ""),
        version=str(said.get("version") or ""),
        lifecycle=lifecycle,
        steps=tuple(step_of(s, f"{where}.steps[{n}]") for n, s in enumerate(steps)),
        inputs=inputs,
        permission=str(said.get("permission") or "intention:create"),
        goals=frozenset(said.get("goals") or ()),
        kinds=frozenset(said.get("kinds") or ()),
        entity_types=tuple(said.get("entity_types") or ()),
        examples=tuple(said.get("examples") or ()),
        path=path,
    )


def from_spec(key: str, version: str, spec: Mapping[str, Any]) -> Workflow:
    """A workflow as a run kept it (Workflow.spec): what that run runs,
    whatever its file says since."""
    steps = tuple(
        Step(
            id=str(s["id"]),
            uses=str(s["uses"]),
            after=tuple(s.get("after") or ()),
            when=condition_of(s["when"], f"{key}.{s['id']}") if s.get("when") else None,
            given={
                str(k): _value(v, f"{key}.{s['id']}") for k, v in (s.get("given") or {}).items()
            },
            attempts=int(s.get("attempts") or 1),
            on_failure=str(s.get("on_failure") or "stop"),
            title=s.get("title"),
        )
        for s in spec.get("steps") or []
    )
    return Workflow(
        key=key,
        title=key,
        summary="",
        category="",
        version=version,
        lifecycle=Lifecycle.ACTIVE,
        steps=steps,
    )


def order(workflow: Workflow) -> list[str]:
    """Its steps in the order of their dependencies — as written where
    they do not depend on each other. A cycle refuses it."""
    placed: list[str] = []
    waiting = [s.id for s in workflow.steps]
    while waiting:
        ready = [s for s in waiting if set(workflow.step(s).after) <= set(placed)]
        if not ready:
            msg = f"{workflow.key}: its steps wait on each other ({', '.join(waiting)})"
            raise WorkflowError(msg)
        placed.append(ready[0])
        waiting.remove(ready[0])
    return placed


def validated(workflow: Workflow, known: Mapping[str, Definition]) -> Workflow:
    """It, as it can be registered: its key, version, steps — each using a
    capability LEKA has and that can run in a workflow (LEKA's own rules,
    an agent), given only what that capability takes, after steps that
    exist, on conditions that read steps it runs after and inputs the
    workflow takes — in an order that ends."""
    w = workflow
    if not KEY.match(w.key):
        msg = f"workflow key must be kebab-case, got {w.key!r}"
        raise WorkflowError(msg)
    semver(w.version)
    if not w.title.strip() or len(w.summary.strip()) < 20:
        msg = f"{w.key}: a title, and when to use it in a sentence"
        raise WorkflowError(msg)
    if w.category not in CATEGORIES:
        msg = f"{w.key}: unknown category {w.category!r}"
        raise WorkflowError(msg)
    if len(w.steps) > MOST_STEPS:
        msg = f"{w.key}: {MOST_STEPS} steps at most"
        raise WorkflowError(msg)
    for word in (*w.goals, *w.kinds):
        if not WORD.match(word):
            msg = f"{w.key}: {word!r} is not a goal or a kind"
            raise WorkflowError(msg)
    ids = [s.id for s in w.steps]
    if len(ids) != len(set(ids)):
        msg = f"{w.key}: two steps share an id"
        raise WorkflowError(msg)
    inputs = {i.name for i in w.inputs}
    for s in w.steps:
        where = f"{w.key}.{s.id}"
        if not STEP.match(s.id):
            msg = f"{where}: a step id is a word (snake_case)"
            raise WorkflowError(msg)
        key = skill_of(s.uses)
        if key is not None:
            # A skill (LEKA-401): given only what its contract takes.
            skill = find_skill(key)
            if skill is None:
                msg = f"{where}: no skill {key!r}"
                raise WorkflowError(msg)
            fields = skill.input.model_fields
            takes = set(fields)
            needed = [n for n, f in fields.items() if f.is_required()]
        else:
            used = known.get(s.uses)
            if used is None:
                msg = f"{where}: no capability {s.uses!r}"
                raise WorkflowError(msg)
            if used.kind not in (Kind.RULES, Kind.AGENT):
                msg = f"{where}: {s.uses!r} cannot run as a step (LEKA's own rules, an agent, "
                msg += "or a skill)"
                raise WorkflowError(msg)
            takes = {i.name for i in used.contract.inputs}
            needed = [i.name for i in used.contract.inputs if i.required]
        if set(s.given) - takes:
            msg = f"{where}: {s.uses!r} does not take {sorted(set(s.given) - takes)}"
            raise WorkflowError(msg)
        for name, value in s.given.items():
            if value.input is not None and value.input not in inputs:
                msg = f"{where}.with.{name}: the workflow takes no input {value.input!r}"
                raise WorkflowError(msg)
        missing = [n for n in needed if n not in s.given]
        if missing:
            msg = f"{where}: {s.uses!r} needs {missing}"
            raise WorkflowError(msg)
        unknown = set(s.after) - set(ids)
        if unknown or s.id in s.after:
            msg = f"{where}: after {sorted(unknown or {s.id})}, which is not another step"
            raise WorkflowError(msg)
        if not 1 <= s.attempts <= MOST_ATTEMPTS:
            msg = f"{where}: 1 to {MOST_ATTEMPTS} attempts"
            raise WorkflowError(msg)
        if s.on_failure not in FAILURE_POLICIES:
            msg = f"{where}: on_failure is {' or '.join(FAILURE_POLICIES)}"
            raise WorkflowError(msg)
    order(w)
    for s in w.steps:
        if s.when is None:
            continue
        read, before = s.when.refs(), _ancestors(w, s.id)
        if not read <= before:
            msg = f"{w.key}.{s.id}: its condition reads {sorted(read - before)}, "
            msg += "which it does not run after"
            raise WorkflowError(msg)
        if not s.when.inputs() <= inputs:
            msg = f"{w.key}.{s.id}: its condition reads an input the workflow does not take"
            raise WorkflowError(msg)
    return workflow


def _ancestors(workflow: Workflow, step_id: str) -> set[str]:
    found: set[str] = set()
    todo = list(workflow.step(step_id).after)
    while todo:
        one = todo.pop()
        if one not in found:
            found.add(one)
            todo.extend(workflow.step(one).after)
    return found


# ── a run ──────────────────────────────────────────────────────────────────


class RunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_REACHED = "not_reached"


ENDED = frozenset({StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.SKIPPED})


@dataclass(frozen=True)
class Next:
    """What the engine does next."""

    run: tuple[str, ...] = ()  # steps that can run now
    skip: tuple[str, ...] = ()  # steps whose condition does not hold
    done: bool = False  # nothing left: the workflow ended
    failed: str | None = None  # the step whose failure stops it


def next_steps(
    workflow: Workflow,
    statuses: Mapping[str, StepStatus],
    ended: Mapping[str, Ended],
    inputs: Mapping[str, object],
) -> Next:
    """From where a run stands: what fails it, what is skipped, what runs."""
    for s in workflow.steps:
        if statuses.get(s.id) is StepStatus.FAILED and s.on_failure == "stop":
            return Next(done=True, failed=s.id)
    run: list[str] = []
    skip: list[str] = []
    for step_id in order(workflow):
        if statuses.get(step_id, StepStatus.PENDING) is not StepStatus.PENDING:
            continue
        s = workflow.step(step_id)
        if not all(statuses.get(a) in ENDED for a in s.after):
            continue
        if holds(s.when, ended, inputs):
            run.append(step_id)
        else:
            skip.append(step_id)
    if not run and not skip:
        return Next(done=True)
    return Next(run=tuple(run), skip=tuple(skip))


def outcome(statuses: Mapping[str, StepStatus], workflow: Workflow) -> RunStatus:
    """How a run that ended went: failed when a step that stops it failed."""
    for s in workflow.steps:
        if statuses.get(s.id) is StepStatus.FAILED and s.on_failure == "stop":
            return RunStatus.FAILED
    return RunStatus.SUCCEEDED


def given_to(step: Step, inputs: Mapping[str, object]) -> dict[str, object]:
    """What a step's capability is given: the workflow's inputs it names,
    the literals it says — an input not given left out."""
    said: dict[str, object] = {}
    for name, value in step.given.items():
        if value.input is not None:
            if inputs.get(value.input) is not None:
                said[name] = inputs[value.input]
        else:
            said[name] = value.literal
    return said
