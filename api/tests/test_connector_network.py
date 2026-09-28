"""Where a connector may connect (leka/connectors/network.py).

A fake resolver says what a name points to, and a MockTransport stands
behind the guard: what reaches it is what would have reached the network.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import HttpUrl, SecretStr, ValidationError

from leka.connectors import ConnectorError, DiagnosticCode
from leka.connectors.github import GitHubConfig, GitHubConnector, GitHubCredentials
from leka.connectors.gitlab import GitLabConfig
from leka.connectors.network import BlockedAddressError, PublicTransport

PUBLIC = "140.82.112.6"


def _guard(names: dict[str, list[str]]) -> tuple[PublicTransport, list[httpx.Request]]:
    reached: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        reached.append(request)
        return httpx.Response(200, json={})

    async def resolve(host: str, port: int) -> list[str]:
        return names[host]

    return PublicTransport(httpx.MockTransport(answer), resolve=resolve), reached


async def _get(transport: PublicTransport, url: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=transport) as client:
        return await client.get(url)


async def test_a_public_name_is_reached_at_the_address_that_was_checked() -> None:
    transport, reached = _guard({"api.github.com": [PUBLIC]})

    await _get(transport, "https://api.github.com/user")

    (request,) = reached
    assert request.url.host == PUBLIC
    assert request.headers["host"] == "api.github.com"
    # TLS is verified against the name, not the address.
    assert request.extensions["sni_hostname"] == "api.github.com"


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # the server itself
        "10.0.3.7",  # the private network
        "172.16.0.1",
        "192.168.1.10",
        "169.254.169.254",  # the cloud's metadata service
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",  # noqa: S104 — refused, not bound
        "::1",
        "fd00::1",
        "fe80::1",
        "::ffff:127.0.0.1",  # IPv4 loopback, written as IPv6
    ],
)
async def test_a_name_that_leads_inside_is_refused(address: str) -> None:
    transport, reached = _guard({"gitlab.acme.example": [address]})

    with pytest.raises(BlockedAddressError):
        await _get(transport, "https://gitlab.acme.example/api/v4/user")
    assert reached == []


async def test_one_private_address_among_public_ones_is_enough_to_refuse() -> None:
    transport, reached = _guard({"gitlab.acme.example": [PUBLIC, "10.0.0.5"]})

    with pytest.raises(BlockedAddressError):
        await _get(transport, "https://gitlab.acme.example/")
    assert reached == []


@pytest.mark.parametrize("url", ["https://127.0.0.1/", "https://[::1]/", "http://api.github.com/"])
async def test_a_literal_inside_address_and_plain_http_are_refused(url: str) -> None:
    transport, reached = _guard({"api.github.com": [PUBLIC]})

    with pytest.raises(BlockedAddressError):
        await _get(transport, url)
    assert reached == []


@pytest.mark.parametrize(
    "base_url",
    ["http://gitlab.acme.example", "https://10.0.0.5", "https://169.254.169.254", "https://[::1]"],
)
def test_the_form_refuses_what_is_plainly_not_a_public_https_address(base_url: str) -> None:
    with pytest.raises(ValidationError):
        GitLabConfig(base_url=base_url)
    with pytest.raises(ValidationError):
        GitHubConfig(base_url=base_url)


def test_the_form_accepts_a_public_https_name() -> None:
    assert GitLabConfig(base_url="https://gitlab.acme.example").base_url.host == (
        "gitlab.acme.example"
    )


async def test_a_connector_on_the_network_is_guarded_and_says_why() -> None:
    """No transport given: the real one, behind the guard. The config is
    built past its validation, as if the address had been saved before the
    form refused it; a literal address needs no DNS, so nothing leaves."""
    connector = GitHubConnector(
        GitHubConfig.model_construct(organization="acme", base_url=HttpUrl("https://127.0.0.1")),
        GitHubCredentials(token=SecretStr("github_pat_11ABCDEFG0123456789_secret")),
    )

    with pytest.raises(ConnectorError) as caught:
        await connector.test_connection()

    assert caught.value.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "public" in caught.value.diagnostic.message
