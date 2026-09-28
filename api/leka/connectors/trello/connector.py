"""The Trello connector — trello.com, through its REST API (1).

Trello is read at https://api.trello.com/1 with an API key and a token
the key's owner authorised, sent in the Authorization header and never in
a URL — httpx writes every URL it calls to the logs. A token can be
authorised for reading only (`scope=read`), and the documentation asks for
one. Trello tells what a token may do only at a URL holding the token, so
the test does not ask. Every call is a GET.

test_connection: who am I (GET /members/me), which boards (GET
/members/me/boards), is every board in scope among them, and can I read
the cards of one board.

check_health: GET /members/me, reading Trello's
x-rate-limit-api-token-* headers. Degraded under a tenth left.

list_scope: every board the token's member belongs to, closed ones too.

iter_resources: boards — with their lists, labels, members and workspace
— whole each pass; then cards, board by board, archived ones included,
newest first across pages of 500 (`before` the last one read). Trello
cannot filter cards by their last activity, so an incremental pass reads
every card and keeps those active since the last pass.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from leka.connectors.base import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    HealthResult,
    ScopeListing,
    ScopeOption,
)
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.http import (
    Item,
    VendorHttp,
    parse_timestamp,
    record,
    refusal,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

API = "https://api.trello.com/1"
PAGE_SIZE = 500  # cards per page; Trello allows 1 000
MAX_SCOPE_OPTIONS = 1000
LOW_QUOTA_RATIO = 0.1
# Trello's window is ten seconds, and it says no more than that.
RATE_WINDOW_SECONDS = 10
# A card's last activity is written by Trello a moment after the change.
ACTIVITY_MARGIN = timedelta(minutes=2)
BOARD_ID = re.compile(r"^[0-9a-f]{24}$")
SHORT_LINK = re.compile(r"^[A-Za-z0-9]{8}$")
BOARD_LINK = re.compile(r"trello\.com/b/([A-Za-z0-9]{8})")

BOARD_FIELDS = "name,desc,closed,url,shortUrl,shortLink,dateLastActivity,idOrganization"
BOARD_EXTRAS = {
    "lists": "all",
    "list_fields": "name,closed,pos",
    "labels": "all",
    "label_fields": "name,color",
    "members": "all",
    "member_fields": "fullName,username",
    "organization": "true",
    "organization_fields": "displayName,name",
}
CARD_FIELDS = (
    "name,desc,closed,idBoard,idList,idMembers,labels,due,dueComplete,start,"
    "dateLastActivity,idShort,shortUrl,url"
)


def board_key(value: str) -> str:
    """A board's id or short link, from what an admin typed or pasted —
    "5f1e…" (24 hex digits), "AbCd1234", or https://trello.com/b/AbCd1234/…
    Anything else is refused."""
    text = value.strip()
    found = BOARD_LINK.search(text)
    if found:
        return found.group(1)
    if BOARD_ID.match(text.lower()):
        return text.lower()
    if SHORT_LINK.match(text):
        return text
    msg = f"{value!r} is not the id or the link of a Trello board"
    raise ValueError(msg)


class TrelloConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boards: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Ids or links of the boards to read. Empty: every board of the token's member.",
    )

    @field_validator("boards")
    @classmethod
    def _keys(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(board_key(board) for board in value))


class TrelloCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First, so the stored hint is the token's.
    token: SecretStr = Field(
        min_length=32,
        description="A token authorised for reading (ATTA…), by the key's owner.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    api_key: SecretStr = Field(
        min_length=32,
        max_length=64,
        description="The API key of a Power-Up, from trello.com/power-ups/admin.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class TrelloConnector(Connector[TrelloConfig, TrelloCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.TRELLO,
        display_name="Trello",
        category=ConnectorCategory.PROJECT,
        auth_type="token",
        config_schema=TrelloConfig,
        credentials_schema=TrelloCredentials,
        capabilities=frozenset({Capability.PROJECTS, Capability.ISSUES}),
        # Boards come whole every pass; cards are kept by their last activity.
        listed_whole=frozenset({Capability.PROJECTS}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            me = (
                await client.get("/members/me", params={"fields": "username,fullName,email"})
            ).json()
            boards = await self._boards(client, "all", "name,closed")
            self._require_scope(boards)
            chosen = [board for board in self._in_scope(boards) if not board.get("closed")]
            warnings: list[str] = []
            capabilities: list[Capability] = []
            if chosen:
                sample = str(chosen[0]["id"])
                capabilities = await client.probe(
                    {
                        Capability.PROJECTS: f"/boards/{sample}?fields=name",
                        Capability.ISSUES: f"/boards/{sample}/cards/all?limit=1&fields=name",
                    }
                )
            else:
                warnings.append("Aucun tableau ouvert n'est visible avec ce token.")

        return ConnectionTestResult(
            account=str(me.get("email") or me.get("username") or "Trello"),
            metadata={
                "member": me.get("fullName"),
                "boards_visible": sum(1 for board in boards if not board.get("closed")),
            },
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            response = await client.get("/members/me", params={"fields": "username"})
        limit = int(response.headers.get("x-rate-limit-api-token-max", 0))
        remaining = int(response.headers.get("x-rate-limit-api-token-remaining", limit))
        low = limit > 0 and remaining < limit * LOW_QUOTA_RATIO
        return HealthResult(
            status=HealthStatus.DEGRADED if low else HealthStatus.HEALTHY,
            detail=f"quota {remaining}/{limit}" if limit else None,
            checked_at=datetime.now(UTC),
        )

    async def list_scope(self) -> ScopeListing:
        async with self._client() as client:
            boards = await self._boards(client, "all", "name,desc,closed,dateLastActivity")
        options = [
            ScopeOption(
                key=str(board["id"]),
                name=str(board.get("name") or board["id"]),
                description=_description(board),
                updated_at=parse_timestamp(board.get("dateLastActivity")),
            )
            for board in boards[:MAX_SCOPE_OPTIONS]
        ]
        return ScopeListing(options=options, truncated=len(boards) > MAX_SCOPE_OPTIONS)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Trello does not read {capability}"
            raise ValueError(msg)
        async with self._client() as client:
            boards = self._in_scope(await self._boards(client, "all", "name"))
            if capability is Capability.PROJECTS:
                for board in boards:
                    params = {"fields": BOARD_FIELDS, **BOARD_EXTRAS}
                    response = await client.get(f"/boards/{board['id']}", params=params, empty=404)
                    if response.status_code == 404:
                        continue  # gone since the listing: swept
                    found = response.json()
                    yield record(
                        capability,
                        found,
                        external_id=str(found["id"]),
                        container=found.get("idOrganization"),
                        updated=found.get("dateLastActivity"),
                    )
                return
            wanted = since - ACTIVITY_MARGIN if since else None
            for board in boards:
                async for card in self._cards(client, str(board["id"])):
                    active = parse_timestamp(card.get("dateLastActivity"))
                    if wanted and active is not None and active < wanted:
                        continue
                    yield record(
                        capability,
                        card,
                        external_id=str(card["id"]),
                        container=str(board["id"]),
                        updated=card.get("dateLastActivity"),
                    )

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        token = self.credentials.token.get_secret_value()
        key = self.credentials.api_key.get_secret_value()
        client = self.http(
            API,
            headers={
                "Accept": "application/json",
                "User-Agent": "LEKA",
                # In the header: neither shows in a URL, which gets logged.
                "Authorization": f'OAuth oauth_consumer_key="{key}", oauth_token="{token}"',
            },
        )
        return VendorHttp(client, secret=token, refuse=self._refuse, page_size=PAGE_SIZE)

    async def _boards(self, client: VendorHttp, which: str, fields: str) -> list[Item]:
        """The boards of the token's member. One call: Trello allows only a
        hundred on /members/ every fifteen minutes."""
        fields = ",".join(dict.fromkeys(["shortLink", *fields.split(",")]))
        response = await client.get(
            "/members/me/boards", params={"filter": which, "fields": fields}
        )
        found = response.json()
        return found if isinstance(found, list) else []

    def _in_scope(self, boards: list[Item]) -> list[Item]:
        if not self.config.boards:
            return boards
        wanted = set(self.config.boards)
        return [b for b in boards if b.get("id") in wanted or b.get("shortLink") in wanted]

    def _require_scope(self, boards: list[Item]) -> None:
        """Every board in scope must be one of the member's boards."""
        known = {str(b.get(field)) for b in boards for field in ("id", "shortLink")}
        missing = [key for key in self.config.boards or [] if key not in known]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"Trello ne montre pas ces tableaux à ce token : {named}.",
            )

    async def _cards(self, client: VendorHttp, board: str) -> AsyncIterator[Item]:
        """Every card of a board, archived ones too. Trello gives the newest
        first; the next page is the cards created before the last one read."""
        before: str | None = None
        seen: set[str] = set()
        while True:
            params: dict[str, str | int] = {"fields": CARD_FIELDS, "limit": PAGE_SIZE}
            if before:
                params["before"] = before
            response = await client.get(f"/boards/{board}/cards/all", params=params, empty=404)
            if response.status_code == 404:
                return  # the board left between the listing and now
            page = response.json()
            if not isinstance(page, list):
                return
            fresh = [card for card in page if card["id"] not in seen]
            for card in fresh:
                seen.add(str(card["id"]))
                yield card
            if len(page) < PAGE_SIZE:
                return
            if not fresh:
                # A page of cards already read: following it would never end.
                raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail="Trello repeated a page")
            before = min(str(card["id"]) for card in page)  # ids grow with creation

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Trello's refusals, as diagnostics. It answers in plain text:
        "invalid token", "unauthorized permission requested"."""
        secret = self.credentials.token.get_secret_value()
        status, text = response.status_code, response.text.lower()
        if status == 429:
            return refusal(
                response,
                path,
                secret,
                DiagnosticCode.RATE_LIMITED,
                retry_after=_window(response),
            )
        if status == 401 and "permission" in text:
            message = "Trello refuse cette lecture à ce token."
            return refusal(
                response, path, secret, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        if status in (400, 401) and ("invalid key" in text or "invalid token" in text):
            message = "Trello refuse cette clé d'API ou ce token."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 404:
            what = missing or "ce tableau"
            message = f"Trello ne trouve pas {what}, ou ce token ne le voit pas."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        return refusal(response, path, secret, usual_code(status))


def _window(response: httpx.Response) -> int:
    """Seconds until Trello's window turns over: it says how long the
    window is, not when it ends."""
    interval = response.headers.get("x-rate-limit-api-token-interval-ms")
    return max(1, int(interval) // 1000) if interval and interval.isdigit() else RATE_WINDOW_SECONDS


def _description(board: Any) -> str | None:
    text = str(board.get("desc") or "").strip() or None
    if board.get("closed"):
        return f"Fermé · {text}" if text else "Fermé"
    return text
