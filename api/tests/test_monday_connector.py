"""The Monday connector against a Monday that is not there (LEKA-346).

httpx.MockTransport stands in for api.monday.com. Monday speaks GraphQL
through POST only, so the stand-in checks the other half of "LEKA reads":
every request is a POST to /v2, carrying a `query` — never a mutation —
with the token configured and the API version pinned.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
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
from leka.connectors.monday import MondayConfig, MondayConnector, MondayCredentials
from leka.connectors.monday import connector as monday_module
from leka.connectors.monday.connector import API_VERSION, DOCUMENTS, read_only

TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjEyMzQ1Njc4OSwiYWFpIjoxMX0.Abcdefghijklmnop0123"
EMAIL = "nora@acme.test"

ROADMAP: dict[str, Any] = {
    "id": "111",
    "name": "Roadmap",
    "description": "What ships when",
    "type": "board",
    "board_kind": "public",
    "updated_at": "2026-09-25T09:00:00Z",
    "workspace": {"id": "7", "name": "Product"},
}
SECRET: dict[str, Any] = {"id": "222", "name": "Hiring", "type": "board", "board_kind": "private"}
SUBITEMS: dict[str, Any] = {"id": "333", "name": "Subitems of Roadmap", "type": "sub_items_board"}

Answer = object | Callable[[dict[str, Any]], httpx.Response]


def data(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"data": body})


def refused(code: str, status: int = 200, **extensions: Any) -> httpx.Response:
    body = {"errors": [{"message": code, "extensions": {"code": code, **extensions}}]}
    return httpx.Response(status, json=body)


class Monday:
    """A healthy Monday, unless an operation is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.boards = [ROADMAP, SECRET, SUBITEMS]
        self.items: dict[str, list[dict[str, Any]]] = {}
        self.answers: dict[str, Answer] = {
            "Me": data(
                {
                    "me": {
                        "id": "1",
                        "name": "Nora",
                        "email": EMAIL,
                        "is_admin": False,
                        "account": {"id": "9", "name": "Acme", "slug": "acme"},
                    }
                }
            ),
            "Health": data({"me": {"id": "1"}}),
            "Boards": self._boards,
            "BoardsById": self._boards_by_id,
            "Items": self._items,
            **(overrides or {}),
        }
        self.asked: list[tuple[str, dict[str, Any]]] = []

    def _boards(self, variables: dict[str, Any]) -> httpx.Response:
        start = (variables["page"] - 1) * variables["limit"]
        return data({"boards": self.boards[start : start + variables["limit"]]})

    def _boards_by_id(self, variables: dict[str, Any]) -> httpx.Response:
        return data({"boards": [b for b in self.boards if b["id"] in variables["ids"]]})

    def _items(self, variables: dict[str, Any]) -> httpx.Response:
        found = self.items.get(variables["board"], [])
        return data({"boards": [{"items_page": {"cursor": None, "items": found}}]})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert (request.method, request.url.host, request.url.path) == (
            "POST",
            "api.monday.com",
            "/v2",
        ), "LEKA reads Monday through its one GraphQL endpoint"
        assert request.headers["authorization"] == TOKEN
        assert request.headers["api-version"] == API_VERSION
        body = json.loads(request.content)
        document: str = body["query"]
        assert document.startswith("query") and "mutation" not in document, "LEKA reads"
        found = re.match(r"query\s+(\w+)", document)
        assert found is not None
        operation, variables = found.group(1), body.get("variables") or {}
        self.asked.append((operation, variables))
        answer = self.answers[operation]
        if callable(answer):
            response: httpx.Response = answer(variables)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def variables(self, operation: str) -> list[dict[str, Any]]:
        return [variables for name, variables in self.asked if name == operation]


def _connector(monday: Monday, **config: Any) -> MondayConnector:
    return MondayConnector(
        MondayConfig.model_validate(config),
        MondayCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(monday),
    )


