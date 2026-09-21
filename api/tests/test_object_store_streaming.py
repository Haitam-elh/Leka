"""The object store moves bytes; it does not hold them.

`ObjectStore.put` takes an async iterator and `get` produces one, which reads
like a promise that memory is bounded by the chunk rather than by the object.
Nothing in tests/test_object_storage.py checks that, because every payload
there is a few kilobytes — the round trip is identical whether the adapter
streams or buffers.

So this file uses objects large enough for the difference to show. A Datadog
log export is the realistic case: one connector, one day, hundreds of
megabytes, and a worker that dies with a number nobody can read.

Two kinds of check, because neither alone is enough:

    the ceiling     tracemalloc, on a payload far larger than the bound
    incrementality  deterministic, no measurement: bytes must reach the file
                    before the last chunk is even asked for

The second matters because a memory measurement can pass for the wrong
reason — a garbage collection at the right moment, an allocator returning
pages. Watching when the producer is pulled cannot.
"""

from __future__ import annotations

import asyncio
import tracemalloc
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from leka.platform.storage import CHUNK_SIZE, LocalObjectStore, ObjectTooLargeError

pytestmark = pytest.mark.integration

# Large enough that buffering is unmistakable, small enough that CI does not
# notice. 32 chunks of CHUNK_SIZE.
LARGE_OBJECT_CHUNKS = 32
LARGE_OBJECT_SIZE = LARGE_OBJECT_CHUNKS * CHUNK_SIZE

# What "bounded" is allowed to mean. A few chunks in flight plus whatever
# Python holds around them — not a fraction of the object, which would pass
# on an adapter that buffers half of it.
MEMORY_CEILING = 8 * CHUNK_SIZE


async def _synthetic(chunks: int = LARGE_OBJECT_CHUNKS) -> AsyncIterator[bytes]:
    """Produce chunks one at a time, holding none of them.

    Built on the fly rather than sliced from a prepared payload: a test that
    materialises 32 MB before calling put() measures its own allocation and
    proves nothing about the adapter.
    """
    for index in range(chunks):
        yield bytes((index % 251,)) * CHUNK_SIZE


@pytest.fixture
def store(tmp_path: Path) -> LocalObjectStore:
    return LocalObjectStore(tmp_path)


async def test_writing_a_large_object_does_not_hold_it_in_memory(
    store: LocalObjectStore,
) -> None:
    """The ceiling. 32 MB in, a few MB of peak allocation.

    Before this was fixed, put() drained the whole async iterator into a list
    before writing the first byte, so peak allocation tracked the size of the
    object. A 200 MB log export took 200 MB of RAM and the worker died
    without leaving anything usable behind.
    """
    key = f"large/{uuid.uuid4()}.bin"

    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        written = await store.put(key, _synthetic(), content_type="application/octet-stream")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert written.size_bytes == LARGE_OBJECT_SIZE

    megabyte = 1024 * 1024
    assert peak < MEMORY_CEILING, (
        f"put() peaked at {peak / megabyte:.1f} MB writing a "
        f"{LARGE_OBJECT_SIZE / megabyte:.0f} MB object. The ceiling is "
        f"{MEMORY_CEILING / megabyte:.0f} MB — memory must be bounded by the "
        "chunk, not by the object."
    )


async def test_bytes_reach_the_file_before_the_last_chunk_is_asked_for(
    store: LocalObjectStore, tmp_path: Path
) -> None:
    """Incrementality, without measuring memory.

    A generator that notices when it is pulled. If the adapter streams, the
    consumer has already written most of the object by the time the last
    chunk is requested; if it buffers, the staging file does not exist yet,
    because nothing has been written at all.

    Deterministic rather than timing-dependent: with a bounded queue the
    producer cannot run ahead of the consumer by more than the queue holds,
    so reaching the last chunk means the earlier ones have been taken.
    """
    key = "incremental/object.bin"
    staging = (tmp_path / key).with_suffix(".bin.part")
    written_when_last_chunk_was_asked_for: list[int] = []

    async def watched() -> AsyncIterator[bytes]:
        for index in range(LARGE_OBJECT_CHUNKS):
            if index == LARGE_OBJECT_CHUNKS - 1:
                written_when_last_chunk_was_asked_for.append(
                    staging.stat().st_size if staging.exists() else 0
                )
            yield bytes((index % 251,)) * CHUNK_SIZE

    await store.put(key, watched(), content_type="application/octet-stream")

    assert written_when_last_chunk_was_asked_for, "the generator was never pulled"
    already_written = written_when_last_chunk_was_asked_for[0]
    assert already_written > 0, (
        "nothing had been written to disk when the last chunk was requested — "
        "put() drains the whole iterator before writing, so the object is held "
        "in memory in full"
    )


