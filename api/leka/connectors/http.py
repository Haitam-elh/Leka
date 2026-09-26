"""What every HTTP connector does the same way.

GitHub, GitLab and Bitbucket differ in what their answers mean, not in how
they are asked. One GET whose failures become diagnostics, pagination by
the Link header that never follows a link to another host, probes in
parallel, timestamps, and records: written once here, so a fix to any of
them is a fix to all.

What stays in each connector is what the vendor means: which 403 is a
quota and which a scope (`refuse`), and how its listings are shaped.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

import httpx

from leka.connectors.base import Capability
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.schemas import RawRecord

type Item = dict[str, object]
type Params = Mapping[str, str | int]
# What a vendor makes of a failed answer: (response, path, what was missing).
type Refuse = Callable[[httpx.Response, str, str], ConnectorError]


class VendorHttp:
    """A connector's HTTP client for one call, holding the secret only to
    scrub it from what goes wrong. Used as `async with`."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        secret: str,
        refuse: Refuse,
        page_size: int,
        page_size_param: str = "per_page",
        in_body: tuple[str, str] | None = None,
    ) -> None:
        """`in_body`: for vendors that page in the body rather than the Link
        header — the fields holding the items and the next page's URL,
        ("values", "next") for Bitbucket."""
        self._client = client
        self._secret = secret
        self._refuse = refuse
        self._page = {page_size_param: page_size}
        self._in_body = in_body

    async def __aenter__(self) -> Self:
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(kind, error, traceback)

    async def get(
        self,
        path: str,
        *,
        params: Params | None = None,
        missing: str = "",
        empty: int | None = None,
    ) -> httpx.Response:
        """A successful answer, or `empty` — a status that means "nothing
        here" — or a ConnectorError with its diagnostic."""
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException as error:
            raise diagnose(
                DiagnosticCode.TIMEOUT, detail=f"GET {path}", secrets=[self._secret]
            ) from error
        except httpx.TransportError as error:
            raise diagnose(
                DiagnosticCode.NETWORK_UNREACHABLE,
                detail=f"GET {path}: {type(error).__name__}",
                secrets=[self._secret],
            ) from error
        if response.is_success or response.status_code == empty:
            return response
        raise self._refuse(response, path, missing)

    async def get_if_answered(self, path: str) -> httpx.Response | None:
        """For what a vendor may not answer at all: None rather than an error."""
        try:
            response = await self._client.get(path)
        except httpx.HTTPError:
            return None
        return response if response.is_success else None

    async def pages(
        self,
        path: str,
        params: Params | None = None,
        *,
        empty: int | None = None,
        stop_before: datetime | None = None,
        updated_field: str = "updated_at",
    ) -> AsyncIterator[Item]:
        """Every item of a listing, page after page.

        `stop_before`: the listing is sorted newest-updated first, and
        nothing updated before this is wanted.
        """
        url: str | None = path
        query: Params | None = {**self._page, **(params or {})}
        while url:
            response = await self.get(url, params=query, empty=empty)
            if response.status_code == empty:
                return
            body = response.json()
            for item in body[self._in_body[0]] if self._in_body else body:
                if stop_before:
                    updated = parse_timestamp(item.get(updated_field))
                    if updated is None or updated < stop_before:
                        return
                yield item
            url, query = self._next_page(response, body), None  # the link carries the query

    def _next_page(self, response: httpx.Response, body: Any) -> str | None:
        """The next page — only if it is on the host the secret was meant for."""
        if self._in_body:
            found = body.get(self._in_body[1])
        else:
            found = response.links.get("next", {}).get("url")
        if not found:
            return None
        link = str(found)
        host = httpx.URL(link).host
        if host != self._client.base_url.host:
            raise diagnose(
                DiagnosticCode.PROVIDER_ERROR,
                detail=f"pagination points to another host: {host}",
                secrets=[self._secret],
            )
        return link

    async def probe(
        self, paths: Mapping[Capability, str], params: Params | None = None
    ) -> list[Capability]:
        """Which of these capabilities can be read, asked at once. A probe
        that fails is a capability left out, never an error."""
        responses = await asyncio.gather(
            *(self._client.get(path, params=params) for path in paths.values()),
            return_exceptions=True,
        )
        return [
            capability
            for capability, response in zip(paths, responses, strict=True)
            if isinstance(response, httpx.Response) and response.is_success
        ]


def refusal(
    response: httpx.Response,
    path: str,
    secret: str,
    code: DiagnosticCode,
    *,
    message: str | None = None,
    retry_after: int | None = None,
) -> ConnectorError:
    """The diagnostic for a failed answer, its detail cleaned of the secret."""
    return diagnose(
        code,
        message=message,
        provider_status=response.status_code,
        retry_after=retry_after,
        detail=f"GET {path} → {response.status_code}: {response.text[:200]}",
        secrets=[secret],
    )


def usual_code(status: int) -> DiagnosticCode:
    """What a status means when the vendor says nothing more precise."""
    if status == 401:
        return DiagnosticCode.AUTH_INVALID
    if status == 403:
        return DiagnosticCode.PERMISSION_DENIED
    if status == 404:
        return DiagnosticCode.NOT_FOUND
    if status == 429:
        return DiagnosticCode.RATE_LIMITED
    if status >= 500:
        return DiagnosticCode.PROVIDER_ERROR
    return DiagnosticCode.UNKNOWN


def retry_after(response: httpx.Response, reset_header: str | None = None) -> int | None:
    """Seconds to wait: Retry-After, else the vendor's reset time (epoch)."""
    if "retry-after" in response.headers:
        return int(response.headers["retry-after"])
    reset = response.headers.get(reset_header) if reset_header else None
    return max(0, int(reset) - int(time.time())) if reset else None


def parse_timestamp(value: object) -> datetime | None:
    """ISO 8601 as vendors send it — "…Z", "….000Z", "…+00:00" — or None."""
    return datetime.fromisoformat(str(value)) if value else None


def record(
    kind: Capability,
    item: Item,
    *,
    external_id: str,
    container: str | None = None,
    updated: object = None,
) -> RawRecord:
    return RawRecord(
        kind=kind,
        external_id=external_id,
        container=container,
        payload=item,
        updated_at=parse_timestamp(updated),
        fetched_at=datetime.now(UTC),
    )


async def records(
    kind: Capability,
    items: AsyncIterator[Item],
    container: str,
    *,
    key: Callable[[Any], str],
    updated: Callable[[Any], object] = lambda item: item.get("updated_at"),
) -> AsyncIterator[RawRecord]:
    """A listing's items as records of one container."""
    async for item in items:
        yield record(kind, item, external_id=key(item), container=container, updated=updated(item))


async def without(items: AsyncIterator[Item], field: str) -> AsyncIterator[Item]:
    async for item in items:
        if field not in item:
            yield item


async def nothing() -> AsyncIterator[RawRecord]:
    return
    yield  # an async generator that yields nothing
