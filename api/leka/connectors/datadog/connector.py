"""The Datadog connector — monitors, events, incidents, metrics and logs.

Datadog is read at https://api.<site>, the site the organisation lives on
(datadoghq.com, datadoghq.eu, us3.datadoghq.com…), with an API key and an
application key. The application key should belong to a service account
with Datadog's read-only role and be scoped to the read permissions below:
what it may not read, LEKA cannot. Every call is a GET.

    alerts      monitors, with their overall state        monitors_read
    events      the event stream: alerts, deploys, …      events_read
    incidents   Datadog Incident Management               incident_read
    metrics     metric definitions, not their points      metrics_read
    logs        logs matching `logs_query`                logs_read_data

test_connection: is the API key valid (GET /api/v1/validate), whose is the
application key (GET /api/v2/current_user), and which of the five can it
read — each probed with one small read, a refusal leaving it out.

check_health: GET /api/v1/validate, reading Datadog's X-RateLimit-*.

list_scope: the services the organisation knows — its service catalog,
and the `service:` tags of its monitors.

iter_resources: monitors and incidents come whole each pass, so what a
pass did not see is gone; metrics too, at most MAX_METRICS, and left for the
weekly full pass to sweep, since a cut list must not sweep; events and logs
from the last pass (less a margin), newest first, at most MAX_EVENTS and
MAX_LOGS a pass. With `services`, each is read for those
services only. Every record keeps Datadog's own id and timestamp, and the
service it belongs to is its container.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

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
    quota_of,
    record,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

C = Capability
# Datadog's sites, as its API documents them.
SITES = (
    "datadoghq.com",
    "us3.datadoghq.com",
    "us5.datadoghq.com",
    "datadoghq.eu",
    "ap1.datadoghq.com",
    "ap2.datadoghq.com",
    "uk1.datadoghq.com",
    "ddog-gov.com",
    "us2.ddog-gov.com",
)
MONITOR_PAGE = 1000  # Datadog's maximum
STREAM_PAGE = 1000  # events and logs, Datadog's maximum
INCIDENT_PAGE = 100  # Datadog's maximum
METRIC_PAGE = 1000
CATALOG_PAGE = 100
MAX_PAGES = 1000
MAX_SCOPE_OPTIONS = 1000
# What a pass reads of the streams, newest first: narrow `logs_query` or the
# services when this is too little.
MAX_EVENTS = 50_000
MAX_LOGS = 10_000
MAX_METRICS = 20_000
# How far back an initial pass reads the streams. Datadog keeps events
# longer and logs as long as their index says; an initial pass is a start,
# not an archive.
EVENTS_HISTORY = timedelta(days=30)
LOGS_HISTORY = timedelta(days=1)
# Datadog indexes an event or a log a moment after it happened.
INDEXING_MARGIN = timedelta(minutes=5)
DEFAULT_LOGS_QUERY = "status:error"
LOW_QUOTA_RATIO = 0.1
SERVICE = re.compile(r"^[a-z0-9][a-z0-9_.:/-]{0,199}$")
# The permission each read needs, for the diagnostic that names it.
PERMISSIONS = {
    "/api/v1/monitor": "monitors_read",
    "/api/v2/events": "events_read",
    "/api/v2/incidents": "incident_read",
    "/api/v2/metrics": "metrics_read",
    "/api/v2/logs/events": "logs_read_data",
    "/api/v2/services/definitions": "apm_service_catalog_read",
}


def datadog_site(value: str) -> str:
    """The site, from what an admin typed or pasted — "datadoghq.eu", or
    the address of their Datadog, https://app.datadoghq.eu/dashboard/…
    Anything that is not one of Datadog's sites is refused: LEKA sends the
    keys to api.<site> and nowhere else."""
    text = value.strip().lower()
    text = re.sub(r"^[a-z]+://", "", text).split("/", 1)[0].split("?", 1)[0]
    text = re.sub(r"^(app|api)\.", "", text)
    if text not in SITES:
        msg = f"{value!r} is not a Datadog site like 'datadoghq.com' or 'datadoghq.eu'"
        raise ValueError(msg)
    return text


def app_host(site: str) -> str:
    """Where people open Datadog: app.datadoghq.com, but us3.datadoghq.com."""
    return site if re.match(r"^(us\d|ap\d|uk\d)\.", site) else f"app.{site}"


class DatadogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str = Field(
        default="datadoghq.com",
        max_length=100,
        description="The Datadog site of the organisation: datadoghq.com, datadoghq.eu, "
        "us3.datadoghq.com…",
    )
    logs_query: str = Field(
        default=DEFAULT_LOGS_QUERY,
        min_length=1,
        max_length=1000,
        description="Which logs to read, in Datadog's log search syntax.",
    )
    services: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="The services to read. Empty: all of them.",
    )

    @field_validator("site")
    @classmethod
    def _a_site(cls, value: str) -> str:
        return datadog_site(value)

    @field_validator("services")
    @classmethod
    def _names(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        names = [service.strip().lower().removeprefix("service:") for service in value]
        for name in names:
            if not SERVICE.match(name):
                msg = f"{name!r} is not a Datadog service name"
                raise ValueError(msg)
        return list(dict.fromkeys(names))


class DatadogCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First: the stored hint is taken from the first field.
    application_key: SecretStr = Field(
        min_length=20,
        max_length=100,
        description="An application key of a read-only service account, scoped to reading.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    api_key: SecretStr = Field(
        min_length=20,
        max_length=100,
        description="An API key of the organisation.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class DatadogConnector(Connector[DatadogConfig, DatadogCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.DATADOG,
        display_name="Datadog",
        category=ConnectorCategory.OBSERVABILITY,
        auth_type="token",
        config_schema=DatadogConfig,
        credentials_schema=DatadogCredentials,
        capabilities=frozenset({C.ALERTS, C.EVENTS, C.INCIDENTS, C.METRICS, C.LOGS}),
        # Monitors, incidents and metrics come whole; events and logs by date.
        listed_whole=frozenset({C.ALERTS, C.INCIDENTS}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            await client.get("/api/v1/validate", missing="api_key")
            me = (await client.get("/api/v2/current_user", missing="application_key")).json()
            capabilities = await client.probe(self._probes())
        warnings: list[str] = []
        if not capabilities:
            warnings.append(
                "Cette clé d'application ne peut rien lire : donnez-lui les permissions de "
                "lecture (monitors_read, events_read, incident_read, metrics_read, "
                "logs_read_data)."
            )
        attributes = dig(me, "data.attributes") or {}
        return ConnectionTestResult(
            account=str(attributes.get("email") or attributes.get("handle") or "Datadog"),
            metadata={"site": self.config.site, "services": self.config.services},
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            response = await client.get("/api/v1/validate", missing="api_key")
        quota = quota_of(response)
        low = quota is not None and quota.remaining < quota.limit * LOW_QUOTA_RATIO
        return HealthResult(
            status=HealthStatus.DEGRADED if low else HealthStatus.HEALTHY,
            detail=f"quota {quota.remaining}/{quota.limit}" if quota else None,
            checked_at=datetime.now(UTC),
        )

    async def list_scope(self) -> ScopeListing:
        found: dict[str, str] = {}
        async with self._client() as client:
            try:
                async for definition in self._catalog(client):
                    name = str(dig(definition, "attributes.schema.dd-service") or "").lower()
                    if name:
                        found.setdefault(name, "Catalogue de services")
            except ConnectorError as error:
                if error.diagnostic.code is not DiagnosticCode.PERMISSION_DENIED:
                    raise
            async for monitor in self._monitors(client):
                for name in _services_in(monitor.get("tags")):
                    found.setdefault(name, "Tag des moniteurs")
        names = sorted(found)
        options = [
            ScopeOption(key=name, name=name, description=found[name])
            for name in names[:MAX_SCOPE_OPTIONS]
        ]
        return ScopeListing(options=options, truncated=len(names) > MAX_SCOPE_OPTIONS)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Datadog does not read {capability}"
            raise ValueError(msg)
        reads = {
            C.ALERTS: self._alerts,
            C.EVENTS: self._events,
            C.INCIDENTS: self._incidents,
            C.METRICS: self._metrics,
            C.LOGS: self._logs,
        }
        async with self._client() as client:
            async for found in reads[capability](client, since):
                yield found

    # ── what is read ─────────────────────────────────────────────────────────

    async def _alerts(self, client: VendorHttp, since: datetime | None) -> AsyncIterator[RawRecord]:
        async for monitor in self._monitors(client):
            services = _services_in(monitor.get("tags"))
            if not self._wanted(services):
                continue
            payload = {**monitor, "web_url": self._web(f"/monitors/{monitor['id']}")}
            yield record(
                C.ALERTS,
                payload,
                external_id=str(monitor["id"]),
                container=services[0] if services else None,
                updated=monitor.get("modified"),
            )

    async def _events(self, client: VendorHttp, since: datetime | None) -> AsyncIterator[RawRecord]:
        after = (since - INDEXING_MARGIN) if since else datetime.now(UTC) - EVENTS_HISTORY
        params: dict[str, str | int] = {
            "filter[from]": str(int(after.timestamp() * 1000)),
            "filter[to]": "now",
            "sort": "-timestamp",
        }
        query = self._service_query()
        if query:
            params["filter[query]"] = query
        async for event in self._stream(client, "/api/v2/events", params, MAX_EVENTS):
            attributes = dig(event, "attributes.attributes") or {}
            service = attributes.get("service") or next(
                iter(_services_in(dig(event, "attributes.tags"))), None
            )
            yield record(
                C.EVENTS,
                event,
                external_id=str(event["id"]),
                container=str(service) if service else None,
                updated=dig(event, "attributes.timestamp"),
            )

    async def _incidents(
        self, client: VendorHttp, since: datetime | None
    ) -> AsyncIterator[RawRecord]:
        offset = 0
        for _ in range(MAX_PAGES):
            response = await client.get(
                "/api/v2/incidents",
                params={"page[size]": INCIDENT_PAGE, "page[offset]": offset, "include": "users"},
            )
            body = response.json()
            people = {
                str(user["id"]): user.get("attributes") or {}
                for user in body.get("included") or []
                if isinstance(user, dict) and user.get("type") == "users"
            }
            incidents = body.get("data") or []
            for incident in incidents:
                services = _incident_services(incident)
                if not self._wanted(services):
                    continue
                public_id = dig(incident, "attributes.public_id")
                payload: Item = {
                    **incident,
                    "people": {
                        role: people.get(str(dig(incident, f"relationships.{role}.data.id")))
                        for role in ("commander_user", "created_by_user")
                    },
                    "web_url": self._web(f"/incidents/{public_id}") if public_id else None,
                }
                yield record(
                    C.INCIDENTS,
                    payload,
                    external_id=str(incident["id"]),
                    container=services[0] if services else None,
                    updated=dig(incident, "attributes.modified"),
                )
            following = dig(body, "meta.pagination.next_offset")
            if not incidents or not isinstance(following, int) or following <= offset:
                return
            offset = following
            client.spare_the_quota(response)
        raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail="Datadog gave too many incident pages")

    async def _metrics(
        self, client: VendorHttp, since: datetime | None
    ) -> AsyncIterator[RawRecord]:
        params: dict[str, str | int] = {"page[size]": METRIC_PAGE}
        if self.config.services:
            params["filter[tags]"] = " OR ".join(f"service:{s}" for s in self.config.services)
        given = 0
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            response = await client.get("/api/v2/metrics", params=params)
            body = response.json()
            for metric in body.get("data") or []:
                if given == MAX_METRICS:
                    return
                given += 1
                yield record(
                    C.METRICS,
                    metric,
                    external_id=str(metric["id"]),
                    updated=dig(metric, "attributes.modified_at"),
                )
            cursor = dig(body, "meta.pagination.next_cursor")
            if not cursor:
                return
            if cursor in seen:
                raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail="Datadog repeated a cursor")
            seen.add(str(cursor))
            params = {**params, "page[cursor]": str(cursor)}
            client.spare_the_quota(response)
        raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail="Datadog gave too many metric pages")

    async def _logs(self, client: VendorHttp, since: datetime | None) -> AsyncIterator[RawRecord]:
        after = (since - INDEXING_MARGIN) if since else datetime.now(UTC) - LOGS_HISTORY
        query = self.config.logs_query
        services = self._service_query()
        if services:
            query = f"({query}) {services}"
        params: dict[str, str | int] = {
            "filter[query]": query,
            "filter[from]": after.astimezone(UTC).isoformat(),
            "filter[to]": "now",
            "sort": "-timestamp",
        }
        async for log in self._stream(client, "/api/v2/logs/events", params, MAX_LOGS):
            service = dig(log, "attributes.service")
            yield record(
                C.LOGS,
                {**log, "web_url": self._web("/logs?" + urlencode({"event": str(log["id"])}))},
                external_id=str(log["id"]),
                container=str(service) if service else None,
                updated=dig(log, "attributes.timestamp"),
            )

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        application_key = self.credentials.application_key.get_secret_value()
        client = self.http(
            f"https://api.{self.config.site}",
            headers={
                "Accept": "application/json",
                "User-Agent": "LEKA",
                "DD-API-KEY": self.credentials.api_key.get_secret_value(),
                "DD-APPLICATION-KEY": application_key,
            },
        )
        return VendorHttp(client, secret=application_key, refuse=self._refuse, page_size=0)

    def _probes(self) -> dict[Capability, str]:
        """One small read per capability, in scope."""
        logs = self.config.logs_query
        return {
            C.ALERTS: "/api/v1/monitor?" + urlencode({"page": 0, "page_size": 1}),
            C.EVENTS: "/api/v2/events?"
            + urlencode({"page[limit]": 1, "filter[from]": "now-1h", "filter[to]": "now"}),
            C.INCIDENTS: "/api/v2/incidents?" + urlencode({"page[size]": 1}),
            C.METRICS: "/api/v2/metrics?" + urlencode({"page[size]": 1}),
            C.LOGS: "/api/v2/logs/events?"
            + urlencode({"page[limit]": 1, "filter[from]": "now-15m", "filter[query]": logs}),
        }

    async def _monitors(self, client: VendorHttp) -> AsyncIterator[Item]:
        """Every monitor, page after page."""
        for page in range(MAX_PAGES):
            response = await client.get(
                "/api/v1/monitor", params={"page": page, "page_size": MONITOR_PAGE}
            )
            monitors = response.json()
            if not isinstance(monitors, list):
                return
            for monitor in monitors:
                yield monitor
            if len(monitors) < MONITOR_PAGE:
                return
            client.spare_the_quota(response)
        raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail="Datadog gave too many monitor pages")

    async def _catalog(self, client: VendorHttp) -> AsyncIterator[Item]:
        """The service catalog's definitions, page after page."""
        for page in range(MAX_PAGES):
            response = await client.get(
                "/api/v2/services/definitions",
                params={"page[size]": CATALOG_PAGE, "page[number]": page},
            )
            definitions = response.json().get("data") or []
            for definition in definitions:
                yield definition
            if len(definitions) < CATALOG_PAGE:
                return

    async def _stream(
        self, client: VendorHttp, path: str, params: Params, cap: int
    ) -> AsyncIterator[Item]:
        """Events or logs, newest first, following Datadog's cursor — at most
        `cap` of them."""
        query: dict[str, Any] = {**params, "page[limit]": STREAM_PAGE}
        given = 0
        seen: set[str] = set()
        while True:
            response = await client.get(path, params=query)
            body = response.json()
            for item in body.get("data") or []:
                if given == cap:
                    return
                given += 1
                yield item
            cursor = dig(body, "meta.page.after")
            if not cursor or not body.get("data"):
                return
            if cursor in seen:
                raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail="Datadog repeated a cursor")
            seen.add(str(cursor))
            query = {**query, "page[cursor]": str(cursor)}
            client.spare_the_quota(response)

    def _wanted(self, services: list[str]) -> bool:
        """In scope: every record when no service is chosen; else one of its
        services is."""
        if not self.config.services:
            return True
        return any(service in self.config.services for service in services)

    def _service_query(self) -> str | None:
        if not self.config.services:
            return None
        return "service:(" + " OR ".join(self.config.services) + ")"

    def _web(self, path: str) -> str:
        return f"https://{app_host(self.config.site)}{path}"

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Datadog's refusals, as diagnostics. A 403 means a key refused —
        the API key at /validate, the application key at /current_user — or
        a permission the application key lacks, named."""
        status = response.status_code
        route = path.split("?", 1)[0]
        if status == 429:
            return self._diagnostic(
                response,
                path,
                DiagnosticCode.RATE_LIMITED,
                retry_after=_reset(response),
            )
        if status in (401, 403) and missing == "api_key":
            message = "Datadog refuse cette clé d'API (ou ce site : vérifiez-le)."
            return self._diagnostic(response, path, DiagnosticCode.AUTH_INVALID, message=message)
        if status in (401, 403) and missing == "application_key":
            message = "Datadog refuse cette clé d'application."
            return self._diagnostic(response, path, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 401:
            return self._diagnostic(response, path, DiagnosticCode.AUTH_INVALID)
        if status == 403:
            needed = next((p for r, p in PERMISSIONS.items() if route.startswith(r)), None)
            message = (
                f"La clé d'application n'a pas la permission {needed}."
                if needed
                else "La clé d'application n'a pas la permission de lire ceci."
            )
            return self._diagnostic(
                response, path, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        return self._diagnostic(response, path, usual_code(status))

    def _diagnostic(
        self,
        response: httpx.Response,
        path: str,
        code: DiagnosticCode,
        *,
        message: str | None = None,
        retry_after: int | None = None,
    ) -> ConnectorError:
        """A refusal's diagnostic, its detail cleaned of both keys."""
        return diagnose(
            code,
            message=message,
            provider_status=response.status_code,
            retry_after=retry_after,
            detail=f"GET {path} → {response.status_code}: {response.text[:200]}",
            secrets=[
                self.credentials.api_key.get_secret_value(),
                self.credentials.application_key.get_secret_value(),
            ],
        )


def _services_in(tags: object) -> list[str]:
    """The services a list of tags names: 'service:checkout' → checkout."""
    if not isinstance(tags, list):
        return []
    found = [str(tag)[len("service:") :].lower() for tag in tags if str(tag).startswith("service:")]
    return list(dict.fromkeys(found))


def _incident_services(incident: Mapping[str, Any]) -> list[str]:
    """The services an incident names, in its `services` field."""
    value = dig(incident, "attributes.fields.services.value")
    if isinstance(value, list):
        return [str(service).lower() for service in value if service]
    return [str(value).lower()] if isinstance(value, str) and value else []


def _reset(response: httpx.Response) -> int | None:
    """Seconds until Datadog takes calls again: its X-RateLimit-Reset is in
    seconds from now; Retry-After when it says that instead."""
    for header in ("x-ratelimit-reset", "retry-after"):
        value = response.headers.get(header)
        if value and value.isdigit():
            return int(value)
    return None
