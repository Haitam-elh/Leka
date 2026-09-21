"""The object store, and the row that speaks for what it holds.

LEKA-332's structural half. Two things are being checked here and they are
not the same thing: that an adapter gives back exactly what it was given,
and that a row describing an object cannot be read, written or guessed
across a tenant boundary.

The S3 adapter is exercised against a stand-in rather than a real bucket.
That is not a shortcut around testing it: the logic worth checking — telling
"no such key" from a permissions failure, paginating a delete past S3's
thousand-key limit — is precisely the logic that never runs in a test needing
credentials, which means it never runs at all until the day it matters.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from leka.connectors import Source, SourceKind
from leka.db import (
    CrossWorkspaceWriteError,
    MissingWorkspaceScopeError,
    session_factory,
    system_scope,
)
from leka.ingestion import RawPayload, RawPayloadRepository
from leka.platform import Workspace
from leka.platform.storage import (
    LocalObjectStore,
    ObjectNotFoundError,
    ObjectStore,
    ObjectStoreError,
    S3ObjectStore,
    from_bytes,
    object_key,
    workspace_prefix,
)

pytestmark = pytest.mark.integration


async def _drain(chunks: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in chunks])


@pytest.fixture
def store(tmp_path: Path) -> LocalObjectStore:
    return LocalObjectStore(tmp_path)


# ── The adapter keeps what it was given ──────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("json", b'{"repository": "payment-api", "stars": 12}'),
        # Binary, because a payload is not always text and an adapter that
        # decodes somewhere in the middle only breaks on the first tarball.
        ("binary", bytes(range(256)) * 64),
        # Empty, because "nothing" is a real answer from an API and the
        # difference between an empty object and a missing one matters.
        ("empty", b""),
        ("utf8", "accentué — ünïcode 🎯".encode()),
    ],
)
async def test_an_object_comes_back_exactly_as_it_went_in(
    store: LocalObjectStore, label: str, payload: bytes
) -> None:
    key = f"round-trip/{label}"

    written = await store.put(key, from_bytes(payload), content_type="application/octet-stream")
    read_back = await _drain(store.get(key))

    assert read_back == payload, f"{label} payload did not survive the round trip"
    assert written.size_bytes == len(payload)
    assert await store.exists(key)


async def test_the_store_measures_the_object_rather_than_believing_the_caller(
    store: LocalObjectStore,
) -> None:
    """size_bytes and the checksum are what makes corruption detectable later.

    They are only worth anything if they describe what was actually written,
    so they are computed by the store as the bytes go past — a caller cannot
    hand in a length and a hash of its own.
    """
    import hashlib

    payload = b"a" * 5000
    written = await store.put("measured", from_bytes(payload), content_type="text/plain")

    assert written.size_bytes == 5000
    assert written.checksum_sha256 == hashlib.sha256(payload).hexdigest()
    assert written.content_type == "text/plain"


async def test_identical_payloads_share_a_fingerprint(store: LocalObjectStore) -> None:
    """Re-syncing the same repository every night produces the same bytes.

    Telling "we already have this" from "this changed" is what the checksum
    is for — that, and noticing an object that has silently rotted before we
    analyse it and answer a customer with something untrue.
    """
    payload = b'{"commit": "25ee3d7", "message": "same as yesterday"}'

    first = await store.put("copy-a", from_bytes(payload), content_type="application/json")
    second = await store.put("copy-b", from_bytes(payload), content_type="application/json")

    assert first.checksum_sha256 == second.checksum_sha256
    assert first.key != second.key, "different objects must not share a key"


async def test_a_missing_object_is_distinguishable_from_an_empty_one(
    store: LocalObjectStore,
) -> None:
    await store.put("present-but-empty", from_bytes(b""), content_type="text/plain")

    assert await _drain(store.get("present-but-empty")) == b""
    assert not await store.exists("never-written")
    with pytest.raises(ObjectNotFoundError):
        await _drain(store.get("never-written"))


async def test_deleting_says_whether_there_was_anything_there(store: LocalObjectStore) -> None:
    await store.put("doomed", from_bytes(b"x"), content_type="text/plain")

    assert await store.delete("doomed") is True
    assert await store.delete("doomed") is False
    assert not await store.exists("doomed")


async def test_a_prefix_delete_takes_everything_under_it_and_nothing_else(
    store: LocalObjectStore,
) -> None:
    """This is what erasing a customer relies on."""
    doomed = uuid.uuid4()
    kept = uuid.uuid4()
    for index in range(3):
        await store.put(f"{doomed}/src/{index}.json", from_bytes(b"{}"), content_type="app/json")
    await store.put(f"{kept}/src/0.json", from_bytes(b"{}"), content_type="app/json")

    removed = await store.delete_prefix(workspace_prefix(doomed))

    assert removed == 3
    assert [key async for key in store.iter_prefix(workspace_prefix(doomed))] == []
    assert len([key async for key in store.iter_prefix(workspace_prefix(kept))]) == 1


async def test_purging_a_prefix_that_holds_nothing_is_not_an_error(
    store: LocalObjectStore,
) -> None:
    """A workspace that never stored a payload is erased like any other."""
    assert await store.delete_prefix(workspace_prefix(uuid.uuid4())) == 0


async def test_a_key_cannot_escape_the_store_root(store: LocalObjectStore) -> None:
    """Keys are built by this module, so `..` should be impossible.

    Should be. This is the one place where being wrong writes to an arbitrary
    path on the filesystem, so it is checked rather than trusted.
    """
    with pytest.raises(ObjectStoreError):
        await store.put("../../escaped", from_bytes(b"x"), content_type="text/plain")


async def test_an_interrupted_write_leaves_no_half_object(store: LocalObjectStore) -> None:
    """A partial file must never look like a whole one.

    The write goes to a .part file and is renamed once complete, so a crash
    halfway leaves something obviously unfinished rather than a truncated
    payload that reads fine and is wrong.
    """

    async def fails_halfway() -> AsyncIterator[bytes]:
        yield b"the first half"
        msg = "connection reset while reading the payload"
        raise ConnectionError(msg)

    with pytest.raises(ConnectionError):
        await store.put("interrupted", fails_halfway(), content_type="text/plain")

    assert not await store.exists("interrupted")
    assert [key async for key in store.iter_prefix("")] == []


# ── Keys ─────────────────────────────────────────────────────────────────────


def test_a_key_starts_with_the_workspace_and_ends_in_a_uuid() -> None:
    """The shape is load-bearing, not cosmetic.

    The workspace first makes erasing one customer a prefix delete, and makes
    a cross-tenant leak visible at a glance in a log line. The uuid last
    makes the key unguessable: a predictable key is an enumerable key.
    """
    workspace, source = uuid.uuid4(), uuid.uuid4()
    when = datetime(2026, 9, 21, 14, 45, tzinfo=UTC)

    key = object_key(workspace, source, when, extension="json")

    workspace_part, source_part, year, month, day, filename = key.split("/")
    assert workspace_part == str(workspace)
    assert source_part == str(source)
    assert (year, month, day) == ("2026", "09", "21")
    uuid.UUID(filename.removesuffix(".json"))  # raises if it is not one
    assert key.startswith(workspace_prefix(workspace))


def test_two_keys_for_the_same_payload_are_different() -> None:
    """Never content-derived. The same payload in two workspaces producing
    the same key would turn the store into a way of asking "does that
    customer have this file too?"."""
    workspace, source = uuid.uuid4(), uuid.uuid4()
    when = datetime.now(UTC)

    assert object_key(workspace, source, when) != object_key(workspace, source, when)


