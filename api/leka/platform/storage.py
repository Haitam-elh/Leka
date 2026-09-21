"""Object storage: where raw payloads live, which is not PostgreSQL.

A GitHub API response, a Datadog log export, a raw Confluence page. These are
the largest volume LEKA handles and the shortest-lived. Putting them in a
relational database swells every backup, lengthens every restore, and makes
retention expensive — you pay to keep, and you pay again to delete. So a row
in `raw_payloads` carries the metadata and a key; the bytes live here.

One protocol, two implementations, chosen by configuration and never by an
`if` in business code. This is the shape leka.platform.secrets and
leka.identity.email already use, and it earns the same thing it earned for
LEKA-330: the default implementation needs no account anywhere, so the whole
platform is testable on a laptop and in CI with nothing to set up.

    LocalObjectStore  writes under a directory. The default.
    S3ObjectStore     anything speaking S3 — Cloudflare R2 today, Amazon S3
                      in phase 3, without changing a line here.

THE BYTES ARE STREAMED, NEVER HELD. `put` consumes an async iterator and
`get` produces one. A connector exporting a day of logs will hand this a
200 MB body one day, and an adapter that materialised it as a single bytes
object would take the process down with it. The checksum is computed while
the bytes go past, so nothing is ever read twice.

See docs/adr/010-object-storage.md.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog

from leka.core.config import settings

logger = structlog.get_logger(__name__)

# How much is moved at a time. Large enough that a big object is not a million
# syscalls, small enough that several concurrent uploads do not add up to
# something the container's memory limit notices.
CHUNK_SIZE = 1024 * 1024


class ObjectStoreError(RuntimeError):
    """The object store could not do what was asked.

    Deliberately not swallowed the way a failed email is. An email that does
    not arrive can be asked for again; a payload we believe we stored and did
    not is a row pointing at nothing, and every later read of it is a bug
    with no obvious cause.
    """


class ObjectNotFoundError(ObjectStoreError):
    """No object under that key. Usually a row outliving its bytes."""


@dataclass(frozen=True)
class StoredObject:
    """What the store observed while writing, not what a caller claimed.

    size_bytes and checksum_sha256 are measured as the bytes go past. A
    caller cannot pass a length and a hash it worked out itself — which is
    the point: these two fields are what later proves the object was not
    truncated or silently corrupted.
    """

    key: str
    size_bytes: int
    checksum_sha256: str
    content_type: str


@runtime_checkable
class ObjectStore(Protocol):
    """Everything LEKA needs from an object store, and nothing more.

    Six methods. `iter_prefix` is not decoration: reconciling orphaned
    objects — the ones no row speaks for any more — means walking the store,
    and without it that sweep cannot exist at all.
    """

    async def put(
        self, key: str, chunks: AsyncIterator[bytes], *, content_type: str
    ) -> StoredObject:
        """Write an object, measuring it on the way through."""
        ...

    def get(self, key: str) -> AsyncIterator[bytes]:
        """Read an object back, in chunks. Raises ObjectNotFoundError."""
        ...

    async def delete(self, key: str) -> bool:
        """Remove one object. False if it was already gone."""
        ...

    async def delete_prefix(self, prefix: str) -> int:
        """Remove everything under a prefix. Returns how many went."""
        ...

    async def exists(self, key: str) -> bool:
        """Whether the bytes are actually there."""
        ...

    def iter_prefix(self, prefix: str) -> AsyncIterator[str]:
        """Every key under a prefix."""
        ...


# ── Keys ─────────────────────────────────────────────────────────────────────


def object_key(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    fetched_at: datetime,
    *,
    extension: str = "json",
) -> str:
    """Build a key: {workspace}/{source}/{yyyy}/{mm}/{dd}/{uuid}.{ext}

    The workspace first, and that is not tidiness. It makes erasing one
    customer a single prefix delete rather than a walk of the whole store,
    and it makes a cross-tenant leak visible to the naked eye — a key that
    starts with the wrong workspace is wrong at a glance, in a log line, in
    a bug report, without a query.

    The date next, because retention sweeps and manual archaeology both move
    through time.

    A fresh uuid last, never a name derived from the content and never a
    counter. A predictable key is an enumerable key: anyone who could guess
    one could guess the next. A content hash would be worse still — the same
    payload in two workspaces would produce the same key, which turns the
    store into a way of asking "does that customer have this file too?".
    """
    # UTC, always. The key must not depend on the timezone of whichever
    # machine wrote it, or the same payload lands in a different day's
    # prefix depending on where the worker runs.
    stamp = (
        fetched_at.replace(tzinfo=UTC) if fetched_at.tzinfo is None else fetched_at.astimezone(UTC)
    )
    return (
        f"{workspace_id}/{source_id}/"
        f"{stamp.year:04d}/{stamp.month:02d}/{stamp.day:02d}/"
        f"{uuid.uuid4()}.{extension.lstrip('.')}"
    )


def workspace_prefix(workspace_id: uuid.UUID) -> str:
    """Everything belonging to one customer, addressable in one string.

    This is what a deletion purges and what a leak would betray.
    """
    return f"{workspace_id}/"


async def from_bytes(payload: bytes) -> AsyncIterator[bytes]:
    """Adapt a small in-memory payload to the streaming interface.

    For tests and for genuinely small bodies. Anything that might be large
    should hand `put` a real stream rather than come through here.
    """
    yield payload


# ── Local ────────────────────────────────────────────────────────────────────


class LocalObjectStore:
    """Writes under a directory. The default everywhere but production.

    What ConsoleEmailSender was for LEKA-330: the implementation that makes
    every flow above it runnable with no account, no credentials and no
    network — on a laptop, in CI, and in a test that must not depend on the
    weather in us-east-1.

    Not durable, and the configuration refuses to let it near production: on
    a container the filesystem is ephemeral, so a redeploy would take every
    payload with it and leave the rows pointing at nothing.

    The filesystem calls are synchronous, so they run in a worker thread —
    the same reason SmtpEmailSender runs smtplib there. A slow disk must not
    stall every other request this process is serving.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        """Resolve a key to a path, refusing anything that escapes the root.

        A key is built by this module, so `..` should be impossible. Should
        be: this is the one place where being wrong writes to an arbitrary
        location on the filesystem, so it is checked rather than trusted.
        """
        candidate = (self._root / key).resolve()
        root = self._root.resolve()
        if not candidate.is_relative_to(root):
            msg = f"object key {key!r} escapes the store root"
            raise ObjectStoreError(msg)
        return candidate

    def _put_blocking(self, path: Path, chunks: list[bytes]) -> tuple[int, str]:
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        # A temporary file, renamed once complete. A crash halfway through
        # leaves a .part behind rather than a truncated object that looks
        # whole — and rename is atomic on every filesystem we care about.
        staging = path.with_suffix(path.suffix + ".part")
        with staging.open("wb") as handle:
            for chunk in chunks:
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        staging.replace(path)
        return size, digest.hexdigest()

    async def put(
        self, key: str, chunks: AsyncIterator[bytes], *, content_type: str
    ) -> StoredObject:
        path = self._path(key)
        # Consumed here rather than inside the thread: the iterator is async,
        # and a worker thread has no event loop to drive it. Chunks are
        # handed over one CHUNK_SIZE at a time, so this is not the whole
        # object in memory unless the caller made it so.
        buffered: list[bytes] = [chunk async for chunk in chunks]
        size, checksum = await asyncio.to_thread(self._put_blocking, path, buffered)
        return StoredObject(
            key=key, size_bytes=size, checksum_sha256=checksum, content_type=content_type
        )

    async def get(self, key: str) -> AsyncIterator[bytes]:
        path = self._path(key)
        if not await asyncio.to_thread(path.is_file):
            raise ObjectNotFoundError(key)

        def read_all() -> list[bytes]:
            with path.open("rb") as handle:
                return list(iter(lambda: handle.read(CHUNK_SIZE), b""))

        for chunk in await asyncio.to_thread(read_all):
            yield chunk

    async def delete(self, key: str) -> bool:
        path = self._path(key)

        def remove() -> bool:
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            return True

        return await asyncio.to_thread(remove)

    async def delete_prefix(self, prefix: str) -> int:
        directory = self._path(prefix.rstrip("/"))

        def remove_tree() -> int:
            if not directory.is_dir():
                return 0
            removed = sum(1 for path in directory.rglob("*") if path.is_file())
            shutil.rmtree(directory)
            return removed

        return await asyncio.to_thread(remove_tree)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def iter_prefix(self, prefix: str) -> AsyncIterator[str]:
        root = self._root.resolve()
        directory = self._path(prefix.rstrip("/"))

        def walk() -> list[str]:
            if not directory.is_dir():
                return []
            return sorted(
                str(path.resolve().relative_to(root))
                for path in directory.rglob("*")
                if path.is_file() and path.suffix != ".part"
            )

        for key in await asyncio.to_thread(walk):
            yield key


