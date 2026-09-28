"""The Notion connector — notion.so, through its public API (version 2022-06-28).

Notion is read at https://api.notion.com/v1 with an internal integration's
secret, as Bearer. The integration sees only what the workspace shared with
it — a page or a database, and everything beneath — so the first boundary
is Notion's own sharing. `roots` narrows it further, never wider.

LEKA READS, AND ONE READ IS A POST. Notion lists what it shares only
through POST /search: that one path is declared (`reads_by_post`), and every
other call is a GET. The API cannot tell LEKA which capabilities the
integration was given, so the documentation asks for "Read content" only;
nothing here could write in any case.

test_connection: who am I (GET /users/me — the integration and its
workspace), is every root in scope shared (GET /pages/{id}, else
/databases/{id}), what can I see (one search of pages, one of databases).

check_health: GET /users/me. Notion sends no quota headers.

list_scope: the tops of what is shared — pages and databases whose parent
the integration cannot see — among the MAX_SCOPE_SCAN most recently edited.

iter_resources: POST /search, most recently edited first, pages or
databases. An incremental pass stops at the first one edited before the
last pass, less a margin: Notion rounds edit times down to the minute. A
page comes with its blocks — its text — from GET /blocks/{id}/children,
nested ones included to MAX_DEPTH, at most MAX_BLOCKS. With `roots`, an
object is read only when a root is among its ancestors, each ancestor
asked of Notion once per pass.

Notion allows about three requests a second, on average: the client keeps
to it rather than be refused halfway through a pass.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from leka.connectors.base import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    HealthResult,
    ScopeListing,
    ScopeOption,
)
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.http import (
    Item,
    Pace,
    VendorHttp,
    dig,
    parse_timestamp,
    record,
    refusal,
    retry_after,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
SEARCH = "/search"
PAGE_SIZE = 100  # Notion's maximum
MAX_SCOPE_OPTIONS = 1000
# Objects looked through to find the tops of what is shared: twenty
# searches, about seven seconds at Notion's pace.
MAX_SCOPE_SCAN = 2000
MAX_DEPTH = 3  # levels of blocks read, the page's own being the first
MAX_BLOCKS = 1000  # per page
MAX_ANCESTRY = 64
# Notion rounds last_edited_time down to the minute: a page edited while
# the last pass ran may carry a time from before it started.
EDIT_MARGIN = timedelta(minutes=2)
# Seconds between two requests: Notion's limit is three a second, on average.
MIN_INTERVAL = 0.34
# A page's or a database's id: 32 hex digits, dashed or not, alone or
# ending a URL ("…/Roadmap-1a2b…?v=…").
NOTION_ID = re.compile(r"([0-9a-f]{32})$")
# Blocks that are objects of their own — a page, a database — found by the
# search, never read as a part of their parent.
SEPARATE = frozenset({"child_page", "child_database"})
# How to ask Notion for what an object sits in, by the kind of its parent.
LOOKUP = {"page_id": "/pages/{}", "database_id": "/databases/{}", "block_id": "/blocks/{}"}

type Parent = tuple[str, str]  # ("page_id", "1a2b…"), ("database_id", …), ("block_id", …)


def notion_id(value: str) -> str:
    """The id of a page or a database, from what an admin typed or pasted —
    "1a2b…", "1a2b3c4d-…", "https://www.notion.so/acme/Roadmap-1a2b…?v=…" —
    written the way Notion's answers write it. Anything else is refused."""
    text = value.strip().lower().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    found = NOTION_ID.search(text.replace("-", ""))
    if not found:
        msg = f"{value!r} is not the id or the link of a Notion page or database"
        raise ValueError(msg)
    h = found.group(1)
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


class NotionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roots: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Ids of the pages and databases to read, each with everything beneath it. "
        "Empty: everything shared with the integration.",
    )

    @field_validator("roots")
    @classmethod
    def _roots_are_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(notion_id(root) for root in value))


class NotionCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr = Field(
        min_length=20,
        description="The internal integration's secret (ntn_…), from "
        "notion.so/profile/integrations.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class NotionConnector(Connector[NotionConfig, NotionCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.NOTION,
        display_name="Notion",
        category=ConnectorCategory.DOCS,
        auth_type="token",
        config_schema=NotionConfig,
        credentials_schema=NotionCredentials,
        capabilities=frozenset({Capability.PAGES, Capability.DATABASES}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            me = (await client.get("/users/me")).json()
            metadata: dict[str, object] = {"workspace": dig(me, "bot.workspace_name")}
            if self.config.roots:
                await self._require_scope(client)
            pages = (await client.post(SEARCH, _search("page"))).json()
            databases = (await client.post(SEARCH, _search("database", page_size=1))).json()

        listed = pages.get("results") or []
        metadata["pages_visible"] = f"{len(listed)}+" if pages.get("has_more") else len(listed)
        capabilities = [Capability.PAGES] if listed else []
        if databases.get("results"):
            capabilities.append(Capability.DATABASES)
        warnings = (
            []
            if capabilities
            else [
                "Rien n'est partagé avec cette intégration. Dans Notion, ouvrez une page, "
                "menu ••• → Connexions, et ajoutez-la."
            ]
        )
        return ConnectionTestResult(
            account=str(me.get("name") or "Notion"),
            metadata=metadata,
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            await client.get("/users/me")
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        async with self._client() as client:
            found = [item async for item in self._search(client, None, limit=MAX_SCOPE_SCAN + 1)]
        scanned, truncated = found[:MAX_SCOPE_SCAN], len(found) > MAX_SCOPE_SCAN
        shared = {str(item["id"]) for item in scanned}
        options: list[ScopeOption] = []
        for item in scanned:
            parent = _parent(item)
            if parent is not None and parent[1] in shared:
                continue  # beneath something the list already offers
            if len(options) == MAX_SCOPE_OPTIONS:
                return ScopeListing(options=options, truncated=True)
            options.append(
                ScopeOption(
                    key=str(item["id"]),
                    name=_title(item),
                    description="Base de données" if item.get("object") == "database" else "Page",
                    updated_at=parse_timestamp(item.get("last_edited_time")),
                )
            )
        return ScopeListing(options=options, truncated=truncated)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Notion does not read {capability}"
            raise ValueError(msg)
        kind: Literal["page", "database"] = "page" if capability is Capability.PAGES else "database"
        async with self._client() as client:
            tree = _Ancestry(client, self.config.roots)
            found = self._search(client, kind, stop_before=since - EDIT_MARGIN if since else None)
            async for item in found:
                tree.learn(item)
                if not await tree.in_scope(item):
                    continue
                payload: Item = dict(item)
                if capability is Capability.PAGES and not _gone(item):
                    blocks, truncated = await self._blocks(client, str(item["id"]))
                    payload["blocks"] = blocks
                    payload["blocks_truncated"] = truncated
                parent = _parent(item)
                yield record(
                    capability,
                    payload,
                    external_id=str(item["id"]),
                    container=parent[1] if parent else None,
                    updated=item.get("last_edited_time"),
                )

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.token.get_secret_value()
        client = self.http(
            API,
            headers={
                "Accept": "application/json",
                "User-Agent": "LEKA",
                "Authorization": f"Bearer {secret}",
                "Notion-Version": VERSION,
            },
        )
        client.event_hooks = {"request": [Pace(MIN_INTERVAL)], "response": []}
        return VendorHttp(
            client,
            secret=secret,
            refuse=self._refuse,
            page_size=PAGE_SIZE,
            page_size_param="page_size",
            reads_by_post=frozenset({SEARCH}),
        )

    async def _search(
        self,
        client: VendorHttp,
        kind: Literal["page", "database"] | None,
        *,
        stop_before: datetime | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[Item]:
        """What is shared with the integration, most recently edited first,
        following Notion's cursors. `stop_before`: nothing edited before it
        is wanted, and the order makes the first such object the end."""
        body = _search(kind)
        seen: set[str] = set()
        given = 0
        while True:
            answer = (await client.post(SEARCH, body)).json()
            for item in answer.get("results") or []:
                edited = parse_timestamp(item.get("last_edited_time"))
                if stop_before and (edited is None or edited < stop_before):
                    return
                if limit is not None and given == limit:
                    return
                given += 1
                yield item
            cursor = _next_cursor(answer, seen)
            if cursor is None:
                return
            body = {**body, "start_cursor": cursor}

    async def _blocks(self, client: VendorHttp, page_id: str) -> tuple[list[Item], bool]:
        """A page's blocks in reading order, each nested one right after the
        block holding it, to MAX_DEPTH and at most MAX_BLOCKS — and whether
        any were left out."""
        read: list[Item] = []
        truncated = False

        async def walk(block_id: str, depth: int) -> None:
            nonlocal truncated
            children, more = await self._children(client, block_id, MAX_BLOCKS - len(read))
            truncated = truncated or more
            for block in children:
                if len(read) >= MAX_BLOCKS:
                    truncated = True
                    return
                read.append(block)
                if not block.get("has_children") or block.get("type") in SEPARATE:
                    continue
                if depth >= MAX_DEPTH:
                    truncated = True
                else:
                    await walk(str(block["id"]), depth + 1)

        await walk(page_id, 1)
        return read, truncated

    async def _children(
        self, client: VendorHttp, block_id: str, room: int
    ) -> tuple[list[Item], bool]:
        """At most `room` children of a block, and whether more were left."""
        if room <= 0:
            return [], True
        found: list[Item] = []
        seen: set[str] = set()
        params: dict[str, str | int] = {"page_size": PAGE_SIZE}
        while True:
            answer = (await client.get(f"/blocks/{block_id}/children", params=params)).json()
            found.extend(answer.get("results") or [])
            if len(found) >= room:
                return found[:room], len(found) > room or bool(answer.get("has_more"))
            cursor = _next_cursor(answer, seen)
            if cursor is None:
                return found, False
            params = {"page_size": PAGE_SIZE, "start_cursor": cursor}

    async def _require_scope(self, client: VendorHttp) -> None:
        """Every root in scope must be shared with the integration."""
        missing = [root for root in self.config.roots or [] if not await _shared(client, root)]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message="Notion ne partage pas ces pages ou bases avec cette intégration : "
                f"{named}.",
            )

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Notion's refusals, as diagnostics: the `code` of its error body
        first, the HTTP status when it says nothing."""
        secret = self.credentials.token.get_secret_value()
        status, code = response.status_code, _error_code(response)
        if status == 429 or code == "rate_limited":
            return refusal(
                response,
                path,
                secret,
                DiagnosticCode.RATE_LIMITED,
                retry_after=retry_after(response),
            )
        if status == 401 or code == "unauthorized":
            message = "Notion refuse ce token d'intégration."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 403 or code == "restricted_resource":
            message = (
                "Notion refuse la lecture : l'intégration doit avoir la capacité « Read content »."
            )
            return refusal(
                response, path, secret, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        if status == 404 or code == "object_not_found":
            what = missing or "cette page"
            message = f"Notion ne trouve pas {what}, ou ne la partage pas avec cette intégration."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        return refusal(response, path, secret, usual_code(status))


class _Ancestry:
    """Whether an object is beneath one of the roots.

    What each object sits in is learned from the search as the pass goes,
    and what the search did not show is asked of Notion — once per object
    per pass. An ancestor Notion does not share ends the climb: what is
    beneath no root is not read.
    """

    def __init__(self, client: VendorHttp, roots: list[str] | None) -> None:
        self._client = client
        self._roots = set(roots or [])
        self._parents: dict[str, Parent | None] = {}

    def learn(self, item: Mapping[str, Any]) -> None:
        self._parents[str(item["id"])] = _parent(item)

    async def in_scope(self, item: Mapping[str, Any]) -> bool:
        if not self._roots:
            return True
        node, parent = str(item["id"]), _parent(item)
        for _ in range(MAX_ANCESTRY):
            if node in self._roots:
                return True
            if parent is None:
                return False
            kind, node = parent
            parent = None if node in self._roots else await self._parent_of(kind, node)
        return False

    async def _parent_of(self, kind: str, node: str) -> Parent | None:
        if node not in self._parents:
            response = await self._client.get(LOOKUP[kind].format(node), empty=404)
            self._parents[node] = None if response.status_code == 404 else _parent(response.json())
        return self._parents[node]


async def _shared(client: VendorHttp, object_id: str) -> bool:
    """Whether a page or a database is shared with the integration. An id
    asked as the wrong kind is a 400 or a 404, depending on Notion's mood:
    both mean "try the other kind"."""
    for path in ("/pages/{}", "/databases/{}"):
        try:
            response = await client.get(path.format(object_id), empty=404)
        except ConnectorError as error:
            if error.diagnostic.provider_status == 400:
                continue
            raise
        if response.status_code != 404:
            return True
    return False


def _search(
    kind: Literal["page", "database"] | None, page_size: int | None = None
) -> dict[str, object]:
    body: dict[str, object] = {
        "page_size": page_size or PAGE_SIZE,
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
    }
    if kind:
        body["filter"] = {"property": "object", "value": kind}
    return body


def _next_cursor(answer: Mapping[str, Any], seen: set[str]) -> str | None:
    """Where the next page of a listing starts, or None at its end."""
    if not answer.get("has_more"):
        return None
    cursor = answer.get("next_cursor")
    if not cursor or cursor in seen:
        # A cursor Notion already gave: following it would never end.
        raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail="Notion repeated a cursor")
    seen.add(str(cursor))
    return str(cursor)


def _parent(item: Mapping[str, Any]) -> Parent | None:
    """What an object sits in — a page, a database, a block — or None at the
    top of the workspace."""
    parent = item.get("parent")
    if not isinstance(parent, dict):
        return None
    kind = parent.get("type")
    if kind in LOOKUP and parent.get(kind):
        return str(kind), str(parent[kind])
    return None


def _title(item: Mapping[str, Any]) -> str:
    """A database's title, or the page's title property, as plain text."""
    if item.get("object") == "database":
        parts = item.get("title") or []
    else:
        properties = item.get("properties") or {}
        parts = next(
            (
                prop.get("title") or []
                for prop in properties.values()
                if isinstance(prop, dict) and prop.get("type") == "title"
            ),
            [],
        )
    text = "".join(str(part.get("plain_text", "")) for part in parts if isinstance(part, dict))
    return text.strip() or "Sans titre"


def _gone(item: Mapping[str, Any]) -> bool:
    """Archived or in the trash: listed, but with no content to read."""
    return item.get("archived") is True or item.get("in_trash") is True


def _error_code(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("code") or "") if isinstance(body, dict) else ""
