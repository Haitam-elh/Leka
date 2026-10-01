"""The Azure connector against a Microsoft that is not there (LEKA-347).

httpx.MockTransport answers for both hosts: the identity platform's token
endpoint and Azure Resource Manager. What is asserted: the only POST is the
token request, every call to ARM is a GET; each refusal becomes its
diagnostic, the secret in none; resources listed by type, page after page,
known by their lower-cased ARM id.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from leka.connectors import Capability, ConnectorError, DiagnosticCode, HealthStatus
from leka.connectors.azure import AzureConfig, AzureConnector, AzureCredentials

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SECRET = "Xy8Q~thesecretthatmustneverleak.abc"
SUB = "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0"
OTHER = "9f8e7d6c-5b4a-3928-1706-f5e4d3c2b1a0"

VM = {
    "id": f"/subscriptions/{SUB}/resourceGroups/Prod"
    "/providers/Microsoft.Compute/virtualMachines/API-1",
    "name": "api-1",
    "type": "Microsoft.Compute/virtualMachines",
    "location": "westeurope",
}


GROUP: dict[str, Any] = {
    "id": f"/subscriptions/{SUB}/resourceGroups/Prod",
    "name": "Prod",
    "type": "Microsoft.Resources/resourceGroups",
    "location": "westeurope",
    "tags": {"env": "prod"},
}


class Microsoft:
    """Both hosts. `resources` maps a subscription to its pages of resources."""

    def __init__(self, **overrides: Any) -> None:
        self.token: httpx.Response = httpx.Response(
            200, json={"access_token": "tok", "expires_in": 3599}
        )
        self.subscriptions: Any = {
            "value": [{"subscriptionId": SUB, "displayName": "Prod", "state": "Enabled"}]
        }
        self.resources: dict[str, Any] = {SUB: [[VM]]}
        self.groups: dict[str, Any] = {SUB: [[GROUP]]}
        self.__dict__.update(overrides)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            assert request.method == "POST"
            return self.token
        assert request.method == "GET", "LEKA only reads Azure Resource Manager"
        assert request.headers["authorization"] == "Bearer tok"
        path = request.url.path
        if path == "/subscriptions":
            return (
                self.subscriptions
                if isinstance(self.subscriptions, httpx.Response)
                else httpx.Response(200, json=self.subscriptions)
            )
        subscription = path.split("/")[2]
        listing = self.groups if path.endswith("/resourcegroups") else self.resources
        answer = listing.get(subscription, [[]])
        if isinstance(answer, httpx.Response):
            return answer
        page = int(request.url.params.get("page", "1"))
        body: dict[str, Any] = {"value": answer[page - 1]}
        if page < len(answer):
            body["nextLink"] = str(request.url.copy_set_param("page", page + 1))
        return httpx.Response(200, json=body)


def _connector(microsoft: Microsoft, **config: Any) -> AzureConnector:
    return AzureConnector(
        AzureConfig.model_validate({"tenant_id": TENANT, **config}),
        AzureCredentials(client_id=CLIENT, client_secret=SecretStr(SECRET)),
        transport=httpx.MockTransport(microsoft),
    )


async def _failure(microsoft: Microsoft, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(microsoft, **config).test_connection()
    assert SECRET not in repr(caught.value.diagnostic)
    return caught.value


async def test_a_working_service_principal_reads_every_kind_of_resource() -> None:
    microsoft = Microsoft()

    result = await _connector(microsoft).test_connection()

    assert result.account == TENANT
    assert result.metadata["subscriptions_in_scope"] == 1
    assert set(result.capabilities) == set(AzureConnector.manifest.capabilities)
    token = parse_qs(microsoft.requests[0].content.decode())
    assert token["grant_type"] == ["client_credentials"]
    assert token["scope"] == ["https://management.azure.com/.default"]
    assert token["client_id"] == [CLIENT]


async def test_the_token_is_asked_for_once_per_connector() -> None:
    microsoft = Microsoft()
    connector = _connector(microsoft)

    await connector.test_connection()
    await connector.check_health()

    assert sum(r.url.host == "login.microsoftonline.com" for r in microsoft.requests) == 1


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ("AADSTS7000215: Invalid client secret provided.", 401, "AUTH_INVALID"),
        ("AADSTS700016: Application not found in the directory.", 400, "AUTH_INVALID"),
        ("AADSTS7000222: The provided client secret keys are expired.", 401, "AUTH_EXPIRED"),
        ("AADSTS90002: Tenant not found.", 400, "NOT_FOUND"),
        ("Service unavailable", 503, "PROVIDER_ERROR"),
    ],
)
async def test_each_refused_token_has_its_diagnostic(body: str, status: int, code: str) -> None:
    echo = httpx.Response(status, text=f"{body} secret={SECRET}")

    error = await _failure(Microsoft(token=echo))

    assert error.diagnostic.code == DiagnosticCode(code)
    assert error.diagnostic.remediation


async def test_a_subscription_in_scope_it_cannot_see_is_named() -> None:
    error = await _failure(Microsoft(), subscriptions=[SUB, OTHER])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert OTHER in error.diagnostic.message and "Reader" in error.diagnostic.message


async def test_resources_it_may_not_list_leave_every_capability_out() -> None:
    forbidden = httpx.Response(403, json={"error": {"code": "AuthorizationFailed"}})

    result = await _connector(Microsoft(resources={SUB: forbidden})).test_connection()

    assert result.capabilities == []


async def test_no_subscription_visible_is_a_warning() -> None:
    result = await _connector(Microsoft(subscriptions={"value": []})).test_connection()

    assert result.capabilities == []
    assert "Aucun abonnement" in result.warnings[0]


async def test_health_and_scope() -> None:
    connector = _connector(Microsoft())

    assert (await connector.check_health()).status is HealthStatus.HEALTHY
    listing = await connector.list_scope()
    assert [(o.key, o.name) for o in listing.options] == [(SUB, "Prod")]


async def test_resources_are_read_by_type_across_pages_and_subscriptions() -> None:
    database = {
        **VM,
        "id": VM["id"].replace("virtualMachines/API-1", "x/db"),
        "type": "Microsoft.Sql/servers/databases",
    }
    microsoft = Microsoft(resources={SUB: [[VM], [database]], OTHER: [[VM]]})
    connector = _connector(microsoft, subscriptions=[SUB, OTHER])

    records = [r async for r in connector.iter_resources(Capability.INSTANCES)]

    assert [r.container for r in records] == [SUB, SUB, OTHER]
    assert records[0].external_id == VM["id"].lower()  # case-insensitive ids, one record
    listing = next(r for r in microsoft.requests if r.url.path.endswith("/resources"))
    assert listing.url.params["$filter"] == (
        "resourceType eq 'Microsoft.Compute/virtualMachines' "
        "or resourceType eq 'Microsoft.Compute/virtualMachineScaleSets'"
    )


async def test_a_throttled_listing_says_when_to_come_back() -> None:
    throttled = httpx.Response(
        429, headers={"retry-after": "17"}, json={"error": {"code": "TooManyRequests"}}
    )
    connector = _connector(Microsoft(resources={SUB: throttled}))

    with pytest.raises(ConnectorError) as caught:
        _ = [r async for r in connector.iter_resources(Capability.NETWORKS)]

    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert caught.value.diagnostic.retry_after == 17


def test_every_azure_capability_is_listed_whole() -> None:
    manifest = AzureConnector.manifest
    assert manifest.listed_whole == manifest.capabilities


@pytest.mark.parametrize(
    "config",
    [
        {"tenant_id": "contoso"},
        {"tenant_id": TENANT, "subscriptions": ["prod"]},
        {"tenant_id": TENANT, "subscriptions": []},
    ],
    ids=["tenant-not-an-id", "subscription-not-an-id", "empty-scope"],
)
def test_settings_that_cannot_work_are_refused(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AzureConfig.model_validate(config)


def test_the_hint_names_the_application_and_the_secret_never_shows() -> None:
    credentials = AzureCredentials(client_id=CLIENT, client_secret=SecretStr(SECRET))

    assert next(iter(credentials.model_dump())) == "client_id"
    assert SECRET not in repr(credentials)


async def test_the_subscriptions_in_scope_are_read_then_their_resource_groups() -> None:
    microsoft = Microsoft(
        subscriptions={
            "value": [
                {"subscriptionId": SUB, "displayName": "Prod", "state": "Enabled"},
                {"subscriptionId": OTHER, "displayName": "Sandbox", "state": "Enabled"},
            ]
        }
    )
    connector = _connector(microsoft, subscriptions=[SUB])

    records = [r async for r in connector.iter_resources(Capability.ACCOUNTS)]

    assert [(r.external_id, r.container) for r in records] == [
        (f"/subscriptions/{SUB}", None),
        (GROUP["id"].lower(), SUB),
    ]
    assert records[0].payload["displayName"] == "Prod"
    # The other subscription, out of scope, is not read.
    assert not any(OTHER in r.url.path for r in microsoft.requests)
