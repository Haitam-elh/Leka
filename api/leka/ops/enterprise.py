"""An Enterprise account, made from the server's shell (2026-10-25): an
organisation, its account, its plan, its dedicated agents — idempotent.

    python -m leka.ops.enterprise provision \\
        --email admin@client.example --organisation "Nom du client" \\
        --agent application-architecture \\
        [--first-name … --last-name …] [--credits N] \\
        [--contact-name … --contact-email …] [--remove-agent KEY] \\
        [--instructions consignes.md | --instructions - | --clear-instructions]

    python -m leka.ops.enterprise show --organisation "Nom du client"

`provision`, run once or ten times, leaves the same thing:
- the account of `--email`: made when it does not exist — its address
  vouched for by the operator, its password asked for (hidden), or read
  from LEKA_ENTERPRISE_PASSWORD, never on the command line, never printed —
  else the existing one, confirmed;
- the organisation — the workspace of that name — made when it does not
  exist, its owner the account; else the account seated in it as owner;
- the plan Enterprise from now on, its AI capacity the contract's
  (`--credits`, LEKA's own allowance otherwise) — never shown in euros or
  credits to the organisation;
- the agents of `--agent` assigned to it, those of `--remove-agent` taken
  back (leka/capabilities/dedicated.py);
- the contract it shows: its type, since when, its dedicated contact;
- with `--instructions`, the organisation's own instructions for the agents
  of `--agent` — its architect's prompt, its template, its spaces, its
  directory — in place of the registry's, on LEKA and in the package it
  downloads (`-`: read from the standard input); `--clear-instructions`:
  back to the registry's. Never printed: their length only.

Nothing of an organisation is written in LEKA's code: its name, its
account and its agents are this command's arguments, kept in the database —
a second Enterprise customer is the same command.

On the production box:

    cd /opt/leka && docker compose -f docker-compose.production.yml \\
      --env-file production.env exec api python -m leka.ops.enterprise provision …

    # its instructions, from a file of the box, through the standard input:
    docker compose -f docker-compose.production.yml --env-file production.env \\
      exec -T api python -m leka.ops.enterprise provision --email … \\
      --organisation "…" --agent application-architecture --instructions - < consignes.md

WHY AN ACCOUNT IS MADE HERE. The other admin command (leka.identity.admin)
never makes one: a person registers and confirms their address. An
Enterprise account is agreed with the customer, its address given by them:
the operator vouches for it, and gives its first password by hand — to be
changed by its owner (Profil → Mot de passe).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.dedicated import (
    assign,
    dedicated_to,
    instruct,
    instructions_of,
    unassign,
)
from leka.capabilities.registry import find
from leka.core.security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, hash_password
from leka.db import load_schema, session_factory, system_scope, workspace_scope
from leka.governance.audit import audit
from leka.governance.plans import plan_of, set_plan
from leka.identity import User, UserRepository, password_is_breached
from leka.platform import (
    MembershipRepository,
    Role,
    Workspace,
    WorkspaceRepository,
    WorkspaceService,
    slugify,
)

ENTERPRISE = "enterprise"
OPERATOR = "provisioning"
# An agent's own instructions, at most: a long prompt, never a document.
MAX_INSTRUCTIONS = 200_000
# The name of the variable a first password may be read from — never a password.
PASSWORD_ENV = "LEKA_ENTERPRISE_PASSWORD"  # noqa: S105


class ProvisioningError(Exception):
    """Refused, with a sentence an operator can act on."""


@dataclass
class Provisioned:
    """What an organisation is now — and what this run changed."""

    organisation: str
    workspace_id: str
    email: str
    account: str
    role: str
    plan: str
    agents: list[str]
    contract: dict[str, object]
    changed: list[str] = field(default_factory=list)
    # An agent's own instructions, by their length — never their words.
    instructions: dict[str, int] = field(default_factory=dict)


def contract_of(workspace: Workspace) -> dict[str, object]:
    """An Enterprise organisation's contract, as kept with it."""
    said = (workspace.settings or {}).get("enterprise")
    return dict(said) if isinstance(said, dict) else {}


async def _account(
    session: AsyncSession,
    email: str,
    password: str | None,
    *,
    first_name: str | None,
    last_name: str | None,
    now: datetime,
    changed: list[str],
) -> tuple[User, str]:
    users = UserRepository(session)
    user = await users.get_by_email(email)
    if user is not None:
        if not user.is_verified:
            user.email_verified_at = now
            changed.append("adresse confirmée")
        return user, "existant"
    if not password:
        raise ProvisioningError(
            f"Aucun compte pour {email} : son mot de passe est demandé (saisie masquée), "
            f"ou lu dans {PASSWORD_ENV}."
        )
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise ProvisioningError(
            f"Le mot de passe doit faire de {PASSWORD_MIN_LENGTH} à {PASSWORD_MAX_LENGTH} "
            "caractères."
        )
    if await password_is_breached(password):
        raise ProvisioningError(
            "Ce mot de passe figure dans une fuite de données connue : choisissez-en un autre."
        )
    user = User(
        email=email,
        password_hash=hash_password(password),
        first_name=first_name,
        last_name=last_name,
        language="fr",
        email_verified_at=now,
        password_changed_at=now,
    )
    users.add(user)
    await users.flush()
    changed.append("compte créé")
    return user, "créé"


