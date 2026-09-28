"""The Bitbucket connector — Bitbucket Cloud (api.bitbucket.org).

test_connection: is the workspace there and readable (GET
/workspaces/{workspace}), who am I where Bitbucket says (GET /user — an
access token is not a user, and may not answer), what can I see (one page
of repositories), and — on one sample repository, in scope if a scope is
set — which of commits, pull requests, issues and branches this token can
actually read.

check_health: GET /workspaces/{workspace}. Healthy, or degraded when
Bitbucket says the quota is nearly spent (X-RateLimit-NearLimit).

list_scope: every repository of the workspace, for the admin to choose from.

iter_resources: the repositories in scope, then per repository its
branches, the commits of its main branch, its pull requests (every state)
and its issues (where the tracker is on). Bitbucket filters none of them by
date: pull requests and issues are asked newest-updated first and stop at
`since`; commits come only roughly newest first, so the older ones are
skipped and the listing ends after a page with nothing newer. Bitbucket has no releases.

Two kinds of token. A repository, project or workspace access token is sent
as a Bearer token. An Atlassian API token needs its account's email, and
goes as Basic. LEKA READS: read scopes are enough, and a token Bitbucket
says can write draws a warning. Bitbucket Data Center is another API, not
this one.
"""

from __future__ import annotations

import base64
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

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
    Params,
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
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

API = "https://api.bitbucket.org/2.0"
PAGE_SIZE = 50  # the most every listing takes; pull requests stop at 50
MAX_SCOPE_OPTIONS = 1000
PULL_REQUEST_STATES = ["OPEN", "MERGED", "DECLINED", "SUPERSEDED"]
SLUG = re.compile(r"^[A-Za-z0-9_.-]+$")


class BitbucketConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(
        max_length=100, description="The workspace to read: its slug, as in bitbucket.org/acme."
    )
    repositories: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Full names ('acme/api') of the repositories to read. "
        "Empty: every repository of the workspace the token sees.",
    )

    @model_validator(mode="after")
    def _names_are_slugs_in_the_workspace(self) -> BitbucketConfig:
        if not SLUG.match(self.workspace):
            msg = f"{self.workspace!r} is not a workspace slug like 'acme'"
            raise ValueError(msg)
        for name in self.repositories or []:
            owner, _, slug = name.partition("/")
            if not SLUG.match(slug):
                msg = f"{name!r} is not a full name like 'acme/api'"
                raise ValueError(msg)
            if owner.lower() != self.workspace.lower():
                msg = f"{name!r} is not in the workspace {self.workspace!r}"
                raise ValueError(msg)
        return self


class BitbucketCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First: the stored hint is taken from the first field.
    token: SecretStr = Field(
        min_length=20,
        description="Access token (repository, project or workspace), or Atlassian API token.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    email: str | None = Field(
        default=None,
        max_length=254,
        description="Only for an Atlassian API token: the email of its account.",
    )


