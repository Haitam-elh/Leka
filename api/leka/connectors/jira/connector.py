"""The Jira connector — Jira Cloud (<site>.atlassian.net), REST API v3.

test_connection: who am I (GET /myself — the account, and the time zone
JQL dates are read in), may this account administer Jira (GET
/mypermissions — a warning: LEKA only reads), are the projects in scope
there (GET /project/search?keys=…), what can I see (one page of projects),
and — on one project, in scope if a scope is set — can I search its issues
(GET /search/jql).

check_health: GET /myself. Healthy, or degraded when Atlassian says the
quota is nearly spent (X-RateLimit-NearLimit).

list_scope: every project the account can browse, for the admin to choose from.

iter_resources: the projects in scope — every project the account can
browse, unless `projects` names some — then, project by project, their
issues through JQL, oldest change first, with every field: comments, links
to other issues, parent, sprint. One JQL per project, so a search is always
bounded and each issue knows its project. An incremental pass asks for the
issues updated since the last one; JQL reads a date to the minute, in the
account's time zone, so it asks from a minute earlier — an issue seen twice
is a write, not a duplicate.

Jira Data Center is another API, not this one.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from leka.connectors import atlassian
from leka.connectors.atlassian import AtlassianCredentials
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
from leka.connectors.errors import DiagnosticCode, diagnose
from leka.connectors.http import Item, VendorHttp, parse_timestamp, record
from leka.connectors.models import SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

API = "/rest/api/3"
PAGE_SIZE = 50  # /project/search's maximum
ISSUE_PAGE = 100
KEYS_PER_CALL = 50  # /project/search takes at most fifty keys
MAX_SCOPE_OPTIONS = 1000
# What a project carries beyond its name: its description, and when an
# issue in it last changed.
EXPAND = "description,insight"
# A project key: a capital letter, then capitals, digits or "_".
KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,254}$")
# JQL reads a date to the minute: ask from a minute earlier.
JQL_MARGIN = timedelta(minutes=1)
# An account whose time zone Jira does not say: the widest offset there is.
UNKNOWN_ZONE_MARGIN = timedelta(hours=14)


class JiraConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str = Field(
        max_length=255,
        description="The Atlassian site: 'acme', as in acme.atlassian.net.",
    )
    projects: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Keys of the projects to read ('PAY'). "
        "Empty: every project the account can browse.",
    )
    issues: bool = Field(
        default=False,
        description="Allow LEKA to create the tickets a person accepted — new issues in the "
        "projects this source reads, never an edit. The account then needs Create issues there.",
    )

    @field_validator("site")
    @classmethod
    def _site_is_a_name(cls, value: str) -> str:
        return atlassian.site_name(value)

    @field_validator("projects")
    @classmethod
    def _keys_are_keys(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        keys = [key.strip().upper() for key in value]
        for key in keys:
            if not KEY.match(key):
                msg = f"{key!r} is not a project key like 'PAY'"
                raise ValueError(msg)
        return list(dict.fromkeys(keys))


class JiraCredentials(AtlassianCredentials):
    """An Atlassian account's API token, and the email it belongs to."""


