"""Small, forgiving readers of vendor JSON, shared by the strategies.

Forgiving where a vendor may leave a field out (`dig`), strict where the
record means nothing without it (`required`).
"""

from __future__ import annotations

import html
import json
import re
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


# Atlassian Document Format: the blocks that end a line, and the inline
# nodes whose text lives in their attributes.
_ADF_BLOCKS = frozenset(
    {"paragraph", "heading", "codeBlock", "blockquote", "tableRow", "panel", "rule"}
)
_ADF_INLINE = {"mention": "text", "emoji": "shortName", "status": "text", "inlineCard": "url"}


def adf_text(document: object) -> str | None:
    """Jira's rich text (ADF) as plain text: its words, a line per block.

    Walked with a stack, not recursion: a payload decides how deep it nests,
    and a quoted quote in a list in a panel costs nothing.
    A plain string — an older API, a plain field — is returned as it is.
    """
    if isinstance(document, str):
        return document.strip() or None
    parts: list[str] = []
    stack: list[object] = [document]
    while stack:
        node = stack.pop()
        if node == "\n":
            parts.append("\n")
            continue
        if not isinstance(node, dict):
            continue
        kind = node.get("type")
        if kind == "text":
            parts.append(str(node.get("text") or ""))
        elif kind == "hardBreak":
            parts.append("\n")
        elif kind in _ADF_INLINE:
            parts.append(string(node, "attrs", _ADF_INLINE[str(kind)]) or "")
        if kind in _ADF_BLOCKS:
            stack.append("\n")
        children = node.get("content")
        if isinstance(children, list):
            stack.extend(reversed(children))
    text = re.sub(r"\n{3,}", "\n\n", "".join(parts)).strip()
    return text or None


def tags(value: object, *path: str | int) -> list[str]:
    """Cloud tags as 'key=value', sorted — from AWS's [{Key, Value}] or
    Azure's and Google's {key: value}."""
    found = dig(value, *path)
    pairs: list[tuple[str | None, str | None]] = []
    if isinstance(found, dict):
        pairs = [(string(k), string(v)) for k, v in found.items()]
    elif isinstance(found, list):
        pairs = [(string(t, "Key"), string(t, "Value")) for t in found]
    return sorted(f"{k}={v or ''}" for k, v in pairs if k)


def last_segment(value: str | None) -> str | None:
    """'…/zones/europe-west1-b/machineTypes/e2-small' → 'e2-small'."""
    return value.rstrip("/").rsplit("/", 1)[-1] or None if value else None


# A markup element that ends a line of text: a paragraph, a heading, a cell.
_MARKUP_BLOCKS = re.compile(
    r"</?(?:p|div|br|li|tr|td|th|h[1-6]|pre|blockquote|table|ul|ol)\b[^>]*>", re.IGNORECASE
)
_MARKUP_DROPPED = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_MARKUP_TAG = re.compile(r"<[^>]+>")


def markup_text(markup: object) -> str | None:
    """HTML or Confluence's storage XHTML as plain text: its words, a line
    per block. Read by expressions, never parsed: no entity is expanded
    beyond HTML's own, nothing is fetched."""
    if not isinstance(markup, str) or not markup.strip():
        return None
    text = _MARKUP_DROPPED.sub(" ", markup)
    text = _MARKUP_BLOCKS.sub("\n", text)
    text = html.unescape(_MARKUP_TAG.sub("", text))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    joined = "\n".join(line for line in lines if line)
    return joined or None


def delta_text(value: object) -> str | None:
    """A Quill delta — Slab's rich text, as JSON text or a list of
    operations — as plain text: what its operations insert."""
    operations = value
    if isinstance(value, str):
        try:
            operations = json.loads(value)
        except json.JSONDecodeError:
            return value.strip() or None
    if isinstance(operations, dict):
        operations = operations.get("ops")
    if not isinstance(operations, list):
        return None
    parts = [
        op["insert"]
        for op in operations
        if isinstance(op, dict) and isinstance(op.get("insert"), str)
    ]
    return "".join(parts).strip() or None


def rich_text(value: object) -> str | None:
    """Notion's rich text — a list of runs — as its plain text."""
    if not isinstance(value, list):
        return None
    text = "".join(str(run.get("plain_text") or "") for run in value if isinstance(run, dict))
    return text.strip() or None
