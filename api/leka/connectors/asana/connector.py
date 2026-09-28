"""The Asana connector — app.asana.com, through its REST API (1.0).

Asana is read at https://app.asana.com/api/1.0 with a personal access
token, as Bearer. A token can do what its owner can, and Asana cannot
narrow it to reading: the documentation asks for a dedicated member, and
every call here is a GET.

test_connection: who am I, in which workspaces (GET /users/me), are the
projects in scope there (GET /projects/{gid}), what can I see (one page of
projects), and — in one project, in scope if a scope is set — can I read
its tasks.

check_health: GET /users/me. Asana sends no quota headers; a refusal for
the rate says when to come back (Retry-After).

list_scope: every project of every workspace the token sees, archived ones
included, by gid.

iter_resources: projects — the ones in scope, or every project of every
workspace — whole each pass; then tasks, project by project, which Asana
filters by `modified_since` on an incremental pass. A task in several
projects is read once per pass.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
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
from leka.connectors.http import (
    Item,
    VendorHttp,
    parse_timestamp,
    record,
    refusal,
    retry_after,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

API = "https://app.asana.com/api/1.0"
PAGE_SIZE = 100  # Asana's maximum
MAX_SCOPE_OPTIONS = 1000
# A gid: Asana's ids are digits, and long.
GID = re.compile(r"^[0-9]{1,24}$")
# A project's link, new form (/1/<workspace>/project/<gid>/…) or old (/0/<gid>/…).
PROJECT_LINK = re.compile(r"app\.asana\.com/(?:1/[0-9]+/project|0)/([0-9]+)")

ME_FIELDS = "name,email,workspaces.name"
PROJECT_FIELDS = (
    "name,notes,archived,color,created_at,modified_at,start_on,due_on,completed,"
    "completed_at,owner.name,owner.email,team.name,workspace.name,permalink_url"
)
TASK_FIELDS = (
    "name,notes,resource_subtype,completed,completed_at,created_at,modified_at,"
    "start_on,due_on,due_at,assignee.name,assignee.email,parent.name,"
    "memberships.project.name,memberships.section.name,tags.name,"
    "custom_fields.name,custom_fields.display_value,num_subtasks,permalink_url"
)


def project_gid(value: str) -> str:
    """A project's gid, from what an admin typed or pasted — "1204…", or a
    link to the project. Anything else is refused."""
    text = value.strip()
    found = PROJECT_LINK.search(text)
    gid = found.group(1) if found else text
    if not GID.match(gid):
        msg = f"{value!r} is not the gid or the link of an Asana project"
        raise ValueError(msg)
    return gid


class AsanaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Gids of the projects to read. Empty: every project the token can see.",
    )

    @field_validator("projects")
    @classmethod
    def _gids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(project_gid(project) for project in value))


class AsanaCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr = Field(
        min_length=20,
        description="A personal access token, from My settings → Apps → Developer apps.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class AsanaConnector(Connector[AsanaConfig, AsanaCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.ASANA,
        display_name="Asana",
        category=ConnectorCategory.PROJECT,
        auth_type="token",
        config_schema=AsanaConfig,
        credentials_schema=AsanaCredentials,
        capabilities=frozenset({Capability.PROJECTS, Capability.ISSUES}),
        # Projects come whole every pass; tasks filtered by `modified_since`.
        listed_whole=frozenset({Capability.PROJECTS}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            me = await self._me(client)
            workspaces = me.get("workspaces") or []
            metadata: dict[str, object] = {
                "workspaces": [str(w.get("name")) for w in workspaces],
            }
            if self.config.projects:
                await self._require_scope(client)
                sample: str | None = self.config.projects[0]
            else:
                sample = None
                if workspaces:
                    first = await client.get(
                        "/projects",
                        params={
                            "workspace": str(workspaces[0]["gid"]),
                            "limit": PAGE_SIZE,
                            "opt_fields": "name",
                        },
                    )
                    body = first.json()
                    listed = body.get("data") or []
                    more = bool(body.get("next_page"))
                    metadata["projects_visible"] = f"{len(listed)}+" if more else len(listed)
                    sample = str(listed[0]["gid"]) if listed else None
            capabilities: list[Capability] = []
            warnings: list[str] = []
            if sample is None:
                warnings.append("Aucun projet n'est visible avec ce token.")
            else:
                capabilities = await client.probe(
                    {
                        Capability.PROJECTS: f"/projects/{sample}",
                        Capability.ISSUES: f"/tasks?project={sample}&limit=1",
                    }
                )

        return ConnectionTestResult(
            account=str(me.get("email") or me.get("name") or "Asana"),
            metadata=metadata,
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            await client.get("/users/me", params={"opt_fields": "name"})
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        options: list[ScopeOption] = []
        async with self._client() as client:
            me = await self._me(client)
            for workspace in me.get("workspaces") or []:
                params = {"workspace": str(workspace["gid"]), "opt_fields": PROJECT_FIELDS}
                async for project in client.pages("/projects", params):
                    if len(options) == MAX_SCOPE_OPTIONS:
                        return ScopeListing(options=options, truncated=True)
                    where = str(workspace.get("name") or "")
                    options.append(
                        ScopeOption(
                            key=str(project["gid"]),
                            name=str(project.get("name") or project["gid"]),
                            description=f"{where} · archivé" if project.get("archived") else where,
                            updated_at=parse_timestamp(project.get("modified_at")),
                        )
                    )
        return ScopeListing(options=options)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Asana does not read {capability}"
            raise ValueError(msg)
        async with self._client() as client:
            if capability is Capability.PROJECTS:
                async for project in self._projects(client, PROJECT_FIELDS):
                    yield record(
                        capability,
                        project,
                        external_id=str(project["gid"]),
                        container=_gid(project.get("workspace")),
                        updated=project.get("modified_at"),
                    )
                return
            seen: set[str] = set()
            async for project in self._projects(client, "name"):
                params = {"project": str(project["gid"]), "opt_fields": TASK_FIELDS}
                if since:
                    params["modified_since"] = since.isoformat()
                async for task in client.pages("/tasks", params):
                    if task["gid"] in seen:
                        continue  # in a project already read
                    seen.add(str(task["gid"]))
                    yield record(
                        capability,
                        task,
                        external_id=str(task["gid"]),
                        container=str(project["gid"]),
                        updated=task.get("modified_at"),
                    )

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.token.get_secret_value()
        client = self.http(
            API,
            headers={
                "Accept": "application/json",
                "User-Agent": "LEKA",
                "Authorization": f"Bearer {secret}",
            },
        )
        return VendorHttp(
            client,
            secret=secret,
            refuse=self._refuse,
            page_size=PAGE_SIZE,
            page_size_param="limit",
            in_body=("data", "next_page.offset"),
            page_cursor_param="offset",
        )

    async def _me(self, client: VendorHttp) -> dict[str, Any]:
        response = await client.get("/users/me", params={"opt_fields": ME_FIELDS})
        found = response.json().get("data")
        return found if isinstance(found, dict) else {}

    async def _projects(self, client: VendorHttp, fields: str) -> AsyncIterator[Item]:
        """The projects in scope, or every project of every workspace."""
        if self.config.projects:
            for gid in self.config.projects:
                response = await client.get(
                    f"/projects/{gid}", params={"opt_fields": fields}, empty=404
                )
                if response.status_code != 404:  # gone since the test: swept
                    yield response.json()["data"]
            return
        me = await self._me(client)
        for workspace in me.get("workspaces") or []:
            params = {"workspace": str(workspace["gid"]), "opt_fields": fields}
            async for project in client.pages("/projects", params):
                yield project

    async def _require_scope(self, client: VendorHttp) -> None:
        """Every project in scope must be one this token can see."""
        projects = self.config.projects or []
        answers = await asyncio.gather(
            *(
                client.get(f"/projects/{gid}", params={"opt_fields": "name"}, empty=404)
                for gid in projects
            )
        )
        missing = [
            gid for gid, answer in zip(projects, answers, strict=True) if answer.status_code == 404
        ]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"Asana ne montre pas ces projets à ce token : {named}.",
            )

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Asana's refusals, as diagnostics. 402 is a feature of a paid plan."""
        secret = self.credentials.token.get_secret_value()
        status = response.status_code
        if status == 429:
            return refusal(
                response,
                path,
                secret,
                DiagnosticCode.RATE_LIMITED,
                retry_after=retry_after(response),
            )
        if status == 401:
            message = "Asana refuse ce token d'accès."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 402:
            message = "Cette lecture demande une offre Asana payante."
            return refusal(
                response, path, secret, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        if status == 404:
            what = missing or "ce projet"
            message = f"Asana ne trouve pas {what}, ou ce token ne le voit pas."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        return refusal(response, path, secret, usual_code(status))


def _gid(item: Any) -> str | None:
    return str(item["gid"]) if isinstance(item, dict) and item.get("gid") else None
