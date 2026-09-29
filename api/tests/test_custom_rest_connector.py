"""The generic REST connector against a system LEKA has no connector for
(LEKA-350).

The system is Helpdesk, invented here and shaped like the ticketing tools
companies run: tickets behind a cursor, agents behind page numbers, assets
behind a Link header. httpx.MockTransport stands in for it, at the
configured address, and checks the other half of "LEKA reads": every
request is a GET, to that host, the secret sent as the admin chose.

Nothing of Helpdesk is in LEKA's code: the definition below is what an
admin would type — and it is the whole integration, from the connection
test to extracted records.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
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
    HealthStatus,
    RawRecord,
    Source,
    SourceKind,
    SourceService,
    get_connector,
    manifests,
    register_connector,
    unregister_connector,
)
from leka.connectors.custom import CustomCredentials, CustomRestConfig, CustomRestConnector, rest
from leka.connectors.custom import definition as definitions
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion import sync as sync_module
from leka.ingestion.extraction import ExtractedRecord, ExtractionFailure, extract
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.models import SourceRecord
from leka.ingestion.normalisation import NormalisationFailure, NormalisedRecord, normalise
from leka.ingestion.parsing import ParsedRecord, parse
from leka.ingestion.sync import sync_source
from leka.platform import LocalObjectStore

C = Capability
HOST = "helpdesk.acme.example"
BASE = f"https://{HOST}/api/v2"
SECRET = "hd_live_" + "Zq8Xn2Lk4Wv6Tr1Ys3Pm5Ob7Ic9Ua0"

TICKETS = [
    {
        "id": 101,
        "subject": "VPN drops every hour",
        "status": "Open",
        "html_url": f"https://{HOST}/tickets/101",
        "created_at": "2026-09-20T08:00:00Z",
        "updated_at": 1790000000,  # seconds since the epoch
        "description": "Since Monday the VPN drops.",
        "requester": {"email": "ada@acme.example"},
        "priority": "high",
        "tags": ["network", "vpn"],
        "custom": {"team": "infra"},
    },
    {
        "id": 102,
        "subject": "Invoice export is empty",
        "status": "Pending",
        "created_at": "2026-09-21T10:30:00",  # no zone: read as UTC
        "requester": {"email": "grace@acme.example"},
        "priority": "low",
    },
    {"subject": "No id: not a record LEKA can tell apart"},
    {
        "id": 103,
        "subject": "Printer on 3rd floor",
        "status": "Solved",
        "requester": {"name": "Linus"},
    },
]
AGENTS = [{"id": f"a{n}", "name": f"Agent {n}", "role": "agent"} for n in range(1, 6)]
ASSETS = [{"serial": f"SN-{n}", "model": f"Laptop {n}"} for n in range(1, 4)]

DEFINITION: dict[str, Any] = {
    "version": 1,
    "resources": [
        {
            "name": "tickets",
            "entity": "issue",
            "path": "/tickets",
            "params": {"sort": "updated_at"},
            "items": "data",
            "pagination": {
                "type": "cursor",
                "next": "meta.next_cursor",
                "param": "cursor",
                "size_param": "limit",
                "size": 2,
            },
            "mapping": {
                "id": "id",
                "title": "subject",
                "url": "html_url",
                "state": "status",
                "created_at": "created_at",
                "updated_at": "updated_at",
                "description": "description",
                "author": "requester.email",
                "metadata": {"priority": "priority", "tags": "tags", "team": "custom"},
            },
        },
        {
            "name": "agents",
            "path": "/agents",
            "pagination": {"type": "page", "param": "page", "size_param": "per_page", "size": 2},
            "mapping": {"id": "id", "title": "name", "metadata": {"role": "role"}},
        },
        {
            "name": "assets",
            "path": "/assets",
            "items": "assets",
            "pagination": {"type": "link"},
            "mapping": {"id": "serial", "title": "model"},
        },
    ],
}

Answer = Callable[[httpx.Request], httpx.Response]


class Helpdesk:
    """Helpdesk as it answers, unless a path is overridden. Records what it
    was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.overrides = overrides or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.method == "GET", "LEKA reads: GET only"
        assert request.url.host == HOST, f"LEKA asked another host: {request.url.host}"
        path = request.url.path.removeprefix("/api/v2")
        if path in self.overrides:
            return self.overrides[path](request)
        params = request.url.params
        if path == "/tickets":
            start = int(params.get("cursor", "0"))
            size = int(params["limit"])
            page = TICKETS[start : start + size]
            following = str(start + size) if start + size < len(TICKETS) else None
            return httpx.Response(200, json={"data": page, "meta": {"next_cursor": following}})
        if path == "/agents":
            number, size = int(params["page"]), int(params["per_page"])
            return httpx.Response(200, json=AGENTS[(number - 1) * size : number * size])
        if path == "/assets":
            start = int(params.get("from", "0"))
            headers = {}
            if start + 2 < len(ASSETS):
                headers["Link"] = f'<{BASE}/assets?from={start + 2}>; rel="next"'
            return httpx.Response(200, json={"assets": ASSETS[start : start + 2]}, headers=headers)
        return httpx.Response(404, json={"error": "no such path"})


