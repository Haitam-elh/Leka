"""The Microsoft 365 connector against a Microsoft that is not there (LEKA-346).

httpx.MockTransport stands in for Microsoft's identity platform, Microsoft
Graph, and the tenant's SharePoint host. It checks the other half of "LEKA
reads": the one POST is the token exchange; every call to Graph is a GET
with the token; SharePoint is reached only through the link Graph gave,
without LEKA's token.
"""

from __future__ import annotations

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
from leka.connectors.microsoft_365 import (
    Microsoft365Config,
    Microsoft365Connector,
    Microsoft365Credentials,
)
from leka.connectors.microsoft_365 import connector as m365

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SECRET = "m365~client-secret-0123456789"
PREFIX = "/v1.0"
DOCS = "b!docsLibrary0000"
HANDBOOK = "b!handbookLibrary"
NORA_DRIVE = "b!noraOneDrive000"

SITES = [
    {"id": "site-root", "displayName": "Acme"},
    {"id": "site-hr", "displayName": "People"},
]
DRIVES: dict[str, dict[str, Any]] = {
    DOCS: {"id": DOCS, "name": "Documents", "driveType": "documentLibrary"},
    HANDBOOK: {"id": HANDBOOK, "name": "Handbook", "driveType": "documentLibrary"},
    NORA_DRIVE: {"id": NORA_DRIVE, "name": "OneDrive", "driveType": "business"},
}

Answer = object | Callable[[httpx.Request], httpx.Response]


