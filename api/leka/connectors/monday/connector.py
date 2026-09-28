"""The Monday connector — monday.com, through its GraphQL API.

Monday has one endpoint, POST https://api.monday.com/v2, and speaks only
GraphQL, like Linear. Every document this connector sends is below, as a
constant, and is a `query`: `read_only` refuses a `mutation` or a
`subscription` before it is sent, and a test runs it over every document.
The version of the API is pinned (API-Version), so Monday's next one
cannot change an answer under LEKA.

test_connection: who am I, in which account, may I administer it (`me` —
a warning: LEKA only reads), are the boards in scope there, what can I see
(one page of boards), and — on one board, in scope if a scope is set — can
I read its items.

check_health: `me { id }`. Monday's budget is per minute and says itself
when it runs out; health is healthy or failed.

list_scope: every active board the token sees — boards only, not
subitem boards nor docs, which Monday lists as boards too.

iter_resources: boards, with their groups and columns, whole each pass;
then items, board by board, 100 a page by Monday's cursors, with their
column values and subitems. Monday cannot filter items by their last
update without a rule per board, so an incremental pass reads every item
and keeps those updated since the last pass.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from leka.connectors import graphql
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
from leka.connectors.graphql import errors_of
from leka.connectors.http import (
    Item,
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

API = "https://api.monday.com"
GRAPHQL = "/v2"
API_VERSION = "2026-07"
BOARD_PAGE = 100
ITEM_PAGE = 100  # Monday allows 500; a page of items with every column is heavy
MAX_BOARD_PAGES = 100
MAX_SCOPE_OPTIONS = 1000
# An item's updated_at is written a moment after the change.
UPDATE_MARGIN = timedelta(minutes=2)
BOARD_ID = re.compile(r"^[0-9]{1,20}$")
BOARD_LINK = re.compile(r"\.monday\.com/boards/([0-9]+)")

# ── the documents: queries, nothing else ─────────────────────────────────────

ME = """
query Me {
  me { id name email is_admin is_guest account { id name slug } }
}
"""

HEALTH = """
query Health { me { id } }
"""

BOARD_FIELDS = """
    id name description state board_kind type url updated_at items_count
    workspace { id name }
    owners { id name }
    groups { id title archived }
    columns { id title type }
"""

BOARDS = f"""
query Boards($limit: Int!, $page: Int!) {{
  boards(limit: $limit, page: $page, order_by: created_at) {{ {BOARD_FIELDS} }}
}}
"""

BOARDS_BY_ID = f"""
query BoardsById($ids: [ID!]!, $limit: Int!) {{
  boards(ids: $ids, limit: $limit) {{ {BOARD_FIELDS} }}
}}
"""

ITEM_FIELDS = """
    id name state created_at updated_at url
    group { id title }
    creator { id name }
    parent_item { id }
    column_values { id type text value }
    subitems { id name }
"""

ITEMS = f"""
query Items($board: ID!, $limit: Int!) {{
  boards(ids: [$board]) {{ items_page(limit: $limit) {{ cursor items {{ {ITEM_FIELDS} }} }} }}
}}
"""

NEXT_ITEMS = f"""
query NextItems($cursor: String!, $limit: Int!) {{
  next_items_page(cursor: $cursor, limit: $limit) {{ cursor items {{ {ITEM_FIELDS} }} }}
}}
"""

DOCUMENTS = (ME, HEALTH, BOARDS, BOARDS_BY_ID, ITEMS, NEXT_ITEMS)

# Monday's codes, by what they mean for a source.
AUTH_CODES = frozenset({"UNAUTHORIZED", "UNAUTHORIZEDEXCEPTION"})
FORBIDDEN_CODES = frozenset({"USERUNAUTHORIZEDEXCEPTION", "FORBIDDEN"})
NOT_FOUND_CODES = frozenset({"RESOURCENOTFOUNDEXCEPTION", "INVALIDBOARDIDEXCEPTION"})
BUSY_CODES = frozenset(
    {
        "RATE_LIMIT_EXCEEDED",
        "COMPLEXITY_BUDGET_EXHAUSTED",
        "COMPLEXITYEXCEPTION",
        "MAXCONCURRENCYEXCEEDED",
        "IP_RATE_LIMIT_EXCEEDED",
    }
)


def read_only(document: str) -> str:
    """The document, if it only reads (leka/connectors/graphql.py)."""
    return graphql.read_only(document, "Monday")


def board_id(value: str) -> str:
    """A board's id, from what an admin typed or pasted — "1234567890", or
    https://acme.monday.com/boards/1234567890. Anything else is refused."""
    text = value.strip()
    found = BOARD_LINK.search(text)
    board = found.group(1) if found else text
    if not BOARD_ID.match(board):
        msg = f"{value!r} is not the id or the link of a Monday board"
        raise ValueError(msg)
    return board


class MondayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boards: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Ids or links of the boards to read. Empty: every board the token can see.",
    )

    @field_validator("boards")
    @classmethod
    def _ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(board_id(board) for board in value))


class MondayCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr = Field(
        min_length=20,
        description="A personal API token, from your avatar → Developers → API token.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class MondayConnector(Connector[MondayConfig, MondayCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.MONDAY,
        display_name="Monday",
        category=ConnectorCategory.PROJECT,
        auth_type="token",
        config_schema=MondayConfig,
        credentials_schema=MondayCredentials,
        capabilities=frozenset({Capability.PROJECTS, Capability.ISSUES}),
        # Boards come whole every pass; items are kept by their last update.
        listed_whole=frozenset({Capability.PROJECTS}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            me = dig(await self._query(client, ME), "me") or {}
            metadata: dict[str, object] = {
                "account": dig(me, "account.name"),
                "slug": dig(me, "account.slug"),
            }
            warnings: list[str] = []
            if me.get("is_admin"):
                warnings.append(
                    "Ce token appartient à un administrateur du compte Monday. LEKA ne fait que "
                    "lire : le token d'un membre suffit."
                )
            if self.config.boards:
                chosen = await self._require_scope(client)
            else:
                data = await self._query(client, BOARDS, {"limit": BOARD_PAGE, "page": 1})
                page = data.get("boards") or []
                chosen = [board for board in page if _is_board(board)]
                more = len(page) == BOARD_PAGE
                metadata["boards_visible"] = f"{len(chosen)}+" if more else len(chosen)
            capabilities: list[Capability] = []
            if chosen:
                capabilities.append(Capability.PROJECTS)
                try:
                    await self._query(client, ITEMS, {"board": str(chosen[0]["id"]), "limit": 1})
                    capabilities.append(Capability.ISSUES)
                except ConnectorError:
                    pass  # a capability left out, not a failed test
            else:
                warnings.append("Aucun tableau n'est visible avec ce token.")

        return ConnectionTestResult(
            account=str(me.get("email") or me.get("name") or "Monday"),
            metadata=metadata,
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            await self._query(client, HEALTH)
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        options: list[ScopeOption] = []
        async with self._client() as client:
            async for board in self._boards(client):
                if len(options) == MAX_SCOPE_OPTIONS:
                    return ScopeListing(options=options, truncated=True)
                options.append(
                    ScopeOption(
                        key=str(board["id"]),
                        name=str(board.get("name") or board["id"]),
                        description=_description(board),
                        private=board.get("board_kind") == "private",
                        updated_at=parse_timestamp(board.get("updated_at")),
                    )
                )
        return ScopeListing(options=options)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Monday does not read {capability}"
            raise ValueError(msg)
        async with self._client() as client:
            boards = [board async for board in self._boards(client, self.config.boards)]
            if capability is Capability.PROJECTS:
                for board in boards:
                    yield record(
                        capability,
                        board,
                        external_id=str(board["id"]),
                        container=_id(board.get("workspace")),
                        updated=board.get("updated_at"),
                    )
                return
            wanted = since - UPDATE_MARGIN if since else None
            for board in boards:
                async for item in self._items(client, str(board["id"])):
                    updated = parse_timestamp(item.get("updated_at"))
                    if wanted and updated is not None and updated < wanted:
                        continue
                    yield record(
                        capability,
                        item,
                        external_id=str(item["id"]),
                        container=str(board["id"]),
                        updated=item.get("updated_at"),
                    )

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.token.get_secret_value()
        client = self.http(
            API,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "LEKA",
                "Authorization": secret,
                "API-Version": API_VERSION,
            },
        )
        return VendorHttp(
            client,
            secret=secret,
            refuse=self._refuse,
            page_size=ITEM_PAGE,
            reads_by_post=frozenset({GRAPHQL}),
        )

    async def _query(
        self, client: VendorHttp, document: str, variables: Mapping[str, object] | None = None
    ) -> Any:
        """The `data` of one query, or the diagnostic of what Monday refused."""
        body: dict[str, object] = {"query": read_only(document)}
        if variables:
            body["variables"] = dict(variables)
        response = await client.post(GRAPHQL, body)
        if errors_of(response) or _legacy_error(response):
            raise self._refuse(response, GRAPHQL, "")
        return response.json().get("data") or {}

    async def _boards(
        self, client: VendorHttp, ids: list[str] | None = None
    ) -> AsyncIterator[Item]:
        """The boards — these, or every one the token sees — boards only."""
        if ids:
            data = await self._query(client, BOARDS_BY_ID, {"ids": ids, "limit": len(ids)})
            for board in data.get("boards") or []:
                if _is_board(board):
                    yield board
            return
        for page in range(1, MAX_BOARD_PAGES + 1):
            data = await self._query(client, BOARDS, {"limit": BOARD_PAGE, "page": page})
            found = data.get("boards") or []
            for board in found:
                if _is_board(board):
                    yield board
            if len(found) < BOARD_PAGE:
                return
        raise diagnose(
            DiagnosticCode.PROVIDER_ERROR,
            detail=f"Monday gave more than {MAX_BOARD_PAGES} pages of boards",
        )

    async def _items(self, client: VendorHttp, board: str) -> AsyncIterator[Item]:
        """Every item of a board, following Monday's cursors."""
        data = await self._query(client, ITEMS, {"board": board, "limit": ITEM_PAGE})
        found = dig((data.get("boards") or [{}])[0], "items_page") or {}
        seen: set[str] = set()
        while True:
            for item in found.get("items") or []:
                yield item
            cursor = found.get("cursor")
            if not cursor:
                return
            if cursor in seen:
                # A cursor Monday already gave: following it would never end.
                raise diagnose(DiagnosticCode.PROVIDER_ERROR, detail="Monday repeated a cursor")
            seen.add(str(cursor))
            data = await self._query(client, NEXT_ITEMS, {"cursor": cursor, "limit": ITEM_PAGE})
            found = data.get("next_items_page") or {}

    async def _require_scope(self, client: VendorHttp) -> list[Item]:
        """Every board in scope must be one this token can see. The boards
        found, in the order of the scope."""
        wanted = self.config.boards or []
        found = {str(board["id"]): board async for board in self._boards(client, wanted)}
        missing = [board for board in wanted if board not in found]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"Monday ne montre pas ces tableaux à ce token : {named}.",
            )
        return [found[board] for board in wanted]

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Monday's refusals, as diagnostics: the code of its errors first
        (`extensions.code`, or the older `error_code`), the HTTP status when
        it says nothing."""
        secret = self.credentials.token.get_secret_value()
        codes = _codes(response)
        status = response.status_code
        if codes & BUSY_CODES or status == 429:
            return refusal(
                response, path, secret, DiagnosticCode.RATE_LIMITED, retry_after=_wait(response)
            )
        if codes & AUTH_CODES or status == 401:
            message = "Monday refuse ce token d'API."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if codes & FORBIDDEN_CODES or status == 403:
            return refusal(response, path, secret, DiagnosticCode.PERMISSION_DENIED)
        if codes & NOT_FOUND_CODES or status == 404:
            message = "Monday ne trouve pas ce tableau, ou ce token ne le voit pas."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        if status >= 500:
            return refusal(response, path, secret, DiagnosticCode.PROVIDER_ERROR)
        return refusal(response, path, secret, usual_code(status))


def _is_board(board: Any) -> bool:
    """A board, not a subitem board or a doc, which Monday lists as boards."""
    return isinstance(board, dict) and board.get("type") in (None, "board")


def _id(item: Any) -> str | None:
    return str(item["id"]) if isinstance(item, dict) and item.get("id") else None


def _description(board: Item) -> str | None:
    workspace = dig(board, "workspace.name")
    text = str(board.get("description") or "").strip()
    parts = [str(part) for part in (workspace, text) if part]
    return " · ".join(parts) or None


def _body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _legacy_error(response: httpx.Response) -> bool:
    """Monday's older way of refusing: `error_code` or `error_message`
    beside no `data`."""
    body = _body(response)
    return "data" not in body and bool(body.get("error_code") or body.get("error_message"))


def _codes(response: httpx.Response) -> set[str]:
    codes = {str(dig(error, "extensions.code") or "").upper() for error in errors_of(response)}
    legacy = _body(response).get("error_code")
    if legacy:
        codes.add(str(legacy).upper())
    return codes - {""}


def _wait(response: httpx.Response) -> int | None:
    """Seconds until Monday takes queries again: the error says it
    (`retry_in_seconds`), else Retry-After."""
    for error in errors_of(response):
        for path in ("extensions.retry_in_seconds", "extensions.error_data.retry_in_seconds"):
            seconds = dig(error, path)
            if isinstance(seconds, int | float):
                return int(seconds)
    return retry_after(response)