def _config(definition: dict[str, Any] | None = None, **more: Any) -> CustomRestConfig:
    return CustomRestConfig.model_validate(
        {"base_url": BASE, "definition": json.dumps(definition or DEFINITION), **more}
    )


def _connector(
    helpdesk: Helpdesk | None = None,
    *,
    definition: dict[str, Any] | None = None,
    secret: str | None = SECRET,
    username: str | None = None,
    **config: Any,
) -> CustomRestConnector:
    return CustomRestConnector(
        _config(definition, **config),
        CustomCredentials(
            secret=SecretStr(secret) if secret is not None else None, username=username
        ),
        transport=httpx.MockTransport(helpdesk or Helpdesk()),
    )


async def _records(connector: CustomRestConnector) -> list[RawRecord]:
    return [record async for record in connector.iter_resources(C.RECORDS)]


async def _failure(connector: CustomRestConnector) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await connector.test_connection()
    return caught.value


def _only(resource: str) -> dict[str, Any]:
    return {**DEFINITION, "resources": [DEFINITION["resources"][0] | {"name": resource}]}


# ── the definition ───────────────────────────────────────────────────────────


def test_the_example_definition_reads() -> None:
    parsed = definitions.parse(json.dumps(DEFINITION))

    assert [resource.name for resource in parsed.resources] == ["tickets", "agents", "assets"]
    assert parsed.resources[1].pagination.first == 1
    assert parsed.resources[0].pagination.first == 0


@pytest.mark.parametrize(
    ("document", "said"),
    [
        ("{not json", "not JSON: line 1, column 2"),
        (json.dumps({"resources": []}), "resources"),
        (
            json.dumps({"resources": [{"name": "t", "path": "/t", "mapping": {"id": "id"}}]}),
            "title",
        ),
        (
            json.dumps({**DEFINITION, "resources": DEFINITION["resources"][:1] * 2}),
            "tickets twice",
        ),
        (
            json.dumps(
                {
                    "resources": [
                        {
                            "name": "t",
                            "path": "/t",
                            "pagination": {"type": "cursor", "param": "c"},
                            "mapping": {"id": "id", "title": "t"},
                        }
                    ]
                }
            ),
            "needs `next`",
        ),
        (
            json.dumps(
                {
                    "resources": [
                        {
                            "name": "t",
                            "path": "https://evil.example/t",
                            "mapping": {"id": "id", "title": "t"},
                        }
                    ]
                }
            ),
            "path",
        ),
        (
            json.dumps(
                {
                    "resources": [
                        {"name": "t", "path": "/a/../admin", "mapping": {"id": "id", "title": "t"}}
                    ]
                }
            ),
            "path",
        ),
        (
            json.dumps(
                {"resources": [{"name": "T!", "path": "/t", "mapping": {"id": "id", "title": "t"}}]}
            ),
            "name",
        ),
        (json.dumps({**DEFINITION, "script": "rm -rf /"}), "script"),
    ],
)
def test_a_definition_that_cannot_work_says_where(document: str, said: str) -> None:
    with pytest.raises(ValueError) as caught:
        definitions.parse(document)

    assert said in str(caught.value)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("subject", "VPN drops every hour"),
        ("requester.email", "ada@acme.example"),
        ("tags.1", "vpn"),
        ("tags.9", None),
        ("requester.missing.deeper", None),
    ],
)
def test_a_path_leads_into_the_record(path: str, value: object) -> None:
    assert definitions.at(TICKETS[0], path) == value


