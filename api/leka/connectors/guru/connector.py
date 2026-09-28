"""The Guru connector — getguru.com, through its REST API (v1).

Guru is read at https://api.getguru.com/api/v1 with HTTP Basic: a
username and a token. Two kinds of token fit:

- a collection token — read-only by Guru's own design, one collection;
  its username is the collection's id. The narrowest, and the one the
  documentation recommends;
- a user token — the user's email as username; it can do what the user
  can, so the documentation asks for a dedicated read-only user.

Every call is a GET.

test_connection: who am I (GET /whoami), which collections (GET
/collections), is every collection in scope among them, and can I search
the cards.

check_health: GET /whoami. Guru sends no quota headers.

list_scope: every collection the token sees.

iter_resources: collections, whole each pass; cards through GET
/search/query, most recently modified first, 50 a page by Guru's Link
header (rel="next-page"). An incremental pass stops at the first card
modified before the last pass. With `collections`, a card is read when its
collection is in scope.
"""

from __future__ import annotations

import base64
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
    dig,
    record,
    refusal,
    retry_after,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

API = "https://api.getguru.com/api/v1"
PAGE_SIZE = 50  # Guru's maximum
MAX_SCOPE_OPTIONS = 1000
# A card's lastModified is written a moment after the change.
UPDATE_MARGIN = timedelta(minutes=2)
COLLECTION_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
CARDS = "/search/query"
CARD_ORDER = {"sortField": "lastModified", "sortOrder": "desc", "showArchived": "false"}


class GuruConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collections: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Ids of the collections to read. Empty: every collection the token sees.",
    )

    @field_validator("collections")
    @classmethod
    def _ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        ids = [collection.strip().lower() for collection in value]
        for collection in ids:
            if not COLLECTION_ID.match(collection):
                msg = f"{collection!r} is not the id of a Guru collection"
                raise ValueError(msg)
        return list(dict.fromkeys(ids))


class GuruCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First, so the stored hint is the token's.
    token: SecretStr = Field(
        min_length=20,
        description="A collection token (read-only), or a dedicated user's token.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    username: str = Field(
        min_length=3,
        max_length=254,
        description="The collection's id for a collection token; the user's email for a "
        "user token.",
    )


@register_connector
class GuruConnector(Connector[GuruConfig, GuruCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.GURU,
        display_name="Guru",
        category=ConnectorCategory.DOCS,
        auth_type="token",
        config_schema=GuruConfig,
        credentials_schema=GuruCredentials,
        capabilities=frozenset({Capability.SPACES, Capability.PAGES}),
        # Collections come whole every pass; cards by their last change.
        listed_whole=frozenset({Capability.SPACES}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            me = (await client.get("/whoami")).json()
            collections = await self._collections(client)
            self._require_scope(collections)
            capabilities = [Capability.SPACES] if collections else []
            try:
                await client.get(CARDS, params={**CARD_ORDER, "maxResults": 1})
                capabilities.append(Capability.PAGES)
            except ConnectorError:
                pass  # a capability left out, not a failed test
        warnings: list[str] = []
        if not collections:
            warnings.append("Aucune collection n'est visible avec ce token.")
        return ConnectionTestResult(
            account=_account(me) or self.credentials.username,
            metadata={
                "team": dig(me, "team.name") or dig(me, "user.team.name"),
                "collections_visible": len(collections),
            },
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            await client.get("/whoami")
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        async with self._client() as client:
            collections = await self._collections(client)
        options = [
            ScopeOption(
                key=str(collection["id"]),
                name=str(collection.get("name") or collection["id"]),
                description=str(collection.get("description") or "").strip() or None,
            )
            for collection in collections[:MAX_SCOPE_OPTIONS]
        ]
        return ScopeListing(options=options, truncated=len(collections) > MAX_SCOPE_OPTIONS)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Guru does not read {capability}"
            raise ValueError(msg)
        wanted = set(self.config.collections or [])
        async with self._client() as client:
            if capability is Capability.SPACES:
                for collection in await self._collections(client):
                    if wanted and str(collection["id"]).lower() not in wanted:
                        continue
                    yield record(
                        capability,
                        collection,
                        external_id=str(collection["id"]),
                        updated=collection.get("lastModified"),
                    )
                return
            cards = client.pages(
                CARDS,
                CARD_ORDER,
                stop_before=since - UPDATE_MARGIN if since else None,
                updated_field="lastModified",
            )
            async for card in cards:
                where = str(dig(card, "collection.id") or "")
                if wanted and where.lower() not in wanted:
                    continue
                yield record(
                    capability,
                    card,
                    external_id=str(card["id"]),
                    container=where or None,
                    updated=card.get("lastModified"),
                )

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.token.get_secret_value()
        pair = f"{self.credentials.username}:{secret}".encode()
        client = self.http(
            API,
            headers={
                "Accept": "application/json",
                "User-Agent": "LEKA",
                "Authorization": f"Basic {base64.b64encode(pair).decode()}",
            },
        )
        return VendorHttp(
            client,
            secret=secret,
            refuse=self._refuse,
            page_size=PAGE_SIZE,
            page_size_param="maxResults",
            next_rel="next-page",
        )

    async def _collections(self, client: VendorHttp) -> list[Item]:
        found = (await client.get("/collections")).json()
        return found if isinstance(found, list) else []

    def _require_scope(self, collections: list[Item]) -> None:
        """Every collection in scope must be one this token can see."""
        known = {str(collection["id"]).lower() for collection in collections}
        missing = [c for c in self.config.collections or [] if c not in known]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"Guru ne montre pas ces collections à ce token : {named}.",
            )

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        secret = self.credentials.token.get_secret_value()
        status = response.status_code
        if status == 429:
            return refusal(
                response,
                path,
                secret,
                DiagnosticCode.RATE_LIMITED,
                retry_after=retry_after(response),
            )
        if status == 401:
            message = "Guru refuse cet identifiant ou ce token."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 404:
            what = missing or "cette collection"
            message = f"Guru ne trouve pas {what}, ou ce token ne la voit pas."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        return refusal(response, path, secret, usual_code(status))


def _account(me: Any) -> str | None:
    """Who the token is: a user's email, or a collection's name."""
    for path in ("email", "user.email", "username", "collection.name", "name"):
        found = dig(me, path)
        if isinstance(found, str) and found:
            return found
    return None
