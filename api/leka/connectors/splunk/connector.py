"""The Splunk connector — alerts, the alerts that fired, dashboards.

Splunk is read through its REST API on the management port — Splunk Cloud
Platform (https://acme.splunkcloud.com:8089, once the address LEKA calls
from is allowed to reach it) or a Splunk Enterprise of the customer's own —
with an authentication token, as Bearer. The token's user needs a role that
sees the apps to read, and nothing more: what it cannot see, LEKA cannot.
Every call is a GET, over https, to a public address only
(leka/connectors/network.py), with a certificate a known authority signed:
Splunk Enterprise's own self-signed one is refused — the management port
needs a real one.

    alerts      the saved searches that alert: their search, schedule,
                severity, actions, app and owner
    events      the alerts that fired: which search, when, how severe —
                what Splunk keeps of them (each alert's expiry, 24 hours
                by default)
    dashboards  every dashboard: its label, description and app

test_connection: whose token it is (GET /services/authentication/
current-context), and which of the three it can read — one small read
each, a refusal leaving it out.

check_health: the same call.

list_scope: none — the source's scope rules (docs/connectors/
scope-and-mapping.md) apply to each record's container: its app.

iter_resources: alerts and dashboards come whole each pass, page after page
(Splunk's count and offset); fired alerts too, newest first, at most
MAX_FIRED a pass.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from leka.connectors.base import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    HealthResult,
)
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.http import (
    Item,
    Params,
    VendorHttp,
    dig,
    record,
    refusal,
    retry_after,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.network import PublicHttpsUrl
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

C = Capability
PAGE_SIZE = 100
MAX_PAGES = 500
MAX_FIRED = 10_000
WHO = "/services/authentication/current-context"
SAVED_SEARCHES = "/servicesNS/-/-/saved/searches"
FIRED_ALERTS = "/services/alerts/fired_alerts/-"
VIEWS = "/servicesNS/-/-/data/ui/views"
# What a dashboard's listing needs — not its source, which can be large.
VIEW_FIELDS = ["label", "description", "isDashboard", "isVisible"]


class SplunkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: PublicHttpsUrl = Field(
        description="The address of Splunk's REST API, on its management port: "
        "https://acme.splunkcloud.com:8089, or one of your own.",
    )


class SplunkCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr = Field(
        min_length=20,
        max_length=4096,
        description="An authentication token (Settings → Tokens) of a user whose role "
        "sees the apps to read.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class SplunkConnector(Connector[SplunkConfig, SplunkCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.SPLUNK,
        display_name="Splunk",
        category=ConnectorCategory.OBSERVABILITY,
        auth_type="token",
        config_schema=SplunkConfig,
        credentials_schema=SplunkCredentials,
        capabilities=frozenset({C.ALERTS, C.EVENTS, C.DASHBOARDS}),
        # Each is listed whole: what a pass did not see is gone.
        listed_whole=frozenset({C.ALERTS, C.DASHBOARDS}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            who = (await client.get(WHO, params={"output_mode": "json"})).json()
            capabilities = await client.probe(
                {
                    C.ALERTS: SAVED_SEARCHES,
                    C.EVENTS: FIRED_ALERTS,
                    C.DASHBOARDS: VIEWS,
                },
                params={"output_mode": "json", "count": 1},
            )
        entries = who.get("entry") if isinstance(who, dict) else None
        first = entries[0] if isinstance(entries, list) and entries else None
        found = first.get("content") if isinstance(first, dict) else None
        content: Item = found if isinstance(found, dict) else {}
        warnings: list[str] = []
        if not capabilities:
            warnings.append(
                "Ce token ne peut rien lire : donnez à son utilisateur un rôle qui voit les "
                "applications à lire."
            )
        return ConnectionTestResult(
            account=str(content.get("realname") or content.get("username") or "Splunk"),
            metadata={"url": str(self.config.base_url), "roles": content.get("roles") or []},
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            await client.get(WHO, params={"output_mode": "json"})
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Splunk does not read {capability}"
            raise ValueError(msg)
        async with self._client() as client:
            if capability is C.ALERTS:
                async for entry in self._entries(client, SAVED_SEARCHES, {}):
                    if not is_alert(entry):
                        continue
                    yield record(
                        capability,
                        entry,
                        external_id=entry_key(entry),
                        container=_app(entry),
                        updated=entry.get("updated"),
                    )
            elif capability is C.DASHBOARDS:
                async for entry in self._entries(client, VIEWS, {"f": VIEW_FIELDS}):
                    if not _truthy(dig(entry, "content.isDashboard")):
                        continue
                    yield record(
                        capability,
                        entry,
                        external_id=entry_key(entry),
                        container=_app(entry),
                        updated=entry.get("updated"),
                    )
            else:
                given = 0
                async for entry in self._entries(client, FIRED_ALERTS, {}):
                    if given == MAX_FIRED:
                        return
                    given += 1
                    fired = _from_epoch(dig(entry, "content.trigger_time"))
                    yield record(
                        capability,
                        entry,
                        external_id=str(dig(entry, "content.sid") or entry_key(entry)),
                        container=_app(entry),
                        updated=fired or entry.get("updated"),
                    )

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.token.get_secret_value()
        client = self.http(
            str(self.config.base_url).rstrip("/"),
            headers={
                "Accept": "application/json",
                "User-Agent": "LEKA",
                "Authorization": f"Bearer {secret}",
            },
        )
        return VendorHttp(client, secret=secret, refuse=self._refuse, page_size=0)

    async def _entries(self, client: VendorHttp, path: str, params: Params) -> AsyncIterator[Item]:
        """Every entry of a listing, Splunk's offset after offset, until its
        `paging.total` is reached."""
        offset = 0
        for _ in range(MAX_PAGES):
            response = await client.get(
                path,
                params={**params, "output_mode": "json", "count": PAGE_SIZE, "offset": offset},
            )
            body = response.json()
            entries = body.get("entry") or [] if isinstance(body, dict) else []
            for entry in entries:
                if isinstance(entry, dict):
                    yield entry
            offset += len(entries)
            total = dig(body, "paging.total")
            if not entries or not isinstance(total, int) or offset >= total:
                return
        raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail=f"Splunk gave too many pages: {path}")

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Splunk's refusals, as diagnostics."""
        secret = self.credentials.token.get_secret_value()
        status = response.status_code
        if status == 429:
            return refusal(
                response,
                path,
                secret,
                DiagnosticCode.RATE_LIMITED,
                retry_after=retry_after(response),
            )
        if status == 401:
            message = "Splunk refuse ce token d'authentification."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 403:
            message = (
                "Splunk refuse cette lecture : le rôle de l'utilisateur du token ne la permet pas."
            )
            return refusal(
                response, path, secret, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        if status == 404:
            message = (
                "Splunk ne trouve pas cette adresse : vérifiez l'adresse de l'API, sur le port "
                "de gestion (8089 en général)."
            )
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        return refusal(response, path, secret, usual_code(status))


def is_alert(entry: Item) -> bool:
    """A saved search that alerts: scheduled, and with a condition that
    triggers or an alert that is tracked — not a report."""
    found = entry.get("content")
    content: Item = found if isinstance(found, dict) else {}
    if not _truthy(content.get("is_scheduled")):
        return False
    condition = str(content.get("alert_type") or "always").strip().lower()
    return condition != "always" or _truthy(content.get("alert.track"))


def entry_key(entry: Item) -> str:
    """An entry's place in Splunk — `nobody/search/saved/searches/Disk full`
    — from its id, a URL whose host can change; its name when it has none."""
    identifier = str(entry.get("id") or "")
    path = unquote(urlsplit(identifier).path)
    for marker in ("/servicesNS/", "/services/"):
        if marker in path:
            return path.split(marker, 1)[1]
    return str(entry.get("name") or identifier)


def _app(entry: Item) -> str | None:
    app = dig(entry, "acl.app") or dig(entry, "content.app")
    return str(app) if app else None


def _truthy(value: Any) -> bool:
    """Splunk writes its yes as true, 1 or "1"."""
    return value is True or value == 1 or str(value).strip().lower() in ("1", "true")


def _from_epoch(value: Any) -> str | None:
    """A fired alert's trigger time: seconds since the epoch."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat()
