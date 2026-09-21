"""Cursor pagination. One implementation, for every list the API serves.

NEVER OFFSET AND LIMIT. Rows are inserted while somebody is reading, so
`OFFSET 20` means "skip whatever the first twenty are right now". Insert one
row at the top between page one and page two and the reader sees an item
twice; delete one and they never see the item that shifted up. On a screen
fed continuously — the history of a workspace, a stream of incidents — that
is not an edge case, it is the normal behaviour.

A cursor names a POSITION instead of a COUNT: "everything after this row".
Rows arriving above it do not move it.

THE CURSOR IS OPAQUE, AND SIGNED. Opaque so the encoding can change without
breaking clients, and so nobody is tempted to build one by hand. Signed with
the application secret, so a modified one is refused before its contents are
trusted at all — the difference between "a forged cursor is harmless" and
"a forged cursor is impossible". Validation alone would have been enough for
the first; the second is cheap.

A rotation of LEKA_SECRET_KEY invalidates cursors in flight. A cursor lives
for seconds, so that is a non-event, and it is the price of the signature.

IT CARRIES THE SORT KEY AND THE ID. The id is the tiebreaker, and leaving it
out is the classic way to lose rows: two records with the same timestamp sit
on a page boundary, and "everything after that timestamp" skips one of them
for ever. The comparison is on the pair, which is also what an index on
(sort column, id) is shaped for.

IT NEVER CARRIES A WORKSPACE. The workspace comes from the Principal, always
— rule 3. A cursor arrives from the client; anything in it is a request, not
a fact. There is a test that signs a cursor containing someone else's
workspace id and proves the server ignores it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, literal, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from leka.core.config import settings

Direction = Literal["asc", "desc"]

# How many rows a page holds when the client does not say, and the most it
# may ask for. The ceiling is not politeness: without it, `limit=1000000` is
# a way to turn one request into a full table read.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class CursorError(ValueError):
    """A cursor that was not produced by us, or no longer means anything.

    One exception for "malformed", "badly signed", "sorted differently" and
    "truncated". Telling them apart would help somebody probing far more
    than it helps a client, which only ever needs to start again from the
    first page.
    """


@dataclass(frozen=True)
class SortableField:
    """A field a client is allowed to sort by, and what backs it.

    `note` is not documentation for its own sake. Every sortable field costs
    an index or a sort in memory, and the day somebody exposes a column with
    neither, the first large tenant finds out. Writing down what supports it
    forces the question at the moment it is cheap to answer.
    """

    name: str
    column: InstrumentedAttribute[Any]
    note: str


@dataclass(frozen=True)
class Page[T]:
    """A slice of a list, and how to ask for the next one."""

    items: list[T]
    next_cursor: str | None


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(payload: bytes) -> str:
    secret = settings.secret_key.get_secret_value().encode()
    return _b64(hmac.new(secret, payload, hashlib.sha256).digest())


def _encode_value(value: object) -> object:
    """Make a sort key survive a round trip through JSON.

    Datetimes and UUIDs are what we actually sort by; both come back as
    strings and are turned back into themselves on the way in.
    """
    if isinstance(value, datetime):
        return {"t": "datetime", "v": value.isoformat()}
    if isinstance(value, uuid.UUID):
        return {"t": "uuid", "v": str(value)}
    return value


def _decode_value(value: object) -> object:
    if isinstance(value, dict) and "t" in value and "v" in value:
        kind, raw = value["t"], value["v"]
        if kind == "datetime":
            return datetime.fromisoformat(str(raw))
        if kind == "uuid":
            return uuid.UUID(str(raw))
        msg = "unknown cursor value type"
        raise CursorError(msg)
    return value


def encode_cursor(*, sort: str, direction: Direction, key: object, row_id: uuid.UUID) -> str:
    """Build the cursor that points just after one row."""
    payload = json.dumps(
        {"s": sort, "d": direction, "k": _encode_value(key), "i": str(row_id)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"{_b64(payload)}.{_sign(payload)}"


def decode_cursor(cursor: str, *, sort: str, direction: Direction) -> tuple[object, uuid.UUID]:
    """Read a cursor, or refuse it.

    The signature is checked before anything in the payload is looked at, so
    a forged cursor never reaches the code that would interpret it.

    The sort and direction are compared against the request. Reusing a
    cursor while changing `sort=` would otherwise walk one ordering with a
    position taken from another, and quietly return nonsense — which is
    worse than an error, because nobody would notice.
    """
    try:
        encoded, signature = cursor.split(".", 1)
        payload = _unb64(encoded)
    except (ValueError, binascii.Error) as error:
        msg = "cursor is malformed"
        raise CursorError(msg) from error

    if not hmac.compare_digest(signature, _sign(payload)):
        msg = "cursor signature does not match"
        raise CursorError(msg)

    try:
        data = json.loads(payload)
        if data["s"] != sort or data["d"] != direction:
            msg = "cursor was issued for a different ordering"
            raise CursorError(msg)
        # Anything else in the payload — a workspace id, say — is ignored on
        # purpose. Only these two fields are ever read out of it.
        return _decode_value(data["k"]), uuid.UUID(str(data["i"]))
    except CursorError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        msg = "cursor contents are not usable"
        raise CursorError(msg) from error


async def paginate[T](
    session: AsyncSession,
    statement: Select[tuple[T]],
    *,
    sort_by: SortableField,
    id_column: InstrumentedAttribute[Any],
    direction: Direction = "desc",
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> Page[T]:
    """Run a query as one page, and say how to get the next.

    The statement arrives already scoped — it comes from a
    WorkspaceScopedRepository — and this function never widens it. It only
    adds an ordering, a position and a ceiling.

    One row more than asked for is fetched, and dropped. That is how the
    next cursor is only issued when there is genuinely something after this
    page: a client that keeps asking until `next_cursor` is null makes
    exactly one wasted request instead of discovering the end by getting an
    empty page.
    """
    bounded = max(1, min(limit, MAX_PAGE_SIZE))

    if cursor is not None:
        key, row_id = decode_cursor(cursor, sort=sort_by.name, direction=direction)
        position = tuple_(sort_by.column, id_column)
        # literal() rather than the bare values: these are bound parameters,
        # never interpolated, and saying so is what keeps a cursor's contents
        # from ever being part of the SQL text.
        marker = tuple_(literal(key), literal(row_id))
        # Row-value comparison, not `col < k OR (col = k AND id < i)`. Same
        # meaning, and this is the form an index on (column, id) serves
        # directly.
        statement = statement.where(position < marker if direction == "desc" else position > marker)

    ordering = (
        (sort_by.column.desc(), id_column.desc())
        if direction == "desc"
        else (sort_by.column.asc(), id_column.asc())
    )
    statement = statement.order_by(*ordering).limit(bounded + 1)

    rows = list((await session.execute(statement)).scalars().all())

    if len(rows) <= bounded:
        return Page(items=rows, next_cursor=None)

    page = rows[:bounded]
    last = page[-1]
    return Page(
        items=page,
        next_cursor=encode_cursor(
            sort=sort_by.name,
            direction=direction,
            key=getattr(last, sort_by.column.key),
            row_id=getattr(last, id_column.key),
        ),
    )


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "CursorError",
    "Direction",
    "Page",
    "SortableField",
    "decode_cursor",
    "encode_cursor",
    "paginate",
]
