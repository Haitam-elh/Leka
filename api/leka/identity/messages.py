"""What authentication emails say, in each language e-mails are translated
into (leka/core/languages.yaml, `ui.emails`) — French and English today.

Four messages, each in two parts: plain text, which every client shows and
spam filters trust, and a sober HTML version with one button and the same
link written out beneath it, for the clients that strip buttons. No
template engine: four messages do not need one.

Each says what happened, what to do, how long the link lasts, and what to
do if it was not you.

`language` is the language the e-mail is written in, already resolved
(`email_language`): a language e-mails are not translated into falls back
along its chain, and is never an empty e-mail.
"""

from __future__ import annotations

from html import escape

from leka.core import languages
from leka.core.config import settings
from leka.identity.email import EmailMessage
from leka.identity.email_layout import MUTED, VIOLET, layout, paragraphs
from leka.identity.links import invitation_link, reset_link, verification_link

# Every word, by language. Each language has the same keys —
# tests/test_auth_emails.py holds them to it, and to the catalogue.
WORDS: dict[str, dict[str, str]] = {
    "fr": {
        "signature": "L'équipe LEKA",
        "fallback": "Si le bouton ne fonctionne pas, copiez ce lien dans votre navigateur :",
        "hour": "{n} heure",
        "hours": "{n} heures",
        "verification.subject": "Confirmez votre adresse e-mail LEKA",
        "verification.title": "Confirmez votre adresse",
        "verification.intro": (
            "Bienvenue sur LEKA. Confirmez votre adresse pour activer votre compte."
        ),
        "verification.note": (
            "Ce lien est valable {hours} et ne fonctionne qu'une fois. Si vous n'êtes pas "
            "à l'origine de cette inscription, ignorez ce message : aucun compte ne sera activé."
        ),
        "verification.button": "Confirmer mon adresse",
        "reset.subject": "Réinitialisez votre mot de passe LEKA",
        "reset.title": "Réinitialisez votre mot de passe",
        "reset.intro": (
            "Une réinitialisation du mot de passe a été demandée pour votre compte LEKA."
        ),
        "reset.note": (
            "Ce lien est valable {hours} et ne fonctionne qu'une fois. Si vous n'êtes pas "
            "à l'origine de cette demande, ignorez ce message : votre mot de passe reste inchangé."
        ),
        "reset.button": "Choisir un mot de passe",
        "role.owner": "propriétaire",
        "role.admin": "administrateur",
        "role.member": "membre",
        "invitation.subject": "{inviter} vous invite sur LEKA",
        "invitation.title": "Rejoignez « {workspace} »",
        "invitation.intro": (
            "{inviter} vous invite à rejoindre l'espace « {workspace} » sur LEKA, "
            "en tant que {role}."
        ),
        "invitation.note": (
            "Ce lien est valable 7 jours et ne fonctionne qu'une fois. Connectez-vous, ou "
            "créez votre compte avec cette adresse, pour rejoindre l'espace. Si vous ne "
            "vous attendiez pas à cette invitation, ignorez ce message."
        ),
        "invitation.button": "Rejoindre l'espace",
        "registered.subject": "Une inscription a été tentée avec votre adresse",
        "registered.title": "Vous avez déjà un compte",
        "registered.intro": (
            "Quelqu'un vient d'essayer de créer un compte LEKA avec votre adresse, "
            "qui en a déjà un."
        ),
        "registered.note": (
            "Si c'était vous, connectez-vous, ou utilisez « Mot de passe oublié ? » sur la "
            "page de connexion. Sinon, vous n'avez rien à faire : aucun compte n'a été créé "
            "et rien n'a changé."
        ),
        "registered.button": "Se connecter",
    },
    "en": {
        "signature": "The LEKA team",
        "fallback": "If the button does not work, copy this link into your browser:",
        "hour": "{n} hour",
        "hours": "{n} hours",
        "verification.subject": "Confirm your LEKA email address",
        "verification.title": "Confirm your address",
        "verification.intro": "Welcome to LEKA. Confirm your address to activate your account.",
        "verification.note": (
            "This link is valid for {hours} and works only once. If you did not sign up, "
            "ignore this message: no account will be activated."
        ),
        "verification.button": "Confirm my address",
        "reset.subject": "Reset your LEKA password",
        "reset.title": "Reset your password",
        "reset.intro": "A password reset was requested for your LEKA account.",
        "reset.note": (
            "This link is valid for {hours} and works only once. If you did not ask for it, "
            "ignore this message: your password stays as it is."
        ),
        "reset.button": "Choose a password",
        "role.owner": "an owner",
        "role.admin": "an administrator",
        "role.member": "a member",
        "invitation.subject": "{inviter} invites you to LEKA",
        "invitation.title": "Join “{workspace}”",
        "invitation.intro": (
            "{inviter} invites you to join the workspace “{workspace}” on LEKA, as {role}."
        ),
        "invitation.note": (
            "This link is valid for 7 days and works only once. Sign in, or create your "
            "account with this address, to join the workspace. If you were not expecting "
            "this invitation, ignore this message."
        ),
        "invitation.button": "Join the workspace",
        "registered.subject": "Someone tried to sign up with your address",
        "registered.title": "You already have an account",
        "registered.intro": (
            "Someone just tried to create a LEKA account with your address, which already has one."
        ),
        "registered.note": (
            "If it was you, sign in, or use “Forgot password?” on the sign-in page. "
            "Otherwise there is nothing to do: no account was created and nothing changed."
        ),
        "registered.button": "Sign in",
    },
}