@pytest.mark.parametrize(
    ("value", "moment"),
    [
        ("2026-09-20T08:00:00Z", datetime(2026, 9, 20, 8, tzinfo=UTC)),
        ("2026-09-20T08:00:00", datetime(2026, 9, 20, 8, tzinfo=UTC)),
        (1790000000, datetime.fromtimestamp(1790000000, UTC)),
        (1790000000000, datetime.fromtimestamp(1790000000, UTC)),
        ("1790000000", datetime.fromtimestamp(1790000000, UTC)),
        ("next tuesday", None),
        (True, None),
        (None, None),
    ],
)
def test_a_date_is_read_as_apis_write_them(value: object, moment: datetime | None) -> None:
    assert definitions.moment(value) == moment


# ── the settings ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config",
    [
        {"base_url": f"http://{HOST}/api"},
        {"base_url": "https://10.0.0.5/api"},
        {"base_url": BASE, "auth": "header"},
        {"base_url": BASE, "auth": "header", "auth_name": "Authorization"},
        {"base_url": BASE, "auth": "header", "auth_name": "Host"},
        {"base_url": BASE, "auth": "header", "auth_name": "X Key"},
        {"base_url": BASE, "auth": "query"},
        {"base_url": BASE, "auth": "bearer", "auth_name": "X-Api-Key"},
        {"base_url": BASE, "auth": "oauth"},
        {"base_url": BASE, "definition": "{}"},
        {"base_url": BASE, "definition": "not json"},
    ],
)
def test_settings_that_cannot_work_are_refused(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CustomRestConfig.model_validate({"definition": json.dumps(DEFINITION), **config})


def test_the_manifest_and_the_hint() -> None:
    manifest = next(m for m in manifests() if m.key is SourceKind.CUSTOM_REST)
    credentials = CustomCredentials(secret=SecretStr(SECRET))

    assert manifest.category is ConnectorCategory.CUSTOM
    assert manifest.capabilities == manifest.listed_whole == {C.RECORDS}
    assert manifest.read_only is True
    assert next(iter(credentials.model_dump())) == "secret"
    assert SECRET not in repr(credentials)
    assert CustomRestConfig.model_json_schema()["properties"]["definition"]["format"] == "json"


# ── the connection test ──────────────────────────────────────────────────────


async def test_the_connection_test_reads_a_page_of_each_and_tries_the_mapping() -> None:
    helpdesk = Helpdesk()

    result = await _connector(helpdesk).test_connection()

    assert result.account == HOST
    assert result.capabilities == [C.RECORDS]
    assert result.metadata == {"resources": {"tickets": 2, "agents": 2, "assets": 2}}
    # The first ticket has all its mapped fields; nothing to warn of.
    assert result.warnings == []
    assert all(r.headers["Authorization"] == f"Bearer {SECRET}" for r in helpdesk.requests)
    assert all(r.headers["Accept"] == "application/json" for r in helpdesk.requests)


async def test_a_mapped_path_the_first_record_lacks_is_a_warning() -> None:
    definition = _only("tickets")
    definition["resources"][0]["mapping"] = {
        **definition["resources"][0]["mapping"],
        "url": "links.web",
    }

    result = await _connector(definition=definition).test_connection()

    assert result.warnings == [
        "« tickets » : rien à ces chemins dans le premier enregistrement — url (links.web)."
    ]


async def test_a_mapping_without_an_id_or_a_title_is_named() -> None:
    definition = _only("tickets")
    definition["resources"][0]["mapping"] = {"id": "ticket_id", "title": "subject"}

    error = await _failure(_connector(definition=definition))

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "« tickets »" in error.diagnostic.message
    assert "ticket_id" in error.diagnostic.message


async def test_items_that_are_not_a_list_are_named() -> None:
    definition = _only("tickets")
    definition["resources"][0]["items"] = "meta"

    error = await _failure(_connector(definition=definition))

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "« meta »" in error.diagnostic.message


async def test_an_empty_first_page_is_a_warning_not_a_failure() -> None:
    helpdesk = Helpdesk({"/tickets": lambda r: httpx.Response(200, json={"data": []})})

    result = await _connector(helpdesk, definition=_only("tickets")).test_connection()

    assert result.metadata == {"resources": {"tickets": 0}}
    assert "vide" in result.warnings[0]


# ── the ways to send the secret ──────────────────────────────────────────────


async def test_a_header_of_its_own() -> None:
    helpdesk = Helpdesk()

    await _connector(helpdesk, auth="header", auth_name="X-Api-Key").test_connection()

    assert all(r.headers["X-Api-Key"] == SECRET for r in helpdesk.requests)
    assert all("Authorization" not in r.headers for r in helpdesk.requests)


async def test_a_query_parameter_and_never_in_a_diagnostic() -> None:
    echo = Helpdesk(
        {"/agents": lambda r: httpx.Response(500, text=f"boom at {r.url}")}  # echoes the key
    )

    error = await _failure(_connector(echo, auth="query", auth_name="api_key"))

    assert all(r.url.params["api_key"] == SECRET for r in echo.requests)
    assert error.diagnostic.code is DiagnosticCode.PROVIDER_ERROR
    assert SECRET not in error.diagnostic.model_dump_json()


async def test_basic_with_a_user() -> None:
    helpdesk = Helpdesk()

    await _connector(helpdesk, auth="basic", username="lekabot").test_connection()

    expected = base64.b64encode(f"lekabot:{SECRET}".encode()).decode()
    assert all(r.headers["Authorization"] == f"Basic {expected}" for r in helpdesk.requests)


async def test_none_sends_nothing() -> None:
    helpdesk = Helpdesk()

    await _connector(helpdesk, auth="none", secret=None).test_connection()

    assert all("Authorization" not in r.headers for r in helpdesk.requests)


@pytest.mark.parametrize(("auth", "username"), [("bearer", None), ("basic", None)])
async def test_a_secret_or_a_user_missing_is_said_before_asking(
    auth: str, username: str | None
) -> None:
    helpdesk = Helpdesk()
    secret = None if auth == "bearer" else SECRET

    error = await _failure(_connector(helpdesk, auth=auth, secret=secret, username=username))

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert helpdesk.requests == []


# ── what goes wrong ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "code", "said"),
    [
        (401, DiagnosticCode.AUTH_INVALID, "secret"),
        (403, DiagnosticCode.PERMISSION_DENIED, "/agents"),
        (404, DiagnosticCode.NOT_FOUND, "/agents"),
        (429, DiagnosticCode.RATE_LIMITED, None),
        (502, DiagnosticCode.PROVIDER_ERROR, None),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    status: int, code: DiagnosticCode, said: str | None
) -> None:
    helpdesk = Helpdesk(
        {"/agents": lambda r: httpx.Response(status, headers={"Retry-After": "30"}, text=SECRET)}
    )

    error = await _failure(_connector(helpdesk))

    assert error.diagnostic.code is code
    if said:
        assert said in error.diagnostic.message
    if status == 429:
        assert error.diagnostic.retry_after == 30
    assert SECRET not in error.diagnostic.model_dump_json()


async def test_an_answer_that_is_not_json() -> None:
    helpdesk = Helpdesk({"/tickets": lambda r: httpx.Response(200, text="<html>login</html>")})

    error = await _failure(_connector(helpdesk))

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "JSON" in error.diagnostic.message


async def test_a_timeout() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    error = await _failure(_connector(Helpdesk({"/tickets": slow})))

    assert error.diagnostic.code is DiagnosticCode.TIMEOUT


async def test_a_next_page_on_another_host_is_not_followed() -> None:
    evil = Helpdesk(
        {
            "/assets": lambda r: httpx.Response(
                200,
                json={"assets": ASSETS[:1]},
                headers={"Link": '<https://evil.example/steal>; rel="next"'},
            )
        }
    )
    definition = {**DEFINITION, "resources": [DEFINITION["resources"][2]]}

    with pytest.raises(ConnectorError) as caught:
        await _records(_connector(evil, definition=definition))

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR
    assert all(r.url.host == HOST for r in evil.requests)  # the secret never left


async def test_a_quota_nearly_spent_pauses_the_read() -> None:
    def low(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=AGENTS[:2],
            headers={"x-ratelimit-remaining": "1", "x-ratelimit-limit": "100"},
        )

    definition = {**DEFINITION, "resources": [DEFINITION["resources"][1]]}

    with pytest.raises(ConnectorError) as caught:
        await _records(_connector(Helpdesk({"/agents": low}), definition=definition))

    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED


@pytest.mark.parametrize(
    ("limit", "what"), [("MAX_PAGES", "pages"), ("MAX_RECORDS", "enregistrements")]
)
async def test_more_than_a_pass_reads_is_a_failure_not_a_cut(
    limit: str, what: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rest, limit, 2)

    with pytest.raises(ConnectorError) as caught:
        await _records(_connector())

    assert caught.value.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert what in caught.value.diagnostic.message


async def test_a_cursor_given_again_ends_the_listing() -> None:
    def stuck(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": TICKETS[:1], "meta": {"next_cursor": "same"}})

    helpdesk = Helpdesk({"/tickets": stuck})

    records = await _records(_connector(helpdesk, definition=_only("tickets")))

    assert len(helpdesk.requests) == 2  # the first page, then "same" once
    assert {r.external_id for r in records} == {"tickets:101"}


async def test_a_link_back_to_a_page_already_read_ends_the_listing() -> None:
    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"assets": ASSETS[:1]},
            headers={"Link": f'<{BASE}/assets>; rel="next"'},  # itself
        )

    helpdesk = Helpdesk({"/assets": loop})
    definition = {**DEFINITION, "resources": [DEFINITION["resources"][2]]}

    records = await _records(_connector(helpdesk, definition=definition))

    assert len(helpdesk.requests) == 1
    assert [r.external_id for r in records] == ["assets:SN-1"]


