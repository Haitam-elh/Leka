"""LEKA-335: a module reads only the secrets it owns.

`from leka.core.config import settings` hands every module every secret. A
secret seldom leaks through an attacker. It leaks through a log line or a
traceback written by a module that had no reason to hold the value. Here,
each secret names the modules allowed to read it, and CI fails, naming the
file and the line, when any other module does.

Static, on the model of test_module_boundaries.py, for the same reasons:
nothing to pay at runtime, no signature to change in the modules that import
settings, and the failure lands in CI rather than in production.

A READ IS RECOGNISED BY THE ATTRIBUTE NAME, whatever it is read from.
`settings.secret_key`, `cfg.secret_key` and `self.config.secret_key` are the
same read. Renamed imports and aliases change the receiver, never the name.

WHAT IT CANNOT SEE, IT REFUSES. `getattr(settings, name)`, `vars(settings)`
and `settings.model_dump()` read fields whose names are written nowhere, and
an alias of the settings object hides the reads made through it. None of
these can be checked, so each fails on sight instead of passing on trust.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterable, Iterator
from functools import cache, cached_property
from pathlib import Path
from typing import get_args, get_type_hints

import pytest
from pydantic import Secret, SecretBytes, SecretStr

from leka.core.config import Settings

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parent

# Every secret the settings hold, and the only modules allowed to read it.
# A package name covers every module inside it.
#
# The tests below refuse to let this fall behind: a secret-typed field, a
# property returning one, or a URL that can carry a password, with no line
# here, fails CI.
SECRET_OWNERS: dict[str, frozenset[str]] = {
    # Signs what the server hands a client and expects back. Every other
    # module asks leka.core.signing for a signature under its own purpose and
    # never holds the key.
    "secret_key": frozenset({"leka.core.signing"}),
    # The keys to every customer credential stored at rest.
    "encryption_keys": frozenset({"leka.platform.secrets"}),
    "s3_secret_access_key": frozenset({"leka.platform.storage"}),
    "smtp_password": frozenset({"leka.identity.email"}),
    # Stripe (LEKA-431): the one module that calls Stripe and verifies its
    # webhooks; the routes ask it whether payment is open, never the key.
    "stripe_secret_key": frozenset({"leka.billing.subscriptions"}),
    "stripe_webhook_secret": frozenset({"leka.billing.subscriptions"}),
    "resend_api_key": frozenset({"leka.identity.email"}),
    # The DSN is read once, to start the SDK. The events themselves are
    # cleaned by leka.core.logging, which is why this module is not also a
    # reader of secret_values.
    "sentry_dsn": frozenset({"leka.platform.monitoring"}),
    # Architecture rule 7: one place calls a model.
    "google_api_key": frozenset({"leka.capabilities"}),
    "anthropic_api_key": frozenset({"leka.capabilities"}),
    # LEKA's OpenAI key (LEKA-491): the gateway's, as the other providers'.
    "openai_api_key": frozenset({"leka.capabilities"}),
    "mistral_api_key": frozenset({"leka.capabilities"}),
    "llm_api_key": frozenset({"leka.capabilities"}),
    # A managed database or Redis puts its password in the URL, so reading
    # the URL is reading the password.
    "database_url": frozenset(
        {"leka.db.session", "alembic.env", "leka.background.runner", "leka.ops.backup"}
    ),  # background.runner: its own unpooled engine, one per job (see its docstring);
    # ops.backup: pg_dump and pg_restore are given the URL (LEKA-408)
    # Three clients for one server, consolidated by LEKA-334: the job queue
    # moved from leka.platform.jobs to leka.background.jobs, below platform, so
    # that platform itself can enqueue work.
    # LEKA-408: the circuit breakers, and operations — the queues' depth, the
    # alerts' state, the last backup's date.
    "redis_url": frozenset(
        {
            "leka.core.ratelimit",
            "leka.platform.health",
            "leka.background.jobs",
            "leka.core.breaker",
            "leka.ops",
        }
    ),
    # Every value at once, so the log masking can recognise them anywhere.
    # Holding them all is that module's job, and nobody else's.
    "secret_values": frozenset({"leka.core.logging"}),
    # Operations (LEKA-408): who may read the metrics — checked by its route;
    # the backup bucket's key — used by the backup alone.
    "metrics_token": frozenset({"leka.api.ops"}),
    "backup_secret_access_key": frozenset({"leka.ops.backup"}),
}

# Grants nobody exercises yet, on purpose. Any other unused grant is stale:
# a permission handed out for nothing.
# (None since the model gateway, LEKA-394, read the model keys.)
RESERVED: dict[tuple[str, str], str] = {}

# (directory scanned, the directory its module names start from)
SCANNED = (
    (API_ROOT / "leka", API_ROOT),
    (API_ROOT / "alembic", API_ROOT),
    (REPO_ROOT / "scripts", REPO_ROOT),
)

# Where the fields are declared: `self.secret_key` in there is the field, not
# a use of it. Tests are not scanned either. They are not services, and the
# values they read are fakes.
DECLARED_IN = ("leka.core.config", "leka.core.settings")

# Reading one of these off the settings object reads every secret at once.
BULK_READS = frozenset({"__dict__", "__getattribute__", "model_dump", "model_dump_json"})

# The inventory works on types. A field NAMED like a secret must also be
# TYPED like one, or the inventory — and SecretStr's masking — never sees it.
SECRET_NAME = re.compile(r"(password|secret|token|api_key|private_key|access_key|credentials?)$")


# ── The inventory: what counts as a secret ──────────────────────────────────


def _mentions(annotation: object, wanted: Callable[[object], bool]) -> bool:
    """Whether a type, or any type inside it, satisfies `wanted`.

    Recursive, because the most sensitive field in the project is
    `tuple[SecretStr, ...]`: comparing an annotation to SecretStr misses it.
    """
    return wanted(annotation) or any(_mentions(arg, wanted) for arg in get_args(annotation))


def _is_secret_type(kind: object) -> bool:
    return isinstance(kind, type) and issubclass(kind, (SecretStr, SecretBytes, Secret))


def _can_carry_a_password(kind: object) -> bool:
    """URL types. `postgresql://user:password@host` is a secret all the same."""
    return isinstance(kind, type) and (hasattr(kind, "password") or hasattr(kind, "hosts"))


def _getter(member: object) -> Callable[..., object] | None:
    if isinstance(member, property):
        return member.fget
    return member.func if isinstance(member, cached_property) else None


def _secrets_in_settings() -> dict[str, str]:
    """Every name on Settings that yields a secret, and what makes it one."""
    found: dict[str, str] = {}
    for name, field in Settings.model_fields.items():
        if _mentions(field.annotation, _is_secret_type):
            found[name] = "a secret-typed field"
        elif _mentions(field.annotation, _can_carry_a_password):
            found[name] = "a URL that can carry a password"

    # A property returning a SecretStr is a secret as well: `llm_api_key`
    # has no field of its own, and a check on field names never sees it.
    for klass in Settings.__mro__:
        if not klass.__module__.startswith("leka."):
            continue
        for name, member in vars(klass).items():
            getter = _getter(member)
            if getter is None:
                continue
            returns = get_type_hints(getter).get("return")
            if returns is not None and _mentions(returns, _is_secret_type):
                found[name] = "a property returning a secret"
    return found


SECRETS = _secrets_in_settings()


# ── The scan: who reads what ─────────────────────────────────────────────────


def _within(module: str, owners: Iterable[str]) -> bool:
    return any(module == owner or module.startswith(f"{owner}.") for owner in owners)


def _module_name(path: Path, base: Path) -> str:
    parts = path.relative_to(base).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _scanned_files() -> Iterator[tuple[Path, str]]:
    for directory, base in SCANNED:
        for path in sorted(directory.rglob("*.py")):
            module = _module_name(path, base)
            if "__pycache__" not in path.parts and not _within(module, DECLARED_IN):
                yield path, module


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _parameters_typed_settings(tree: ast.AST) -> set[str]:
    """A parameter annotated `Settings` holds the settings, whatever its name."""
    return {
        node.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.arg)
        and node.annotation is not None
        and ast.unparse(node.annotation).strip("'\"").split(".")[-1] == "Settings"
    }


def _findings(source: str, secrets: Iterable[str]) -> list[tuple[int, str | None, str]]:
    """Every read of a secret in `source`, and every read that cannot be seen.

    Returns (line, secret, what happened). `secret` is None for an access no
    static check can verify; it fails whoever makes it.
    """
    names = frozenset(secrets)
    from_environment = {f"LEKA_{name.upper()}": name for name in names}
    tree = ast.parse(source)
    holders = {"settings"} | _parameters_typed_settings(tree)

    def is_settings(node: ast.AST | None) -> bool:
        return (isinstance(node, ast.Name) and node.id in holders) or (
            isinstance(node, ast.Attribute) and node.attr == "settings"
        )

    found: list[tuple[int, str | None, str]] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)

        if isinstance(node, ast.Attribute):
            if node.attr in names:
                found.append((line, node.attr, f"reads {node.attr}"))
            elif node.attr in BULK_READS and is_settings(node.value):
                found.append((line, None, f"settings.{node.attr} reads every secret at once"))

        elif isinstance(node, ast.Call):
            called = _called_name(node)
            named = [a.value for a in node.args if isinstance(a, ast.Constant) and a.value in names]
            computed = len(node.args) > 1 and not isinstance(node.args[1], ast.Constant)
            if called in {"getattr", "attrgetter"} and named:
                found.append((line, named[0], f"reads {named[0]} through {called}"))
            elif called == "getattr" and computed and is_settings(node.args[0]):
                found.append((line, None, "getattr on settings with a computed name"))
            elif called in {"vars", "dict"} and node.args and is_settings(node.args[0]):
                found.append((line, None, f"{called}(settings) reads every secret at once"))

        elif isinstance(node, ast.ImportFrom) and node.module == "leka.core.config":
            for alias in node.names:
                if alias.name == "*":
                    found.append((line, None, "a star import hides which names are used"))
                elif alias.name == "settings" and alias.asname not in {None, "settings"}:
                    found.append((line, None, f"settings imported as {alias.asname}"))

        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr) and is_settings(
            node.value
        ):
            found.append((line, None, "an alias of settings hides the reads made through it"))

        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            defaults = [*node.args.defaults, *node.args.kw_defaults]
            if any(is_settings(default) for default in defaults):
                found.append((line, None, "settings as a default argument is an alias"))

        elif isinstance(node, ast.Constant) and node.value in from_environment:
            secret = from_environment[node.value]
            found.append((line, secret, f"reads {node.value} from the environment directly"))

    return found


@cache
def _reads() -> tuple[tuple[str, str, int, str | None, str], ...]:
    """(module, file, line, secret, what) for every finding in the code base."""
    return tuple(
        (module, str(path.relative_to(REPO_ROOT)), line, secret, what)
        for path, module in _scanned_files()
        for line, secret, what in _findings(path.read_text(encoding="utf-8"), SECRETS)
    )


# ── The rule ─────────────────────────────────────────────────────────────────


def test_no_module_reads_a_secret_it_does_not_own() -> None:
    violations: list[str] = []
    for module, path, line, secret, what in _reads():
        if secret is None:
            violations.append(f"{path}:{line}: {what}")
        elif not _within(module, SECRET_OWNERS.get(secret, ())):
            owners = ", ".join(sorted(SECRET_OWNERS.get(secret, ())))
            rule = f"which only {owners} may read" if owners else "which has no owner"
            violations.append(f"{path}:{line}: {what}, {rule}")

    assert not violations, (
        "secrets read outside their owners:\n  "
        + "\n  ".join(violations)
        + "\n\nEither the module should not hold the secret — ask its owner for "
        "what it needs (a signature, a client, a sender) — or it genuinely must: "
        "add it to SECRET_OWNERS in tests/test_secret_access.py, with the reason."
    )


# ── The table cannot fall behind ─────────────────────────────────────────────


def test_the_table_matches_the_settings() -> None:
    """A new secret with nobody declared to read it fails here, not in review."""
    unowned = [f"{name} ({why})" for name, why in SECRETS.items() if name not in SECRET_OWNERS]
    assert not unowned, f"secrets nobody is declared to read: {unowned}. Add them to SECRET_OWNERS."

    stale = sorted(set(SECRET_OWNERS) - set(SECRETS))
    assert not stale, f"SECRET_OWNERS lists names that are no longer secrets: {stale}"


def test_a_field_named_like_a_secret_is_typed_like_one() -> None:
    """`redis_password: str` would be invisible to everything above.

    The inventory finds secrets by type. A secret typed `str` escapes it, and
    escapes SecretStr's masking in reprs and tracebacks along the way.
    """
    mistyped = [n for n in Settings.model_fields if SECRET_NAME.search(n) and n not in SECRETS]
    assert not mistyped, f"type these as SecretStr: {mistyped}"


def test_every_owner_exists() -> None:
    """A misspelt owner grants nothing and fails nothing — unless checked."""
    modules = {module for _, module in _scanned_files()}
    missing = sorted(
        owner
        for owners in SECRET_OWNERS.values()
        for owner in owners
        if not any(_within(module, [owner]) for module in modules)
    )
    assert not missing, f"owners that do not exist: {missing}"


def test_every_grant_is_used_or_reserved() -> None:
    """Least privilege applies to the table too."""
    exercised = {
        (secret, owner)
        for module, _, _, secret, _ in _reads()
        if secret is not None
        for owner in SECRET_OWNERS.get(secret, ())
        if _within(module, [owner])
    }
    granted = {(secret, owner) for secret, owners in SECRET_OWNERS.items() for owner in owners}

    unused = sorted(granted - exercised - set(RESERVED))
    assert not unused, f"grants nothing uses — remove them: {unused}"

    stale = sorted(pair for pair in RESERVED if pair in exercised or pair not in granted)
    assert not stale, f"RESERVED entries that are now used, or no longer granted: {stale}"


# ── The check can fail ───────────────────────────────────────────────────────


def test_the_inventory_sees_the_secrets_that_are_easy_to_miss() -> None:
    """If these stop being found, every test above passes over a short list."""
    assert SECRETS.get("encryption_keys") == "a secret-typed field"  # tuple[SecretStr, ...]
    assert SECRETS.get("llm_api_key") == "a property returning a secret"
    assert SECRETS.get("database_url") == "a URL that can carry a password"


def test_the_scan_covers_the_code_that_uses_settings() -> None:
    """A wrong root would scan nothing, and nothing has no violations."""
    importers = [
        path
        for path, _ in _scanned_files()
        if "from leka.core.config import settings" in path.read_text(encoding="utf-8")
    ]
    assert len(importers) >= 15, f"only {len(importers)} files import settings — wrong root?"


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("settings.secret_key", id="direct"),
        pytest.param("from leka.core.config import settings as cfg\ncfg.log_level", id="renamed"),
        pytest.param("cfg = settings", id="alias"),
        pytest.param("config.settings.encryption_keys[0]", id="through-the-module"),
        pytest.param("settings.llm_api_key", id="property"),
        pytest.param("getattr(settings, 'smtp_password')", id="getattr-literal"),
        pytest.param("getattr(settings, name)", id="getattr-computed"),
        pytest.param("vars(settings)", id="vars"),
        pytest.param("settings.model_dump()", id="model-dump"),
        pytest.param("def f(cfg: Settings) -> object:\n    return getattr(cfg, name)", id="typed"),
        pytest.param("def f(cfg=settings) -> None: ...", id="default-argument"),
        pytest.param("os.environ['LEKA_SECRET_KEY']", id="environment"),
        pytest.param("from leka.core.config import *", id="star-import"),
    ],
)
def test_the_scan_catches(source: str) -> None:
    """A scanner that stopped working would report what a clean code base
    reports: nothing. Each of these must be caught."""
    assert _findings(source, SECRETS), f"not caught:\n{source}"


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("settings.log_level", id="plain-setting"),
        pytest.param("getattr(settings, 'log_level')", id="getattr-plain"),
        pytest.param("getattr(row, column.key)", id="getattr-elsewhere"),
        pytest.param("response.model_dump()", id="model-dump-elsewhere"),
        pytest.param("'rotating LEKA_SECRET_KEY invalidates cursors'", id="prose"),
    ],
)
def test_the_scan_leaves_ordinary_code_alone(source: str) -> None:
    """A net that catches everything gets switched off."""
    assert not _findings(source, SECRETS), f"flagged for nothing:\n{source}"


def test_the_documented_owners_match_the_table() -> None:
    """docs/configuration.md is what a person reads; this table is what CI enforces."""
    doc = (REPO_ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    rows = {line.split("`")[1]: line for line in doc.splitlines() if line.startswith("| `LEKA_")}
    variables = [name for name, why in SECRETS.items() if why != "a property returning a secret"]

    wrong = [
        name
        for name in variables
        if any(
            f"`{owner}`" not in rows.get(f"LEKA_{name.upper()}", "")
            for owner in SECRET_OWNERS[name]
        )
    ]
    assert variables, "no secret variables found — the comparison would pass over nothing"
    assert not wrong, f"docs/configuration.md disagrees with SECRET_OWNERS on: {wrong}"
