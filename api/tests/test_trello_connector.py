"""The Trello connector against a Trello that is not there (LEKA-346).

httpx.MockTransport stands in for api.trello.com. It checks the other half
of "LEKA reads": every request is a GET, to Trello, with the key and the
token in the Authorization header — never in the URL, which httpx logs.
"""

from __future__ import annotations

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
from leka.connectors.trello import TrelloConfig, TrelloConnector, TrelloCredentials
from leka.connectors.trello import connector as trello_module

TOKEN = "ATTA" + "0123456789abcdef" * 4 + "A1B2C3D4"
KEY = "0123456789abcdef" * 2
EMAIL = "nora@acme.test"

ROADMAP: dict[str, Any] = {
    "id": "5f1e00000000000000000001",
    "shortLink": "AbCd1234",
    "name": "Roadmap",
    "desc": "What ships when",
    "closed": False,
    "dateLastActivity": "2026-09-25T09:00:00.000Z",
    "idOrganization": "org-1",
}
ARCHIVE: dict[str, Any] = {
    "id": "5f1e00000000000000000002",
    "shortLink": "ZzYy9876",
    "name": "Archive",
    "closed": True,
    "idOrganization": "org-1",
}

Answer = object | Callable[[httpx.Request], httpx.Response]


class Trello:
    """A healthy Trello, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.boards = {b["id"]: b for b in (ROADMAP, ARCHIVE)}
        self.cards: dict[str, list[dict[str, Any]]] = {}
        self.answers: dict[str, Answer] = {
            "/1/members/me": {"id": "m-1", "username": "nora", "fullName": "Nora", "email": EMAIL},
            "/1/members/me/boards": self._boards,
            **(overrides or {}),
        }
        self.asked: list[httpx.Request] = []

    def _boards(self, request: httpx.Request) -> httpx.Response:
        which = request.url.params.get("filter")
        found = [b for b in self.boards.values() if which == "all" or not b.get("closed")]
        return httpx.Response(200, json=found)

    def _cards(self, board: str, request: httpx.Request) -> httpx.Response:
        cards = sorted(self.cards.get(board, []), key=lambda c: c["id"], reverse=True)
        before = request.url.params.get("before")
        if before:
            cards = [c for c in cards if c["id"] < before]
        return httpx.Response(200, json=cards[: int(request.url.params.get("limit", 1000))])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads Trello with GETs"
        assert request.url.host == "api.trello.com"
        assert request.headers["authorization"] == (
            f'OAuth oauth_consumer_key="{KEY}", oauth_token="{TOKEN}"'
        )
        path = request.url.path
        assert TOKEN not in str(request.url) and KEY not in str(request.url)
        self.asked.append(request)
        answer = self.answers.get(path)
        if answer is None and path.startswith("/1/boards/"):
            parts = path.split("/")
            board = self.boards.get(parts[3])
            if board is None:
                return httpx.Response(404, text="The requested resource was not found.")
            if path.endswith("/cards/all"):
                return self._cards(parts[3], request)
            return httpx.Response(200, json={**board, "lists": [{"id": "l-1", "name": "Doing"}]})
        if answer is None:
            return httpx.Response(404, text="The requested resource was not found.")
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def params(self, path: str) -> list[dict[str, str]]:
        return [dict(r.url.params) for r in self.asked if r.url.path == path]


def _connector(trello: Trello, **config: Any) -> TrelloConnector:
    return TrelloConnector(
        TrelloConfig.model_validate(config),
        TrelloCredentials(token=SecretStr(TOKEN), api_key=SecretStr(KEY)),
        transport=httpx.MockTransport(trello),
    )


async def _failure(trello: Trello, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(trello, **config).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


def test_trello_is_in_the_catalogue_as_a_project_tool_with_write_only_secrets() -> None:
    manifest = next(m for m in manifests() if m.key == "trello")
    secrets = manifest.credentials_schema.model_json_schema()["properties"]

    assert manifest.category is ConnectorCategory.PROJECT
    assert manifest.capabilities == {Capability.PROJECTS, Capability.ISSUES}
    assert manifest.listed_whole == {Capability.PROJECTS}
    assert list(secrets) == ["token", "api_key"]  # the token first: its hint is stored
    assert all(field["writeOnly"] is True for field in secrets.values())


# ── the configuration ────────────────────────────────────────────────────────


def test_boards_are_kept_as_ids_or_short_links_once() -> None:
    config = TrelloConfig.model_validate(
        {
            "boards": [
                "5F1E00000000000000000001",
                "AbCd1234",
                "https://trello.com/b/AbCd1234/roadmap",
            ]
        }
    )

    assert config.boards == ["5f1e00000000000000000001", "AbCd1234"]


@pytest.mark.parametrize(
    "config",
    [{"boards": []}, {"boards": ["roadmap"]}, {"boards": ["https://evil.test/b/x"]}, {"x": 1}],
)
def test_a_configuration_that_is_not_boards_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TrelloConfig.model_validate(config)


def test_trello_s_token_shape_is_scrubbed_from_any_detail() -> None:
    assert TOKEN not in sanitise(f"token {TOKEN} refused")


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_token_reports_the_member_and_what_it_can_read() -> None:
    trello = Trello()

    result = await _connector(trello).test_connection()

    assert result.account == EMAIL
    assert result.metadata == {"member": "Nora", "boards_visible": 1}
    assert set(result.capabilities) == TrelloConnector.manifest.capabilities
    assert result.warnings == []
    # The member's boards are asked once: Trello limits /members/ hard.
    assert len(trello.params("/1/members/me/boards")) == 1


async def test_a_capability_trello_refuses_is_left_out_not_failed() -> None:
    trello = Trello()
    board = ROADMAP["id"]
    trello.answers[f"/1/boards/{board}/cards/all"] = httpx.Response(
        401, text="unauthorized permission requested"
    )

    result = await _connector(trello).test_connection()

    assert result.capabilities == [Capability.PROJECTS]


async def test_a_token_that_sees_no_open_board_is_told_so() -> None:
    result = await _connector(Trello(), boards=["ZzYy9876"]).test_connection()

    assert result.capabilities == []
    assert result.warnings == ["Aucun tableau ouvert n'est visible avec ce jeton."]


async def test_a_board_in_scope_that_trello_does_not_show_fails_the_test() -> None:
    error = await _failure(Trello(), boards=["AbCd1234", "Nope5678"])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert error.diagnostic.message == "Trello ne montre pas ces tableaux à ce jeton : Nope5678."


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, text="invalid token"), DiagnosticCode.AUTH_INVALID),
        (httpx.Response(401, text="invalid key"), DiagnosticCode.AUTH_INVALID),
        (httpx.Response(401, text="unauthorized"), DiagnosticCode.AUTH_INVALID),
        (
            httpx.Response(401, text="unauthorized permission requested"),
            DiagnosticCode.PERMISSION_DENIED,
        ),
        (httpx.Response(404, text="not found"), DiagnosticCode.NOT_FOUND),
        (httpx.Response(503, text="down"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Trello({"/1/members/me": response}))

    assert error.diagnostic.code is code


async def test_a_refusal_for_the_rate_says_when_the_window_turns() -> None:
    busy = httpx.Response(
        429,
        headers={"x-rate-limit-api-token-interval-ms": "10000"},
        json={"error": "API_TOKEN_LIMIT_EXCEEDED"},
    )

    error = await _failure(Trello({"/1/members/me": busy}))

    assert (error.diagnostic.code, error.diagnostic.retry_after) == (
        DiagnosticCode.RATE_LIMITED,
        10,
    )


async def test_an_echoed_token_is_removed_from_the_detail() -> None:
    error = await _failure(Trello({"/1/members/me": httpx.Response(500, text=f"bad {TOKEN}")}))

    assert TOKEN not in (error.diagnostic.detail or "")


# ── health ───────────────────────────────────────────────────────────────────


async def test_health_reads_what_is_left_of_the_token_s_window() -> None:
    headers = {"x-rate-limit-api-token-max": "100", "x-rate-limit-api-token-remaining": "5"}
    low = httpx.Response(200, json={"id": "m-1"}, headers=headers)

    healthy = await _connector(Trello()).check_health()
    degraded = await _connector(Trello({"/1/members/me": low})).check_health()

    assert healthy.status is HealthStatus.HEALTHY
    assert (degraded.status, degraded.detail) == (HealthStatus.DEGRADED, "quota 5/100")


# ── the scope ────────────────────────────────────────────────────────────────


async def test_the_scope_is_chosen_from_every_board_closed_ones_too() -> None:
    listing = await _connector(Trello()).list_scope()

    assert [(o.key, o.name, o.description) for o in listing.options] == [
        (ROADMAP["id"], "Roadmap", "What ships when"),
        (ARCHIVE["id"], "Archive", "Fermé"),
    ]
    assert listing.options[0].updated_at is not None


async def test_a_listing_too_long_to_offer_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trello_module, "MAX_SCOPE_OPTIONS", 1)

    listing = await _connector(Trello()).list_scope()

    assert [o.key for o in listing.options] == [ROADMAP["id"]]
    assert listing.truncated is True
