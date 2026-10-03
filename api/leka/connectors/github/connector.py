"""The GitHub connector.

test_connection: who am I (GET /user), is the organisation there (GET
/orgs/{org}), what can I see (one page of repositories), and — on one
sample repository — which of commits, pull requests, releases, issues and
deployments this token can actually read. A fine-grained token says nothing about its
own permissions; asking is the only way to know.

check_health: GET /rate_limit, which GitHub does not count against the
quota. Healthy, or degraded when less than a tenth of the quota is left.

list_scope: every repository the token sees, for the admin to choose from.

iter_resources: the repositories in scope — all the token sees, unless
`repositories` names some — then, repository by repository, their
branches, commits (default branch), pull requests, issues and releases,
following GitHub's pagination. Commits and issues are
filtered by `since` on GitHub's side; pull requests are read newest-updated
first and stop at `since`; branches and releases have no such filter and
come whole. `teams`, with an organisation (LEKA-365): its teams — each with
its parent team, its maintainers and its members — whole each pass; a token
that may not read the organisation's members leaves them out.
`deployments` (LEKA-367): each repository's, newest first — the last
DEPLOYMENT_HISTORY at the first pass, then those made since the last pass
less DEPLOYMENT_MARGIN — each with its statuses, one read per deployment:
how it went, and when.
`components` (LEKA-369): what each repository's code says it runs — its
default branch's tree (one read), then the files that say it (compose
files, workflows, env examples, proxy configs, Dockerfiles, manifests:
MAX_FILES at most, one read each), handed to leka.connectors.components —
one record per service, store or service outside, whole each pass.

LEKA READS. A classic token that carries write scopes is accepted — GitHub
is where it is scoped, not here — but the test says so, in its warnings.
"""

from __future__ import annotations

import base64
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, model_validator

from leka.connectors import components, network
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
    parse_timestamp,
    record,
    records,
    refusal,
    retry_after,
    usual_code,
    without,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.network import PublicHttpsUrl
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

API_VERSION = "2022-11-28"
LOW_QUOTA_RATIO = 0.1
PAGE_SIZE = 100  # GitHub's maximum
# GitHub answers 409 for the commits of a repository with none yet.
EMPTY_REPOSITORY = 409
# What list_scope offers at most: ten pages. An organisation with more is
# scoped by typing names, until the Sources screen searches (LEKA-351).
MAX_SCOPE_OPTIONS = 1000
FULL_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
# Classic OAuth scopes that let a token change something. Fine-grained tokens
# send no X-OAuth-Scopes header at all, so this only ever warns about those.
WRITE_SCOPES = ("repo", "write:", "admin:", "delete_repo", "workflow", "delete:")
# Deployments (LEKA-367): how far back the first pass reads; how far before
# the last pass the next reads again — a status comes after its deployment.
DEPLOYMENT_HISTORY = timedelta(days=90)
DEPLOYMENT_MARGIN = timedelta(days=1)


class GitHubConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization: str | None = Field(
        default=None,
        max_length=100,
        description="The organisation to read. Empty: what the token's owner can see.",
    )
    base_url: PublicHttpsUrl = Field(
        default=HttpUrl("https://api.github.com"),
        description="Change only for GitHub Enterprise Server.",
    )
    repositories: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Full names ('acme/api') of the repositories to read. "
        "Empty: every repository the token sees.",
    )

    @model_validator(mode="after")
    def _repositories_are_full_names_in_the_organisation(self) -> GitHubConfig:
        for name in self.repositories or []:
            if not FULL_NAME.match(name):
                msg = f"{name!r} is not a full name like 'acme/api'"
                raise ValueError(msg)
            owner = name.split("/")[0]
            if self.organization and owner.lower() != self.organization.lower():
                msg = f"{name!r} is not in the organisation {self.organization!r}"
                raise ValueError(msg)
        return self


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
                Capability.TEAMS,
                Capability.DEPLOYMENTS,
                Capability.COMPONENTS,
            }
        ),
        # A team gone from the organisation is gone at the next pass; so is
        # a service gone from the code.
        listed_whole=frozenset({Capability.TEAMS, Capability.COMPONENTS}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            user = await client.get("/user")
            warnings = self._scope_warnings(user)
            org = self.config.organization
            metadata: dict[str, object] = {"login": user.json().get("login")}
            if org:
                organisation = await client.get(f"/orgs/{org}", missing="organisation")
                metadata["organization"] = organisation.json().get("login", org)
                repos = await client.get(f"/orgs/{org}/repos", params={"per_page": 100})
            else:
                repos = await client.get("/user/repos", params={"per_page": 100})

            listed = repos.json()
            more = 'rel="next"' in repos.headers.get("link", "")
            metadata["repositories_visible"] = f"{len(listed)}+" if more else len(listed)
            capabilities = [Capability.REPOSITORIES] if listed else []
            if listed:
                # Probe what will be read: a repository in scope, if one is set.
                sample = listed[0]["full_name"]
                if self.config.repositories:
                    sample = self.config.repositories[0]
                    await client.get(f"/repos/{sample}")
                capabilities += await client.probe(
                    {
                        Capability.COMMITS: f"/repos/{sample}/commits",
                        Capability.PULL_REQUESTS: f"/repos/{sample}/pulls",
                        Capability.RELEASES: f"/repos/{sample}/releases",
                        Capability.ISSUES: f"/repos/{sample}/issues",
                        Capability.BRANCHES: f"/repos/{sample}/branches",
                        Capability.DEPLOYMENTS: f"/repos/{sample}/deployments",
                        # The Contents permission: what reads the code's files.
                        Capability.COMPONENTS: f"/repos/{sample}/contents",
                    },
                    params={"per_page": 1},
                )
            else:
                warnings.append("Aucun dépôt n'est visible avec ce token.")
            if org:
                # The organisation's teams: read:org, or Members read.
                capabilities += await client.probe(
                    {Capability.TEAMS: f"/orgs/{org}/teams"}, params={"per_page": 1}
                )

        return ConnectionTestResult(
            account=str(metadata["login"]),
            metadata=metadata,
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            response = await client.get("/rate_limit")
        core = response.json().get("resources", {}).get("core", {})
        limit, remaining = int(core.get("limit", 0)), int(core.get("remaining", 0))
        low = limit > 0 and remaining < limit * LOW_QUOTA_RATIO
        return HealthResult(
            status=HealthStatus.DEGRADED if low else HealthStatus.HEALTHY,
            detail=f"quota {remaining}/{limit}",
            checked_at=datetime.now(UTC),
        )

    async def list_scope(self) -> ScopeListing:
        options: list[ScopeOption] = []
        async with self._client() as client:
            async for repository in self._visible_repositories(client):
                if len(options) == MAX_SCOPE_OPTIONS:
                    return ScopeListing(options=options, truncated=True)
                options.append(
                    ScopeOption(
                        key=str(repository["full_name"]),
                        name=str(repository["full_name"]),
                        description=str(repository["description"])
                        if repository.get("description")
                        else None,
                        private=bool(repository.get("private")),
                        updated_at=parse_timestamp(repository.get("pushed_at")),
                    )
                )
        return ScopeListing(options=options)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        async with self._client() as client:
            if capability is Capability.TEAMS:
                async for team in self._teams(client):
                    yield team
                return
            async for repository in self._repositories(client):
                if capability is Capability.COMPONENTS:
                    async for component in self._components(client, repository):
                        yield component
                    continue
                if capability is Capability.REPOSITORIES:
                    yield record(
                        capability,
                        repository,
                        external_id=str(repository["node_id"]),
                        # Its own path: what scope rules match it by (LEKA-351).
                        container=str(repository["full_name"]),
                        updated=repository.get("updated_at"),
                    )
                    continue
                async for item in self._contents(client, capability, repository, since):
                    yield item

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.token.get_secret_value()
        client = self.http(
            str(self.config.base_url).rstrip("/"),
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "LEKA",
                "Authorization": f"Bearer {secret}",
            },
        )
        return VendorHttp(client, secret=secret, refuse=self._refuse, page_size=PAGE_SIZE)

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """GitHub's answers, as diagnostics. A 403 is a quota when none is
        left, and a scope when GitHub says the token cannot reach it."""
        status, body = response.status_code, response.text[:200].lower()
        code = usual_code(status)
        if status == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            code = DiagnosticCode.RATE_LIMITED
        elif status == 403 and "not accessible by personal access token" in body:
            code = DiagnosticCode.INSUFFICIENT_SCOPE
        secret = self.credentials.token.get_secret_value()
        if code is DiagnosticCode.RATE_LIMITED:
            wait = retry_after(response, "x-ratelimit-reset")
            return refusal(response, path, secret, code, retry_after=wait)
        if code is DiagnosticCode.NOT_FOUND:
            message = (
                f"GitHub ne trouve pas cette {missing or 'ressource'}, ou le token ne la voit pas."
            )
            return refusal(response, path, secret, code, message=message)
        return refusal(response, path, secret, code)

    async def _teams(self, client: VendorHttp) -> AsyncIterator[RawRecord]:
        """The organisation's teams, each with its maintainers and members —
        their logins: GitHub says no more of them here."""
        org = self.config.organization
        if not org:
            return
        async for team in client.pages(f"/orgs/{org}/teams"):
            slug = str(team["slug"])
            people: dict[str, list[str]] = {}
            for role in ("maintainer", "member"):
                people[role] = [
                    str(user["login"])
                    async for user in client.pages(
                        f"/orgs/{org}/teams/{slug}/members", {"role": role}
                    )
                    if user.get("login")
                ]
            yield record(
                Capability.TEAMS,
                {**team, "maintainers": people["maintainer"], "members": people["member"]},
                external_id=str(team["node_id"]),
                container=org,
                updated=team.get("updated_at"),
            )

    def _visible_repositories(self, client: VendorHttp) -> AsyncIterator[Item]:
        org = self.config.organization
        return client.pages(f"/orgs/{org}/repos" if org else "/user/repos")

    async def _repositories(self, client: VendorHttp) -> AsyncIterator[Item]:
        """The repositories in scope. GitHub's names are case-insensitive."""
        wanted = {name.lower() for name in self.config.repositories or []}
        async for repository in self._visible_repositories(client):
            if not wanted or str(repository["full_name"]).lower() in wanted:
                yield repository

    def _contents(
        self,
        client: VendorHttp,
        capability: Capability,
        repository: Item,
        since: datetime | None,
    ) -> AsyncIterator[RawRecord]:
        """One repository's records for one capability."""
        name = str(repository["full_name"])
        after = {"since": since.isoformat()} if since else {}
        if capability is Capability.BRANCHES:
            items = client.pages(f"/repos/{name}/branches")
            # A branch has no node_id: its repository's, and its own name.
            return records(
                capability, items, name, key=lambda b: f"{repository['node_id']}:{b['name']}"
            )
        if capability is Capability.COMMITS:
            items = client.pages(f"/repos/{name}/commits", after, empty=EMPTY_REPOSITORY)
            return records(
                capability,
                items,
                name,
                key=_node_id,
                updated=lambda c: c["commit"]["committer"]["date"],
            )
        if capability is Capability.PULL_REQUESTS:
            items = client.pages(
                f"/repos/{name}/pulls",
                {"state": "all", "sort": "updated", "direction": "desc"},
                stop_before=since,
            )
            return records(capability, items, name, key=_node_id)
        if capability is Capability.ISSUES:
            items = client.pages(f"/repos/{name}/issues", {"state": "all", **after})
            # GitHub lists pull requests as issues too; they have their own capability.
            return records(capability, without(items, "pull_request"), name, key=_node_id)
        if capability is Capability.RELEASES:
            items = client.pages(f"/repos/{name}/releases")
            return records(
                capability,
                items,
                name,
                key=_node_id,
                updated=lambda r: r.get("published_at") or r["created_at"],
            )
        if capability is Capability.DEPLOYMENTS:
            return records(
                capability,
                self._deployments(client, name, since),
                name,
                key=_node_id,
                updated=lambda d: d.get("updated_at"),
            )
        msg = f"GitHub does not read {capability}"
        raise ValueError(msg)

    async def _deployments(
        self, client: VendorHttp, name: str, since: datetime | None
    ) -> AsyncIterator[Item]:
        """A repository's deployments, newest first, each with its statuses
        — newest first too, as GitHub lists them."""
        after = since - DEPLOYMENT_MARGIN if since else datetime.now(UTC) - DEPLOYMENT_HISTORY
        found = client.pages(
            f"/repos/{name}/deployments", stop_before=after, updated_field="created_at"
        )
        async for deployment in found:
            response = await client.get(
                f"/repos/{name}/deployments/{deployment['id']}/statuses",
                params={"per_page": PAGE_SIZE},
            )
            statuses = response.json()
            yield {**deployment, "statuses": statuses if isinstance(statuses, list) else []}

    async def _components(self, client: VendorHttp, repository: Item) -> AsyncIterator[RawRecord]:
        """What one repository's code says it runs: its default branch's
        tree, the files of it that say so, what they declare."""
        name, branch = str(repository["full_name"]), str(repository.get("default_branch") or "")
        if not branch:
            return
        tree = await client.get(
            f"/repos/{name}/git/trees/{branch}", params={"recursive": "1"}, empty=EMPTY_REPOSITORY
        )
        if tree.status_code == EMPTY_REPOSITORY:
            return
        entries = tree.json().get("tree") if isinstance(tree.json(), dict) else None
        paths = [
            str(entry["path"])
            for entry in entries or []
            if entry.get("type") == "blob" and int(entry.get("size") or 0) <= components.MAX_BYTES
        ]
        files: dict[str, str] = {}
        for path in components.wanted(paths):
            answer = await client.get(
                f"/repos/{name}/contents/{path}", params={"ref": branch}, missing="ce fichier"
            )
            found = answer.json()
            if isinstance(found, dict) and found.get("encoding") == "base64":
                try:
                    files[path] = base64.b64decode(str(found.get("content") or "")).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    continue
        for component in components.discover(name, files):
            # Where its public address is — leka-core.com is on the instance
            # with that IP: what runs it (enrichment's `architecture`).
            url = component.get("public_url")
            host = urlsplit(url).hostname if isinstance(url, str) else None
            yield record(
                Capability.COMPONENTS,
                {
                    **component,
                    "repository_url": repository.get("html_url"),
                    "default_branch": branch,
                    "public_addresses": await self._resolve(host) if host else [],
                },
                external_id=f"{repository['node_id']}:{component['name']}",
                container=name,
                updated=repository.get("pushed_at"),
            )

    async def _resolve(self, host: str) -> list[str]:
        """A name's public addresses: replaced in the tests."""
        return await network.public_addresses(host)

    @staticmethod
    def _scope_warnings(response: httpx.Response) -> list[str]:
        scopes = [scope.strip() for scope in response.headers.get("x-oauth-scopes", "").split(",")]
        writing = [s for s in scopes if s and any(s == w or s.startswith(w) for w in WRITE_SCOPES)]
        if not writing:
            return []
        return [
            "Ce token permet d'écrire (" + ", ".join(writing) + "). LEKA ne fait que lire : "
            "un token fine-grained en lecture seule suffit et limite l'exposition."
        ]


def _node_id(item: Item) -> str:
    """GitHub's global id: stable across renames and transfers."""
    return str(item["node_id"])
