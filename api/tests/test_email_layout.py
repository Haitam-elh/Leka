"""How every e-mail LEKA sends looks (2026-10-29: « on peut mettre le logo
LEKA avec un truc stylé »), pure.

What these protect: an e-mail written as plain text only — an alert, a
credits warning — sent dressed: the logo at its absolute address, the
subject as its title, its « - » lines a list, its addresses links, a button
to LEKA; the plain text unchanged; one already dressed left as it is; the
authentication e-mails in the same dress, their link still written out;
words escaped, never HTML.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from leka.core.config import settings
from leka.identity import email_layout
from leka.identity.email import EmailMessage, ResendEmailSender
from leka.identity.email_layout import dressed
from leka.identity.messages import verification

ALERT = EmailMessage(
    to="ada@acme.example",
    subject="LEKA : 2 alertes sur Acme",
    body=(
        "LEKA a détecté de nouveaux problèmes :\n- payment-api : indisponible\n"
        "- <billing-db> : dégradé\n\nLe détail : https://leka-core.com/environment."
    ),
    language="fr",
)


@pytest.fixture(autouse=True)
def web(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        email_layout, "settings", settings.model_copy(update={"web_url": "https://leka-core.com"})
    )


def test_a_plain_text_email_is_sent_dressed() -> None:
    sent = dressed(ALERT)
    html = sent.html or ""
    assert sent.body == ALERT.body
    assert '<img src="https://leka-core.com/brand/leka-wordmark.png"' in html
    assert ">LEKA : 2 alertes sur Acme</h1>" in html
    assert html.count("<li") == 2 and "&lt;billing-db&gt;" in html and "<billing-db>" not in html
    assert '<a href="https://leka-core.com/environment"' in html
    assert ">Ouvrir LEKA</a>" in html and 'lang="fr"' in html
    # Already dressed: as it is.
    assert dressed(sent) is sent


def test_an_english_email_is_dressed_in_english() -> None:
    html = dressed(EmailMessage(to="a", subject="s", body="b", language="en")).html or ""
    assert ">Open LEKA</a>" in html and "You receive this e-mail" in html


def test_the_authentication_emails_wear_the_same_dress() -> None:
    message = verification("nora@acme.example", "tok123", language="fr")
    html = message.html or ""
    assert "leka-wordmark.png" in html and ">Confirmer mon adresse</a>" in html
    assert "Si le bouton ne fonctionne pas" in html and "équipe LEKA" in html


def test_resend_sends_the_dress_and_the_plain_text() -> None:
    sent: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        import json

        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "e1"})

    real = httpx.AsyncClient

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(answer), **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(httpx, "AsyncClient", client)
        asyncio.run(ResendEmailSender("k", "LEKA <bonjour@leka-core.com>").deliver(ALERT))
    [payload] = sent
    assert payload["text"] == ALERT.body
    assert "leka-wordmark.png" in payload["html"]