# ── S3-compatible ────────────────────────────────────────────────────────────


class _ChunkReader:
    """A file-like view over an async iterator, for boto3's upload_fileobj.

    boto3 wants something with `read(n)`. The chunks arrive asynchronously
    and boto3 pulls synchronously from another thread, so they are drained
    into a list first and handed over as a stream. That keeps the whole
    adapter honest about one thing: boto3 never receives a single bytes
    object it has to hold, it receives something it reads a piece at a time.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks: Iterator[bytes] = iter(chunks)
        self._buffer = bytearray()
        self._done = False

    def read(self, size: int = -1) -> bytes:
        while not self._done and (size < 0 or len(self._buffer) < size):
            try:
                self._buffer.extend(next(self._chunks))
            except StopIteration:
                self._done = True
        if size < 0 or size >= len(self._buffer):
            out, self._buffer = bytes(self._buffer), bytearray()
            return out
        out = bytes(self._buffer[:size])
        del self._buffer[:size]
        return out


class S3ObjectStore:
    """Anything that speaks S3. Cloudflare R2 now, Amazon S3 later.

    Same protocol, same call sites, one endpoint in configuration between
    them — which is the whole reason for writing this against S3's API rather
    than R2's own.

    boto3 is synchronous and every call blocks, so each one runs in a worker
    thread. That is not a workaround: it is the same decision SmtpEmailSender
    made for smtplib, and it avoids adding an async S3 client to the
    dependency list for calls the background loop makes a handful of times
    per sync.

    The bucket is never public. Nothing here grants anonymous access, sets an
    ACL or writes a bucket policy — reaching a payload goes through the
    application, which knows which workspace is asking.
    """

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        region: str = "auto",
        access_key_id: str = "",
        secret_access_key: str = "",
        client: Any | None = None,
    ) -> None:
        """Build a client, or take one.

        `client` exists so this adapter can be exercised against a stand-in
        rather than only against a real bucket. That is not a testing
        convenience bolted on: the logic worth checking here — telling "no
        such key" from a permissions failure, paginating a delete over more
        than a thousand keys — is exactly the logic that never runs in a
        test that needs credentials, and so never runs at all.
        """
        self._bucket = bucket
        if client is not None:
            self._client = client
            return

        import boto3

        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def _is_missing(self, error: Exception) -> bool:
        """Tell "no such key" from every other failure.

        They must not be confused. A missing object is an expected state a
        caller handles; a permissions problem or a network failure is not,
        and returning False for it would turn an outage into silent data
        loss.
        """
        response = getattr(error, "response", None)
        if not isinstance(response, dict):
            return False
        code = str(response.get("Error", {}).get("Code", ""))
        status = int(response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
        return code in {"404", "NoSuchKey", "NotFound"} or status == 404

    async def put(
        self, key: str, chunks: AsyncIterator[bytes], *, content_type: str
    ) -> StoredObject:
        buffered: list[bytes] = [chunk async for chunk in chunks]
        digest = hashlib.sha256()
        size = 0
        for chunk in buffered:
            digest.update(chunk)
            size += len(chunk)

        def upload() -> None:
            self._client.upload_fileobj(
                _ChunkReader(buffered),
                self._bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )

        try:
            await asyncio.to_thread(upload)
        except Exception as error:
            msg = f"could not write object {key!r}"
            raise ObjectStoreError(msg) from error

        return StoredObject(
            key=key,
            size_bytes=size,
            checksum_sha256=digest.hexdigest(),
            content_type=content_type,
        )

    async def get(self, key: str) -> AsyncIterator[bytes]:
        def open_body() -> object:
            try:
                response = self._client.get_object(Bucket=self._bucket, Key=key)
            except Exception as error:
                if self._is_missing(error):
                    raise ObjectNotFoundError(key) from error
                msg = f"could not read object {key!r}"
                raise ObjectStoreError(msg) from error
            return response["Body"]

        body = await asyncio.to_thread(open_body)
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, CHUNK_SIZE)  # type: ignore[attr-defined]
                if not chunk:
                    return
                yield chunk
        finally:
            await asyncio.to_thread(body.close)  # type: ignore[attr-defined]

    async def delete(self, key: str) -> bool:
        existed = await self.exists(key)

        def remove() -> None:
            self._client.delete_object(Bucket=self._bucket, Key=key)

        await asyncio.to_thread(remove)
        return existed

    async def delete_prefix(self, prefix: str) -> int:
        """Delete everything under a prefix, a page at a time.

        S3 deletes at most 1000 keys per request, and a workspace can hold
        far more than that. Listing and deleting page by page keeps this
        bounded in memory however much is there.
        """

        def remove_all() -> int:
            paginator = self._client.get_paginator("list_objects_v2")
            removed = 0
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if not keys:
                    continue
                self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": keys})
                removed += len(keys)
            return removed

        try:
            return await asyncio.to_thread(remove_all)
        except Exception as error:
            msg = f"could not purge prefix {prefix!r}"
            raise ObjectStoreError(msg) from error

    async def exists(self, key: str) -> bool:
        def head() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
            except Exception as error:
                if self._is_missing(error):
                    return False
                msg = f"could not stat object {key!r}"
                raise ObjectStoreError(msg) from error
            return True

        return await asyncio.to_thread(head)

    async def iter_prefix(self, prefix: str) -> AsyncIterator[str]:
        def next_page(token: str | None) -> tuple[list[str], str | None]:
            request: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
            if token is not None:
                request["ContinuationToken"] = token
            response = self._client.list_objects_v2(**request)
            keys = [str(item["Key"]) for item in response.get("Contents", [])]
            return keys, response.get("NextContinuationToken")

        token: str | None = None
        while True:
            keys, token = await asyncio.to_thread(next_page, token)
            for key in keys:
                yield key
            if token is None:
                return


# ── Choosing one ─────────────────────────────────────────────────────────────


def build_object_store() -> ObjectStore:
    """Pick an implementation from configuration, once, at startup.

    The same shape as build_email_sender. Business code never asks which one
    it got.
    """
    if settings.object_store == "s3":
        if settings.s3_bucket is None or settings.s3_secret_access_key is None:
            msg = "LEKA_OBJECT_STORE=s3 but LEKA_S3_BUCKET or LEKA_S3_SECRET_ACCESS_KEY is not set."
            raise ObjectStoreError(msg)
        return S3ObjectStore(
            settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key_id=settings.s3_access_key_id or "",
            secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        )
    return LocalObjectStore(settings.object_store_root)


class _Unset:
    """Sentinel: no store has been built for this process yet."""


_store: ObjectStore | _Unset = _Unset()


def object_store() -> ObjectStore:
    """The store this process uses, built on first use.

    Not at import, unlike secret_box. A malformed Fernet key must stop the
    process on startup because nothing works without it; an object store is
    only needed by the parts of the system that handle payloads, and building
    a boto3 client at import would make every test and every migration open a
    connection they never use.
    """
    global _store
    if isinstance(_store, _Unset):
        _store = build_object_store()
        logger.info("object_store_ready", kind=type(_store).__name__)
    return _store


def reset_object_store() -> None:
    """Forget the built store. For tests that change the configuration."""
    global _store
    _store = _Unset()


__all__ = [
    "CHUNK_SIZE",
    "LocalObjectStore",
    "ObjectNotFoundError",
    "ObjectStore",
    "ObjectStoreError",
    "S3ObjectStore",
    "StoredObject",
    "build_object_store",
    "from_bytes",
    "object_key",
    "object_store",
    "reset_object_store",
    "workspace_prefix",
]
