"""The Asana connector against an Asana that is not there (LEKA-346).

httpx.MockTransport stands in for app.asana.com. It checks the other half
of "LEKA reads": every request is a GET, to Asana, with the token as Bearer.
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
from leka.connectors.asana import AsanaConfig, AsanaConnector, AsanaCredentials
from leka.connectors.asana import connector as asana_module
from leka.connectors.errors import sanitise

TOKEN = "2/1204567890123456/1209876543210987:" + "0123456789abcdef" * 2
EMAIL = "nora@acme.test"
PREFIX = "/api/1.0"

ACME = {"gid": "100", "name": "Acme"}
LABS = {"gid": "200", "name": "Acme Labs"}
LAUNCH = {
    "gid": "1001",
    "name": "Launch",
    "notes": "Ship it",
    "archived": False,
    "modified_at": "2026-09-25T09:00:00.000Z",
    "workspace": {"gid": "100", "name": "Acme"},
}
OLD = {"gid": "1002", "name": "Old", "archived": True, "workspace": {"gid": "100"}}
LAB = {"gid": "2001", "name": "Lab", "workspace": {"gid": "200"}}

Answer = object | Callable[[httpx.Request], httpx.Response]


def page(data: list[Any], offset: str | None = None) -> dict[str, Any]:
    next_page = {"offset": offset, "path": "/x", "uri": "https://app.asana.com/x"}
    return {"data": data, "next_page": next_page if offset else None}


class Asana:
    """A healthy Asana, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.projects = {p["gid"]: p for p in (LAUNCH, OLD, LAB)}
        self.answers: dict[str, Answer] = {
            "/users/me": {
                "data": {"gid": "1", "name": "Nora", "email": EMAIL, "workspaces": [ACME, LABS]}
            },
            "/projects": self._listing,
            "/tasks": page([]),
            **(overrides or {}),
        }
        self.asked: list[httpx.Request] = []

    def _listing(self, request: httpx.Request) -> httpx.Response:
        workspace = request.url.params.get("workspace")
        found = [p for p in self.projects.values() if dig_gid(p) == workspace]
        return httpx.Response(200, json=page(found))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads Asana with GETs"
        assert request.url.host == "app.asana.com"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        self.asked.append(request)
        path = request.url.path.removeprefix(PREFIX)
        answer = self.answers.get(path)
        if answer is None and path.startswith("/projects/"):
            found = self.projects.get(path.rsplit("/", 1)[1])
            answer = {"data": found} if found else httpx.Response(404, json={"errors": []})
        if answer is None:
            return httpx.Response(404, json={"errors": [{"message": "Not found"}]})
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def params(self, path: str) -> list[dict[str, str]]:
        return [dict(r.url.params) for r in self.asked if r.url.path.removeprefix(PREFIX) == path]


def dig_gid(project: dict[str, Any]) -> str | None:
    workspace = project.get("workspace")
    return str(workspace["gid"]) if isinstance(workspace, dict) else None


def _connector(asana: Asana, **config: Any) -> AsanaConnector:
    return AsanaConnector(
        AsanaConfig.model_validate(config),
        AsanaCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(asana),
    )


