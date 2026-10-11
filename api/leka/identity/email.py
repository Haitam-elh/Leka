"""Sending the two emails authentication cannot work without.

A protocol with two implementations, chosen by configuration rather than by
an `if` in the flow that sends. Without an API key the console sender writes
the message to the log, which is what makes verification and recovery
testable with no account anywhere — and what lets a new developer click a
verification link on their first afternoon.

This lives in leka.identity because identity is the only module that sends
email today. When a second one needs it — a digest, an incident alert — it
moves to leka.platform, and this module imports it from there.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import smtplib
import ssl
import sys
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol, runtime_checkable

import httpx
import structlog

from leka.core.config import settings

logger = structlog.get_logger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str
    # Optional: the plain-text body is always sent, and is what counts.
    html: str | None = None
    # The language it is written in (a tag of leka/core/languages.yaml), sent
    # as Content-Language: a mail client may offer to translate it, and
    # reads it aloud in the right voice.
    language: str | None = None


@runtime_checkable
class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Writes the message to the log instead of sending it.

    The default outside production. The body contains a verification or reset
    link, which is a credential — so this is only ever acceptable where the
    logs are a developer's own terminal. leka.core.logging redacts the rest
    of authentication; this one deliberately does not, because reading the
    link is the entire point.
    """

    async def send(self, message: EmailMessage) -> None:
        logger.info(
            "email_not_sent_console_sender",
            to=message.to,
            subject=message.subject,
            body=message.body,
        )
        # For the browser tests: they read the link from here rather than from
        # a terminal. Refused in staging and production (core/config.py).
        if settings.email_outbox_file is not None:
            with settings.email_outbox_file.open("a", encoding="utf-8") as outbox:
                outbox.write(json.dumps(asdict(message)) + "\n")


class ResendEmailSender:
    """Sends through Resend.

    Used only when LEKA_RESEND_API_KEY is set. A delivery failure is logged
    and swallowed: an email provider having a bad afternoon must not turn a
    successful registration into a 500 for someone who has already been
    written to the database. The user can ask for another link.
    """

    def __init__(self, api_key: str, sender: str) -> None:
        self._api_key = api_key
        self._sender = sender

    async def deliver(self, message: EmailMessage) -> None:
        """Send, and raise if it fails. What the diagnostic uses."""
        payload: dict[str, object] = {
            "from": self._sender,
            "to": [message.to],
            "subject": message.subject,
            "text": message.body,
        }
        if message.html:
            payload["html"] = message.html
        if message.language:
            payload["headers"] = {"Content-Language": message.language}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                RESEND_ENDPOINT,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            response.raise_for_status()

    async def send(self, message: EmailMessage) -> None:
        try:
            await self.deliver(message)
        except httpx.HTTPError as error:
            # No body, no recipient in the log beyond what is already there:
            # the body carries the link.
            logger.warning("email_delivery_failed", to=message.to, error=str(error))


