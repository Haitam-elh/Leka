"""The ClickUp connector — clickup.com, through its REST API (v2).

ClickUp is read at https://api.clickup.com/api/v2 with a personal token
(pk_…), sent as it is in the Authorization header. A personal token can do
what its owner can, and ClickUp cannot narrow it to reading: the
documentation asks for a dedicated member, and every call here is a GET.

ClickUp nests Workspaces (its API says "teams"), Spaces, Folders, Lists and
Tasks. The scope is Spaces; what LEKA reads is Lists — projects — and
Tasks.

test_connection: who am I (GET /user), in which Workspaces and with what
role (GET /team — a warning for an owner or an admin), which Spaces, is
every Space in scope among them, and — in one Space, in scope if a scope is
set — can I read its Lists and its Tasks.

check_health: GET /user, reading X-RateLimit-*. Degraded under a tenth left.

list_scope: every Space of every Workspace the token sees.

iter_resources: Lists — in Folders and outside them — whole each pass;
Tasks, Workspace by Workspace, closed ones and subtasks included, 100 a
page, filtered by ClickUp on `date_updated` for an incremental pass.
"""

from __future__ import annotations

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
    Params,
    VendorHttp,
    quota_of,
    record,
    refusal,
    retry_after,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

API = "https://api.clickup.com/api/v2"
PAGE_SIZE = 100  # ClickUp's, fixed: a shorter page is the last
MAX_PAGES = 1000  # 100 000 tasks a Workspace, per pass
MAX_SCOPE_OPTIONS = 1000
SPACE_ID = re.compile(r"^[0-9]{1,20}$")
# Roles in a Workspace: 1 owner, 2 admin, 3 member, 4 guest.
ADMIN_ROLES = frozenset({1, 2})
# ClickUp's codes for "this Workspace was not authorised for this token".
UNAUTHORISED_TEAM = re.compile(r"^OAUTH_0(?:23|26|27|29|3[0-9]|4[0-5])$")


class ClickUpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spaces: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Ids of the Spaces to read. Empty: every Space the token can see.",
    )

    @field_validator("spaces")
    @classmethod
    def _ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        ids = [space.strip() for space in value]
        for space in ids:
            if not SPACE_ID.match(space):
                msg = f"{space!r} is not the id of a ClickUp Space"
                raise ValueError(msg)
        return list(dict.fromkeys(ids))


class ClickUpCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr = Field(
        min_length=20,
        description="A personal token (pk_…), from Settings → Apps → API Token.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class ClickUpConnector(Connector[ClickUpConfig, ClickUpCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.CLICKUP,
        display_name="ClickUp",
        category=ConnectorCategory.PROJECT,
        auth_type="token",
        config_schema=ClickUpConfig,
        credentials_schema=ClickUpCredentials,
        capabilities=frozenset({Capability.PROJECTS, Capability.ISSUES}),
        # Lists come whole every pass; tasks filtered by `date_updated`.
        listed_whole=frozenset({Capability.PROJECTS}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            user = (await client.get("/user")).json().get("user") or {}
            teams = await self._teams(client)
            spaces = await self._spaces(client, teams)
            self._require_scope(spaces)
            chosen = self._in_scope(spaces)
            warnings: list[str] = []
            if any(_role(team, user) in ADMIN_ROLES for team in teams):
                warnings.append(
                    "Ce jeton appartient à un propriétaire ou un administrateur de l'espace de "
                    "travail ClickUp. LEKA ne fait que lire : le jeton d'un membre suffit."
                )
            capabilities: list[Capability] = []
            if chosen:
                team, space = chosen[0]
                capabilities = await client.probe(
                    {
                        Capability.PROJECTS: f"/space/{space['id']}/list?archived=false",
                        Capability.ISSUES: f"/team/{team}/task?page=0&space_ids[]={space['id']}",
                    }
                )
            else:
                warnings.append("Aucun espace (Space) n'est visible avec ce jeton.")

        return ConnectionTestResult(
            account=str(user.get("email") or user.get("username") or "ClickUp"),
            metadata={
                "workspaces": [str(team.get("name")) for team in teams],
                "spaces_visible": len(spaces),
            },
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            response = await client.get("/user")
        quota = quota_of(response)
        return HealthResult(
            status=HealthStatus.DEGRADED if quota and quota.low else HealthStatus.HEALTHY,
            detail=f"quota {quota.remaining}/{quota.limit}" if quota else None,
            checked_at=datetime.now(UTC),
        )

    async def list_scope(self) -> ScopeListing:
        async with self._client() as client:
            teams = await self._teams(client)
            spaces = await self._spaces(client, teams)
        names = {str(team["id"]): str(team.get("name") or "") for team in teams}
        options = [
            ScopeOption(
                key=str(space["id"]),
                name=str(space.get("name") or space["id"]),
                description=names.get(team) or None,
                private=space.get("private") is True,
            )
            for team, space in spaces[:MAX_SCOPE_OPTIONS]
        ]
        return ScopeListing(options=options, truncated=len(spaces) > MAX_SCOPE_OPTIONS)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"ClickUp does not read {capability}"
            raise ValueError(msg)
        async with self._client() as client:
            chosen = self._in_scope(await self._spaces(client, await self._teams(client)))
            if capability is Capability.PROJECTS:
                for _, space in chosen:
                    async for found in self._lists(client, str(space["id"])):
                        yield record(
                            capability,
                            found,
                            external_id=str(found["id"]),
                            container=str(space["id"]),
                        )
                return
            by_team: dict[str, list[str]] = {}
            for team, space in chosen:
                by_team.setdefault(team, []).append(str(space["id"]))
            for team, space_ids in by_team.items():
                async for task in self._tasks(client, team, space_ids, since):
                    yield record(
                        capability,
                        task,
                        external_id=str(task["id"]),
                        container=_id(task.get("list")),
                        updated=_from_ms(task.get("date_updated")),
                    )

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.token.get_secret_value()
        client = self.http(
            API,
            headers={
                "Accept": "application/json",
                "User-Agent": "LEKA",
                # A personal token goes as it is; "Bearer" is for OAuth.
                "Authorization": secret,
            },
        )
        return VendorHttp(client, secret=secret, refuse=self._refuse, page_size=PAGE_SIZE)

    async def _teams(self, client: VendorHttp) -> list[dict[str, Any]]:
        teams = (await client.get("/team")).json().get("teams")
        return teams if isinstance(teams, list) else []

    async def _spaces(
        self, client: VendorHttp, teams: list[dict[str, Any]]
    ) -> list[tuple[str, Item]]:
        """Every Space of every Workspace, with the Workspace it is in."""
        found: list[tuple[str, Item]] = []
        for team in teams:
            response = await client.get(f"/team/{team['id']}/space", params={"archived": "false"})
            for space in response.json().get("spaces") or []:
                found.append((str(team["id"]), space))
        return found

    def _in_scope(self, spaces: list[tuple[str, Item]]) -> list[tuple[str, Item]]:
        if not self.config.spaces:
            return spaces
        wanted = set(self.config.spaces)
        return [(team, space) for team, space in spaces if str(space["id"]) in wanted]

    def _require_scope(self, spaces: list[tuple[str, Item]]) -> None:
        """Every Space in scope must be one this token can see."""
        known = {str(space["id"]) for _, space in spaces}
        missing = [space for space in self.config.spaces or [] if space not in known]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"ClickUp ne montre pas ces espaces à ce jeton : {named}.",
            )

    async def _lists(self, client: VendorHttp, space: str) -> AsyncIterator[Item]:
        """A Space's Lists: those in its Folders, then those outside any."""
        folders = await client.get(f"/space/{space}/folder", params={"archived": "false"})
        for folder in folders.json().get("folders") or []:
            where = {"id": folder.get("id"), "name": folder.get("name")}
            for found in folder.get("lists") or []:
                yield {**found, "folder": found.get("folder") or where}
        loose = await client.get(f"/space/{space}/list", params={"archived": "false"})
        for found in loose.json().get("lists") or []:
            yield found

    async def _tasks(
        self, client: VendorHttp, team: str, space_ids: list[str], since: datetime | None
    ) -> AsyncIterator[Item]:
        """A Workspace's Tasks in these Spaces, page after page, in the order
        they were created — an order an edit during the pass cannot shuffle."""
        params: dict[str, str | int | list[str]] = {
            "include_closed": "true",
            "subtasks": "true",
            "include_markdown_description": "true",
            "space_ids[]": space_ids,
        }
        if since:
            params["date_updated_gt"] = int(since.timestamp() * 1000)
        for page in range(MAX_PAGES):
            query: Params = {**params, "page": page}
            body = (await client.get(f"/team/{team}/task", params=query)).json()
            tasks = body.get("tasks") or []
            for task in tasks:
                yield task
            if body.get("last_page") is True or len(tasks) < PAGE_SIZE:
                return
        raise diagnose(
            DiagnosticCode.PROVIDER_ERROR,
            detail=f"ClickUp gave more than {MAX_PAGES} pages of tasks",
        )

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """ClickUp's refusals, as diagnostics: its ECODE first, the status
        when it says nothing."""
        secret = self.credentials.token.get_secret_value()
        status, code = response.status_code, _ecode(response)
        if status == 429:
            return refusal(
                response,
                path,
                secret,
                DiagnosticCode.RATE_LIMITED,
                retry_after=retry_after(response, "x-ratelimit-reset"),
            )
        if UNAUTHORISED_TEAM.match(code):
            message = "Cet espace de travail ClickUp n'a pas été autorisé pour ce jeton."
            return refusal(
                response, path, secret, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        if status == 401:
            message = "ClickUp refuse ce jeton."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 404:
            what = missing or "cet espace"
            message = f"ClickUp ne trouve pas {what}, ou ce jeton ne le voit pas."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        return refusal(response, path, secret, usual_code(status))


def _role(team: dict[str, Any], user: dict[str, Any]) -> int | None:
    """The user's role in a Workspace, from its members."""
    for member in team.get("members") or []:
        if isinstance(member, dict) and _id(member.get("user")) == str(user.get("id")):
            role = member["user"].get("role")
            return role if isinstance(role, int) else None
    return None


def _id(item: Any) -> str | None:
    return str(item["id"]) if isinstance(item, dict) and item.get("id") else None


def _from_ms(value: object) -> str | None:
    """ClickUp's dates are milliseconds since the epoch, as a string."""
    if value is None or not str(value).isdigit():
        return None
    return datetime.fromtimestamp(int(str(value)) / 1000, tz=UTC).isoformat()


def _ecode(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("ECODE") or "") if isinstance(body, dict) else ""
