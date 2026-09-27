"""What every HTTP connector does the same way.

GitHub, GitLab and Bitbucket differ in what their answers mean, not in how
they are asked. One GET whose failures become diagnostics, pagination by
the Link header that never follows a link to another host, probes in
parallel, timestamps, and records: written once here, so a fix to any of
them is a fix to all.

What stays in each connector is what the vendor means: which 403 is a
quota and which a scope (`refuse`), and how its listings are shaped.

READS ONLY — AND A FEW READS ARE POSTS. Notion searches and Linear answers
GraphQL only through POST. `post` sends a body to the paths a connector
declared as reads when it built its client (`reads_by_post`), and to no
other: a POST anywhere else is refused before it leaves, as a bug.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

import httpx

from leka.connectors.base import Capability
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.schemas import RawRecord

type Item = dict[str, object]

# What a bulk read leaves of a token's quota. The token is often the
# customer's own — their CI and scripts spend the same quota — so LEKA stops
# reading before the last tenth rather than spending it all and failing, and
# comes back after the vendor's reset (LEKA-353).
QUOTA_RESERVE = 0.10
# When a vendor only says "near the limit" and not when it resets (Bitbucket).
UNKNOWN_RESET_SECONDS = 600


@dataclass(frozen=True)
class Quota:
    remaining: int
    limit: int
    reset_at: int | None  # epoch seconds, when the vendor says

    @property
    def low(self) -> bool:
        return self.limit > 0 and self.remaining < self.limit * QUOTA_RESERVE


def quota_of(response: httpx.Response) -> Quota | None:
    """What a response says of the quota: GitHub's x-ratelimit-*, GitLab's
    ratelimit-*, Bitbucket's x-ratelimit-nearlimit. None when it says nothing."""
    headers = response.headers
    for prefix in ("x-ratelimit-", "ratelimit-"):
        remaining, limit = headers.get(f"{prefix}remaining"), headers.get(f"{prefix}limit")
        if remaining is None or limit is None:
            continue
        try:
            reset = headers.get(f"{prefix}reset")
            return Quota(int(remaining), int(limit), int(reset) if reset else None)
        except ValueError:
            return None
    if headers.get("x-ratelimit-nearlimit", "").lower() == "true":
        return Quota(remaining=0, limit=1, reset_at=None)
    return None


