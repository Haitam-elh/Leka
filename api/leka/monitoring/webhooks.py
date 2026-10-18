"""The channels a person connects by a webhook (LEKA-496): Slack, Microsoft
Teams, Discord — the URL their tool gives, nothing else.

    connect     its URL checked — https, its tool's own host, a webhook's
                path —, kept encrypted (SecretBox), shown by its hint only;
                untested until a message went
    disconnect  forgotten
    post        a message to it: through the public-only transport (never a
                private address), at most ATTEMPTS tries on a timeout, a 429
                or a 5xx, never on a refusal — its status said
                (operational, failing) and its last error kept

SMS and WhatsApp need a provider's account and number: not here — said
« non disponible », never simulated.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.connectors import PublicTransport
from leka.monitoring.models import WEBHOOK_CHANNELS, ChannelEndpoint
from leka.platform import secret_box

logger = structlog.get_logger(__name__)

ATTEMPTS = 3
TIMEOUT = 10.0
# Each tool's own webhook hosts and paths: a URL anywhere else is refused.
HOSTS: dict[str, tuple[tuple[str, str], ...]] = {
    "slack": (("hooks.slack.com", "/services/"),),
    "discord": (("discord.com", "/api/webhooks/"), ("discordapp.com", "/api/webhooks/")),
    # Teams: a connector's webhook, or a Workflows (Power Automate) one.
    "teams": ((".webhook.office.com", "/"), (".logic.azure.com", "/"), (".powerplatform.com", "/")),
}

# How each tool takes a message.
PAYLOAD: dict[str, Callable[[str], dict[str, str]]] = {
    "slack": lambda text: {"text": text},
    "teams": lambda text: {"text": text},
    "discord": lambda text: {"content": text[:2000]},
}


class WebhookRefusedError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Sent:
    ok: bool
    error: str | None


def checked(channel: str, url: str) -> httpx.URL:
    """Its URL, when it is its tool's webhook — WebhookRefusedError otherwise."""
    if channel not in WEBHOOK_CHANNELS:
        raise WebhookRefusedError("unknown_channel", "No such channel.")
    try:
        parsed = httpx.URL(url.strip())
    except httpx.InvalidURL:
        raise WebhookRefusedError("invalid_url", "Not a URL.") from None
    host = parsed.host.lower()
    fits = parsed.scheme == "https" and any(
        (host == domain or (domain.startswith(".") and host.endswith(domain)))
        and parsed.path.startswith(path)
        and len(parsed.path) > len(path)
        for domain, path in HOSTS[channel]
    )
    if not fits:
        raise WebhookRefusedError("invalid_url", f"Not a {channel} webhook URL.")
    return parsed


def hint_of(url: httpx.URL) -> str:
    """Enough to recognise it: its host and the last four characters."""
    return f"{url.host}/…{str(url)[-4:]}"


async def endpoints(session: AsyncSession, workspace_id: uuid.UUID) -> dict[str, ChannelEndpoint]:
    rows = await session.scalars(
        select(ChannelEndpoint).where(ChannelEndpoint.workspace_id == workspace_id)
    )
    return {row.channel: row for row in rows}


async def connect(
    session: AsyncSession, workspace_id: uuid.UUID, channel: str, url: str, *, by: uuid.UUID
) -> ChannelEndpoint:
    parsed = checked(channel, url)
    row = (await endpoints(session, workspace_id)).get(channel)
    if row is None:
        row = ChannelEndpoint(workspace_id=workspace_id, channel=channel, created_by=by)
        session.add(row)
    row.webhook_ciphertext = secret_box.encrypt(str(parsed))
    row.hint = hint_of(parsed)
    row.status = "untested"
    row.last_error = None
    row.tested_at = None
    await session.flush()
    return row


async def disconnect(session: AsyncSession, workspace_id: uuid.UUID, channel: str) -> bool:
    row = (await endpoints(session, workspace_id)).get(channel)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


def _transport() -> httpx.AsyncBaseTransport:
    return PublicTransport()


async def _pause(attempt: int) -> None:
    await asyncio.sleep(0.5 * attempt)


async def post(row: ChannelEndpoint, text: str, *, now: datetime) -> Sent:
    """The message sent to it; its status and last error kept on it."""
    url = secret_box.decrypt(row.webhook_ciphertext)
    error: str | None = None
    async with httpx.AsyncClient(transport=_transport(), timeout=TIMEOUT) as client:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                answer = await client.post(url, json=PAYLOAD[row.channel](text))
            except httpx.HTTPError as caught:
                error = type(caught).__name__
            else:
                if answer.is_success:
                    error = None
                    break
                error = f"HTTP {answer.status_code}"
                # A refusal is final: its URL or its rights, said, not retried.
                if answer.status_code != 429 and answer.status_code < 500:
                    break
            if attempt < ATTEMPTS:
                await _pause(attempt)
    row.status = "failing" if error else "operational"
    row.last_error = error
    row.tested_at = now
    if error:
        logger.warning("alert_webhook_failed", channel=row.channel, error=error)
    return Sent(ok=error is None, error=error)
