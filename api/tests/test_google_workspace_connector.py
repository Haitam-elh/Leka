"""The Google Workspace connector against a Google that is not there (LEKA-346).

The service account's key is a real RSA key made by the Google Cloud tests,
so the JWT the connector signs is a real one. httpx.MockTransport stands in
for the token endpoint and the Drive API; it checks the other half of
"LEKA reads": the one POST is the token exchange, every other call a GET
with the token Google gave.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from leka.connectors import (
    Capability,
    ConnectorCategory,
    ConnectorError,
    DiagnosticCode,
    HealthStatus,
    manifests,
)
from leka.connectors.google_workspace import (
    GoogleWorkspaceConfig,
    GoogleWorkspaceConnector,
    GoogleWorkspaceCredentials,
)
from tests.test_gcp_connector import EMAIL, KEY, _claims

PREFIX = "/drive/v3"
DOC = "application/vnd.google-apps.document"
SHEET = "application/vnd.google-apps.spreadsheet"
FOLDER = "application/vnd.google-apps.folder"
ENGINEERING = {
    "id": "0AEngineeringDrive",
    "name": "Engineering",
    "createdTime": "2025-01-01T00:00:00Z",
}
LEGAL = {"id": "0ALegalDrive00", "name": "Legal"}

Answer = object | Callable[[httpx.Request], httpx.Response]


def reason(status: int, why: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": status, "errors": [{"reason": why}]}})


def drive_file(
    file_id: str, mime: str = DOC, drive: str | None = None, **more: Any
) -> dict[str, Any]:
    found = {
        "id": file_id,
        "name": f"{file_id}.doc",
        "mimeType": mime,
        "modifiedTime": "2026-09-21T12:05:00.000Z",
        **more,
    }
    if drive:
        found["driveId"] = drive
    return found


class Google:
    """A healthy Google, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.token: httpx.Response = httpx.Response(200, json={"access_token": "tok"})
        self.drives = [ENGINEERING, LEGAL]
        # Files by corpus: "user" for My Drive, else the shared drive's id.
        self.files: dict[str, list[dict[str, Any]]] = {
            "user": [drive_file("mine")],
            ENGINEERING["id"]: [drive_file("design", drive=ENGINEERING["id"])],
        }
        self.contents: dict[str, bytes] = {}
        self.answers: dict[str, Answer] = {
            "/about": {"user": {"displayName": "LEKA", "emailAddress": "leka@acme.test"}},
            "/drives": lambda _: httpx.Response(200, json={"drives": self.drives}),
            "/files": self._files,
            **(overrides or {}),
        }
        self.asked: list[httpx.Request] = []

    def _files(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        corpus = params.get("driveId") if params.get("corpora") == "drive" else "user"
        found = self.files.get(corpus or "", [])
        size = int(params.get("pageSize", 1000))
        start = int(params.get("pageToken", 0))
        body: dict[str, Any] = {"files": found[start : start + size]}
        if start + size < len(found):
            body["nextPageToken"] = str(start + size)
        return httpx.Response(200, json=body)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if request.url.host == "oauth2.googleapis.com":
            assert (request.method, request.url.path) == ("POST", "/token")
            return self.token
        assert request.method == "GET", "LEKA reads Google Drive with GETs"
        assert request.url.host == "www.googleapis.com"
        assert request.headers["authorization"] == "Bearer tok"
        path = request.url.path.removeprefix(PREFIX)
        answer = self.answers.get(path)
        if answer is None and path.startswith("/files/"):
            file_id = path.split("/")[2]
            if file_id in self.contents:
                return httpx.Response(200, content=self.contents[file_id])
            return reason(404, "notFound")
        if answer is None:
            return reason(404, "notFound")
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def requests(self, path: str) -> list[httpx.Request]:
        return [r for r in self.asked if r.url.path.removeprefix(PREFIX) == path]

    def assertion(self) -> dict[str, Any]:
        form = parse_qs(next(r for r in self.asked if r.method == "POST").content.decode())
        return _claims(form["assertion"][0])


def _connector(google: Google, **config: Any) -> GoogleWorkspaceConnector:
    return GoogleWorkspaceConnector(
        GoogleWorkspaceConfig.model_validate(config),
        GoogleWorkspaceCredentials(service_account_key=SecretStr(KEY)),
        transport=httpx.MockTransport(google),
    )


async def _failure(google: Google, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(google, **config).test_connection()
    assert "PRIVATE KEY" not in repr(caught.value.diagnostic)
    return caught.value


def test_google_workspace_is_in_the_catalogue_as_a_documentation_tool() -> None:
    manifest = next(m for m in manifests() if m.key == "google_workspace")
    key = manifest.credentials_schema.model_json_schema()["properties"]["service_account_key"]

    assert manifest.category is ConnectorCategory.DOCS
    assert manifest.capabilities == {Capability.DRIVES, Capability.FILES}
    assert manifest.listed_whole == {Capability.DRIVES}
    assert key["writeOnly"] is True


# ── the configuration ────────────────────────────────────────────────────────


def test_the_scope_is_my_drive_and_shared_drives_typed_or_pasted() -> None:
    config = GoogleWorkspaceConfig.model_validate(
        {
            "subject": " Reader@Acme.test ",
            "drives": [
                "USER",
                "0AEngineeringDrive",
                "https://drive.google.com/drive/u/0/folders/0AEngineeringDrive",
            ],
        }
    )

    assert config.subject == "reader@acme.test"
    assert config.drives == ["user", "0AEngineeringDrive"]


@pytest.mark.parametrize(
    "config",
    [{"subject": "not an email"}, {"drives": []}, {"drives": ["../x"]}, {"drives": ["a b c"]}],
)
def test_a_configuration_that_is_not_a_scope_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GoogleWorkspaceConfig.model_validate(config)


def test_a_key_that_is_not_a_service_account_s_is_refused() -> None:
    not_one = json.dumps({"type": "authorized_user", "client_id": "x" * 100})

    with pytest.raises(ValidationError):
        GoogleWorkspaceCredentials(service_account_key=SecretStr(not_one))


# ── the connection test ──────────────────────────────────────────────────────


async def test_the_service_account_signs_in_read_only_and_reports_what_it_sees() -> None:
    google = Google()

    result = await _connector(google).test_connection()

    assert result.account == "leka@acme.test"
    assert result.metadata == {"acting_as": None, "shared_drives_visible": 2, "files_visible": 1}
    assert set(result.capabilities) == {Capability.DRIVES, Capability.FILES}
    assert result.warnings == []
    claims = google.assertion()
    assert claims["iss"] == EMAIL
    assert claims["scope"] == "https://www.googleapis.com/auth/drive.readonly"
    assert "sub" not in claims


async def test_with_domain_wide_delegation_it_acts_as_the_subject() -> None:
    google = Google()

    await _connector(google, subject="reader@acme.test").test_connection()

    assert google.assertion()["sub"] == "reader@acme.test"


async def test_a_delegation_not_granted_is_a_permission_to_give() -> None:
    google = Google()
    google.token = httpx.Response(401, json={"error": "unauthorized_client"})

    error = await _failure(google, subject="reader@acme.test")

    assert error.diagnostic.code is DiagnosticCode.PERMISSION_DENIED
    assert "délégation" in error.diagnostic.message


async def test_an_account_that_sees_nothing_is_told_what_to_share() -> None:
    google = Google()
    google.drives, google.files = [], {}

    result = await _connector(google).test_connection()

    assert result.warnings and EMAIL in result.warnings[0]


async def test_a_shared_drive_in_scope_the_account_is_not_in_fails_the_test() -> None:
    error = await _failure(Google(), drives=["user", "0AUnknownDrive"])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert error.diagnostic.message == (
        "Google ne montre pas ces Drive partagés à ce compte : 0AUnknownDrive."
    )


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (reason(401, "authError"), DiagnosticCode.AUTH_INVALID),
        (reason(403, "accessNotConfigured"), DiagnosticCode.PERMISSION_DENIED),
        (reason(403, "insufficientPermissions"), DiagnosticCode.PERMISSION_DENIED),
        (reason(403, "userRateLimitExceeded"), DiagnosticCode.RATE_LIMITED),
        (reason(429, "rateLimitExceeded"), DiagnosticCode.RATE_LIMITED),
        (httpx.Response(503, text="down"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Google({"/about": response}))

    assert error.diagnostic.code is code


async def test_an_api_left_off_says_so() -> None:
    error = await _failure(Google({"/about": reason(403, "accessNotConfigured")}))

    assert "API Google Drive" in error.diagnostic.message


# ── health, the scope ────────────────────────────────────────────────────────


async def test_health_is_a_token_and_drive_answering() -> None:
    assert (await _connector(Google()).check_health()).status is HealthStatus.HEALTHY


async def test_the_scope_offers_my_drive_then_every_shared_drive() -> None:
    listing = await _connector(Google(), subject="reader@acme.test").list_scope()

    assert [(o.key, o.name) for o in listing.options] == [
        ("user", "Mon Drive"),
        ("0AEngineeringDrive", "Engineering"),
        ("0ALegalDrive00", "Legal"),
    ]
    assert "reader@acme.test" in (listing.options[0].description or "")