@pytest.mark.parametrize("kind", ["next_url", "offset"])
async def test_the_other_paginations(kind: str) -> None:
    def listing(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params.get("skip", request.url.params.get("from", "0")))
        page = AGENTS[start : start + 2]
        following = f"{BASE}/agents?from={start + 2}" if start + 2 < len(AGENTS) else None
        return httpx.Response(200, json={"rows": page, "next": following})

    pagination: dict[str, Any] = (
        {"type": "next_url", "next": "next"}
        if kind == "next_url"
        else {"type": "offset", "param": "skip", "size_param": "take", "size": 2}
    )
    resource = {
        "name": "agents",
        "path": "/agents",
        "items": "rows",
        "pagination": pagination,
        "mapping": {"id": "id", "title": "name"},
    }

    records = await _records(
        _connector(Helpdesk({"/agents": listing}), definition={"resources": [resource]})
    )

    assert [r.external_id for r in records] == [f"agents:a{n}" for n in range(1, 6)]


# ── what is read ─────────────────────────────────────────────────────────────


async def test_every_page_of_every_resource_becomes_records() -> None:
    records = await _records(_connector())

    ids = [record.external_id for record in records]
    # The ticket without an id is not stored: nothing tells it apart.
    assert ids == [
        "tickets:101",
        "tickets:102",
        "tickets:103",
        *(f"agents:a{n}" for n in range(1, 6)),
        *(f"assets:SN-{n}" for n in range(1, 4)),
    ]
    first = records[0]
    assert (first.kind, first.container) == (C.RECORDS, "tickets")
    assert (first.payload["resource"], first.payload["entity"]) == ("tickets", "issue")
    assert "entity" not in records[3].payload  # agents declare no entity
    assert first.payload["record"] == TICKETS[0]
    assert first.payload["fields"] == {
        "id": 101,
        "title": "VPN drops every hour",
        "url": f"https://{HOST}/tickets/101",
        "state": "Open",
        "created_at": "2026-09-20T08:00:00Z",
        "updated_at": 1790000000,
        "description": "Since Monday the VPN drops.",
        "author": "ada@acme.example",
        "metadata": {"priority": "high", "tags": ["network", "vpn"], "team": {"team": "infra"}},
    }
    assert first.updated_at == datetime.fromtimestamp(1790000000, UTC)


