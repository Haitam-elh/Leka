"""The GitHub connector.

test_connection: who am I (GET /user), is the organisation there (GET
/orgs/{org}), what can I see (one page of repositories), and — on one
sample repository — which of commits, pull requests, releases and issues
this token can actually read. A fine-grained token says nothing about its
own permissions; asking is the only way to know.

check_health: GET /rate_limit, which GitHub does not count against the
quota. Healthy, or degraded when less than a tenth of the quota is left.

LEKA READS. A classic token that carries write scopes is accepted — GitHub
is where it is scoped, not here — but the test says so, in its warnings.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

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

API_VERSION = "2022-11-28"
LOW_QUOTA_RATIO = 0.1
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
        params: dict[str, int] | None = None,
        missing: str = "ressource",
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

    async def _probe(self, client: httpx.AsyncClient, full_name: str) -> list[Capability]:
        """Which of the per-repository capabilities this token can read, at once."""
        probes = {
            Capability.COMMITS: f"/repos/{full_name}/commits",
            Capability.PULL_REQUESTS: f"/repos/{full_name}/pulls",
            Capability.RELEASES: f"/repos/{full_name}/releases",
            Capability.ISSUES: f"/repos/{full_name}/issues",
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