def test_the_day_in_a_key_is_utc_wherever_the_worker_runs() -> None:
    """Otherwise the same payload lands in a different day's prefix
    depending on which machine collected it."""
    from datetime import timezone

    workspace, source = uuid.uuid4(), uuid.uuid4()
    # 01:30 on the 22nd in Tokyo is still the 21st in UTC.
    tokyo = datetime(2026, 9, 22, 1, 30, tzinfo=timezone(timedelta(hours=9)))

    assert "/2026/09/21/" in object_key(workspace, source, tokyo)


# ── The S3 adapter, against a stand-in ───────────────────────────────────────


class FakeS3:
    """Enough of the S3 API to exercise the adapter's own logic.

    Not a reimplementation of S3 — a stand-in that answers the way S3 does in
    the cases the adapter reasons about: a missing key raises with a 404, and
    listing pages.
    """

    def __init__(self, *, page_size: int = 2) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.page_size = page_size

    # boto3's parameters really are capitalised — Bucket, Key, ExtraArgs. A
    # stand-in that renamed them would not be standing in for anything, so
    # N803 is silenced here and only here.

    class _Error(Exception):
        def __init__(self, code: str, status: int) -> None:
            super().__init__(code)
            self.response = {
                "Error": {"Code": code},
                "ResponseMetadata": {"HTTPStatusCode": status},
            }

    def upload_fileobj(
        self,
        fileobj: Any,
        bucket: str,
        key: str,
        ExtraArgs: dict[str, str] | None = None,  # noqa: N803
    ) -> None:
        self.objects[key] = fileobj.read()
        self.content_types[key] = (ExtraArgs or {}).get("ContentType", "")

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise self._Error("NoSuchKey", 404)
        return {"Body": _FakeBody(self.objects[Key])}

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise self._Error("404", 404)
        return {"ContentLength": len(self.objects[Key])}

    def delete_object(self, Bucket: str, Key: str) -> None:  # noqa: N803
        self.objects.pop(Key, None)

    def delete_objects(self, Bucket: str, Delete: dict[str, Any]) -> None:  # noqa: N803
        for item in Delete["Objects"]:
            self.objects.pop(item["Key"], None)

    def list_objects_v2(self, **request: Any) -> dict[str, Any]:
        prefix = request.get("Prefix", "")
        token = request.get("ContinuationToken")
        keys = sorted(key for key in self.objects if key.startswith(prefix))
        start = keys.index(token) if token in keys else 0
        page = keys[start : start + self.page_size]
        following = keys[start + self.page_size :]
        return {
            "Contents": [{"Key": key} for key in page],
            **({"NextContinuationToken": following[0]} if following else {}),
        }

    def get_paginator(self, name: str) -> Any:
        return _FakePaginator(self)


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        chunk = (
            self._data[self._offset :]
            if size < 0
            else self._data[self._offset : self._offset + size]
        )
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        return None