def email_language(
    chosen: str | None, *, said: str | None = None, workspace: str | None = None
) -> str:
    """The language an e-mail to someone is written in: the one they chose,
    else the one the page they used was shown in, else their workspace's —
    the first of its chain that e-mails are translated into."""
    return languages.shown("emails", chosen or said, workspace=workspace)


def _words(language: str) -> dict[str, str]:
    return WORDS.get(language) or WORDS[languages.catalogue().default]


def _hours(words: dict[str, str], value: int) -> str:
    return (words["hour"] if value == 1 else words["hours"]).format(n=value)


def _html(
    words: dict[str, str],
    language: str,
    title: str,
    lines: list[str],
    button: str | None = None,
    link: str | None = None,
) -> str:
    """In LEKA's dress (email_layout): the button, and its link written out
    beneath it for the clients that strip buttons; the signature."""
    after = ""
    if button and link:
        safe = escape(link, quote=True)
        after = (
            f'<p style="margin:0 0 16px;font-size:13px;color:{MUTED}">'
            f"{escape(words['fallback'])}<br>"
            f'<a href="{safe}" style="color:{VIOLET};word-break:break-all">{escape(link)}</a></p>'
        )
    after += f'<p style="margin:20px 0 0;color:{MUTED}">{escape(words["signature"])}</p>'
    return layout(
        title,
        paragraphs(lines),
        language=language,
        preheader=lines[0] if lines else title,
        action=(button, link) if button and link else None,
        after=after,
    )


def _message(
    to: str, language: str, key: str, link: str, values: dict[str, str] | None = None
) -> EmailMessage:
    words = _words(language)
    said = {
        name: text.format(**(values or {}))
        for name, text in words.items()
        if name.startswith(f"{key}.")
    }
    intro, note = said[f"{key}.intro"], said[f"{key}.note"]
    return EmailMessage(
        to=to,
        subject=said[f"{key}.subject"],
        body=f"{intro}\n\n{link}\n\n{note}\n\n{words['signature']}\n",
        html=_html(
            words, language, said[f"{key}.title"], [intro, note], said[f"{key}.button"], link
        ),
        language=language,
    )


def verification(to: str, token: str, *, language: str) -> EmailMessage:
    hours = _hours(_words(language), settings.verification_token_lifetime_hours)
    return _message(to, language, "verification", verification_link(token), {"hours": hours})


def password_reset(to: str, token: str, *, language: str) -> EmailMessage:
    hours = _hours(_words(language), settings.reset_token_lifetime_hours)
    return _message(to, language, "reset", reset_link(token), {"hours": hours})


def invitation(
    to: str, token: str, *, workspace: str, inviter: str, role: str, language: str
) -> EmailMessage:
    """An invitation to a workspace: who invites, where, as what."""
    words = _words(language)
    return _message(
        to,
        language,
        "invitation",
        invitation_link(token),
        {"inviter": inviter, "workspace": workspace, "role": words.get(f"role.{role}", role)},
    )


def already_registered(to: str, *, language: str) -> EmailMessage:
    """For a VERIFIED account. An unverified one gets a new link instead."""
    return _message(to, language, "registered", f"{settings.web_url}/login")
