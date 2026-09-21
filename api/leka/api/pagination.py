"""Query parameters and the response envelope for every list the API serves.

The mechanics of a cursor live in leka.db.pagination. This is the HTTP half:
the parameters a client sends, the whitelist that decides what it may sort
by, and the shape that comes back.

THE ENVELOPE

    a list       {"data": [...], "next_cursor": "..." | null}
    one resource the object itself, unwrapped

Decided, documented, applied everywhere. A list needs somewhere to put the
cursor, and a single resource does not need a wrapper to carry nothing. The
inconsistency of doing it differently per route costs more than either
choice.

SORTING IS A WHITELIST, NEVER A PASS-THROUGH. A query parameter that reaches
the ORM is how a client ends up sorting by password_hash, or by a column
with no index that puts the database on its knees the first time a large
tenant asks for it. Each resource declares what it allows, and each entry
says what supports it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from leka.api.errors import ApiError
from leka.core.errors import ErrorCode
from leka.db.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CursorError,
    Direction,
    Page,
    SortableField,
    paginate,
)


class PageEnvelope[T](BaseModel):
    """What every list route returns."""

    data: list[T] = Field(description="The rows on this page, in the requested order.")
    next_cursor: str | None = Field(
        default=None,
        description=(
            "Pass as ?cursor= to get the next page. Null means this is the last one. "
            "Opaque: do not parse it, do not build one."
        ),
    )


@dataclass(frozen=True)
class SortCatalogue:
    """What one resource may be sorted by.

    A tuple rather than a dict so the order is the order a reader sees, and
    frozen so it cannot be widened at runtime by something that finds itself
    inconvenienced by it.
    """

    fields: tuple[SortableField, ...]
    default: str

    def resolve(self, name: str | None) -> SortableField:
        """Turn a client's `sort=` into a column, or refuse it.

        Refusing names what is allowed. A client that sends a typo gets the
        list rather than a shrug, and nothing about the schema is revealed
        that the documentation does not already say.
        """
        wanted = name or self.default
        for field in self.fields:
            if field.name == wanted:
                return field

        allowed = ", ".join(field.name for field in self.fields)
        raise ApiError(
            400,
            ErrorCode.INVALID_SORT,
            f"Cannot sort by {wanted!r}. Allowed: {allowed}.",
        )


@dataclass(frozen=True)
class PageRequest:
    """What a client asked for, before it has been checked."""

    cursor: str | None
    limit: int
    sort: str | None
    order: Direction


def page_request(
    cursor: Annotated[
        str | None,
        Query(description="From a previous response's next_cursor. Opaque."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_PAGE_SIZE, description="Rows per page."),
    ] = DEFAULT_PAGE_SIZE,
    sort: Annotated[
        str | None,
        Query(description="Field to sort by. Each resource documents what it allows."),
    ] = None,
    order: Annotated[Direction, Query(description="Ascending or descending.")] = "desc",
) -> PageRequest:
    """The four parameters every list route takes, declared once."""
    return PageRequest(cursor=cursor, limit=limit, sort=sort, order=order)


PageParams = Annotated[PageRequest, Depends(page_request)]


async def serve_page[RowT](
    session: AsyncSession,
    statement: Select[tuple[RowT]],
    *,
    request: PageRequest,
    catalogue: SortCatalogue,
    id_column: InstrumentedAttribute[Any],
) -> Page[RowT]:
    """Run one page of a query, refusing anything the client got wrong.

    The statement arrives already scoped to a workspace — it comes from a
    WorkspaceScopedRepository — and nothing here widens it. A cursor cannot
    reach the workspace filter; it only says where in the ordering to
    resume.

    A bad cursor is a 400 and never a 500. Clients keep them in URLs, users
    share those URLs, and secrets get rotated; a cursor that no longer means
    anything is an ordinary Tuesday, not a bug.
    """
    sort_by = catalogue.resolve(request.sort)
    try:
        return await paginate(
            session,
            statement,
            sort_by=sort_by,
            id_column=id_column,
            direction=request.order,
            limit=request.limit,
            cursor=request.cursor,
        )
    except CursorError as error:
        raise ApiError(
            400,
            ErrorCode.INVALID_CURSOR,
            "This cursor is not valid. Start again from the first page.",
        ) from error


__all__ = [
    "PageEnvelope",
    "PageParams",
    "PageRequest",
    "SortCatalogue",
    "page_request",
    "serve_page",
]
