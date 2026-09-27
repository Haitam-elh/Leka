"""The Notion connector against a Notion that is not there (LEKA-346).

httpx.MockTransport stands in for api.notion.com. It checks the other half
of "LEKA reads": every request is a GET, or a POST to /search — Notion's one
read by POST — with the integration's secret and the API version pinned.

The stand-in shares a small workspace, newest edited first:

    Wiki (page, top of the workspace)
    ├── Roadmap (page)
    └── Specs (database)
        └── Spec: search (page, a row of Specs)
    Notes (page, top of the workspace)
    Draft (page, beneath a page NOT shared with the integration)
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from leka.connectors import (
    Capability,
    ConnectorCategory,
    ConnectorError,
    DiagnosticCode,
    HealthStatus,
    manifests,
)
from leka.connectors.errors import sanitise
from leka.connectors.notion import NotionConfig, NotionConnector, NotionCredentials
from leka.connectors.notion import connector as notion_module

TOKEN = "ntn_" + "A1b2C3d4E5" * 5


def uid(n: int) -> str:
    return f"{n:08d}-0000-4000-8000-{n:012d}"


WIKI, ROADMAP, SPECS, SPEC_ROW, NOTES, DRAFT, UNSHARED = (uid(n) for n in range(1, 8))


def _text(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "plain_text": value}]


def page(
    object_id: str, title: str, edited: str, parent: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    return {
        "object": "page",
        "id": object_id,
        "created_time": "2026-09-01T08:00:00.000Z",
        "last_edited_time": edited,
        "parent": parent,
        "archived": False,
        "in_trash": False,
        "properties": {"Name": {"id": "title", "type": "title", "title": _text(title)}},
        "url": f"https://www.notion.so/{object_id.replace('-', '')}",
        **extra,
    }


def in_page(object_id: str) -> dict[str, Any]:
    return {"type": "page_id", "page_id": object_id}


TOP = {"type": "workspace", "workspace": True}

OBJECTS: list[dict[str, Any]] = [
    page(ROADMAP, "Roadmap", "2026-09-25T10:00:00.000Z", in_page(WIKI)),
    page(
        SPEC_ROW,
        "Spec: search",
        "2026-09-24T10:00:00.000Z",
        {"type": "database_id", "database_id": SPECS},
    ),
    {
        "object": "database",
        "id": SPECS,
        "title": _text("Specs"),
        "description": _text("Every specification"),
        "last_edited_time": "2026-09-23T10:00:00.000Z",
        "parent": in_page(WIKI),
        "properties": {"Name": {"id": "title", "type": "title", "title": {}}},
        "archived": False,
    },
    page(NOTES, "Notes", "2026-09-22T10:00:00.000Z", TOP),
    page(DRAFT, "Draft", "2026-09-21T10:00:00.000Z", in_page(UNSHARED)),
    page(WIKI, "Wiki", "2026-09-10T10:00:00.000Z", TOP),
]

ME = {
    "object": "user",
    "id": "bot-1",
    "type": "bot",
    "name": "LEKA",
    "bot": {"owner": {"type": "workspace", "workspace": True}, "workspace_name": "Acme"},
}

Answer = httpx.Response | Callable[[httpx.Request], httpx.Response]


def failure(status: int, code: str, headers: dict[str, str] | None = None) -> httpx.Response:
    body = {"object": "error", "status": status, "code": code, "message": code}
    return httpx.Response(status, json=body, headers=headers or {})


def listing(items: list[Any], start: int, size: int) -> dict[str, Any]:
    chunk = items[start : start + size]
    more = start + size < len(items)
    return {
        "object": "list",
        "results": chunk,
        "has_more": more,
        "next_cursor": str(start + size) if more else None,
    }


class Notion:
    """A healthy Notion sharing OBJECTS, unless a route is overridden.

    `blocks` holds each block's children; `block_parents` what a block sits
    in. Records every request as (method, path, body or query)."""

    def __init__(
        self,
        objects: list[dict[str, Any]] | None = None,
        *,
        blocks: dict[str, list[dict[str, Any]]] | None = None,
        block_parents: dict[str, dict[str, Any]] | None = None,
        overrides: dict[str, Answer] | None = None,
    ) -> None:
        self.objects = OBJECTS if objects is None else objects
        self.blocks = blocks or {}
        self.block_parents = block_parents or {}
        self.overrides = overrides or {}
        self.asked: list[tuple[str, str, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.notion.com"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert request.headers["notion-version"] == "2022-06-28"
        path = request.url.path.removeprefix("/v1")
        if request.method == "POST":
            assert path == "/search", "the one read Notion offers only as a POST"
            asked: dict[str, Any] = json.loads(request.content)
        else:
            assert request.method == "GET", "LEKA reads"
            asked = dict(request.url.params)
        self.asked.append((request.method, path, asked))

        override = self.overrides.get(f"{request.method} {path}")
        if override is not None:
            return override(request) if callable(override) else override
        if path == "/users/me":
            return httpx.Response(200, json=ME)
        if path == "/search":
            return httpx.Response(200, json=self._search(asked))
        return self._get(path, asked)

    def _search(self, body: dict[str, Any]) -> dict[str, Any]:
        wanted = (body.get("filter") or {}).get("value")
        assert body["sort"] == {"direction": "descending", "timestamp": "last_edited_time"}
        found = [item for item in self.objects if not wanted or item["object"] == wanted]
        return listing(found, int(body.get("start_cursor") or 0), int(body["page_size"]))

    def _get(self, path: str, query: dict[str, Any]) -> httpx.Response:
        parts = path.strip("/").split("/")
        if parts[0] == "blocks" and len(parts) == 3:
            children = self.blocks.get(parts[1], [])
            start, size = int(query.get("start_cursor") or 0), int(query["page_size"])
            return httpx.Response(200, json=listing(children, start, size))
        if parts[0] == "blocks":
            parent = self.block_parents.get(parts[1])
            if parent is None:
                return failure(404, "object_not_found")
            return httpx.Response(200, json={"object": "block", "id": parts[1], "parent": parent})
        kinds = {"pages": "page", "databases": "database"}
        found = next((item for item in self.objects if item["id"] == parts[1]), None)
        if found is None:
            return failure(404, "object_not_found")
        if found["object"] != kinds[parts[0]]:
            return failure(400, "validation_error")
        return httpx.Response(200, json=found)

    def paths(self, method: str = "GET") -> list[str]:
        return [path for asked_method, path, _ in self.asked if asked_method == method]

    def searches(self) -> list[dict[str, Any]]:
        return [body for method, _, body in self.asked if method == "POST"]


@pytest.fixture(autouse=True)
def _no_pace(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Notion's three requests a second, lifted for the stand-in."""
    monkeypatch.setattr(notion_module, "MIN_INTERVAL", 0.0)
    yield


