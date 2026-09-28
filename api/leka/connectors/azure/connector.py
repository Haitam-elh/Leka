"""The Azure connector — one Microsoft Entra tenant, read-only (LEKA-347).

test_connection: a token for the service principal (client credentials),
the subscriptions it can see and whether the ones in scope are among them,
then — in the first subscription of the scope — whether it can list the
resources: the Reader role opens them all at once, so one call answers for
every kind.

check_health: a token and the subscription list — what fails first when a
secret expires or a role assignment is removed.

list_scope: the subscriptions the service principal can see.

iter_resources: each capability in every subscription of the scope, from
Azure Resource Manager's resource list filtered by type, following
`nextLink`. Every resource is known by its ARM id, lower-cased — Azure's ids
are case-insensitive, and the same resource must not be two records. Azure
has no "changed since" here: every capability is `listed_whole`.

LEKA READS. Every call to Azure Resource Manager is a GET. The one POST is
the token request to Microsoft's identity platform — an exchange of the
service principal's secret for a token, which touches nothing of the
customer's. The Reader role is all it needs (docs/connectors/cloud.md).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from leka.connectors import microsoft
from leka.connectors.base import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    HealthResult,
    ScopeListing,
    ScopeOption,
)
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.http import (
    Item,
    VendorHttp,
    record,
    refusal,
    retry_after,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

ARM = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
SUBSCRIPTIONS_API = "2022-12-01"
RESOURCES_API = "2021-04-01"
PAGE_SIZE = 1000  # ARM's $top ceiling for the resource list
UUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")

# What each capability is, in Azure's resource types.
TYPES: dict[Capability, tuple[str, ...]] = {
    Capability.INSTANCES: (
        "Microsoft.Compute/virtualMachines",
        "Microsoft.Compute/virtualMachineScaleSets",
    ),
    Capability.DB_INSTANCES: (
        "Microsoft.Sql/servers/databases",
        "Microsoft.DBforPostgreSQL/flexibleServers",
        "Microsoft.DBforMySQL/flexibleServers",
        "Microsoft.DocumentDB/databaseAccounts",
    ),
    Capability.BUCKETS: ("Microsoft.Storage/storageAccounts",),
    Capability.FUNCTIONS: ("Microsoft.Web/sites",),
    Capability.CLUSTERS: ("Microsoft.ContainerService/managedClusters",),
    Capability.NETWORKS: ("Microsoft.Network/virtualNetworks",),
    Capability.LOAD_BALANCERS: (
        "Microsoft.Network/loadBalancers",
        "Microsoft.Network/applicationGateways",
    ),
}
CLOUD_CAPABILITIES = frozenset(TYPES)


class AzureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(
        description="The Microsoft Entra tenant (directory) id of the service principal."
    )
    subscriptions: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="The subscription ids to read. Empty: every subscription it can see.",
    )

    @model_validator(mode="after")
    def _ids_are_ids(self) -> AzureConfig:
        for value in (self.tenant_id, *(self.subscriptions or [])):
            if not UUID.match(value):
                msg = f"{value!r} is not an Azure id like '00000000-0000-0000-0000-000000000000'"
                raise ValueError(msg)
        return self


class AzureCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First: the stored hint is taken from the first field — the application
    # id names the service principal, and says nothing of the secret.
    client_id: str = Field(
        min_length=36, max_length=36, description="The service principal's application id."
    )
    client_secret: SecretStr = Field(
        min_length=8,
        max_length=512,
        description="Its client secret.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class AzureConnector(Connector[AzureConfig, AzureCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.AZURE,
        display_name="Microsoft Azure",
        category=ConnectorCategory.CLOUD,
        auth_type="token",
        config_schema=AzureConfig,
        credentials_schema=AzureCredentials,
        capabilities=CLOUD_CAPABILITIES,
        listed_whole=CLOUD_CAPABILITIES,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._token: str | None = None

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with await self._client() as client:
            visible = await self._subscriptions(client)
            scope = self.config.subscriptions or [str(s["subscriptionId"]) for s in visible]
            known = {str(s["subscriptionId"]).lower() for s in visible}
            missing = sorted(s for s in scope if s.lower() not in known)
            if missing:
                raise diagnose(
                    DiagnosticCode.NOT_FOUND,
                    message="Le service principal ne voit pas ces abonnements : "
                    f"{', '.join(missing)}. Vérifiez qu'il y a le rôle Reader.",
                    secrets=self._secrets(),
                )
            capabilities: list[Capability] = []
            if scope:
                # Reader opens the whole resource list at once: one light call
                # says whether it is readable, for every kind of resource.
                readable = await client.probe(
                    {Capability.INSTANCES: _resources_path(scope[0])},
                    params={"api-version": RESOURCES_API, "$top": 1},
                )
                capabilities = sorted(TYPES) if readable else []
            warnings = (
                [] if scope else ["Aucun abonnement n'est visible avec ce service principal."]
            )
        return ConnectionTestResult(
            account=self.config.tenant_id,
            metadata={"tenant": self.config.tenant_id, "subscriptions_in_scope": len(scope)},
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with await self._client() as client:
            await self._subscriptions(client)
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        async with await self._client() as client:
            visible = await self._subscriptions(client)
        return ScopeListing(
            options=[
                ScopeOption(
                    key=str(s["subscriptionId"]),
                    name=str(s.get("displayName") or s["subscriptionId"]),
                    description=str(s.get("state") or "") or None,
                )
                for s in sorted(visible, key=lambda s: str(s.get("displayName", "")))
            ]
        )

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        """`since` is not used: Azure lists these whole, and says so in the manifest."""
        types = TYPES[capability]
        async with await self._client() as client:
            scope = self.config.subscriptions or [
                str(s["subscriptionId"]) for s in await self._subscriptions(client)
            ]
            query = {
                "api-version": RESOURCES_API,
                "$filter": " or ".join(f"resourceType eq '{t}'" for t in types),
            }
            for subscription in scope:
                async for resource in client.pages(_resources_path(subscription), query):
                    yield record(
                        capability,
                        resource,
                        external_id=str(resource["id"]).lower(),
                        container=subscription,
                    )

    # ── inside ───────────────────────────────────────────────────────────────

    async def _client(self) -> VendorHttp:
        token = await self._access_token()
        return VendorHttp(
            self.http(ARM, headers={"Authorization": f"Bearer {token}", "User-Agent": "LEKA"}),
            secret=self.credentials.client_secret.get_secret_value(),
            refuse=self._refuse,
            page_size=PAGE_SIZE,
            page_size_param="$top",
            in_body=("value", "nextLink"),
        )

    async def _access_token(self) -> str:
        """The client-credentials token, once per connector
        (leka/connectors/microsoft.py). The only POST: to Microsoft's
        identity platform, never to the customer's resources."""
        if self._token is None:
            self._token = await microsoft.client_credentials_token(
                self.http,
                self.config.tenant_id,
                self.credentials.client_id,
                self.credentials.client_secret.get_secret_value(),
                ARM_SCOPE,
            )
        return self._token

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Azure Resource Manager's answers, as diagnostics."""
        secret = self.credentials.client_secret.get_secret_value()
        code = usual_code(response.status_code)
        if code is DiagnosticCode.RATE_LIMITED:
            return refusal(response, path, secret, code, retry_after=retry_after(response))
        return refusal(response, path, secret, code)

    async def _subscriptions(self, client: VendorHttp) -> list[Item]:
        return [s async for s in client.pages("/subscriptions", {"api-version": SUBSCRIPTIONS_API})]

    def _secrets(self) -> list[str]:
        return [self.credentials.client_secret.get_secret_value()]


def _resources_path(subscription: str) -> str:
    return f"/subscriptions/{subscription}/resources"