class _FakePaginator:
    def __init__(self, client: FakeS3) -> None:
        self._client = client

    def paginate(self, **request: Any) -> Any:
        token = None
        while True:
            page = self._client.list_objects_v2(
                **request, **({"ContinuationToken": token} if token else {})
            )
            yield page
            token = page.get("NextContinuationToken")
            if token is None:
                return


@pytest.fixture
def s3() -> tuple[S3ObjectStore, FakeS3]:
    fake = FakeS3()
    return S3ObjectStore("leka-payloads", client=fake), fake


async def test_the_s3_adapter_round_trips(s3: tuple[S3ObjectStore, FakeS3]) -> None:
    store, fake = s3
    payload = bytes(range(256)) * 16

    written = await store.put("ws/src/object.bin", from_bytes(payload), content_type="app/bin")

    assert fake.objects["ws/src/object.bin"] == payload
    assert written.size_bytes == len(payload)
    assert await _drain(store.get("ws/src/object.bin")) == payload
    assert await store.exists("ws/src/object.bin")


async def test_the_s3_adapter_tells_a_missing_key_from_a_real_failure(
    s3: tuple[S3ObjectStore, FakeS3],
) -> None:
    """Confusing the two would turn an outage into silent data loss.

    A missing object is a state callers handle. A permissions problem is not,
    and answering "it is not there" to one would have the retention sweep
    cheerfully delete rows whose bytes it never actually removed.
    """
    store, fake = s3

    assert await store.exists("never-written") is False

    # The same signature as the method it replaces, boto3's capitals and
    # all. A stand-in that takes **kwargs would type-check as a different
    # thing and hide the very mismatch this file exists to catch.
    def refuse(Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        raise FakeS3._Error("AccessDenied", 403)

    fake.head_object = refuse  # type: ignore[method-assign]
    with pytest.raises(ObjectStoreError):
        await store.exists("forbidden")


async def test_the_s3_adapter_purges_more_than_one_page(
    s3: tuple[S3ObjectStore, FakeS3],
) -> None:
    """S3 deletes at most 1000 keys per request and a workspace holds more.

    The stand-in pages every 2 keys, so 5 objects is three pages — which is
    what proves the loop continues rather than stopping at the first.
    """
    store, fake = s3
    workspace = uuid.uuid4()
    for index in range(5):
        await store.put(f"{workspace}/src/{index}", from_bytes(b"x"), content_type="text/plain")
    await store.put("other-workspace/src/0", from_bytes(b"x"), content_type="text/plain")

    removed = await store.delete_prefix(workspace_prefix(workspace))

    assert removed == 5
    assert list(fake.objects) == ["other-workspace/src/0"]


async def test_the_s3_adapter_lists_across_pages(s3: tuple[S3ObjectStore, FakeS3]) -> None:
    store, _ = s3
    for index in range(5):
        await store.put(f"ws/src/{index}", from_bytes(b"x"), content_type="text/plain")

    assert len([key async for key in store.iter_prefix("ws/")]) == 5


async def test_both_adapters_satisfy_the_protocol(store: LocalObjectStore) -> None:
    """The point of the protocol is that business code never asks which one
    it got. If one drifts, that promise is quietly broken."""
    assert isinstance(store, ObjectStore)
    assert isinstance(S3ObjectStore("bucket", client=FakeS3()), ObjectStore)


# ── The row that speaks for the object ───────────────────────────────────────


class Tenant:
    def __init__(self, workspace_id: uuid.UUID, source_id: uuid.UUID) -> None:
        self.workspace_id = workspace_id
        self.source_id = source_id


async def _make_tenant(label: str) -> Tenant:
    marker = f"{label}-{uuid.uuid4().hex[:10]}"
    with system_scope():
        async with session_factory() as session:
            workspace = Workspace(name=label, slug=marker)
            session.add(workspace)
            await session.flush()
            source = Source(workspace_id=workspace.id, kind=SourceKind.GITHUB, name=marker)
            session.add(source)
            await session.flush()
            await session.commit()
            return Tenant(workspace.id, source.id)


async def _remove(tenant: Tenant) -> None:
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM workspaces WHERE id = :wid"), {"wid": tenant.workspace_id}
            )
            await session.commit()


