"""The GitHub connector.

test_connection: who am I (GET /user), is the organisation there (GET
/orgs/{org}), what can I see (one page of repositories), and — on one
sample repository — which of commits, pull requests, releases and issues
this token can actually read. A fine-grained token says nothing about its
own permissions; asking is the only way to know.

check_health: GET /rate_limit, which GitHub does not count against the
quota. Healthy, or degraded when less than a tenth of the quota is left.

iter_resources: the repositories the token sees, then — repository by
repository — their branches, commits (default branch), pull requests,
issues and releases, following GitHub's pagination. Commits and issues are
filtered by `since` on GitHub's side; pull requests are read newest-updated
first and stop at `since`; branches and releases have no such filter and
come whole.

LEKA READS. A classic token that carries write scopes is accepted — GitHub
is where it is scoped, not here — but the test says so, in its warnings.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr

from leka.connectors.base import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    HealthResult,
)
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

API_VERSION = "2022-11-28"
LOW_QUOTA_RATIO = 0.1
PAGE_SIZE = 100  # GitHub's maximum
# GitHub answers 409 for the commits of a repository with none yet.
EMPTY_REPOSITORY = 409
# Classic OAuth scopes that let a token change something. Fine-grained tokens
# send no X-OAuth-Scopes header at all, so this only ever warns about those.
WRITE_SCOPES = ("repo", "write:", "admin:", "delete_repo", "workflow", "delete:")


class GitHubConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization: str | None = Field(
        default=None,
        max_length=100,
        description="The organisation to read. Empty: what the token's owner can see.",
    )
    base_url: HttpUrl = Field(
        default=HttpUrl("https://api.github.com"),
        description="Change only for GitHub Enterprise Server.",
    )


class GitHubCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr = Field(
        min_length=20,
        description="Fine-grained personal access token, read-only.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class GitHubConnector(Connector[GitHubConfig, GitHubCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.GITHUB,
        display_name="GitHub",
        category=ConnectorCategory.CODE,
        auth_type="token",
        config_schema=GitHubConfig,
        credentials_schema=GitHubCredentials,
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
            user = await self._get(client, "/user")
            warnings = self._scope_warnings(user)
            org = self.config.organization
            metadata: dict[str, object] = {"login": user.json().get("login")}
            if org:
                organisation = await self._get(client, f"/orgs/{org}", missing="organisation")
                metadata["organization"] = organisation.json().get("login", org)
                repos = await self._get(client, f"/orgs/{org}/repos", params={"per_page": 100})
            else:
                repos = await self._get(client, "/user/repos", params={"per_page": 100})

            listed = repos.json()
            more = 'rel="next"' in repos.headers.get("link", "")
            metadata["repositories_visible"] = f"{len(listed)}+" if more else len(listed)
            capabilities = [Capability.REPOSITORIES] if listed else []
            if listed:
                capabilities += await self._probe(client, listed[0]["full_name"])
            else:
                warnings.append("Aucun dépôt n'est visible avec ce jeton.")

        return ConnectionTestResult(
            account=str(metadata["login"]),
            metadata=metadata,
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            response = await self._get(client, "/rate_limit")
        core = response.json().get("resources", {}).get("core", {})
        limit, remaining = int(core.get("limit", 0)), int(core.get("remaining", 0))
        low = limit > 0 and remaining < limit * LOW_QUOTA_RATIO
        return HealthResult(
            status=HealthStatus.DEGRADED if low else HealthStatus.HEALTHY,
            detail=f"quota {remaining}/{limit}",
            checked_at=datetime.now(UTC),
        )

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        async with self._client() as client:
            if capability is Capability.REPOSITORIES:
                async for repository in self._repositories(client):
                    yield _record(capability, repository, updated=repository.get("updated_at"))
                return
            async for repository in self._repositories(client):
                async for record in self._contents(client, capability, repository, since):
                    yield record

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> httpx.AsyncClient:
        return self.http(
            str(self.config.base_url).rstrip("/"),
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "LEKA",
                "Authorization": f"Bearer {self.credentials.token.get_secret_value()}",
            },
        )

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        missing: str = "ressource",
        empty: int | None = None,
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
        if response.is_success or response.status_code == empty:
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

        if status == 401:
            return build(DiagnosticCode.AUTH_INVALID)
        if status == 429 or (
            status == 403 and response.headers.get("x-ratelimit-remaining") == "0"
        ):
            return build(DiagnosticCode.RATE_LIMITED, retry_after=_retry_after(response))
        if status == 403 and "not accessible by personal access token" in body.lower():
            return build(DiagnosticCode.INSUFFICIENT_SCOPE)
        if status == 403:
            return build(DiagnosticCode.PERMISSION_DENIED)
        if status == 404:
            return build(
                DiagnosticCode.NOT_FOUND,
                message=f"GitHub ne trouve pas cette {missing}, ou le jeton ne la voit pas.",
            )
        if status >= 500:
            return build(DiagnosticCode.PROVIDER_ERROR)
        return build(DiagnosticCode.UNKNOWN)

    def _repositories(self, client: httpx.AsyncClient) -> AsyncIterator[dict[str, object]]:
        org = self.config.organization
        return self._pages(client, f"/orgs/{org}/repos" if org else "/user/repos")

    def _contents(
        self,
        client: httpx.AsyncClient,
        capability: Capability,
        repository: dict[str, object],
        since: datetime | None,
    ) -> AsyncIterator[RawRecord]:
        """One repository's records for one capability."""
        name = str(repository["full_name"])
        after: dict[str, str | int] = {"since": since.isoformat()} if since else {}
        if capability is Capability.BRANCHES:
            items = self._pages(client, f"/repos/{name}/branches")
            # A branch has no node_id: its repository's, and its own name.
            return _records(
                capability, items, name, key=lambda b: f"{repository['node_id']}:{b['name']}"
            )
        if capability is Capability.COMMITS:
            items = self._pages(client, f"/repos/{name}/commits", after, empty=EMPTY_REPOSITORY)
            return _records(capability, items, name, updated=_committed_at)
        if capability is Capability.PULL_REQUESTS:
            items = self._pages(
                client,
                f"/repos/{name}/pulls",
                {"state": "all", "sort": "updated", "direction": "desc"},
                stop_before=since,
            )
            return _records(capability, items, name)
        if capability is Capability.ISSUES:
            items = self._pages(client, f"/repos/{name}/issues", {"state": "all", **after})
            # GitHub lists pull requests as issues too; they have their own capability.
            only_issues = _without(items, "pull_request")
            return _records(capability, only_issues, name)
        if capability is Capability.RELEASES:
            items = self._pages(client, f"/repos/{name}/releases")
            return _records(
                capability, items, name, updated=lambda r: r.get("published_at") or r["created_at"]
            )
        msg = f"GitHub does not read {capability}"
        raise ValueError(msg)

    async def _pages(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, str | int] | None = None,
        *,
        empty: int | None = None,
        stop_before: datetime | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        """Every item of a listing, following GitHub's Link header.

        `stop_before`: the listing is sorted newest-updated first, and
        nothing older than this is wanted.
        """
        url: str | None = path
        query: dict[str, str | int] | None = {"per_page": PAGE_SIZE, **(params or {})}
        while url:
            response = await self._get(client, url, params=query, empty=empty)
            if response.status_code == empty:
                return
            for item in response.json():
                if stop_before and _parse(item.get("updated_at")) < stop_before:
                    return
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

    async def _probe(self, client: httpx.AsyncClient, full_name: str) -> list[Capability]:
        """Which of the per-repository capabilities this token can read, at once."""
        probes = {
            Capability.COMMITS: f"/repos/{full_name}/commits",
            Capability.PULL_REQUESTS: f"/repos/{full_name}/pulls",
            Capability.RELEASES: f"/repos/{full_name}/releases",
            Capability.ISSUES: f"/repos/{full_name}/issues",
            Capability.BRANCHES: f"/repos/{full_name}/branches",
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

    @staticmethod
    def _scope_warnings(response: httpx.Response) -> list[str]:
        scopes = [scope.strip() for scope in response.headers.get("x-oauth-scopes", "").split(",")]
        writing = [s for s in scopes if s and any(s == w or s.startswith(w) for w in WRITE_SCOPES)]
        if not writing:
            return []
        return [
            "Ce jeton permet d'écrire (" + ", ".join(writing) + "). LEKA ne fait que lire : "
            "un jeton fine-grained en lecture seule suffit et limite l'exposition."
        ]


def _retry_after(response: httpx.Response) -> int | None:
    if "retry-after" in response.headers:
        return int(response.headers["retry-after"])
    reset = response.headers.get("x-ratelimit-reset")
    return max(0, int(reset) - int(time.time())) if reset else None


# ── records ─────────────────────────────────────────────────────────────────

type Item = dict[str, object]


def _record(
    kind: Capability,
    item: Item,
    *,
    container: str | None = None,
    external_id: str | None = None,
    updated: object = None,
) -> RawRecord:
    return RawRecord(
        kind=kind,
        external_id=external_id or str(item["node_id"]),
        container=container,
        payload=item,
        updated_at=_parse(updated) if updated else None,
        fetched_at=datetime.now(UTC),
    )


async def _records(
    kind: Capability,
    items: AsyncIterator[Item],
    container: str,
    *,
    key: Callable[[Any], str] | None = None,
    updated: Callable[[Any], object] = lambda item: item.get("updated_at"),
) -> AsyncIterator[RawRecord]:
    async for item in items:
        yield _record(
            kind,
            item,
            container=container,
            external_id=key(item) if key else None,
            updated=updated(item),
        )


async def _without(items: AsyncIterator[Item], field: str) -> AsyncIterator[Item]:
    async for item in items:
        if field not in item:
            yield item


def _committed_at(commit: Any) -> object:
    return commit["commit"]["committer"]["date"]


def _parse(timestamp: object) -> datetime:
    """GitHub's ISO 8601, "2026-09-26T10:00:00Z". A missing one sorts first."""
    if not timestamp:
        return datetime.min.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(timestamp))
