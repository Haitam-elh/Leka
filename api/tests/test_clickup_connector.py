"""The ClickUp connector against a ClickUp that is not there (LEKA-346).

httpx.MockTransport stands in for api.clickup.com. It checks the other half
of "LEKA reads": every request is a GET, to ClickUp, with the personal
token as it is.
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
from leka.connectors.clickup import ClickUpConfig, ClickUpConnector, ClickUpCredentials
from leka.connectors.clickup import connector as clickup_module
from leka.connectors.errors import sanitise

TOKEN = "pk_81234567_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
EMAIL = "nora@acme.test"
PREFIX = "/api/v2"

ACME = {
    "id": "9001",
    "name": "Acme",
    "members": [{"user": {"id": 7, "role": 3}}, {"user": {"id": 8, "role": 1}}],
}
PRODUCT = {"id": "901", "name": "Product", "private": False}
OPS = {"id": "902", "name": "Ops", "private": True}

Answer = object | Callable[[httpx.Request], httpx.Response]


def ecode(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"err": code.lower(), "ECODE": code})


class ClickUp:
    """A healthy ClickUp, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.answers: dict[str, Answer] = {
            "/user": {"user": {"id": 7, "username": "nora", "email": EMAIL}},
            "/team": {"teams": [ACME]},
            "/team/9001/space": {"spaces": [PRODUCT, OPS]},
            "/space/901/folder": {
                "folders": [{"id": "f-1", "name": "Q4", "lists": [{"id": "l-1", "name": "Launch"}]}]
            },
            "/space/901/list": {"lists": [{"id": "l-2", "name": "Backlog"}]},
            "/space/902/folder": {"folders": []},
            "/space/902/list": {"lists": [{"id": "l-3", "name": "Runbooks"}]},
            "/team/9001/task": {"tasks": [], "last_page": True},
            **(overrides or {}),
        }
        self.asked: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads ClickUp with GETs"
        assert request.url.host == "api.clickup.com"
        assert request.headers["authorization"] == TOKEN
        self.asked.append(request)
        answer = self.answers.get(request.url.path.removeprefix(PREFIX))
        if answer is None:
            return ecode(404, "ITEM_015")
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def requests(self, path: str) -> list[httpx.Request]:
        return [r for r in self.asked if r.url.path.removeprefix(PREFIX) == path]


def _connector(clickup: ClickUp, **config: Any) -> ClickUpConnector:
    return ClickUpConnector(
        ClickUpConfig.model_validate(config),
        ClickUpCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(clickup),
    )