@pytest.fixture
async def tenants() -> AsyncIterator[tuple[Tenant, Tenant]]:
    first, second = await _make_tenant("alpha"), await _make_tenant("beta")
    yield first, second
    await _remove(first)
    await _remove(second)


def _record(repository: RawPayloadRepository, tenant: Tenant, *, key: str) -> RawPayload:
    now = datetime.now(UTC)
    return repository.record(
        source_id=tenant.source_id,
        object_key=key,
        content_type="application/json",
        size_bytes=42,
        checksum_sha256="0" * 64,
        fetched_at=now,
        expires_at=now + timedelta(days=30),
    )


async def test_the_repository_refuses_to_exist_without_a_workspace() -> None:
    """Rule 3: the workspace comes from the principal, never from a request.

    Accepting None and failing later would put the error a long way from the
    call that caused it.
    """
    async with session_factory() as session:
        with pytest.raises(MissingWorkspaceScopeError):
            RawPayloadRepository(session, None)


async def test_the_repository_refuses_a_row_belonging_to_another_workspace(
    tenants: tuple[Tenant, Tenant],
) -> None:
    alpha, beta = tenants
    with system_scope():
        async with session_factory() as session:
            repository = RawPayloadRepository(session, alpha.workspace_id)
            stray = RawPayload(
                workspace_id=beta.workspace_id,
                source_id=beta.source_id,
                object_key="beta/key",
                content_type="application/json",
                size_bytes=1,
                checksum_sha256="0" * 64,
                fetched_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            with pytest.raises(CrossWorkspaceWriteError):
                repository.add(stray)


async def test_one_workspace_cannot_read_another_workspaces_object_key(
    tenants: tuple[Tenant, Tenant],
) -> None:
    """The key is the address of a customer's bytes. Being able to look one
    up across the boundary is the whole breach, with no further step."""
    alpha, beta = tenants
    secret_key = f"{beta.workspace_id}/{beta.source_id}/2026/09/21/{uuid.uuid4()}.json"

    with system_scope():
        async with session_factory() as session:
            _record(RawPayloadRepository(session, beta.workspace_id), beta, key=secret_key)
            await session.commit()

    from leka.db import workspace_scope

    with workspace_scope(alpha.workspace_id):
        async with session_factory() as session:
            found = await RawPayloadRepository(session, alpha.workspace_id).get_by_object_key(
                secret_key
            )

    assert found is None, "a workspace resolved another workspace's object key"


async def test_the_database_refuses_a_payload_pointing_at_another_tenants_source(
    tenants: tuple[Tenant, Tenant],
) -> None:
    """Raw SQL on purpose: this asserts what PostgreSQL enforces through the
    composite foreign key, not what the ORM happens to prevent."""
    from leka.db import engine

    alpha, beta = tenants
    async with engine.begin() as connection:
        with pytest.raises(Exception, match=r"(?i)foreign key|violates"):
            await connection.execute(
                text(
                    "INSERT INTO raw_payloads (workspace_id, source_id, object_key, "
                    "content_type, size_bytes, checksum_sha256, fetched_at, expires_at) "
                    "VALUES (:ws, :src, 'stolen', 'application/json', 1, :sum, now(), now())"
                ),
                {"ws": alpha.workspace_id, "src": beta.source_id, "sum": "0" * 64},
            )


async def test_deleting_a_workspace_takes_its_payload_rows(
    tenants: tuple[Tenant, Tenant],
) -> None:
    """The cascade covers the ROWS. It does not touch the objects — that is
    handled explicitly, and is the subject of the lifecycle work."""
    alpha, beta = tenants
    with system_scope():
        async with session_factory() as session:
            _record(RawPayloadRepository(session, alpha.workspace_id), alpha, key="alpha/one")
            _record(RawPayloadRepository(session, beta.workspace_id), beta, key="beta/one")
            await session.commit()

    await _remove(alpha)

    with system_scope():
        async with session_factory() as session:
            remaining = await session.execute(text("SELECT workspace_id FROM raw_payloads"))
            owners = {str(row[0]) for row in remaining}

    assert str(alpha.workspace_id) not in owners
    assert str(beta.workspace_id) in owners


async def test_a_withdrawn_payload_leaves_every_read(tenants: tuple[Tenant, Tenant]) -> None:
    """Withdrawal takes effect at once, before the slow part — deleting
    bytes — has happened or could fail."""
    alpha, _ = tenants
    with system_scope():
        async with session_factory() as session:
            repository = RawPayloadRepository(session, alpha.workspace_id)
            payload = _record(repository, alpha, key="alpha/withdrawn")
            await session.flush()
            payload_id = payload.id

            assert await repository.get_payload(payload_id) is not None

            repository.mark_deleted(payload)
            await session.flush()

            assert await repository.get_payload(payload_id) is None
            assert len(await repository.list_for_source(alpha.source_id)) == 0
            await session.rollback()
