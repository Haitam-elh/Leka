"""What a capability is (LEKA-393), pure: one model for everything LEKA can
do — its own rules over the company model (LEKA-388) and the agents written
as markdown (ADR 004) — so that what routes an intention (LEKA-398) and what
runs it (LEKA-395) read the same thing.

    defined      key, title, when to use it, category, kind, version, its
                 contract (what it takes, what it gives), what it needs
                 (sources, a model), who may use it, what calls for it
    lifecycle    draft ─▶ review ─▶ active ⇄ deprecated ─▶ retired; only
                 active and deprecated run; retired is final
    versioned    semver; what it is, fingerprinted — a change of what it
                 does without a new version is refused
    available    for this workspace and this person, now: each reason it is
                 not said, never assumed
    discovered   by goal, kind of intention, what it acts on, words — each
                 match with why

Nothing here reads a file or a database: the loader and the providers give
definitions, the catalogue keeps their history, this decides.
"""

from __future__ import annotations

import enum
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field

KEY = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
WORD = re.compile(r"^[a-z][a-z0-9_]*$")


class DefinitionError(ValueError):
    """A capability that cannot be registered as said."""


class Kind(enum.StrEnum):
    """How it runs: LEKA's own rules; LEKA's own, written by a language
    model through the gateway (LEKA-394); or an agent — instructions a model
    follows (LEKA-395)."""

    RULES = "rules"
    MODEL = "model"
    AGENT = "agent"
    # Several of the above composed into one controlled run (LEKA-397).
    WORKFLOW = "workflow"


class Lifecycle(enum.StrEnum):
    DRAFT = "draft"
    # A vendor skill awaiting its line-by-line review (agents/README.md).
    REVIEW = "review"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


# Where a capability may go from where it is. Retired is final: a capability
# taken out of service comes back as a new one, or not at all.
TRANSITIONS: Mapping[Lifecycle, frozenset[Lifecycle]] = {
    Lifecycle.DRAFT: frozenset({Lifecycle.REVIEW, Lifecycle.ACTIVE, Lifecycle.RETIRED}),
    Lifecycle.REVIEW: frozenset({Lifecycle.DRAFT, Lifecycle.ACTIVE, Lifecycle.RETIRED}),
    Lifecycle.ACTIVE: frozenset({Lifecycle.DEPRECATED, Lifecycle.RETIRED}),
    Lifecycle.DEPRECATED: frozenset({Lifecycle.ACTIVE, Lifecycle.RETIRED}),
    Lifecycle.RETIRED: frozenset(),
}
RUNNABLE = frozenset({Lifecycle.ACTIVE, Lifecycle.DEPRECATED})


def may_move(before: Lifecycle, after: Lifecycle) -> bool:
    return before == after or after in TRANSITIONS[before]


# What it is about, for the catalogue (mockup 13).
CATEGORIES = (
    "architecture",
    "development",
    "infrastructure",
    "operations",
    "security",
    "compliance",
    "data",
    "documentation",
    "project_management",
    "business",
    "knowledge",
)
FIELD_TYPES = ("text", "number", "boolean", "choice", "entity")
OUTPUTS = ("finding", "analysis", "document", "proposal")
# diff: a change to a repository's code, shown as one (the code-change agent);
# html: screens drawn as pages, before and after (the designer).
FORMATS = ("json", "markdown", "pptx", "pdf", "docx", "xlsx", "csv", "diff", "html")
MODES = ("read_only", "proposes_action")
RISKS = ("low", "medium", "high")


def semver(version: str) -> tuple[int, int, int]:
    found = SEMVER.match(version)
    if not found:
        msg = f"version must be semver (1.2.3), got {version!r}"
        raise DefinitionError(msg)
    major, minor, patch = (int(part) for part in found.groups())
    return major, minor, patch


@dataclass(frozen=True)
class Input:
    """One thing it takes."""

    name: str
    type: str = "text"
    required: bool = True
    description: str = ""
    choices: tuple[str, ...] = ()
    # An entity's: of which types.
    entity_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class Contract:
    """What it takes, and what it gives."""

    inputs: tuple[Input, ...] = ()
    output: str = "finding"
    formats: tuple[str, ...] = ("json",)


