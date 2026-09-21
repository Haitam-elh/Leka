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
import queue
import shutil
import threading
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
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

# How many chunks may sit between the event loop and the worker thread.
#
# This number is the memory bound. Everything that moves bytes through this
# module holds at most STREAM_QUEUE_CHUNKS + 2 chunks at once — the queue,
# the one being produced, and the one being consumed — whatever the size of
# the object. Four is enough to keep a disk or a socket busy without the
# producer waiting; raising it buys throughput and costs exactly
# CHUNK_SIZE per unit.
STREAM_QUEUE_CHUNKS = 4

# What boto3 is allowed to hold for a multipart upload.
#
# Its defaults are ten parts of 8 MiB in flight — eighty megabytes of buffers
# per upload. On a worker running several syncs at once that is the problem
# this module exists to avoid, moved one layer down. S3 refuses parts below
# 5 MiB, so 8 MiB is the smallest sensible part.
#
# ONE PART AT A TIME, and that number was measured rather than reasoned
# about. Uploading 16 MB and then 64 MB to MinIO, peak allocation:
#
#     max_concurrency=2   26.2 MB -> 36.1 MB     (+9.9 MB)
#     max_concurrency=1   26.1 MB -> 27.1 MB     (+1.0 MB)
#
# Quadrupling the payload costs one megabyte with a single part in flight and
# ten with two. Concurrency is the lever here; max_in_memory_upload_chunks,
# which the documentation points at for non-seekable streams, made no
# measurable difference on its own and is set to match anyway.
#
# The cost is throughput: parts go up one after another instead of two at a
# time. That is the right trade for a background worker, where a sync taking
# slightly longer is invisible and a worker dying of memory is not.
S3_PART_BYTES = 8 * 1024 * 1024
S3_CONCURRENT_PARTS = 1


class ObjectStoreError(RuntimeError):
    """The object store could not do what was asked.

    Deliberately not swallowed the way a failed email is. An email that does
    not arrive can be asked for again; a payload we believe we stored and did
    not is a row pointing at nothing, and every later read of it is a bug
    with no obvious cause.
    """


class ObjectNotFoundError(ObjectStoreError):
    """No object under that key. Usually a row outliving its bytes."""


class ObjectTooLargeError(ObjectStoreError):
    """A payload went past the configured ceiling and was refused.

    Streaming bounds our memory, not our disk and not our bill. A source
    that answers with forty gigabytes has either broken or been asked the
    wrong question, and storing it would be the expensive way to find out.
    Refused loudly, mid-flight, with nothing left behind.
    """


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

    @staticmethod
    def _staging(path: Path) -> Path:
        """Where a write goes before it is complete.

        A temporary file, renamed once whole. A crash halfway leaves a .part
        behind rather than a truncated object that reads as complete — and
        rename is atomic on every filesystem we care about.
        """
        return path.with_suffix(path.suffix + ".part")

    def _write_blocking(self, path: Path, stream: _BoundedStream) -> None:
        """Consume the stream onto disk, one chunk at a time.

        Runs in a worker thread. It pulls from the bounded queue rather than
        from a list, so what it holds is one chunk, however large the object
        is.

        A failure — the producer raising, the disk filling, the ceiling
        being passed — removes the staging file on the way out. Leaving it
        would mean a half-written payload sitting in the store, counted by
        nothing and cleaned up by nobody.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = self._staging(path)
        try:
            with staging.open("wb") as handle:
                for chunk in stream.chunks():
                    handle.write(chunk)
            staging.replace(path)
        except BaseException:
            staging.unlink(missing_ok=True)
            raise

    async def put(
        self, key: str, chunks: AsyncIterator[bytes], *, content_type: str
    ) -> StoredObject:
        """Write an object, holding at most a few chunks of it.

        The async iterator cannot be pulled from a worker thread, and the
        filesystem calls cannot run on the event loop. _BoundedStream is the
        bridge: the loop feeds a queue of STREAM_QUEUE_CHUNKS while the
        thread drains it, so memory is bounded by the queue and not by the
        payload. See _BoundedStream for the bound and what it does not cover.
        """
        path = self._path(key)
        stream = _BoundedStream(limit_bytes=settings.max_object_bytes)
        await _stream_through(stream, chunks, lambda s: self._write_blocking(path, s))
        return StoredObject(
            key=key,
            size_bytes=stream.size,
            checksum_sha256=stream.checksum(),
            content_type=content_type,
        )

    async def get(self, key: str) -> AsyncIterator[bytes]:
        """Read an object back, a chunk at a time.

        Each read happens in a worker thread and is yielded before the next
        one is asked for, so a large object is never materialised here. The
        caller decides how much of it to keep.
        """
        path = self._path(key)
        if not await asyncio.to_thread(path.is_file):
            raise ObjectNotFoundError(key)

        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(handle.read, CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

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


class _Failed:
    """Carries the producer's exception across to the consumer thread."""

    def __init__(self, error: BaseException) -> None:
        self.error = error


