"""Files attached to an intention: the paperclip of the home's bar and of
the full step.

A file is uploaded on its own, before the intention is asked: its bytes go
to object storage, what the store measured of them is kept here, and its id
comes back. Asked, the intention carries those ids and is linked to them —
in the same transaction: an intention that cannot be kept keeps nothing.
Nothing is said attached that was not kept.

What is accepted is what LEKA can read — text, CSV, Markdown, JSON, PDF,
PNG, JPEG — judged by what the bytes are, not only by what the browser
says: a PDF begins as one, an image as one, a text is UTF-8. Ten megabytes
each at most, five to an intention. A file nobody asked with is removed
within a day (purge, hourly): uploaded, then abandoned, it is nobody's.

Who may: who may ask (`intention:create`) uploads, and removes their own
before asking; who may read the intention (`intention:read`) reads its
files — and the analysis, the agents, through `of_intention` and `read`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select

from leka.db import WorkspaceScopedRepository, session_factory, system_scope
from leka.intentions.models import IntentionAttachment
from leka.platform.storage import ObjectNotFoundError, ObjectStoreError, object_store

logger = structlog.get_logger(__name__)

# What LEKA reads, and the extension its key gets.
ACCEPTED: dict[str, str] = {
    "text/plain": "txt",
    "text/csv": "csv",
    "text/markdown": "md",
    "application/json": "json",
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
}
MAX_BYTES = 10 * 1024 * 1024
MAX_FILES = 5
NAME = 255
# How much of the beginning is read to say what a file is.
HEAD = 1024
# Uploaded and never asked with: nobody's, after this.
UNLINKED_FOR = timedelta(hours=24)


class AttachmentRefusedError(ValueError):
    """Not kept, and why — the code the screen says in words:

    file_type_refused       not something LEKA reads
    file_content_mismatch   its bytes are not what its type says
    file_too_large          above MAX_BYTES
    file_empty              nothing in it
    file_name_missing       no name to keep it under
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AttachmentUnknownError(ValueError):
    """An id asked with that is not a file this person uploaded here and has
    not attached elsewhere: the intention is refused, nothing kept."""


def accepted(content_type: str) -> str | None:
    """The media type as LEKA keeps it — its parameters dropped — when it
    is one LEKA reads."""
    media = content_type.split(";", 1)[0].strip().lower()
    return media if media in ACCEPTED else None


def looks_like(content_type: str, head: bytes) -> bool:
    """Whether a file's first bytes are what its type says."""
    if content_type == "application/pdf":
        return head.startswith(b"%PDF-")
    if content_type == "image/png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return head.startswith(b"\xff\xd8\xff")
    # A text: UTF-8, no NUL. A character cut at the end of what was read is
    # not a refusal.
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as error:
        return error.start >= len(head) - 3 and len(head) >= HEAD
    return True


async def checked(chunks: AsyncIterator[bytes], content_type: str) -> AsyncIterator[bytes]:
    """The body as it comes, refused mid-way when it is not what it says or
    grows past MAX_BYTES: the store then keeps nothing."""
    head = bytearray()
    judged = False
    size = 0
    async for chunk in chunks:
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_BYTES:
            raise AttachmentRefusedError("file_too_large")
        if judged:
            yield chunk
            continue
        head.extend(chunk)
        if len(head) >= HEAD:
            if not looks_like(content_type, bytes(head[:HEAD])):
                raise AttachmentRefusedError("file_content_mismatch")
            judged = True
            yield bytes(head)
    if not judged:
        if not head:
            raise AttachmentRefusedError("file_empty")
        if not looks_like(content_type, bytes(head)):
            raise AttachmentRefusedError("file_content_mismatch")
        yield bytes(head)


def attachment_key(workspace_id: uuid.UUID, at: datetime, extension: str) -> str:
    """{workspace}/intention-attachments/{yyyy}/{mm}/{dd}/{uuid}.{ext} — the
    workspace first: erased with it, and a leak visible at a glance."""
    stamp = at.astimezone(UTC)
    return (
        f"{workspace_id}/intention-attachments/"
        f"{stamp.year:04d}/{stamp.month:02d}/{stamp.day:02d}/{uuid.uuid4()}.{extension}"
    )


