"""S3ObjectStore against a real S3 server, not against our own stand-in.

tests/test_object_storage.py exercises the adapter against FakeS3, which we
wrote. That is useful and it is circular: it proves the adapter agrees with
what WE believe S3 does. The two beliefs most worth doubting are the ones
this file exists to settle.

**Pagination.** S3 returns at most 1000 keys per list, and deletes at most
1000 per request. A workspace holds far more. The fake pages every two keys
to make the loop run, but a loop that works against a fake pager can still
be wrong about `NextContinuationToken`, or about which key to resume from.

**"Not there" versus "not allowed".** The adapter must tell a missing object
from a refused one. Confusing them is not a cosmetic bug: the retention sweep
deletes a row once it believes the object is gone, so a permissions failure
read as "already deleted" loses the only record of bytes we still hold and
still pay for.

MinIO is the server. It implements the same API, it runs in a container, it
costs nothing, and it is not something we wrote.

Skipped when no server is reachable — except in CI, where LEKA_REQUIRE_S3_TESTS
turns the skip into a failure. A test that quietly stops running is worse than
one that was never written, because the green tick says otherwise.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest

from leka.platform.storage import (
    ObjectNotFoundError,
    ObjectStoreError,
    S3ObjectStore,
    from_bytes,
    object_key,
    workspace_prefix,
)

pytestmark = pytest.mark.integration

ENDPOINT = os.environ.get("LEKA_S3_TEST_ENDPOINT", "http://127.0.0.1:9000")
ACCESS_KEY = os.environ.get("LEKA_S3_TEST_ACCESS_KEY", "minioadmin")
SECRET_KEY = os.environ.get("LEKA_S3_TEST_SECRET_KEY", "minioadmin")

# CI sets this. Locally it is unset, so a developer with no MinIO running
# gets skips rather than a wall of failures — but the pipeline never does.
REQUIRED = os.environ.get("LEKA_REQUIRE_S3_TESTS") == "1"

HOW_TO_START = (
    f"no S3 server at {ENDPOINT}. Start one with `docker compose up -d minio`, "
    "or point LEKA_S3_TEST_ENDPOINT at another."
)

# Just over S3's 1000-key page limit. The number is the whole point: 999 would
# pass against an adapter that silently stops after the first page.
OVER_ONE_PAGE = 1005


def _client() -> object:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )


@pytest.fixture(scope="session")
def bucket() -> Iterator[str]:
    """A bucket of our own, removed afterwards.

    Named uniquely so two runs on the same server — a developer and a
    rerun, or two CI jobs — cannot see each other's objects.
    """
    import botocore.exceptions

    name = f"leka-test-{uuid.uuid4().hex[:12]}"
    client = _client()
    try:
        client.create_bucket(Bucket=name)  # type: ignore[attr-defined]
    except botocore.exceptions.EndpointConnectionError:
        if REQUIRED:
            pytest.fail(
                f"{HOW_TO_START} LEKA_REQUIRE_S3_TESTS=1, so this is a failure "
                "rather than a skip: the S3 adapter would otherwise go "
                "unverified against a real server while CI reports green."
            )
        pytest.skip(HOW_TO_START)

    yield name

    paginator = client.get_paginator("list_objects_v2")  # type: ignore[attr-defined]
    for page in paginator.paginate(Bucket=name):
        keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
        if keys:
            client.delete_objects(Bucket=name, Delete={"Objects": keys})  # type: ignore[attr-defined]
    client.delete_bucket(Bucket=name)  # type: ignore[attr-defined]


@pytest.fixture
def store(bucket: str) -> S3ObjectStore:
    return S3ObjectStore(
        bucket,
        endpoint_url=ENDPOINT,
        region="us-east-1",
        access_key_id=ACCESS_KEY,
        secret_access_key=SECRET_KEY,
    )


async def _drain(chunks: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in chunks])


# ── The adapter keeps what it was given ──────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("json", b'{"repository": "payment-api"}'),
        ("binary", bytes(range(256)) * 64),
        ("empty", b""),
        ("utf8", "accentué — ünïcode 🎯".encode()),
    ],
)
async def test_a_real_bucket_returns_exactly_what_it_was_given(
    store: S3ObjectStore, label: str, payload: bytes
) -> None:
    key = f"round-trip/{uuid.uuid4()}/{label}"

    written = await store.put(key, from_bytes(payload), content_type="application/octet-stream")
    read_back = await _drain(store.get(key))

    assert read_back == payload, f"{label} did not survive a real round trip"
    assert written.size_bytes == len(payload)
    assert written.checksum_sha256 == hashlib.sha256(payload).hexdigest()


async def test_a_real_bucket_tells_an_empty_object_from_a_missing_one(
    store: S3ObjectStore,
) -> None:
    """ "Nothing" is a real answer from an API, and it is not the same as
    "we never stored this"."""
    key = f"empty/{uuid.uuid4()}"
    await store.put(key, from_bytes(b""), content_type="text/plain")

    assert await _drain(store.get(key)) == b""
    assert await store.exists(key) is True
    assert await store.exists(f"never-written/{uuid.uuid4()}") is False
    with pytest.raises(ObjectNotFoundError):
        await _drain(store.get(f"never-written/{uuid.uuid4()}"))


async def test_a_real_bucket_says_whether_a_delete_removed_anything(
    store: S3ObjectStore,
) -> None:
    """S3 deletes are idempotent and report success either way, so the
    adapter has to check first. This is where that gets verified."""
    key = f"doomed/{uuid.uuid4()}"
    await store.put(key, from_bytes(b"x"), content_type="text/plain")

    assert await store.delete(key) is True
    assert await store.delete(key) is False


# ── Past S3's page limit ─────────────────────────────────────────────────────


async def test_listing_and_purging_go_past_one_page(store: S3ObjectStore) -> None:
    """S3 lists and deletes at most 1000 keys per request.

    A customer's workspace holds far more, and erasing one is a prefix
    delete. An adapter that stopped at the first page would leave the rest
    of that customer's data in the bucket, report success, and nothing would
    contradict it — the rows are already gone by then.

    1005 objects, deliberately. 999 would pass against exactly the bug this
    is looking for.
    """
    import asyncio

    workspace, source = uuid.uuid4(), uuid.uuid4()
    when = datetime.now(UTC)
    keys = [object_key(workspace, source, when) for _ in range(OVER_ONE_PAGE)]
    await asyncio.gather(
        *[store.put(key, from_bytes(b"x"), content_type="text/plain") for key in keys]
    )

    listed = [key async for key in store.iter_prefix(workspace_prefix(workspace))]
    assert len(listed) == OVER_ONE_PAGE, (
        f"iter_prefix saw {len(listed)} of {OVER_ONE_PAGE} objects — it stops at a page boundary"
    )

    removed = await store.delete_prefix(workspace_prefix(workspace))
    assert removed == OVER_ONE_PAGE, (
        f"delete_prefix removed {removed} of {OVER_ONE_PAGE} — "
        "a customer's data would be left behind"
    )
    assert [key async for key in store.iter_prefix(workspace_prefix(workspace))] == []


async def test_a_prefix_delete_leaves_its_neighbours_alone(store: S3ObjectStore) -> None:
    """Erasing one customer must not touch the one whose id sorts next to it."""
    doomed, kept = uuid.uuid4(), uuid.uuid4()
    source, when = uuid.uuid4(), datetime.now(UTC)
    for _ in range(3):
        await store.put(
            object_key(doomed, source, when), from_bytes(b"x"), content_type="text/plain"
        )
    survivor = object_key(kept, source, when)
    await store.put(survivor, from_bytes(b"x"), content_type="text/plain")

    assert await store.delete_prefix(workspace_prefix(doomed)) == 3
    assert await store.exists(survivor)


# ── Refused is not the same as absent ────────────────────────────────────────


async def test_a_refused_request_is_an_error_and_not_a_missing_object(
    bucket: str,
) -> None:
    """The one that would cost us data.

    The retention sweep deletes a row once it believes the object is gone.
    If a permissions failure came back as "not there", the row would go and
    the bytes would stay — and nothing would ever mention them again. They
    are not in any listing we own, and the bill keeps arriving.
    """
    wrong = S3ObjectStore(
        bucket,
        endpoint_url=ENDPOINT,
        region="us-east-1",
        access_key_id="not-a-real-key",
        secret_access_key="not-a-real-secret-either",
    )

    with pytest.raises(ObjectStoreError):
        await wrong.exists("whatever")


async def test_a_bucket_that_does_not_exist_is_an_error_too(store: S3ObjectStore) -> None:
    """A typo in LEKA_S3_BUCKET must be loud on the first call, not read as
    an empty store that the sweep is then free to reconcile against."""
    missing = S3ObjectStore(
        f"leka-no-such-bucket-{uuid.uuid4().hex[:12]}",
        endpoint_url=ENDPOINT,
        region="us-east-1",
        access_key_id=ACCESS_KEY,
        secret_access_key=SECRET_KEY,
    )

    with pytest.raises(ObjectStoreError):
        await missing.delete_prefix("anything/")


# ── The guard on the skip ────────────────────────────────────────────────────


def test_these_tests_are_not_silently_skipped_in_ci() -> None:
    """A skip is acceptable on a laptop with no MinIO. It is not acceptable
    in a pipeline that reports the adapter as verified.

    If this file ever stops running in CI — the service removed, the
    variable dropped, the endpoint changed — this fails instead of the
    suite quietly covering nothing.
    """
    if os.environ.get("CI") == "true":
        assert REQUIRED, (
            "running in CI without LEKA_REQUIRE_S3_TESTS=1. The S3 tests would "
            "skip on any connection problem and the pipeline would still be "
            "green, which is how an unverified adapter reaches production."
        )
