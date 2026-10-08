"""What authentication emails say, in French — LEKA's first users are.

Three messages, each in two parts: plain text, which every client shows and
spam filters trust, and a sober HTML version with one button and the same
link written out beneath it, for the clients that strip buttons. No
template engine: three messages do not need one.

Each says what happened, what to do, how long the link lasts, and what to
do if it was not you.
"""

from __future__ import annotations

from html import escape

from leka.core.config import settings
from leka.identity.email import EmailMessage
from leka.identity.links import invitation_link, reset_link, verification_link

SIGNATURE = "L'équipe LEKA"


def _hours(value: int) -> str:
    return f"{value} heure" if value == 1 else f"{value} heures"


def _html(title: str, lines: list[str], button: str | None = None, link: str | None = None) -> str:
    paragraphs = "".join(f'<p style="margin:0 0 16px">{escape(line)}</p>' for line in lines)
    action = ""
    if button and link:
        safe = escape(link, quote=True)
        action = (
            f'<p style="margin:24px 0"><a href="{safe}" style="background:#071143;color:#ffffff;'
            f'padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:600">'
            f"{escape(button)}</a></p>"
            f'<p style="margin:0 0 16px;font-size:13px;color:#5f6480">Si le bouton ne '
            f"fonctionne pas, copiez ce lien dans votre navigateur :<br>"
            f'<a href="{safe}" style="color:#4e0af4;word-break:break-all">{escape(link)}</a></p>'
        )
    return (
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
        'font-size:15px;line-height:1.6;color:#262952;max-width:520px">'
        f'<h1 style="font-size:20px;color:#071143;margin:0 0 16px">{escape(title)}</h1>'
        f"{paragraphs}{action}"
        f'<p style="margin:24px 0 0;color:#5f6480">{SIGNATURE}</p></div>'
    )


def verification(to: str, token: str) -> EmailMessage:
    link = verification_link(token)
    hours = _hours(settings.verification_token_lifetime_hours)
    intro = "Bienvenue sur LEKA. Confirmez votre adresse pour activer votre compte."
    note = (
        f"Ce lien est valable {hours} et ne fonctionne qu'une fois. Si vous n'êtes pas "
        "à l'origine de cette inscription, ignorez ce message : aucun compte ne sera activé."
    )
    return EmailMessage(
        to=to,
        subject="Confirmez votre adresse e-mail LEKA",
        body=f"{intro}\n\n{link}\n\n{note}\n\n{SIGNATURE}\n",
        html=_html("Confirmez votre adresse", [intro, note], "Confirmer mon adresse", link),
    )


def password_reset(to: str, token: str) -> EmailMessage:
    link = reset_link(token)
    hours = _hours(settings.reset_token_lifetime_hours)
    intro = "Une réinitialisation du mot de passe a été demandée pour votre compte LEKA."
    note = (
        f"Ce lien est valable {hours} et ne fonctionne qu'une fois. Si vous n'êtes pas "
        "à l'origine de cette demande, ignorez ce message : votre mot de passe reste inchangé."
    )
    return EmailMessage(
        to=to,
        subject="Réinitialisez votre mot de passe LEKA",
        body=f"{intro}\n\n{link}\n\n{note}\n\n{SIGNATURE}\n",
        html=_html(
            "Réinitialisez votre mot de passe", [intro, note], "Choisir un mot de passe", link
        ),
    )


ROLES = {"owner": "propriétaire", "admin": "administrateur", "member": "membre"}


def invitation(to: str, token: str, *, workspace: str, inviter: str, role: str) -> EmailMessage:
    """An invitation to a workspace: who invites, where, as what."""
    link = invitation_link(token)
    intro = (
        f"{inviter} vous invite à rejoindre l'espace « {workspace} » sur LEKA, "
        f"en tant que {ROLES.get(role, role)}."
    )
    note = (
        "Ce lien est valable 7 jours et ne fonctionne qu'une fois. Connectez-vous, ou "
        "créez votre compte avec cette adresse, pour rejoindre l'espace. Si vous ne "
        "vous attendiez pas à cette invitation, ignorez ce message."
    )
    return EmailMessage(
        to=to,
        subject=f"{inviter} vous invite sur LEKA",
        body=f"{intro}\n\n{link}\n\n{note}\n\n{SIGNATURE}\n",
        html=_html(f"Rejoignez « {workspace} »", [intro, note], "Rejoindre l'espace", link),
    )


def already_registered(to: str) -> EmailMessage:
    """For a VERIFIED account. An unverified one gets a new link instead."""
    lines = [
        "Quelqu'un vient d'essayer de créer un compte LEKA avec votre adresse, qui en a déjà un.",
        "Si c'était vous, connectez-vous, ou utilisez « Mot de passe oublié ? » sur la "
        "page de connexion. Sinon, vous n'avez rien à faire : aucun compte n'a été créé "
        "et rien n'a changé.",
    ]
    return EmailMessage(
        to=to,
        subject="Une inscription a été tentée avec votre adresse",
        body="\n\n".join([*lines, f"{settings.web_url}/login", SIGNATURE]) + "\n",
        html=_html("Vous avez déjà un compte", lines, "Se connecter", f"{settings.web_url}/login"),
    )
