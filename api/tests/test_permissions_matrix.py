"""docs/permissions.md is checked, not trusted.

The Definition of Done says authorisation boundaries are documented. A table
in a markdown file satisfies that on the day it is written and drifts from
the code within a month — at which point it is worse than no table, because
people believe it.

So the document is parsed and compared to ROLE_PERMISSIONS. Changing one
without the other fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from leka.governance import ROLE_PERMISSIONS, Permission
from leka.platform import Role

PERMISSIONS_DOC = Path(__file__).resolve().parents[2] / "docs" / "permissions.md"

_ROW = re.compile(r"^\|\s*`([a-z_]+:[a-z_]+)`\s*\|(.+)\|\s*$")


def _documented_matrix() -> dict[Role, set[str]]:
    """Read the markdown table into the same shape as ROLE_PERMISSIONS."""
    columns = (Role.MEMBER, Role.ADMIN, Role.OWNER)
    matrix: dict[Role, set[str]] = {role: set() for role in columns}
    rows = 0

    for line in PERMISSIONS_DOC.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line.strip())
        if match is None:
            continue
        permission, cells = match.group(1), match.group(2)
        answers = [cell.strip().lower() for cell in cells.split("|") if cell.strip()]
        if len(answers) != len(columns):
            continue
        rows += 1
        for role, answer in zip(columns, answers, strict=True):
            if answer == "yes":
                matrix[role].add(permission)

    assert rows, f"no permission rows found in {PERMISSIONS_DOC} — has the table moved?"
    return matrix


def test_every_permission_appears_in_the_document() -> None:
    documented = set().union(*_documented_matrix().values())
    defined = {permission.value for permission in Permission}

    missing = defined - documented
    assert not missing, (
        f"permissions absent from docs/permissions.md: {sorted(missing)}. "
        "A permission nobody documented is a permission nobody reviewed."
    )


def test_the_document_invents_no_permission() -> None:
    documented = set().union(*_documented_matrix().values())
    defined = {permission.value for permission in Permission}

    invented = documented - defined
    assert not invented, (
        f"docs/permissions.md grants permissions that do not exist: {sorted(invented)}."
    )


@pytest.mark.parametrize("role", [Role.MEMBER, Role.ADMIN, Role.OWNER])
def test_the_document_matches_the_code(role: Role) -> None:
    documented = _documented_matrix()[role]
    actual = {permission.value for permission in ROLE_PERMISSIONS[role]}

    assert documented == actual, (
        f"docs/permissions.md and ROLE_PERMISSIONS disagree about {role.value}.\n"
        f"  only in the document: {sorted(documented - actual)}\n"
        f"  only in the code:     {sorted(actual - documented)}"
    )


def test_roles_are_a_chain() -> None:
    """An owner can do everything an admin can, an admin everything a member
    can. require_role depends on it, and a gap would silently create a role
    that is more powerful in one respect and less in another."""
    assert ROLE_PERMISSIONS[Role.MEMBER] < ROLE_PERMISSIONS[Role.ADMIN]
    assert ROLE_PERMISSIONS[Role.ADMIN] < ROLE_PERMISSIONS[Role.OWNER]


def test_only_an_owner_can_end_or_hand_over_the_workspace() -> None:
    """Running a workspace and ending the company's account are different
    responsibilities."""
    for permission in (Permission.WORKSPACE_DELETE, Permission.WORKSPACE_TRANSFER):
        assert permission not in ROLE_PERMISSIONS[Role.ADMIN]
        assert permission in ROLE_PERMISSIONS[Role.OWNER]