async def test_the_scope_is_the_resources_and_health_a_page() -> None:
    connector = _connector()

    listing = await connector.list_scope()
    health = await connector.check_health()

    assert [option.key for option in listing.options] == ["tickets", "agents", "assets"]
    assert health.status is HealthStatus.HEALTHY


# ── extraction: the mapping, read into LEKA's fields ─────────────────────────


async def test_a_record_extracts_into_leka_s_fields() -> None:
    [first, second, third, *_] = await _records(_connector())

    found = extract(first, source_id=uuid.uuid4(), source_kind=SourceKind.CUSTOM_REST)

    assert isinstance(found, ExtractedRecord)
    assert (found.title, found.url, found.state) == (
        "VPN drops every hour",
        f"https://{HOST}/tickets/101",
        "open",
    )
    assert found.created_at == datetime(2026, 9, 20, 8, tzinfo=UTC)
    assert found.updated_at == datetime.fromtimestamp(1790000000, UTC)
    assert found.content[0].text == "Since Monday the VPN drops."
    assert [(r.role, r.email, r.name) for r in found.references] == [
        ("author", "ada@acme.example", None)
    ]
    # An object in the metadata is left out: the mapping should point inside it.
    assert found.metadata == {"priority": "high", "tags": ["network", "vpn"]}
    assert found.signals == {"resource": "tickets", "entity": "issue"}
    assert found.provenance.external_id == "tickets:101"

    # Mapped to an address, a requester given only by name has no author.
    unnamed = extract(third, source_id=uuid.uuid4(), source_kind=SourceKind.CUSTOM_REST)
    assert isinstance(unnamed, ExtractedRecord)
    assert unnamed.references == []
    by_name = RawRecord(
        kind=C.RECORDS,
        external_id="tickets:9",
        container="tickets",
        payload={"resource": "tickets", "fields": {"id": 9, "title": "x", "author": "Linus"}},
        fetched_at=datetime.now(UTC),
    )
    found_by_name = extract(by_name, source_id=uuid.uuid4(), source_kind=SourceKind.CUSTOM_REST)
    assert isinstance(found_by_name, ExtractedRecord)
    assert [(r.name, r.email) for r in found_by_name.references] == [("Linus", None)]
    assert definitions.at(second.payload, "fields.created_at") == "2026-09-21T10:30:00"


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"id": 1}, "missing field 'fields.title'"),
        ({"id": 1, "title": "x", "updated_at": "next tuesday"}, "not a date: 'fields.updated_at'"),
    ],
)
def test_a_record_the_mapping_cannot_read_is_malformed(
    fields: dict[str, Any], message: str
) -> None:
    record = RawRecord(
        kind=C.RECORDS,
        external_id="tickets:1",
        container="tickets",
        payload={"resource": "tickets", "fields": fields, "record": {}},
        fetched_at=datetime.now(UTC),
    )

    found = extract(record, source_id=uuid.uuid4(), source_kind=SourceKind.CUSTOM_REST)

    assert isinstance(found, ExtractionFailure)
    assert found.message == message