@dataclass(frozen=True)
class ModelNeed:
    """What the model that runs it must be able to do (LEKA-394): the
    router matches it against the models a workspace can reach."""

    structured: bool = False
    tools: bool = False
    # Tokens it takes in, at most: instructions, context, question.
    context: int = 0
    # The least quality it accepts: 1 enough to classify, 2 good analysis,
    # 3 the best.
    quality: int = 1


@dataclass(frozen=True)
class Definition:
    """One capability, one version."""

    key: str
    title: str
    summary: str  # when to use it: what routing reads first
    category: str
    kind: Kind
    version: str
    lifecycle: Lifecycle
    origin: str = "internal"
    contract: Contract = field(default_factory=Contract)
    # Each, a source it needs connected — one of several when they are
    # alternatives ("confluence|microsoft_365").
    sources: tuple[tuple[str, ...], ...] = ()
    model: bool = False
    model_needs: ModelNeed = field(default_factory=ModelNeed)
    permission: str = "intention:create"
    mode: str = "read_only"
    risk: str = "low"
    # What calls for it: the goals of an intention (LEKA-385), its kinds
    # (LEKA-373), what it acts on, and how people ask for it.
    goals: frozenset[str] = frozenset()
    kinds: frozenset[str] = frozenset()
    entity_types: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    # Run whatever the intention: what any answer starts from.
    always: bool = False
    # An agent's instructions: kept here, never sent to a browser. A
    # workflow's: its steps, canonical (LEKA-397).
    instructions: str | None = None
    path: str | None = None
    # A workflow's: the capabilities its steps use (LEKA-397).
    uses: tuple[str, ...] = ()
    # An agent's: the tools it may be offered — every read-only one when it
    # declares none (LEKA-400).
    tools: tuple[str, ...] = ()
    # An agent's: the skills it may be offered — none unless named (LEKA-401).
    skills: tuple[str, ...] = ()
    # An agent's: what LEKA draws of what it delivers — "architecture_deck":
    # its PowerPoint and PDF (capabilities/deliverables).
    renders: str | None = None
    # An agent's: its rounds of tool calls, when not the runtime's default.
    rounds: int | None = None
    # An agent's: the library of guides it reads while it runs (read_method),
    # a directory under agents/_library/.
    method: str | None = None

    def fingerprint(self) -> str:
        """What it is and does, hashed: everything but where it stands in
        its lifecycle — moving it needs no new version, changing it does."""
        said = asdict(self)
        said.pop("lifecycle")
        said.pop("path")
        # Added after capabilities were registered (LEKA-394): at its default
        # it says nothing new — what was registered stays what it is.
        if self.model_needs == ModelNeed():
            said.pop("model_needs")
        # Added with workflows (LEKA-397): empty, it says nothing new.
        if not self.uses:
            said.pop("uses")
        # Added with the agent library (LEKA-400): none, it says nothing new.
        if not self.tools:
            said.pop("tools")
        # Added with the skill library (LEKA-401): none, it says nothing new.
        if not self.skills:
            said.pop("skills")
        # Added with the architect's deliverables: none, it says nothing new.
        if self.renders is None:
            said.pop("renders")
        # Added with the architect's collection (2026-10-14): none, nothing new.
        if self.rounds is None:
            said.pop("rounds")
        # Added with the designer's library: none, it says nothing new.
        if self.method is None:
            said.pop("method")
        said["goals"] = sorted(self.goals)
        said["kinds"] = sorted(self.kinds)
        canonical = json.dumps(said, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def described(self) -> dict[str, object]:
        """What the catalogue keeps of it — its instructions only hashed."""
        said = asdict(self)
        said["instructions"] = None
        said["goals"] = sorted(self.goals)
        said["kinds"] = sorted(self.kinds)
        said["kind"] = self.kind.value
        said["lifecycle"] = self.lifecycle.value
        return said


def validated(
    definition: Definition,
    *,
    entity_types: Iterable[str] = (),
    source_kinds: Iterable[str] = (),
    permissions: Iterable[str] = (),
) -> Definition:
    """A definition as it can be registered — DefinitionError otherwise.
    What it names is checked against what LEKA knows, when told."""
    d = definition
    if not KEY.match(d.key):
        msg = f"key must be kebab-case, got {d.key!r}"
        raise DefinitionError(msg)
    semver(d.version)
    if not d.title.strip() or len(d.title) > 120:
        msg = f"{d.key}: a title, at most 120 characters"
        raise DefinitionError(msg)
    if len(d.summary.strip()) < 20:
        msg = f"{d.key}: say when to use it, in a sentence"
        raise DefinitionError(msg)
    if d.category not in CATEGORIES:
        msg = f"{d.key}: unknown category {d.category!r}"
        raise DefinitionError(msg)
    if d.mode not in MODES or d.risk not in RISKS:
        msg = f"{d.key}: mode {d.mode!r} or risk {d.risk!r} unknown"
        raise DefinitionError(msg)
    if d.contract.output not in OUTPUTS or not set(d.contract.formats) <= set(FORMATS):
        msg = f"{d.key}: unknown output {d.contract.output!r} or format"
        raise DefinitionError(msg)
    names = [i.name for i in d.contract.inputs]
    if len(names) != len(set(names)):
        msg = f"{d.key}: two inputs share a name"
        raise DefinitionError(msg)
    for item in d.contract.inputs:
        if not WORD.match(item.name) or item.type not in FIELD_TYPES:
            msg = f"{d.key}: input {item.name!r} of type {item.type!r}"
            raise DefinitionError(msg)
        if (item.type == "choice") != bool(item.choices):
            msg = f"{d.key}: a choice has choices, and only a choice"
            raise DefinitionError(msg)
    for word in (*d.goals, *d.kinds):
        if not WORD.match(word):
            msg = f"{d.key}: {word!r} is not a goal or a kind"
            raise DefinitionError(msg)
    if d.kind in (Kind.AGENT, Kind.MODEL) and not d.model:
        msg = f"{d.key}: an agent, or a capability a model writes, is run by a model"
        raise DefinitionError(msg)
    if (d.kind is Kind.WORKFLOW) != bool(d.uses):
        msg = f"{d.key}: a workflow uses capabilities, and only a workflow"
        raise DefinitionError(msg)
    known_types = set(entity_types)
    for kind in (*d.entity_types, *(t for i in d.contract.inputs for t in i.entity_types)):
        if known_types and kind not in known_types:
            msg = f"{d.key}: unknown entity type {kind!r}"
            raise DefinitionError(msg)
    known_sources = set(source_kinds)
    for group in d.sources:
        if not group or (known_sources and not set(group) <= known_sources):
            msg = f"{d.key}: unknown source in {'|'.join(group)!r}"
            raise DefinitionError(msg)
    known_permissions = set(permissions)
    if known_permissions and d.permission not in known_permissions:
        msg = f"{d.key}: unknown permission {d.permission!r}"
        raise DefinitionError(msg)
    return definition


# ── available ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Situation:
    """Where it would run: the workspace, the person, LEKA itself."""

    enabled: bool = True
    connected: frozenset[str] = frozenset()
    # A model that can do what it needs can be reached here (LEKA-394).
    model: bool = False
    # An agent can be run: its runtime is there (LEKA-395) — said, so a
    # process without it says no_runtime.
    runtime: bool = False
    permissions: frozenset[str] = frozenset()
    # Why an agent may not run in this workspace by what it pays for
    # (2026-10-14): plan_required, not_owned — None when it may.
    owned: str | None = None


@dataclass(frozen=True)
class Reason:
    # lifecycle, refused, disabled, missing_source, no_model, no_runtime,
    # not_permitted · deprecated
    code: str
    detail: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Availability:
    available: bool
    reasons: tuple[Reason, ...] = ()  # why not
    notes: tuple[Reason, ...] = ()  # available, but said: deprecated

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(r.code for r in self.reasons)


def availability(
    definition: Definition, situation: Situation, *, refused: str | None = None
) -> Availability:
    """Whether it can be used here, by this person, now — and every reason
    it cannot, not only the first. Refused by the catalogue (changed without
    a new version, an older version, a move its lifecycle does not allow):
    not used."""
    d = definition
    reasons: list[Reason] = []
    notes: list[Reason] = []
    if refused:
        reasons.append(Reason("refused", {"why": refused}))
    if d.lifecycle not in RUNNABLE:
        reasons.append(Reason("lifecycle", {"lifecycle": d.lifecycle.value}))
    elif d.lifecycle is Lifecycle.DEPRECATED:
        notes.append(Reason("deprecated"))
    if not situation.enabled:
        reasons.append(Reason("disabled"))
    for group in d.sources:
        if not set(group) & situation.connected:
            reasons.append(Reason("missing_source", {"any_of": list(group)}))
    if d.model and not situation.model:
        reasons.append(Reason("no_model"))
    if d.kind in (Kind.AGENT, Kind.WORKFLOW) and not situation.runtime:
        reasons.append(Reason("no_runtime"))
    if d.permission not in situation.permissions:
        reasons.append(Reason("not_permitted", {"permission": d.permission}))
    if d.kind is Kind.AGENT and situation.owned:
        reasons.append(Reason(situation.owned))
    return Availability(not reasons, tuple(reasons), tuple(notes))


# ── what it takes ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InputError:
    name: str
    code: str  # missing, unknown, type, choice


def check_input(contract: Contract, given: Mapping[str, object]) -> list[InputError]:
    """What is wrong with what it is given — nothing when it can run."""
    errors: list[InputError] = []
    expected = {i.name: i for i in contract.inputs}
    for name in given:
        if name not in expected:
            errors.append(InputError(name, "unknown"))
    for item in contract.inputs:
        value = given.get(item.name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if item.required:
                errors.append(InputError(item.name, "missing"))
            continue
        ok = {
            "text": isinstance(value, str),
            "number": isinstance(value, int | float) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "choice": isinstance(value, str),
            "entity": isinstance(value, str),
        }[item.type]
        if not ok:
            errors.append(InputError(item.name, "type"))
        elif item.type == "choice" and value not in item.choices:
            errors.append(InputError(item.name, "choice"))
    return errors


# ── discovered ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Query:
    """What a router knows of what is asked."""

    goal: str | None = None
    kind: str | None = None
    entity_types: frozenset[str] = frozenset()
    text: str | None = None
    categories: frozenset[str] = frozenset()
    available_only: bool = False


@dataclass(frozen=True)
class Match:
    definition: Definition
    score: float
    reasons: tuple[str, ...]  # goal, kind, entity:<type>, words, always
    availability: Availability


def _words(text: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", plain) if len(w) > 2}


def mentions(definition: Definition, text: str) -> bool:
    """Whether every word searched is in what it is called, says, or is
    asked as — accents and case aside."""
    wanted = _words(text)
    d = definition
    said = _words(" ".join((d.key.replace("-", " "), d.title, d.summary, *d.examples)))
    return wanted <= said or all(any(w in s for s in said) for w in wanted)


def discover(
    definitions: Sequence[Definition],
    query: Query,
    availabilities: Mapping[str, Availability],
) -> list[Match]:
    """The capabilities that answer what is asked, the best first: its goal
    (3), its kind (2), what it acts on (1 each, at most 2), the words it is
    asked in (1 each, at most 3). Retired never; unavailable when asked
    not to; nothing that matches nothing, unless it always runs."""
    asked = _words(query.text or "")
    found: list[Match] = []
    for d in definitions:
        if d.lifecycle is Lifecycle.RETIRED:
            continue
        if query.categories and d.category not in query.categories:
            continue
        able = availabilities.get(d.key, Availability(False, (Reason("unknown"),)))
        if query.available_only and not able.available:
            continue
        score = 0.0
        why: list[str] = []
        if query.goal and query.goal in d.goals:
            score += 3
            why.append("goal")
        if query.kind and query.kind in d.kinds:
            score += 2
            why.append("kind")
        acts_on = [t for t in d.entity_types if t in query.entity_types][:2]
        score += len(acts_on)
        why.extend(f"entity:{t}" for t in acts_on)
        if asked:
            said = _words(" ".join((d.title, d.summary, *d.examples)))
            common = len(asked & said)
            if common:
                score += min(common, 3)
                why.append("words")
        if d.always:
            why.append("always")
        if score or d.always:
            found.append(Match(d, score, tuple(why), able))
    found.sort(key=lambda m: (-m.score, not m.availability.available, m.definition.key))
    return found