def _connector(notion: Notion, **config: Any) -> NotionConnector:
    return NotionConnector(
        NotionConfig.model_validate(config),
        NotionCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(notion),
    )


async def _failure(notion: Notion, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(notion, **config).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


# ── what Notion is to LEKA ───────────────────────────────────────────────────


def test_notion_is_in_the_catalogue_as_a_documentation_tool_with_a_write_only_secret() -> None:
    manifest = next(m for m in manifests() if m.key == "notion")
    token = manifest.credentials_schema.model_json_schema()["properties"]["token"]

    assert manifest.category is ConnectorCategory.DOCS
    assert manifest.capabilities == {Capability.PAGES, Capability.DATABASES}
    assert manifest.read_only is True
    assert token["writeOnly"] is True


# ── the configuration ────────────────────────────────────────────────────────


def test_a_root_is_kept_as_notion_writes_an_id_however_it_was_given() -> None:
    compact = "1a2b3c4d5e6f40718293a4b5c6d7e8f9"
    dashed = "1a2b3c4d-5e6f-4071-8293-a4b5c6d7e8f9"

    config = NotionConfig.model_validate(
        {
            "roots": [
                compact,
                dashed.upper(),
                f"https://www.notion.so/acme/Road-map-{compact}?v=abc#top",
                f"https://www.notion.so/{compact}/",
            ]
        }
    )

    assert config.roots == [dashed]


@pytest.mark.parametrize(
    "config",
    [
        {"roots": []},
        {"roots": ["roadmap"]},
        {"roots": ["1a2b3c4d"]},
        {"roots": ["https://www.notion.so/acme/Roadmap"]},
        {"site": "acme"},
    ],
)
def test_a_configuration_that_is_not_notion_ids_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        NotionConfig.model_validate(config)


def test_the_secret_never_shows_in_a_repr() -> None:
    credentials = NotionCredentials(token=SecretStr(TOKEN))

    assert TOKEN not in repr(credentials)
    assert TOKEN not in str(credentials.model_dump())


@pytest.mark.parametrize("secret", [TOKEN, "secret_" + "Zz9" * 15])
def test_a_notion_secret_is_scrubbed_from_any_detail(secret: str) -> None:
    assert secret not in sanitise(f"integration {secret} refused")


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_secret_reports_the_integration_and_what_it_can_read() -> None:
    notion = Notion()

    result = await _connector(notion).test_connection()

    assert result.account == "LEKA"
    assert result.metadata == {"workspace": "Acme", "pages_visible": 5}
    assert result.capabilities == [Capability.PAGES, Capability.DATABASES]
    assert result.warnings == []
    # Only reads: /users/me, then two searches.
    assert notion.paths() == ["/users/me"]
    assert [body["filter"]["value"] for body in notion.searches()] == ["page", "database"]


async def test_more_pages_than_one_answer_holds_are_counted_as_such(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notion_module, "PAGE_SIZE", 2)

    result = await _connector(Notion()).test_connection()

    assert result.metadata["pages_visible"] == "2+"


async def test_an_integration_nothing_is_shared_with_is_told_how_to_share() -> None:
    result = await _connector(Notion(objects=[])).test_connection()

    assert result.capabilities == []
    assert len(result.warnings) == 1
    assert "Connexions" in result.warnings[0]


async def test_a_root_in_scope_is_looked_up_as_a_page_then_as_a_database() -> None:
    notion = Notion()

    await _connector(notion, roots=[WIKI, SPECS]).test_connection()

    assert notion.paths() == [
        "/users/me",
        f"/pages/{WIKI}",
        f"/pages/{SPECS}",  # a 400: a database asked as a page
        f"/databases/{SPECS}",
    ]


async def test_a_root_notion_does_not_share_fails_the_test_naming_it() -> None:
    error = await _failure(Notion(), roots=[WIKI, UNSHARED])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert error.diagnostic.message == (
        f"Notion ne partage pas ces pages ou bases avec cette intégration : {UNSHARED}."
    )


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (failure(401, "unauthorized"), DiagnosticCode.AUTH_INVALID),
        (failure(403, "restricted_resource"), DiagnosticCode.PERMISSION_DENIED),
        (failure(404, "object_not_found"), DiagnosticCode.NOT_FOUND),
        (failure(502, "internal_server_error"), DiagnosticCode.PROVIDER_ERROR),
        (failure(503, "service_unavailable"), DiagnosticCode.PROVIDER_ERROR),
        (httpx.Response(418, text="teapot"), DiagnosticCode.UNKNOWN),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Notion(overrides={"GET /users/me": response}))

    assert error.diagnostic.code is code


