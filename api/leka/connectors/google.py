"""Google's service accounts, for the connectors that read Google — Google
Cloud (LEKA-347) and Google Workspace (LEKA-346).

A service account signs a JWT with its own private key; Google's token
endpoint exchanges it for an access token (RFC 7523). The JWT names the
scope — always a read-only one — and, for Google Workspace, the user the
account acts as (`sub`), when a Workspace admin granted it domain-wide
delegation. The exchange is the connectors' one POST, to
oauth2.googleapis.com, touching nothing of the customer's.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from leka.connectors.errors import DiagnosticCode, diagnose
from leka.connectors.http import refusal, usual_code

GOOGLE_OAUTH = "https://oauth2.googleapis.com"
TOKEN_URL = f"{GOOGLE_OAUTH}/token"


def service_account_key(text: str) -> dict[str, str]:
    """The JSON key of a service account, as Google Cloud downloads it —
    or ValueError, for a credentials validator to report."""
    try:
        key = json.loads(text)
    except json.JSONDecodeError as error:
        msg = "not a JSON key: paste the whole file Google Cloud downloaded"
        raise ValueError(msg) from error
    if not isinstance(key, dict):
        msg = "not a service account key (type, client_email, private_key)"
        raise ValueError(msg)
    missing = {"type", "client_email", "private_key"} - set(key)
    if key.get("type") != "service_account" or missing:
        msg = "not a service account key (type, client_email, private_key)"
        raise ValueError(msg)
    return {name: str(value) for name, value in key.items()}


async def service_account_token(
    http: Callable[[str], httpx.AsyncClient],
    key: dict[str, str],
    scope: str,
    *,
    subject: str | None = None,
) -> str:
    """An access token for the service account, under `scope`, acting as
    `subject` when one is given. `http` is the connector's own client
    maker, so the tests' stand-in answers for Google too."""
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": key["client_email"],
        "scope": scope,
        "aud": TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    if subject:
        claims["sub"] = subject
    assertion = signed_jwt(claims, key["private_key"])
    async with http(GOOGLE_OAUTH) as google:
        try:
            response = await google.post(
                "/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
        except httpx.TimeoutException as error:
            raise diagnose(DiagnosticCode.TIMEOUT, detail="token") from error
        except httpx.TransportError as error:
            raise diagnose(
                DiagnosticCode.NETWORK_UNREACHABLE, detail=f"token: {type(error).__name__}"
            ) from error
    if not response.is_success:
        secret = key["private_key"]
        if "unauthorized_client" in response.text:
            # Acting as a user the account was not delegated for, or for a
            # scope the delegation does not list.
            raise refusal(
                response,
                "token",
                secret,
                DiagnosticCode.PERMISSION_DENIED,
                message="Google refuse que ce compte de service agisse pour cet utilisateur : "
                "la délégation au niveau du domaine doit lui accorder ce scope.",
            )
        # invalid_grant: a key deleted or disabled, a clock far off.
        code = (
            DiagnosticCode.AUTH_INVALID
            if response.status_code in (400, 401)
            else usual_code(response.status_code)
        )
        raise refusal(response, "token", secret, code)
    return str(response.json()["access_token"])


def signed_jwt(claims: dict[str, Any], private_key: str) -> str:
    """RS256, as Google's token endpoint requires for a service account."""
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps(claims).encode())
    signing_input = f"{header}.{payload}".encode()
    try:
        key = serialization.load_pem_private_key(private_key.encode(), password=None)
    except (ValueError, TypeError) as error:
        raise diagnose(
            DiagnosticCode.CONFIG_INVALID,
            message="La clé privée du compte de service est illisible : téléchargez-en une autre.",
        ) from error
    if not isinstance(key, rsa.RSAPrivateKey):
        raise diagnose(
            DiagnosticCode.CONFIG_INVALID,
            message="La clé du compte de service n'est pas une clé RSA.",
        )
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64(signature)}"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
