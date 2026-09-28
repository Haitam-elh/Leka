"""Where a connector may connect: the public internet, over https. Nowhere else.

A source's `base_url` is typed by an admin, and LEKA's server calls it. Left
open, that is a way to make the server call itself (127.0.0.1), the private
network it sits in (10.x, 172.16/12, 192.168/16), or the cloud's metadata
service (169.254.169.254) — and a diagnostic hands back the start of what
answered.

Checked WHEN CONNECTING, not when the URL is saved: a name that resolves to
a public address today can resolve to 127.0.0.1 tomorrow, or between the
check and the connection (DNS rebinding). So the transport resolves the
name, refuses unless every address is public, and connects to the address
it checked — the name still goes as Host and as TLS SNI, so the vendor's
certificate is verified against the name, not the address.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from typing import Annotated

import httpx
from pydantic import AfterValidator, HttpUrl

type Address = ipaddress.IPv4Address | ipaddress.IPv6Address
type Resolve = Callable[[str, int], Awaitable[list[str]]]


class BlockedAddressError(httpx.ConnectError):
    """The URL leads somewhere a connector must not go."""


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def is_public(address: Address) -> bool:
    """Globally routable. An IPv4 address written as IPv6 is judged as IPv4."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


class PublicTransport(httpx.AsyncBaseTransport):
    """https to public addresses only, pinned to the address it checked."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport | None = None,
        *,
        resolve: Resolve = _resolve,
    ) -> None:
        self._inner = inner or httpx.AsyncHTTPTransport()
        self._resolve = resolve

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme != "https":
            raise BlockedAddressError(f"{url.scheme}:// refused: https only", request=request)
        host = url.host
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            try:
                addresses = [
                    ipaddress.ip_address(a) for a in await self._resolve(host, url.port or 443)
                ]
            except OSError as error:
                raise httpx.ConnectError(f"cannot resolve {host}", request=request) from error
        if not addresses or not all(is_public(address) for address in addresses):
            raise BlockedAddressError(f"{host} is not a public address", request=request)

        pinned = str(addresses[0])
        request.url = url.copy_with(host=pinned)
        request.extensions = {**request.extensions, "sni_hostname": host}
        # Host stays the name: httpx set it from the URL before we changed it.
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


class PrivateAddressError(ValueError):
    """A host — not a URL: a database's — that leads somewhere a connector
    must not go."""


async def public_address(host: str, port: int, *, resolve: Resolve = _resolve) -> str:
    """The address to connect to for `host`: resolved now, every address it
    has public, the first of them. Connect to it, not to the name — the name
    cannot then change target between this check and the connection. The
    same rule as PublicTransport's, for what does not speak HTTP.

    A name that does not resolve raises the resolver's OSError: a network
    failure, not a refusal."""
    try:
        addresses = [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        addresses = [ipaddress.ip_address(a) for a in await resolve(host, port)]
    if not addresses or not all(is_public(address) for address in addresses):
        msg = f"{host} is not a public address"
        raise PrivateAddressError(msg)
    return str(addresses[0])


def obviously_private(host: str) -> bool:
    """A literal address that is not public: 10.0.0.5, ::1. For the form's
    early answer — a name is checked when connecting, by public_address."""
    try:
        return not is_public(ipaddress.ip_address(host.strip().strip("[]")))
    except ValueError:
        return False


def _https_and_not_an_obvious_private_address(url: HttpUrl) -> HttpUrl:
    """Early, readable feedback in the form. Not the protection — the
    transport is: a name can point anywhere once it has been saved."""
    if url.scheme != "https":
        msg = "only https:// addresses are accepted"
        raise ValueError(msg)
    try:
        address = ipaddress.ip_address((url.host or "").strip("[]"))
    except ValueError:
        return url
    if not is_public(address):
        msg = f"{url.host} is not a public address"
        raise ValueError(msg)
    return url


# A base_url a customer can type: https, and not a private address.
PublicHttpsUrl = Annotated[HttpUrl, AfterValidator(_https_and_not_an_obvious_private_address)]