# A list is sent as the parameter repeated: state=OPEN&state=MERGED.
type Params = Mapping[str, str | int | list[str]]
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
        page_cursor_param: str | None = None,
        reads_by_post: frozenset[str] = frozenset(),
    ) -> None:
        """`in_body`: for vendors that page in the body rather than the Link
        header — the fields holding the items and the next page's URL,
        ("values", "next") for Bitbucket, ("results", "_links.next") for
        Confluence: a field may be a path.

        `reads_by_post`: the paths a vendor reads through POST only, named
        one by one — Notion's "/search", Linear's "/graphql"."""
        self._client = client
        self._secret = secret
        self._refuse = refuse
        self._page = {page_size_param: page_size}
        self._in_body = in_body
        # Google's way: the body's field is a token, sent back as this
        # parameter on the same path — not a URL to follow.
        self._page_cursor_param = page_cursor_param
        self._reads_by_post = reads_by_post

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
        return await self._send("GET", path, params=params, missing=missing, empty=empty)

    async def post(
        self, path: str, body: Mapping[str, object], *, missing: str = ""
    ) -> httpx.Response:
        """A read the vendor offers only as a POST, answered like `get`.

        Only to a path declared in `reads_by_post`. Anything else raises
        before a byte is sent: a connector that POSTs elsewhere is a bug,
        and LEKA does not write to a customer's system.
        """
        if path not in self._reads_by_post:
            msg = f"POST {path} is not a read this connector declared"
            raise ValueError(msg)
        return await self._send("POST", path, json=body, missing=missing)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: Params | None = None,
        json: Mapping[str, object] | None = None,
        missing: str = "",
        empty: int | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(method, path, params=params, json=json)
        except httpx.TimeoutException as error:
            raise diagnose(
                DiagnosticCode.TIMEOUT, detail=f"{method} {path}", secrets=[self._secret]
            ) from error
        except httpx.TransportError as error:
            raise diagnose(
                DiagnosticCode.NETWORK_UNREACHABLE,
                detail=f"{method} {path}: {type(error).__name__}",
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
        skip_before: datetime | None = None,
        updated_field: str = "updated_at",
    ) -> AsyncIterator[Item]:
        """Every item of a listing, page after page.

        `stop_before`: the listing is SORTED newest-updated first, and
        nothing updated before this is wanted — the first older item ends it.

        `skip_before`: the listing is only ROUGHLY newest first, like a
        branch's commits, where a rebase or an old branch merged in puts an
        older date before newer ones. Older items are skipped, not a reason
        to stop; the listing ends after a page with nothing newer at all.

        `updated_field` may be a path: "version.createdAt".
        """
        url: str | None = path
        query: Params | None = {**self._page, **(params or {})}
        while url:
            response = await self.get(url, params=query, empty=empty)
            if response.status_code == empty:
                return
            body = response.json()
            page = (dig(body, self._in_body[0]) or []) if self._in_body else body
            skipped = 0
            for item in page:
                updated = parse_timestamp(dig(item, updated_field))
                if stop_before and (updated is None or updated < stop_before):
                    return
                if skip_before and updated is not None and updated < skip_before:
                    skipped += 1
                    continue
                yield item
            if skip_before and page and skipped == len(page):
                return
            if self._page_cursor_param and self._in_body:
                token = body.get(self._in_body[1])
                url = path if token else None
                query = {**self._page, **(params or {}), self._page_cursor_param: str(token)}
            else:
                url, query = self._next_page(response, body), None  # the link carries the query
            if url:
                self._spare_the_quota(response)

    def _spare_the_quota(self, response: httpx.Response) -> None:
        """Stop a bulk read before the next page when the token's quota is low.

        Only in `pages`: a connection test or a health check is a handful of
        calls, and refusing it for a quota at 9 % would say the source is
        broken when it is only busy. What was read so far stands; the pass
        records RATE_LIMITED with when to come back.
        """
        quota = quota_of(response)
        if quota is None or not quota.low:
            return
        wait = (
            max(0, quota.reset_at - int(time.time()))
            if quota.reset_at is not None
            else UNKNOWN_RESET_SECONDS
        )
        raise diagnose(
            DiagnosticCode.RATE_LIMITED,
            message="LEKA a mis la lecture en pause pour laisser une réserve de quota "
            "à vos autres outils sur ce jeton.",
            retry_after=wait,
            detail=f"quota {quota.remaining}/{quota.limit}, below the reserve",
            secrets=[self._secret],
        )

    def _next_page(self, response: httpx.Response, body: Any) -> str | None:
        """The next page — only if it is on the host the secret was meant for,
        over the same scheme.

        A relative link ("/wiki/api/v2/spaces?cursor=…", Confluence's) is
        read against the base URL; an absolute one, or a protocol-relative
        "//elsewhere", must land on the same host all the same.
        """
        if self._in_body:
            found = dig(body, self._in_body[1])
        else:
            found = response.links.get("next", {}).get("url")
        if not found:
            return None
        base = self._client.base_url
        link = base.join(str(found))
        if (link.scheme, link.host) != (base.scheme, base.host):
            raise diagnose(
                DiagnosticCode.PROVIDER_ERROR,
                detail=f"pagination points to another host: {link.scheme}://{link.host}",
                secrets=[self._secret],
            )
        return str(link)

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


def dig(item: Any, path: str) -> Any:
    """`item["version"]["createdAt"]` for "version.createdAt"; None where a
    step is missing."""
    for step in path.split("."):
        if not isinstance(item, dict):
            return None
        item = item.get(step)
    return item


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
