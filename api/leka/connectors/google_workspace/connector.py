"""The Google Workspace connector — Drive, and the Docs, Sheets and Slides in it.

Google Workspace is read through the Drive API (v3), at
https://www.googleapis.com/drive/v3, by a service account under the
`drive.readonly` scope — a token that cannot write, whoever it acts as.

The service account acts as itself, and then sees only what was shared
with its address; or, when a Workspace admin granted it domain-wide
delegation for `drive.readonly`, as the user named in `subject` — a
dedicated account, which sees what that account sees. Either way, Drive's
own sharing is the boundary.

test_connection: a token (leka/connectors/google.py), who am I (GET
/about), which shared drives (GET /drives), is every drive in scope among
them, and one page of files in the first.

check_health: a token and GET /about.

list_scope: "user" — the account's My Drive and what is shared with it —
and every shared drive the account is a member of.

iter_resources: shared drives, whole each pass; files, drive by drive,
folders and trashed ones left out, Drive filtering an incremental pass by
`modifiedTime`. A file comes with its text where one can be had: Docs and
Slides exported as plain text, Sheets as CSV (the first sheet — Drive's
export), Word, Excel and PowerPoint files and plain text downloaded and
read (leka/connectors/office.py), up to MAX_DOWNLOAD. Other files come
without text.

LEKA READS. Every call is a GET; the one POST is the token exchange.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from leka.connectors import google, office
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

API = "https://www.googleapis.com/drive/v3"
READ_ONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
MY_DRIVE = "user"
FILE_PAGE = 1000  # Drive's maximum
DRIVE_PAGE = 100  # Drive's maximum for shared drives
MAX_SCOPE_OPTIONS = 1000
MAX_DOWNLOAD = 10 * 1024 * 1024  # bytes: Drive's own export limit
# Drive writes modifiedTime a moment after the change.
UPDATE_MARGIN = timedelta(minutes=2)
FOLDER = "application/vnd.google-apps.folder"
# Google's own formats, and what each is exported as for its text.
EXPORTS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
}
FILE_FIELDS = (
    "id,name,mimeType,description,createdTime,modifiedTime,size,webViewLink,parents,"
    "driveId,version,owners(displayName,emailAddress),"
    "lastModifyingUser(displayName,emailAddress)"
)
DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
DRIVE_LINK = re.compile(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]{8,64})")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Drive's reasons for a 403 that is a quota, not a refusal.
BUSY = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded"})


def drive_key(value: str) -> str:
    """A scope entry: "user", a shared drive's id, or a pasted link to it."""
    text = value.strip()
    if text.lower() == MY_DRIVE:
        return MY_DRIVE
    found = DRIVE_LINK.search(text)
    drive = found.group(1) if found else text
    if not DRIVE_ID.match(drive):
        msg = f"{value!r} is not 'user' nor the id or the link of a shared drive"
        raise ValueError(msg)
    return drive


class GoogleWorkspaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(
        default=None,
        max_length=254,
        description="The user the service account acts as, by domain-wide delegation. "
        "Empty: the service account itself, which sees what is shared with its address.",
    )
    drives: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="'user' for My Drive, and ids of shared drives. Empty: all of them.",
    )

    @field_validator("subject")
    @classmethod
    def _an_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        if not EMAIL.match(value.strip()):
            msg = f"{value!r} is not an email address"
            raise ValueError(msg)
        return value.strip().lower()

    @field_validator("drives")
    @classmethod
    def _keys(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(drive_key(drive) for drive in value))


class GoogleWorkspaceCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_account_key: SecretStr = Field(
        min_length=100,
        max_length=10_000,
        description="The service account's JSON key, as downloaded.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )

    @model_validator(mode="after")
    def _is_a_service_account_key(self) -> GoogleWorkspaceCredentials:
        google.service_account_key(self.service_account_key.get_secret_value())
        return self


@register_connector
class GoogleWorkspaceConnector(Connector[GoogleWorkspaceConfig, GoogleWorkspaceCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.GOOGLE_WORKSPACE,
        display_name="Google Workspace",
        category=ConnectorCategory.DOCS,
        auth_type="token",
        config_schema=GoogleWorkspaceConfig,
        credentials_schema=GoogleWorkspaceCredentials,
        capabilities=frozenset({Capability.DRIVES, Capability.FILES}),
        # Shared drives come whole every pass; files by `modifiedTime`.
        listed_whole=frozenset({Capability.DRIVES}),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._token: str | None = None

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with await self._client() as client:
            about = await self._about(client)
            drives = await self._shared_drives(client)
            self._require_scope(drives)
            corpus = self._corpora(drives)[0]
            first = await client.get(
                "/files",
                params={
                    **corpus,
                    "q": _query(None),
                    "pageSize": 100,
                    "fields": "nextPageToken,files(id)",
                },
            )
        body = first.json()
        listed = body.get("files") or []
        visible = f"{len(listed)}+" if body.get("nextPageToken") else len(listed)
        warnings: list[str] = []
        if not listed and not drives:
            warnings.append(
                "Rien n'est visible : partagez des dossiers ou des Drive partagés avec "
                f"{self._key()['client_email']}, ou configurez la délégation au niveau du "
                "domaine et un utilisateur délégué."
            )
        return ConnectionTestResult(
            account=str(dig(about, "user.emailAddress") or self._key()["client_email"]),
            metadata={
                "acting_as": self.config.subject,
                "shared_drives_visible": len(drives),
                "files_visible": visible,
            },
            capabilities=[Capability.DRIVES, Capability.FILES],
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with await self._client() as client:
            await self._about(client)
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        async with await self._client() as client:
            drives = await self._shared_drives(client)
        who = self.config.subject or self._key()["client_email"]
        options = [
            ScopeOption(
                key=MY_DRIVE,
                name="Mon Drive",
                description=f"Le Drive de {who}, et ce qui est partagé avec lui",
            )
        ]
        options += [
            ScopeOption(
                key=str(drive["id"]),
                name=str(drive.get("name") or drive["id"]),
                description="Drive partagé",
                updated_at=parse_timestamp(drive.get("createdTime")),
            )
            for drive in drives[: MAX_SCOPE_OPTIONS - 1]
        ]
        return ScopeListing(options=options, truncated=len(drives) > MAX_SCOPE_OPTIONS - 1)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Google Workspace does not read {capability}"
            raise ValueError(msg)
        async with await self._client() as client:
            drives = await self._shared_drives(client)
            if capability is Capability.DRIVES:
                wanted = set(self.config.drives or [])
                for drive in drives:
                    if wanted and str(drive["id"]) not in wanted:
                        continue
                    yield record(
                        capability,
                        drive,
                        external_id=str(drive["id"]),
                        updated=drive.get("createdTime"),
                    )
                return
            seen: set[str] = set()
            for corpus in self._corpora(drives):
                params = {
                    **corpus,
                    "q": _query(since - UPDATE_MARGIN if since else None),
                    "fields": f"nextPageToken,files({FILE_FIELDS})",
                }
                async for found in client.pages("/files", params):
                    if found["id"] in seen:
                        continue  # in My Drive and in a shared drive's listing
                    seen.add(str(found["id"]))
                    payload: Item = dict(found)
                    text = await self._text(client, found)
                    payload["content"] = text.text if text else None
                    payload["content_truncated"] = bool(text and text.truncated)
                    yield record(
                        capability,
                        payload,
                        external_id=str(found["id"]),
                        container=str(found.get("driveId") or MY_DRIVE),
                        updated=found.get("modifiedTime"),
                    )

    # ── inside ───────────────────────────────────────────────────────────────

    async def _client(self) -> VendorHttp:
        if self._token is None:
            self._token = await google.service_account_token(
                self.http, self._key(), READ_ONLY_SCOPE, subject=self.config.subject
            )
        return VendorHttp(
            self.http(
                API, headers={"Authorization": f"Bearer {self._token}", "User-Agent": "LEKA"}
            ),
            secret=self._key()["private_key"],
            refuse=self._refuse,
            page_size=FILE_PAGE,
            page_size_param="pageSize",
            in_body=("files", "nextPageToken"),
            page_cursor_param="pageToken",
        )

    def _key(self) -> dict[str, str]:
        return google.service_account_key(self.credentials.service_account_key.get_secret_value())

    async def _about(self, client: VendorHttp) -> Item:
        response = await client.get("/about", params={"fields": "user(displayName,emailAddress)"})
        found = response.json()
        return found if isinstance(found, dict) else {}

    async def _shared_drives(self, client: VendorHttp) -> list[Item]:
        """The shared drives the account is a member of, following Drive's
        page tokens."""
        found: list[Item] = []
        token: str | None = None
        seen: set[str] = set()
        while True:
            params: dict[str, str | int] = {
                "pageSize": DRIVE_PAGE,
                "fields": "nextPageToken,drives(id,name,createdTime,hidden)",
            }
            if token:
                params["pageToken"] = token
            body = (await client.get("/drives", params=params)).json()
            found.extend(body.get("drives") or [])
            token = body.get("nextPageToken")
            if not token:
                return found
            if token in seen:
                raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail="Drive repeated a page token")
            seen.add(token)

    def _corpora(self, drives: list[Item]) -> list[dict[str, str]]:
        """Where to list files: My Drive and each drive in scope — or My
        Drive and every shared drive, one at a time rather than Drive's
        `allDrives`, which may answer incompletely."""
        keys = self.config.drives or [MY_DRIVE, *(str(drive["id"]) for drive in drives)]
        return [
            {"corpora": "user"}
            if key == MY_DRIVE
            else {
                "corpora": "drive",
                "driveId": key,
                "includeItemsFromAllDrives": "true",
                "supportsAllDrives": "true",
            }
            for key in keys
        ]

    def _require_scope(self, drives: list[Item]) -> None:
        """Every shared drive in scope must be one the account is a member of."""
        known = {str(drive["id"]) for drive in drives}
        missing = [d for d in self.config.drives or [] if d != MY_DRIVE and d not in known]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"Google ne montre pas ces Drive partagés à ce compte : {named}.",
            )

    async def _text(self, client: VendorHttp, found: Item) -> office.Text | None:
        """A file's text, where one can be had; None otherwise. A file Drive
        will not export or hand over — too large, downloads disabled — is a
        file without text, not a failed pass."""
        mime = str(found.get("mimeType") or "")
        file_id = str(found["id"])
        try:
            if mime in EXPORTS:
                exported = await client.get(
                    f"/files/{file_id}/export", params={"mimeType": EXPORTS[mime]}
                )
                return office.text_of(exported.content, EXPORTS[mime])
            kind = office.kind_of(mime, str(found.get("name") or ""))
            size = int(str(found.get("size") or 0))
            if kind is None or size > MAX_DOWNLOAD:
                return None
            downloaded = await client.get(
                f"/files/{file_id}", params={"alt": "media", "supportsAllDrives": "true"}
            )
            return office.text_of(downloaded.content[:MAX_DOWNLOAD], kind)
        except ConnectorError as error:
            if error.diagnostic.code in (
                DiagnosticCode.PERMISSION_DENIED,
                DiagnosticCode.NOT_FOUND,
            ):
                return None
            raise

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Drive's answers, as diagnostics: the reason of its error first."""
        secret = self._key()["private_key"]
        status, reason = response.status_code, _reason(response)
        if status == 429 or reason in BUSY:
            return refusal(
                response,
                path,
                secret,
                DiagnosticCode.RATE_LIMITED,
                retry_after=retry_after(response) or 60,
            )
        if reason in ("accessNotConfigured", "SERVICE_DISABLED"):
            message = "L'API Google Drive n'est pas activée dans le projet du compte de service."
            return refusal(
                response, path, secret, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        if status == 404:
            what = missing or "ce Drive partagé"
            message = f"Google ne trouve pas {what}, ou ce compte ne le voit pas."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        return refusal(response, path, secret, usual_code(status))


def _query(after: datetime | None) -> str:
    """Drive's `q`: files, not folders nor trash; changed after `after`."""
    query = f"trashed = false and mimeType != '{FOLDER}'"
    if after:
        query += f" and modifiedTime > '{after.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%S')}'"
    return query


def _reason(response: httpx.Response) -> str:
    """The reason Google gives: errors[0].reason, else the error's status."""
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return ""
    for detail in error.get("errors") or []:
        if isinstance(detail, dict) and detail.get("reason"):
            return str(detail["reason"])
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and detail.get("reason"):
            return str(detail["reason"])
    return str(error.get("status") or "")
