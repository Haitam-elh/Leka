"""The Google Cloud connector — the projects a service account can see (LEKA-347).

test_connection: a token for the service account (a JWT it signs itself,
exchanged at Google's token endpoint), the projects it can see and whether
the ones in scope are among them, then — in the first project of the scope —
whether Cloud Asset Inventory answers. It answers for every kind of resource
at once, or for none: the API is off in the project, or the role is missing.

check_health: a token and the project search.

list_scope: the projects the service account can see.

iter_resources: Cloud Asset Inventory's assets of the capability's types in
every project of the scope, following `nextPageToken`. Every asset is known
by its full resource name — '//compute.googleapis.com/projects/p/zones/z/
instances/i', unique across Google Cloud — with its project as container.
Google has no "changed since" here: every capability is `listed_whole`.
`accounts` is the projects themselves (LEKA-363): their names, labels,
state and parent — the folder or organisation they are in.

LEKA READS. Every call to Google Cloud's APIs is a GET, under the
`cloud-platform.read-only` scope. The one POST is the token exchange at
oauth2.googleapis.com, touching nothing of the customer's. The service
account needs Cloud Asset Viewer and Browser, nothing more
(docs/connectors/cloud.md).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from leka.connectors import google
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
from leka.connectors.http import Item, VendorHttp, record, refusal, retry_after, usual_code
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

READ_ONLY_SCOPE = "https://www.googleapis.com/auth/cloud-platform.read-only"
RESOURCE_MANAGER = "https://cloudresourcemanager.googleapis.com"
CLOUD_ASSET = "https://cloudasset.googleapis.com"
PAGE_SIZE = 1000  # Cloud Asset's ceiling
# A project id: 6 to 30 lowercase letters, digits and hyphens, starting with a letter.
PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")

# What each capability is, in Cloud Asset Inventory's asset types.
TYPES: dict[Capability, tuple[str, ...]] = {
    Capability.INSTANCES: ("compute.googleapis.com/Instance",),
    Capability.DB_INSTANCES: (
        "sqladmin.googleapis.com/Instance",
        "spanner.googleapis.com/Instance",
    ),
    Capability.BUCKETS: ("storage.googleapis.com/Bucket",),
    Capability.FUNCTIONS: (
        "cloudfunctions.googleapis.com/CloudFunction",
        "cloudfunctions.googleapis.com/Function",
        "run.googleapis.com/Service",
    ),
    Capability.CLUSTERS: ("container.googleapis.com/Cluster",),
    Capability.NETWORKS: ("compute.googleapis.com/Network",),
    Capability.LOAD_BALANCERS: (
        "compute.googleapis.com/ForwardingRule",
        "compute.googleapis.com/BackendService",
    ),
}
# The projects: what the resources are in.
CLOUD_CAPABILITIES = frozenset({*TYPES, Capability.ACCOUNTS})


class GcpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="The project ids to read. Empty: every project the service account can see.",
    )

    @model_validator(mode="after")
    def _ids_are_project_ids(self) -> GcpConfig:
        for project in self.projects or []:
            if not PROJECT.match(project):
                msg = f"{project!r} is not a project id like 'acme-prod'"
                raise ValueError(msg)
        return self


class GcpCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_account_key: SecretStr = Field(
        min_length=100,
        max_length=10_000,
        description="The service account's JSON key, as downloaded.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )

    @model_validator(mode="after")
    def _is_a_service_account_key(self) -> GcpCredentials:
        google.service_account_key(self.service_account_key.get_secret_value())
        return self


@register_connector
class GcpConnector(Connector[GcpConfig, GcpCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.GCP,
        display_name="Google Cloud",
        category=ConnectorCategory.CLOUD,
        auth_type="token",
        config_schema=GcpConfig,
        credentials_schema=GcpCredentials,
        capabilities=CLOUD_CAPABILITIES,
        listed_whole=CLOUD_CAPABILITIES,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._token: str | None = None

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        visible = await self._projects()
        scope = self.config.projects or [str(p["projectId"]) for p in visible]
        known = {str(p["projectId"]) for p in visible}
        missing = sorted(set(scope) - known)
        if missing:
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message="Le compte de service ne voit pas ces projets : "
                f"{', '.join(missing)}. Vérifiez ses rôles Browser et Cloud Asset Viewer.",
                secrets=self._secrets(),
            )
        capabilities: list[Capability] = []
        warnings: list[str] = []
        if scope:
            async with await self._client(CLOUD_ASSET) as assets:
                readable = await assets.probe(
                    {Capability.INSTANCES: f"/v1/projects/{scope[0]}/assets"},
                    params={"pageSize": 1, "contentType": "RESOURCE"},
                )
            capabilities = sorted(CLOUD_CAPABILITIES) if readable else []
            if not readable:
                warnings.append(
                    "Cloud Asset Inventory ne répond pas pour ce projet : activez l'API "
                    "cloudasset.googleapis.com et donnez le rôle Cloud Asset Viewer."
                )
        else:
            warnings.append("Aucun projet n'est visible avec ce compte de service.")
        return ConnectionTestResult(
            account=self._key()["client_email"],
            metadata={"projects_in_scope": len(scope)},
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        await self._projects()
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        return ScopeListing(
            options=[
                ScopeOption(
                    key=str(p["projectId"]),
                    name=str(p.get("displayName") or p["projectId"]),
                    description=str(p.get("state") or "") or None,
                )
                for p in sorted(await self._projects(), key=lambda p: str(p["projectId"]))
            ]
        )

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        """`since` is not used: Google lists these whole, and says so in the manifest."""
        visible = await self._projects()
        scope = self.config.projects or [str(p["projectId"]) for p in visible]
        if capability is Capability.ACCOUNTS:
            for found in visible:
                if str(found["projectId"]) in scope:
                    yield record(
                        capability,
                        found,
                        external_id=str(found["projectId"]),
                        updated=found.get("updateTime"),
                    )
            return
        query: dict[str, str | int | list[str]] = {
            "contentType": "RESOURCE",
            "assetTypes": list(TYPES[capability]),
        }
        async with await self._client(CLOUD_ASSET) as assets:
            for project in scope:
                async for asset in assets.pages(f"/v1/projects/{project}/assets", query):
                    yield record(
                        capability,
                        asset,
                        external_id=str(asset["name"]),
                        container=project,
                        updated=asset.get("updateTime"),
                    )

    # ── inside ───────────────────────────────────────────────────────────────

    async def _projects(self) -> list[Item]:
        async with await self._client(RESOURCE_MANAGER) as manager:
            return [p async for p in manager.pages("/v3/projects:search")]

    async def _client(self, base: str) -> VendorHttp:
        token = await self._access_token()
        return VendorHttp(
            self.http(base, headers={"Authorization": f"Bearer {token}", "User-Agent": "LEKA"}),
            secret=self._key()["private_key"],
            refuse=self._refuse,
            page_size=PAGE_SIZE,
            page_size_param="pageSize",
            in_body=("projects", "nextPageToken")
            if base == RESOURCE_MANAGER
            else ("assets", "nextPageToken"),
            page_cursor_param="pageToken",
        )

    def _key(self) -> dict[str, str]:
        return google.service_account_key(self.credentials.service_account_key.get_secret_value())

    async def _access_token(self) -> str:
        """A token for the service account, once per connector
        (leka/connectors/google.py) — the only POST, touching nothing of the
        customer's."""
        if self._token is None:
            self._token = await google.service_account_token(
                self.http, self._key(), READ_ONLY_SCOPE
            )
        return self._token

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Google Cloud's answers, as diagnostics."""
        secret = self._secrets()[0]
        code = usual_code(response.status_code)
        if code is DiagnosticCode.RATE_LIMITED:
            return refusal(response, path, secret, code, retry_after=retry_after(response))
        return refusal(response, path, secret, code)

    def _secrets(self) -> list[str]:
        return [self._key()["private_key"], self.credentials.service_account_key.get_secret_value()]
