"""The GitLab connector — gitlab.com, or a self-managed instance.

test_connection: who am I (GET /user), what can this token do (GET
/personal_access_tokens/self, where GitLab answers it), is the group there
(GET /groups/{group}), what can I see (one page of projects), and — on one
sample project, in scope if a scope is set — which of commits, merge
requests, issues, releases and branches this token can actually read.

check_health: GET /user, reading the RateLimit headers GitLab sends with
it. Healthy, or degraded when less than a tenth of the quota is left.

list_scope: every project the token sees, for the admin to choose from.

iter_resources: the projects in scope — all the token sees, unless
`projects` names some — then, project by project, their branches, commits
(default branch), merge requests, issues and releases, following GitLab's
pagination. Commits are filtered by `since` on GitLab's side, merge
requests and issues by `updated_after`; branches and releases come whole.
A feature a project has switched off, or an empty repository, is skipped
rather than asked for.

LEKA READS. `read_api` is the only scope it needs; a token with `api` or a
write scope is accepted — GitLab is where it is scoped, not here — but the
test says so, in its warnings.
"""

from __future__ import annotations

import re
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
from leka.connectors.errors import ConnectorError, DiagnosticCode
from leka.connectors.http import (
    Item,
    VendorHttp,
    nothing,
    parse_timestamp,
    record,
    records,
    refusal,
    retry_after,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.network import PublicHttpsUrl
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

LOW_QUOTA_RATIO = 0.1
PAGE_SIZE = 100  # GitLab's maximum
MAX_SCOPE_OPTIONS = 1000
WRITE_SCOPES = ("api", "write_repository", "write_registry", "sudo", "admin_mode")
# A namespace path: "acme", "acme/platform/api". GitLab allows letters,
# digits, "_", "-" and ".", nests groups, and starts no segment with "." or "-".
PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)*$")


class GitLabConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group: str | None = Field(
        default=None,
        max_length=255,
        description="The group to read, with its subgroups: 'acme' or 'acme/platform'. "
        "Empty: the projects the token's owner is a member of.",
    )
    base_url: PublicHttpsUrl = Field(
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
            user = (await client.get("/user")).json()
            metadata: dict[str, object] = {"login": user.get("username")}
            warnings = await self._token_warnings(client, metadata)
            group = self.config.group
            if group:
                found = await client.get(f"/groups/{_id(group)}", missing="ce groupe")
                metadata["group"] = found.json().get("full_path", group)

            listing = await client.get(self._projects_path(), params=self._projects_query())
            listed = listing.json()
            more = "next" in listing.links
            metadata["projects_visible"] = f"{len(listed)}+" if more else len(listed)
            capabilities = [Capability.REPOSITORIES] if listed else []
            if listed:
                # Probe what will be read: a project in scope, if one is set.
                sample = str(listed[0]["id"])
                if self.config.projects:
                    path = f"/projects/{_id(self.config.projects[0])}"
                    sample = str((await client.get(path, missing="ce projet")).json()["id"])
                capabilities += await client.probe(
                    {
                        Capability.COMMITS: f"/projects/{sample}/repository/commits",
                        Capability.PULL_REQUESTS: f"/projects/{sample}/merge_requests",
                        Capability.RELEASES: f"/projects/{sample}/releases",
                        Capability.ISSUES: f"/projects/{sample}/issues",
                        Capability.BRANCHES: f"/projects/{sample}/repository/branches",
                    },
                    params={"per_page": 1},
                )
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
            response = await client.get("/user")
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
            async for project in client.pages(self._projects_path(), self._projects_query()):
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
                        updated_at=parse_timestamp(project.get("last_activity_at")),
                    )
                )
        return ScopeListing(options=options)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        async with self._client() as client:
            async for project in self._projects(client):
                if capability is Capability.REPOSITORIES:
                    yield record(
                        capability,
                        project,
                        external_id=str(project["id"]),
                        updated=project.get("last_activity_at"),
                    )
                    continue
                async for item in self._contents(client, capability, project, since):
                    yield item

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.token.get_secret_value()
        client = self.http(
            str(self.config.base_url).rstrip("/") + "/api/v4",
            headers={"Accept": "application/json", "User-Agent": "LEKA", "PRIVATE-TOKEN": secret},
        )
        return VendorHttp(client, secret=secret, refuse=self._refuse, page_size=PAGE_SIZE)

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """GitLab's answers, as diagnostics. A 401 may say the token expired;
        a 403 may say its scope is short."""
        status, body = response.status_code, response.text[:200].lower()
        code = usual_code(status)
        if status == 401 and ("expired" in body or "revoked" in body):
            code = DiagnosticCode.AUTH_EXPIRED
        elif status == 403 and "insufficient_scope" in body:
            code = DiagnosticCode.INSUFFICIENT_SCOPE
        secret = self.credentials.token.get_secret_value()
        if code is DiagnosticCode.RATE_LIMITED:
            wait = retry_after(response, "ratelimit-reset")
            return refusal(response, path, secret, code, retry_after=wait)
        if code is DiagnosticCode.NOT_FOUND:
            what = missing or "cette ressource"
            message = f"GitLab ne trouve pas {what}, ou le jeton ne le voit pas."
            return refusal(response, path, secret, code, message=message)
        return refusal(response, path, secret, code)

    def _projects_path(self) -> str:
        group = self.config.group
        return f"/groups/{_id(group)}/projects" if group else "/projects"

    def _projects_query(self) -> dict[str, str | int]:
        if self.config.group:
            return {"include_subgroups": "true", "per_page": PAGE_SIZE}
        return {"membership": "true", "per_page": PAGE_SIZE}

    async def _token_warnings(self, client: VendorHttp, metadata: dict[str, object]) -> list[str]:
        """What GitLab says about the token itself. Older instances, and some
        token types, do not answer: that is not a failure of the test."""
        response = await client.get_if_answered("/personal_access_tokens/self")
        if response is None:
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

    async def _projects(self, client: VendorHttp) -> AsyncIterator[Item]:
        """The projects in scope. GitLab's paths are case-insensitive."""
        wanted = {path.lower() for path in self.config.projects or []}
        async for project in client.pages(self._projects_path(), self._projects_query()):
            if not wanted or str(project["path_with_namespace"]).lower() in wanted:
                yield project

    def _contents(
        self,
        client: VendorHttp,
        capability: Capability,
        project: Item,
        since: datetime | None,
    ) -> AsyncIterator[RawRecord]:
        """One project's records for one capability."""
        pid, path = project["id"], str(project["path_with_namespace"])
        if not _offers(project, capability):
            return nothing()
        if capability is Capability.BRANCHES:
            items = client.pages(f"/projects/{pid}/repository/branches")
            return records(capability, items, path, key=lambda b: f"{pid}:{b['name']}")
        if capability is Capability.COMMITS:
            after = {"since": since.isoformat()} if since else {}
            items = client.pages(f"/projects/{pid}/repository/commits", after)
            return records(
                capability,
                items,
                path,
                key=lambda c: f"{pid}:{c['id']}",
                updated=lambda c: c.get("committed_date"),
            )
        # Without a state, a project's listing holds every state: open, merged, closed.
        updated_after = {"updated_after": since.isoformat()} if since else {}
        if capability is Capability.PULL_REQUESTS:
            items = client.pages(f"/projects/{pid}/merge_requests", updated_after)
            return records(capability, items, path, key=_gitlab_id)
        if capability is Capability.ISSUES:
            items = client.pages(f"/projects/{pid}/issues", updated_after)
            return records(capability, items, path, key=_gitlab_id)
        if capability is Capability.RELEASES:
            items = client.pages(f"/projects/{pid}/releases")
            return records(
                capability,
                items,
                path,
                key=lambda r: f"{pid}:{r['tag_name']}",
                updated=lambda r: r.get("released_at") or r.get("created_at"),
            )
        msg = f"GitLab does not read {capability}"
        raise ValueError(msg)


def _id(path: str) -> str:
    """A namespace path as GitLab takes it in a URL: 'acme/api' → 'acme%2Fapi'."""
    return quote(path, safe="")


def _gitlab_id(item: Item) -> str:
    """GitLab's id, unique on the instance — not the per-project `iid`."""
    return str(item["id"])


# The project field that says a feature is switched off, per capability.
# Asking for a disabled feature is a 403 or a 404 that means nothing.
_FEATURE = {
    Capability.BRANCHES: "repository_access_level",
    Capability.COMMITS: "repository_access_level",
    Capability.PULL_REQUESTS: "merge_requests_access_level",
    Capability.ISSUES: "issues_access_level",
    Capability.RELEASES: "releases_access_level",
}
_NEEDS_A_REPOSITORY = {Capability.BRANCHES, Capability.COMMITS}


def _offers(project: Item, capability: Capability) -> bool:
    if project.get(_FEATURE[capability]) == "disabled":
        return False
    return not (capability in _NEEDS_A_REPOSITORY and project.get("empty_repo"))
