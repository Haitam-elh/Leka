"""Every table is registered wherever LEKA's code runs, not only in the API.

The worker used to import only the job it ran. `sources.created_by` points
at `users`, which lives in leka.identity, and a process that had not
imported identity could not run a single query on sources: the source-health
sweep crashed on every source until leka/schema.py. These run in a fresh
interpreter, because this test process has imported everything long ago and
would pass whatever the code did.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "leka"


def _fresh(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — our own interpreter, our own code
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=PACKAGE.parent,
        check=False,
    )


def test_one_module_alone_cannot_resolve_its_foreign_keys() -> None:
    """The failure this file exists for — if it ever stops failing, the
    registry is no longer what makes the worker work, and this says so."""
    alone = _fresh("import leka.connectors\nfrom leka.db import Base\nBase.metadata.sorted_tables")

    assert alone.returncode != 0
    assert "NoReferencedTableError" in alone.stderr


def test_load_schema_registers_every_table() -> None:
    ready = _fresh(
        "from leka.db import load_schema\n"
        "load_schema()\n"
        "import leka.connectors\n"
        "from leka.db import Base\n"
        "print(len(Base.metadata.sorted_tables))"
    )

    assert ready.returncode == 0, ready.stderr
    assert int(ready.stdout.strip()) > 0


def test_every_module_that_declares_a_table_is_in_the_registry() -> None:
    """A new module with a table must be added to leka/schema.py."""
    registered = {
        alias.name.split(".")[1]
        for node in ast.walk(ast.parse((PACKAGE / "schema.py").read_text(encoding="utf-8")))
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name.startswith("leka.")
    }
    declaring = {
        path.parent.name
        for path in PACKAGE.glob("*/models.py")
        if "__tablename__" in path.read_text(encoding="utf-8")
    }

    assert declaring <= registered, f"not in leka/schema.py: {sorted(declaring - registered)}"


def test_every_process_that_queries_registers_the_schema_first() -> None:
    """The worker, and every task that can be run by hand (`python -m ...`)
    and opens a session, calls load_schema() before it does anything."""
    missing = []
    for path in sorted(PACKAGE.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if 'if __name__ == "__main__"' not in source or "session_factory" not in source:
            continue
        entry = source.split('if __name__ == "__main__"', 1)[1]
        if "load_schema()" not in entry:
            missing.append(str(path.relative_to(PACKAGE.parent)))
    worker = (PACKAGE / "platform" / "worker.py").read_text(encoding="utf-8")

    assert missing == [], f"call load_schema() in the __main__ block of: {missing}"
    assert "load_schema()" in worker.split("def main(", 1)[1]
