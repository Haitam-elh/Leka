"""Documentation and office suites: Confluence, Notion, Slab, Guru, Google
Workspace, Microsoft 365 (LEKA-346).

Each has containers — a Confluence space, a Notion database, a Slab topic, a
Guru collection, a shared drive, a SharePoint library or a OneDrive — and
documents in them: a page, a post, a card, a file. A document comes out
with its title, its link, its dates, its people, and its **text** as
content — Confluence's storage XHTML and Guru's HTML read as text, Notion's
blocks line by line, Slab's Quill delta, a file's text as the connector
read it.

The payloads are the ones leka/connectors/{confluence,notion,slab,guru,
google_workspace,microsoft_365} store.
"""

from __future__ import annotations

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction.contract import Extracted, Reference
from leka.ingestion.extraction.engine import Payload, strategy
from leka.ingestion.extraction.fields import (
    content,
    delta_text,
    dig,
    flag,
    lower,
    markup_text,
    number,
    ref,
    required,
    rich_text,
    string,
    when,
)

C = Capability
CONFLUENCE, NOTION, SLAB = SourceKind.CONFLUENCE, SourceKind.NOTION, SourceKind.SLAB
GURU, GOOGLE, MICROSOFT = SourceKind.GURU, SourceKind.GOOGLE_WORKSPACE, SourceKind.MICROSOFT_365


# ── Confluence ───────────────────────────────────────────────────────────────


@strategy("confluence.spaces", 1, (CONFLUENCE, C.SPACES))
def confluence_space(p: Payload) -> Extracted:
    return Extracted(
        title=string(p, "name") or required(p, "key"),
        url=string(p, "web_url"),
        state=lower(p, "status"),
        content=content("description", string(p, "description", "plain", "value")),
        metadata={"key": string(p, "key"), "type": lower(p, "type")},
    )


@strategy("confluence.pages", 1, (CONFLUENCE, C.PAGES))
def confluence_page(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "title"),
        url=string(p, "web_url"),
        state=lower(p, "status"),
        created_at=when(p, "createdAt"),
        updated_at=when(p, "version", "createdAt") or when(p, "createdAt"),
        content=content("body", markup_text(dig(p, "body", "storage", "value"))),
        references=[
            *ref("author", "person", external_id=dig(p, "authorId")),
            *ref("parent", "document", external_id=dig(p, "parentId")),
        ],
        metadata={"version": number(p, "version", "number"), "space_id": string(p, "spaceId")},
    )


# ── Notion ───────────────────────────────────────────────────────────────────


@strategy("notion.pages", 1, (NOTION, C.PAGES))
def notion_page(p: Payload) -> Extracted:
    return Extracted(
        title=_notion_title(p) or required(p, "id"),
        url=string(p, "url"),
        state="archived" if flag(p, "archived") or flag(p, "in_trash") else "active",
        created_at=when(p, "created_time"),
        updated_at=when(p, "last_edited_time"),
        content=content("body", _blocks_text(dig(p, "blocks"))),
        references=[
            *ref("creator", "person", external_id=dig(p, "created_by", "id")),
            *_notion_parent(p),
        ],
        metadata={"blocks_truncated": flag(p, "blocks_truncated")},
    )


@strategy("notion.databases", 1, (NOTION, C.DATABASES))
def notion_database(p: Payload) -> Extracted:
    properties = dig(p, "properties")
    return Extracted(
        title=rich_text(dig(p, "title")) or required(p, "id"),
        url=string(p, "url"),
        state="archived" if flag(p, "archived") or flag(p, "in_trash") else "active",
        created_at=when(p, "created_time"),
        updated_at=when(p, "last_edited_time"),
        content=content("description", rich_text(dig(p, "description"))),
        references=_notion_parent(p),
        metadata={"properties": sorted(properties) if isinstance(properties, dict) else []},
    )


# ── Slab ─────────────────────────────────────────────────────────────────────


@strategy("slab.spaces", 1, (SLAB, C.SPACES))
def slab_topic(p: Payload) -> Extracted:
    description = dig(p, "description")
    return Extracted(
        title=required(p, "name"),
        content=content("description", delta_text(description)),
    )


@strategy("slab.pages", 1, (SLAB, C.PAGES))
def slab_post(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "title"),
        state="published" if string(p, "publishedAt") else "draft",
        created_at=when(p, "insertedAt"),
        updated_at=when(p, "updatedAt"),
        content=content("body", delta_text(dig(p, "content"))),
        metadata={"link_access": lower(p, "linkAccess"), "published_at": string(p, "publishedAt")},
    )


# ── Guru ─────────────────────────────────────────────────────────────────────


@strategy("guru.spaces", 1, (GURU, C.SPACES))
def guru_collection(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        content=content("description", string(p, "description")),
        metadata={"type": lower(p, "collectionType")},
    )


