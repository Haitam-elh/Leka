"""Systems LEKA has no connector for (LEKA-350): what their admin mapped.

A generic source — REST, GraphQL, or a webhook — stores each record as
`{"resource", "entity", "fields", "record"}` (leka/connectors/custom/common.py),
read or received alike: `fields`
is what the source's mapping read in the record — LEKA's own fields, named
as the extraction contract names them. So one strategy reads every such
source, whatever the system and its API: the meaning was declared by the
admin, not guessed here.

    title        the name — a record without one is malformed
    url          where a person opens it
    state        lower-cased, the system's own word
    created_at   ISO 8601, or seconds or milliseconds since the epoch
    updated_at
    description  the text, as `description` content
    author       a person — an address when it is one, a name else
    metadata     what the admin named: text, numbers, yes/no, lists of text

The resource is a signal — `tickets`, `assets`, in the admin's words — and
so is the entity the admin declared for it (`issue`, `service`…), which
normalisation reads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from leka.connectors import Capability, SourceKind
from leka.connectors.custom.definition import moment
from leka.ingestion.extraction.contract import Extracted, Scalar
from leka.ingestion.extraction.engine import MalformedPayloadError, Payload, strategy
from leka.ingestion.extraction.fields import content, dig, lower, ref, required, string

C = Capability
CUSTOM_REST = SourceKind.CUSTOM_REST
CUSTOM_GRAPHQL = SourceKind.CUSTOM_GRAPHQL
CUSTOM_WEBHOOK = SourceKind.CUSTOM_WEBHOOK


@strategy(
    "custom.records",
    1,
    (CUSTOM_REST, C.RECORDS),
    (CUSTOM_GRAPHQL, C.RECORDS),
    (CUSTOM_WEBHOOK, C.RECORDS),
)
def custom_record(p: Payload) -> Extracted:
    if not isinstance(dig(p, "fields"), dict):
        raise MalformedPayloadError("missing field 'fields'")
    author = string(p, "fields", "author")
    return Extracted(
        title=required(p, "fields", "title"),
        url=string(p, "fields", "url"),
        state=lower(p, "fields", "state"),
        created_at=_moment(p, "created_at"),
        updated_at=_moment(p, "updated_at"),
        content=content("description", string(p, "fields", "description")),
        references=ref(
            "author",
            "person",
            name=None if author and "@" in author else author,
            email=author if author and "@" in author else None,
        ),
        metadata=_metadata(dig(p, "fields", "metadata")),
        signals={"resource": string(p, "resource"), "entity": string(p, "entity")},
    )


def _moment(p: Payload, name: str) -> datetime | None:
    """A mapped date — a date that is not one makes the record malformed,
    as it does from any source."""
    value = dig(p, "fields", name)
    if value is None:
        return None
    found = moment(value)
    if found is None:
        raise MalformedPayloadError(f"not a date: 'fields.{name}'")
    return found


def _metadata(value: object) -> dict[str, Scalar | list[str]]:
    """What the admin named, as the contract carries it: text, numbers and
    yes/no as they are, lists of them as text; an object is left out — the
    mapping should point inside it."""
    if not isinstance(value, dict):
        return {}
    found: dict[str, Scalar | list[str]] = {}
    for name, item in value.items():
        if isinstance(item, str | int | float | bool):
            found[str(name)] = item
        elif isinstance(item, list):
            texts = [str(entry) for entry in item if _plain(entry)]
            if texts:
                found[str(name)] = texts
    return found


def _plain(value: Any) -> bool:
    return isinstance(value, str | int | float) and not isinstance(value, bool)