class _End:
    """Marks the end of the stream."""


class _BoundedStream:
    """A bounded pipe from an async producer to a synchronous consumer.

    THE PROBLEM THIS SOLVES. A payload arrives as an async iterator, and the
    things that write it — the filesystem, boto3 — are synchronous and run
    in a worker thread. A thread has no event loop, so it cannot pull from
    an async iterator. The obvious bridge is to drain the iterator into a
    list and hand the list over. That is what this module used to do, and it
    meant a 200 MB export occupied 200 MB of RAM: CHUNK_SIZE bounded the
    size of each element, never the length of the list.

    WHAT IT DOES INSTEAD. A `queue.Queue` holding STREAM_QUEUE_CHUNKS items.
    The event loop pushes chunks into it — from a worker thread, so a full
    queue never blocks the loop — and the consumer pulls them out. A full
    queue makes the producer wait, and that backpressure is what makes the
    bound real: at most STREAM_QUEUE_CHUNKS + 2 chunks exist at once,
    whatever the size of the object.

    That is a bound on what THIS module accumulates, and nothing more. boto3
    keeps its own buffers for a multipart upload and the operating system
    caches writes; neither is ours to promise. The guarantee is that LEKA
    does not hold the object.

    EXCEPTIONS TRAVEL BOTH WAYS, which is most of the code below. A producer
    that raises must not leave the consumer waiting for a chunk that will
    never arrive, and a consumer that dies must not leave the producer
    blocked on a queue nobody will drain. Either freezes a worker with no
    message at all, which is the failure that costs an afternoon before
    anyone knows where to look.

    The size and the SHA-256 are computed as the chunks go past, in one
    pass, on the producer side. Nothing is revisited, because there is no
    list left to revisit.
    """

    # How long the consumer's blocking get waits before checking whether the
    # producer is still there. It runs in a worker thread, so waiting costs
    # nothing but the thread it already holds.
    POLL_SECONDS = 0.05

    # How long the producer waits, on the event loop, when the queue is full.
    # Shorter, because this one is latency on every chunk of every upload.
    PRODUCER_POLL_SECONDS = 0.005

    def __init__(self, *, limit_bytes: int) -> None:
        self._queue: queue.Queue[bytes | _Failed | _End] = queue.Queue(maxsize=STREAM_QUEUE_CHUNKS)
        self._abandoned = threading.Event()
        self._buffer = bytearray()
        self._exhausted = False
        self._limit_bytes = limit_bytes
        self._digest = hashlib.sha256()
        self.size = 0

    # ── Producer side: the event loop ────────────────────────────────────

    async def feed(self, chunks: AsyncIterator[bytes]) -> None:
        """Push an async iterator into the queue, measuring as it passes.

        Never raises. A failure goes onto the queue instead and surfaces
        when the consumer reads it, so an error reaches the caller by
        exactly one path rather than by two that can race.
        """
        try:
            async for chunk in chunks:
                self.size += len(chunk)
                if self.size > self._limit_bytes:
                    megabyte = 1024 * 1024
                    msg = (
                        f"payload exceeds the configured ceiling of "
                        f"{self._limit_bytes / megabyte:.0f} MB "
                        "(LEKA_MAX_OBJECT_BYTES). Nothing was stored."
                    )
                    raise ObjectTooLargeError(msg)
                self._digest.update(chunk)
                if not await self._offer(chunk):
                    return
        except BaseException as error:
            await self._offer(_Failed(error))
        finally:
            await self._offer(_End())

    async def _offer(self, item: bytes | _Failed | _End) -> bool:
        """Put one item, or give up because the consumer has gone.

        NEVER FROM A WORKER THREAD, and that is not a stylistic choice. The
        consumer already occupies one thread of the default executor for as
        long as the transfer lasts. If the producer took another, then N
        concurrent uploads would take 2N threads from a pool that has about
        thirty — and past that point every running consumer would be waiting
        for a chunk from a producer queued behind it for a thread that is
        never released. The whole pool deadlocks, silently.

        So this waits on the event loop instead: a non-blocking put, and
        `await asyncio.sleep` when the queue is full. The loop stays free,
        the backpressure still happens, and no thread is involved.

        Returns False once the consumer has abandoned the stream, which is
        what stops a producer pushing an entire object into a queue nobody
        will ever read again.
        """
        while not self._abandoned.is_set():
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                await asyncio.sleep(self.PRODUCER_POLL_SECONDS)
                continue
            return True
        return False

    # ── Consumer side: the worker thread ─────────────────────────────────

    def abandon(self) -> None:
        """Say that nobody will read from this stream again.

        Called from the consumer's `finally`, on success and on failure.
        Without it a consumer that raised would leave the producer waiting
        on a queue that never drains.
        """
        self._abandoned.set()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _take(self) -> bytes | None:
        """The next chunk, or None at the end. Raises what the producer did."""
        while True:
            try:
                item = self._queue.get(timeout=self.POLL_SECONDS)
            except queue.Empty:
                continue
            if isinstance(item, _End):
                self._exhausted = True
                return None
            if isinstance(item, _Failed):
                self._exhausted = True
                raise item.error
            return item

    def chunks(self) -> Iterator[bytes]:
        """Iterate the payload, for a consumer that writes chunk by chunk."""
        while True:
            chunk = self._take()
            if chunk is None:
                return
            yield chunk

    def read(self, size: int = -1) -> bytes:
        """A file-like read, for boto3's upload_fileobj.

        boto3 asks for a specific number of bytes and expects them, so a
        chunk that overshoots is held over to the next call. That remainder
        is smaller than one chunk and is the only thing this object keeps
        between calls.

        A negative size means "everything". boto3 does not use it for an
        upload, and it is the one call here that is NOT bounded — asking for
        everything is asking for the object in memory. That is a limit of
        this method, not a property of the stream.
        """
        while not self._exhausted and (size < 0 or len(self._buffer) < size):
            chunk = self._take()
            if chunk is None:
                break
            self._buffer.extend(chunk)

        if size < 0 or size >= len(self._buffer):
            out, self._buffer = bytes(self._buffer), bytearray()
            return out
        out = bytes(self._buffer[:size])
        del self._buffer[:size]
        return out

    def checksum(self) -> str:
        """The SHA-256 of everything that went past."""
        return self._digest.hexdigest()


