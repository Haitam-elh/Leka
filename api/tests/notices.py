"""The third-party notices (third_party/NOTICES.md), as the tests read them.

The sources an agent's method was rewritten from are named there and
nowhere else (2026-11-05): a test checks an agent or a guide never names
one by reading their names from the notices, never by writing them.
"""

from __future__ import annotations

import re

from leka.core.config import settings

NOTICES = (settings.agents_dir.parent / "third_party" / "NOTICES.md").read_text(encoding="utf-8")

# Each linked repository, its owner and its name — a name too common to
# point at anyone (« skills ») left out — and each copyright holder.
_LINKED = re.findall(r"\[([\w.-]+)/([\w.-]+)\]\(https://github\.com/", NOTICES)
_HOLDERS = re.findall(r"Copyright \(c\) \d{4} ([^;|`]+?)(?=;|\||$)", NOTICES, re.MULTILINE)
_WORDS = (
    {f"{owner}/{repo}" for owner, repo in _LINKED}
    | {owner for owner, _ in _LINKED}
    | {repo for _, repo in _LINKED if repo != "skills"}
    | {holder.strip() for holder in _HOLDERS}
)
SOURCE = re.compile(
    r"(?<![\w-])("
    + "|".join(sorted(map(re.escape, _WORDS), key=len, reverse=True))
    + r")(?![\w-])",
    re.IGNORECASE,
)
assert _LINKED and _HOLDERS, "the notices name no source: their format changed"


def names_a_source(text: str) -> bool:
    """Whether a text names a source of the notices, or carries its credit line."""
    return bool(SOURCE.search(text)) or "<sub>" in text


def credited(file: str) -> bool:
    """A row of the notices names this file: its provenance is recorded."""
    return any(f"`{file}`" in line for line in NOTICES.splitlines() if line.startswith("|"))
