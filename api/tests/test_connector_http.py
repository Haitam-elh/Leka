"""The HTTP every connector shares (leka/connectors/http.py), on its own.

GitHub and GitLab test the Link header through their own suites; what is
tested here is what only a body-paged vendor (Bitbucket) will use, and the
refusals that apply to every vendor.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from leka.connectors import ConnectorError, DiagnosticCode
from leka.connectors.http import VendorHttp, dig, refusal, usual_code

SECRET = "a-secret-that-must-never-leak-0123456789"


def _vendor(handler: httpx.MockTransport) -> VendorHttp:
    def refuse(response: httpx.Response, path: str, missing: str) -> ConnectorError:
        return refusal(response, path, SECRET, usual_code(response.status_code))

    client = httpx.AsyncClient(base_url="https://api.vendor.example", transport=handler)
    return VendorHttp(
        client,
        secret=SECRET,
        refuse=refuse,
        page_size=50,
        page_size_param="pagelen",
        in_body=("values", "next"),
    )


async def test_a_body_paged_listing_is_read_to_its_end() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json={"values": [{"n": 3}]})
        assert request.url.params["pagelen"] == "50"
        following = "https://api.vendor.example/things?page=2"
        return httpx.Response(200, json={"values": [{"n": 1}, {"n": 2}], "next": following})

    async with _vendor(httpx.MockTransport(handle)) as vendor:
        items = [item async for item in vendor.pages("/things")]

    assert [item["n"] for item in items] == [1, 2, 3]


async def test_a_next_page_elsewhere_is_refused() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.vendor.example", "the secret went elsewhere"
        return httpx.Response(200, json={"values": [], "next": "https://evil.example/x"})

    async with _vendor(httpx.MockTransport(handle)) as vendor:
        with pytest.raises(ConnectorError) as caught:
            _ = [item async for item in vendor.pages("/things")]

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR


def _confluence_like(handler: httpx.MockTransport) -> VendorHttp:
    """A vendor whose items and next link sit deeper in the body, and whose
    links are relative: Confluence's shape."""

    def refuse(response: httpx.Response, path: str, missing: str) -> ConnectorError:
        return refusal(response, path, SECRET, usual_code(response.status_code))

    client = httpx.AsyncClient(base_url="https://acme.atlassian.net/wiki", transport=handler)
    return VendorHttp(
        client,
        secret=SECRET,
        refuse=refuse,
        page_size=50,
        page_size_param="limit",
        in_body=("results", "_links.next"),
    )


async def test_a_relative_next_link_is_followed_on_the_same_host() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "acme.atlassian.net", "the secret went elsewhere"
        if request.url.params.get("cursor") == "c2":
            assert request.url.path == "/wiki/api/v2/spaces"
            return httpx.Response(200, json={"results": [{"n": 2}], "_links": {}})
        following = "/wiki/api/v2/spaces?cursor=c2&limit=50"
        return httpx.Response(200, json={"results": [{"n": 1}], "_links": {"next": following}})

    async with _confluence_like(httpx.MockTransport(handle)) as vendor:
        items = [item async for item in vendor.pages("/api/v2/spaces")]

    assert [item["n"] for item in items] == [1, 2]


@pytest.mark.parametrize(
    "following",
    [
        "//evil.example/wiki/api/v2/spaces?cursor=c2",
        "http://acme.atlassian.net/wiki/api/v2/spaces?cursor=c2",
        "https://evil.example/wiki/api/v2/spaces?cursor=c2",
    ],
)
async def test_a_next_link_elsewhere_or_in_clear_is_refused(following: str) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("cursor") is None, "the next link was followed"
        return httpx.Response(200, json={"results": [], "_links": {"next": following}})

    async with _confluence_like(httpx.MockTransport(handle)) as vendor:
        with pytest.raises(ConnectorError) as caught:
            _ = [item async for item in vendor.pages("/api/v2/spaces")]

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR


async def test_a_listing_stops_at_a_nested_date() -> None:
    newest = {"id": 1, "version": {"createdAt": "2026-09-25T10:00:00.000Z"}}
    older = {"id": 2, "version": {"createdAt": "2026-09-01T10:00:00.000Z"}}
    body = {"results": [newest, older], "_links": {"next": "/wiki/api/v2/pages?cursor=c2"}}

    async with _confluence_like(
        httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as vendor:
        since = datetime(2026, 9, 20, tzinfo=UTC)
        items = [
            item
            async for item in vendor.pages(
                "/api/v2/pages", stop_before=since, updated_field="version.createdAt"
            )
        ]

    assert [item["id"] for item in items] == [1]


def test_dig_follows_a_path_and_gives_none_where_it_ends() -> None:
    item = {"version": {"createdAt": "x"}, "flat": 1}

    assert dig(item, "version.createdAt") == "x"
    assert dig(item, "flat") == 1
    assert dig(item, "version.missing") is None
    assert dig(item, "flat.deeper") is None


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "AUTH_INVALID"),
        (403, "PERMISSION_DENIED"),
        (404, "NOT_FOUND"),
        (429, "RATE_LIMITED"),
        (503, "PROVIDER_ERROR"),
        (418, "UNKNOWN"),
    ],
)
async def test_a_refusal_carries_its_code_and_never_the_secret(status: int, code: str) -> None:
    echo = httpx.MockTransport(lambda request: httpx.Response(status, text=f"no: {SECRET}"))

    async with _vendor(echo) as vendor:
        with pytest.raises(ConnectorError) as caught:
            await vendor.get("/things")
        assert await vendor.get_if_answered("/things") is None

    assert caught.value.diagnostic.code == DiagnosticCode(code)
    assert SECRET not in repr(caught.value.diagnostic)
