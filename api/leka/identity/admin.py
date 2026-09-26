"""Give an account access to a workspace, from the server's shell.

    python -m leka.identity.admin accounts
    python -m leka.identity.admin grant karim@example.com --role admin

`accounts` lists who registered, whether they confirmed their address, and
which workspaces they sit in — never a password hash. `grant` seats one.

On the production box:

    cd /opt/leka && docker compose -f docker-compose.production.yml \\
      --env-file production.env exec api \\
      python -m leka.identity.admin grant karim@example.com --role admin

WHY THIS EXISTS. The first production deployment had no workspace and no
screen to make one: whoever signed in saw an empty shell, and a colleague
could not be let in. Until the team screen does it, this does.

WHAT IT WILL NOT DO. Create an account, or know a password. The person
registers on the site and confirms their address themselves; no password
travels between people. An unconfirmed account is refused: the confirmation
is what proves the address is theirs.

The first account granted into a workspace that does not exist yet creates
it and becomes its owner — a workspace nobody owns cannot be administered.
The last owner is never demoted.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from leka.core.config import settings
from leka.db import load_schema, session_factory, system_scope, workspace_scope
from leka.identity.models import User
from leka.identity.repository import UserRepository
from leka.platform import (
    Membership,
    MembershipRepository,
    Role,
    Workspace,
    WorkspaceRepository,
    WorkspaceService,
    slugify,
)

DEFAULT_WORKSPACE = "LEKA"


class AccessError(Exception):
    """Refused, with a sentence an operator can act on."""


async def grant(email: str, role: Role, workspace_name: str = DEFAULT_WORKSPACE) -> str:
    """Seat an existing, confirmed account in the workspace. Returns what was done."""
    address = email.strip().lower()

    with system_scope():
        async with session_factory() as session:
            user = await UserRepository(session).get_by_email(address)
            if user is None:
                msg = (
                    f"No account for {address}. They register first at "
                    f"{settings.web_url}/register and confirm the email, then run this again."
                )
                raise AccessError(msg)
            if not user.is_verified:
                msg = (
                    f"{address} has not confirmed their email yet. The link is in the "
                    "'Confirmez votre adresse e-mail LEKA' message; run this again after."
                )
                raise AccessError(msg)

            workspaces = WorkspaceRepository(session)
            workspace = await workspaces.get_by_slug(slugify(workspace_name))

            if workspace is None:
                workspace = await WorkspaceService(workspaces, session).create(
                    workspace_name, owner_user_id=user.id
                )
                await session.commit()
                return (
                    f"Workspace {workspace_name!r} created; {address} is its owner. "
                    "They sign out and in again to land in it."
                )

            with workspace_scope(workspace.id):
                memberships = MembershipRepository(session, workspace.id)
                seat = await memberships.get_for_user(user.id)

                if seat is None:
                    memberships.create(user_id=user.id, role=role)
                    await memberships.flush()
                    await session.commit()
                    return (
                        f"{address} is now {role.value} of {workspace_name!r}. "
                        "They sign out and in again to land in it."
                    )

                if seat.role is role:
                    return f"{address} is already {role.value} of {workspace_name!r}."

                if seat.role is Role.OWNER and await memberships.count_owners() == 1:
                    msg = (
                        f"{address} is the only owner of {workspace_name!r}; "
                        "make someone else owner first."
                    )
                    raise AccessError(msg)

                before = seat.role
                seat.role = role
                await memberships.flush()
                await session.commit()
                return f"{address}: {before.value} → {role.value} in {workspace_name!r}."


async def accounts() -> str:
    """Every account, oldest first: address, confirmed or not, workspaces."""
    with system_scope():
        async with session_factory() as session:
            rows = await session.execute(
                select(
                    User.email,
                    User.email_verified_at,
                    User.created_at,
                    Workspace.name,
                    Membership.role,
                )
                .outerjoin(Membership, Membership.user_id == User.id)
                .outerjoin(Workspace, Workspace.id == Membership.workspace_id)
                .order_by(User.created_at, User.email)
            )
            people: dict[str, tuple[str, str, list[str]]] = {}
            for email, verified_at, created_at, workspace, role in rows.tuples():
                confirmed = "confirmed" if verified_at else "NOT confirmed"
                registered = created_at.strftime("%Y-%m-%d %H:%M UTC")
                seats = people.setdefault(email, (confirmed, registered, []))[2]
                if workspace is not None and role is not None:
                    seats.append(f"{workspace} ({role.value})")

    if not people:
        return "No account yet."
    width = max(len(email) for email in people) + 2
    lines = [f"{'EMAIL':<{width}}{'CONFIRMED':<16}{'REGISTERED':<22}WORKSPACES"]
    for email, (confirmed, registered, seats) in people.items():
        where = ", ".join(seats) if seats else "no workspace"
        lines.append(f"{email:<{width}}{confirmed:<16}{registered:<22}{where}")
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m leka.identity.admin")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("accounts", help="list the accounts and where they sit")
    granting = commands.add_parser("grant", help="give an account access to a workspace")
    granting.add_argument("email")
    granting.add_argument("--role", choices=[role.value for role in Role], default="member")
    granting.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    args = parser.parse_args(argv)

    if args.command == "accounts":
        sys.stdout.write(f"{await accounts()}\n")
        return 0

    try:
        said = await grant(args.email, Role(args.role), args.workspace)
    except AccessError as refusal:
        sys.stdout.write(f"Refused: {refusal}\n")
        return 1
    sys.stdout.write(f"{said}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - the process itself
    load_schema()  # every table, as the API has (leka/schema.py)
    sys.exit(asyncio.run(main()))
