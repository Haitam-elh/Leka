"""The AWS connector — one AWS account, read-only (LEKA-347).

test_connection: who am I (sts:GetCallerIdentity), after assuming the role
when one is configured; which regions the account has enabled, and whether
the ones in scope are among them; then — in the first region of the scope —
which services these credentials can actually read, one call each, in
parallel. A service the policy does not allow is a capability left out, not
a failure: the admin sees what LEKA will and will not read.

check_health: sts:GetCallerIdentity — free, and it is what fails first when
a key is revoked or a role's trust policy changes.

list_scope: the regions the account has enabled.

iter_resources: each capability in every region of the scope — S3's bucket
list, being global, once — page by page through boto3's paginators, each
resource known by its ARN. AWS has no "changed since" for any of these:
every pass reads them whole (`listed_whole`), and the index keeps a pass
from writing what did not change and marks gone what is no longer listed.
`accounts` is the account itself (LEKA-363): its id, its alias — the name
its admins gave it — and its organisation, each read when the policy allows
it and left out when it does not.

BOTO3, NOT self.http(). AWS signs every request (SigV4) and each service
speaks its own protocol; reimplementing that over httpx would be a second
SDK to maintain. boto3 is already LEKA's (the S3 object store). What
self.http() guards against — an admin typing an address the server should
not call (leka/connectors/network.py) — does not arise: every endpoint is
AWS's own, chosen by region, never typed. Tests replace `_client` with fake
clients raising botocore's own ClientError, as the other connectors replace
their transport.

CREDENTIALS. An IAM user's access key, with a read-only policy
(docs/connectors/cloud.md). Better: a role in the customer's account that
the key assumes, with an external id — the key alone then reads nothing,
and the customer revokes LEKA by editing one trust policy.

LEKA READS. Every call is a Describe, List or Get. A root user's key is
accepted — IAM is where it should be refused — with a warning.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
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
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

CLOUD_CAPABILITIES = frozenset(
    {
        Capability.INSTANCES,
        Capability.DB_INSTANCES,
        Capability.BUCKETS,
        Capability.FUNCTIONS,
        Capability.CLUSTERS,
        Capability.NETWORKS,
        Capability.LOAD_BALANCERS,
        Capability.ACCOUNTS,
    }
)
# Where the calls that are not regional go (STS, the region list).
HOME_REGION = "us-east-1"
REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")
ROLE_ARN = re.compile(r"^arn:aws[a-z-]*:iam::\d{12}:role/[\w+=,.@/-]{1,512}$")
# Short: the connection test has 15 s for all of it (TEST_BUDGET_SECONDS).
CLIENT_CONFIG = Config(
    connect_timeout=5, read_timeout=10, retries={"max_attempts": 2, "mode": "standard"}
)

_AUTH_INVALID = {
    "InvalidClientTokenId",
    "SignatureDoesNotMatch",
    "UnrecognizedClientException",
    "AuthFailure",
    "IncompleteSignature",
    "InvalidAccessKeyId",
}
_AUTH_EXPIRED = {"ExpiredToken", "ExpiredTokenException", "RequestExpired"}
_DENIED = {
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
    "UnauthorizedException",
    "AuthorizationError",
}
# What is not there to read: an account in no organisation.
_ABSENT = {"AWSOrganizationsNotInUseException"}
_THROTTLED = {
    "Throttling",
    "ThrottlingException",
    "RequestLimitExceeded",
    "TooManyRequestsException",
    "SlowDown",
}


class AwsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_arn: str | None = Field(
        default=None,
        max_length=2048,
        description="A role in the account for LEKA to assume. Recommended.",
    )
    external_id: str | None = Field(
        default=None,
        min_length=2,
        max_length=1224,
        description="The external id the role's trust policy requires.",
    )
    regions: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=40,
        description="The regions to read ('eu-west-3'). Empty: every region enabled.",
    )

    @model_validator(mode="after")
    def _well_formed(self) -> AwsConfig:
        if self.role_arn is not None and not ROLE_ARN.match(self.role_arn):
            msg = f"{self.role_arn!r} is not a role ARN like 'arn:aws:iam::123456789012:role/leka'"
            raise ValueError(msg)
        if self.external_id is not None and self.role_arn is None:
            msg = "an external id goes with a role to assume"
            raise ValueError(msg)
        for region in self.regions or []:
            if not REGION.match(region):
                msg = f"{region!r} is not a region like 'eu-west-3'"
                raise ValueError(msg)
        return self


class AwsCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First: the stored hint is taken from the first field — "AKIA…WXYZ"
    # names the key, and says nothing of the secret.
    access_key_id: SecretStr = Field(
        min_length=16,
        max_length=128,
        description="An IAM access key id, of a user with a read-only policy.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    secret_access_key: SecretStr = Field(
        min_length=16,
        max_length=128,
        description="Its secret access key.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class AwsConnector(Connector[AwsConfig, AwsCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.AWS,
        display_name="Amazon Web Services",
        category=ConnectorCategory.CLOUD,
        auth_type="token",
        config_schema=AwsConfig,
        credentials_schema=AwsCredentials,
        capabilities=CLOUD_CAPABILITIES,
        listed_whole=CLOUD_CAPABILITIES,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._built: Any = None

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        identity = await self._call("sts", HOME_REGION, lambda sts: sts.get_caller_identity())
        warnings: list[str] = []
        if str(identity.get("Arn", "")).endswith(":root"):
            warnings.append(
                "Cette clé est celle du compte racine. LEKA ne fait que lire : un utilisateur "
                "IAM, ou mieux un rôle en lecture seule, suffit et limite l'exposition."
            )

        enabled = await self._enabled_regions()
        scope = self.config.regions or enabled
        missing = sorted(set(scope) - set(enabled))
        if missing:
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message="Ces régions ne sont pas activées sur le compte, ou le rôle ne les voit "
                f"pas : {', '.join(missing)}.",
                secrets=self._secrets(),
            )
        capabilities = await self._probe(scope[0] if scope else HOME_REGION)
        if not capabilities:
            warnings.append(
                "La politique de ces identifiants ne permet de lire aucun des services que "
                "LEKA connaît. Voir la politique en lecture seule recommandée."
            )

        return ConnectionTestResult(
            account=str(identity.get("Account")),
            metadata={
                "account": identity.get("Account"),
                "arn": identity.get("Arn"),
                "regions_in_scope": len(scope),
            },
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        await self._call("sts", HOME_REGION, lambda sts: sts.get_caller_identity())
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        regions = await self._enabled_regions()
        return ScopeListing(options=[ScopeOption(key=r, name=r) for r in sorted(regions)])

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        """`since` is not used: AWS lists these whole, and says so in the manifest."""
        identity = await self._call("sts", HOME_REGION, lambda sts: sts.get_caller_identity())
        account = str(identity["Account"])
        if capability is Capability.ACCOUNTS:
            yield _record(capability, account, None, await self._account(account))
            return
        if capability is Capability.BUCKETS:
            # Global: one list for the account, whatever the regions in scope.
            answer = await self._call("s3", HOME_REGION, lambda s3: s3.list_buckets())
            for bucket in answer.get("Buckets", []):
                yield _record(capability, f"arn:aws:s3:::{bucket['Name']}", None, bucket)
            return
        for region in self.config.regions or await self._enabled_regions():
            async for record in self._in_region(capability, region, account):
                yield record

    # ── inside ───────────────────────────────────────────────────────────────

    async def _in_region(
        self, capability: Capability, region: str, account: str
    ) -> AsyncIterator[RawRecord]:
        """One capability's resources in one region, each known by its ARN."""
        if capability is Capability.INSTANCES:
            async for page in self._pages("ec2", region, "describe_instances"):
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        arn = f"arn:aws:ec2:{region}:{account}:instance/{instance['InstanceId']}"
                        yield _record(capability, arn, region, instance)
        elif capability is Capability.NETWORKS:
            async for page in self._pages("ec2", region, "describe_vpcs"):
                for vpc in page.get("Vpcs", []):
                    owner = vpc.get("OwnerId", account)
                    arn = f"arn:aws:ec2:{region}:{owner}:vpc/{vpc['VpcId']}"
                    yield _record(capability, arn, region, vpc)
        elif capability is Capability.DB_INSTANCES:
            async for page in self._pages("rds", region, "describe_db_instances"):
                for database in page.get("DBInstances", []):
                    yield _record(capability, database["DBInstanceArn"], region, database)
        elif capability is Capability.FUNCTIONS:
            async for page in self._pages("lambda", region, "list_functions"):
                for function in page.get("Functions", []):
                    yield _record(
                        capability,
                        function["FunctionArn"],
                        region,
                        function,
                        updated=function.get("LastModified"),
                    )
        elif capability is Capability.LOAD_BALANCERS:
            async for page in self._pages("elbv2", region, "describe_load_balancers"):
                for balancer in page.get("LoadBalancers", []):
                    yield _record(capability, balancer["LoadBalancerArn"], region, balancer)
        elif capability is Capability.CLUSTERS:
            async for page in self._pages("eks", region, "list_clusters"):
                for name in page.get("clusters", []):
                    described = await self._call("eks", region, _describe_cluster(str(name)))
                    cluster = described["cluster"]
                    yield _record(capability, cluster["arn"], region, cluster)
        else:
            msg = f"AWS does not read {capability}"
            raise ValueError(msg)

    async def _account(self, account: str) -> dict[str, Any]:
        """The account: its id, its aliases and its organisation — the two
        last only where the policy allows reading them (docs/connectors/
        cloud.md), and none where the account is in no organisation."""
        found: dict[str, Any] = {"Account": account}
        aliases = await self._optional("iam", lambda iam: iam.list_account_aliases())
        if aliases is not None:
            found["AccountAliases"] = list(aliases.get("AccountAliases", []))
        organization = await self._optional(
            "organizations", lambda organizations: organizations.describe_organization()
        )
        if organization is not None and organization.get("Organization"):
            found["Organization"] = organization["Organization"]
        stored: dict[str, Any] = json.loads(json.dumps(found, default=str))
        return stored

    async def _optional(self, service: str, call: Callable[[Any], Any]) -> Any:
        """A call whose refusal, or whose nothing to read, is not a failure:
        None, and the rest is read."""
        try:
            return await self._call(service, HOME_REGION, call)
        except ConnectorError as error:
            if error.diagnostic.code in (
                DiagnosticCode.PERMISSION_DENIED,
                DiagnosticCode.NOT_FOUND,
            ):
                return None
            raise

    async def _pages(
        self, service: str, region: str, operation: str
    ) -> AsyncIterator[dict[str, Any]]:
        """A boto3 paginator, a page at a time, each fetched in a thread with
        its failures mapped like any call."""
        pages = await self._call(
            service, region, lambda client: iter(client.get_paginator(operation).paginate())
        )
        while True:
            page = await self._call(service, region, lambda _client: next(pages, None))
            if page is None:
                return
            yield page

    async def _enabled_regions(self) -> list[str]:
        answer = await self._call(
            "ec2", HOME_REGION, lambda ec2: ec2.describe_regions(AllRegions=False)
        )
        return sorted(str(region["RegionName"]) for region in answer.get("Regions", []))

    async def _probe(self, region: str) -> list[Capability]:
        """Which services these credentials can read, one light call each."""
        probes: dict[Capability, tuple[str, Callable[[Any], Any]]] = {
            Capability.INSTANCES: ("ec2", lambda c: c.describe_instances(MaxResults=5)),
            Capability.DB_INSTANCES: ("rds", lambda c: c.describe_db_instances(MaxRecords=20)),
            Capability.BUCKETS: ("s3", lambda c: c.list_buckets()),
            Capability.FUNCTIONS: ("lambda", lambda c: c.list_functions(MaxItems=1)),
            Capability.CLUSTERS: ("eks", lambda c: c.list_clusters(maxResults=1)),
            Capability.NETWORKS: ("ec2", lambda c: c.describe_vpcs(MaxResults=5)),
            Capability.LOAD_BALANCERS: (
                "elbv2",
                lambda c: c.describe_load_balancers(PageSize=1),
            ),
        }
        answers = await asyncio.gather(
            *(self._call(service, region, call) for service, call in probes.values()),
            return_exceptions=True,
        )
        found: list[Capability] = []
        for capability, answer in zip(probes, answers, strict=True):
            if isinstance(answer, ConnectorError):
                if answer.diagnostic.code is DiagnosticCode.PERMISSION_DENIED:
                    continue  # the policy leaves it out: not a failure
                raise answer
            if isinstance(answer, BaseException):
                raise answer
            found.append(capability)
        # The account is read wherever its resources are: who am I always
        # answers, and its alias and organisation are read when allowed.
        return [*found, Capability.ACCOUNTS] if found else []

    async def _call(self, service: str, region: str, call: Callable[[Any], Any]) -> Any:
        """One AWS call, in a thread — boto3 is synchronous — its failures
        turned into the framework's diagnostics."""
        try:
            return await asyncio.to_thread(lambda: call(self._client(service, region)))
        except ClientError as error:
            raise self._refuse(error) from error
        except (ReadTimeoutError, ConnectTimeoutError) as error:
            raise diagnose(
                DiagnosticCode.TIMEOUT, detail=f"{service}: {type(error).__name__}"
            ) from error
        except EndpointConnectionError as error:
            raise diagnose(
                DiagnosticCode.NETWORK_UNREACHABLE, detail=f"{service}: {type(error).__name__}"
            ) from error
        except BotoCoreError as error:
            raise diagnose(
                DiagnosticCode.UNKNOWN,
                detail=f"{service}: {type(error).__name__}",
                secrets=self._secrets(),
            ) from error

    def _client(self, service: str, region: str) -> Any:
        """A boto3 client, from the session — with the assumed role's
        credentials when one is configured. The tests replace this."""
        return self._session().client(service, region_name=region, config=CLIENT_CONFIG)

    def _session(self) -> Any:
        """The session, built once per connector — so a role is assumed once,
        not once per client. The first call of every public method is a
        single one (who am I, the regions), so the parallel probes that
        follow find it built."""
        if self._built is None:
            self._built = self._build_session()
        return self._built

    def _build_session(self) -> Any:
        import boto3  # only a connector that runs needs it

        base = boto3.session.Session(
            aws_access_key_id=self.credentials.access_key_id.get_secret_value(),
            aws_secret_access_key=self.credentials.secret_access_key.get_secret_value(),
        )
        if self.config.role_arn is None:
            return base
        request: dict[str, Any] = {"RoleArn": self.config.role_arn, "RoleSessionName": "leka"}
        if self.config.external_id:
            request["ExternalId"] = self.config.external_id
        assumed = base.client("sts", region_name=HOME_REGION, config=CLIENT_CONFIG).assume_role(
            **request
        )["Credentials"]
        return boto3.session.Session(
            aws_access_key_id=assumed["AccessKeyId"],
            aws_secret_access_key=assumed["SecretAccessKey"],
            aws_session_token=assumed["SessionToken"],
        )

    def _refuse(self, error: ClientError) -> ConnectorError:
        """AWS's error codes, as the framework's diagnostics."""
        code_name = str(error.response.get("Error", {}).get("Code", ""))
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code_name in _AUTH_INVALID:
            code = DiagnosticCode.AUTH_INVALID
        elif code_name in _AUTH_EXPIRED:
            code = DiagnosticCode.AUTH_EXPIRED
        elif code_name in _DENIED:
            code = DiagnosticCode.PERMISSION_DENIED
        elif code_name in _THROTTLED:
            code = DiagnosticCode.RATE_LIMITED
        elif code_name in _ABSENT:
            code = DiagnosticCode.NOT_FOUND
        elif isinstance(status, int) and status >= 500:
            code = DiagnosticCode.PROVIDER_ERROR
        else:
            code = DiagnosticCode.UNKNOWN
        return diagnose(
            code,
            provider_status=status if isinstance(status, int) else None,
            retry_after=60 if code is DiagnosticCode.RATE_LIMITED else None,
            detail=f"{error.operation_name}: {code_name}: {error}"[:300],
            secrets=self._secrets(),
        )

    def _secrets(self) -> list[str]:
        return [
            self.credentials.access_key_id.get_secret_value(),
            self.credentials.secret_access_key.get_secret_value(),
        ]


def _record(
    kind: Capability,
    arn: str,
    region: str | None,
    resource: dict[str, Any],
    *,
    updated: object = None,
) -> RawRecord:
    return RawRecord(
        kind=kind,
        external_id=arn,
        container=region,
        # boto3 hands back datetimes; the payload is stored as JSON.
        payload=json.loads(json.dumps(resource, default=str)),
        updated_at=_parse(updated),
        fetched_at=datetime.now(UTC),
    )


def _parse(value: object) -> datetime | None:
    """Lambda's LastModified, '2026-09-27T10:00:00.000+0000'."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        return None


def _describe_cluster(name: str) -> Callable[[Any], Any]:
    """EKS lists names; the cluster itself — its ARN, version, endpoint — is one more call."""
    return lambda eks: eks.describe_cluster(name=name)
