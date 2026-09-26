"""What Jira and Confluence share: an Atlassian Cloud site, and how to sign in.

Both are read at https://<site>.atlassian.net, with the email of an
Atlassian account and one of its API tokens, sent as HTTP Basic. Both answer
refusals the same way and announce a nearly spent quota with the same
header. That is written once, here; what each product means stays in its
connector.

THE HOST IS NEVER FREE TEXT. An admin types the site's name — "acme", or
pastes "https://acme.atlassian.net/jira/..." — and only the name survives,
checked against what Atlassian allows. The host is built here, always under
atlassian.net. A connector whose host could be typed would let anyone who
may add a source point LEKA's requests into LEKA's own network.

LEKA READS. An API token carries every permission of its account, and
Atlassian cannot narrow a classic token to reading. The documentation asks
for a dedicated account that can only browse; the connectors warn when the
account can administer.
"""

from __future__ import annotations

import base64
import re
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from leka.connectors.base import HealthResult
from leka.connectors.errors import ConnectorError, DiagnosticCode
from leka.connectors.http import Refuse, refusal, retry_after, usual_code
from leka.connectors.models import HealthStatus

# A site's name: letters, digits and inner hyphens — what Atlassian accepts
# when a site is created, and nothing that could change the host.
SITE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
SUFFIX = ".atlassian.net"


def site_name(value: str) -> str:
    """The site's name from what an admin typed.

    "acme", "acme.atlassian.net" and "https://acme.atlassian.net/wiki/home"
    all give "acme". Anything that is not a name under atlassian.net is
    refused, not repaired.
    """
    text = value.strip().lower()
    for scheme in ("https://", "http://"):
        text = text.removeprefix(scheme)
    host = text.split("/", 1)[0]
    if "." in host:
        if not host.endswith(SUFFIX):
            msg = f"{value!r} is not an Atlassian Cloud site (…{SUFFIX})"
            raise ValueError(msg)
        host = host.removesuffix(SUFFIX)
    if not SITE.match(host):
        msg = f"{value!r} is not a site name like 'acme' (acme{SUFFIX})"
        raise ValueError(msg)
    return host


def site_url(site: str) -> str:
    """The only address a connector of this module ever calls."""
    return f"https://{site}{SUFFIX}"


class AtlassianCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First: the stored hint is taken from the first field.
    token: SecretStr = Field(
        min_length=20,
        description="An API token of the account, created at "
        "id.atlassian.com → Security → API tokens.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    email: str = Field(
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+$",
        description="The email of the Atlassian account the token belongs to.",
    )


def headers(credentials: AtlassianCredentials) -> dict[str, str]:
    """Basic authentication, as Atlassian takes an API token."""
    pair = f"{credentials.email}:{credentials.token.get_secret_value()}".encode()
    return {
        "Accept": "application/json",
        "User-Agent": "LEKA",
        "Authorization": "Basic " + base64.b64encode(pair).decode(),
    }


def refuser(product: str, credentials: AtlassianCredentials) -> Refuse:
    """How an Atlassian product's refusals become diagnostics.

    A redirect is a site that does not exist: Atlassian sends the browser
    elsewhere rather than answering. A 403 naming a scope is a token short
    of one. A 401 is the email and the token together — Atlassian does not
    say which of the two is wrong.
    """
    secret = credentials.token.get_secret_value()

    def refuse(response: httpx.Response, path: str, missing: str) -> ConnectorError:
        status, body = response.status_code, response.text[:300].lower()
        code = usual_code(status)
        if response.is_redirect:
            message = "Ce site Atlassian n'existe pas, ou n'est pas un site Atlassian Cloud."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        if status == 401:
            message = f"{product} refuse cette adresse e-mail ou ce jeton."
            return refusal(response, path, secret, code, message=message)
        if status == 403 and "scope" in body:
            code = DiagnosticCode.INSUFFICIENT_SCOPE
        if code is DiagnosticCode.RATE_LIMITED:
            return refusal(response, path, secret, code, retry_after=retry_after(response))
        if code is DiagnosticCode.NOT_FOUND:
            what = missing or "cette ressource"
            message = f"{product} ne trouve pas {what}, ou ce compte ne le voit pas."
            return refusal(response, path, secret, code, message=message)
        return refusal(response, path, secret, code)

    return refuse


def health(response: httpx.Response) -> HealthResult:
    """Healthy, or degraded when Atlassian says the quota is nearly spent."""
    near = response.headers.get("x-ratelimit-nearlimit", "").lower() == "true"
    return HealthResult(
        status=HealthStatus.DEGRADED if near else HealthStatus.HEALTHY,
        detail="quota presque épuisé" if near else None,
        checked_at=datetime.now(UTC),
    )
