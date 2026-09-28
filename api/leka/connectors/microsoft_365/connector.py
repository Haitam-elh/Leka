"""The Microsoft 365 connector — SharePoint, OneDrive, and the Word, Excel
and PowerPoint files in them.

Microsoft 365 is read through Microsoft Graph (v1.0), at
https://graph.microsoft.com/v1.0, by an application registered in the
customer's Microsoft Entra tenant, with its client secret (the
client-credentials grant, leka/connectors/microsoft.py). The application is
given Graph's *application* permissions Sites.Read.All and Files.Read.All —
read, never write — and User.Read.All to find the users' OneDrives, all
with an admin's consent. Those are the boundary.

test_connection: a token, the tenant's root site (GET /sites/root — its
host is the account), every drive in scope (GET /drives/{id}), whether the
users can be listed (their OneDrives), and one page of files in the first
drive.

check_health: a token and GET /sites/root.

list_scope: the drives — each site's document libraries, and each user's
OneDrive — at most MAX_SCOPE_CALLS calls to Graph.

iter_resources: drives, whole each pass; files, drive by drive, through
Graph's delta — every item on an initial pass, and from a timestamp on an
incremental one (SharePoint and OneDrive for Business take one in place of
a delta token). Folders, deleted items and OneNote packages are left out.
A file comes with its text where one can be had: Word, Excel, PowerPoint
and plain text files, downloaded and read (leka/connectors/office.py), up
to MAX_DOWNLOAD.

A file's content is not at Graph: Graph answers 302 with a
pre-authenticated link on the tenant's SharePoint host. The link is
followed only to a SharePoint host, over https, without LEKA's token — the
link carries its own — and httpx does not log it (leka/core/logging.py).

LEKA READS. Every call is a GET; the one POST is the token exchange.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from leka.connectors import microsoft, office
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
    dig,
    parse_timestamp,
    record,
    refusal,
    retry_after,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
PAGE_SIZE = 200
MAX_SCOPE_OPTIONS = 1000
MAX_SCOPE_CALLS = 300
MAX_DOWNLOAD = 10 * 1024 * 1024  # bytes
# Graph writes lastModifiedDateTime a moment after the change.
UPDATE_MARGIN = timedelta(minutes=2)
UUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
DRIVE_ID = re.compile(r"^[A-Za-z0-9!_-]{8,200}$")
# Where Graph sends a file's content: the tenant's SharePoint, in one of
# Microsoft's clouds.
SHAREPOINT = (".sharepoint.com", ".sharepoint.us", ".sharepoint.de", ".sharepoint.cn")
DRIVE_FIELDS = "id,name,driveType,webUrl,createdDateTime,lastModifiedDateTime,owner"
ITEM_FIELDS = (
    "id,name,file,folder,package,deleted,root,size,createdDateTime,lastModifiedDateTime,"
    "webUrl,parentReference,createdBy,lastModifiedBy"
)


class Microsoft365Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(description="The Microsoft Entra tenant (directory) id.")
    drives: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Ids of the drives to read — document libraries and OneDrives. Empty: "
        "every drive the application can see.",
    )

    @field_validator("tenant_id")
    @classmethod
    def _a_tenant(cls, value: str) -> str:
        if not UUID.match(value.strip()):
            msg = f"{value!r} is not a tenant id like '00000000-0000-0000-0000-000000000000'"
            raise ValueError(msg)
        return value.strip().lower()

    @field_validator("drives")
    @classmethod
    def _ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        ids = [drive.strip() for drive in value]
        for drive in ids:
            if not DRIVE_ID.match(drive):
                msg = f"{drive!r} is not the id of a Microsoft 365 drive"
                raise ValueError(msg)
        return list(dict.fromkeys(ids))


class Microsoft365Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First: the stored hint is taken from the first field — the application
    # id names the application, and says nothing of the secret.
    client_id: str = Field(min_length=36, max_length=36, description="The application (client) id.")
    client_secret: SecretStr = Field(
        min_length=8,
        max_length=512,
        description="Its client secret.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class Microsoft365Connector(Connector[Microsoft365Config, Microsoft365Credentials]):
    manifest = ConnectorManifest(
        key=SourceKind.MICROSOFT_365,
        display_name="Microsoft 365",
        category=ConnectorCategory.DOCS,
        auth_type="token",
        config_schema=Microsoft365Config,
        credentials_schema=Microsoft365Credentials,
        capabilities=frozenset({Capability.DRIVES, Capability.FILES}),
        # Drives come whole every pass; files through delta, from a time.
        listed_whole=frozenset({Capability.DRIVES}),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._token: str | None = None

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with await self._client() as client:
            root = (
                await client.get("/sites/root", params={"$select": "id,displayName,webUrl"})
            ).json()
            if self.config.drives:
                await self._require_scope(client)
                sample: str | None = self.config.drives[0]
            else:
                default = await client.get("/sites/root/drive", params={"$select": "id"}, empty=404)
                sample = None if default.status_code == 404 else str(default.json()["id"])
            warnings: list[str] = []
            if await client.get_if_answered("/users?$select=id&$top=1") is None:
                warnings.append(
                    "Sans la permission User.Read.All, LEKA ne voit pas les OneDrive des "
                    "utilisateurs : seulement les bibliothèques SharePoint."
                )
            capabilities = [Capability.DRIVES]
            if sample is not None:
                capabilities += await client.probe(
                    {Capability.FILES: f"/drives/{sample}/root/children?$top=1&$select=id"}
                )
        return ConnectionTestResult(
            account=httpx.URL(str(root.get("webUrl") or GRAPH)).host,
            metadata={"root_site": root.get("displayName")},
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with await self._client() as client:
            await client.get("/sites/root", params={"$select": "id"})
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        options: list[ScopeOption] = []
        async with await self._client() as client:
            budget = _Budget(MAX_SCOPE_CALLS)
            async for drive, where in self._every_drive(client, budget):
                if len(options) == MAX_SCOPE_OPTIONS:
                    return ScopeListing(options=options, truncated=True)
                options.append(
                    ScopeOption(
                        key=str(drive["id"]),
                        name=f"{where} — {drive.get('name') or drive['id']}",
                        description="OneDrive"
                        if drive.get("driveType") == "business"
                        else "SharePoint",
                        updated_at=parse_timestamp(drive.get("lastModifiedDateTime")),
                    )
                )
            return ScopeListing(options=options, truncated=budget.spent)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Microsoft 365 does not read {capability}"
            raise ValueError(msg)
        async with await self._client() as client:
            drives = [drive async for drive in self._drives(client)]
            if capability is Capability.DRIVES:
                for drive in drives:
                    yield record(
                        capability,
                        drive,
                        external_id=str(drive["id"]),
                        updated=drive.get("lastModifiedDateTime"),
                    )
                return
            for drive in drives:
                drive_id = str(drive["id"])
                params: dict[str, str | int] = {"$select": ITEM_FIELDS}
                if since:
                    after = (since - UPDATE_MARGIN).astimezone(UTC)
                    params["token"] = after.strftime("%Y-%m-%dT%H:%M:%SZ")
                seen: set[str] = set()
                async for item in client.pages(f"/drives/{drive_id}/root/delta", params):
                    if not _a_file(item) or item["id"] in seen:
                        continue
                    seen.add(str(item["id"]))
                    payload: Item = dict(item)
                    text = await self._text(client, drive_id, item)
                    payload["content"] = text.text if text else None
                    payload["content_truncated"] = bool(text and text.truncated)
                    yield record(
                        capability,
                        payload,
                        external_id=str(item["id"]),
                        container=drive_id,
                        updated=item.get("lastModifiedDateTime"),
                    )

    # ── inside ───────────────────────────────────────────────────────────────

    async def _client(self) -> VendorHttp:
        if self._token is None:
            self._token = await microsoft.client_credentials_token(
                self.http,
                self.config.tenant_id,
                self.credentials.client_id,
                self.credentials.client_secret.get_secret_value(),
                GRAPH_SCOPE,
            )
        return VendorHttp(
            self.http(
                GRAPH, headers={"Authorization": f"Bearer {self._token}", "User-Agent": "LEKA"}
            ),
            secret=self.credentials.client_secret.get_secret_value(),
            refuse=self._refuse,
            page_size=PAGE_SIZE,
            page_size_param="$top",
            in_body=("value", "@odata.nextLink"),
        )

    async def _drives(self, client: VendorHttp) -> AsyncIterator[Item]:
        """The drives in scope, each asked of Graph — or every drive."""
        if self.config.drives:
            for drive_id in self.config.drives:
                response = await client.get(
                    f"/drives/{drive_id}", params={"$select": DRIVE_FIELDS}, empty=404
                )
                if response.status_code != 404:  # gone since the test: swept
                    yield response.json()
            return
        async for drive, _ in self._every_drive(client, _Budget(None)):
            yield drive

    async def _every_drive(
        self, client: VendorHttp, budget: _Budget
    ) -> AsyncIterator[tuple[Item, str]]:
        """Each site's libraries, then each user's OneDrive, with whose they
        are. The users are skipped when the application may not list them."""
        async for site in client.pages("/sites", {"search": "*", "$select": "id,displayName"}):
            if not budget.spend():
                return
            libraries = client.pages(f"/sites/{site['id']}/drives", {"$select": DRIVE_FIELDS})
            async for drive in libraries:
                yield drive, str(site.get("displayName") or site["id"])
        try:
            users = [
                user
                async for user in client.pages(
                    "/users", {"$select": "id,displayName,userPrincipalName"}
                )
            ]
        except ConnectorError as error:
            if error.diagnostic.code is DiagnosticCode.PERMISSION_DENIED:
                return  # no User.Read.All: SharePoint only, as the test said
            raise
        for user in users:
            if not budget.spend():
                return
            response = await client.get(
                f"/users/{user['id']}/drive", params={"$select": DRIVE_FIELDS}, empty=404
            )
            if response.status_code != 404:  # a user without a OneDrive
                yield response.json(), str(user.get("displayName") or user["id"])

    async def _require_scope(self, client: VendorHttp) -> None:
        """Every drive in scope must be one the application can see."""
        missing: list[str] = []
        for drive_id in self.config.drives or []:
            response = await client.get(f"/drives/{drive_id}", params={"$select": "id"}, empty=404)
            if response.status_code == 404:
                missing.append(drive_id)
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"Microsoft Graph ne montre pas ces drives à l'application : {named}.",
            )

    async def _text(self, client: VendorHttp, drive_id: str, item: Item) -> office.Text | None:
        """A file's text, where one can be had; None otherwise."""
        kind = office.kind_of(str(dig(item, "file.mimeType") or ""), str(item.get("name") or ""))
        size = int(str(item.get("size") or 0))
        if kind is None or size > MAX_DOWNLOAD:
            return None
        try:
            response = await client.get(f"/drives/{drive_id}/items/{item['id']}/content", empty=302)
        except ConnectorError as error:
            if error.diagnostic.code in (
                DiagnosticCode.PERMISSION_DENIED,
                DiagnosticCode.NOT_FOUND,
            ):
                return None
            raise
        if response.status_code != 302:
            return office.text_of(response.content[:MAX_DOWNLOAD], kind)
        data = await self._download(response.headers.get("location", ""))
        return office.text_of(data, kind) if data is not None else None

    async def _download(self, location: str) -> bytes | None:
        """The bytes behind Graph's pre-authenticated link — only on a
        SharePoint host, over https, without LEKA's token. None when the
        link goes elsewhere or the file is not handed over."""
        url = httpx.URL(location)
        if url.scheme != "https" or not url.host.endswith(SHAREPOINT):
            return None
        async with self.http(f"https://{url.host}", headers={"User-Agent": "LEKA"}) as sharepoint:
            try:
                response = await sharepoint.get(url.raw_path.decode("ascii"))
            except httpx.HTTPError:
                return None
        if not response.is_success or len(response.content) > MAX_DOWNLOAD:
            return None
        return response.content

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Microsoft Graph's answers, as diagnostics: its error's code first."""
        secret = self.credentials.client_secret.get_secret_value()
        status, code = response.status_code, str(dig(_body(response), "error.code") or "")
        if status in (429, 503) and "retry-after" in response.headers:
            return refusal(
                response,
                path,
                secret,
                DiagnosticCode.RATE_LIMITED,
                retry_after=retry_after(response),
            )
        if status == 401:
            message = "Microsoft Graph refuse le jeton de cette application."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 403 or code in ("accessDenied", "Authorization_RequestDenied"):
            message = (
                "Microsoft Graph refuse cette lecture : l'application doit avoir les permissions "
                "Sites.Read.All et Files.Read.All (application), avec le consentement d'un "
                "administrateur."
            )
            return refusal(
                response, path, secret, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        if status == 404:
            what = missing or "ce drive"
            message = f"Microsoft Graph ne trouve pas {what}, ou l'application ne le voit pas."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        return refusal(response, path, secret, usual_code(status))


class _Budget:
    """How many more calls a listing may make; None for no end."""

    def __init__(self, calls: int | None) -> None:
        self._left = calls
        self.spent = False

    def spend(self) -> bool:
        if self._left is None:
            return True
        if self._left <= 0:
            self.spent = True
            return False
        self._left -= 1
        return True


def _a_file(item: Item) -> bool:
    """A file — not a folder, not the root, not a OneNote package, not gone."""
    return "file" in item and not any(
        key in item for key in ("folder", "root", "package", "deleted")
    )


def _body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {}