@strategy("guru.pages", 1, (GURU, C.PAGES))
def guru_card(p: Payload) -> Extracted:
    return Extracted(
        title=string(p, "preferredPhrase") or required(p, "title"),
        state=lower(p, "verificationState"),
        created_at=when(p, "dateCreated"),
        updated_at=when(p, "lastModified"),
        content=content("body", markup_text(dig(p, "content"))),
        references=[
            *ref(
                "author", "person", email=dig(p, "owner", "email"), name=_full_name(dig(p, "owner"))
            ),
            *ref(
                "collection",
                "space",
                external_id=dig(p, "collection", "id"),
                name=dig(p, "collection", "name"),
            ),
        ],
        metadata={"collection": string(p, "collection", "name"), "slug": string(p, "slug")},
    )


# ── Google Workspace ─────────────────────────────────────────────────────────


@strategy("google_workspace.drives", 1, (GOOGLE, C.DRIVES))
def google_drive(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        state="hidden" if flag(p, "hidden") else "active",
        created_at=when(p, "createdTime"),
    )


@strategy("google_workspace.files", 1, (GOOGLE, C.FILES))
def google_file(p: Payload) -> Extracted:
    owners = dig(p, "owners")
    first_owner = owners[0] if isinstance(owners, list) and owners else None
    return Extracted(
        title=required(p, "name"),
        url=string(p, "webViewLink"),
        created_at=when(p, "createdTime"),
        updated_at=when(p, "modifiedTime"),
        content=[
            *content("description", string(p, "description")),
            *content("body", string(p, "content")),
        ],
        references=[
            *ref(
                "author",
                "person",
                email=dig(first_owner, "emailAddress"),
                name=dig(first_owner, "displayName"),
            ),
            *ref(
                "editor",
                "person",
                email=dig(p, "lastModifyingUser", "emailAddress"),
                name=dig(p, "lastModifyingUser", "displayName"),
            ),
        ],
        metadata={
            "mime_type": string(p, "mimeType"),
            "size": _int(dig(p, "size")),
            "drive_id": string(p, "driveId"),
            "content_truncated": flag(p, "content_truncated"),
        },
    )


# ── Microsoft 365 ────────────────────────────────────────────────────────────


@strategy("microsoft_365.drives", 1, (MICROSOFT, C.DRIVES))
def microsoft_drive(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        url=string(p, "webUrl"),
        created_at=when(p, "createdDateTime"),
        updated_at=when(p, "lastModifiedDateTime"),
        metadata={
            "type": lower(p, "driveType"),
            "owner": string(p, "owner", "user", "displayName")
            or string(p, "owner", "group", "displayName"),
        },
    )


@strategy("microsoft_365.files", 1, (MICROSOFT, C.FILES))
def microsoft_file(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        url=string(p, "webUrl"),
        created_at=when(p, "createdDateTime"),
        updated_at=when(p, "lastModifiedDateTime"),
        content=content("body", string(p, "content")),
        references=[
            *_graph_user("author", dig(p, "createdBy")),
            *_graph_user("editor", dig(p, "lastModifiedBy")),
        ],
        metadata={
            "mime_type": string(p, "file", "mimeType"),
            "size": number(p, "size"),
            "path": string(p, "parentReference", "path"),
            "drive_id": string(p, "parentReference", "driveId"),
            "content_truncated": flag(p, "content_truncated"),
        },
    )


# ── shared ───────────────────────────────────────────────────────────────────


def _notion_title(p: Payload) -> str | None:
    """A page's title property, whatever the database named it."""
    properties = dig(p, "properties")
    if not isinstance(properties, dict):
        return None
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return rich_text(prop.get("title"))
    return None


def _blocks_text(blocks: object) -> str | None:
    """A page's blocks, a line each: the text of each block's rich text."""
    if not isinstance(blocks, list):
        return None
    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        body = block.get(str(block.get("type")))
        line = rich_text(dig(body, "rich_text")) or string(body, "title")
        if line:
            lines.append(line)
    return "\n".join(lines) or None


def _notion_parent(p: Payload) -> list[Reference]:
    """What a page or a database sits in: a page, a database — or nothing."""
    kind = string(p, "parent", "type")
    if kind in ("page_id", "database_id"):
        return ref("parent", "document", external_id=dig(p, "parent", kind))
    return []


def _graph_user(role: str, who: object) -> list[Reference]:
    return ref(
        role,
        "person",
        external_id=dig(who, "user", "id"),
        name=dig(who, "user", "displayName"),
        email=dig(who, "user", "email"),
    )


def _full_name(who: object) -> str | None:
    parts = [string(who, "firstName"), string(who, "lastName")]
    return " ".join(p for p in parts if p) or None


def _int(value: object) -> int | None:
    """Drive's sizes are numbers written as text."""
    text = str(value) if value is not None else ""
    return int(text) if text.isdigit() else None