async def provision(
    email: str,
    organisation: str,
    *,
    password: str | None = None,
    agents: Sequence[str] = (),
    remove: Sequence[str] = (),
    first_name: str | None = None,
    last_name: str | None = None,
    monthly_credits: int | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
    instructions: str | None = None,
    clear_instructions: bool = False,
    now: datetime | None = None,
) -> Provisioned:
    """The organisation as asked — made or brought to it, never twice."""
    moment = now or datetime.now(UTC)
    address = email.strip().lower()
    name = organisation.strip()
    if "@" not in address:
        raise ProvisioningError(f"{email!r} n'est pas une adresse e-mail.")
    if not name:
        raise ProvisioningError("Le nom de l'organisation est vide.")
    for key in [*agents, *remove]:
        if find(key) is None:
            raise ProvisioningError(f"Aucun agent {key!r} dans le registre (agents/registry.yaml).")
    if (instructions is not None or clear_instructions) and not agents:
        raise ProvisioningError("Des consignes vont à un agent : précisez --agent.")
    if instructions is not None and not instructions.strip():
        raise ProvisioningError("Les consignes sont vides.")
    if instructions is not None and len(instructions) > MAX_INSTRUCTIONS:
        raise ProvisioningError(f"Les consignes dépassent {MAX_INSTRUCTIONS} caractères.")
    if monthly_credits is not None and monthly_credits < 0:
        raise ProvisioningError("La capacité IA du contrat n'est jamais négative.")
    changed: list[str] = []

    with system_scope():
        async with session_factory() as session:
            user, account = await _account(
                session,
                address,
                password,
                first_name=first_name,
                last_name=last_name,
                now=moment,
                changed=changed,
            )
            workspaces = WorkspaceRepository(session)
            workspace = await workspaces.get_by_slug(slugify(name))
            if workspace is None:
                workspace = await WorkspaceService(workspaces, session).create(
                    name, owner_user_id=user.id, default_language="fr"
                )
                changed.append("organisation créée")
            elif workspace.name != name:
                workspace.name = name
                changed.append("nom de l'organisation")

            with workspace_scope(workspace.id):
                memberships = MembershipRepository(session, workspace.id)
                seat = await memberships.get_for_user(user.id)
                if seat is None:
                    memberships.create(user_id=user.id, role=Role.OWNER)
                    await memberships.flush()
                    changed.append("compte rattaché, propriétaire")
                elif seat.role is not Role.OWNER:
                    seat.role = Role.OWNER
                    changed.append("compte propriétaire")

                current = await plan_of(session, workspace.id)
                wanted_credits: int | None = (
                    monthly_credits if monthly_credits is not None else current.monthly_credits
                )
                if current.name != ENTERPRISE or (
                    monthly_credits is not None and current.monthly_credits != monthly_credits
                ):
                    await set_plan(
                        session,
                        workspace.id,
                        ENTERPRISE,
                        by=OPERATOR,
                        reason=f"Contrat Entreprise : {name}"[:300],
                        monthly_credits=monthly_credits,
                        at=moment,
                    )
                    changed.append("plan Entreprise")
                    wanted_credits = monthly_credits

                for key in agents:
                    if await assign(session, workspace.id, key, by=OPERATOR, now=moment):
                        changed.append(f"agent dédié {key}")
                for key in remove:
                    if await unassign(session, workspace.id, key):
                        changed.append(f"agent dédié retiré {key}")
                if instructions is not None or clear_instructions:
                    given = None if clear_instructions else instructions
                    for key in agents:
                        if await instruct(session, workspace.id, key, given):
                            changed.append(f"consignes de {key}")

                contract = contract_of(workspace)
                had = contract.get("contact")
                kept = dict(had) if isinstance(had, dict) else {}
                updated: dict[str, object] = {
                    "type": "Entreprise",
                    "since": contract.get("since") or moment.date().isoformat(),
                    "contact": {
                        "name": contact_name if contact_name is not None else kept.get("name"),
                        "email": contact_email if contact_email is not None else kept.get("email"),
                    },
                }
                if updated != contract:
                    workspace.settings = {**(workspace.settings or {}), "enterprise": updated}
                    if contract:
                        changed.append("contrat")
                    else:
                        changed.append("contrat créé")

                assigned = sorted(await dedicated_to(session, workspace.id))
                own = await _own(session, workspace.id, assigned)
                if changed:
                    audit(
                        session,
                        workspace.id,
                        "workspace",
                        "workspace.enterprise_provisioned",
                        detail={
                            "changed": changed,
                            "agents": assigned,
                            "account": account,
                            "credits": wanted_credits,
                        },
                        at=moment,
                    )
                await session.commit()
                return Provisioned(
                    organisation=name,
                    workspace_id=str(workspace.id),
                    email=address,
                    account=account,
                    role=Role.OWNER.value,
                    plan=ENTERPRISE,
                    agents=assigned,
                    contract=updated,
                    changed=changed,
                    instructions=own,
                )