async def test_reading_a_large_object_does_not_load_it_either(
    store: LocalObjectStore,
) -> None:
    """The same bound on the way back out.

    get() used to read the whole file into a list and then yield from it,
    so a caller streaming a 200 MB payload still paid 200 MB — at the exact
    moment it was trying not to.
    """
    key = f"large/{uuid.uuid4()}.bin"
    await store.put(key, _synthetic(), content_type="application/octet-stream")

    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        # Counted, never accumulated: a test that collected the chunks would
        # measure its own list rather than the adapter.
        total = 0
        async for chunk in store.get(key):
            total += len(chunk)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert total == LARGE_OBJECT_SIZE

    megabyte = 1024 * 1024
    assert peak < MEMORY_CEILING, (
        f"get() peaked at {peak / megabyte:.1f} MB reading a "
        f"{LARGE_OBJECT_SIZE / megabyte:.0f} MB object, against a ceiling of "
        f"{MEMORY_CEILING / megabyte:.0f} MB"
    )


# ── The ceiling ──────────────────────────────────────────────────────────────


@pytest.fixture
def low_ceiling(monkeypatch: pytest.MonkeyPatch) -> int:
    """Lower the maximum object size to something a test can exceed quickly.

    Settings is frozen — the environment is read once, at startup — so a
    copy is the honest way to ask what a different configuration would do.
    """
    from leka.core.config import settings
    from leka.platform import storage

    ceiling = 4 * CHUNK_SIZE
    monkeypatch.setattr(
        storage, "settings", settings.model_copy(update={"max_object_bytes": ceiling})
    )
    return ceiling


async def test_a_payload_over_the_ceiling_is_refused(
    store: LocalObjectStore, low_ceiling: int
) -> None:
    """Streaming bounds our memory. It does not bound the disk or the bill.

    A source answering with forty gigabytes has broken or been asked the
    wrong question, and storing it is the expensive way to find out.
    """
    key = f"too-big/{uuid.uuid4()}.bin"

    with pytest.raises(ObjectTooLargeError, match="LEKA_MAX_OBJECT_BYTES"):
        await store.put(key, _synthetic(), content_type="application/octet-stream")

    assert not await store.exists(key)


async def test_a_refused_payload_leaves_nothing_behind(
    store: LocalObjectStore, low_ceiling: int, tmp_path: Path
) -> None:
    """Not the object, and not the staging file either.

    A half-written .part sitting in the store is counted by nothing and
    cleaned up by nobody: the reconciliation sweep skips it, because it
    only looks at finished objects.
    """
    key = "too-big/leftover.bin"

    with pytest.raises(ObjectTooLargeError):
        await store.put(key, _synthetic(), content_type="application/octet-stream")

    def survivors() -> list[str]:
        return [path.name for path in tmp_path.rglob("*") if path.is_file()]

    leftovers = await asyncio.to_thread(survivors)
    assert leftovers == [], f"the store is not clean after a refusal: {leftovers}"


async def test_a_payload_just_under_the_ceiling_is_accepted(
    store: LocalObjectStore, low_ceiling: int
) -> None:
    """The guard must bite above the limit and nowhere else. A ceiling that
    refuses ordinary payloads gets raised until it protects nothing."""
    key = f"just-under/{uuid.uuid4()}.bin"

    written = await store.put(
        key, _synthetic(chunks=low_ceiling // CHUNK_SIZE), content_type="application/octet-stream"
    )

    assert written.size_bytes == low_ceiling
    assert await store.exists(key)