@register_connector
class JiraConnector(Connector[JiraConfig, JiraCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.JIRA,
        display_name="Jira",
        category=ConnectorCategory.PROJECT,
        auth_type="token",
        config_schema=JiraConfig,
        credentials_schema=JiraCredentials,
        capabilities=frozenset({Capability.PROJECTS, Capability.ISSUES}),
        # Projects come whole every pass; issues by JQL `updated >=`.
        listed_whole=frozenset({Capability.PROJECTS}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            me = (await client.get("/myself", missing="ce site Atlassian")).json()
            metadata: dict[str, object] = {
                "site": f"{self.config.site}{atlassian.SUFFIX}",
                "timezone": me.get("timeZone"),
            }
            warnings = await self._admin_warnings(client)
            if self.config.projects:
                await self._require_scope(client)

            query: dict[str, str | int | list[str]] = {"maxResults": PAGE_SIZE}
            if self.config.projects:
                query["keys"] = self.config.projects[:KEYS_PER_CALL]
            first = (await client.get("/project/search", params=query)).json()
            listed = first.get("values", [])
            metadata["projects_visible"] = first.get("total", len(listed))
            capabilities = [Capability.PROJECTS] if listed else []
            if listed:
                # Probe what will be read: a project in scope, if one is set.
                capabilities += await client.probe(
                    {Capability.ISSUES: "/search/jql"},
                    params={"jql": _jql(str(listed[0]["key"])), "maxResults": 1, "fields": "id"},
                )
            else:
                warnings.append("Aucun projet n'est visible avec ce compte.")

        return ConnectionTestResult(
            account=str(me.get("displayName") or me.get("emailAddress") or self.credentials.email),
            metadata=metadata,
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            response = await client.get("/myself")
        return atlassian.health(response)

    async def list_scope(self) -> ScopeListing:
        options: list[ScopeOption] = []
        async with self._client() as client:
            async for project in client.pages("/project/search", {"expand": EXPAND}):
                if len(options) == MAX_SCOPE_OPTIONS:
                    return ScopeListing(options=options, truncated=True)
                insight = project.get("insight")
                options.append(
                    ScopeOption(
                        key=str(project["key"]),
                        name=str(project["name"]),
                        description=str(project["description"])
                        if project.get("description")
                        else None,
                        private=project.get("isPrivate") is True,
                        updated_at=parse_timestamp(insight.get("lastIssueUpdateTime"))
                        if isinstance(insight, dict)
                        else None,
                    )
                )
        return ScopeListing(options=options)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Jira does not read {capability}"
            raise ValueError(msg)
        async with self._client() as client:
            if capability is Capability.PROJECTS:
                async for project in self._projects(client):
                    # Its own key: what scope rules match it by (LEKA-351).
                    yield record(
                        capability,
                        project,
                        external_id=str(project["id"]),
                        container=str(project["key"]),
                    )
                return

            after = await self._jql_date(client, since) if since else None
            async for project in self._projects(client):
                key = str(project["key"])
                async for issue in self._issues(client, _jql(key, after)):
                    fields = issue.get("fields")
                    yield record(
                        capability,
                        issue,
                        external_id=str(issue["id"]),
                        container=key,
                        updated=fields.get("updated") if isinstance(fields, dict) else None,
                    )

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        client = self.http(
            atlassian.site_url(self.config.site) + API,
            headers=atlassian.headers(self.credentials),
        )
        return VendorHttp(
            client,
            secret=self.credentials.token.get_secret_value(),
            refuse=atlassian.refuser("Jira", self.credentials),
            page_size=PAGE_SIZE,
            page_size_param="maxResults",
            in_body=("values", "nextPage"),
        )

    async def _admin_warnings(self, client: VendorHttp) -> list[str]:
        """An account that administers Jira is more than LEKA needs. A Jira
        that does not answer this is not a failure of the test."""
        response = await client.get_if_answered("/mypermissions?permissions=ADMINISTER")
        if response is None:
            return []
        permission = response.json().get("permissions", {}).get("ADMINISTER", {})
        if not permission.get("havePermission"):
            return []
        return [
            "Ce compte administre Jira. LEKA ne fait que lire : un compte qui peut "
            "seulement consulter les projets suffit et limite l'exposition."
        ]

    async def _require_scope(self, client: VendorHttp) -> None:
        """Every project in scope must be one this account can see."""
        found = {str(project["key"]).upper() async for project in self._projects(client)}
        missing = [key for key in self.config.projects or [] if key not in found]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"Jira ne montre pas ces projets à ce compte : {named}.",
            )

    async def _projects(self, client: VendorHttp) -> AsyncIterator[Item]:
        """The projects in scope, as Jira describes them."""
        wanted = self.config.projects
        if not wanted:
            async for project in client.pages("/project/search", {"expand": EXPAND}):
                yield project
            return
        for start in range(0, len(wanted), KEYS_PER_CALL):
            keys = wanted[start : start + KEYS_PER_CALL]
            async for project in client.pages("/project/search", {"keys": keys, "expand": EXPAND}):
                yield project

    async def _issues(self, client: VendorHttp, jql: str) -> AsyncIterator[Item]:
        """Every issue a JQL finds, following Jira's page tokens."""
        params: dict[str, str | int] = {"jql": jql, "maxResults": ISSUE_PAGE, "fields": "*all"}
        seen: set[str] = set()
        while True:
            body = (await client.get("/search/jql", params=params)).json()
            for issue in body.get("issues", []):
                yield issue
            token = body.get("nextPageToken")
            if not token or body.get("isLast", False):
                return
            if token in seen:
                # A token Jira already gave: following it would never end.
                raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail="Jira repeated a page token")
            seen.add(token)
            params = {**params, "nextPageToken": str(token)}

    async def _jql_date(self, client: VendorHttp, since: datetime) -> str:
        """`since` as JQL reads a date: to the minute, in the account's zone."""
        me = (await client.get("/myself")).json()
        zone: tzinfo
        try:
            zone = ZoneInfo(str(me.get("timeZone")))
            moment = since - JQL_MARGIN
        except (ZoneInfoNotFoundError, ValueError):
            zone, moment = UTC, since - UNKNOWN_ZONE_MARGIN
        return moment.astimezone(zone).strftime("%Y/%m/%d %H:%M")


def _jql(key: str, after: str | None = None) -> str:
    """One project's issues, oldest change first.

    The key is quoted and escaped: it was checked against KEY when it came
    from the configuration, but a key Jira lists is Jira's to shape.
    """
    quoted = key.replace("\\", "\\\\").replace('"', '\\"')
    clause = f'project = "{quoted}"'
    if after:
        clause += f' AND updated >= "{after}"'
    return clause + " ORDER BY updated ASC"
