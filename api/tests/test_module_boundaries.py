"""Architecture rule 1, enforced on the import graph.

Two things no linter can express, checked here instead:

1. **Direction.** Dependencies run one way only —
   `intentions → context → knowledge → ingestion → connectors`. A module may
   import modules below it, never above.

2. **Depth.** A module is reached through its `__init__.py`. Importing
   `leka.knowledge.repository` from elsewhere couples you to a decision that
   module is entitled to change without telling you.

Ruff cannot do this: its banned-import check is per-file, so exempting a
module's own directory also exempts it when it reaches into everyone else's.
This test reads the AST instead, so it sees who imports what.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "leka"

# Lower number = closer to the foundations. A module may import strictly
# lower layers. Equal layers are independent of each other and must not
# import one another.
#
# background (job queue, events, execution history) is infrastructure that
# platform itself must be able to use, so it sits between db and platform.
# Only the relative order matters — the numbers are labels.
LAYERS: dict[str, int] = {
    "core": 0,
    # The application architect's core (2026-10-25): imports nothing of
    # LEKA's — it ships alone as the downloadable agent.
    "architect": 0,
    "db": 1,
    "background": 2,
    "platform": 3,
    "identity": 4,
    "connectors": 4,
    # LEKA CORE's commercial offer (LEKA-431): its catalogue, the pricing
    # page's analytics.
    "billing": 6,
    "ingestion": 5,
    "governance": 5,
    "knowledge": 6,
    "context": 7,
    "capabilities": 8,
    "intelligence": 9,
    "intentions": 10,
    # Operations (LEKA-408): reads every module's tables as operating data.
    "ops": 11,
    # Watching the environment (LEKA-442): reads the twin, the plan.
    "monitoring": 11,
    # Metering (LEKA-430): derives the usage ledger from the calls and runs.
    "metering": 11,
    "demo": 11,
    # The notification centre (LEKA-476): reads what every module kept.
    "notifications": 12,
    "api": 13,
}

# Files a module keeps to itself. Everything else imports the package.
INTERNAL_MODULES = frozenset({"models", "schemas", "repository", "service", "loader"})


def _source_files() -> list[Path]:
    return sorted(path for path in PACKAGE_ROOT.rglob("*.py") if "__pycache__" not in path.parts)


def _module_of(path: Path) -> str | None:
    """Which top-level LEKA module a file belongs to, if any."""
    relative = path.relative_to(PACKAGE_ROOT).parts
    return relative[0] if len(relative) > 1 else None


def _leka_imports(path: Path) -> list[tuple[str, ...]]:
    """Every `leka.*` import in a file, as dotted parts."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, ...]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import, which stays inside the module.
            if node.level == 0 and node.module and node.module.startswith("leka"):
                found.append(tuple(node.module.split(".")))
        elif isinstance(node, ast.Import):
            found.extend(
                tuple(alias.name.split("."))
                for alias in node.names
                if alias.name.startswith("leka")
            )
    return found


def test_every_module_has_a_declared_layer() -> None:
    """A new module must be placed in the hierarchy, not left floating."""
    on_disk = {
        path.name for path in PACKAGE_ROOT.iterdir() if path.is_dir() and path.name != "__pycache__"
    }
    undeclared = on_disk - set(LAYERS)
    assert not undeclared, (
        f"modules with no declared layer: {sorted(undeclared)}. "
        "Add them to LAYERS and to docs/architecture.md."
    )


def test_dependencies_only_point_downwards() -> None:
    """No module imports one at its own level or above."""
    violations: list[str] = []

    for path in _source_files():
        importer = _module_of(path)
        if importer is None or importer not in LAYERS:
            continue

        for parts in _leka_imports(path):
            if len(parts) < 2:
                continue
            imported = parts[1]
            if imported == importer or imported not in LAYERS:
                continue
            if LAYERS[imported] >= LAYERS[importer]:
                violations.append(
                    f"{path.relative_to(PACKAGE_ROOT.parent)}: "
                    f"{importer} (layer {LAYERS[importer]}) imports "
                    f"{imported} (layer {LAYERS[imported]})"
                )

    assert not violations, "dependency direction violated:\n  " + "\n  ".join(violations)


def test_modules_are_imported_through_their_init() -> None:
    """No module reaches into another's models, schemas, repository, service."""
    violations: list[str] = []

    for path in _source_files():
        importer = _module_of(path)
        if importer is None:
            continue

        for parts in _leka_imports(path):
            if len(parts) < 3:
                continue
            imported, internal = parts[1], parts[2]
            if imported == importer or imported not in LAYERS:
                continue
            if internal in INTERNAL_MODULES:
                violations.append(
                    f"{path.relative_to(PACKAGE_ROOT.parent)}: "
                    f"imports leka.{imported}.{internal} — use leka.{imported}"
                )

    assert not violations, "module internals reached from outside:\n  " + "\n  ".join(violations)


@pytest.mark.parametrize(
    "module",
    # The architect's core is a library that ships alone, no table of its own.
    sorted(name for name in LAYERS if name not in {"core", "db", "api", "architect"}),
)
def test_every_module_has_the_same_five_files(module: str) -> None:
    """One shape, so that opening any module means knowing where to look."""
    directory = PACKAGE_ROOT / module
    missing = [
        name
        for name in ("__init__.py", "models.py", "schemas.py", "repository.py", "service.py")
        if not (directory / name).exists()
    ]
    assert not missing, f"leka/{module}/ is missing {missing}"