async def _failure(clickup: ClickUp, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(clickup, **config).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


def test_clickup_is_in_the_catalogue_as_a_project_tool_with_a_write_only_token() -> None:
    manifest = next(m for m in manifests() if m.key == "clickup")
    token = manifest.credentials_schema.model_json_schema()["properties"]["token"]

    assert manifest.category is ConnectorCategory.PROJECT
    assert manifest.capabilities == {Capability.PROJECTS, Capability.ISSUES}
    assert manifest.listed_whole == {Capability.PROJECTS}
    assert token["writeOnly"] is True


def test_spaces_are_kept_as_ids_once() -> None:
    assert ClickUpConfig.model_validate({"spaces": ["901", " 902", "901"]}).spaces == [
        "901",
        "902",
    ]


@pytest.mark.parametrize("config", [{"spaces": []}, {"spaces": ["Product"]}, {"team": "1"}])
def test_a_configuration_that_is_not_spaces_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ClickUpConfig.model_validate(config)


def test_clickup_s_token_shape_is_scrubbed_from_any_detail() -> None:
    assert TOKEN not in sanitise(f"token {TOKEN} refused")


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_token_reports_the_account_and_what_it_can_read() -> None:
    clickup = ClickUp()

    result = await _connector(clickup).test_connection()

    assert result.account == EMAIL
    assert result.metadata == {"workspaces": ["Acme"], "spaces_visible": 2}
    assert set(result.capabilities) == ClickUpConnector.manifest.capabilities
    assert result.warnings == []
    probe = clickup.requests("/team/9001/task")[0]
    assert probe.url.params.get_list("space_ids[]") == ["901"]


async def test_an_owner_s_token_is_accepted_with_a_warning() -> None:
    owner = {"user": {"id": 8, "email": "boss@acme.test"}}

    result = await _connector(ClickUp({"/user": owner})).test_connection()

    assert len(result.warnings) == 1
    assert "administrateur" in result.warnings[0]


async def test_the_probes_read_a_space_in_scope() -> None:
    clickup = ClickUp()

    await _connector(clickup, spaces=["902"]).test_connection()

    assert clickup.requests("/space/902/list")
    assert clickup.requests("/team/9001/task")[0].url.params.get_list("space_ids[]") == ["902"]


async def test_a_capability_clickup_refuses_is_left_out_not_failed() -> None:
    result = await _connector(
        ClickUp({"/team/9001/task": ecode(403, "ACCESS_083")})
    ).test_connection()

    assert result.capabilities == [Capability.PROJECTS]


async def test_a_token_that_sees_no_space_is_told_so() -> None:
    result = await _connector(ClickUp({"/team/9001/space": {"spaces": []}})).test_connection()

    assert result.capabilities == []
    assert result.warnings == ["Aucun espace (Space) n'est visible avec ce token."]


async def test_a_space_in_scope_that_clickup_does_not_show_fails_the_test() -> None:
    error = await _failure(ClickUp(), spaces=["901", "999"])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert error.diagnostic.message == "ClickUp ne montre pas ces espaces à ce token : 999."


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (ecode(401, "OAUTH_019"), DiagnosticCode.AUTH_INVALID),
        (ecode(401, "OAUTH_027"), DiagnosticCode.PERMISSION_DENIED),
        (ecode(401, "OAUTH_041"), DiagnosticCode.PERMISSION_DENIED),
        (ecode(403, "ACCESS_083"), DiagnosticCode.PERMISSION_DENIED),
        (ecode(404, "ITEM_015"), DiagnosticCode.NOT_FOUND),
        (httpx.Response(502, text="bad gateway"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(ClickUp({"/user": response}))

    assert error.diagnostic.code is code


async def test_an_exhausted_quota_says_when_to_come_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("leka.connectors.http.time.time", lambda: 1_790_000_000)
    busy = httpx.Response(429, headers={"x-ratelimit-reset": "1790000042"}, json={})

    error = await _failure(ClickUp({"/user": busy}))

    assert (error.diagnostic.code, error.diagnostic.retry_after) == (
        DiagnosticCode.RATE_LIMITED,
        42,
    )


async def test_an_echoed_token_is_removed_from_the_detail() -> None:
    error = await _failure(ClickUp({"/user": httpx.Response(500, text=f"bad {TOKEN}")}))

    assert TOKEN not in (error.diagnostic.detail or "")


# ── health ───────────────────────────────────────────────────────────────────


async def test_health_reads_the_requests_left_in_the_minute() -> None:
    headers = {"x-ratelimit-limit": "100", "x-ratelimit-remaining": "4"}
    low = httpx.Response(200, json={"user": {"id": 7}}, headers=headers)

    healthy = await _connector(ClickUp()).check_health()
    degraded = await _connector(ClickUp({"/user": low})).check_health()

    assert healthy.status is HealthStatus.HEALTHY
    assert (degraded.status, degraded.detail) == (HealthStatus.DEGRADED, "quota 4/100")


# ── the scope ────────────────────────────────────────────────────────────────


async def test_the_scope_is_chosen_from_every_space_of_every_workspace() -> None:
    listing = await _connector(ClickUp(), spaces=["902"]).list_scope()

    assert [(o.key, o.name, o.description, o.private) for o in listing.options] == [
        ("901", "Product", "Acme", False),
        ("902", "Ops", "Acme", True),
    ]


async def test_a_listing_too_long_to_offer_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clickup_module, "MAX_SCOPE_OPTIONS", 1)

    listing = await _connector(ClickUp()).list_scope()

    assert [o.key for o in listing.options] == ["901"]
    assert listing.truncated is True
