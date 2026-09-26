"""The GitLab connector — gitlab.com, or a self-managed instance.

test_connection: who am I (GET /user), what can this token do (GET
/personal_access_tokens/self, where GitLab answers it), is the group there
(GET /groups/{group}), what can I see (one page of projects), and — on one
sample project, in scope if a scope is set — which of commits, merge
requests, issues, releases and branches this token can actually read.

check_health: GET /user, reading the RateLimit headers GitLab sends with
it. Healthy, or degraded when less than a tenth of the quota is left.

list_scope: every project the token sees, for the admin to choose from.

LEKA READS. `read_api` is the only scope it needs; a token with `api` or a
write scope is accepted — GitLab is where it is scoped, not here — but the
test says so, in its warnings.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, model_validator

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
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector

LOW_QUOTA_RATIO = 0.1
PAGE_SIZE = 100  # GitLab's maximum
MAX_SCOPE_OPTIONS = 1000
WRITE_SCOPES = ("api", "write_repository", "write_registry", "sudo", "admin_mode")
# A namespace path: "acme", "acme/platform/api". GitLab allows letters,
# digits, "_", "-" and ".", nests groups, and starts no segment with "." or "-".
PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)*$")

type Item = dict[str, object]


class GitLabConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group: str | None = Field(
        default=None,
        max_length=255,
        description="The group to read, with its subgroups: 'acme' or 'acme/platform'. "
        "Empty: the projects the token's owner is a member of.",
    )
    base_url: HttpUrl = Field(
        default=HttpUrl("https://gitlab.com"),
        description="Change only for a self-managed GitLab.",
    )
    projects: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Full paths ('acme/api') of the projects to read. "
        "Empty: every project the token sees.",
    )

    @model_validator(mode="after")
    def _paths_are_full_and_inside_the_group(self) -> GitLabConfig:
        if self.group and not PATH.match(self.group):
            msg = f"{self.group!r} is not a group path like 'acme/platform'"
            raise ValueError(msg)
        for path in self.projects or []:
            if not PATH.match(path) or "/" not in path:
                msg = f"{path!r} is not a full path like 'acme/api'"
                raise ValueError(msg)
            if self.group and not path.lower().startswith(self.group.lower() + "/"):
                msg = f"{path!r} is not in the group {self.group!r}"
                raise ValueError(msg)
        return self


class GitLabCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr = Field(
        min_length=20,
        description="Personal, group or project access token with the read_api scope.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class GitLabConnector(Connector[GitLabConfig, GitLabCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.GITLAB,
        display_name="GitLab",
        category=ConnectorCategory.CODE,
        auth_type="token",
        config_schema=GitLabConfig,
        credentials_schema=GitLabCredentials,
        capabilities=frozenset(
            {
                Capability.REPOSITORIES,
                Capability.COMMITS,
                Capability.PULL_REQUESTS,
                Capability.RELEASES,
                Capability.ISSUES,
                Capability.BRANCHES,
            }
        ),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            user = (await self._get(client, "/user")).json()
            metadata: dict[str, object] = {"login": user.get("username")}
            warnings = await self._token_warnings(client, metadata)
            group = self.config.group
            if group:
                found = await self._get(client, f"/groups/{_id(group)}", missing="ce groupe")
                metadata["group"] = found.json().get("full_path", group)

            listing = await self._get(client, self._projects_path(), params=self._projects_query())
            listed = listing.json()
            more = "next" in listing.links
            metadata["projects_visible"] = f"{len(listed)}+" if more else len(listed)
            capabilities = [Capability.REPOSITORIES] if listed else []
            if listed:
                # Probe what will be read: a project in scope, if one is set.
                sample = str(listed[0]["id"])
                if self.config.projects:
                    path = f"/projects/{_id(self.config.projects[0])}"
                    sample = str((await self._get(client, path, missing="ce projet")).json()["id"])
                capabilities += await self._probe(client, sample)
            else:
                warnings.append("Aucun projet n'est visible avec ce jeton.")

        return ConnectionTestResult(
            account=str(metadata["login"]),
            metadata=metadata,
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            response = await self._get(client, "/user")
        limit = int(response.headers.get("ratelimit-limit", 0))
        remaining = int(response.headers.get("ratelimit-remaining", limit))
        low = limit > 0 and remaining < limit * LOW_QUOTA_RATIO
        return HealthResult(
            status=HealthStatus.DEGRADED if low else HealthStatus.HEALTHY,
            detail=f"quota {remaining}/{limit}" if limit else None,
            checked_at=datetime.now(UTC),
        )

    async def list_scope(self) -> ScopeListing:
        options: list[ScopeOption] = []
        async with self._client() as client:
            async for project in self._pages(client, self._projects_path(), self._projects_query()):
                if len(options) == MAX_SCOPE_OPTIONS:
                    return ScopeListing(options=options, truncated=True)
                options.append(
                    ScopeOption(
                        key=str(project["path_with_namespace"]),
                        name=str(project["path_with_namespace"]),
                        description=str(project["description"])
                        if project.get("description")
                        else None,
                        private=project.get("visibility") != "public",
                        updated_at=_parse(project.get("last_activity_at")),
                    )
                )
        return ScopeListing(options=options)

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> httpx.AsyncClient:
        return self.http(
            str(self.config.base_url).rstrip("/") + "/api/v4",
            headers={
                "Accept": "application/json",
                "User-Agent": "LEKA",
                "PRIVATE-TOKEN": self.credentials.token.get_secret_value(),
            },
        )

    def _projects_path(self) -> str:
        group = self.config.group
        return f"/groups/{_id(group)}/projects" if group else "/projects"

    def _projects_query(self) -> dict[str, str | int]:
        if self.config.group:
            return {"include_subgroups": "true", "per_page": PAGE_SIZE}
        return {"membership": "true", "per_page": PAGE_SIZE}

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        missing: str = "cette ressource",
    ) -> httpx.Response:
        secret = self.credentials.token.get_secret_value()
        try:
            response = await client.get(path, params=params)
        except httpx.TimeoutException as error:
            raise diagnose(
                DiagnosticCode.TIMEOUT, detail=f"GET {path}", secrets=[secret]
            ) from error
        except httpx.TransportError as error:
            raise diagnose(
                DiagnosticCode.NETWORK_UNREACHABLE,
                detail=f"GET {path}: {type(error).__name__}",
                secrets=[secret],
            ) from error
        if response.is_success:
            return response
        raise self._diagnose(response, path, missing, secret)

    def _diagnose(
        self, response: httpx.Response, path: str, missing: str, secret: str
    ) -> ConnectorError:
        status = response.status_code
        body = response.text[:200]
        detail = f"GET {path} → {status}: {body}"

        def build(
            code: DiagnosticCode, *, message: str | None = None, retry_after: int | None = None
        ) -> ConnectorError:
            return diagnose(
                code,
                message=message,
                provider_status=status,
                retry_after=retry_after,
                detail=detail,
                secrets=[secret],
            )

        lowered = body.lower()
        if status == 401 and ("expired" in lowered or "revoked" in lowered):
            return build(DiagnosticCode.AUTH_EXPIRED)
        if status == 401:
            return build(DiagnosticCode.AUTH_INVALID)
        if status == 429:
            return build(DiagnosticCode.RATE_LIMITED, retry_after=_retry_after(response))
        if status == 403 and "insufficient_scope" in lowered:
            return build(DiagnosticCode.INSUFFICIENT_SCOPE)
        if status == 403:
            return build(DiagnosticCode.PERMISSION_DENIED)
        if status == 404:
            return build(
                DiagnosticCode.NOT_FOUND,
                message=f"GitLab ne trouve pas {missing}, ou le jeton ne le voit pas.",
            )
        if status >= 500:
            return build(DiagnosticCode.PROVIDER_ERROR)
        return build(DiagnosticCode.UNKNOWN)

    async def _token_warnings(
        self, client: httpx.AsyncClient, metadata: dict[str, object]
    ) -> list[str]:
        """What GitLab says about the token itself. Older instances, and some
        token types, do not answer: that is not a failure of the test."""
        try:
            response = await client.get("/personal_access_tokens/self")
        except httpx.HTTPError:
            return []
        if not response.is_success:
            return []
        token = response.json()
        if token.get("expires_at"):
            metadata["token_expires_at"] = token["expires_at"]
        writing = [s for s in token.get("scopes", []) if s in WRITE_SCOPES]
        if not writing:
            return []
        return [
            "Ce jeton permet d'écrire (" + ", ".join(writing) + "). LEKA ne fait que lire : "
            "un jeton limité à read_api suffit et limite l'exposition."
        ]

    async def _pages(
        self, client: httpx.AsyncClient, path: str, params: dict[str, str | int]
    ) -> AsyncIterator[Item]:
        """Every item of a listing, following GitLab's Link header."""
        url: str | None = path
        query: dict[str, str | int] | None = {"per_page": PAGE_SIZE, **params}
        while url:
            response = await self._get(client, url, params=query)
            for item in response.json():
                yield item
            url, query = self._next_page(client, response), None  # the link carries the query

    def _next_page(self, client: httpx.AsyncClient, response: httpx.Response) -> str | None:
        """The next page — only if it is on the host the token was meant for."""
        link = response.links.get("next", {}).get("url")
        if link is None:
            return None
        if httpx.URL(link).host != client.base_url.host:
            raise diagnose(
                DiagnosticCode.PROVIDER_ERROR,
                detail=f"pagination points to another host: {httpx.URL(link).host}",
                secrets=[self.credentials.token.get_secret_value()],
            )
        return link

    async def _probe(self, client: httpx.AsyncClient, project: str) -> list[Capability]:
        """Which of the per-project capabilities this token can read, at once."""
        probes = {
            Capability.COMMITS: f"/projects/{project}/repository/commits",
            Capability.PULL_REQUESTS: f"/projects/{project}/merge_requests",
            Capability.RELEASES: f"/projects/{project}/releases",
            Capability.ISSUES: f"/projects/{project}/issues",
            Capability.BRANCHES: f"/projects/{project}/repository/branches",
        }
        responses = await asyncio.gather(
            *(client.get(path, params={"per_page": 1}) for path in probes.values()),
            return_exceptions=True,
        )
        return [
            capability
            for capability, response in zip(probes, responses, strict=True)
            if isinstance(response, httpx.Response) and response.is_success
        ]


def _id(path: str) -> str:
    """A namespace path as GitLab takes it in a URL: 'acme/api' → 'acme%2Fapi'."""
    return quote(path, safe="")


def _retry_after(response: httpx.Response) -> int | None:
    if "retry-after" in response.headers:
        return int(response.headers["retry-after"])
    reset = response.headers.get("ratelimit-reset")
    return max(0, int(reset) - int(time.time())) if reset else None


def _parse(timestamp: object) -> datetime | None:
    """GitLab's ISO 8601, "2026-09-26T10:00:00.000Z"."""
    return datetime.fromisoformat(str(timestamp)) if timestamp else None
