"""An ADR number is unique.

It is cited from docs, from docstrings and from commit messages, so two ADRs
sharing one is not a filing accident — it is a reference nobody can trust: "see
ADR 012" means one document until the day it means two. LEKA-334 and LEKA-335
picked the same number by opening in parallel, and the second one to merge had
to renumber. This is the three-line guard that stops it happening quietly again
— the same principle as the SECRET_OWNERS check in test_secret_access.py, which
LEKA-335 added after a module moved and nobody updated the table it belonged to.

Static, on the model of test_module_boundaries.py: nothing to pay at runtime,
and the failure names the two files rather than being noticed in a doc review.
"""

from __future__ import annotations

import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
ADR_DIR = API_ROOT.parent / "docs" / "adr"

FILENAME = re.compile(r"^(\d{3})-.+\.md$")


def test_every_adr_number_is_used_once() -> None:
    numbers: dict[str, list[str]] = {}
    for path in ADR_DIR.glob("*.md"):
        match = FILENAME.match(path.name)
        if not match:
            continue
        numbers.setdefault(match.group(1), []).append(path.name)

    collisions = {number: names for number, names in numbers.items() if len(names) > 1}
    assert not collisions, (
        f"more than one ADR uses the same number: {collisions}. "
        "An ADR number is cited from docs, comments and commit messages, so it "
        "must be unique — renumber the one that merged second."
    )


def test_the_check_can_actually_fail() -> None:
    """ADR_DIR is never empty, or the test above would pass over nothing."""
    assert any(FILENAME.match(path.name) for path in ADR_DIR.glob("*.md"))
