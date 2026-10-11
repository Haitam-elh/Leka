"""Stripe, as LEKA uses it (LEKA-431): its REST API, form-encoded, with the
secret key — server-side only, never in a browser — and its webhooks,
believed only once their signature is verified.

No SDK: a handful of calls (products, prices, coupons, checkout sessions,
the customer portal, subscriptions) and one signature check (HMAC-SHA256),
not worth a dependency.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

API = "https://api.stripe.com"
TIMEOUT = 20.0
# How old a webhook's timestamp may be, in seconds: Stripe's own default.
TOLERANCE = 300

Form = list[tuple[str, str]]


class StripeError(Exception):
    """What Stripe answered, when it is not a success."""

    def __init__(self, status: int, code: str | None, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class SignatureError(Exception):
    """A webhook whose signature, or age, does not hold."""


def form(data: Mapping[str, Any], prefix: str = "") -> Form:
    """Stripe's form encoding: nested keys as a[b][c], lists as a[0], booleans
    as true/false; None left out."""
    said: Form = []
    for key, value in data.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if value is None:
            continue
        if isinstance(value, Mapping):
            said.extend(form(value, name))
        elif isinstance(value, list | tuple):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    said.extend(form(item, f"{name}[{index}]"))
                else:
                    said.append((f"{name}[{index}]", _word(item)))
        else:
            said.append((name, _word(value)))
    return said


def _word(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class Stripe:
    """Stripe's API, with one secret key."""

    def __init__(
        self,
        secret: str,
        *,
        base_url: str = API,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._secret = secret
        self._base = base_url.rstrip("/")
        self._transport = transport

    async def _call(
        self,
        method: str,
        path: str,
        *,
        data: Mapping[str, Any] | None = None,
        params: list[tuple[str, str | int | float | bool | None]] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Stripe-Version": "2024-06-20"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(
            base_url=self._base,
            auth=(self._secret, ""),
            timeout=TIMEOUT,
            transport=self._transport,
            headers=headers,
        ) as client:
            response = await client.request(
                method, path, data=dict(form(data)) if data else None, params=params
            )
        body: dict[str, Any] = response.json() if response.content else {}
        if response.status_code >= 400:
            error = body.get("error") or {}
            raise StripeError(
                response.status_code,
                error.get("code") or error.get("type"),
                str(error.get("message") or f"Stripe answered {response.status_code}"),
            )
        return body

    async def get(
        self, path: str, params: Sequence[tuple[str, str]] | None = None
    ) -> dict[str, Any]:
        return await self._call("GET", path, params=list(params) if params else None)

    async def post(
        self, path: str, data: Mapping[str, Any], *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        return await self._call("POST", path, data=data, idempotency_key=idempotency_key)


def verify(
    payload: bytes, header: str, secret: str, *, now: int, tolerance: int = TOLERANCE
) -> dict[str, Any]:
    """The event a webhook carries — only when its `Stripe-Signature` holds:
    HMAC-SHA256 of "{t}.{payload}" with the endpoint's secret, one of its
    v1 signatures, its timestamp within `tolerance` of now. SignatureError
    otherwise."""
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        key, _, value = item.strip().partition("=")
        if key and value:
            parts.setdefault(key, []).append(value)
    try:
        stamp = int(parts["t"][0])
    except (KeyError, ValueError) as error:
        raise SignatureError("no timestamp") from error
    if abs(now - stamp) > tolerance:
        raise SignatureError("too old")
    expected = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, given) for given in parts.get("v1", [])):
        raise SignatureError("signature")
    try:
        event: dict[str, Any] = json.loads(payload)
    except ValueError as error:
        raise SignatureError("not JSON") from error
    return event


def sign(payload: bytes, secret: str, *, at: int) -> str:
    """A `Stripe-Signature` header, as Stripe writes it — for the tests."""
    digest = hmac.new(secret.encode(), f"{at}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={at},v1={digest}"


__all__ = ["API", "SignatureError", "Stripe", "StripeError", "form", "sign", "verify"]