async def _failure(monday: Monday, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(monday, **config).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


# ── LEKA only reads ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("document", DOCUMENTS)
def test_every_document_sent_to_monday_is_a_query(document: str) -> None:
    assert read_only(document).startswith("query")


@pytest.mark.parametrize(
    "document",
    ["mutation { delete_item(item_id: 1) { id } }", "query A { me { id } }\nmutation B { x }"],
)
def test_a_document_that_could_write_is_refused(document: str) -> None:
    with pytest.raises(ValueError, match="Monday queries only"):
        read_only(document)


def test_monday_is_in_the_catalogue_as_a_project_tool_with_a_write_only_token() -> None:
    manifest = next(m for m in manifests() if m.key == "monday")
    token = manifest.credentials_schema.model_json_schema()["properties"]["token"]

    assert manifest.category is ConnectorCategory.PROJECT
    assert manifest.capabilities == {Capability.PROJECTS, Capability.ISSUES}
    assert manifest.listed_whole == {Capability.PROJECTS}
    assert token["writeOnly"] is True


# ── the configuration ────────────────────────────────────────────────────────


def test_boards_are_kept_as_ids_once_whether_typed_or_pasted() -> None:
    config = MondayConfig.model_validate(
        {"boards": ["111", " 111", "https://acme.monday.com/boards/222/views/9"]}
    )

    assert config.boards == ["111", "222"]


@pytest.mark.parametrize(
    "config",
    [{"boards": []}, {"boards": ["Roadmap"]}, {"boards": ["https://evil.test/x/1"]}, {"x": 1}],
)
def test_a_configuration_that_is_not_boards_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MondayConfig.model_validate(config)


def test_a_json_web_token_is_scrubbed_from_any_detail() -> None:
    assert TOKEN not in sanitise(f"token {TOKEN} refused")


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_token_reports_the_account_and_what_it_can_read() -> None:
    monday = Monday()

    result = await _connector(monday).test_connection()

    assert result.account == EMAIL
    assert result.metadata == {"account": "Acme", "slug": "acme", "boards_visible": 2}
    assert set(result.capabilities) == MondayConnector.manifest.capabilities
    assert result.warnings == []
    assert monday.variables("Items") == [{"board": "111", "limit": 1}]


async def test_an_admin_s_token_is_accepted_with_a_warning() -> None:
    admin = data({"me": {"id": "1", "email": EMAIL, "is_admin": True, "account": {}}})

    result = await _connector(Monday({"Me": admin})).test_connection()

    assert len(result.warnings) == 1
    assert "administrateur" in result.warnings[0]


async def test_the_probe_reads_a_board_in_scope() -> None:
    monday = Monday()

    await _connector(monday, boards=["222"]).test_connection()

    assert monday.variables("BoardsById")[0]["ids"] == ["222"]
    assert monday.variables("Items")[0]["board"] == "222"


async def test_a_capability_monday_refuses_is_left_out_not_failed() -> None:
    forbidden = refused("UserUnauthorizedException", status=403)

    result = await _connector(Monday({"Items": forbidden})).test_connection()

    assert result.capabilities == [Capability.PROJECTS]


async def test_a_token_that_sees_no_board_is_told_so() -> None:
    result = await _connector(Monday({"Boards": data({"boards": []})})).test_connection()

    assert result.capabilities == []
    assert result.warnings == ["Aucun tableau n'est visible avec ce token."]


async def test_a_board_in_scope_that_monday_does_not_show_fails_the_test() -> None:
    error = await _failure(Monday(), boards=["111", "333", "999"])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert error.diagnostic.message == "Monday ne montre pas ces tableaux à ce token : 333, 999."


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            httpx.Response(401, json={"errors": [{"message": "Unauthorized"}]}),
            DiagnosticCode.AUTH_INVALID,
        ),
        (
            httpx.Response(200, json={"error_code": "Unauthorized", "status_code": 401}),
            DiagnosticCode.AUTH_INVALID,
        ),
        (refused("UserUnauthorizedException", status=403), DiagnosticCode.PERMISSION_DENIED),
        (refused("ResourceNotFoundException", status=404), DiagnosticCode.NOT_FOUND),
        (refused("InvalidBoardIdException"), DiagnosticCode.NOT_FOUND),
        (httpx.Response(500, text="Internal Server Error"), DiagnosticCode.PROVIDER_ERROR),
        (refused("SomethingNew"), DiagnosticCode.UNKNOWN),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Monday({"Me": response}))

    assert error.diagnostic.code is code


@pytest.mark.parametrize(
    "response",
    [
        refused("COMPLEXITY_BUDGET_EXHAUSTED", status=429, retry_in_seconds=21),
        refused("RATE_LIMIT_EXCEEDED", error_data={"retry_in_seconds": 21}),
        httpx.Response(429, headers={"retry-after": "21"}, json={"errors": [{"message": "x"}]}),
    ],
)
async def test_an_exhausted_budget_says_when_to_come_back(response: httpx.Response) -> None:
    error = await _failure(Monday({"Me": response}))

    assert (error.diagnostic.code, error.diagnostic.retry_after) == (
        DiagnosticCode.RATE_LIMITED,
        21,
    )


async def test_an_echoed_token_is_removed_from_the_detail() -> None:
    error = await _failure(Monday({"Me": httpx.Response(500, text=f"bad {TOKEN}")}))

    assert TOKEN not in (error.diagnostic.detail or "")


# ── health ───────────────────────────────────────────────────────────────────


async def test_health_is_monday_answering() -> None:
    assert (await _connector(Monday()).check_health()).status is HealthStatus.HEALTHY


async def test_health_fails_like_a_test_when_the_token_is_revoked() -> None:
    revoked = Monday({"Health": httpx.Response(401, json={"errors": []})})

    with pytest.raises(ConnectorError) as caught:
        await _connector(revoked).check_health()

    assert caught.value.diagnostic.code is DiagnosticCode.AUTH_INVALID


# ── the scope ────────────────────────────────────────────────────────────────


async def test_the_scope_is_chosen_from_boards_only() -> None:
    listing = await _connector(Monday()).list_scope()

    assert [(o.key, o.name, o.description, o.private) for o in listing.options] == [
        ("111", "Roadmap", "Product · What ships when", False),
        ("222", "Hiring", None, True),
    ]


async def test_boards_are_followed_across_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monday_module, "BOARD_PAGE", 2)
    monday = Monday()

    listing = await _connector(monday).list_scope()

    assert [o.key for o in listing.options] == ["111", "222"]
    assert [v["page"] for v in monday.variables("Boards")] == [1, 2]


async def test_a_listing_too_long_to_offer_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monday_module, "MAX_SCOPE_OPTIONS", 1)

    listing = await _connector(Monday()).list_scope()

    assert [o.key for o in listing.options] == ["111"]
    assert listing.truncated is True
