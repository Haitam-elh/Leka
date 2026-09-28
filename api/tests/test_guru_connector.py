"""The Guru connector against a Guru that is not there (LEKA-346).

httpx.MockTransport stands in for api.getguru.com. It checks the other half
of "LEKA reads": every request is a GET, to Guru, with the username and
the token as HTTP Basic.
"""

from __future__ import annotations

import base64
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
from leka.connectors.guru import GuruConfig, GuruConnector, GuruCredentials

TOKEN = "d3b07384-d9a0-4c9b-8f6a-" + "0123456789ab" * 2
USERNAME = "leka@acme.test"
PREFIX = "/api/v1"
PAGES = "https://api.getguru.com/api/v1/search/query"

ONBOARDING: dict[str, Any] = {"id": "c-onboard", "name": "Onboarding", "description": "Day one"}
SALES: dict[str, Any] = {"id": "c-sales", "name": "Sales"}

Answer = object | Callable[[httpx.Request], httpx.Response]


def card(number: int, collection: str = "c-onboard", modified: str = "") -> dict[str, Any]:
    return {
        "id": f"card-{number}",
        "preferredPhrase": f"Card {number}",
        "content": f"<p>Card {number}</p>",
        "lastModified": modified or "2026-09-21T12:05:00.000+0000",
        "collection": {"id": collection, "name": collection},
    }


class Guru:
    """A healthy Guru, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.cards = [card(1), card(2, "c-sales")]
        self.answers: dict[str, Answer] = {
            "/whoami": {"email": USERNAME, "team": {"name": "Acme"}},
            "/collections": [ONBOARDING, SALES],
            "/search/query": self._search,
            **(overrides or {}),
        }
        self.asked: list[httpx.Request] = []

    def _search(self, request: httpx.Request) -> httpx.Response:
        size = int(request.url.params.get("maxResults", 50))
        start = int(request.url.params.get("token", 0))
        found = self.cards[start : start + size]
        headers = {}
        if start + size < len(self.cards):
            link = f"{PAGES}?token={start + size}&maxResults={size}"
            headers["link"] = f'< {link} >; rel="next-page"'
        return httpx.Response(200, json=found, headers=headers)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads Guru with GETs"
        assert request.url.host == "api.getguru.com"
        pair = base64.b64encode(f"{USERNAME}:{TOKEN}".encode()).decode()
        assert request.headers["authorization"] == f"Basic {pair}"
        self.asked.append(request)
        answer = self.answers.get(request.url.path.removeprefix(PREFIX))
        if answer is None:
            return httpx.Response(404, json={"description": "Not found"})
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def params(self, path: str) -> list[dict[str, str]]:
        return [dict(r.url.params) for r in self.asked if r.url.path.removeprefix(PREFIX) == path]


def _connector(guru: Guru, **config: Any) -> GuruConnector:
    return GuruConnector(
        GuruConfig.model_validate(config),
        GuruCredentials(token=SecretStr(TOKEN), username=USERNAME),
        transport=httpx.MockTransport(guru),
    )


async def _failure(guru: Guru, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(guru, **config).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


def test_guru_is_in_the_catalogue_as_a_documentation_tool_with_a_write_only_token() -> None:
    manifest = next(m for m in manifests() if m.key == "guru")
    secrets = manifest.credentials_schema.model_json_schema()["properties"]

    assert manifest.category is ConnectorCategory.DOCS
    assert manifest.capabilities == {Capability.SPACES, Capability.PAGES}
    assert manifest.listed_whole == {Capability.SPACES}
    assert list(secrets) == ["token", "username"]  # the token first: its hint is stored
    assert secrets["token"]["writeOnly"] is True


def test_collections_are_kept_in_small_letters_once() -> None:
    config = GuruConfig.model_validate({"collections": ["C-Onboard", "c-onboard "]})

    assert config.collections == ["c-onboard"]


@pytest.mark.parametrize(
    "config", [{"collections": []}, {"collections": ["a b"]}, {"collections": ["../x"]}]
)
def test_a_configuration_that_is_not_collections_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GuruConfig.model_validate(config)


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_token_reports_the_account_and_what_it_can_read() -> None:
    result = await _connector(Guru()).test_connection()

    assert result.account == USERNAME
    assert result.metadata == {"team": "Acme", "collections_visible": 2}
    assert set(result.capabilities) == GuruConnector.manifest.capabilities
    assert result.warnings == []


async def test_a_collection_token_is_known_by_its_collection() -> None:
    collection = {"collection": {"id": "c-onboard", "name": "Onboarding"}}

    result = await _connector(Guru({"/whoami": collection})).test_connection()

    assert result.account == "Onboarding"


async def test_a_search_guru_refuses_leaves_the_cards_out() -> None:
    forbidden = httpx.Response(403, json={"description": "Forbidden"})

    result = await _connector(Guru({"/search/query": forbidden})).test_connection()

    assert result.capabilities == [Capability.SPACES]


async def test_a_token_that_sees_no_collection_is_told_so() -> None:
    result = await _connector(Guru({"/collections": []})).test_connection()

    assert Capability.SPACES not in result.capabilities
    assert result.warnings == ["Aucune collection n'est visible avec ce token."]


async def test_a_collection_in_scope_guru_does_not_show_fails_the_test() -> None:
    error = await _failure(Guru(), collections=["c-onboard", "c-legal"])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert error.diagnostic.message == "Guru ne montre pas ces collections à ce token : c-legal."


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={}), DiagnosticCode.AUTH_INVALID),
        (httpx.Response(403, json={}), DiagnosticCode.PERMISSION_DENIED),
        (httpx.Response(404, json={}), DiagnosticCode.NOT_FOUND),
        (httpx.Response(503, text="down"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Guru({"/whoami": response}))

    assert error.diagnostic.code is code


async def test_a_refusal_for_the_rate_says_when_to_come_back() -> None:
    busy = httpx.Response(429, headers={"retry-after": "12"}, json={})

    error = await _failure(Guru({"/whoami": busy}))

    assert (error.diagnostic.code, error.diagnostic.retry_after) == (
        DiagnosticCode.RATE_LIMITED,
        12,
    )


async def test_an_echoed_token_is_removed_from_the_detail() -> None:
    error = await _failure(Guru({"/whoami": httpx.Response(500, text=f"bad {TOKEN}")}))

    assert TOKEN not in (error.diagnostic.detail or "")


# ── health, the scope ────────────────────────────────────────────────────────


async def test_health_is_guru_answering() -> None:
    assert (await _connector(Guru()).check_health()).status is HealthStatus.HEALTHY


async def test_the_scope_is_chosen_from_every_collection() -> None:
    listing = await _connector(Guru()).list_scope()

    assert [(o.key, o.name, o.description) for o in listing.options] == [
        ("c-onboard", "Onboarding", "Day one"),
        ("c-sales", "Sales", None),
    ]
