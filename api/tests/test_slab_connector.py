"""The Slab connector against a Slab that is not there (LEKA-346).

httpx.MockTransport stands in for api.slab.com. Slab speaks GraphQL
through POST only, so the stand-in checks the other half of "LEKA reads":
every request is a POST to /v1/graphql, carrying a `query` — never a
mutation — with the token configured.
"""

from __future__ import annotations

import json
import re
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
from leka.connectors.slab import SlabConfig, SlabConnector, SlabCredentials
from leka.connectors.slab import connector as slab_module
from leka.connectors.slab.connector import DOCUMENTS, read_only

TOKEN = "slab-token-" + "A1b2C3d4E5" * 3

ENGINEERING: dict[str, Any] = {"id": "t-eng", "name": "Engineering", "description": "How we build"}
PEOPLE: dict[str, Any] = {
    "id": "t-people",
    "name": "People",
    "description": [{"insert": "Hiring and "}, {"insert": "onboarding\n"}],
}

Answer = object | Callable[[dict[str, Any]], httpx.Response]


def data(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"data": body})


def refused(message: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"errors": [{"message": message}]})


def post(number: int, updated: str = "2026-09-21T12:05:00Z") -> dict[str, Any]:
    return {"id": f"p{number}", "title": f"Post {number}", "updatedAt": updated}


class Slab:
    """A healthy Slab, unless an operation is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.posts = [post(1), post(2)]
        self.topics = {"t-eng": ["p1"], "t-people": ["p2"]}
        self.answers: dict[str, Answer] = {
            "Organization": data({"organization": {"id": "o-1", "name": "Acme"}}),
            "Health": data({"organization": {"id": "o-1"}}),
            "Topics": data({"organization": {"topics": [ENGINEERING, PEOPLE]}}),
            "Posts": lambda _: data({"organization": {"posts": self.posts}}),
            "TopicPosts": self._topic_posts,
            "Post": self._post,
            **(overrides or {}),
        }
        self.asked: list[tuple[str, dict[str, Any]]] = []

    def _topic_posts(self, variables: dict[str, Any]) -> httpx.Response:
        ids = self.topics.get(variables["id"], [])
        return data({"topic": {"id": variables["id"], "posts": [{"id": i} for i in ids]}})

    def _post(self, variables: dict[str, Any]) -> httpx.Response:
        found = next((p for p in self.posts if p["id"] == variables["id"]), None)
        if found is None:
            return data({"post": None})
        content = json.dumps([{"insert": f"Body of {found['title']}\n"}])
        return data({"post": {**found, "content": content, "linkAccess": "INTERNAL"}})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert (request.method, request.url.host, request.url.path) == (
            "POST",
            "api.slab.com",
            "/v1/graphql",
        ), "LEKA reads Slab through its one GraphQL endpoint"
        assert request.headers["authorization"] == TOKEN
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


@pytest.fixture(autouse=True)
def _no_pace(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Slab's pace, lifted for the stand-in."""
    monkeypatch.setattr(slab_module, "MIN_INTERVAL", 0.0)
    yield


def _connector(slab: Slab, **config: Any) -> SlabConnector:
    return SlabConnector(
        SlabConfig.model_validate(config),
        SlabCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(slab),
    )


