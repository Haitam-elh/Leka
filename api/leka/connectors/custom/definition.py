"""What an admin declares of a system LEKA has no connector for (LEKA-350).

A definition says, for each kind of thing to read — a `resource` — where it
is, how its pages follow each other, and what each field of it means to
LEKA. It is data, not code: a JSON document in the source's settings,
validated here, so that a system LEKA has never heard of is read without a
line of the core changing.

    {
      "version": 1,
      "resources": [
        {
          "name": "tickets",
          "entity": "issue",
          "path": "/api/v2/tickets",
          "params": {"status": "open"},
          "items": "data",
          "pagination": {"type": "cursor", "next": "meta.next_cursor",
                         "param": "cursor", "size_param": "limit", "size": 100},
          "mapping": {"id": "id", "title": "subject", "url": "html_url",
                      "state": "status", "updated_at": "updated_at",
                      "description": "description", "author": "requester.email",
                      "metadata": {"priority": "priority", "tags": "tags"}}
        }
      ]
    }

`entity` says what a resource's records are in LEKA's model — an `issue`,
an `incident`, a `service`, a `project`, a `document` — so normalisation
makes them entities (leka/ingestion/normalisation/mapping.py). Without it,
they are extracted, and stay out of the model.

A path in `items`, `next` and the mapping is a dotted path into the JSON:
`requester.email`, `labels.0.name`. What it leads to in each record is its
value, read as is — the mapping never runs anything.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

MAX_RESOURCES = 20
MAX_METADATA = 30
MAX_PARAMS = 20
DEFINITION_MAX = 100_000  # characters of JSON

# A dotted path into a JSON document: `data`, `meta.next_cursor`, `labels.0.name`.
Path = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9_$@-]+(\.[A-Za-z0-9_$@-]+)*$", max_length=200)
]
# A resource's or a metadata's name: what LEKA shows, and a scope matches.
Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
# What a resource's records may be in LEKA's model.
Entity = Literal["issue", "incident", "service", "project", "document"]
# A query parameter's name, as an API spells it.
Param = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.\[\]-]{1,64}$")]


class Pagination(BaseModel):
    """How one page leads to the next.

    - `none`: one page, the whole listing;
    - `link`: the Link header's `rel="next"` (GitHub's way);
    - `next_url`: a field of the body holds the next page's URL (`next`);
    - `cursor`: a field of the body holds a token (`next`), sent back as a
      parameter (`param`) — the listing ends when it is empty;
    - `page`: a page number (`param`), from `start` (1), until a page comes
      back short or empty;
    - `offset`: an offset (`param`), from `start` (0), the same way.

    `size_param` and `size`: the page size, when the API takes one.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "link", "next_url", "cursor", "page", "offset"] = "none"
    next: Path | None = None
    param: Param | None = None
    size_param: Param | None = None
    size: int = Field(default=100, ge=1, le=1000)
    start: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _complete(self) -> Self:
        needs_next = self.type in ("next_url", "cursor")
        needs_param = self.type in ("cursor", "page", "offset")
        if needs_next and not self.next:
            msg = f"pagination {self.type!r} needs `next`: the field that says what comes next"
            raise ValueError(msg)
        if needs_param and not self.param:
            msg = f"pagination {self.type!r} needs `param`: the query parameter to send"
            raise ValueError(msg)
        return self

    @property
    def first(self) -> int:
        """The first page's number, or the first offset."""
        if self.start is not None:
            return self.start
        return 1 if self.type == "page" else 0


class Mapping(BaseModel):
    """What each field of a record means to LEKA: a path in the record for
    each of LEKA's fields. `id` and `title` are required — a record LEKA
    cannot tell from another, or name, is not one."""

    model_config = ConfigDict(extra="forbid")

    id: Path
    title: Path
    url: Path | None = None
    state: Path | None = None
    created_at: Path | None = None
    updated_at: Path | None = None
    description: Path | None = None
    author: Path | None = None
    metadata: dict[Name, Path] = Field(default_factory=dict, max_length=MAX_METADATA)


class Resource(BaseModel):
    """One kind of thing to read, and where."""

    model_config = ConfigDict(extra="forbid")

    name: Name
    # What its records are in LEKA's model; None: extracted, not modelled.
    entity: Entity | None = None
    # On the source's host, from its base: no scheme, no host, no query —
    # `params` holds the query — and no `..` to climb out of the base.
    path: Annotated[str, StringConstraints(pattern=r"^/[^\s?#]*$", max_length=500)]
    params: dict[Param, Annotated[str, StringConstraints(max_length=500)]] = Field(
        default_factory=dict, max_length=MAX_PARAMS
    )
    # Where the records are in a page; None: the page is the list.
    items: Path | None = None
    pagination: Pagination = Field(default_factory=Pagination)
    mapping: Mapping

    @field_validator("path")
    @classmethod
    def _within_the_base(cls, value: str) -> str:
        if ".." in value.split("/"):
            msg = "a path may not climb out of the base with `..`"
            raise ValueError(msg)
        return value


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    resources: list[Resource] = Field(min_length=1, max_length=MAX_RESOURCES)

    @model_validator(mode="after")
    def _names_once(self) -> Self:
        names = [resource.name for resource in self.resources]
        twice = sorted({name for name in names if names.count(name) > 1})
        if twice:
            msg = f"each resource needs a name of its own: {', '.join(twice)} twice"
            raise ValueError(msg)
        return self

    def resource(self, name: str) -> Resource | None:
        return next((resource for resource in self.resources if resource.name == name), None)


def parse(text: str) -> Definition:
    """A definition from its JSON — or a ValueError that says, in a line,
    where it is wrong."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        msg = f"the definition is not JSON: line {error.lineno}, column {error.colno}"
        raise ValueError(msg) from None
    try:
        return Definition.model_validate(document)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(step) for step in first["loc"]) or "the definition"
        msg = f"{where}: {first['msg']}"
        raise ValueError(msg) from None


def at(document: object, path: str) -> object:
    """The value at a dotted path, or None as soon as a step is missing. A
    step made of digits indexes a list."""
    value = document
    for step in path.split("."):
        if isinstance(value, dict):
            value = value.get(step)
        elif isinstance(value, list) and re.fullmatch(r"\d+", step) and int(step) < len(value):
            value = value[int(step)]
        else:
            return None
    return value


def fields(mapping: Mapping, record: dict[str, Any]) -> dict[str, Any]:
    """What the mapping reads in one record: LEKA's fields, each the value
    at its path — left out where the record has nothing there."""
    found: dict[str, Any] = {}
    for name in (
        "id",
        "title",
        "url",
        "state",
        "created_at",
        "updated_at",
        "description",
        "author",
    ):
        path = getattr(mapping, name)
        if path is not None and (value := at(record, path)) is not None:
            found[name] = value
    metadata = {
        name: value
        for name, path in mapping.metadata.items()
        if (value := at(record, path)) is not None
    }
    if metadata:
        found["metadata"] = metadata
    return found


def identifier(value: object) -> str | None:
    """A record's id as text — a number or a string, never an object."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | str):
        text = str(value).strip()
        return text or None
    return None


def moment(value: object) -> datetime | None:
    """A date as APIs write them: ISO 8601 — without a zone, read as UTC —
    or seconds, or milliseconds, since the epoch. None when it is neither."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        seconds = value / 1000 if value > 100_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if re.fullmatch(r"\d{9,13}", text):
        return moment(int(text))
    try:
        found = datetime.fromisoformat(text)
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)
