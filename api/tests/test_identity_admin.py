"""Giving an account access to a workspace, from the server's shell.

The first production deployment had no workspace at all and no screen to
make one: whoever signed in saw an empty shell, and there was no way to let
a colleague in. `python -m leka.identity.admin grant` is that way until the
team screen exists. These tests hold it to what an operator needs: it only
seats accounts that registered and confirmed themselves — no password is
ever handed over — and it never leaves a workspace without an owner.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from leka.core.security import hash_password
from leka.db import session_factory, system_scope
from leka.identity import User
from leka.identity.admin import AccessError, grant, main
from leka.platform import Membership, Role, Workspace

pytestmark = pytest.mark.integration

WORKSPACE = "LEKA"


async def _wipe() -> None:
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM workspaces"))
            await session.execute(text("DELETE FROM users"))
            await session.commit()


@pytest.fixture(autouse=True)
async def clean_everything() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()


async def _account(
    email: str, *, verified: bool = True, name: tuple[str, str] | None = None, company: str = ""
) -> None:
    with system_scope():
        async with session_factory() as session:
            session.add(
                User(
                    email=email,
                    password_hash=hash_password("a long enough passphrase"),
                    email_verified_at=datetime.now(UTC) if verified else None,
                    first_name=name[0] if name else None,
                    last_name=name[1] if name else None,
                    company=company or None,
                )
            )
            await session.commit()


async def _seats() -> dict[str, Role]:
    """Who sits in the LEKA workspace, and as what."""
    with system_scope():
        async with session_factory() as session:
            rows = await session.execute(
                select(User.email, Membership.role)
                .join(Membership, Membership.user_id == User.id)
                .join(Workspace, Workspace.id == Membership.workspace_id)
                .where(Workspace.name == WORKSPACE)
            )
            return dict(list(rows.tuples()))


async def test_an_address_with_no_account_is_told_to_register_first() -> None:
    with pytest.raises(AccessError, match="/register"):
        await grant("karim@acme.example", Role.ADMIN)


async def test_an_unconfirmed_account_is_not_let_in() -> None:
    """The confirmation proves the address is theirs. Seating an unconfirmed
    account would hand a workspace to whoever typed someone else's email."""
    await _account("karim@acme.example", verified=False)

    with pytest.raises(AccessError, match="confirm"):
        await grant("karim@acme.example", Role.ADMIN)
    assert await _seats() == {}


async def test_the_first_grant_creates_the_workspace_and_its_owner() -> None:
    await _account("haitam@acme.example")

    said = await grant("haitam@acme.example", Role.ADMIN)

    # A workspace with no owner cannot be administered: the first one is it.
    assert await _seats() == {"haitam@acme.example": Role.OWNER}
    assert "created" in said and "owner" in said


async def test_the_next_ones_get_the_role_asked_for() -> None:
    await _account("haitam@acme.example")
    await _account("karim@acme.example")
    await _account("lina@acme.example")
    await grant("haitam@acme.example", Role.OWNER)

    await grant("Karim@Acme.Example", Role.ADMIN)
    await grant("lina@acme.example", Role.MEMBER)

    assert await _seats() == {
        "haitam@acme.example": Role.OWNER,
        "karim@acme.example": Role.ADMIN,
        "lina@acme.example": Role.MEMBER,
    }


async def test_granting_again_changes_the_role() -> None:
    await _account("haitam@acme.example")
    await _account("karim@acme.example")
    await grant("haitam@acme.example", Role.OWNER)
    await grant("karim@acme.example", Role.MEMBER)

    said = await grant("karim@acme.example", Role.ADMIN)

    assert (await _seats())["karim@acme.example"] is Role.ADMIN
    assert "member" in said and "admin" in said


async def test_the_last_owner_is_never_demoted() -> None:
    await _account("haitam@acme.example")
    await grant("haitam@acme.example", Role.OWNER)

    with pytest.raises(AccessError, match="owner"):
        await grant("haitam@acme.example", Role.MEMBER)
    assert await _seats() == {"haitam@acme.example": Role.OWNER}


async def test_the_command_line_says_what_happened(capsys: pytest.CaptureFixture[str]) -> None:
    await _account("haitam@acme.example")

    assert await main(["grant", "haitam@acme.example", "--role", "admin"]) == 0
    assert "haitam@acme.example" in capsys.readouterr().out

    assert await main(["grant", "nobody@acme.example", "--role", "admin"]) == 1
    assert "/register" in capsys.readouterr().out


async def test_accounts_lists_who_registered_and_where_they_sit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """What an operator asks first: did they register, did they confirm, are
    they in. Never a password hash — only what the operator needs."""
    await _account("haitam@acme.example")
    await _account("karim@acme.example", verified=False, name=("Karim", "B."), company="LEKA")
    await grant("haitam@acme.example", Role.OWNER)

    assert await main(["accounts"]) == 0
    out = capsys.readouterr().out

    haitam = next(line for line in out.splitlines() if "haitam@acme.example" in line)
    karim = next(line for line in out.splitlines() if "karim@acme.example" in line)
    assert "confirmed" in haitam and "LEKA (owner)" in haitam
    assert "NOT confirmed" in karim and "no workspace" in karim
    # Who they said they are, for whoever decides to let them in; an
    # account from before registration asked shows a dash.
    assert "Karim B." in karim and "LEKA" in karim
    assert haitam.split()[1:3] == ["-", "-"]
    assert "$argon2" not in out
