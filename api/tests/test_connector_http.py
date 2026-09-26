"""The HTTP every connector shares (leka/connectors/http.py), on its own.

GitHub and GitLab test the Link header through their own suites; what is
tested here is what only a body-paged vendor (Bitbucket) will use, and the
refusals that apply to every vendor.
"""

from __future__ import annotations

import httpx
import pytest

from leka.connectors import ConnectorError, DiagnosticCode
from leka.connectors.http import VendorHttp, refusal, usual_code

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
