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
from collections.abc import Sequence
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

from leka.connectors.graphql import read_only

MAX_RESOURCES = 20
MAX_METADATA = 30
MAX_PARAMS = 20
DEFINITION_MAX = 100_000  # characters of JSON
QUERY_MAX = 20_000  # characters of a GraphQL document

# A dotted path into a JSON document: `data`, `meta.next_cursor`, `labels.0.name`.
Path = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9_$@-]+(\.[A-Za-z0-9_$@-]+)*$", max_length=200)
]
# A resource's or a metadata's name: what LEKA shows, and a scope matches.
Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
# What a resource's records may be in LEKA's model.
Entity = Literal["issue", "incident", "service", "project", "document"]
# A GraphQL variable's name, as the spec spells them.
Variable = Annotated[str, StringConstraints(pattern=r"^[_A-Za-z][_0-9A-Za-z]{0,63}$")]
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


class Declared(BaseModel):
    """What every resource declares, whatever the API: its name, what its
    records are, where they are in an answer, what their fields mean."""

    model_config = ConfigDict(extra="forbid")

    name: Name
    # What its records are in LEKA's model; None: extracted, not modelled.
    entity: Entity | None = None
    # Where the records are in an answer; None: the answer is the list.
    items: Path | None = None
    mapping: Mapping


class Resource(Declared):
    """A REST resource: a path on the API's host, and its query."""

    # On the source's host, from its base: no scheme, no host, no query —
    # `params` holds the query — and no `..` to climb out of the base.
    path: Annotated[str, StringConstraints(pattern=r"^/[^\s?#]*$", max_length=500)]
    params: dict[Param, Annotated[str, StringConstraints(max_length=500)]] = Field(
        default_factory=dict, max_length=MAX_PARAMS
    )
    pagination: Pagination = Field(default_factory=Pagination)

    @field_validator("path")
    @classmethod
    def _within_the_base(cls, value: str) -> str:
        if ".." in value.split("/"):
            msg = "a path may not climb out of the base with `..`"
            raise ValueError(msg)
        return value


