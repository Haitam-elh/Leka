"""The AWS connector against an AWS that is not there (LEKA-347).

`_client` is replaced by fake clients: each method answers what the test
says, or raises botocore's own ClientError with AWS's own error codes — the
probes run in parallel, and two of them share EC2, so an order-bound stubber
would not do. No network, no credentials.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError
from pydantic import SecretStr, ValidationError

from leka.connectors import Capability, ConnectorError, DiagnosticCode, HealthStatus
from leka.connectors.aws import AwsConfig, AwsConnector, AwsCredentials
from leka.connectors.aws import connector as aws_module

KEY_ID = "AKIAABCDEFGHIJKLMNOP"
SECRET = "wJalrXUtnFEMIK7MDENGbPxRfiCYsecretthatmustneverleak"

# A dict, an error, or — for a paginated operation — a list of pages.
Answer = dict[str, Any] | BaseException | list[Any]


def denied(operation: str, code: str = "AccessDenied", status: int = 403) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": f"no {SECRET}"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


HEALTHY: dict[str, Answer] = {
    "get_caller_identity": {
        "Account": "123456789012",
        "Arn": "arn:aws:iam::123456789012:user/leka",
    },
    "describe_regions": {"Regions": [{"RegionName": "eu-west-3"}, {"RegionName": "eu-central-1"}]},
    "describe_instances": {"Reservations": []},
    "describe_db_instances": {"DBInstances": []},
    "list_buckets": {"Buckets": []},
    "list_functions": {"Functions": []},
    "list_clusters": {"clusters": []},
    "describe_vpcs": {"Vpcs": []},
    "describe_load_balancers": {"LoadBalancers": []},
    # The account (LEKA-363): read with the resources, never probed.
    "list_account_aliases": {"AccountAliases": ["acme-prod"]},
    "describe_organization": {
        "Organization": {"Id": "o-abc123", "MasterAccountId": "999999999999"}
    },
}


class FakeClient:
    def __init__(
        self, answers: dict[str, Answer], calls: list[tuple[str, str]], region: str
    ) -> None:
        self._answers, self._calls, self._region = answers, calls, region

    def get_paginator(self, operation: str) -> Any:
        """boto3's paginator: a list answer is its pages, a dict one page;
        a page that is an exception is raised when that page is reached."""
        calls, answers, region = self._calls, self._answers, self._region

        class Paginator:
            def paginate(self, **_: Any) -> Any:
                calls.append((operation, region))
                answer = answers[operation]
                pages = answer if isinstance(answer, list) else [answer]
                for page in pages:
                    if isinstance(page, BaseException):
                        raise page
                    yield page

        return Paginator()

    def __getattr__(self, method: str) -> Callable[..., dict[str, Any]]:
        def call(**_: Any) -> dict[str, Any]:
            self._calls.append((method, self._region))
            answer = self._answers[method]
            if isinstance(answer, BaseException):
                raise answer
            # Called directly, a paginated answer is its first page.
            return answer[0] if isinstance(answer, list) else answer

        return call


def _connector(
    overrides: dict[str, Answer] | None = None, **config: Any
) -> tuple[AwsConnector, list[tuple[str, str]]]:
    connector = AwsConnector(
        AwsConfig.model_validate(config),
        AwsCredentials(access_key_id=SecretStr(KEY_ID), secret_access_key=SecretStr(SECRET)),
    )
    answers = {**HEALTHY, **(overrides or {})}
    calls: list[tuple[str, str]] = []
    connector._client = lambda service, region: FakeClient(answers, calls, region)  # type: ignore[method-assign]
    return connector, calls


async def _failure(overrides: dict[str, Answer]) -> ConnectorError:
    connector, _ = _connector(overrides)
    with pytest.raises(ConnectorError) as caught:
        await connector.test_connection()
    assert SECRET not in repr(caught.value.diagnostic)
    assert KEY_ID not in repr(caught.value.diagnostic)
    return caught.value


async def test_working_credentials_report_the_account_and_what_they_can_read() -> None:
    connector, calls = _connector()

    result = await connector.test_connection()

    assert result.account == "123456789012"
    assert result.metadata["regions_in_scope"] == 2
    assert set(result.capabilities) == set(AwsConnector.manifest.capabilities)
    assert result.warnings == []
    # Probed in the first region of the scope, sorted.
    assert ("describe_instances", "eu-central-1") in calls


async def test_a_service_the_policy_leaves_out_is_a_capability_left_out() -> None:
    connector, _ = _connector({"describe_db_instances": denied("DescribeDBInstances")})

    result = await connector.test_connection()

    assert Capability.DB_INSTANCES not in result.capabilities
    assert Capability.INSTANCES in result.capabilities


async def test_credentials_that_read_nothing_say_so() -> None:
    nothing = {name: denied(name, "UnauthorizedOperation") for name in list(HEALTHY)[2:]}
    connector, _ = _connector(nothing)

    result = await connector.test_connection()

    assert result.capabilities == []
    assert "aucun des services" in result.warnings[0]


async def test_a_root_key_is_accepted_with_a_warning() -> None:
    root = {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:root"}
    connector, _ = _connector({"get_caller_identity": root})

    result = await connector.test_connection()

    assert "racine" in result.warnings[0]


async def test_a_region_in_scope_the_account_has_not_enabled_is_named() -> None:
    connector, _ = _connector(regions=["eu-west-3", "ap-south-2"])

    with pytest.raises(ConnectorError) as caught:
        await connector.test_connection()

    assert caught.value.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert "ap-south-2" in caught.value.diagnostic.message


@pytest.mark.parametrize(
    ("answer", "code", "retryable"),
    [
        (denied("GetCallerIdentity", "InvalidClientTokenId"), "AUTH_INVALID", False),
        (denied("GetCallerIdentity", "SignatureDoesNotMatch"), "AUTH_INVALID", False),
        (denied("GetCallerIdentity", "ExpiredToken"), "AUTH_EXPIRED", False),
        (denied("AssumeRole", "AccessDenied"), "PERMISSION_DENIED", False),
        (denied("GetCallerIdentity", "Throttling", 400), "RATE_LIMITED", True),
        (denied("GetCallerIdentity", "ServiceUnavailable", 503), "PROVIDER_ERROR", True),
        (
            EndpointConnectionError(endpoint_url="https://sts.amazonaws.com"),
            "NETWORK_UNREACHABLE",
            True,
        ),
        (ReadTimeoutError(endpoint_url="https://sts.amazonaws.com"), "TIMEOUT", True),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    answer: BaseException, code: str, retryable: bool
) -> None:
    error = await _failure({"get_caller_identity": answer})

    assert error.diagnostic.code == DiagnosticCode(code)
    assert error.diagnostic.retryable is retryable
    assert error.diagnostic.remediation


async def test_health_and_scope() -> None:
    connector, _ = _connector()

    assert (await connector.check_health()).status is HealthStatus.HEALTHY
    listing = await connector.list_scope()
    assert [option.key for option in listing.options] == ["eu-central-1", "eu-west-3"]


@pytest.mark.parametrize(
    "config",
    [
        {"regions": ["paris"]},
        {"regions": []},
        {"role_arn": "arn:aws:iam::12:role/x"},
        {"external_id": "abc123"},
    ],
    ids=["not-a-region", "empty-regions", "not-a-role-arn", "external-id-without-role"],
)
def test_settings_that_cannot_work_are_refused(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AwsConfig.model_validate(config)


def test_the_hint_names_the_key_and_the_secret_never_shows() -> None:
    credentials = AwsCredentials(
        access_key_id=SecretStr(KEY_ID), secret_access_key=SecretStr(SECRET)
    )

    assert next(iter(credentials.model_dump())) == "access_key_id"
    assert SECRET not in repr(credentials)


async def test_a_role_is_assumed_once_with_its_external_id(monkeypatch: pytest.MonkeyPatch) -> None:
    assumed: list[dict[str, Any]] = []
    calls: list[tuple[str, str]] = []

    class FakeSession:
        def __init__(self, **credentials: Any) -> None:
            self.credentials = credentials

        def client(self, service: str, region_name: str, **_: Any) -> Any:
            if service == "sts" and "aws_session_token" not in self.credentials:

                class Sts:
                    def assume_role(self, **request: Any) -> dict[str, Any]:
                        assumed.append(request)
                        return {
                            "Credentials": {
                                "AccessKeyId": "ASIA",
                                "SecretAccessKey": "s",
                                "SessionToken": "t",
                            }
                        }

                return Sts()
            return FakeClient(HEALTHY, calls, region_name)

    import boto3

    monkeypatch.setattr(boto3.session, "Session", FakeSession)
    connector = AwsConnector(
        AwsConfig(role_arn="arn:aws:iam::123456789012:role/leka-read", external_id="ext-7f3"),
        AwsCredentials(access_key_id=SecretStr(KEY_ID), secret_access_key=SecretStr(SECRET)),
    )
    assert aws_module.HOME_REGION == "us-east-1"

    await connector.test_connection()

    assert len(assumed) == 1
    assert assumed[0]["ExternalId"] == "ext-7f3"
    assert assumed[0]["RoleArn"].endswith(":role/leka-read")