@register_connector
class BitbucketConnector(Connector[BitbucketConfig, BitbucketCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.BITBUCKET,
        display_name="Bitbucket",
        category=ConnectorCategory.CODE,
        auth_type="token",
        config_schema=BitbucketConfig,
        credentials_schema=BitbucketCredentials,
        capabilities=frozenset(
            {
                Capability.REPOSITORIES,
                Capability.COMMITS,
                Capability.PULL_REQUESTS,
                Capability.ISSUES,
                Capability.BRANCHES,
            }
        ),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        workspace = self.config.workspace
        async with self._client() as client:
            found = await client.get(f"/workspaces/{workspace}", missing="cet espace de travail")
            metadata: dict[str, object] = {"workspace": found.json().get("slug", workspace)}
            warnings = _write_warnings(found)
            user = await client.get_if_answered("/user")
            if user is not None:
                metadata["login"] = user.json().get("username")

            listing = await client.get(f"/repositories/{workspace}", params={"pagelen": PAGE_SIZE})
            body = listing.json()
            listed = body.get("values", [])
            more = bool(body.get("next"))
            metadata["repositories_visible"] = f"{len(listed)}+" if more else len(listed)
            capabilities = [Capability.REPOSITORIES] if listed else []
            if listed:
                # Probe what will be read: a repository in scope, if one is set.
                sample = listed[0]
                if self.config.repositories:
                    path = f"/repositories/{self.config.repositories[0]}"
                    sample = (await client.get(path, missing="ce dépôt")).json()
                capabilities += await client.probe(
                    self._per_repository(sample), params={"pagelen": 1}
                )
            else:
                warnings.append("Aucun dépôt n'est visible avec ce token.")

        return ConnectionTestResult(
            account=str(metadata.get("login") or metadata["workspace"]),
            metadata=metadata,
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            response = await client.get(f"/workspaces/{self.config.workspace}")
        near = response.headers.get("x-ratelimit-nearlimit", "").lower() == "true"
        return HealthResult(
            status=HealthStatus.DEGRADED if near else HealthStatus.HEALTHY,
            detail="quota presque épuisé" if near else None,
            checked_at=datetime.now(UTC),
        )

    async def list_scope(self) -> ScopeListing:
        options: list[ScopeOption] = []
        async with self._client() as client:
            async for repository in client.pages(f"/repositories/{self.config.workspace}"):
                if len(options) == MAX_SCOPE_OPTIONS:
                    return ScopeListing(options=options, truncated=True)
                options.append(
                    ScopeOption(
                        key=str(repository["full_name"]),
                        name=str(repository["full_name"]),
                        description=str(repository["description"])
                        if repository.get("description")
                        else None,
                        private=bool(repository.get("is_private")),
                        updated_at=parse_timestamp(repository.get("updated_on")),
                    )
                )
        return ScopeListing(options=options)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        async with self._client() as client:
            async for repository in self._repositories(client):
                if capability is Capability.REPOSITORIES:
                    yield record(
                        capability,
                        repository,
                        external_id=str(repository["uuid"]),
                        # Its own path: what scope rules match it by (LEKA-351).
                        container=str(repository["full_name"]),
                        updated=repository.get("updated_on"),
                    )
                    continue
                async for item in self._contents(client, capability, repository, since):
                    yield item

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.token.get_secret_value()
        if self.credentials.email:
            pair = f"{self.credentials.email}:{secret}".encode()
            authorization = "Basic " + base64.b64encode(pair).decode()
        else:
            authorization = f"Bearer {secret}"
        client = self.http(
            API,
            headers={
                "Accept": "application/json",
                "User-Agent": "LEKA",
                "Authorization": authorization,
            },
        )
        return VendorHttp(
            client,
            secret=secret,
            refuse=self._refuse,
            page_size=PAGE_SIZE,
            page_size_param="pagelen",
            in_body=("values", "next"),
        )

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Bitbucket's answers, as diagnostics. A 403 that names scopes is a
        token short of them, not a repository closed to it."""
        status, body = response.status_code, response.text[:200].lower()
        code = usual_code(status)
        if status == 403 and "scope" in body:
            code = DiagnosticCode.INSUFFICIENT_SCOPE
        secret = self.credentials.token.get_secret_value()
        if code is DiagnosticCode.RATE_LIMITED:
            return refusal(response, path, secret, code, retry_after=retry_after(response))
        if code is DiagnosticCode.NOT_FOUND:
            what = missing or "cette ressource"
            message = f"Bitbucket ne trouve pas {what}, ou le token ne le voit pas."
            return refusal(response, path, secret, code, message=message)
        return refusal(response, path, secret, code)

    async def _repositories(self, client: VendorHttp) -> AsyncIterator[Item]:
        """The repositories in scope. Bitbucket's names are case-insensitive."""
        wanted = {name.lower() for name in self.config.repositories or []}
        async for repository in client.pages(f"/repositories/{self.config.workspace}"):
            if not wanted or str(repository["full_name"]).lower() in wanted:
                yield repository

    @staticmethod
    def _per_repository(repository: Item) -> dict[Capability, str]:
        """Where each capability of one repository is read."""
        base = f"/repositories/{repository['full_name']}"
        main = repository.get("mainbranch")
        branch = main.get("name") if isinstance(main, dict) else None
        paths = {
            Capability.BRANCHES: f"{base}/refs/branches",
            Capability.PULL_REQUESTS: f"{base}/pullrequests",
            Capability.ISSUES: f"{base}/issues",
        }
        if branch:  # an empty repository has no main branch, and no commits
            paths[Capability.COMMITS] = f"{base}/commits/{branch}"
        if repository.get("has_issues") is False:
            del paths[Capability.ISSUES]
        return paths

    def _contents(
        self,
        client: VendorHttp,
        capability: Capability,
        repository: Item,
        since: datetime | None,
    ) -> AsyncIterator[RawRecord]:
        """One repository's records for one capability."""
        path = self._per_repository(repository).get(capability)
        if path is None:
            return nothing()
        name, rid = str(repository["full_name"]), str(repository["uuid"])
        if capability is Capability.BRANCHES:
            return records(capability, client.pages(path), name, key=lambda b: f"{rid}:{b['name']}")
        if capability is Capability.COMMITS:
            # Only roughly newest first: a rebase can put an old date ahead.
            items = client.pages(path, skip_before=since, updated_field="date")
            return records(
                capability, items, name, key=lambda c: f"{rid}:{c['hash']}", updated=_date
            )
        newest_first = {"sort": "-updated_on"}
        if capability is Capability.PULL_REQUESTS:
            query: Params = {**newest_first, "state": PULL_REQUEST_STATES}
            items = client.pages(path, query, stop_before=since, updated_field="updated_on")
            return records(capability, items, name, key=lambda p: f"{rid}:{p['id']}", updated=_on)
        if capability is Capability.ISSUES:
            items = client.pages(path, newest_first, stop_before=since, updated_field="updated_on")
            return records(capability, items, name, key=lambda i: f"{rid}:{i['id']}", updated=_on)
        msg = f"Bitbucket does not read {capability}"
        raise ValueError(msg)


def _date(item: Item) -> object:
    return item.get("date")


def _on(item: Item) -> object:
    return item.get("updated_on")


def _write_warnings(response: httpx.Response) -> list[str]:
    """Bitbucket names an OAuth-style token's scopes in a header; a scope
    that writes or administers is more than LEKA needs."""
    scopes = [s.strip() for s in response.headers.get("x-oauth-scopes", "").split(",")]
    writing = [s for s in scopes if s and ("write" in s or "admin" in s or "delete" in s)]
    if not writing:
        return []
    return [
        "Ce token permet d'écrire (" + ", ".join(writing) + "). LEKA ne fait que lire : "
        "des permissions de lecture suffisent et limitent l'exposition."
    ]
