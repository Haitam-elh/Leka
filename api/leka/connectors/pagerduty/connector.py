"""The PagerDuty connector — its services, what they depend on, and their
incidents.

PagerDuty is read at https://api.pagerduty.com (or api.eu.pagerduty.com for
an account in its EU service region) with a REST API key, sent as
`Token token=…`. PagerDuty lets an admin make that key **read-only**; the
documentation asks for one. Every call is a GET.

test_connection: may this key read the account (GET /abilities), are the
services in scope among the account's (GET /services), and can it read
their incidents (one page).

check_health: GET /abilities, reading PagerDuty's ratelimit-* headers.

list_scope: every service of the account.

iter_resources: services, whole each pass, each with the services it
depends on (GET /service_dependencies/technical_services/{id}); the business
services too — what the company's applications are to PagerDuty — each with
the services that support it (…/business_services/{id}), those supporting a
service in scope when there is a scope (LEKA-362). Teams (LEKA-365), whole
each pass: each with its members — their name, address and role, a manager
leading it — and its parent team where the account has team hierarchy; a
key that may not read teams leaves them out. An account whose plan or
key does not show dependencies or business services is read without them.
Incidents created in the last
INCIDENT_WINDOW, every pass — PagerDuty lists incidents by when they were
created, not when they last changed, so a pass reads the whole window
again and an incident that changed in it is read again. With `services`,
only theirs. An incident's service is its container.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

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
    Params,
    VendorHttp,
    dig,
    parse_timestamp,
    quota_of,
    record,
    refusal,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

C = Capability
HOSTS = {"us": "https://api.pagerduty.com", "eu": "https://api.eu.pagerduty.com"}
ACCEPT = "application/vnd.pagerduty+json;version=2"
PAGE_SIZE = 100  # PagerDuty's maximum
MAX_PAGES = 1000
MAX_SCOPE_OPTIONS = 1000
# How far back each pass reads incidents: PagerDuty allows six months at
# most, and an incident rarely changes three months after it was opened.
INCIDENT_WINDOW = timedelta(days=90)
LOW_QUOTA_RATIO = 0.1
# One read per service for its dependencies: past this many a pass, the
# rest are read without them.
MAX_DEPENDENCY_READS = 2000
# What a plan or a key without dependencies or business services answers.
UNAVAILABLE = frozenset({DiagnosticCode.PERMISSION_DENIED, DiagnosticCode.NOT_FOUND})
SERVICE_ID = re.compile(r"^P[A-Z0-9]{6,13}$")


class PagerDutyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: Literal["us", "eu"] = Field(
        default="us", description="The account's service region: us, or eu."
    )
    services: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Ids of the services to read (PXXXXXX). Empty: every service.",
    )

    @field_validator("region", mode="before")
    @classmethod
    def _a_region(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("services")
    @classmethod
    def _ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        ids = [service.strip().upper().rstrip("/").rsplit("/", 1)[-1] for service in value]
        for service in ids:
            if not SERVICE_ID.match(service):
                msg = f"{service!r} is not the id of a PagerDuty service, like 'PXXXXXX'"
                raise ValueError(msg)
        return list(dict.fromkeys(ids))


class PagerDutyCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(
        min_length=16,
        max_length=100,
        description="A read-only REST API key, from Integrations → API Access Keys.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class PagerDutyConnector(Connector[PagerDutyConfig, PagerDutyCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.PAGERDUTY,
        display_name="PagerDuty",
        category=ConnectorCategory.OBSERVABILITY,
        auth_type="token",
        config_schema=PagerDutyConfig,
        credentials_schema=PagerDutyCredentials,
        capabilities=frozenset({C.SERVICES, C.INCIDENTS, C.TEAMS}),
        # Services and teams come whole every pass; incidents by their
        # creation window.
        listed_whole=frozenset({C.SERVICES, C.TEAMS}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            abilities = (await client.get("/abilities", missing="api_key")).json()
            services = [s async for s in self._services(client)]
            self._require_scope(services)
            capabilities = [C.SERVICES]
            try:
                await client.get("/incidents", params=self._incident_params(limit=1))
                capabilities.append(C.INCIDENTS)
            except ConnectorError as error:
                if error.diagnostic.code is not DiagnosticCode.PERMISSION_DENIED:
                    raise
            if await self._optional_response(client, "/teams?limit=1") is not None:
                capabilities.append(C.TEAMS)
        warnings: list[str] = []
        if not services:
            warnings.append("Aucun service n'est visible avec cette clé.")
        return ConnectionTestResult(
            account="PagerDuty",
            metadata={
                "region": self.config.region,
                "services_visible": len(services),
                "abilities": len(abilities.get("abilities") or []),
            },
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            response = await client.get("/abilities", missing="api_key")
        quota = quota_of(response)
        low = quota is not None and quota.remaining < quota.limit * LOW_QUOTA_RATIO
        return HealthResult(
            status=HealthStatus.DEGRADED if low else HealthStatus.HEALTHY,
            detail=f"quota {quota.remaining}/{quota.limit}" if quota else None,
            checked_at=datetime.now(UTC),
        )

    async def list_scope(self) -> ScopeListing:
        async with self._client() as client:
            services = [s async for s in self._services(client)]
        options = [
            ScopeOption(
                key=str(service["id"]),
                name=str(service.get("name") or service["id"]),
                description=str(service.get("description") or "").strip() or None,
                updated_at=parse_timestamp(service.get("last_incident_timestamp")),
            )
            for service in services[:MAX_SCOPE_OPTIONS]
        ]
        return ScopeListing(options=options, truncated=len(services) > MAX_SCOPE_OPTIONS)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"PagerDuty does not read {capability}"
            raise ValueError(msg)
        async with self._client() as client:
            if capability is C.SERVICES:
                async for found in self._services_whole(client):
                    yield found
                return
            if capability is C.TEAMS:
                async for team in self._pages(client, "/teams", {}):
                    members = [
                        member
                        async for member in self._pages(
                            client,
                            f"/teams/{team['id']}/members",
                            {"include[]": "users"},
                            field="members",
                        )
                    ]
                    yield record(
                        capability,
                        {**team, "members": members},
                        external_id=str(team["id"]),
                    )
                return
            async for incident in self._pages(client, "/incidents", self._incident_params()):
                yield record(
                    capability,
                    incident,
                    external_id=str(incident["id"]),
                    container=dig(incident, "service.id"),
                    updated=incident.get("updated_at") or incident.get("last_status_change_at"),
                )

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.api_key.get_secret_value()
        client = self.http(
            HOSTS[self.config.region],
            headers={
                "Accept": ACCEPT,
                "User-Agent": "LEKA",
                "Authorization": f"Token token={secret}",
            },
        )
        return VendorHttp(client, secret=secret, refuse=self._refuse, page_size=PAGE_SIZE)

    def _incident_params(self, limit: int = PAGE_SIZE) -> dict[str, str | int | list[str]]:
        now = datetime.now(UTC)
        params: dict[str, str | int | list[str]] = {
            "since": (now - INCIDENT_WINDOW).isoformat(),
            "until": now.isoformat(),
            "limit": limit,
            "sort_by": "created_at:asc",
        }
        if self.config.services:
            params["service_ids[]"] = self.config.services
        return params

    async def _services(self, client: VendorHttp) -> AsyncIterator[Item]:
        async for service in self._pages(client, "/services", {"include[]": "teams"}):
            yield service

    async def _services_whole(self, client: VendorHttp) -> AsyncIterator[RawRecord]:
        """The services in scope, then the business services, each with
        what it depends on: `dependencies`, `[{id, name, type}]`, `type`
        `business` or `technical`."""
        wanted = set(self.config.services or [])
        services = [s async for s in self._services(client)]
        business = await self._optional(self._listing(client, "/business_services"))
        names = {str(item["id"]): str(item.get("name") or "") for item in (*services, *business)}
        reads = 0
        for service in services:
            if wanted and str(service["id"]) not in wanted:
                continue
            reads += 1
            dependencies = (
                await self._supporting(client, "technical_services", service, names)
                if reads <= MAX_DEPENDENCY_READS
                else []
            )
            yield record(
                C.SERVICES,
                {**service, "dependencies": dependencies},
                external_id=str(service["id"]),
                updated=service.get("updated_at"),
            )
        for item in business:
            reads += 1
            supporting = (
                await self._supporting(client, "business_services", item, names)
                if reads <= MAX_DEPENDENCY_READS
                else []
            )
            if wanted and not any(d["id"] in wanted for d in supporting):
                continue
            yield record(
                C.SERVICES,
                {**item, "type": "business_service", "dependencies": supporting},
                external_id=str(item["id"]),
                updated=item.get("updated_at"),
            )

    async def _supporting(
        self, client: VendorHttp, kind: str, dependent: Item, names: dict[str, str]
    ) -> list[dict[str, str]]:
        """What supports one service: its side of PagerDuty's dependency
        relationships, named from the listings."""
        identifier = str(dependent["id"])
        response = await self._optional_response(
            client, f"/service_dependencies/{kind}/{identifier}"
        )
        if response is None:
            return []
        found: dict[str, dict[str, str]] = {}
        for relationship in response.json().get("relationships") or []:
            if str(dig(relationship, "dependent_service.id")) != identifier:
                continue
            supporting = dig(relationship, "supporting_service") or {}
            other = str(supporting.get("id") or "")
            if not other or other == identifier:
                continue
            found[other] = {
                "id": other,
                "name": names.get(other) or other,
                "type": "business" if "business" in str(supporting.get("type")) else "technical",
            }
        return list(found.values())

    async def _listing(self, client: VendorHttp, path: str) -> list[Item]:
        return [item async for item in self._pages(client, path, {})]

    async def _optional(self, reading: Awaitable[list[Item]]) -> list[Item]:
        """A listing a plan or a key may not show: empty then."""
        try:
            found = await reading
        except ConnectorError as error:
            if error.diagnostic.code not in UNAVAILABLE:
                raise
            return []
        return found

    async def _optional_response(self, client: VendorHttp, path: str) -> httpx.Response | None:
        try:
            return await client.get(path)
        except ConnectorError as error:
            if error.diagnostic.code not in UNAVAILABLE:
                raise
            return None

    async def _pages(
        self, client: VendorHttp, path: str, params: Params, *, field: str | None = None
    ) -> AsyncIterator[Item]:
        """Every item of a listing, PagerDuty's offset after offset, while it
        says there are `more`. Its items are in the field the path names —
        `/teams` → `teams` — unless said."""
        field = field or path.strip("/")
        offset = 0
        for _ in range(MAX_PAGES):
            query: dict[str, Any] = {**params, "limit": PAGE_SIZE, "offset": offset}
            response = await client.get(path, params=query)
            body = response.json()
            found = body.get(field) or []
            for item in found:
                yield item
            if not body.get("more") or not found:
                return
            offset += len(found)
            client.spare_the_quota(response)
        raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail=f"PagerDuty gave too many {field}")

    def _require_scope(self, services: list[Item]) -> None:
        known = {str(service["id"]) for service in services}
        missing = [s for s in self.config.services or [] if s not in known]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"PagerDuty ne montre pas ces services à cette clé : {named}.",
            )

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """PagerDuty's refusals, as diagnostics."""
        secret = self.credentials.api_key.get_secret_value()
        status = response.status_code
        if status == 429:
            reset = response.headers.get("ratelimit-reset") or response.headers.get("retry-after")
            wait = int(reset) if reset and reset.isdigit() else None
            return refusal(response, path, secret, DiagnosticCode.RATE_LIMITED, retry_after=wait)
        if status == 401:
            message = "PagerDuty refuse cette clé d'API (ou cette région : vérifiez-la)."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 403:
            message = "PagerDuty refuse cette lecture à cette clé."
            return refusal(
                response, path, secret, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        return refusal(response, path, secret, usual_code(status))
