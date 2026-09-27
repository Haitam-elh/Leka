"""The Google Cloud connector against a Google that is not there (LEKA-347).

A real RSA key is made for the test, so the JWT the connector signs can be
verified with its public half — the one thing Google checks first. The rest
is httpx.MockTransport for the three hosts: the token endpoint, Resource
Manager and Cloud Asset Inventory. The only POST is the token exchange.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import SecretStr, ValidationError

from leka.connectors import Capability, ConnectorError, DiagnosticCode, HealthStatus
from leka.connectors.gcp import GcpConfig, GcpConnector, GcpCredentials

PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = PRIVATE.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
EMAIL = "leka-reader@acme-prod.iam.gserviceaccount.com"
KEY = json.dumps(
    {
        "type": "service_account",
        "client_email": EMAIL,
        "private_key": PEM,
        "project_id": "acme-prod",
    }
)

INSTANCE = {
    "name": "//compute.googleapis.com/projects/acme-prod/zones/europe-west1-b/instances/api-1",
    "assetType": "compute.googleapis.com/Instance",
    "updateTime": "2026-09-25T10:00:00Z",
    "resource": {"data": {"status": "RUNNING"}},
}


class Google:
    def __init__(self, **overrides: Any) -> None:
        self.token: httpx.Response = httpx.Response(
            200, json={"access_token": "tok", "expires_in": 3599}
        )
        self.projects: Any = [
            [{"projectId": "acme-prod", "displayName": "Prod", "state": "ACTIVE"}]
        ]
        self.assets: Any = [[INSTANCE]]
        self.__dict__.update(overrides)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            assert (request.method, request.url.path) == ("POST", "/token")
            return self.token
        assert request.method == "GET", "LEKA only reads Google Cloud"
        assert request.headers["authorization"] == "Bearer tok"
        answer = (
            self.projects
            if request.url.host == "cloudresourcemanager.googleapis.com"
            else self.assets
        )
        if isinstance(answer, httpx.Response):
            return answer
        field = (
            "projects" if request.url.host == "cloudresourcemanager.googleapis.com" else "assets"
        )
        page = int(request.url.params.get("pageToken", "1"))
        body: dict[str, Any] = {field: answer[page - 1]}
        if page < len(answer):
            body["nextPageToken"] = str(page + 1)
        return httpx.Response(200, json=body)


def _connector(google: Google, **config: Any) -> GcpConnector:
    return GcpConnector(
        GcpConfig.model_validate(config),
        GcpCredentials(service_account_key=SecretStr(KEY)),
        transport=httpx.MockTransport(google),
    )


def pad(part: str) -> str:
    return part + "=" * (-len(part) % 4)


def _claims(assertion: str) -> dict[str, Any]:
    header, payload, signature = assertion.split(".")
    PRIVATE.public_key().verify(
        base64.urlsafe_b64decode(pad(signature)),
        f"{header}.{payload}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )  # raises if the signature is not the key's
    assert json.loads(base64.urlsafe_b64decode(pad(header))) == {"alg": "RS256", "typ": "JWT"}
    claims: dict[str, Any] = json.loads(base64.urlsafe_b64decode(pad(payload)))
    return claims


async def test_a_working_service_account_signs_its_way_in_and_reads_everything() -> None:
    google = Google()

    result = await _connector(google).test_connection()

    assert result.account == EMAIL
    assert set(result.capabilities) == set(GcpConnector.manifest.capabilities)
    form = parse_qs(google.requests[0].content.decode())
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    claims = _claims(form["assertion"][0])
    assert claims["iss"] == EMAIL
    assert claims["scope"] == "https://www.googleapis.com/auth/cloud-platform.read-only"
    assert claims["aud"] == "https://oauth2.googleapis.com/token"
    assert claims["exp"] - claims["iat"] == 3600


async def test_the_token_is_asked_for_once_per_connector() -> None:
    google = Google()
    connector = _connector(google)

    await connector.test_connection()
    await connector.check_health()

    assert sum(r.url.host == "oauth2.googleapis.com" for r in google.requests) == 1


async def test_a_refused_key_is_auth_invalid_and_never_quoted() -> None:
    echo = httpx.Response(
        400, json={"error": "invalid_grant", "error_description": f"Invalid JWT Signature. {PEM}"}
    )

    with pytest.raises(ConnectorError) as caught:
        await _connector(Google(token=echo)).test_connection()

    assert caught.value.diagnostic.code is DiagnosticCode.AUTH_INVALID
    assert "PRIVATE KEY" not in repr(caught.value.diagnostic)


async def test_a_project_in_scope_it_cannot_see_is_named() -> None:
    with pytest.raises(ConnectorError) as caught:
        await _connector(Google(), projects=["acme-prod", "globex-data"]).test_connection()

    assert caught.value.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert "globex-data" in caught.value.diagnostic.message


async def test_cloud_asset_off_or_forbidden_leaves_everything_out_and_says_what_to_do() -> None:
    off = httpx.Response(
        403,
        json={
            "error": {"status": "PERMISSION_DENIED", "details": [{"reason": "SERVICE_DISABLED"}]}
        },
    )

    result = await _connector(Google(assets=off)).test_connection()

    assert result.capabilities == []
    assert "cloudasset.googleapis.com" in result.warnings[0]


async def test_no_project_visible_is_a_warning() -> None:
    result = await _connector(Google(projects=[[]])).test_connection()

    assert "Aucun projet" in result.warnings[0]


async def test_health_and_scope() -> None:
    connector = _connector(Google())

    assert (await connector.check_health()).status is HealthStatus.HEALTHY
    assert [(o.key, o.name) for o in (await connector.list_scope()).options] == [
        ("acme-prod", "Prod")
    ]


async def test_assets_are_read_by_type_page_after_page() -> None:
    bucket = {
        **INSTANCE,
        "name": "//storage.googleapis.com/acme-logs",
        "assetType": "storage.googleapis.com/Bucket",
    }
    google = Google(assets=[[INSTANCE], [bucket]])

    records = [r async for r in _connector(google).iter_resources(Capability.INSTANCES)]

    assert [(r.external_id, r.container) for r in records] == [
        (INSTANCE["name"], "acme-prod"),
        (bucket["name"], "acme-prod"),
    ]
    assert records[0].updated_at is not None
    listing = [r for r in google.requests if r.url.host == "cloudasset.googleapis.com"]
    assert listing[0].url.params.get_list("assetTypes") == ["compute.googleapis.com/Instance"]
    assert listing[0].url.params["contentType"] == "RESOURCE"
    assert listing[1].url.params["pageToken"] == "2"


async def test_a_throttled_listing_says_when_to_come_back() -> None:
    throttled = httpx.Response(
        429, headers={"retry-after": "30"}, json={"error": {"status": "RESOURCE_EXHAUSTED"}}
    )

    with pytest.raises(ConnectorError) as caught:
        _ = [
            r async for r in _connector(Google(assets=throttled)).iter_resources(Capability.BUCKETS)
        ]

    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert caught.value.diagnostic.retry_after == 30


def test_every_gcp_capability_is_listed_whole() -> None:
    manifest = GcpConnector.manifest
    assert manifest.listed_whole == manifest.capabilities


@pytest.mark.parametrize(
    "key",
    [
        "not json",
        json.dumps({"type": "authorized_user", "client_email": EMAIL, "private_key": PEM}),
    ],
    ids=["not-json", "not-a-service-account"],
)
def test_what_is_not_a_service_account_key_is_refused(key: str) -> None:
    with pytest.raises(ValidationError):
        GcpCredentials(service_account_key=SecretStr(key.ljust(120)))


def test_a_project_id_is_checked() -> None:
    with pytest.raises(ValidationError):
        GcpConfig(projects=["Acme Prod"])
    assert GcpConfig(projects=["acme-prod"]).projects == ["acme-prod"]
