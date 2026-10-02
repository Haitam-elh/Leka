"""Documentation and office suites: Confluence, Notion, Slab, Guru, Google
Workspace, Microsoft 365 (LEKA-346).

Each has containers — a Confluence space, a Notion database, a Slab topic, a
Guru collection, a shared drive, a SharePoint library or a OneDrive — and
documents in them: a page, a post, a card, a file. A document comes out
with its title, its link, its dates, its people, and its **text** as
content — Confluence's storage XHTML and Guru's HTML read as text, Notion's
blocks line by line, Slab's Quill delta, a file's text as the connector
read it. And what it links to (`metadata.links`), its owner and who last
edited it where its tool says, what it sits in — a Notion page in a
database is in a space, not under a page (LEKA-366).

The payloads are the ones leka/connectors/{confluence,notion,slab,guru,
google_workspace,microsoft_365} store.
"""

from __future__ import annotations

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction.contract import Extracted, Reference
from leka.ingestion.extraction.engine import Payload, strategy
from leka.ingestion.extraction.fields import (
    content,
    delta_links,
    delta_text,
    dig,
    flag,
    links,
    lower,
    markup_links,
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


@strategy("confluence.pages", 2, (CONFLUENCE, C.PAGES))
def confluence_page(p: Payload) -> Extracted:
    body = dig(p, "body", "storage", "value")
    return Extracted(
        title=required(p, "title"),
        url=string(p, "web_url"),
        state=lower(p, "status"),
        created_at=when(p, "createdAt"),
        updated_at=when(p, "version", "createdAt") or when(p, "createdAt"),
        content=content("body", markup_text(body)),
        references=[
            *ref("author", "person", external_id=dig(p, "authorId")),
            *ref("owner", "person", external_id=dig(p, "ownerId")),
            *ref("editor", "person", external_id=dig(p, "version", "authorId")),
            *ref("parent", "document", external_id=dig(p, "parentId")),
        ],
        metadata={
            "version": number(p, "version", "number"),
            "space_id": string(p, "spaceId"),
            "links": markup_links(body),
        },
    )


# ── Notion ───────────────────────────────────────────────────────────────────


@strategy("notion.pages", 2, (NOTION, C.PAGES))
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
            *ref("editor", "person", external_id=dig(p, "last_edited_by", "id")),
            *_notion_parent(p),
        ],
        metadata={
            "blocks_truncated": flag(p, "blocks_truncated"),
            "links": _blocks_links(dig(p, "blocks")),
        },
    )


@strategy("notion.databases", 2, (NOTION, C.DATABASES))
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


@strategy("slab.pages", 2, (SLAB, C.PAGES))
def slab_post(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "title"),
        state="published" if string(p, "publishedAt") else "draft",
        created_at=when(p, "insertedAt"),
        updated_at=when(p, "updatedAt"),
        content=content("body", delta_text(dig(p, "content"))),
        metadata={
            "link_access": lower(p, "linkAccess"),
            "published_at": string(p, "publishedAt"),
            "links": delta_links(dig(p, "content")),
        },
    )


# ── Guru ─────────────────────────────────────────────────────────────────────


@strategy("guru.spaces", 1, (GURU, C.SPACES))
def guru_collection(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        content=content("description", string(p, "description")),
        metadata={"type": lower(p, "collectionType")},
    )


@strategy("guru.pages", 2, (GURU, C.PAGES))
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
                "editor",
                "person",
                email=dig(p, "lastModifiedBy", "email"),
                name=_full_name(dig(p, "lastModifiedBy")),
            ),
            *ref(
                "collection",
                "space",
                external_id=dig(p, "collection", "id"),
                name=dig(p, "collection", "name"),
            ),
        ],
        metadata={
            "collection": string(p, "collection", "name"),
            "slug": string(p, "slug"),
            "last_verified_at": string(p, "lastVerified"),
            "next_verification_at": string(p, "nextVerificationDate"),
            "links": markup_links(dig(p, "content")),
        },
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


@strategy("microsoft_365.drives", 2, (MICROSOFT, C.DRIVES))
def microsoft_drive(p: Payload) -> Extracted:
    """A SharePoint library, a OneDrive: its owner a group — a team's site —
    or a person (LEKA-366)."""
    return Extracted(
        title=required(p, "name"),
        url=string(p, "webUrl"),
        created_at=when(p, "createdDateTime"),
        updated_at=when(p, "lastModifiedDateTime"),
        references=[
            *ref("owner", "team", name=dig(p, "owner", "group", "displayName")),
            *_graph_user("owner", dig(p, "owner")),
        ],
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


def _blocks_links(blocks: object) -> list[str]:
    """What a page's blocks link to: their runs' addresses — a link, a
    mention of a page — and the pages a block links to."""
    found: list[str] = []
    for block in blocks if isinstance(blocks, list) else []:
        kind = str(dig(block, "type"))
        body = dig(block, kind)
        runs = dig(body, "rich_text")
        listed = runs if isinstance(runs, list) else []
        found += [str(run.get("href") or "") for run in listed if isinstance(run, dict)]
        if kind == "link_to_page":
            target = string(body, "page_id") or string(body, "database_id")
            if target:
                found.append(f"https://www.notion.so/{target.replace('-', '')}")
    return links(found)


def _notion_parent(p: Payload) -> list[Reference]:
    """What a page or a database sits in: a page — or a database, the space
    its pages are kept in — or nothing."""
    kind = string(p, "parent", "type")
    if kind == "page_id":
        return ref("parent", "document", external_id=dig(p, "parent", kind))
    if kind == "database_id":
        return ref("parent", "space", external_id=dig(p, "parent", kind))
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
