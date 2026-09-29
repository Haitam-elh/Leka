"""The generic GraphQL connector against a system LEKA has no connector for
(LEKA-350).

The system is Tracker, invented here: issues behind a Relay-style cursor
(`pageInfo { endCursor hasNextPage }`), incidents in one answer. An
httpx.MockTransport stands in for it and checks the other half of "LEKA
reads": every request is a POST to the one endpoint, carrying a `query` —
never a mutation — and the secret as the admin chose.

What is shared with the REST connector — the mapping tried in the
connection test, the records, extraction, normalisation — is tested there
(tests/test_custom_rest_connector.py); here, what GraphQL does its own way.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, text

from leka.connectors import (
    Capability,
    ConnectorCategory,
    ConnectorError,
    DiagnosticCode,
    RawRecord,
    Source,
    SourceKind,
    SourceService,
    get_connector,
    manifests,
    register_connector,
    unregister_connector,
)
from leka.connectors.custom import (
    CustomCredentials,
    CustomGraphQLConfig,
    CustomGraphQLConnector,
    common,
)
from leka.connectors.custom import definition as definitions
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion import sync as sync_module
from leka.ingestion.extraction import ExtractedRecord, extract
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.models import SourceRecord
from leka.ingestion.normalisation import NormalisedRecord, normalise
from leka.ingestion.parsing import ParsedRecord, parse
from leka.ingestion.sync import sync_source
from leka.platform import LocalObjectStore

C = Capability
HOST = "tracker.acme.example"
ENDPOINT = f"https://{HOST}/api/graphql"
SECRET = "trk_" + "Qw3Er5Ty7Ui9Op1As3Df5Gh7Jk9"

ISSUES = [
    {
        "id": f"ISS-{n}",
        "title": f"Issue {n}",
        "state": {"name": "In Progress" if n % 2 else "Done"},
        "url": f"https://{HOST}/issues/{n}",
        "updatedAt": f"2026-09-2{n}T10:00:00Z",
        "reporter": {"email": f"user{n}@acme.example"},
    }
    for n in range(1, 6)
]
INCIDENTS = [
    {"id": "INC-7", "name": "Checkout down", "status": "resolved", "severity": "sev1"},
]

ISSUES_QUERY = """
query Issues($first: Int!, $after: String, $project: String!) {
  issues(first: $first, after: $after, project: $project) {
    nodes { id title url updatedAt state { name } reporter { email } }
    pageInfo { endCursor hasNextPage }
  }
}
"""
INCIDENTS_QUERY = "query { incidents { id name status severity } }"

DEFINITION: dict[str, Any] = {
    "version": 1,
    "resources": [
        {
            "name": "issues",
            "entity": "issue",
            "query": ISSUES_QUERY,
            "variables": {"project": "PLAT"},
            "items": "data.issues.nodes",
            "pagination": {
                "type": "cursor",
                "next": "data.issues.pageInfo.endCursor",
                "has_next": "data.issues.pageInfo.hasNextPage",
                "variable": "after",
                "size_variable": "first",
                "size": 2,
            },
            "mapping": {
                "id": "id",
                "title": "title",
                "url": "url",
                "state": "state.name",
                "updated_at": "updatedAt",
                "author": "reporter.email",
            },
        },
        {
            "name": "incidents",
            "entity": "incident",
            "query": INCIDENTS_QUERY,
            "items": "data.incidents",
            "mapping": {
                "id": "id",
                "title": "name",
                "state": "status",
                "metadata": {"severity": "severity"},
            },
        },
    ],
}

Answer = Callable[[dict[str, Any]], httpx.Response]


class Tracker:
    """Tracker as it answers, unless a query is overridden. Records what it
    was asked."""

    def __init__(self, answer: Answer | None = None) -> None:
        self.answer = answer
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.method == "POST", "GraphQL: POST, to the endpoint"
        assert (request.url.host, request.url.path) == (HOST, "/api/graphql")
        body = json.loads(request.content)
        self.bodies.append(body)
        assert "mutation" not in body["query"] and "subscription" not in body["query"]
        if self.answer is not None:
            return self.answer(body)
        variables = body.get("variables") or {}
        if "incidents" in body["query"]:
            return httpx.Response(200, json={"data": {"incidents": INCIDENTS}})
        start = int(variables.get("after") or 0)
        size = int(variables["first"])
        page = ISSUES[start : start + size]
        more = start + size < len(ISSUES)
        info = {"endCursor": str(start + size) if page else None, "hasNextPage": more}
        return httpx.Response(200, json={"data": {"issues": {"nodes": page, "pageInfo": info}}})


def _connector(
    tracker: Tracker | None = None,
    *,
    definition: dict[str, Any] | None = None,
    secret: str | None = SECRET,
    **config: Any,
) -> CustomGraphQLConnector:
    return CustomGraphQLConnector(
        CustomGraphQLConfig.model_validate(
            {"endpoint": ENDPOINT, "definition": json.dumps(definition or DEFINITION), **config}
        ),
        CustomCredentials(secret=SecretStr(secret) if secret is not None else None),
        transport=httpx.MockTransport(tracker or Tracker()),
    )


async def _records(connector: CustomGraphQLConnector) -> list[RawRecord]:
    return [record async for record in connector.iter_resources(C.RECORDS)]


async def _failure(connector: CustomGraphQLConnector) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await connector.test_connection()
    return caught.value


def _errors(*errors: dict[str, Any], data: Any = None) -> Answer:
    return lambda body: httpx.Response(200, json={"data": data, "errors": list(errors)})


# ── the definition and the settings ──────────────────────────────────────────


def _resource(**changes: Any) -> str:
    resource = {**DEFINITION["resources"][1], **changes}
    return json.dumps({"resources": [resource]})


@pytest.mark.parametrize(
    ("document", "said"),
    [
        (_resource(query="mutation { deleteEverything }"), "queries only"),
        (_resource(query="subscription { incidents { id } }"), "queries only"),
        (_resource(query="query { a } mutation { b }"), "queries only"),
        (_resource(items=None), "needs `items`"),
        (_resource(pagination={"type": "cursor", "next": "data.x"}), "`variable`"),
        (_resource(variables={"1bad": 1}), "variables"),
    ],
)
def test_a_definition_that_cannot_work_says_where(document: str, said: str) -> None:
    with pytest.raises(ValueError) as caught:
        definitions.parse_graphql(document)

    assert said in str(caught.value)


@pytest.mark.parametrize(
    "config",
    [
        {"endpoint": f"http://{HOST}/graphql"},
        {"endpoint": "https://10.0.0.5/graphql"},
        {"endpoint": f"{ENDPOINT}?token=x"},
        {"endpoint": ENDPOINT, "auth": "header", "auth_name": "Cookie"},
        {
            "endpoint": ENDPOINT,
            "definition": json.dumps({"resources": DEFINITION["resources"][:1] * 2}),
        },
    ],
)
def test_settings_that_cannot_work_are_refused(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CustomGraphQLConfig.model_validate({"definition": json.dumps(DEFINITION), **config})


def test_the_manifest() -> None:
    manifest = next(m for m in manifests() if m.key is SourceKind.CUSTOM_GRAPHQL)

    assert (manifest.display_name, manifest.category) == ("API GraphQL", ConnectorCategory.CUSTOM)
    assert manifest.capabilities == manifest.listed_whole == {C.RECORDS}
    assert manifest.read_only is True


# ── the connection test ──────────────────────────────────────────────────────


async def test_the_connection_test_asks_each_query_once_and_tries_the_mapping() -> None:
    tracker = Tracker()

    result = await _connector(tracker).test_connection()

    assert result.account == HOST
    assert result.metadata == {"resources": {"issues": 2, "incidents": 1}}
    assert result.warnings == []
    assert len(tracker.requests) == 2
    first = tracker.bodies[0]
    assert first["variables"] == {"project": "PLAT", "first": 2}
    assert first["query"] == ISSUES_QUERY.strip()
    assert all(r.headers["Authorization"] == f"Bearer {SECRET}" for r in tracker.requests)
    assert all(r.headers["Content-Type"] == "application/json" for r in tracker.requests)


async def test_the_secret_as_a_query_parameter_goes_beside_the_body() -> None:
    tracker = Tracker()

    await _connector(tracker, auth="query", auth_name="api_key").test_connection()

    assert all(r.url.params["api_key"] == SECRET for r in tracker.requests)
    assert all("Authorization" not in r.headers for r in tracker.requests)


# ── pages ────────────────────────────────────────────────────────────────────


async def test_every_page_follows_the_cursor_while_there_is_more() -> None:
    tracker = Tracker()

    records = await _records(_connector(tracker))

    assert [r.external_id for r in records] == [
        *(f"issues:ISS-{n}" for n in range(1, 6)),
        "incidents:INC-7",
    ]
    cursors = [body["variables"].get("after") for body in tracker.bodies]
    assert cursors == [None, "2", "4", None]  # three pages of issues, then incidents
    assert records[0].payload["entity"] == "issue"
    assert definitions.at(records[0].payload, "fields.state") == "In Progress"


async def test_without_has_next_a_cursor_given_again_ends_the_listing() -> None:
    def stuck(body: dict[str, Any]) -> httpx.Response:
        page = {"nodes": ISSUES[:1], "pageInfo": {"endCursor": "same"}}
        return httpx.Response(200, json={"data": {"issues": page}})

    resource = {**DEFINITION["resources"][0]}
    resource["pagination"] = {k: v for k, v in resource["pagination"].items() if k != "has_next"}
    tracker = Tracker(stuck)

    records = await _records(_connector(tracker, definition={"resources": [resource]}))

    assert len(tracker.requests) == 2
    assert {r.external_id for r in records} == {"issues:ISS-1"}


async def test_more_pages_than_a_pass_reads_is_a_failure_not_a_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(common, "MAX_PAGES", 2)

    with pytest.raises(ConnectorError) as caught:
        await _records(_connector())

    assert caught.value.diagnostic.code is DiagnosticCode.CONFIG_INVALID


# ── refusals, by status and by `errors` ──────────────────────────────────────


@pytest.mark.parametrize(
    ("code", "diagnostic"),
    [
        ("UNAUTHENTICATED", DiagnosticCode.AUTH_INVALID),
        ("FORBIDDEN", DiagnosticCode.PERMISSION_DENIED),
        ("GRAPHQL_VALIDATION_FAILED", DiagnosticCode.CONFIG_INVALID),
        ("RATE_LIMITED", DiagnosticCode.RATE_LIMITED),
        ("INTERNAL_SERVER_ERROR", DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_errors_in_a_200_are_a_failure_by_their_code(
    code: str, diagnostic: DiagnosticCode
) -> None:
    said = {"message": f"no: {SECRET}", "extensions": {"code": code}}

    error = await _failure(_connector(Tracker(_errors(said))))

    assert error.diagnostic.code is diagnostic
    assert SECRET not in error.diagnostic.model_dump_json()


async def test_partial_data_beside_errors_is_still_a_failure() -> None:
    partial = _errors({"message": "one field failed"}, data={"issues": {"nodes": ISSUES}})

    with pytest.raises(ConnectorError) as caught:
        await _records(_connector(Tracker(partial)))

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR


@pytest.mark.parametrize(
    ("status", "diagnostic"),
    [
        (401, DiagnosticCode.AUTH_INVALID),
        (403, DiagnosticCode.PERMISSION_DENIED),
        (502, DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_a_refusal_by_status(status: int, diagnostic: DiagnosticCode) -> None:
    error = await _failure(_connector(Tracker(lambda body: httpx.Response(status, text=SECRET))))

    assert error.diagnostic.code is diagnostic
    assert SECRET not in error.diagnostic.model_dump_json()


async def test_an_answer_that_is_not_json() -> None:
    error = await _failure(_connector(Tracker(lambda body: httpx.Response(200, text="<html/>"))))

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID


# ── into LEKA's model ────────────────────────────────────────────────────────


async def test_an_incident_becomes_an_incident_on_leka_s_scales() -> None:
    [*_, incident] = await _records(_connector())
    source_id = uuid.uuid4()

    extracted = extract(incident, source_id=source_id, source_kind=SourceKind.CUSTOM_GRAPHQL)
    assert isinstance(extracted, ExtractedRecord)
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord)
    result = normalise(extracted, parsed)

    assert isinstance(result, NormalisedRecord)
    assert result.entity.type == "incident"
    assert result.entity.key == f"custom-{source_id}:incident:incidents:INC-7"
    assert result.entity.attributes["state_raw"] == "resolved"
    assert result.entity.attributes["severity"] == "sev1"


# ── end to end: a source, a pass, extraction ─────────────────────────────────


class TrackerAsItAnswers(CustomGraphQLConnector):
    """The generic GraphQL connector, answered by Tracker."""

    def __init__(self, config: Any, credentials: Any, *, transport: Any = None) -> None:
        super().__init__(config, credentials, transport=httpx.MockTransport(Tracker()))


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    from leka.platform import storage

    real = get_connector(SourceKind.CUSTOM_GRAPHQL)
    unregister_connector(SourceKind.CUSTOM_GRAPHQL)
    register_connector(TrackerAsItAnswers)
    monkeypatch.setattr(storage, "_store", LocalObjectStore(tmp_path))

    async def capture(job: str, *args: object, **kwargs: object) -> object:
        return object()

    monkeypatch.setattr(sync_module, "enqueue_job", capture)
    monkeypatch.setattr(pipeline_module, "enqueue_job", capture)
    yield
    unregister_connector(SourceKind.CUSTOM_GRAPHQL)
    register_connector(real)


@pytest.fixture
async def source(pipeline: None) -> AsyncIterator[Source]:
    with system_scope():
        async with session_factory() as session:
            workspace_id: uuid.UUID = (
                await session.execute(
                    text("INSERT INTO workspaces (name, slug) VALUES ('Tracker', :s) RETURNING id"),
                    {"s": f"tracker-{uuid.uuid4().hex[:10]}"},
                )
            ).scalar_one()
            await session.commit()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = SourceService(session, workspace_id, actor_user_id=None)
            created = await service.create(
                SourceKind.CUSTOM_GRAPHQL,
                "Tracker",
                {"endpoint": ENDPOINT, "definition": json.dumps(DEFINITION)},
                {"secret": SECRET},
            )
            await service.test(created)
            await service.activate(created)
            await session.commit()
            yield created
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace_id})
            await session.commit()


async def test_a_graphql_system_goes_from_its_api_to_extracted_records(source: Source) -> None:
    assert source.capabilities == ["records"]

    report = await sync_source(source.workspace_id, source.id, full=True)

    assert report.status == "succeeded", report.error
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(SourceRecord).where(SourceRecord.source_id == source.id)
                )
            ).scalars()
            index = {row.external_id: row.container for row in rows}
    assert index == {
        **{f"issues:ISS-{n}": "issues" for n in range(1, 6)},
        "incidents:INC-7": "incidents",
    }
    extracted = await extract_source(source.workspace_id, source.id)
    assert (extracted["extracted"], extracted["failed"]) == (6, 0)
