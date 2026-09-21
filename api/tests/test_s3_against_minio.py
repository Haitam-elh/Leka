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

import asyncio
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

# Which server these tests run against.
#
# MinIO by default: it is what docker compose starts, what CI starts, and it
# costs nothing. Set LEKA_S3_TEST_TARGET=aws to point them at the real bucket
# in the application's own settings instead.
#
# OPT-IN ON PURPOSE. A fallback to whatever LEKA_S3_* happens to hold would
# mean a developer with a filled .env silently running the suite against a
# paid bucket — writing a thousand objects into it to test pagination. The
# switch is a separate variable, and it carries no secret.
TARGET = os.environ.get("LEKA_S3_TEST_TARGET", "minio").lower()
AGAINST_AWS = TARGET == "aws"

if AGAINST_AWS:
    # Read from the application's configuration rather than from test-only
    # variables: the credential lives in .env once, and nowhere else.
    from leka.core.config import settings as _settings

    ENDPOINT = _settings.s3_endpoint_url  # None means AWS's own endpoints
    REGION = _settings.s3_region
    ACCESS_KEY = _settings.s3_access_key_id or ""
    SECRET_KEY = (
        _settings.s3_secret_access_key.get_secret_value() if _settings.s3_secret_access_key else ""
    )
    CONFIGURED_BUCKET = _settings.s3_bucket
else:
    ENDPOINT = os.environ.get("LEKA_S3_TEST_ENDPOINT", "http://127.0.0.1:9000")
    REGION = "us-east-1"
    ACCESS_KEY = os.environ.get("LEKA_S3_TEST_ACCESS_KEY", "minioadmin")
    SECRET_KEY = os.environ.get("LEKA_S3_TEST_SECRET_KEY", "minioadmin")
    CONFIGURED_BUCKET = None

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
        region_name=REGION,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )


@pytest.fixture(scope="session")
def bucket() -> Iterator[str]:
    """A bucket to work in, whether we may create one or not.

    Against MinIO we make a disposable bucket and delete it afterwards.

    Against AWS we do neither, and that is the IAM policy being right rather
    than a limitation: `leka-payloads-readwrite` grants no CreateBucket and
    no DeleteBucket, so a leaked key cannot make resources or destroy the
    bucket. A test suite is not a reason to widen it. We borrow the existing
    bucket and stay inside a prefix of our own — see the `prefix` fixture.
    """
    import botocore.exceptions

    client = _client()

    if AGAINST_AWS:
        if not CONFIGURED_BUCKET:
            pytest.fail(
                "LEKA_S3_TEST_TARGET=aws but LEKA_S3_BUCKET is not set in .env. "
                "The bucket, region and credentials come from the application's "
                "own settings when running against AWS."
            )
        try:
            client.head_bucket(Bucket=CONFIGURED_BUCKET)  # type: ignore[attr-defined]
        except botocore.exceptions.EndpointConnectionError:
            pytest.fail(f"cannot reach AWS S3 at {ENDPOINT or 'the default endpoint'}")
        except botocore.exceptions.ClientError as error:
            pytest.fail(
                f"cannot reach bucket {CONFIGURED_BUCKET!r}: {error}. Check "
                "LEKA_S3_ACCESS_KEY_ID, LEKA_S3_SECRET_ACCESS_KEY and the region."
            )
        yield CONFIGURED_BUCKET
        return

    name = f"leka-test-{uuid.uuid4().hex[:12]}"
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


@pytest.fixture(scope="session")
def prefix(bucket: str) -> Iterator[str]:
    """Every key this suite writes lives under one prefix, removed afterwards.

    Against MinIO the bucket is disposable and this changes nothing. Against
    a real bucket it is what makes the suite safe to run: it cannot see or
    delete anything it did not write, whatever else is in there, and the
    teardown is one prefix rather than "everything".

    Unique per run, so two runs at once — a developer and CI, or a rerun
    after a timeout — cannot delete each other's objects halfway through.
    """
    path = f"validation/{uuid.uuid4().hex}/"

    yield path

    client = _client()
    paginator = client.get_paginator("list_objects_v2")  # type: ignore[attr-defined]
    removed = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=path):
        keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
        if keys:
            client.delete_objects(Bucket=bucket, Delete={"Objects": keys})  # type: ignore[attr-defined]
            removed += len(keys)
    # Printed, not logged: the point is that a human reading the test output
    # can see the bucket was left clean. noqa because this is that exception.
    print(f"\nprefix {path} cleaned: {removed} objects removed")  # noqa: T201


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
    store: S3ObjectStore, prefix: str, label: str, payload: bytes
) -> None:
    key = f"{prefix}round-trip/{uuid.uuid4()}/{label}"

    written = await store.put(key, from_bytes(payload), content_type="application/octet-stream")
    read_back = await _drain(store.get(key))

    assert read_back == payload, f"{label} did not survive a real round trip"
    assert written.size_bytes == len(payload)
    assert written.checksum_sha256 == hashlib.sha256(payload).hexdigest()


async def test_a_real_bucket_tells_an_empty_object_from_a_missing_one(
    store: S3ObjectStore, prefix: str
) -> None:
    """ "Nothing" is a real answer from an API, and it is not the same as
    "we never stored this"."""
    key = f"{prefix}empty/{uuid.uuid4()}"
    await store.put(key, from_bytes(b""), content_type="text/plain")

    assert await _drain(store.get(key)) == b""
    assert await store.exists(key) is True
    assert await store.exists(f"{prefix}never-written/{uuid.uuid4()}") is False
    with pytest.raises(ObjectNotFoundError):
        await _drain(store.get(f"{prefix}never-written/{uuid.uuid4()}"))


