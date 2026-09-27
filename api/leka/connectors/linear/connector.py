"""The Linear connector — linear.app, through its GraphQL API.

Linear has one endpoint, POST https://api.linear.app/graphql, and speaks
only GraphQL. Every document this connector sends is below, as a constant,
and is a `query`: `read_only` refuses a `mutation` or a `subscription`
before it is sent, and a test runs it over every document here.

test_connection: who am I, in which workspace, may I administer it
(`viewer` — a warning: LEKA only reads), are the teams in scope there, what
can I see (one page of teams), and — in one team, in scope if a scope is
set — can I read its projects and its issues.

check_health: `viewer { id }`, reading the X-RateLimit-Requests-* headers
Linear sends with it. Healthy, or degraded under a tenth of the hour's
requests.

list_scope: every team the key can see, by its key.

iter_resources: the teams in scope — every team the key sees, unless
`teams` names some — then, team by team, their projects and their issues,
archived ones included, following Linear's cursors. An incremental pass
asks Linear for the issues updated since the last one; projects come whole,
each once even when several teams share it.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any

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
from leka.connectors.http import Item, VendorHttp, dig, parse_timestamp, record, refusal
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

API = "https://api.linear.app"
GRAPHQL = "/graphql"
PAGE_SIZE = 50
MAX_SCOPE_OPTIONS = 1000
LOW_QUOTA_RATIO = 0.1
# A team key: capitals and digits, as Linear shows it before an issue's number.
TEAM_KEY = re.compile(r"^[A-Z0-9_]{1,16}$")

# ── the documents: queries, nothing else ─────────────────────────────────────

VIEWER = """
query Viewer {
  viewer { id name displayName email admin organization { id name urlKey } }
}
"""

HEALTH = """
query Health { viewer { id } }
"""

TEAMS = """
query Teams($first: Int!, $after: String, $filter: TeamFilter) {
  teams(first: $first, after: $after, filter: $filter) {
    nodes { id key name description private createdAt updatedAt }
    pageInfo { hasNextPage endCursor }
  }
}
"""

TEAM_PROJECTS = """
query TeamProjects($team: String!, $first: Int!, $after: String) {
  team(id: $team) {
    projects(first: $first, after: $after, includeArchived: true) {
      nodes {
        id name description url slugId progress
        startDate targetDate createdAt updatedAt archivedAt completedAt canceledAt
        status { id name type }
        lead { id name email }
        teams(first: 10) { nodes { id key } }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

TEAM_ISSUES = """
query TeamIssues($team: String!, $first: Int!, $after: String, $filter: IssueFilter) {
  team(id: $team) {
    issues(
      first: $first, after: $after, filter: $filter, includeArchived: true, orderBy: updatedAt
    ) {
      nodes {
        id identifier title description priority priorityLabel estimate url dueDate
        createdAt updatedAt startedAt completedAt canceledAt archivedAt
        state { id name type }
        team { id key }
        project { id name }
        cycle { id number name }
        parent { id identifier }
        assignee { id name email }
        creator { id name email }
        labels(first: 20) { nodes { id name } }
        relations(first: 20) { nodes { id type relatedIssue { id identifier } } }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

DOCUMENTS = (VIEWER, HEALTH, TEAMS, TEAM_PROJECTS, TEAM_ISSUES)


def read_only(document: str) -> str:
    """The document, if it only reads: one `query`, no `mutation`, no
    `subscription`, not even in a comment."""
    text = re.sub(r"#[^\n]*", "", document).strip()
    if not text.startswith("query") or re.search(r"\b(mutation|subscription)\b", text):
        msg = "LEKA sends Linear queries only: no mutation, no subscription"
        raise ValueError(msg)
    return text


# ── configuration ────────────────────────────────────────────────────────────


class LinearConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teams: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Keys of the teams to read ('ENG'). Empty: every team the key can see.",
    )

    @field_validator("teams")
    @classmethod
    def _keys_are_keys(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        keys = [key.strip().upper() for key in value]
        for key in keys:
            if not TEAM_KEY.match(key):
                msg = f"{key!r} is not a team key like 'ENG'"
                raise ValueError(msg)
        return list(dict.fromkeys(keys))


class LinearCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(
        min_length=20,
        description="A personal API key (lin_api_…), from Settings → Security & access.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class LinearConnector(Connector[LinearConfig, LinearCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.LINEAR,
        display_name="Linear",
        category=ConnectorCategory.PROJECT,
        auth_type="token",
        config_schema=LinearConfig,
        credentials_schema=LinearCredentials,
        capabilities=frozenset({Capability.PROJECTS, Capability.ISSUES}),
        # Projects come whole every pass; issues filtered by `updatedAt`.
        listed_whole=frozenset({Capability.PROJECTS}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            viewer = dig(await self._query(client, VIEWER), "viewer") or {}
            organization = viewer.get("organization") or {}
            metadata: dict[str, object] = {
                "workspace": organization.get("name"),
                "url_key": organization.get("urlKey"),
            }
            warnings: list[str] = []
            if viewer.get("admin"):
                warnings.append(
                    "Cette clé appartient à un administrateur de l'espace Linear. LEKA ne fait "
                    "que lire : la clé d'un membre, limitée à la lecture, suffit."
                )
            if self.config.teams:
                await self._require_scope(client)

            first = dig(
                await self._query(
                    client, TEAMS, {"first": PAGE_SIZE, "after": None, "filter": self._filter()}
                ),
                "teams",
            )
            listed = first.get("nodes", []) if isinstance(first, dict) else []
            more = bool(dig(first, "pageInfo.hasNextPage"))
            metadata["teams_visible"] = f"{len(listed)}+" if more else len(listed)
            capabilities: list[Capability] = []
            if listed:
                capabilities = await self._probe(client, str(listed[0]["id"]))
            else:
                warnings.append("Aucune équipe n'est visible avec cette clé.")

        return ConnectionTestResult(
            account=str(viewer.get("email") or viewer.get("name") or "Linear"),
            metadata=metadata,
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            response = await client.post(GRAPHQL, {"query": read_only(HEALTH)})
        self._raise_errors(response)
        limit = int(response.headers.get("x-ratelimit-requests-limit", 0))
        remaining = int(response.headers.get("x-ratelimit-requests-remaining", limit))
        low = limit > 0 and remaining < limit * LOW_QUOTA_RATIO
        return HealthResult(
            status=HealthStatus.DEGRADED if low else HealthStatus.HEALTHY,
            detail=f"quota {remaining}/{limit}" if limit else None,
            checked_at=datetime.now(UTC),
        )

    async def list_scope(self) -> ScopeListing:
        options: list[ScopeOption] = []
        async with self._client() as client:
            async for team in self._nodes(client, TEAMS, {"filter": None}, "teams"):
                if len(options) == MAX_SCOPE_OPTIONS:
                    return ScopeListing(options=options, truncated=True)
                options.append(
                    ScopeOption(
                        key=str(team["key"]),
                        name=str(team["name"]),
                        description=str(team["description"]) if team.get("description") else None,
                        private=team.get("private") is True,
                        updated_at=parse_timestamp(team.get("updatedAt")),
                    )
                )
        return ScopeListing(options=options)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Linear does not read {capability}"
            raise ValueError(msg)
        async with self._client() as client:
            seen: set[str] = set()
            async for team in self._nodes(client, TEAMS, {"filter": self._filter()}, "teams"):
                key, variables = str(team["key"]), {"team": str(team["id"])}
                if capability is Capability.PROJECTS:
                    projects = self._nodes(client, TEAM_PROJECTS, variables, "team.projects")
                    async for project in projects:
                        if project["id"] in seen:
                            continue  # shared with a team already read
                        seen.add(str(project["id"]))
                        yield _record(capability, project, key)
                    continue
                changed = {"updatedAt": {"gte": since.isoformat()}} if since else None
                issues = self._nodes(
                    client, TEAM_ISSUES, {**variables, "filter": changed}, "team.issues"
                )
                async for issue in issues:
                    yield _record(capability, issue, key)

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.api_key.get_secret_value()
        client = self.http(
            API,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "LEKA",
                # A personal API key goes as it is; "Bearer" is for OAuth.
                "Authorization": secret,
            },
        )
        return VendorHttp(
            client,
            secret=secret,
            refuse=self._refuse,
            page_size=PAGE_SIZE,
            reads_by_post=frozenset({GRAPHQL}),
        )

    def _filter(self) -> dict[str, object] | None:
        return {"key": {"in": self.config.teams}} if self.config.teams else None

    async def _query(
        self, client: VendorHttp, document: str, variables: Mapping[str, object] | None = None
    ) -> Any:
        """The `data` of one query, or the diagnostic of what Linear refused."""
        body: dict[str, object] = {"query": read_only(document)}
        if variables:
            body["variables"] = dict(variables)
        response = await client.post(GRAPHQL, body)
        self._raise_errors(response)
        return response.json().get("data") or {}

    async def _nodes(
        self,
        client: VendorHttp,
        document: str,
        variables: Mapping[str, object],
        connection: str,
    ) -> AsyncIterator[Item]:
        """Every node of a connection, following Linear's cursors."""
        after: str | None = None
        seen: set[str] = set()
        while True:
            data = await self._query(
                client, document, {**variables, "first": PAGE_SIZE, "after": after}
            )
            found = dig(data, connection)
            if not isinstance(found, dict):
                return
            for node in found.get("nodes", []):
                yield node
            if not dig(found, "pageInfo.hasNextPage"):
                return
            after = dig(found, "pageInfo.endCursor")
            if not after or after in seen:
                # A cursor Linear already gave: following it would never end.
                raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail="Linear repeated a cursor")
            seen.add(after)

    async def _require_scope(self, client: VendorHttp) -> None:
        """Every team in scope must be one this key can see."""
        found = {
            str(team["key"]).upper()
            async for team in self._nodes(client, TEAMS, {"filter": self._filter()}, "teams")
        }
        missing = [key for key in self.config.teams or [] if key not in found]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"Linear ne montre pas ces équipes à cette clé : {named}.",
            )

    async def _probe(self, client: VendorHttp, team: str) -> list[Capability]:
        """Which of projects and issues one team lets this key read, asked at
        once. A probe that fails is a capability left out, never an error."""
        asked = {
            Capability.PROJECTS: (TEAM_PROJECTS, {"team": team, "first": 1, "after": None}),
            Capability.ISSUES: (
                TEAM_ISSUES,
                {"team": team, "first": 1, "after": None, "filter": None},
            ),
        }
        answers = await asyncio.gather(
            *(self._query(client, document, variables) for document, variables in asked.values()),
            return_exceptions=True,
        )
        return [
            capability
            for capability, answer in zip(asked, answers, strict=True)
            if not isinstance(answer, BaseException)
        ]

    def _raise_errors(self, response: httpx.Response) -> None:
        """Linear answers a refused query with 200 and `errors` as often as
        with an HTTP error: both end the same way."""
        errors = _errors(response)
        if errors:
            raise self._refuse(response, GRAPHQL, "")

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Linear's refusals, as diagnostics: its `extensions.code` first,
        the HTTP status when it says nothing."""
        secret = self.credentials.api_key.get_secret_value()
        codes = {str(dig(error, "extensions.code") or "").upper() for error in _errors(response)}
        status = response.status_code
        if "RATELIMITED" in codes or status == 429:
            return refusal(
                response, path, secret, DiagnosticCode.RATE_LIMITED, retry_after=_reset(response)
            )
        if "AUTHENTICATION_ERROR" in codes or status == 401:
            message = "Linear refuse cette clé d'API."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if "FORBIDDEN" in codes or status == 403:
            return refusal(response, path, secret, DiagnosticCode.PERMISSION_DENIED)
        if any("NOT_FOUND" in code for code in codes) or status == 404:
            message = "Linear ne trouve pas cette équipe, ou cette clé ne la voit pas."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        if status >= 500:
            return refusal(response, path, secret, DiagnosticCode.PROVIDER_ERROR)
        return refusal(response, path, secret, DiagnosticCode.UNKNOWN)


def _errors(response: httpx.Response) -> list[Any]:
    try:
        errors = response.json().get("errors")
    except (ValueError, AttributeError):
        return []
    return errors if isinstance(errors, list) else []


def _reset(response: httpx.Response) -> int | None:
    """Seconds until the hour's requests come back. Linear gives the moment
    in milliseconds since the epoch."""
    if "retry-after" in response.headers:
        return int(response.headers["retry-after"])
    reset = response.headers.get("x-ratelimit-requests-reset")
    return max(0, int(reset) // 1000 - int(time.time())) if reset else None


def _record(capability: Capability, item: Item, team: str) -> RawRecord:
    return record(
        capability, item, external_id=str(item["id"]), container=team, updated=item.get("updatedAt")
    )
