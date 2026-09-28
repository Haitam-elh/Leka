"""Microsoft's identity platform, for the connectors that read Microsoft —
Azure (LEKA-347) and Microsoft 365 (LEKA-346).

An application registered in the customer's Microsoft Entra tenant signs
in with its client id and a client secret (the client-credentials grant)
and receives a token for one resource: Azure Resource Manager, or
Microsoft Graph. The exchange is the connectors' one POST, to
login.microsoftonline.com, touching nothing of the customer's.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.http import refusal, usual_code

LOGIN = "https://login.microsoftonline.com"


async def client_credentials_token(
    http: Callable[[str], httpx.AsyncClient],
    tenant: str,
    client_id: str,
    secret: str,
    scope: str,
) -> str:
    """A token for the application, for the resource `scope` names
    ("https://graph.microsoft.com/.default"). `http` is the connector's own
    client maker, so the tests' stand-in answers for Microsoft too."""
    async with http(LOGIN) as login:
        try:
            response = await login.post(
                f"/{tenant}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": secret,
                    "scope": scope,
                },
            )
        except httpx.TimeoutException as error:
            raise diagnose(DiagnosticCode.TIMEOUT, detail="token") from error
        except httpx.TransportError as error:
            raise diagnose(
                DiagnosticCode.NETWORK_UNREACHABLE, detail=f"token: {type(error).__name__}"
            ) from error
    if not response.is_success:
        raise refuse_token(response, secret)
    return str(response.json()["access_token"])


def refuse_token(response: httpx.Response, secret: str) -> ConnectorError:
    """Microsoft identity's AADSTS codes, as diagnostics."""
    body = response.text[:300]
    if "AADSTS90002" in body or "AADSTS900023" in body:  # no such tenant
        return refusal(
            response,
            "token",
            secret,
            DiagnosticCode.NOT_FOUND,
            message="Ce tenant Microsoft Entra n'existe pas.",
        )
    if "AADSTS7000222" in body:  # the secret has expired
        return refusal(response, "token", secret, DiagnosticCode.AUTH_EXPIRED)
    if response.status_code in (400, 401):  # a wrong secret, an unknown app
        return refusal(response, "token", secret, DiagnosticCode.AUTH_INVALID)
    return refusal(response, "token", secret, usual_code(response.status_code))