async def show(organisation: str) -> dict[str, object]:
    """An organisation as it stands: its plan, its owners, its agents, its
    contract — never a password, never a secret."""
    with system_scope():
        async with session_factory() as session:
            workspace = await WorkspaceRepository(session).get_by_slug(slugify(organisation))
            if workspace is None:
                raise ProvisioningError(f"Aucune organisation « {organisation} ».")
            with workspace_scope(workspace.id):
                plan = await plan_of(session, workspace.id)
                agents = sorted(await dedicated_to(session, workspace.id))
                return {
                    "organisation": workspace.name,
                    "workspace_id": str(workspace.id),
                    "plan": plan.name,
                    "agents": agents,
                    "instructions": await _own(session, workspace.id, agents),
                    "contract": contract_of(workspace),
                }


async def _own(
    session: AsyncSession, workspace_id: uuid.UUID, agents: Sequence[str]
) -> dict[str, int]:
    """Its agents with their own instructions — their length, never their words."""
    found: dict[str, int] = {}
    for key in agents:
        said = await instructions_of(session, workspace_id, key)
        if said:
            found[key] = len(said)
    return found


def _instructions(given: str | None) -> str | None:
    """The instructions of `--instructions`: a file's, or the standard input's (`-`)."""
    if given is None:
        return None
    if given == "-":
        return sys.stdin.read()
    try:
        return Path(given).read_text(encoding="utf-8")
    except OSError as error:
        raise ProvisioningError(f"Consignes illisibles : {given} ({error.strerror}).") from error


def _password(interactive: bool) -> str | None:
    """The first password: from the environment, else asked — hidden."""
    said = os.environ.get(PASSWORD_ENV)
    if said:
        return said
    if interactive:
        return getpass.getpass("Mot de passe du compte (s'il faut le créer) : ") or None
    return None


async def main(argv: list[str] | None = None, *, interactive: bool | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m leka.ops.enterprise")
    commands = parser.add_subparsers(dest="command", required=True)
    making = commands.add_parser("provision", help="créer ou mettre à jour une organisation")
    making.add_argument("--email", required=True)
    making.add_argument("--organisation", required=True)
    making.add_argument("--agent", action="append", default=[], help="un agent dédié")
    making.add_argument("--remove-agent", action="append", default=[], help="un agent à retirer")
    making.add_argument("--first-name")
    making.add_argument("--last-name")
    making.add_argument("--credits", type=int, help="la capacité IA mensuelle du contrat")
    making.add_argument("--contact-name", help="le contact dédié de l'organisation")
    making.add_argument("--contact-email")
    own = making.add_mutually_exclusive_group()
    own.add_argument(
        "--instructions",
        help="les consignes propres des agents de --agent : un fichier, - pour l'entrée standard",
    )
    own.add_argument(
        "--clear-instructions", action="store_true", help="revenir aux consignes du registre"
    )
    showing = commands.add_parser("show", help="afficher une organisation")
    showing.add_argument("--organisation", required=True)
    args = parser.parse_args(argv)
    asks = sys.stdin.isatty() if interactive is None else interactive
    try:
        if args.command == "show":
            sys.stdout.write(
                json.dumps(await show(args.organisation), ensure_ascii=False, indent=2)
            )
            sys.stdout.write("\n")
            return 0
        done = await provision(
            args.email,
            args.organisation,
            password=_password(asks),
            agents=args.agent,
            remove=args.remove_agent,
            first_name=args.first_name,
            last_name=args.last_name,
            monthly_credits=args.credits,
            contact_name=args.contact_name,
            contact_email=args.contact_email,
            instructions=_instructions(args.instructions),
            clear_instructions=args.clear_instructions,
        )
    except ProvisioningError as refusal:
        sys.stdout.write(f"Refusé : {refusal}\n")
        return 1
    sys.stdout.write(json.dumps(asdict(done), ensure_ascii=False, indent=2) + "\n")
    return 0


__all__ = ["Provisioned", "ProvisioningError", "contract_of", "main", "provision", "show"]


if __name__ == "__main__":  # pragma: no cover - the process itself
    load_schema()  # every table, as the API has (leka/schema.py)
    sys.exit(asyncio.run(main()))