async def test_a_missing_read_content_capability_says_so() -> None:
    notion = Notion(overrides={"POST /search": failure(403, "restricted_resource")})

    error = await _failure(notion)

    assert error.diagnostic.code is DiagnosticCode.PERMISSION_DENIED
    assert "Read content" in error.diagnostic.message


async def test_an_exhausted_quota_says_when_to_come_back() -> None:
    busy = failure(429, "rate_limited", headers={"retry-after": "7"})

    error = await _failure(Notion(overrides={"GET /users/me": busy}))

    assert error.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert error.diagnostic.retry_after == 7


async def test_a_notion_that_does_not_answer() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    error = await _failure(Notion(overrides={"GET /users/me": slow}))

    assert error.diagnostic.code is DiagnosticCode.TIMEOUT


async def test_an_echoed_secret_is_removed_from_the_detail() -> None:
    echo = httpx.Response(500, text=f"Internal error for Bearer {TOKEN}")

    error = await _failure(Notion(overrides={"GET /users/me": echo}))

    assert TOKEN not in (error.diagnostic.detail or "")


# ── health ───────────────────────────────────────────────────────────────────


async def test_health_is_one_light_call() -> None:
    notion = Notion()

    health = await _connector(notion).check_health()

    assert health.status is HealthStatus.HEALTHY
    assert notion.paths() == ["/users/me"]


async def test_health_fails_like_a_test_when_the_secret_is_revoked() -> None:
    revoked = Notion(overrides={"GET /users/me": failure(401, "unauthorized")})

    with pytest.raises(ConnectorError) as caught:
        await _connector(revoked).check_health()

    assert caught.value.diagnostic.code is DiagnosticCode.AUTH_INVALID


# ── the scope ────────────────────────────────────────────────────────────────


async def test_the_scope_offers_the_tops_of_what_is_shared() -> None:
    notion = Notion()

    listing_ = await _connector(notion, roots=[NOTES]).list_scope()

    # Roadmap, Specs and its row are beneath Wiki, which is offered; Draft
    # is beneath a page the integration cannot see, so it is a top.
    assert [(o.key, o.name, o.description) for o in listing_.options] == [
        (NOTES, "Notes", "Page"),
        (DRAFT, "Draft", "Page"),
        (WIKI, "Wiki", "Page"),
    ]
    assert listing_.truncated is False
    assert listing_.options[0].updated_at is not None
    # Both kinds, in one search: no filter.
    assert "filter" not in notion.searches()[0]


async def test_a_shared_database_at_the_top_is_offered_as_one() -> None:
    specs = next(item for item in OBJECTS if item["id"] == SPECS)
    alone = {**specs, "parent": TOP}

    listing_ = await _connector(Notion(objects=[alone])).list_scope()

    assert [(o.key, o.name, o.description) for o in listing_.options] == [
        (SPECS, "Specs", "Base de données")
    ]


async def test_a_workspace_too_large_to_look_through_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notion_module, "MAX_SCOPE_SCAN", 2)

    listing_ = await _connector(Notion()).list_scope()

    assert listing_.truncated is True


async def test_a_listing_too_long_to_offer_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_module, "MAX_SCOPE_OPTIONS", 1)

    listing_ = await _connector(Notion()).list_scope()

    assert [o.key for o in listing_.options] == [NOTES]
    assert listing_.truncated is True


async def test_an_untitled_page_is_named_so() -> None:
    untitled = page(NOTES, "", "2026-09-22T10:00:00.000Z", TOP)

    listing_ = await _connector(Notion(objects=[untitled])).list_scope()

    assert listing_.options[0].name == "Sans titre"


# ── Notion's pace ────────────────────────────────────────────────────────────


async def test_requests_keep_to_notion_s_pace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_module, "MIN_INTERVAL", 0.05)
    started = time.monotonic()

    await _connector(Notion()).test_connection()  # three requests

    assert time.monotonic() - started >= 0.1