async def _stream_through(
    stream: _BoundedStream,
    chunks: AsyncIterator[bytes],
    consume: Callable[[_BoundedStream], None],
) -> None:
    """Run a synchronous consumer in a thread while feeding it from the loop.

    Both run at once, which is the whole point: the consumer writes chunks
    the producer has already handed over while the producer fetches the
    next. Sequencing them would mean buffering everything in between, which
    is the bug this exists to prevent.

    The consumer's exception is the one that comes out. A producer failure
    reaches the consumer through the queue and is re-raised there, so
    whatever surfaces here is the error that actually stopped the transfer.
    """

    def run() -> None:
        try:
            consume(stream)
        finally:
            stream.abandon()

    consumer = asyncio.create_task(asyncio.to_thread(run))
    await stream.feed(chunks)
    await consumer


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
        """Upload an object, holding at most a few chunks of it.

        upload_fileobj reads from a file-like object and handles multipart
        itself — it will do that work properly only if it is given something
        that actually streams. It used to be handed a reader over a list
        containing the whole payload, which took that work away and made the
        object resident regardless. _BoundedStream gives it a real stream.

        boto3 keeps buffers of its own, and those are bounded here too —
        see S3_PART_BYTES for the measurements. What comes out of it is that
        the footprint of an upload is a constant rather than a fraction of
        the payload: quadrupling the object moves peak allocation by about a
        megabyte.
        """
        from boto3.s3.transfer import TransferConfig

        stream = _BoundedStream(limit_bytes=settings.max_object_bytes)
        transfer = TransferConfig(
            multipart_threshold=S3_PART_BYTES,
            multipart_chunksize=S3_PART_BYTES,
            max_concurrency=S3_CONCURRENT_PARTS,
        )
        # Set after construction, not passed in: boto3's TransferConfig does
        # not accept this one as a keyword, although it inherits it from
        # s3transfer and honours it. It is the setting that actually bounds a
        # non-seekable stream — see the note above S3_PART_BYTES.
        transfer.max_in_memory_upload_chunks = S3_CONCURRENT_PARTS

        def upload(source: _BoundedStream) -> None:
            self._client.upload_fileobj(
                source,
                self._bucket,
                key,
                ExtraArgs={"ContentType": content_type},
                Config=transfer,
            )

        try:
            await _stream_through(stream, chunks, upload)
        except ObjectStoreError:
            # Already one of ours — a ceiling breach, most likely. Wrapping
            # it again would bury the reason.
            raise
        except Exception as error:
            msg = f"could not write object {key!r}"
            raise ObjectStoreError(msg) from error

        return StoredObject(
            key=key,
            size_bytes=stream.size,
            checksum_sha256=stream.checksum(),
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
