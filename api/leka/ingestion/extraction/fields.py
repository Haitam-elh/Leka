"""Small, forgiving readers of vendor JSON, shared by the strategies.

Forgiving where a vendor may leave a field out (`dig`), strict where the
record means nothing without it (`required`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from leka.ingestion.extraction.contract import MAX_TEXT, Content, Reference
from leka.ingestion.extraction.engine import MalformedPayloadError


def dig(value: object, *path: str | int) -> object:
    """value[path[0]][path[1]]…, or None as soon as a step is missing."""
    for step in path:
        if isinstance(step, int) and isinstance(value, list) and -len(value) <= step < len(value):
            value = value[step]
        elif isinstance(step, str) and isinstance(value, dict):
            value = value.get(step)
        else:
            return None
    return value


def required(value: object, *path: str | int) -> str:
    """A string the record means nothing without — a title, an id. Missing,
    or not text, the record is malformed."""
    found = string(value, *path)
    if found is None:
        where = ".".join(str(p) for p in path)
        if dig(value, *path) is None:
            raise MalformedPayloadError(f"missing field {where!r}")
        raise MalformedPayloadError(f"not text: {where!r}")
    return found


def string(value: object, *path: str | int) -> str | None:
    """A non-empty string, or None. Numbers become strings: ids often are."""
    found = dig(value, *path)
    if isinstance(found, bool) or found is None:
        return None
    if isinstance(found, int | float | str):
        text = str(found).strip()
        return text or None
    return None


def when(value: object, *path: str | int) -> datetime | None:
    """An ISO 8601 date, as every vendor here writes them — "Z", "+02:00",
    "+0200" alike. A date that is not one makes the record malformed."""
    found = string(value, *path)
    if found is None:
        return None
    try:
        return datetime.fromisoformat(found)
    except ValueError as error:
        raise MalformedPayloadError(f"not a date: {'.'.join(str(p) for p in path)!r}") from error


def flag(value: object, *path: str | int) -> bool | None:
    found = dig(value, *path)
    return found if isinstance(found, bool) else None


def number(value: object, *path: str | int) -> int | float | None:
    found = dig(value, *path)
    return found if isinstance(found, int | float) and not isinstance(found, bool) else None


def lower(value: object, *path: str | int) -> str | None:
    found = string(value, *path)
    return found.lower() if found else None


def strings(value: object, *path: str | int, key: str | None = None) -> list[str]:
    """A list of strings — or of objects, each read at `key` (labels' names)."""
    found = dig(value, *path)
    if not isinstance(found, list):
        return []
    out = [string(item, key) if key else string(item) for item in found]
    return [item for item in out if item]


def first_line(text: str | None) -> str | None:
    stripped = (text or "").strip()
    return stripped.splitlines()[0].strip() if stripped else None


def content(role: str, text: object, fmt: Literal["text", "markdown"] = "text") -> list[Content]:
    """A text as Content — none if it is empty, cut at MAX_TEXT if long."""
    if not isinstance(text, str) or not text.strip():
        return []
    cut = len(text) > MAX_TEXT
    return [Content(role=role, format=fmt, text=text[:MAX_TEXT] if cut else text, truncated=cut)]


def ref(
    role: str,
    kind: str,
    *,
    external_id: object = None,
    name: object = None,
    email: object = None,
) -> list[Reference]:
    """A Reference — none if it names nothing."""
    ids = [string(v) for v in (external_id, name, email)]
    if not any(ids):
        return []
    return [Reference(role=role, kind=kind, external_id=ids[0], name=ids[1], email=ids[2])]


def people(
    role: str, items: object, *, id_key: str, name_key: str | None = None
) -> list[Reference]:
    """One person Reference per object of a list (assignees, reviewers)."""
    if not isinstance(items, list):
        return []
    out: list[Reference] = []
    for item in items:
        out += ref(
            role, "person", external_id=dig(item, id_key), name=dig(item, name_key or id_key)
        )
    return out
