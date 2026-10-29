"""How every e-mail LEKA sends looks (2026-10-29, Haitam: « les mails
envoyés par LEKA sont un peu simples, on peut mettre le logo LEKA avec un
truc stylé »): its logo above, a white card with the brand's line along its
top, the title, the words, one button, and below what LEKA is.

Tables and inline styles, as mail clients read them — Outlook and Gmail
drop a style sheet; the logo a PNG at its absolute address (an SVG Gmail
does not show). The plain text stays the e-mail: this is its dress.

An e-mail written as plain text only — an alert, a credits warning, a
decision escalated — is dressed here at sending: its subject, the title;
its lines, paragraphs; its « - » lines, a list; its addresses, links; and a
button to LEKA.
"""

from __future__ import annotations

import re
from dataclasses import replace
from html import escape
from urllib.parse import urlsplit

from leka.core import languages
from leka.core.config import settings
from leka.identity.email import EmailMessage

NAVY = "#071143"
VIOLET = "#4e0af4"
INK = "#262952"
MUTED = "#6b7090"
LINE = "#e3e5f0"
PAGE = "#f3f4fa"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
LOGO = "/brand/leka-wordmark.png"  # 300 by 72, shown at 120 by 29
_URL = re.compile(r"https?://[^\s<>()]+[^\s<>().,;:!?»]")

WORDS: dict[str, dict[str, str]] = {
    "fr": {
        "open": "Ouvrir LEKA",
        "footer": (
            "Vous recevez cet e-mail parce que vous utilisez LEKA, l'IA de votre environnement IT."
        ),
    },
    "en": {
        "open": "Open LEKA",
        "footer": "You receive this e-mail because you use LEKA, the AI of your IT environment.",
    },
}


def _words(language: str | None) -> dict[str, str]:
    return WORDS.get((language or "").split("-")[0]) or WORDS["en"]


def _linked(text: str) -> str:
    """`text`, escaped, its addresses links."""
    out, last = [], 0
    for match in _URL.finditer(text):
        out.append(escape(text[last : match.start()]))
        url = escape(match.group(0), quote=True)
        out.append(f'<a href="{url}" style="color:{VIOLET};word-break:break-all">{url}</a>')
        last = match.end()
    out.append(escape(text[last:]))
    return "".join(out)


def paragraphs(lines: list[str]) -> str:
    """Lines as the card's paragraphs: « - » lines gathered in a list."""
    out: list[str] = []
    items: list[str] = []

    def close() -> None:
        if items:
            out.append(f'<ul style="margin:0 0 16px;padding:0 0 0 20px">{"".join(items)}</ul>')
            items.clear()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("- ", "• ")):
            items.append(f'<li style="margin:0 0 6px">{_linked(stripped[2:])}</li>')
            continue
        close()
        if stripped:
            out.append(f'<p style="margin:0 0 16px">{_linked(stripped)}</p>')
    close()
    return "".join(out)


def button(label: str, link: str) -> str:
    """One button, as every client draws one — and its address beneath."""
    safe = escape(link, quote=True)
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0 8px">'
        f'<tr><td style="border-radius:10px;background:{VIOLET}">'
        f'<a href="{safe}" style="display:inline-block;padding:13px 22px;font-family:{FONT};'
        f"font-size:15px;font-weight:600;color:#ffffff;text-decoration:none;border-radius:10px"
        f'">{escape(label)}</a></td></tr></table>'
    )


def layout(
    title: str,
    body_html: str,
    *,
    language: str | None,
    preheader: str = "",
    action: tuple[str, str] | None = None,
    after: str = "",
) -> str:
    """The whole e-mail: logo, card, title, `body_html`, the button
    `action` (label, address), `after` — beneath it — and the footer."""
    web = settings.web_url
    host = urlsplit(web).netloc or web
    words = _words(language)
    lang = escape(language or "fr", quote=True)
    direction = languages.direction(language) if language else "ltr"
    cta = button(*action) if action else ""
    return (
        "<!doctype html>"
        f'<html lang="{lang}" dir="{direction}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        f"<title>{escape(title)}</title></head>"
        f'<body style="margin:0;padding:0;background:{PAGE}">'
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0">'
        f"{escape(preheader)}</div>"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{PAGE}"><tr><td align="center" style="padding:32px 12px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:560px">'
        f'<tr><td style="padding:0 4px 20px"><a href="{escape(web, quote=True)}">'
        f'<img src="{escape(web + LOGO, quote=True)}" width="120" height="29" alt="LEKA" '
        'style="display:block;border:0;outline:none"></a></td></tr>'
        f'<tr><td style="background:#ffffff;border:1px solid {LINE};border-radius:14px">'
        f'<div style="height:4px;background:{VIOLET};'
        f"background-image:linear-gradient(90deg,{NAVY},{VIOLET});"
        'border-radius:14px 14px 0 0"></div>'
        f'<div style="padding:30px 32px 26px;font-family:{FONT};font-size:15px;'
        f'line-height:1.6;color:{INK}">'
        f'<h1 style="margin:0 0 16px;font-size:22px;line-height:1.3;color:{NAVY}">'
        f"{escape(title)}</h1>{body_html}{cta}{after}</div></td></tr>"
        f'<tr><td style="padding:20px 12px 8px;font-family:{FONT};font-size:12px;'
        f'line-height:1.5;color:{MUTED};text-align:center">{escape(words["footer"])}<br>'
        f'<a href="{escape(web, quote=True)}" style="color:{VIOLET};text-decoration:none">'
        f"{escape(host)}</a></td></tr></table></td></tr></table></body></html>"
    )


def dressed(message: EmailMessage) -> EmailMessage:
    """A message as it is sent: one written as plain text only, dressed —
    its subject the title, its words the card, a button to LEKA."""
    if message.html:
        return message
    html = layout(
        message.subject,
        paragraphs(message.body.strip().split("\n")),
        language=message.language,
        preheader=message.subject,
        action=(_words(message.language)["open"], settings.web_url),
    )
    return replace(message, html=html)