async def test_a_real_bucket_says_whether_a_delete_removed_anything(
    store: S3ObjectStore, prefix: str
) -> None:
    """S3 deletes are idempotent and report success either way, so the
    adapter has to check first. This is where that gets verified."""
    key = f"{prefix}doomed/{uuid.uuid4()}"
    await store.put(key, from_bytes(b"x"), content_type="text/plain")

    assert await store.delete(key) is True
    assert await store.delete(key) is False


# ── Past S3's page limit ─────────────────────────────────────────────────────


async def test_listing_and_purging_go_past_one_page(store: S3ObjectStore, prefix: str) -> None:
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
    keys = [prefix + object_key(workspace, source, when) for _ in range(OVER_ONE_PAGE)]
    await asyncio.gather(
        *[store.put(key, from_bytes(b"x"), content_type="text/plain") for key in keys]
    )

    listed = [key async for key in store.iter_prefix(prefix + workspace_prefix(workspace))]
    assert len(listed) == OVER_ONE_PAGE, (
        f"iter_prefix saw {len(listed)} of {OVER_ONE_PAGE} objects — it stops at a page boundary"
    )

    removed = await store.delete_prefix(prefix + workspace_prefix(workspace))
    assert removed == OVER_ONE_PAGE, (
        f"delete_prefix removed {removed} of {OVER_ONE_PAGE} — "
        "a customer's data would be left behind"
    )
    assert [key async for key in store.iter_prefix(prefix + workspace_prefix(workspace))] == []


async def test_a_prefix_delete_leaves_its_neighbours_alone(
    store: S3ObjectStore, prefix: str
) -> None:
    """Erasing one customer must not touch the one whose id sorts next to it."""
    doomed, kept = uuid.uuid4(), uuid.uuid4()
    source, when = uuid.uuid4(), datetime.now(UTC)
    for _ in range(3):
        await store.put(
            prefix + object_key(doomed, source, when),
            from_bytes(b"x"),
            content_type="text/plain",
        )
    survivor = prefix + object_key(kept, source, when)
    await store.put(survivor, from_bytes(b"x"), content_type="text/plain")

    assert await store.delete_prefix(prefix + workspace_prefix(doomed)) == 3
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


# ── Bounded memory, against a real server ────────────────────────────────────


async def test_the_upload_footprint_does_not_grow_with_the_payload(
    store: S3ObjectStore, prefix: str
) -> None:
    """The bound, stated as what it actually is: a constant.

    An absolute ceiling here would be a guess. This path goes through
    upload_fileobj, which keeps buffers of its own for a multipart upload —
    storage.py bounds them, but the exact number depends on part size,
    concurrency and boto3's internals, and hard-coding it would make this
    test a record of one version's behaviour.

    What must be true regardless is that the footprint does NOT track the
    payload. So the same upload runs at two sizes, four times apart, and the
    peaks are compared. Before this was fixed the adapter drained the whole
    iterator into a list first, so quadrupling the object quadrupled the
    peak; now it barely moves.

    Worth doing against a real server rather than trusting the local result.
    It was exactly here that boto3's max_in_memory_upload_chunks turned out
    to default to ten parts — 80 MB of buffers that nothing in a stand-in
    would ever have shown.
    """
    import tracemalloc

    from leka.platform.storage import CHUNK_SIZE

    async def synthetic(chunks: int) -> AsyncIterator[bytes]:
        for index in range(chunks):
            yield bytes((index % 251,)) * CHUNK_SIZE

    async def peak_for(chunks: int) -> int:
        key = f"{prefix}footprint/{uuid.uuid4()}.bin"
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            written = await store.put(
                key, synthetic(chunks), content_type="application/octet-stream"
            )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert written.size_bytes == chunks * CHUNK_SIZE
        await store.delete(key)
        return peak

    small = await peak_for(16)
    large = await peak_for(64)

    megabyte = 1024 * 1024
    growth = large - small
    assert growth < 8 * CHUNK_SIZE, (
        f"quadrupling the payload moved the peak by {growth / megabyte:.1f} MB "
        f"({small / megabyte:.1f} MB for 16 MB, {large / megabyte:.1f} MB for "
        "64 MB). Memory is tracking the object rather than the buffers."
    )


async def test_a_payload_over_the_ceiling_leaves_nothing_in_the_bucket(
    store: S3ObjectStore, prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal must not leave half an object behind.

    Worth checking against a real server specifically: a multipart upload
    interrupted partway leaves parts on the server unless it is aborted, and
    those parts are invisible to a normal listing while still being billed.
    """
    from leka.core.config import settings
    from leka.platform import storage
    from leka.platform.storage import CHUNK_SIZE, ObjectTooLargeError

    ceiling = 4 * CHUNK_SIZE
    monkeypatch.setattr(
        storage, "settings", settings.model_copy(update={"max_object_bytes": ceiling})
    )

    async def synthetic() -> AsyncIterator[bytes]:
        for index in range(32):
            yield bytes((index % 251,)) * CHUNK_SIZE

    key = f"{prefix}too-big/{uuid.uuid4()}.bin"

    with pytest.raises(ObjectTooLargeError, match="LEKA_MAX_OBJECT_BYTES"):
        await store.put(key, synthetic(), content_type="application/octet-stream")

    assert await store.exists(key) is False

    incomplete = await asyncio.to_thread(
        lambda: _client().list_multipart_uploads(  # type: ignore[attr-defined]
            Bucket=store._bucket, Prefix=prefix
        )
    )
    assert not incomplete.get("Uploads"), (
        "an aborted upload left multipart parts on the server: invisible to a listing, and billed"
    )
