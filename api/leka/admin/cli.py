"""LEKA ADMIN's accounts, from the server's shell (LEKA-544).

    python -m leka.admin.cli create haitam@leka-core.com --name "Haïtam" --role super_admin
    python -m leka.admin.cli list
    python -m leka.admin.cli role haitam@leka-core.com operations
    python -m leka.admin.cli disable haitam@leka-core.com
    python -m leka.admin.cli enable haitam@leka-core.com
    python -m leka.admin.cli password haitam@leka-core.com

The password is typed, twice, never given on the command line (where the
shell's history and `ps` would keep it). `disable` and `password` end every
session of the account at once. Each change is kept in the admin trail,
said by whom (the shell's user).

Until LEKA-545 lets a Super Admin do it from LEKA ADMIN, this is how the
team's accounts are made. On the production box:

    cd /opt/leka && docker compose -f docker-compose.production.yml \\
      --env-file production.env exec api python -m leka.admin.cli list
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime

from leka.admin import audit
from leka.admin.access import AdminRole
from leka.admin.repository import AdminRepository
from leka.admin.service import MIN_PASSWORD_LENGTH, AdminAccountError, create_account
from leka.core.security import hash_password
from leka.db import load_schema, session_factory


def _operator() -> str:
    return f"cli:{getpass.getuser()}"


def _password() -> str:
    first = getpass.getpass(f"Password ({MIN_PASSWORD_LENGTH} characters at least): ")
    if getpass.getpass("Again: ") != first:
        raise AdminAccountError("The two passwords differ.")
    return first


async def _create(email: str, name: str, role: str) -> str:
    password = _password()
    async with session_factory() as session:
        account = await create_account(
            session, email=email, name=name, role=role, password=password, by=_operator()
        )
        await session.commit()
        return f"{account.email} is now an admin, as {account.role}."


async def _list() -> str:
    async with session_factory() as session:
        accounts = await AdminRepository(session).accounts()
    if not accounts:
        return (
            "No admin yet. Make the first one: "
            "python -m leka.admin.cli create <email> --role super_admin"
        )
    lines = [
        f"{a.email:40} {a.role:12} {a.status:9} last sign-in: "
        f"{a.last_sign_in_at.isoformat(timespec='minutes') if a.last_sign_in_at else 'never'}"
        for a in accounts
    ]
    return "\n".join(lines)


async def _change(
    email: str, *, role: str | None = None, status: str | None = None, password: bool = False
) -> str:
    async with session_factory() as session:
        accounts = AdminRepository(session)
        account = await accounts.account_by_email(email)
        if account is None:
            raise AdminAccountError(f"No admin {email.strip().lower()}.")
        before = {"role": account.role, "status": account.status}
        now = datetime.now(UTC)
        ended = 0
        if role is not None:
            if role not in {r.value for r in AdminRole}:
                raise AdminAccountError(
                    f"Unknown role {role!r}: one of {', '.join(r.value for r in AdminRole)}."
                )
            account.role = role
        if status is not None:
            account.status = status
            if status == "disabled":
                ended = await accounts.revoke_all(account.id, now)
            else:
                account.failed_sign_ins = 0
                account.locked_until = None
        if password:
            secret = _password()
            if len(secret) < MIN_PASSWORD_LENGTH:
                raise AdminAccountError(f"A password of {MIN_PASSWORD_LENGTH} characters at least.")
            account.password_hash = hash_password(secret)
            ended = await accounts.revoke_all(account.id, now)
        audit.record(
            session,
            "admin.account_changed",
            admin_id=None,
            admin_email=_operator(),
            target_type="admin",
            target_id=account.id,
            detail={
                "email": account.email,
                "before": before,
                "after": {"role": account.role, "status": account.status},
                "password_changed": password,
                "sessions_ended": ended,
            },
        )
        await session.commit()
        return f"{account.email}: {account.role}, {account.status}" + (
            f"; {ended} session(s) ended." if ended else "."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m leka.admin.cli", description=__doc__.split("\n\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="make an admin account")
    create.add_argument("email")
    create.add_argument("--name", default="")
    create.add_argument("--role", required=True, choices=[r.value for r in AdminRole])
    commands.add_parser("list", help="every admin account")
    role = commands.add_parser("role", help="change an admin's role")
    role.add_argument("email")
    role.add_argument("role", choices=[r.value for r in AdminRole])
    for name in ("disable", "enable", "password"):
        command = commands.add_parser(name, help=f"{name} an admin account")
        command.add_argument("email")
    args = parser.parse_args(argv)

    load_schema()
    try:
        if args.command == "create":
            said = asyncio.run(_create(args.email, args.name, args.role))
        elif args.command == "list":
            said = asyncio.run(_list())
        elif args.command == "role":
            said = asyncio.run(_change(args.email, role=args.role))
        elif args.command == "password":
            said = asyncio.run(_change(args.email, password=True))
        else:
            status = "disabled" if args.command == "disable" else "active"
            said = asyncio.run(_change(args.email, status=status))
    except AdminAccountError as error:
        sys.stderr.write(f"Refused: {error}\n")
        return 1
    sys.stdout.write(f"{said}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
