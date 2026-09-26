"""The HTTP every connector shares (leka/connectors/http.py), on its own.

GitHub and GitLab test the Link header through their own suites; what is
tested here is what only a body-paged vendor (Bitbucket) will use, and the
refusals that apply to every vendor.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import httpx
import pytest

from leka.connectors import ConnectorError, DiagnosticCode
from leka.connectors.http import Quota, VendorHttp, dig, quota_of, refusal, usual_code

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


# ── sparing the customer's quota (LEKA-353) ──────────────────────────────────


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (
            {
                "x-ratelimit-remaining": "4900",
                "x-ratelimit-limit": "5000",
                "x-ratelimit-reset": "9",
            },
            Quota(4900, 5000, 9),
        ),  # GitHub
        ({"ratelimit-remaining": "3", "ratelimit-limit": "2000"}, Quota(3, 2000, None)),  # GitLab
        ({"x-ratelimit-nearlimit": "true"}, Quota(0, 1, None)),  # Bitbucket
        ({}, None),
        ({"x-ratelimit-remaining": "many", "x-ratelimit-limit": "5000"}, None),
    ],
    ids=["github", "gitlab", "bitbucket", "silent", "garbled"],
)
def test_the_quota_is_read_the_way_each_vendor_writes_it(
    headers: dict[str, str], expected: Quota | None
) -> None:
    assert quota_of(httpx.Response(200, headers=headers)) == expected


def _paged(remaining: int, *, reset_in: int = 120) -> tuple[httpx.MockTransport, list[str]]:
    asked: list[str] = []
    reset = str(int(time.time()) + reset_in)

    def handle(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        asked.append(page)
        quota = {
            "x-ratelimit-remaining": str(remaining),
            "x-ratelimit-limit": "100",
            "x-ratelimit-reset": reset,
        }
        if page == "1":
            following = "https://api.vendor.example/things?page=2"
            return httpx.Response(
                200, json={"values": [{"n": 1}], "next": following}, headers=quota
            )
        return httpx.Response(200, json={"values": [{"n": 2}]}, headers=quota)

    return httpx.MockTransport(handle), asked


async def test_a_bulk_read_stops_before_the_reserve_and_keeps_what_it_read() -> None:
    transport, asked = _paged(remaining=5)
    read: list[object] = []

    async with _vendor(transport) as vendor:
        with pytest.raises(ConnectorError) as caught:
            async for item in vendor.pages("/things"):
                read.append(item["n"])

    assert read == [1]  # the page it had is kept
    assert asked == ["1"]  # the next one is not asked for
    diagnostic = caught.value.diagnostic
    assert diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert diagnostic.retry_after is not None and 100 <= diagnostic.retry_after <= 120
    assert "réserve" in diagnostic.message


async def test_a_quota_above_the_reserve_or_a_last_page_does_not_stop_it() -> None:
    plenty, asked = _paged(remaining=50)
    async with _vendor(plenty) as vendor:
        assert [item["n"] async for item in vendor.pages("/things")] == [1, 2]
    assert asked == ["1", "2"]


async def test_a_single_call_is_not_refused_for_a_low_quota() -> None:
    transport, _ = _paged(remaining=1)
    async with _vendor(transport) as vendor:
        assert (await vendor.get("/things")).status_code == 200


# ── reads a vendor offers only as POST ───────────────────────────────────────


def _reading_by_post(handler: httpx.MockTransport) -> VendorHttp:
    def refuse(response: httpx.Response, path: str, missing: str) -> ConnectorError:
        return refusal(response, path, SECRET, usual_code(response.status_code))

    client = httpx.AsyncClient(base_url="https://api.vendor.example", transport=handler)
    return VendorHttp(
        client, secret=SECRET, refuse=refuse, page_size=50, reads_by_post=frozenset({"/search"})
    )


async def test_a_declared_read_is_posted_with_its_body() -> None:
    sent: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"results": []})

    async with _reading_by_post(httpx.MockTransport(handle)) as vendor:
        response = await vendor.post("/search", {"query": "runbook"})

    assert response.json() == {"results": []}
    assert (sent[0].method, sent[0].url.path) == ("POST", "/search")
    assert sent[0].read() == b'{"query":"runbook"}'


@pytest.mark.parametrize("path", ["/pages", "/search/../pages", "/search/", "/blocks/1/children"])
async def test_a_post_anywhere_else_is_refused_before_it_is_sent(path: str) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing may be sent")

    async with _reading_by_post(httpx.MockTransport(handle)) as vendor:
        with pytest.raises(ValueError, match="not a read this connector declared"):
            await vendor.post(path, {"archived": True})


async def test_a_refused_post_is_a_diagnostic_like_a_get() -> None:
    echo = httpx.MockTransport(lambda request: httpx.Response(429, text=f"slow down {SECRET}"))

    async with _reading_by_post(echo) as vendor:
        with pytest.raises(ConnectorError) as caught:
            await vendor.post("/search", {})

    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert SECRET not in repr(caught.value.diagnostic)


async def test_a_client_that_declared_nothing_posts_nothing() -> None:
    async with _vendor(httpx.MockTransport(lambda request: httpx.Response(200))) as vendor:
        with pytest.raises(ValueError):
            await vendor.post("/things", {})