class SmtpEmailSender:
    """Sends through an ordinary mailbox over SMTP.

    Used when LEKA_SMTP_HOST and LEKA_SMTP_PASSWORD are set — which means a
    mailbox we already pay for, rather than a second account with an email
    API. OVH, Gmail, Fastmail and anything else speaking SMTP work the same
    way.

    smtplib is synchronous and blocks. Run in a worker thread so that one
    slow handshake does not stall every other request this process is
    serving: an email that takes two seconds must not cost two seconds of
    the whole API.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        *,
        use_ssl: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._use_ssl = use_ssl

    def _send_blocking(self, message: EmailMessage) -> None:
        payload: MIMEText | MIMEMultipart
        if message.html:
            # Text first, HTML last: a client shows the last part it can.
            payload = MIMEMultipart("alternative")
            payload.attach(MIMEText(message.body, "plain", "utf-8"))
            payload.attach(MIMEText(message.html, "html", "utf-8"))
        else:
            payload = MIMEText(message.body, "plain", "utf-8")
        payload["Subject"] = message.subject
        payload["From"] = self._sender
        payload["To"] = message.to
        if message.language:
            payload["Content-Language"] = message.language

        context = ssl.create_default_context()
        if self._use_ssl:
            # Port 465: TLS from the first byte.
            with smtplib.SMTP_SSL(self._host, self._port, timeout=15, context=context) as server:
                server.login(self._username, self._password)
                server.send_message(payload)
        else:
            # Port 587: plain connection, upgraded with STARTTLS.
            with smtplib.SMTP(self._host, self._port, timeout=15) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(self._username, self._password)
                server.send_message(payload)

    async def deliver(self, message: EmailMessage) -> None:
        """Send, and raise if it fails. What the diagnostic uses."""
        await asyncio.to_thread(self._send_blocking, message)

    async def send(self, message: EmailMessage) -> None:
        try:
            await self.deliver(message)
        except (smtplib.SMTPException, OSError) as error:
            # Logged and swallowed, like the API sender: a mail server having
            # a bad afternoon must not turn a successful registration into a
            # 500 for someone already written to the database. They can ask
            # for another link.
            logger.warning("email_delivery_failed", to=message.to, error=str(error))


def build_email_sender() -> EmailSender:
    """Pick an implementation from configuration, once, at startup.

    SMTP first: if a real mailbox is configured, use it rather than asking
    for a second account somewhere else.
    """
    if settings.smtp_configured:
        assert settings.smtp_host is not None
        assert settings.smtp_password is not None
        return SmtpEmailSender(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_username or settings.email_from,
            settings.smtp_password.get_secret_value(),
            settings.email_from,
            use_ssl=settings.smtp_use_ssl,
        )
    if settings.resend_api_key is not None:
        return ResendEmailSender(settings.resend_api_key.get_secret_value(), settings.email_from)
    return ConsoleEmailSender()


class DeferredEmailSender:
    """Queues each message to go once the request is over.

    The route hands in FastAPI's BackgroundTasks.add_task. Background tasks
    run after the response is sent, and the request's transaction commits
    before the response (DatabaseSession, LEKA-343) — so a message leaves
    only once the token it carries is in the database. Sent from inside the
    request, a link could name a token the database then never kept, if the
    commit failed after the send.
    """

    def __init__(
        self,
        inner: EmailSender,
        schedule: Callable[[Callable[[EmailMessage], Awaitable[None]], EmailMessage], None],
    ) -> None:
        self._inner = inner
        self._schedule = schedule

    async def send(self, message: EmailMessage) -> None:
        self._schedule(self._inner.send, message)


def _say(line: str) -> None:
    # A command-line tool's output is its interface, not a log line.
    sys.stdout.write(line + "\n")


async def _diagnose(address: str) -> int:
    """Send one real test message with the configured sender, errors in the open."""
    sender = build_email_sender()
    _say(f"Sender: {type(sender).__name__}, from {settings.email_from}")
    if isinstance(sender, ConsoleEmailSender):
        _say("No real sender is configured (LEKA_SMTP_HOST / LEKA_SMTP_PASSWORD, or")
        _say("LEKA_RESEND_API_KEY): the message would only be written to the log.")
        return 2
    assert isinstance(sender, SmtpEmailSender | ResendEmailSender)
    message = EmailMessage(
        to=address,
        subject="LEKA — e-mail de test",
        body=(
            "Si vous lisez ce message, LEKA sait envoyer des e-mails depuis ce serveur.\n\n"
            f"Expéditeur : {settings.email_from}\n"
        ),
    )
    try:
        await sender.deliver(message)
    except Exception as error:
        # In the clear, unlike a normal send: this is the tool for finding out why.
        _say(f"FAILED: {type(error).__name__}: {error}")
        return 1
    _say(f"Sent to {address}. Check the inbox, and the spam folder.")
    return 0


def main() -> None:  # pragma: no cover - a command-line tool
    parser = argparse.ArgumentParser(
        description="Send a test email with the configured sender, errors in the open."
    )
    parser.add_argument("--test", metavar="ADDRESS", required=True)
    sys.exit(asyncio.run(_diagnose(parser.parse_args().test)))


if __name__ == "__main__":  # pragma: no cover
    main()