async def _failure(asana: Asana, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(asana, **config).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


def test_asana_is_in_the_catalogue_as_a_project_tool_with_a_write_only_token() -> None:
    manifest = next(m for m in manifests() if m.key == "asana")
    token = manifest.credentials_schema.model_json_schema()["properties"]["token"]

    assert manifest.category is ConnectorCategory.PROJECT
    assert manifest.capabilities == {Capability.PROJECTS, Capability.ISSUES}
    assert manifest.listed_whole == {Capability.PROJECTS}
    assert manifest.read_only is True
    assert token["writeOnly"] is True


# ── the configuration ────────────────────────────────────────────────────────


def test_projects_are_kept_as_gids_once_whether_typed_or_pasted() -> None:
    config = AsanaConfig.model_validate(
        {
            "projects": [
                "1001",
                " 1001 ",
                "https://app.asana.com/1/100/project/1002/list/3",
                "https://app.asana.com/0/2001/list",
            ]
        }
    )

    assert config.projects == ["1001", "1002", "2001"]


@pytest.mark.parametrize(
    "config",
    [{"projects": []}, {"projects": ["launch"]}, {"projects": ["https://evil.test/0/1"]}, {"x": 1}],
)
def test_a_configuration_that_is_not_projects_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AsanaConfig.model_validate(config)


def test_asana_s_token_shape_is_scrubbed_from_any_detail() -> None:
    assert TOKEN not in sanitise(f"token {TOKEN} refused")


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_token_reports_the_account_and_what_it_can_read() -> None:
    asana = Asana()

    result = await _connector(asana).test_connection()

    assert result.account == EMAIL
    assert result.metadata == {"workspaces": ["Acme", "Acme Labs"], "projects_visible": 2}
    assert set(result.capabilities) == AsanaConnector.manifest.capabilities
    assert result.warnings == []
    assert asana.params("/tasks")[0]["project"] == "1001"


async def test_the_probes_read_a_project_in_scope() -> None:
    asana = Asana()

    result = await _connector(asana, projects=["2001"]).test_connection()

    assert set(result.capabilities) == {Capability.PROJECTS, Capability.ISSUES}
    assert asana.params("/tasks")[0]["project"] == "2001"


async def test_a_capability_asana_refuses_is_left_out_not_failed() -> None:
    forbidden = httpx.Response(403, json={"errors": [{"message": "Forbidden"}]})

    result = await _connector(Asana({"/tasks": forbidden})).test_connection()

    assert result.capabilities == [Capability.PROJECTS]


async def test_a_token_that_sees_no_project_is_told_so() -> None:
    nothing = {"data": {"gid": "1", "email": EMAIL, "workspaces": []}}

    result = await _connector(Asana({"/users/me": nothing})).test_connection()

    assert result.capabilities == []
    assert result.warnings == ["Aucun projet n'est visible avec ce jeton."]


async def test_a_project_in_scope_that_asana_does_not_show_fails_the_test() -> None:
    error = await _failure(Asana(), projects=["1001", "9999"])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert error.diagnostic.message == "Asana ne montre pas ces projets à ce jeton : 9999."


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={"errors": []}), DiagnosticCode.AUTH_INVALID),
        (httpx.Response(402, json={"errors": []}), DiagnosticCode.PERMISSION_DENIED),
        (httpx.Response(403, json={"errors": []}), DiagnosticCode.PERMISSION_DENIED),
        (httpx.Response(404, json={"errors": []}), DiagnosticCode.NOT_FOUND),
        (httpx.Response(500, text="oops"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Asana({"/users/me": response}))

    assert error.diagnostic.code is code


async def test_a_refusal_for_the_rate_says_when_to_come_back() -> None:
    busy = httpx.Response(429, headers={"retry-after": "30"}, json={"errors": []})

    error = await _failure(Asana({"/users/me": busy}))

    assert (error.diagnostic.code, error.diagnostic.retry_after) == (
        DiagnosticCode.RATE_LIMITED,
        30,
    )


async def test_an_echoed_token_is_removed_from_the_detail() -> None:
    error = await _failure(Asana({"/users/me": httpx.Response(500, text=f"bad {TOKEN}")}))

    assert TOKEN not in (error.diagnostic.detail or "")


# ── health ───────────────────────────────────────────────────────────────────


async def test_health_is_the_account_answering() -> None:
    assert (await _connector(Asana()).check_health()).status is HealthStatus.HEALTHY


async def test_health_fails_like_a_test_when_the_token_is_revoked() -> None:
    revoked = Asana({"/users/me": httpx.Response(401, json={"errors": []})})

    with pytest.raises(ConnectorError) as caught:
        await _connector(revoked).check_health()

    assert caught.value.diagnostic.code is DiagnosticCode.AUTH_INVALID


# ── the scope ────────────────────────────────────────────────────────────────


async def test_the_scope_is_chosen_from_every_project_of_every_workspace() -> None:
    listing = await _connector(Asana(), projects=["1001"]).list_scope()

    assert [(o.key, o.name, o.description) for o in listing.options] == [
        ("1001", "Launch", "Acme"),
        ("1002", "Old", "Acme · archivé"),
        ("2001", "Lab", "Acme Labs"),
    ]
    assert listing.options[0].updated_at is not None


async def test_a_listing_too_long_to_offer_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asana_module, "MAX_SCOPE_OPTIONS", 1)

    listing = await _connector(Asana()).list_scope()

    assert [o.key for o in listing.options] == ["1001"]
    assert listing.truncated is True
