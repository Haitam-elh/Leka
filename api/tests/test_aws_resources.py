"""What the AWS connector streams to the sync engine (LEKA-347).

The fake AWS of test_aws_connector.py, whose paginators serve a list answer
as its pages. What is asserted: every region of the scope is read, S3 once,
each resource by its ARN with its region as container, boto3's datetimes
stored as text, and a failure mid-listing stops it with its diagnostic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from leka.connectors.aws import AwsConnector
from tests.test_aws_connector import _connector, denied

ELB_ARN = "arn:aws:elasticloadbalancing:eu-west-3:1:loadbalancer/app/web/1"


async def _stream(
    capability: Capability, overrides: dict[str, Any], **config: Any
) -> list[RawRecord]:
    connector, _ = _connector(overrides, **config)
    return [record async for record in connector.iter_resources(capability)]


def test_every_cloud_capability_is_listed_whole() -> None:
    manifest = AwsConnector.manifest
    assert manifest.listed_whole == manifest.capabilities


async def test_instances_are_read_in_every_region_of_the_scope_across_pages() -> None:
    launched = datetime(2026, 9, 1, tzinfo=UTC)
    pages = [
        {"Reservations": [{"Instances": [{"InstanceId": "i-1", "LaunchTime": launched}]}]},
        {"Reservations": [{"Instances": [{"InstanceId": "i-2", "LaunchTime": launched}]}]},
    ]

    records = await _stream(
        Capability.INSTANCES, {"describe_instances": pages}, regions=["eu-west-3", "eu-central-1"]
    )

    assert [(r.external_id, r.container) for r in records] == [
        ("arn:aws:ec2:eu-west-3:123456789012:instance/i-1", "eu-west-3"),
        ("arn:aws:ec2:eu-west-3:123456789012:instance/i-2", "eu-west-3"),
        ("arn:aws:ec2:eu-central-1:123456789012:instance/i-1", "eu-central-1"),
        ("arn:aws:ec2:eu-central-1:123456789012:instance/i-2", "eu-central-1"),
    ]
    assert records[0].payload["LaunchTime"] == str(launched)  # stored as text


async def test_without_a_scope_every_enabled_region_is_read() -> None:
    connector, calls = _connector(
        {"describe_vpcs": {"Vpcs": [{"VpcId": "vpc-1", "OwnerId": "123456789012"}]}}
    )

    records = [r async for r in connector.iter_resources(Capability.NETWORKS)]

    assert {region for op, region in calls if op == "describe_vpcs"} == {
        "eu-west-3",
        "eu-central-1",
    }
    assert (
        records[0].external_id.startswith("arn:aws:ec2:") and ":vpc/vpc-1" in records[0].external_id
    )


async def test_buckets_are_listed_once_whatever_the_regions() -> None:
    connector, calls = _connector(
        {"list_buckets": {"Buckets": [{"Name": "acme-logs"}]}},
        regions=["eu-west-3", "eu-central-1"],
    )

    records = [r async for r in connector.iter_resources(Capability.BUCKETS)]

    assert [(r.external_id, r.container) for r in records] == [("arn:aws:s3:::acme-logs", None)]
    assert [op for op, _ in calls].count("list_buckets") == 1


async def test_a_cluster_is_described_after_it_is_listed() -> None:
    overrides = {
        "list_clusters": {"clusters": ["prod"]},
        "describe_cluster": {
            "cluster": {
                "name": "prod",
                "arn": "arn:aws:eks:eu-west-3:123456789012:cluster/prod",
                "version": "1.31",
            }
        },
    }

    records = await _stream(Capability.CLUSTERS, overrides, regions=["eu-west-3"])

    assert [r.external_id for r in records] == ["arn:aws:eks:eu-west-3:123456789012:cluster/prod"]
    assert records[0].payload["version"] == "1.31"


async def test_a_function_is_dated_by_its_last_change_and_others_by_arn() -> None:
    overrides = {
        "list_functions": {
            "Functions": [
                {
                    "FunctionArn": "arn:aws:lambda:eu-west-3:1:function:f",
                    "LastModified": "2026-09-20T10:00:00.000+0000",
                }
            ]
        },
        "describe_db_instances": {
            "DBInstances": [{"DBInstanceArn": "arn:aws:rds:eu-west-3:1:db:main"}]
        },
        "describe_load_balancers": {"LoadBalancers": [{"LoadBalancerArn": ELB_ARN}]},
    }

    (function,) = await _stream(Capability.FUNCTIONS, overrides, regions=["eu-west-3"])
    (database,) = await _stream(Capability.DB_INSTANCES, overrides, regions=["eu-west-3"])
    (balancer,) = await _stream(Capability.LOAD_BALANCERS, overrides, regions=["eu-west-3"])

    assert function.updated_at == datetime(2026, 9, 20, 10, tzinfo=UTC)
    assert database.external_id.endswith(":db:main")
    assert balancer.external_id.endswith("loadbalancer/app/web/1")


async def test_a_quota_hit_mid_listing_keeps_what_was_read_and_says_when_to_return() -> None:
    pages = [
        {"Reservations": [{"Instances": [{"InstanceId": "i-1"}]}]},
        denied("DescribeInstances", "RequestLimitExceeded", 503),
    ]
    connector, _ = _connector({"describe_instances": pages}, regions=["eu-west-3"])
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for record in connector.iter_resources(Capability.INSTANCES):
            read.append(record)

    assert len(read) == 1
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert caught.value.diagnostic.retry_after == 60