def tidy_name(name: str) -> str:
    """The file's name as kept: no path, no control character, not too long."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(c for c in base if c.isprintable()).strip()
    if len(cleaned) > NAME:
        stem, dot, extension = cleaned.rpartition(".")
        cleaned = f"{stem[: NAME - len(extension) - 1]}.{extension}" if dot else cleaned[:NAME]
    return cleaned


class AttachmentRepository(WorkspaceScopedRepository):
    """Rows in `intention_attachments`, for one workspace."""

    async def mine_unlinked(
        self, ids: Sequence[uuid.UUID], *, by: uuid.UUID | None
    ) -> list[IntentionAttachment]:
        rows = await self._session.scalars(
            self.select(IntentionAttachment).where(
                IntentionAttachment.id.in_(list(ids)),
                IntentionAttachment.uploaded_by == by,
            )
        )
        return list(rows.all())

    async def one(self, attachment_id: uuid.UUID) -> IntentionAttachment | None:
        rows = await self._session.scalars(
            self.select(IntentionAttachment).where(IntentionAttachment.id == attachment_id)
        )
        return rows.first()

    async def of_intention(self, intention_id: uuid.UUID) -> list[IntentionAttachment]:
        rows = await self._session.scalars(
            self.select(IntentionAttachment)
            .where(IntentionAttachment.intention_id == intention_id)
            .order_by(IntentionAttachment.created_at, IntentionAttachment.id)
        )
        return list(rows.all())

    async def remove(self, row: IntentionAttachment) -> None:
        await self._session.delete(row)


async def keep(
    repository: AttachmentRepository,
    *,
    by: uuid.UUID | None,
    name: str,
    content_type: str,
    chunks: AsyncIterator[bytes],
    now: datetime | None = None,
) -> IntentionAttachment:
    """A file uploaded: checked, stored, kept — or refused, nothing left."""
    media = accepted(content_type)
    if media is None:
        raise AttachmentRefusedError("file_type_refused")
    kept_as = tidy_name(name)
    if not kept_as:
        raise AttachmentRefusedError("file_name_missing")
    at = now or datetime.now(UTC)
    stored = await object_store().put(
        attachment_key(repository.workspace_id, at, ACCEPTED[media]),
        checked(chunks, media),
        content_type=media,
    )
    row = IntentionAttachment(
        workspace_id=repository.workspace_id,
        id=uuid.uuid4(),
        created_at=at,
        updated_at=at,
        uploaded_by=by,
        name=kept_as,
        content_type=media,
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.checksum_sha256,
        storage_key=stored.key,
    )
    repository.add(row)
    return row


async def link(
    repository: AttachmentRepository,
    intention_id: uuid.UUID,
    ids: Sequence[uuid.UUID],
    *,
    by: uuid.UUID | None,
) -> list[IntentionAttachment]:
    """The files an intention was asked with, linked to it. Each must be one
    this person uploaded here, not attached to another intention — else
    AttachmentUnknownError, and the intention is not kept."""
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return []
    if len(wanted) > MAX_FILES:
        raise AttachmentUnknownError
    rows = await repository.mine_unlinked(wanted, by=by)
    usable = [r for r in rows if r.intention_id in (None, intention_id)]
    if len(usable) != len(wanted):
        raise AttachmentUnknownError
    for row in usable:
        row.intention_id = intention_id
    return sorted(usable, key=lambda r: wanted.index(r.id))


async def drop(
    repository: AttachmentRepository, attachment_id: uuid.UUID, *, by: uuid.UUID | None
) -> bool:
    """Removed before asking — one's own, not attached yet. False: no such
    file of this person's, or already attached (kept with its intention)."""
    row = await repository.one(attachment_id)
    if row is None or row.uploaded_by != by or row.intention_id is not None:
        return False
    await repository.remove(row)
    try:
        await object_store().delete(row.storage_key)
    except ObjectStoreError:
        # Its row is gone; the purge's walk of the store would find the
        # bytes — said, never left silent.
        logger.warning("attachment_bytes_not_removed", key=row.storage_key, exc_info=True)
    return True


def read(row: IntentionAttachment) -> AsyncIterator[bytes]:
    """Its bytes, streamed — ObjectNotFoundError when the store lost them."""
    return object_store().get(row.storage_key)


async def purge(*, now: datetime | None = None) -> int:
    """Files uploaded and never asked with, past a day: removed, bytes and
    row — across every workspace."""
    before = (now or datetime.now(UTC)) - UNLINKED_FOR
    removed = 0
    with system_scope():
        async with session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(IntentionAttachment)
                        .where(
                            IntentionAttachment.intention_id.is_(None),
                            IntentionAttachment.created_at < before,
                        )
                        .limit(500)
                    )
                ).all()
            )
            for row in rows:
                try:
                    await object_store().delete(row.storage_key)
                except ObjectNotFoundError:
                    pass
                except ObjectStoreError:
                    logger.warning("attachment_purge_failed", key=row.storage_key, exc_info=True)
                    continue
                await session.delete(row)
                removed += 1
            await session.commit()
    return removed


def run_purge() -> dict[str, int]:
    """Entry point for the schedule."""
    return {"removed": asyncio.run(purge())}
