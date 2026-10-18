"""The Confluence connector — Confluence Cloud (<site>.atlassian.net/wiki), REST API v2.

test_connection: who am I (GET /rest/api/user/current — v2 has no such
call), are the spaces in scope there (GET /api/v2/spaces?keys=…), what can
I see (one page of spaces), and — in one space, in scope if a scope is set
— can I read its pages.

check_health: GET /api/v2/spaces?limit=1. Healthy, or degraded when
Atlassian says the quota is nearly spent (X-RateLimit-NearLimit).

list_scope: every space the account can see, for the admin to choose from.

iter_resources: the spaces in scope — every space the account can see,
unless `spaces` names some — then, space by space, their current pages with
their body in Confluence's storage format, most recently changed first. An
incremental pass stops at the first page changed before the last one: the
listing is sorted by Confluence, by the date of each page's latest version.
Pages the account may not view — restricted pages included — are not in
Confluence's answers, so they are not in LEKA's.

Confluence Data Center is another API, not this one.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from leka.connectors import atlassian
from leka.connectors.atlassian import AtlassianCredentials
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
from leka.connectors.errors import DiagnosticCode, diagnose
from leka.connectors.http import Item, VendorHttp, dig, record, records
from leka.connectors.models import SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

WIKI = "/wiki"
PAGE_SIZE = 50  # pages come with their body: fifty is plenty per answer
KEYS_PER_CALL = 50
MAX_SCOPE_OPTIONS = 1000
# A space key: letters, digits and "_"; a personal space's starts with "~".
KEY = re.compile(r"^~?[A-Za-z0-9_]{1,255}$")


class ConfluenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str = Field(
        max_length=255,
        description="The Atlassian site: 'acme', as in acme.atlassian.net.",
    )
    spaces: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Keys of the spaces to read ('ENG'). Empty: every space the account can see.",
    )
    pages: bool = Field(
        default=False,
        description="Allow LEKA to publish the pages a person accepted — new pages in the "
        "spaces this source reads, never an edit. The account then needs Add pages there.",
    )

    @field_validator("site")
    @classmethod
    def _site_is_a_name(cls, value: str) -> str:
        return atlassian.site_name(value)

    @field_validator("spaces")
    @classmethod
    def _keys_are_keys(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        keys = [key.strip() for key in value]
        for key in keys:
            if not KEY.match(key):
                msg = f"{key!r} is not a space key like 'ENG'"
                raise ValueError(msg)
        return list(dict.fromkeys(keys))


class ConfluenceCredentials(AtlassianCredentials):
    """An Atlassian account's API token, and the email it belongs to."""


@register_connector
class ConfluenceConnector(Connector[ConfluenceConfig, ConfluenceCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.CONFLUENCE,
        display_name="Confluence",
        category=ConnectorCategory.DOCS,
        auth_type="token",
        config_schema=ConfluenceConfig,
        credentials_schema=ConfluenceCredentials,
        capabilities=frozenset({Capability.SPACES, Capability.PAGES}),
        # Spaces come whole every pass; pages stop at the last pass.
        listed_whole=frozenset({Capability.SPACES}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            me = (await client.get("/rest/api/user/current", missing="ce site Atlassian")).json()
            if me.get("type") == "anonymous":
                raise diagnose(
                    DiagnosticCode.AUTH_INVALID,
                    message="Confluence refuse cette adresse e-mail ou ce token.",
                )
            metadata: dict[str, object] = {"site": f"{self.config.site}{atlassian.SUFFIX}"}
            if self.config.spaces:
                await self._require_scope(client)

            query: dict[str, str | int | list[str]] = {"limit": PAGE_SIZE}
            if self.config.spaces:
                query["keys"] = ",".join(self.config.spaces[:KEYS_PER_CALL])
            first = (await client.get("/api/v2/spaces", params=query)).json()
            listed = first.get("results", [])
            more = bool(dig(first, "_links.next"))
            metadata["spaces_visible"] = f"{len(listed)}+" if more else len(listed)
            capabilities = [Capability.SPACES] if listed else []
            warnings: list[str] = []
            if listed:
                # Probe what will be read: a space in scope, if one is set.
                capabilities += await client.probe(
                    {Capability.PAGES: f"/api/v2/spaces/{listed[0]['id']}/pages"},
                    params={"limit": 1},
                )
            else:
                warnings.append("Aucun espace n'est visible avec ce compte.")

        return ConnectionTestResult(
            account=str(me.get("displayName") or me.get("email") or self.credentials.email),
            metadata=metadata,
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            response = await client.get("/api/v2/spaces", params={"limit": 1})
        return atlassian.health(response)

    async def list_scope(self) -> ScopeListing:
        options: list[ScopeOption] = []
        async with self._client() as client:
            async for space in client.pages("/api/v2/spaces", {"description-format": "plain"}):
                if len(options) == MAX_SCOPE_OPTIONS:
                    return ScopeListing(options=options, truncated=True)
                description = dig(space, "description.plain.value")
                options.append(
                    ScopeOption(
                        key=str(space["key"]),
                        name=str(space["name"]),
                        description=str(description) if description else None,
                    )
                )
        return ScopeListing(options=options)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Confluence does not read {capability}"
            raise ValueError(msg)
        async with self._client() as client:
            async for space in self._spaces(client):
                if capability is Capability.SPACES:
                    yield record(capability, self._linked(space), external_id=str(space["id"]))
                    continue
                pages = client.pages(
                    f"/api/v2/spaces/{space['id']}/pages",
                    {"body-format": "storage", "sort": "-modified-date", "status": "current"},
                    stop_before=since,
                    updated_field="version.createdAt",
                )
                async for page in records(
                    capability,
                    self._each_linked(pages),
                    str(space["key"]),
                    key=lambda page: str(page["id"]),
                    updated=lambda page: dig(page, "version.createdAt"),
                ):
                    yield page

    # ── inside ───────────────────────────────────────────────────────────────

    def _linked(self, item: Item) -> Item:
        """The item, with the link to open it: Confluence gives a path only."""
        path = dig(item, "_links.webui")
        if not path:
            return item
        return {**item, "web_url": f"{atlassian.site_url(self.config.site)}{WIKI}{path}"}

    async def _each_linked(self, items: AsyncIterator[Item]) -> AsyncIterator[Item]:
        async for item in items:
            yield self._linked(item)

    def _client(self) -> VendorHttp:
        client = self.http(
            atlassian.site_url(self.config.site) + WIKI,
            headers=atlassian.headers(self.credentials),
        )
        return VendorHttp(
            client,
            secret=self.credentials.token.get_secret_value(),
            refuse=atlassian.refuser("Confluence", self.credentials),
            page_size=PAGE_SIZE,
            page_size_param="limit",
            in_body=("results", "_links.next"),
        )

    async def _require_scope(self, client: VendorHttp) -> None:
        """Every space in scope must be one this account can see."""
        found = {str(space["key"]) async for space in self._spaces(client)}
        missing = [key for key in self.config.spaces or [] if key not in found]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"Confluence ne montre pas ces espaces à ce compte : {named}.",
            )

    async def _spaces(self, client: VendorHttp) -> AsyncIterator[Item]:
        """The spaces in scope, as Confluence describes them."""
        described = {"description-format": "plain"}
        wanted = self.config.spaces
        if not wanted:
            async for space in client.pages("/api/v2/spaces", described):
                yield space
            return
        for start in range(0, len(wanted), KEYS_PER_CALL):
            keys = ",".join(wanted[start : start + KEYS_PER_CALL])
            async for space in client.pages("/api/v2/spaces", {**described, "keys": keys}):
                yield space
