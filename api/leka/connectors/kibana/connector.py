"""The Kibana connector — alert rules, cases, dashboards, space by space.

Kibana is read at the address the admin gives — Elastic Cloud
(https://acme.kb.europe-west1.gcp.cloud.es.io) or a Kibana of their own —
with an Elastic API key, its encoded form sent as `ApiKey`. The key needs
read access to the three — Kibana's alerting rules, Cases and Dashboards
features — in the spaces to read, and nothing more: what it cannot see,
LEKA cannot. Every call is a GET, over https, to a public address only
(leka/connectors/network.py).

    alerts      every alerting rule: its type, its tags, whether it is on,
                how its last run went
    incidents   the cases — Kibana's incidents: title, status, severity,
                tags, who opened them, when they changed and closed
    dashboards  every dashboard: its title and description

test_connection: which Kibana (GET /api/status), and which of the three
the key can read in the default space — one small read each, a refusal
leaving it out.

check_health: GET /api/status.

list_scope: none — the source's scope rules (docs/connectors/
scope-and-mapping.md) apply to each record's container: its space.

iter_resources: every space the key sees (GET /api/spaces/space — a Kibana
without spaces is its default space), and in each, the three listed whole,
page after page.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import quote

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
DEFAULT_SPACE = "default"
# Kibana's public API version, which serverless projects ask for.
API_VERSION = "2023-10-31"
# Where a case is opened, by the solution that owns it.
CASE_APPS = {
    "securitySolution": "/app/security/cases",
    "observability": "/app/observability/cases",
}
GENERAL_CASES = "/app/management/insightsAndAlerting/cases"


class KibanaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: PublicHttpsUrl = Field(
        description="The Kibana's address: https://acme.kb.europe-west1.gcp.cloud.es.io, "
        "or one of your own.",
    )


class KibanaCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(
        min_length=20,
        max_length=1024,
        description="An Elastic API key, in its encoded form, with read access to "
        "alerting rules, cases and dashboards.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class KibanaConnector(Connector[KibanaConfig, KibanaCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.KIBANA,
        display_name="Kibana",
        category=ConnectorCategory.OBSERVABILITY,
        auth_type="token",
        config_schema=KibanaConfig,
        credentials_schema=KibanaCredentials,
        capabilities=frozenset({C.ALERTS, C.INCIDENTS, C.DASHBOARDS}),
        listed_whole=frozenset({C.ALERTS, C.INCIDENTS, C.DASHBOARDS}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            status = (await client.get("/api/status")).json()
            capabilities = await client.probe(
                {
                    C.ALERTS: "/api/alerting/rules/_find?per_page=1",
                    C.INCIDENTS: "/api/cases/_find?perPage=1",
                    C.DASHBOARDS: "/api/saved_objects/_find?type=dashboard&per_page=1",
                }
            )
        warnings: list[str] = []
        if not capabilities:
            warnings.append(
                "Cette clé ne peut rien lire : donnez-lui la lecture des règles d'alerte, des "
                "cas et des tableaux de bord dans les espaces à lire."
            )
        return ConnectionTestResult(
            account=str(status.get("name") or "Kibana"),
            metadata={
                "url": str(self.config.base_url),
                "version": dig(status, "version.number"),
            },
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            await client.get("/api/status")
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Kibana does not read {capability}"
            raise ValueError(msg)
        async with self._client() as client:
            for space in await self._spaces(client):
                prefix = space_prefix(space)
                if capability is C.ALERTS:
                    async for rule in self._pages(
                        client, f"{prefix}/api/alerting/rules/_find", "data", {}
                    ):
                        url = f"{prefix}/app/management/insightsAndAlerting/triggersActions"
                        yield self._record(capability, rule, space, f"{url}/rule/{rule['id']}")
                elif capability is C.INCIDENTS:
                    newest: Params = {"sortField": "updatedAt", "sortOrder": "desc"}
                    async for case in self._pages(
                        client, f"{prefix}/api/cases/_find", "cases", newest, size="perPage"
                    ):
                        app = CASE_APPS.get(str(case.get("owner")), GENERAL_CASES)
                        yield self._record(capability, case, space, f"{prefix}{app}/{case['id']}")
                else:
                    dashboards: Params = {"type": "dashboard", "fields": ["title", "description"]}
                    async for dashboard in self._pages(
                        client, f"{prefix}/api/saved_objects/_find", "saved_objects", dashboards
                    ):
                        url = f"{prefix}/app/dashboards#/view/{dashboard['id']}"
                        yield self._record(capability, dashboard, space, url)

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.api_key.get_secret_value()
        client = self.http(
            str(self.config.base_url).rstrip("/"),
            headers={
                "Accept": "application/json",
                "User-Agent": "LEKA",
                "Authorization": f"ApiKey {secret}",
                "elastic-api-version": API_VERSION,
            },
        )
        return VendorHttp(client, secret=secret, refuse=self._refuse, page_size=0)

    def _record(self, capability: Capability, item: Item, space: str, path: str) -> RawRecord:
        """A record of a space: its id within it, the space its container,
        and where to open it."""
        base = str(self.config.base_url).rstrip("/")
        return record(
            capability,
            {**item, "space": space, "web_url": base + path},
            external_id=f"{space}/{item['id']}",
            container=space,
            updated=item.get("updated_at") or item.get("created_at"),
        )

    async def _spaces(self, client: VendorHttp) -> list[str]:
        """The spaces the key sees — the default one alone where Kibana has
        no spaces, or the key may not list them."""
        response = await client.get_if_answered("/api/spaces/space")
        found = response.json() if response is not None else None
        spaces = (
            [str(s["id"]) for s in found if isinstance(s, dict) and s.get("id")]
            if isinstance(found, list)
            else []
        )
        return spaces or [DEFAULT_SPACE]

    async def _pages(
        self,
        client: VendorHttp,
        path: str,
        field: str,
        params: Params,
        *,
        size: str = "per_page",
    ) -> AsyncIterator[Item]:
        """Every item of a listing, page after page, until its `total`."""
        given = 0
        for page in range(1, MAX_PAGES + 1):
            response = await client.get(path, params={**params, size: PAGE_SIZE, "page": page})
            body = response.json()
            items = body.get(field) or [] if isinstance(body, dict) else []
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    yield item
            given += len(items)
            total = body.get("total") if isinstance(body, dict) else None
            if not items or not isinstance(total, int) or given >= total:
                return
        raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail=f"Kibana gave too many pages: {path}")

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Kibana's refusals, as diagnostics."""
        secret = self.credentials.api_key.get_secret_value()
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
            message = "Kibana refuse cette clé d'API."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 403:
            message = (
                "Kibana refuse cette lecture : la clé doit pouvoir lire les règles d'alerte, "
                "les cas et les tableaux de bord de cet espace."
            )
            return refusal(
                response, path, secret, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        if status == 404:
            message = "Kibana ne trouve pas cette adresse : vérifiez l'adresse du Kibana."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        return refusal(response, path, secret, usual_code(status))


def space_prefix(space: str) -> str:
    """Where a space's API and pages are: none for the default one."""
    return "" if space == DEFAULT_SPACE else f"/s/{quote(space, safe='')}"