def graph_error(status: int, code: str, **headers: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": code}}, headers=headers)


class Microsoft:
    """A healthy tenant, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.token: httpx.Response = httpx.Response(200, json={"access_token": "tok"})
        self.items: dict[str, list[dict[str, Any]]] = {}
        self.downloads: dict[str, bytes] = {}
        self.answers: dict[str, Answer] = {
            "/sites/root": {
                "id": "site-root",
                "displayName": "Acme",
                "webUrl": "https://acme.sharepoint.com",
            },
            "/sites/root/drive": {"id": DOCS},
            "/sites": {"value": SITES},
            "/sites/site-root/drives": {"value": [DRIVES[DOCS]]},
            "/sites/site-hr/drives": {"value": [DRIVES[HANDBOOK]]},
            "/users": {"value": [{"id": "u-nora", "displayName": "Nora"}, {"id": "u-bot"}]},
            "/users/u-nora/drive": DRIVES[NORA_DRIVE],
            **(overrides or {}),
        }
        self.asked: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if request.url.host == "login.microsoftonline.com":
            assert (request.method, request.url.path) == (
                "POST",
                f"/{TENANT}/oauth2/v2.0/token",
            )
            return self.token
        assert request.method == "GET", "LEKA reads Microsoft 365 with GETs"
        if request.url.host == "acme.sharepoint.com":
            assert "authorization" not in request.headers, "the link carries its own"
            found = self.downloads.get(request.url.params.get("UniqueId", ""))
            return httpx.Response(200, content=found) if found else httpx.Response(404)
        assert request.url.host == "graph.microsoft.com"
        assert request.headers["authorization"] == "Bearer tok"
        path = request.url.path.removeprefix(PREFIX)
        answer = self.answers.get(path)
        if answer is None:
            answer = self._drive_paths(path)
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def _drive_paths(self, path: str) -> Answer:
        parts = path.split("/")  # "", "drives", id, …
        if len(parts) < 3 or parts[1] != "drives" or parts[2] not in DRIVES:
            return graph_error(404, "itemNotFound")
        drive = parts[2]
        if len(parts) == 3:
            return DRIVES[drive]
        if parts[3:] == ["root", "children"]:
            return {"value": []}
        if parts[3:] == ["root", "delta"]:
            return {"value": self.items.get(drive, []), "@odata.deltaLink": "https://x/delta"}
        if parts[3] == "items" and parts[5:] == ["content"]:
            item = parts[4]
            location = (
                "https://acme.sharepoint.com/_layouts/15/download.aspx"
                f"?UniqueId={item}&tempauth=v1.secret-link"
            )
            return httpx.Response(302, headers={"location": location})
        return graph_error(404, "itemNotFound")

    def requests(self, path: str) -> list[httpx.Request]:
        return [
            r
            for r in self.asked
            if r.url.host == "graph.microsoft.com" and r.url.path.removeprefix(PREFIX) == path
        ]


def _connector(microsoft: Microsoft, **config: Any) -> Microsoft365Connector:
    return Microsoft365Connector(
        Microsoft365Config.model_validate({"tenant_id": TENANT, **config}),
        Microsoft365Credentials(client_id=CLIENT, client_secret=SecretStr(SECRET)),
        transport=httpx.MockTransport(microsoft),
    )


async def _failure(microsoft: Microsoft, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(microsoft, **config).test_connection()
    assert SECRET not in repr(caught.value.diagnostic)
    return caught.value


def test_microsoft_365_is_in_the_catalogue_as_a_documentation_tool() -> None:
    manifest = next(m for m in manifests() if m.key == "microsoft_365")
    secrets = manifest.credentials_schema.model_json_schema()["properties"]

    assert manifest.category is ConnectorCategory.DOCS
    assert manifest.capabilities == {Capability.DRIVES, Capability.FILES}
    assert manifest.listed_whole == {Capability.DRIVES}
    assert list(secrets) == ["client_id", "client_secret"]  # the hint names the app
    assert secrets["client_secret"]["writeOnly"] is True


# ── the configuration ────────────────────────────────────────────────────────


def test_the_tenant_is_an_id_and_the_scope_drive_ids() -> None:
    config = Microsoft365Config.model_validate(
        {"tenant_id": TENANT.upper(), "drives": [DOCS, f" {DOCS} ", NORA_DRIVE]}
    )

    assert config.tenant_id == TENANT
    assert config.drives == [DOCS, NORA_DRIVE]


@pytest.mark.parametrize(
    "config",
    [
        {"tenant_id": "acme.onmicrosoft.com"},
        {"tenant_id": TENANT, "drives": []},
        {"tenant_id": TENANT, "drives": ["../../users"]},
    ],
)
def test_a_configuration_that_is_not_ids_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Microsoft365Config.model_validate(config)


# ── the connection test ──────────────────────────────────────────────────────


async def test_the_application_signs_in_to_graph_and_reports_what_it_sees() -> None:
    microsoft = Microsoft()

    result = await _connector(microsoft).test_connection()

    assert result.account == "acme.sharepoint.com"
    assert result.metadata == {"root_site": "Acme"}
    assert set(result.capabilities) == {Capability.DRIVES, Capability.FILES}
    assert result.warnings == []
    form = parse_qs(microsoft.asked[0].content.decode())
    assert form["scope"] == ["https://graph.microsoft.com/.default"]
    assert form["grant_type"] == ["client_credentials"]


async def test_without_user_read_all_the_onedrives_are_said_to_be_left_out() -> None:
    refused = Microsoft({"/users": graph_error(403, "Authorization_RequestDenied")})

    result = await _connector(refused).test_connection()

    assert Capability.FILES in result.capabilities
    assert "User.Read.All" in result.warnings[0]


async def test_a_drive_in_scope_graph_does_not_show_fails_the_test() -> None:
    error = await _failure(Microsoft(), drives=[DOCS, "b!unknownDrive00"])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert "b!unknownDrive00" in error.diagnostic.message


@pytest.mark.parametrize(
    ("token", "code"),
    [
        (httpx.Response(400, text="AADSTS90002: Tenant not found"), DiagnosticCode.NOT_FOUND),
        (httpx.Response(401, text="AADSTS7000222: expired"), DiagnosticCode.AUTH_EXPIRED),
        (httpx.Response(401, text="AADSTS7000215: invalid secret"), DiagnosticCode.AUTH_INVALID),
    ],
)
async def test_a_refused_sign_in_has_its_diagnostic(
    token: httpx.Response, code: DiagnosticCode
) -> None:
    microsoft = Microsoft()
    microsoft.token = token

    error = await _failure(microsoft)

    assert error.diagnostic.code is code


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (graph_error(401, "InvalidAuthenticationToken"), DiagnosticCode.AUTH_INVALID),
        (graph_error(403, "accessDenied"), DiagnosticCode.PERMISSION_DENIED),
        (graph_error(404, "itemNotFound"), DiagnosticCode.NOT_FOUND),
        (graph_error(429, "TooManyRequests", **{"retry-after": "9"}), DiagnosticCode.RATE_LIMITED),
        (graph_error(503, "serviceNotAvailable"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Microsoft({"/sites/root": response}))

    assert error.diagnostic.code is code


async def test_a_refusal_names_the_permissions_to_grant() -> None:
    error = await _failure(Microsoft({"/sites/root": graph_error(403, "accessDenied")}))

    assert "Sites.Read.All" in error.diagnostic.message


# ── health, the scope ────────────────────────────────────────────────────────


async def test_health_is_a_token_and_graph_answering() -> None:
    assert (await _connector(Microsoft()).check_health()).status is HealthStatus.HEALTHY


async def test_the_scope_offers_each_site_s_libraries_then_each_onedrive() -> None:
    listing = await _connector(Microsoft()).list_scope()

    assert [(o.key, o.name, o.description) for o in listing.options] == [
        (DOCS, "Acme — Documents", "SharePoint"),
        (HANDBOOK, "People — Handbook", "SharePoint"),
        (NORA_DRIVE, "Nora — OneDrive", "OneDrive"),
    ]
    assert listing.truncated is False


async def test_a_listing_that_would_take_too_many_calls_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m365, "MAX_SCOPE_CALLS", 1)

    listing = await _connector(Microsoft()).list_scope()

    assert [o.key for o in listing.options] == [DOCS]
    assert listing.truncated is True
