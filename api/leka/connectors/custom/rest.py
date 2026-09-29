"""The generic REST connector — a system LEKA has no connector for, read as
its admin declared it (LEKA-350).

No code of its own: an address, a way to authenticate, and a definition
(leka/connectors/custom/definition.py) — which resources to read, how their
pages follow each other, what each field means. Everything else is the
framework's, as for any connector: the secret encrypted at rest and never
shown again, the connection test, the health checks, the sync, the scope
rules — by resource — the retention, the history. What it shares with the
GraphQL connector is leka/connectors/custom/common.py.

READS ONLY: GET, and nothing else — a generic connector has no read that is
a POST to declare. To the configured host only: `base_url` is public and
https, checked when saved and when connecting (leka/connectors/network.py),
a resource's path is relative to it, and a next page on another host is
refused.

BOUNDED: at most 2 000 pages a resource and 50 000 records a pass. Beyond,
the pass fails and says so — a listing read whole and cut would mark the
rest gone — as a database's does past 20 000 tables. A page already read
ends the listing: a cursor given again, a link back.

Each record is stored with what the mapping read in it, beside the record
itself: `{"resource", "entity", "fields", "record"}` — `entity` when the
resource declares one. Extraction reads the fields
(leka/ingestion/extraction/custom.py); a mapping changed changes them, and
so what is extracted.

Every pass reads everything: an API's own "changed since" is too various to
trust from a declaration, and the sync writes only what changed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from leka.connectors.base import Capability, ConnectorCategory, ConnectorManifest
from leka.connectors.custom import common
from leka.connectors.custom.common import (
    AUTH_HELP,
    AUTH_NAME_HELP,
    Auth,
    CustomCredentials,
    DeclaredConnector,
    named_where_needed,
    no_credential_in,
    path_of,
    records_at,
    text,
    too_many,
)
from leka.connectors.custom.definition import DEFINITION_MAX, Resource, at, parse
from leka.connectors.http import Params, VendorHttp, on_the_host
from leka.connectors.models import SourceKind
from leka.connectors.network import PublicHttpsUrl
from leka.connectors.registry import register_connector

C = Capability


class CustomRestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: PublicHttpsUrl = Field(
        description="The API's address, https and public: https://api.acme.com/v2. "
        "Each resource's path is read from it."
    )
    auth: Auth = Field(default="bearer", description=AUTH_HELP)
    auth_name: str | None = Field(default=None, max_length=64, description=AUTH_NAME_HELP)
    definition: str = Field(
        min_length=2,
        max_length=DEFINITION_MAX,
        description="What to read and what it means — resources, pagination, mapping — as JSON.",
        json_schema_extra={"format": "json"},
    )

    @field_validator("definition")
    @classmethod
    def _readable(cls, value: str) -> str:
        parse(value)
        return value

    @field_validator("base_url")
    @classmethod
    def _no_secret(cls, value: Any) -> Any:
        no_credential_in(value)
        return value

    @model_validator(mode="after")
    def _named_where_needed(self) -> Self:
        named_where_needed(self.auth, self.auth_name)
        return self


@register_connector
class CustomRestConnector(DeclaredConnector[CustomRestConfig, Resource]):
    manifest = ConnectorManifest(
        key=SourceKind.CUSTOM_REST,
        display_name="API REST",
        category=ConnectorCategory.CUSTOM,
        auth_type="token",
        config_schema=CustomRestConfig,
        credentials_schema=CustomCredentials,
        capabilities=frozenset({C.RECORDS}),
        # Read whole each pass (the module's docstring).
        listed_whole=frozenset({C.RECORDS}),
    )

    def __init__(
        self,
        config: CustomRestConfig,
        credentials: CustomCredentials,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(config, credentials, transport=transport)
        self.resources = parse(config.definition).resources

    def _client(self) -> VendorHttp:
        client = self.http(str(self.config.base_url), self._headers())
        return VendorHttp(client, secret=self._secret(), refuse=self._refuse, page_size=0)

    def _describe(self, resource: Resource) -> str:
        return resource.path

    def _account(self) -> str:
        return str(self.config.base_url.host)

    async def _get(
        self, client: VendorHttp, url: str, params: Params
    ) -> tuple[httpx.Response, Any]:
        """One page, as JSON — with the secret as a parameter when that is
        the way chosen."""
        response = await client.get(url, params={**params, **self._query_secret()})
        return response, self._json(response, "GET", path_of(url))

    async def _first_page(self, client: VendorHttp, resource: Resource) -> list[dict[str, Any]]:
        _response, body = await self._get(client, resource.path, self._params(resource))
        return records_at(resource, body)

    def _params(self, resource: Resource, **more: str | int) -> Params:
        pagination = resource.pagination
        params: dict[str, str | int | list[str]] = dict(resource.params)
        if pagination.size_param:
            params[pagination.size_param] = pagination.size
        if pagination.type in ("page", "offset") and pagination.param:
            params[pagination.param] = pagination.first
        return {**params, **more}

    async def _items(self, client: VendorHttp, resource: Resource) -> AsyncIterator[dict[str, Any]]:
        """Every record of a resource, page after page, as its pagination says."""
        pagination = resource.pagination
        url: str | None = resource.path
        params = self._params(resource)
        position = pagination.first
        cursor: object = None
        pages = 0
        asked: set[str] = set()
        while url is not None:
            asked.add(self._where(url, params))
            response, body = await self._get(client, url, params)
            page = records_at(resource, body)
            for item in page:
                yield item
            pages += 1
            url, following = None, None
            if pagination.type == "link":
                following = response.links.get("next", {}).get("url")
            elif pagination.type == "next_url" and pagination.next:
                following = text(at(body, pagination.next))
            elif pagination.type == "cursor" and pagination.next and pagination.param:
                token = at(body, pagination.next)
                # An empty token ends the listing; the same one again would
                # loop on the same page.
                if text(token) and token != cursor:
                    cursor = token
                    url, params = (
                        resource.path,
                        self._params(resource, **{pagination.param: str(token)}),
                    )
            elif pagination.type in ("page", "offset") and pagination.param:
                full = len(page) >= pagination.size if pagination.size_param else bool(page)
                if page and full:
                    position += 1 if pagination.type == "page" else len(page)
                    url, params = (
                        resource.path,
                        self._params(resource, **{pagination.param: position}),
                    )
            if following:
                base = httpx.URL(str(self.config.base_url))
                url, params = _split(on_the_host(base, following, self._secret()))
                if self._where(url, params) in asked:
                    # A link back to a page already read ends the listing,
                    # as a cursor given again does.
                    url = None
            if url is not None:
                if pages >= common.MAX_PAGES:
                    raise too_many(f"plus de {common.MAX_PAGES} pages pour « {resource.name} »")
                client.spare_the_quota(response)

    def _where(self, url: str, params: Params) -> str:
        """A page's full address and query, the same whether it was a path
        from the base — as httpx joins them — or a link, however its query
        was given."""
        full = url if "://" in url else str(self.config.base_url).rstrip("/") + url
        return str(httpx.URL(full).copy_merge_params(dict(params)))


def _split(url: str) -> tuple[str, Params]:
    """A next page's URL as its address and its query — the query handed
    back as parameters, so that it is kept, and a secret sent as one joins
    it. A parameter given twice stays a list."""
    link = httpx.URL(url)
    params: dict[str, str | int | list[str]] = {}
    for key in link.params:
        values = link.params.get_list(key)
        params[key] = values if len(values) > 1 else values[0]
    return str(link.copy_with(query=None)), params
