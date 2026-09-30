"""The web app's copy of the knowledge vocabulary matches this one (LEKA-340).

web/lib/knowledge.ts repeats EntityType and RelationshipType as lists —
the generated API types have them as unions (LEKA-361), which cannot be
iterated. A repeated list drifts: an entity type added here would render as
nothing there, silently. This reads the TypeScript and compares.
"""

from __future__ import annotations

import re

import pytest

from leka.core.config import REPO_ROOT
from leka.knowledge import EntityType, RelationshipType

MIRROR = REPO_ROOT / "web" / "lib" / "knowledge.ts"


def _typescript_list(name: str) -> list[str]:
    source = MIRROR.read_text(encoding="utf-8")
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", source, re.S)
    assert match, f"{name} not found in {MIRROR}"
    return re.findall(r'"([a-z_]+)"', match.group(1))


@pytest.mark.parametrize(
    ("name", "enum"),
    [("ENTITY_TYPES", EntityType), ("RELATIONSHIP_TYPES", RelationshipType)],
)
def test_the_web_app_knows_the_same_kinds(name: str, enum: type[EntityType]) -> None:
    assert _typescript_list(name) == [member.value for member in enum]