# ── end to end: a source, a pass, extraction ─────────────────────────────────


class HelpdeskAsItAnswers(CustomRestConnector):
    """The generic connector, its HTTP answered by Helpdesk."""

    def __init__(self, config: Any, credentials: Any, *, transport: Any = None) -> None:
        super().__init__(config, credentials, transport=httpx.MockTransport(Helpdesk()))


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    from leka.platform import storage

    real = get_connector(SourceKind.CUSTOM_REST)
    unregister_connector(SourceKind.CUSTOM_REST)
    register_connector(HelpdeskAsItAnswers)
    monkeypatch.setattr(storage, "_store", LocalObjectStore(tmp_path))

    async def capture(job: str, *args: object, **kwargs: object) -> object:
        return object()

    monkeypatch.setattr(sync_module, "enqueue_job", capture)
    monkeypatch.setattr(pipeline_module, "enqueue_job", capture)
    yield
    unregister_connector(SourceKind.CUSTOM_REST)
    register_connector(real)


@pytest.fixture
async def source(pipeline: None) -> AsyncIterator[Source]:
    with system_scope():
        async with session_factory() as session:
            workspace_id: uuid.UUID = (
                await session.execute(
                    text("INSERT INTO workspaces (name, slug) VALUES ('Custom', :s) RETURNING id"),
                    {"s": f"custom-{uuid.uuid4().hex[:10]}"},
                )
            ).scalar_one()
            await session.commit()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = SourceService(session, workspace_id, actor_user_id=None)
            created = await service.create(
                SourceKind.CUSTOM_REST,
                "Helpdesk",
                {"base_url": BASE, "definition": json.dumps(DEFINITION)},
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


async def _index(source: Source) -> dict[str, SourceRecord]:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = await session.execute(
                select(SourceRecord).where(SourceRecord.source_id == source.id)
            )
            return {f"{row.kind}:{row.external_id}": row for row in rows.scalars()}


async def test_a_system_leka_has_no_connector_for_goes_from_its_api_to_extracted_records(
    source: Source,
) -> None:
    assert source.capabilities == ["records"]

    report = await sync_source(source.workspace_id, source.id, full=True)

    assert report.status == "succeeded", report.error
    index = await _index(source)
    assert len(index) == 11
    assert {row.container for row in index.values()} == {"tickets", "agents", "assets"}

    await sync_source(source.workspace_id, source.id, full=True)

    assert {k: r.payload_key for k, r in (await _index(source)).items()} == {
        k: r.payload_key for k, r in index.items()
    }  # unchanged, not written again
    extracted = await extract_source(source.workspace_id, source.id)
    assert (extracted["extracted"], extracted["failed"]) == (11, 0)


# ── normalisation: the entity each resource declares ─────────────────────────


def _normalised(record: RawRecord) -> NormalisedRecord | NormalisationFailure:
    source_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    extracted = extract(record, source_id=source_id, source_kind=SourceKind.CUSTOM_REST)
    assert isinstance(extracted, ExtractedRecord)
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord)
    return normalise(extracted, parsed)