class GraphQLPagination(BaseModel):
    """How a GraphQL listing's pages follow each other.

    - `none`: one answer, the whole listing;
    - `cursor`: the end cursor (`next`: `data.issues.pageInfo.endCursor`),
      sent back as a variable (`variable`: `after`) — while `has_next`
      (`data.issues.pageInfo.hasNextPage`) says there is more, or, without
      it, while the cursor is neither empty nor the same again.

    `size_variable` and `size`: the page size, as the query takes it
    (`first`).
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "cursor"] = "none"
    next: Path | None = None
    has_next: Path | None = None
    variable: Variable | None = None
    size_variable: Variable | None = None
    size: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if self.type == "cursor" and not (self.next and self.variable):
            msg = "pagination 'cursor' needs `next`, the end cursor, and `variable`, its name"
            raise ValueError(msg)
        return self


class GraphQLResource(Declared):
    """A GraphQL resource: a query document and its variables. The query
    reads — a `mutation` or a `subscription` is refused when saved — and
    `items` is where its records are in the answer: `data.issues.nodes`."""

    query: Annotated[str, StringConstraints(min_length=5, max_length=QUERY_MAX)]
    variables: dict[Variable, Any] = Field(default_factory=dict, max_length=MAX_PARAMS)
    pagination: GraphQLPagination = Field(default_factory=GraphQLPagination)

    @field_validator("query")
    @classmethod
    def _reads(cls, value: str) -> str:
        return read_only(value, "the API")

    @model_validator(mode="after")
    def _located(self) -> Self:
        if not self.items:
            msg = "a GraphQL resource needs `items`: where its records are, as data.issues.nodes"
            raise ValueError(msg)
        return self


# What a condition compares with: text, a number, yes/no.
Value = str | int | float | bool


class Match(BaseModel):
    """A condition on a delivery: the value at `path` is `equals` — or one
    of them, when it is a list. `{"path": "event", "equals": "ticket.updated"}`."""

    model_config = ConfigDict(extra="forbid")

    path: Path
    equals: Value | list[Value]

    @field_validator("equals")
    @classmethod
    def _some(cls, value: Value | list[Value]) -> Value | list[Value]:
        if isinstance(value, list) and not 1 <= len(value) <= MAX_PARAMS:
            msg = f"`equals` lists 1 to {MAX_PARAMS} values"
            raise ValueError(msg)
        return value

    def met_by(self, document: object) -> bool:
        found = at(document, self.path)
        wanted = self.equals if isinstance(self.equals, list) else [self.equals]
        return any(_same(found, value) for value in wanted)


def _same(found: object, wanted: Value) -> bool:
    """Equal, and of the same kind: `true` is not `1`, nor `"1"`."""
    if isinstance(found, bool) or isinstance(wanted, bool):
        return isinstance(found, bool) and isinstance(wanted, bool) and found is wanted
    return isinstance(found, str | int | float) and found == wanted


class WebhookResource(Declared):
    """What a delivery is, when it is one of this resource's, and where its
    records are in it.

    `match`: the condition on the delivery — which event it is. The first
    resource whose `match` the delivery meets is its resource; one without
    `match` takes every delivery, so it comes last. `items`: where its
    records are — absent, the delivery is the record, or the list of them.
    `deleted`: the condition that says its records were deleted — they are
    marked gone, not stored."""

    match: Match | None = None
    deleted: Match | None = None


def _names_once(resources: Sequence[Declared]) -> None:
    names = [resource.name for resource in resources]
    twice = sorted({name for name in names if names.count(name) > 1})
    if twice:
        msg = f"each resource needs a name of its own: {', '.join(twice)} twice"
        raise ValueError(msg)


class Definition(BaseModel):
    """A REST source's definition."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    resources: list[Resource] = Field(min_length=1, max_length=MAX_RESOURCES)

    @model_validator(mode="after")
    def _named(self) -> Self:
        _names_once(self.resources)
        return self


class GraphQLDefinition(BaseModel):
    """A GraphQL source's definition."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    resources: list[GraphQLResource] = Field(min_length=1, max_length=MAX_RESOURCES)

    @model_validator(mode="after")
    def _named(self) -> Self:
        _names_once(self.resources)
        return self


class WebhookDefinition(BaseModel):
    """A webhook source's definition: what its deliveries may be."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    resources: list[WebhookResource] = Field(min_length=1, max_length=MAX_RESOURCES)

    @model_validator(mode="after")
    def _named(self) -> Self:
        _names_once(self.resources)
        unmatched = [r.name for r in self.resources if r.match is None]
        if len(unmatched) > 1 or (unmatched and self.resources[-1].match is not None):
            msg = (
                "a resource without `match` takes every delivery: one at most, and last — "
                f"the others would never be reached ({', '.join(unmatched)})"
            )
            raise ValueError(msg)
        return self

    def of(self, delivery: object) -> WebhookResource | None:
        """The resource a delivery is — the first whose `match` it meets."""
        for resource in self.resources:
            if resource.match is None or resource.match.met_by(delivery):
                return resource
        return None


def parse(text: str) -> Definition:
    """A REST definition from its JSON — or a ValueError that says, in a
    line, where it is wrong."""
    return _parsed(text, Definition)


def parse_graphql(text: str) -> GraphQLDefinition:
    """A GraphQL definition from its JSON, as `parse`."""
    return _parsed(text, GraphQLDefinition)


def parse_webhook(text: str) -> WebhookDefinition:
    """A webhook definition from its JSON, as `parse`."""
    return _parsed(text, WebhookDefinition)


def _parsed[T: BaseModel](text: str, model: type[T]) -> T:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        msg = f"the definition is not JSON: line {error.lineno}, column {error.colno}"
        raise ValueError(msg) from None
    try:
        return model.model_validate(document)
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