async def _failure(slab: Slab, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(slab, **config).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


# ── LEKA only reads ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("document", DOCUMENTS)
def test_every_document_sent_to_slab_is_a_query(document: str) -> None:
    assert read_only(document).startswith("query")


def test_a_document_that_could_write_is_refused() -> None:
    with pytest.raises(ValueError, match="Slab queries only"):
        read_only('mutation { updatePost(id: "p1") { id } }')


def test_slab_is_in_the_catalogue_as_a_documentation_tool() -> None:
    manifest = next(m for m in manifests() if m.key == "slab")
    token = manifest.credentials_schema.model_json_schema()["properties"]["token"]

    assert manifest.category is ConnectorCategory.DOCS
    assert manifest.capabilities == {Capability.SPACES, Capability.PAGES}
    assert manifest.listed_whole == {Capability.SPACES}
    assert token["writeOnly"] is True


# ── the configuration ────────────────────────────────────────────────────────


def test_topics_are_kept_once() -> None:
    assert SlabConfig.model_validate({"topics": ["t-eng", " t-eng "]}).topics == ["t-eng"]


@pytest.mark.parametrize(
    "config", [{"topics": []}, {"topics": ["a topic"]}, {"topics": ["../x"]}, {"x": 1}]
)
def test_a_configuration_that_is_not_topics_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SlabConfig.model_validate(config)


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_token_reports_the_organisation_and_what_it_can_read() -> None:
    slab = Slab()

    result = await _connector(slab).test_connection()

    assert result.account == "Acme"
    assert result.metadata == {"topics_visible": 2, "posts_visible": 2}
    assert set(result.capabilities) == SlabConnector.manifest.capabilities
    assert result.warnings == []
    assert slab.variables("Post") == [{"id": "p1"}]


async def test_a_post_slab_will_not_open_leaves_pages_out() -> None:
    result = await _connector(Slab({"Post": refused("forbidden")})).test_connection()

    assert result.capabilities == [Capability.SPACES]


async def test_a_bot_that_sees_nothing_is_told_how_to_share() -> None:
    empty = Slab(
        {
            "Topics": data({"organization": {"topics": []}}),
            "Posts": data({"organization": {"posts": []}}),
        }
    )

    result = await _connector(empty).test_connection()

    assert result.capabilities == []
    assert "Slab Bot" in result.warnings[0]


async def test_a_topic_in_scope_the_bot_does_not_see_fails_the_test() -> None:
    error = await _failure(Slab(), topics=["t-eng", "t-secret"])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert error.diagnostic.message == "Slab ne montre pas ces sujets au Slab Bot : t-secret."


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={}), DiagnosticCode.AUTH_INVALID),
        (refused("Unauthorized"), DiagnosticCode.AUTH_INVALID),
        (refused("Forbidden"), DiagnosticCode.PERMISSION_DENIED),
        (refused("Post not found"), DiagnosticCode.NOT_FOUND),
        (httpx.Response(502, text="bad gateway"), DiagnosticCode.PROVIDER_ERROR),
        (refused("Something new"), DiagnosticCode.UNKNOWN),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Slab({"Organization": response}))

    assert error.diagnostic.code is code


@pytest.mark.parametrize(
    "response",
    [httpx.Response(429, headers={"retry-after": "7"}, json={}), refused("Rate limit exceeded")],
)
async def test_a_throttled_token_is_told_when_to_come_back(response: httpx.Response) -> None:
    error = await _failure(Slab({"Organization": response}))

    assert error.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert error.diagnostic.retry_after in (7, 60)


async def test_an_echoed_token_is_removed_from_the_detail() -> None:
    error = await _failure(Slab({"Organization": httpx.Response(500, text=f"bad {TOKEN}")}))

    assert TOKEN not in (error.diagnostic.detail or "")


# ── health, the scope, the pace ──────────────────────────────────────────────


async def test_health_is_slab_answering() -> None:
    assert (await _connector(Slab()).check_health()).status is HealthStatus.HEALTHY


async def test_the_scope_is_chosen_from_every_topic_with_its_description_as_text() -> None:
    listing = await _connector(Slab()).list_scope()

    assert [(o.key, o.name, o.description) for o in listing.options] == [
        ("t-eng", "Engineering", "How we build"),
        ("t-people", "People", "Hiring and onboarding"),
    ]


async def test_requests_keep_to_a_pace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(slab_module, "MIN_INTERVAL", 0.05)
    started = time.monotonic()

    await _connector(Slab()).test_connection()  # four requests

    assert time.monotonic() - started >= 0.15