async def test_a_ticket_becomes_an_issue_on_leka_s_scales_with_its_author() -> None:
    [ticket, *_] = await _records(_connector())

    result = _normalised(ticket)

    assert isinstance(result, NormalisedRecord)
    issue = result.entity
    assert issue.type == "issue"
    assert issue.key == "custom-11111111-2222-3333-4444-555555555555:issue:tickets:101"
    assert issue.name == "VPN drops every hour"
    # Lower-cased by extraction, then on LEKA's scale.
    assert (issue.attributes["state"], issue.attributes["state_raw"]) == ("open", "open")
    assert issue.attributes["priority_raw"] == "high"
    assert "priority" in issue.attributes
    [author] = result.related
    assert (author.type, author.key) == ("person", "person:email:ada@acme.example")
    assert [(r.type, r.from_key, r.to_key) for r in result.relationships] == [
        ("authored_by", issue.key, "person:email:ada@acme.example")
    ]


async def test_a_resource_that_declares_no_entity_is_extracted_not_modelled() -> None:
    agent = next(r for r in await _records(_connector()) if r.container == "agents")

    result = _normalised(agent)

    assert isinstance(result, NormalisationFailure)
    assert result.code == "unsupported"
    assert "agents" in result.message


async def test_a_service_meets_the_same_service_from_other_sources_by_its_name() -> None:
    definition = {
        "resources": [
            {
                "name": "apps",
                "entity": "service",
                "path": "/assets",
                "items": "assets",
                "mapping": {"id": "serial", "title": "model"},
            }
        ]
    }
    [app, *_] = await _records(_connector(definition=definition))

    result = _normalised(app)

    assert isinstance(result, NormalisedRecord)
    assert (result.entity.type, result.entity.key) == ("service", "service:laptop-1")
