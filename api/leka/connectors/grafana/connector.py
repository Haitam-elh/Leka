"""The Grafana connector — dashboards, alert rules with their state, annotations.

Grafana is read at the address the admin gives — Grafana Cloud
(https://acme.grafana.net) or a Grafana of their own — with a service
account's token, as Bearer. The service account needs Grafana's **Viewer**
role, nothing more: what a Viewer cannot see, LEKA cannot. Every call is a
GET, over https, to a public address only (leka/connectors/network.py): an
address that leads to LEKA's own network is refused when connecting.

test_connection: whose organisation (GET /api/org), and which of the three
this token can read — one small read each, a refusal leaving it out.

check_health: GET /api/org.

list_scope: none — the source's scope rules (docs/connectors/
scope-and-mapping.md) apply to each record's folder.

iter_resources: dashboards and alert rules come whole each pass;
annotations — the events Grafana keeps: deploys, alert state changes,
notes — from the last pass less a margin, newest first, at most
MAX_ANNOTATIONS a pass. A dashboard's or an alert rule's folder is its
container.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

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
from leka.connectors.http import Item, VendorHttp, dig, record, refusal, retry_after, usual_code
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.network import PublicHttpsUrl
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

C = Capability
SEARCH_PAGE = 5000  # Grafana's maximum
MAX_PAGES = 100
MAX_ANNOTATIONS = 10_000
# How far back an initial pass reads annotations.
ANNOTATIONS_HISTORY = timedelta(days=30)
# An annotation written while the last pass ran can carry a time before it.
ANNOTATION_MARGIN = timedelta(minutes=5)
RULES = "/api/prometheus/grafana/api/v1/rules"


class GrafanaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: PublicHttpsUrl = Field(
        description="The Grafana's address: https://acme.grafana.net, or one of your own.",
    )


class GrafanaCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr = Field(
        min_length=20,
        max_length=512,
        description="A service account's token (glsa_…), the account with the Viewer role.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class GrafanaConnector(Connector[GrafanaConfig, GrafanaCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.GRAFANA,
        display_name="Grafana",
        category=ConnectorCategory.OBSERVABILITY,
        auth_type="token",
        config_schema=GrafanaConfig,
        credentials_schema=GrafanaCredentials,
        capabilities=frozenset({C.DASHBOARDS, C.ALERTS, C.EVENTS}),
        # Dashboards and alert rules come whole; annotations by time.
        listed_whole=frozenset({C.DASHBOARDS, C.ALERTS}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            org = (await client.get("/api/org")).json()
            capabilities = await client.probe(
                {
                    C.DASHBOARDS: "/api/search?type=dash-db&limit=1",
                    C.ALERTS: RULES,
                    C.EVENTS: "/api/annotations?limit=1",
                }
            )
        warnings: list[str] = []
        if not capabilities:
            warnings.append(
                "Ce token ne peut rien lire : donnez au compte de service le rôle Viewer."
            )
        return ConnectionTestResult(
            account=str(org.get("name") or "Grafana"),
            metadata={"url": str(self.config.base_url)},
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            await client.get("/api/org")
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Grafana does not read {capability}"
            raise ValueError(msg)
        async with self._client() as client:
            if capability is C.DASHBOARDS:
                async for dashboard in self._dashboards(client):
                    yield record(
                        capability,
                        {**dashboard, "web_url": self._web(dashboard.get("url"))},
                        external_id=str(dashboard["uid"]),
                        container=_text(dashboard.get("folderTitle")),
                    )
            elif capability is C.ALERTS:
                async for rule, group in self._rules(client):
                    yield record(
                        capability,
                        {**rule, "group": group.get("name"), "folder": group.get("file")},
                        external_id=_rule_id(rule, group),
                        container=_text(group.get("file")),
                        updated=rule.get("lastEvaluation"),
                    )
            else:
                async for annotation in self._annotations(client, since):
                    yield record(
                        capability,
                        annotation,
                        external_id=str(annotation["id"]),
                        container=_text(annotation.get("dashboardUID")),
                        updated=_from_ms(annotation.get("updated") or annotation.get("time")),
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

    def _web(self, path: object) -> str | None:
        return str(self.config.base_url).rstrip("/") + str(path) if path else None

    async def _dashboards(self, client: VendorHttp) -> AsyncIterator[Item]:
        """Every dashboard, page after page of the search."""
        for page in range(1, MAX_PAGES + 1):
            response = await client.get(
                "/api/search", params={"type": "dash-db", "limit": SEARCH_PAGE, "page": page}
            )
            found = response.json()
            if not isinstance(found, list):
                return
            for dashboard in found:
                yield dashboard
            if len(found) < SEARCH_PAGE:
                return
        raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail="Grafana gave too many dashboards")

    async def _rules(self, client: VendorHttp) -> AsyncIterator[tuple[Item, Item]]:
        """Every Grafana-managed alert rule, with its group, as Grafana's
        Prometheus-compatible API gives them: with their state."""
        body = (await client.get(RULES)).json()
        for group in dig(body, "data.groups") or []:
            for rule in group.get("rules") or []:
                if rule.get("type", "alerting") == "alerting":
                    yield rule, group

    async def _annotations(self, client: VendorHttp, since: datetime | None) -> AsyncIterator[Item]:
        """Annotations since the last pass, newest first — Grafana gives no
        cursor, only a limit."""
        after = (since - ANNOTATION_MARGIN) if since else datetime.now(UTC) - ANNOTATIONS_HISTORY
        response = await client.get(
            "/api/annotations",
            params={
                "from": int(after.timestamp() * 1000),
                "to": int(datetime.now(UTC).timestamp() * 1000),
                "limit": MAX_ANNOTATIONS,
            },
        )
        found = response.json()
        for annotation in found if isinstance(found, list) else []:
            yield annotation

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Grafana's refusals, as diagnostics."""
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
            message = "Grafana refuse ce token de compte de service."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 403:
            message = (
                "Grafana refuse cette lecture : le compte de service doit avoir le rôle Viewer."
            )
            return refusal(
                response, path, secret, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        if status == 404:
            message = "Grafana ne trouve pas cette adresse : vérifiez l'adresse du Grafana."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        return refusal(response, path, secret, usual_code(status))


def _rule_id(rule: Item, group: Item) -> str:
    """A rule's uid, when Grafana gives it; its folder, group and name else."""
    uid = rule.get("uid")
    if uid:
        return str(uid)
    return f"{group.get('file')}/{group.get('name')}/{rule.get('name')}"


def _text(value: object) -> str | None:
    return str(value) if value else None


def _from_ms(value: Any) -> str | None:
    """Grafana's annotation times are milliseconds since the epoch."""
    if not isinstance(value, int | float) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()
