"""The codes LEKA ADMIN sends by email, and the two emails (LEKA-545).

A code rather than a link: LEKA ADMIN is an Android app, and a code typed in
the app works whatever the phone does with links. Eight characters from an
alphabet without look-alikes (no 0 and O, no 1 and I), shown as ABCD-EFGH —
about a trillion possibilities — kept hashed, valid 72 hours for an
invitation and 15 minutes to reset a password, burnt after five wrong tries.

The emails are in French: they go to LEKA's team.
"""

from __future__ import annotations

import re
import secrets
from datetime import timedelta

from leka.admin.access import AdminRole
from leka.identity import EmailMessage

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LENGTH = 8
MAX_ATTEMPTS = 5
LIFETIME = {"invite": timedelta(hours=72), "reset": timedelta(minutes=15)}

ROLE_NAMES = {
    AdminRole.SUPER_ADMIN: "Super Admin",
    AdminRole.OPERATIONS: "Operations",
    AdminRole.SUPPORT: "Support",
    AdminRole.FINANCE: "Finance",
}


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def normalised(typed: str) -> str:
    """What was typed, as it was sent: capitals, no dash, no space."""
    return re.sub(r"[^A-Z0-9]", "", typed.upper())


def shown(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def invitation(to: str, name: str, role: str, by: str, code: str) -> EmailMessage:
    role_name = ROLE_NAMES.get(AdminRole(role), role)
    return EmailMessage(
        to=to,
        subject="Votre accès à LEKA ADMIN",
        language="fr",
        body=(
            f"Bonjour {name},\n\n"
            f"{by} vous a ouvert un accès à LEKA ADMIN, la console de l'équipe LEKA, "
            f"avec le rôle {role_name}.\n\n"
            "Pour choisir votre mot de passe, ouvrez l'application LEKA ADMIN, touchez "
            "« Première connexion », puis saisissez votre adresse et ce code :\n\n"
            f"    {shown(code)}\n\n"
            "Le code est valable 72 heures. Si vous n'attendiez pas ce message, ignorez-le : "
            "rien ne s'ouvre sans lui.\n"
        ),
    )


def reset(to: str, name: str, code: str) -> EmailMessage:
    return EmailMessage(
        to=to,
        subject="Réinitialiser votre mot de passe LEKA ADMIN",
        language="fr",
        body=(
            f"Bonjour {name},\n\n"
            "Pour choisir un nouveau mot de passe LEKA ADMIN, saisissez ce code dans "
            "l'application :\n\n"
            f"    {shown(code)}\n\n"
            "Il est valable 15 minutes. Toutes vos sessions seront fermées une fois le mot "
            "de passe changé. Si vous n'avez rien demandé, ignorez ce message : votre mot de "
            "passe reste le même.\n"
        ),
    )
