"""Sources over HTTP: lifecycle, secrets, isolation, permissions (LEKA-344).

A FakeConnector — registered for these tests only — carries a source
through its whole lifecycle without a vendor. GitHub then does the same
end to end, its API answered by httpx.MockTransport. Nothing here touches
the network.
"""

# ruff: noqa: F811 — the fixture of test_postgresql_connector is imported to be requested by name.
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import asyncpg
import httpx
import pytest
from httpx import AsyncClient
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy import select, text

from leka.api.connectors import get_connector_transport
from leka.connectors import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    DiagnosticCode,
    HealthResult,
    HealthStatus,
    SourceCredential,
    SourceEvent,
    SourceKind,
    diagnose,
    register_connector,
    unregister_connector,
)
from leka.connectors.postgresql import PostgreSQLConnector
from leka.db import session_factory, system_scope
from leka.main import app
from leka.platform import secret_box
from tests.conftest import FakeIdentity, error_code
from tests.test_asana_connector import TOKEN as ASANA_TOKEN
from tests.test_asana_connector import Asana
from tests.test_clickup_connector import TOKEN as CLICKUP_TOKEN
from tests.test_clickup_connector import ClickUp
from tests.test_confluence_connector import Confluence
from tests.test_datadog_connector import API_KEY as DATADOG_API_KEY
from tests.test_datadog_connector import APP_KEY as DATADOG_APP_KEY
from tests.test_datadog_connector import Datadog
from tests.test_gcp_connector import KEY as GOOGLE_KEY
from tests.test_github_connector import github
from tests.test_google_workspace_connector import Google as GoogleWorkspace
from tests.test_grafana_connector import HOST as GRAFANA_HOST
from tests.test_grafana_connector import TOKEN as GRAFANA_TOKEN
from tests.test_grafana_connector import Grafana
from tests.test_guru_connector import TOKEN as GURU_TOKEN
from tests.test_guru_connector import USERNAME as GURU_USERNAME
from tests.test_guru_connector import Guru
from tests.test_jira_connector import EMAIL as JIRA_EMAIL
from tests.test_jira_connector import TOKEN as JIRA_TOKEN
from tests.test_jira_connector import Jira
from tests.test_linear_connector import KEY as LINEAR_KEY
from tests.test_linear_connector import Linear
from tests.test_microsoft_365_connector import CLIENT as M365_CLIENT
from tests.test_microsoft_365_connector import DOCS as M365_DOCS
from tests.test_microsoft_365_connector import SECRET as M365_SECRET
from tests.test_microsoft_365_connector import TENANT as M365_TENANT
from tests.test_microsoft_365_connector import Microsoft
from tests.test_monday_connector import TOKEN as MONDAY_TOKEN
from tests.test_monday_connector import Monday
from tests.test_notion_connector import TOKEN as NOTION_TOKEN
from tests.test_notion_connector import WIKI, Notion
from tests.test_pagerduty_connector import KEY as PAGERDUTY_KEY
from tests.test_pagerduty_connector import PagerDuty
from tests.test_postgresql_connector import SERVER as PG_SERVER
from tests.test_postgresql_connector import Catalogue, catalogue  # noqa: F401 — fixture
from tests.test_slab_connector import TOKEN as SLAB_TOKEN
from tests.test_slab_connector import Slab
from tests.test_trello_connector import KEY as TRELLO_KEY
from tests.test_trello_connector import ROADMAP as TRELLO_ROADMAP
from tests.test_trello_connector import TOKEN as TRELLO_TOKEN
from tests.test_trello_connector import Trello

pytestmark = pytest.mark.integration

API = "/api/v1"
FAKE_KEY = "fake-key-that-must-never-appear-anywhere"
WRONG_KEY = "wrong-key-the-fake-refuses-every-time"
GITHUB_TOKEN = "github_pat_11ABCDEFG0123456789_secretpartthatmustneverleak"


class FakeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: str = "eu"


class FakeCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr


class FakeConnector(Connector[FakeConfig, FakeCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.SLACK,
        display_name="Fake",
        category=ConnectorCategory.CHAT,
        auth_type="token",
        config_schema=FakeConfig,
        credentials_schema=FakeCredentials,
        capabilities=frozenset({Capability.ISSUES}),
    )

    async def test_connection(self) -> ConnectionTestResult:
        key = self.credentials.api_key.get_secret_value()
        if key == WRONG_KEY:
            raise diagnose(DiagnosticCode.AUTH_INVALID, detail=f"refused {key}", secrets=[key])
        return ConnectionTestResult(account="fake", capabilities=[Capability.ISSUES])

    async def check_health(self) -> HealthResult:
        from datetime import UTC, datetime

        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))


@pytest.fixture(autouse=True)
def fake_connector() -> Iterator[None]:
    register_connector(FakeConnector)
    yield
    unregister_connector(SourceKind.SLACK)


@pytest.fixture
def github_api() -> Iterator[None]:
    app.dependency_overrides[get_connector_transport] = lambda: httpx.MockTransport(github())
    yield
    app.dependency_overrides.pop(get_connector_transport, None)


async def _user(label: str) -> uuid.UUID:
    with system_scope():
        async with session_factory() as session:
            user_id: uuid.UUID = (
                await session.execute(
                    text("INSERT INTO users (email) VALUES (:e) RETURNING id"),
                    {"e": f"{label}-{uuid.uuid4().hex[:8]}@acme.example"},
                )
            ).scalar_one()
            await session.commit()
            return user_id


async def _workspace(members: dict[uuid.UUID, str]) -> uuid.UUID:
    with system_scope():
        async with session_factory() as session:
            workspace_id: uuid.UUID = (
                await session.execute(
                    text("INSERT INTO workspaces (name, slug) VALUES ('W', :s) RETURNING id"),
                    {"s": f"w-{uuid.uuid4().hex[:10]}"},
                )
            ).scalar_one()
            for user_id, role in members.items():
                await session.execute(
                    text(
                        "INSERT INTO memberships (workspace_id, user_id, role) VALUES (:w, :u, :r)"
                    ),
                    {"w": workspace_id, "u": user_id, "r": role},
                )
            await session.commit()
            return workspace_id


@pytest.fixture
async def acme() -> AsyncIterator[dict[str, uuid.UUID]]:
    """An owner and a member in Acme; another workspace, with its own admin."""
    people = {name: await _user(name) for name in ("admin", "member", "other_admin")}
    people["acme"] = await _workspace({people["admin"]: "admin", people["member"]: "member"})
    people["globex"] = await _workspace({people["other_admin"]: "admin"})
    yield people
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM workspaces WHERE id IN (:a, :g)"),
                {"a": people["acme"], "g": people["globex"]},
            )
            await session.execute(
                text("DELETE FROM users WHERE id IN (:a, :m, :o)"),
                {"a": people["admin"], "m": people["member"], "o": people["other_admin"]},
            )
            await session.commit()


def _as(identity: FakeIdentity, people: dict[str, uuid.UUID], who: str) -> None:
    workspace = people["globex"] if who == "other_admin" else people["acme"]
    identity.sign_in(people[who], workspace)


async def _create(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    body = {"type": "slack", "display_name": "Fake", "credentials": {"api_key": FAKE_KEY}}
    body.update(overrides)
    response = await client.post(f"{API}/sources", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


# ── the lifecycle, through the API ───────────────────────────────────────────


async def test_a_source_goes_through_its_whole_lifecycle(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client)
    url = f"{API}/sources/{source['id']}"
    assert source["status"] == "draft"
    assert source["credentials"]["hint"]

    refused = await client.post(f"{url}/activate")
    assert refused.status_code == 409
    assert error_code(refused) == "conflict"

    tested = (await client.post(f"{url}/test")).json()
    assert tested["ok"] is True
    assert tested["source"]["status"] == "tested"
    assert tested["source"]["capabilities"] == ["issues"]

    assert (await client.post(f"{url}/activate")).json()["status"] == "active"

    health = (await client.post(f"{url}/health-check")).json()
    assert health["health_status"] == "healthy"
    assert (await client.get(f"{url}/health")).json()["health_status"] == "healthy"

    # New credentials are unproven credentials.
    rotated = await client.put(
        f"{url}/credentials", json={"credentials": {"api_key": FAKE_KEY + "2"}}
    )
    assert rotated.json()["status"] == "draft"
    assert (await client.post(f"{url}/activate")).status_code == 409

    await client.post(f"{url}/test")
    assert (await client.post(f"{url}/activate")).json()["status"] == "active"
    assert (await client.post(f"{url}/disable")).json()["status"] == "disabled"

    events = (await client.get(f"{url}/events", params={"limit": 50})).json()["data"]
    assert {event["type"] for event in events} >= {
        "created",
        "test_succeeded",
        "activated",
        "health_changed",
        "credentials_rotated",
        "disabled",
    }
    assert all(event["actor_user_id"] == str(acme["admin"]) for event in events)

    assert (await client.delete(url)).status_code == 204
    assert (await client.get(url)).status_code == 404
    # The source is gone; its history is not, and it says why.
    with system_scope():
        async with session_factory() as session:
            last = await session.scalar(
                select(SourceEvent.type)
                .where(SourceEvent.source_id == uuid.UUID(source["id"]))
                .order_by(SourceEvent.created_at.desc())
                .limit(1)
            )
            credentials = await session.scalar(
                select(SourceCredential).where(
                    SourceCredential.source_id == uuid.UUID(source["id"])
                )
            )
    assert last == "deleted"
    assert credentials is None


async def test_new_settings_take_back_the_activation(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    url = f"{API}/sources/{(await _create(client))['id']}"
    await client.post(f"{url}/test")

    changed = await client.patch(url, json={"config": {"region": "us"}})
    assert changed.json()["status"] == "draft"
    assert (await client.post(f"{url}/activate")).status_code == 409


async def test_a_failed_test_is_an_answer_with_a_diagnostic(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client, credentials={"api_key": WRONG_KEY})

    response = await client.post(f"{API}/sources/{source['id']}/test")

    assert response.status_code == 200
    outcome = response.json()
    assert outcome["ok"] is False
    assert outcome["diagnostic"]["code"] == "AUTH_INVALID"
    assert outcome["diagnostic"]["message"]
    assert outcome["source"]["status"] == "draft"
    assert outcome["source"]["last_error"]["code"] == "AUTH_INVALID"
    assert WRONG_KEY not in response.text


async def test_the_input_is_checked_against_the_connector(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")

    bad_config = await client.post(
        f"{API}/sources",
        json={
            "type": "slack",
            "display_name": "X",
            "config": {"nope": 1},
            "credentials": {"api_key": FAKE_KEY},
        },
    )
    assert bad_config.status_code == 422
    assert FAKE_KEY not in bad_config.text

    # A kind LEKA knows but has no connector for: Slack, without the stand-in.
    unregister_connector(SourceKind.SLACK)
    try:
        unknown = await client.post(
            f"{API}/sources", json={"type": "slack", "display_name": "X", "credentials": {"k": "v"}}
        )
    finally:
        register_connector(FakeConnector)
    assert unknown.status_code == 422
    assert "No connector exists" in unknown.text

    await _create(client, display_name="Same")
    assert (
        await client.post(
            f"{API}/sources",
            json={"type": "slack", "display_name": "Same", "credentials": {"api_key": FAKE_KEY}},
        )
    ).status_code == 409


# ── secrets ──────────────────────────────────────────────────────────────────


async def test_a_secret_goes_in_and_never_comes_out(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client)
    url = f"{API}/sources/{source['id']}"
    answers = [
        json.dumps(source),
        (await client.get(url)).text,
        (await client.get(f"{API}/sources")).text,
        (await client.post(f"{url}/test")).text,
        (await client.put(f"{url}/credentials", json={"credentials": {"api_key": FAKE_KEY}})).text,
        (await client.get(f"{url}/events")).text,
    ]
    for answer in answers:
        assert FAKE_KEY not in answer
    assert FAKE_KEY not in caplog.text
    assert FAKE_KEY not in capsys.readouterr().out

    with system_scope():
        async with session_factory() as session:
            stored = (
                await session.execute(
                    select(SourceCredential).where(
                        SourceCredential.source_id == uuid.UUID(source["id"])
                    )
                )
            ).scalar_one()
    assert FAKE_KEY.encode() not in stored.ciphertext
    assert json.loads(secret_box.decrypt(stored.ciphertext)) == {"api_key": FAKE_KEY}
    assert stored.key_version == secret_box.key_version
    assert FAKE_KEY not in repr(stored.hint)


# ── who may do what, where ───────────────────────────────────────────────────


async def test_another_workspace_cannot_see_or_test_a_source(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    url = f"{API}/sources/{(await _create(client))['id']}"

    _as(identity, acme, "other_admin")
    assert (await client.get(url)).status_code == 404
    assert (await client.post(f"{url}/test")).status_code == 404
    assert (await client.get(f"{API}/sources")).json()["data"] == []


async def test_a_member_reads_but_does_not_manage(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    url = f"{API}/sources/{(await _create(client))['id']}"

    _as(identity, acme, "member")
    assert (await client.get(url)).status_code == 200
    assert (await client.get(f"{API}/connectors/catalog")).status_code == 200
    body = {"type": "slack", "display_name": "No", "credentials": {"api_key": FAKE_KEY}}
    assert (await client.post(f"{API}/sources", json=body)).status_code == 403
    assert (await client.post(f"{url}/test")).status_code == 403
    assert (await client.post(f"{url}/activate")).status_code == 403


# ── GitHub, end to end ───────────────────────────────────────────────────────


async def test_github_end_to_end(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github_api: None,
) -> None:
    _as(identity, acme, "admin")
    catalog = (await client.get(f"{API}/connectors/catalog")).json()
    entry = next(item for item in catalog if item["key"] == "github")
    assert entry["read_only"] is True
    assert entry["credentials_schema"]["properties"]["token"]["writeOnly"] is True

    source = await _create(
        client,
        type="github",
        display_name="Acme GitHub",
        config={"organization": "acme"},
        credentials={"token": GITHUB_TOKEN},
    )
    assert source["credentials"]["hint"] == "github_pat_…leak"
    url = f"{API}/sources/{source['id']}"

    tested = (await client.post(f"{url}/test")).json()
    assert tested["ok"] is True
    assert tested["result"]["account"] == "nora"
    assert (await client.post(f"{url}/activate")).json()["status"] == "active"
    assert (await client.post(f"{url}/health-check")).json()["health_status"] == "healthy"


async def test_github_scope_is_chosen_from_what_github_offers(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github_api: None,
) -> None:
    _as(identity, acme, "admin")
    source = await _create(
        client,
        type="github",
        display_name="Acme GitHub",
        config={"organization": "acme"},
        credentials={"token": GITHUB_TOKEN},
    )
    url = f"{API}/sources/{source['id']}"

    offered = (await client.get(f"{url}/scope/options")).json()
    assert offered["ok"] is True
    assert [option["key"] for option in offered["options"]] == ["acme/api"]
    # Asking reads: nothing about the source changed, nothing was recorded.
    assert (await client.get(url)).json()["status"] == "draft"
    events = (await client.get(f"{url}/events")).json()["data"]
    assert [event["type"] for event in events] == ["created"]

    in_scope = {"organization": "acme", "repositories": ["acme/api"]}
    scoped = await client.patch(url, json={"config": in_scope})
    assert scoped.json()["config"]["repositories"] == ["acme/api"]
    assert (await client.post(f"{url}/test")).json()["ok"] is True

    elsewhere = {"organization": "acme", "repositories": ["globex/api"]}
    refused = await client.patch(url, json={"config": elsewhere})
    assert refused.status_code == 422

    _as(identity, acme, "member")
    assert (await client.get(f"{url}/scope/options")).status_code == 403
    _as(identity, acme, "other_admin")
    assert (await client.get(f"{url}/scope/options")).status_code == 404


# ── Jira, end to end ─────────────────────────────────────────────────────────


@pytest.fixture
def jira_api() -> Iterator[Jira]:
    jira = Jira()
    app.dependency_overrides[get_connector_transport] = lambda: httpx.MockTransport(jira)
    yield jira
    app.dependency_overrides.pop(get_connector_transport, None)


def _jira(site: str = "acme", **config: object) -> dict[str, Any]:
    return {
        "type": "jira",
        "display_name": "Acme Jira",
        "config": {"site": site, **config},
        "credentials": {"token": JIRA_TOKEN, "email": JIRA_EMAIL},
    }


async def test_jira_end_to_end(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    jira_api: Jira,
) -> None:
    _as(identity, acme, "admin")
    catalog = (await client.get(f"{API}/connectors/catalog")).json()
    entry = next(item for item in catalog if item["key"] == "jira")
    assert (entry["category"], entry["read_only"]) == ("project", True)
    assert entry["credentials_schema"]["properties"]["token"]["writeOnly"] is True

    # Pasted from the browser's address bar: kept as the site's name.
    source = await _create(client, **_jira("https://acme.atlassian.net/jira/software"))
    assert source["config"] == {"site": "acme", "projects": None}
    assert JIRA_TOKEN not in json.dumps(source)
    url = f"{API}/sources/{source['id']}"

    tested = (await client.post(f"{url}/test")).json()
    assert tested["ok"] is True
    assert tested["result"]["account"] == "Nora Admin"
    assert sorted(tested["source"]["capabilities"]) == ["issues", "projects"]

    offered = (await client.get(f"{url}/scope/options")).json()
    assert [option["key"] for option in offered["options"]] == ["PAY", "OPS"]
    scoped = await client.patch(url, json={"config": {"site": "acme", "projects": ["pay"]}})
    assert scoped.json()["config"]["projects"] == ["PAY"]

    assert (await client.post(f"{url}/test")).json()["ok"] is True
    assert (await client.post(f"{url}/activate")).json()["status"] == "active"
    assert (await client.post(f"{url}/health-check")).json()["health_status"] == "healthy"
    # Every call went to the customer's site, as a GET: the stand-in asserts both.
    assert {request.url.host for request in jira_api.requests} == {"acme.atlassian.net"}


@pytest.mark.parametrize(
    "site",
    [
        "169.254.169.254",
        "http://10.0.0.1/rest/api/3",
        "localhost:8000",
        "evil.example",
        "acme.atlassian.net.evil.example",
    ],
)
async def test_a_jira_source_cannot_be_aimed_anywhere_but_atlassian(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID], site: str
) -> None:
    _as(identity, acme, "admin")

    refused = await client.post(f"{API}/sources", json=_jira(site))

    assert refused.status_code == 422
    assert JIRA_TOKEN not in refused.text
    assert (await client.get(f"{API}/sources")).json()["data"] == []


async def test_only_an_admin_connects_jira_and_the_token_never_comes_back(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    jira_api: Jira,
) -> None:
    _as(identity, acme, "member")
    assert (await client.post(f"{API}/sources", json=_jira())).status_code == 403

    _as(identity, acme, "admin")
    url = f"{API}/sources/{(await _create(client, **_jira()))['id']}"

    _as(identity, acme, "member")
    seen = await client.get(url)
    assert seen.status_code == 200
    assert JIRA_TOKEN not in seen.text
    assert seen.json()["credentials"]["hint"]
    assert (await client.post(f"{url}/test")).status_code == 403
    assert (await client.get(f"{url}/scope/options")).status_code == 403

    _as(identity, acme, "other_admin")
    assert (await client.get(url)).status_code == 404
    assert (await client.post(f"{url}/test")).status_code == 404
    # Nothing of the above reached Jira: refusals happen before a request.
    assert jira_api.requests == []


# ── Confluence, end to end ───────────────────────────────────────────────────


@pytest.fixture
def confluence_api() -> Iterator[Confluence]:
    confluence = Confluence()
    app.dependency_overrides[get_connector_transport] = lambda: httpx.MockTransport(confluence)
    yield confluence
    app.dependency_overrides.pop(get_connector_transport, None)


async def test_confluence_end_to_end(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    confluence_api: Confluence,
) -> None:
    _as(identity, acme, "admin")
    catalog = (await client.get(f"{API}/connectors/catalog")).json()
    entry = next(item for item in catalog if item["key"] == "confluence")
    assert (entry["category"], entry["read_only"]) == ("docs", True)

    body = {**_jira("acme.atlassian.net"), "type": "confluence", "display_name": "Wiki"}
    source = await _create(client, **body)
    assert source["config"] == {"site": "acme", "spaces": None}
    url = f"{API}/sources/{source['id']}"

    tested = (await client.post(f"{url}/test")).json()
    assert tested["ok"] is True
    assert sorted(tested["source"]["capabilities"]) == ["pages", "spaces"]

    offered = (await client.get(f"{url}/scope/options")).json()
    assert [option["key"] for option in offered["options"]] == ["ENG", "OPS"]
    scoped = await client.patch(url, json={"config": {"site": "acme", "spaces": ["ENG"]}})
    assert scoped.json()["config"]["spaces"] == ["ENG"]
    unknown = await client.patch(url, json={"config": {"site": "acme", "spaces": ["SEC"]}})
    assert unknown.status_code == 200  # saved; the test is what checks it exists
    failed = (await client.post(f"{url}/test")).json()
    assert failed["ok"] is False
    assert failed["diagnostic"]["code"] == "NOT_FOUND"

    await client.patch(url, json={"config": {"site": "acme", "spaces": ["ENG"]}})
    assert (await client.post(f"{url}/test")).json()["ok"] is True
    assert (await client.post(f"{url}/activate")).json()["status"] == "active"
    assert (await client.post(f"{url}/health-check")).json()["health_status"] == "healthy"
    assert {request.url.host for request in confluence_api.requests} == {"acme.atlassian.net"}

    _as(identity, acme, "member")
    assert (await client.get(f"{url}/scope/options")).status_code == 403
    assert JIRA_TOKEN not in (await client.get(url)).text


# ── Linear, end to end ───────────────────────────────────────────────────────


@pytest.fixture
def linear_api() -> Iterator[Linear]:
    linear = Linear()
    app.dependency_overrides[get_connector_transport] = lambda: httpx.MockTransport(linear)
    yield linear
    app.dependency_overrides.pop(get_connector_transport, None)


async def test_linear_end_to_end(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    linear_api: Linear,
) -> None:
    _as(identity, acme, "member")
    body = {"type": "linear", "display_name": "Linear", "credentials": {"api_key": LINEAR_KEY}}
    assert (await client.post(f"{API}/sources", json=body)).status_code == 403

    _as(identity, acme, "admin")
    catalog = (await client.get(f"{API}/connectors/catalog")).json()
    entry = next(item for item in catalog if item["key"] == "linear")
    assert (entry["category"], entry["read_only"]) == ("project", True)
    assert entry["credentials_schema"]["properties"]["api_key"]["writeOnly"] is True

    source = await _create(client, **body)
    assert LINEAR_KEY not in json.dumps(source)
    url = f"{API}/sources/{source['id']}"

    tested = (await client.post(f"{url}/test")).json()
    assert tested["ok"] is True
    assert tested["result"]["account"] == "nora@acme.test"
    assert sorted(tested["source"]["capabilities"]) == ["issues", "projects"]

    offered = (await client.get(f"{url}/scope/options")).json()
    assert [option["key"] for option in offered["options"]] == ["ENG", "OPS"]
    scoped = await client.patch(url, json={"config": {"teams": ["eng"]}})
    assert scoped.json()["config"]["teams"] == ["ENG"]

    assert (await client.post(f"{url}/test")).json()["ok"] is True
    assert (await client.post(f"{url}/activate")).json()["status"] == "active"
    assert (await client.post(f"{url}/health-check")).json()["health_status"] == "healthy"
    # Every call was a query to Linear's one endpoint: the stand-in asserts it.
    assert {operation for operation, _ in linear_api.asked} == {
        "Viewer",
        "Teams",
        "TeamProjects",
        "TeamIssues",
        "Health",
    }

    _as(identity, acme, "member")
    assert LINEAR_KEY not in (await client.get(url)).text
    assert (await client.post(f"{url}/test")).status_code == 403


# ── Notion, end to end ───────────────────────────────────────────────────────


@pytest.fixture
def notion_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[Notion]:
    monkeypatch.setattr("leka.connectors.notion.connector.MIN_INTERVAL", 0.0)
    notion = Notion()
    app.dependency_overrides[get_connector_transport] = lambda: httpx.MockTransport(notion)
    yield notion
    app.dependency_overrides.pop(get_connector_transport, None)


async def test_notion_end_to_end(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    notion_api: Notion,
) -> None:
    _as(identity, acme, "member")
    body = {"type": "notion", "display_name": "Notion", "credentials": {"token": NOTION_TOKEN}}
    assert (await client.post(f"{API}/sources", json=body)).status_code == 403

    _as(identity, acme, "admin")
    catalog = (await client.get(f"{API}/connectors/catalog")).json()
    entry = next(item for item in catalog if item["key"] == "notion")
    assert (entry["category"], entry["read_only"]) == ("docs", True)
    assert entry["credentials_schema"]["properties"]["token"]["writeOnly"] is True

    source = await _create(client, **body)
    assert NOTION_TOKEN not in json.dumps(source)
    url = f"{API}/sources/{source['id']}"

    tested = (await client.post(f"{url}/test")).json()
    assert tested["ok"] is True
    assert tested["result"]["account"] == "LEKA"
    assert sorted(tested["source"]["capabilities"]) == ["databases", "pages"]

    offered = (await client.get(f"{url}/scope/options")).json()
    assert WIKI in [option["key"] for option in offered["options"]]
    # Pasted as a link, kept as Notion writes the id.
    link = f"https://www.notion.so/acme/Wiki-{WIKI.replace('-', '')}?pvs=4"
    scoped = await client.patch(url, json={"config": {"roots": [link]}})
    assert scoped.json()["config"]["roots"] == [WIKI]
    refused = await client.patch(url, json={"config": {"roots": ["http://10.0.0.1/admin"]}})
    assert refused.status_code == 422

    assert (await client.post(f"{url}/test")).json()["ok"] is True
    assert (await client.post(f"{url}/activate")).json()["status"] == "active"
    assert (await client.post(f"{url}/health-check")).json()["health_status"] == "healthy"
    # Every call was a GET, or a POST to /search: the stand-in asserts it.
    assert {method for method, _, _ in notion_api.asked} == {"GET", "POST"}
    assert set(notion_api.paths("POST")) == {"/search"}

    _as(identity, acme, "member")
    assert NOTION_TOKEN not in (await client.get(url)).text
    assert (await client.post(f"{url}/test")).status_code == 403


# ── Asana, Trello, ClickUp, Monday, end to end ───────────────────────────────

# kind, the stand-in, its secrets, the scope's field, what an admin pastes in
# it and what is kept, the first option offered.
PROJECT_TOOLS = [
    (
        "asana",
        Asana,
        {"token": ASANA_TOKEN},
        "projects",
        "https://app.asana.com/1/100/project/2001/list/9",
        "2001",
        "1001",
    ),
    (
        "trello",
        Trello,
        {"token": TRELLO_TOKEN, "api_key": TRELLO_KEY},
        "boards",
        "https://trello.com/b/AbCd1234/roadmap",
        "AbCd1234",
        TRELLO_ROADMAP["id"],
    ),
    ("clickup", ClickUp, {"token": CLICKUP_TOKEN}, "spaces", " 902 ", "902", "901"),
    (
        "monday",
        Monday,
        {"token": MONDAY_TOKEN},
        "boards",
        "https://acme.monday.com/boards/222",
        "222",
        "111",
    ),
]


@pytest.mark.parametrize(
    ("kind", "stand_in", "secrets", "field", "pasted", "kept", "first"), PROJECT_TOOLS
)
async def test_a_project_tool_end_to_end(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    kind: str,
    stand_in: Any,
    secrets: dict[str, str],
    field: str,
    pasted: str,
    kept: str,
    first: str,
) -> None:
    """Only an admin connects it; the secrets never come back; a pasted link
    is kept as the vendor's id; test, activation and health go through."""
    vendor = stand_in()
    app.dependency_overrides[get_connector_transport] = lambda: httpx.MockTransport(vendor)
    try:
        _as(identity, acme, "member")
        body = {"type": kind, "display_name": kind.title(), "credentials": secrets}
        assert (await client.post(f"{API}/sources", json=body)).status_code == 403

        _as(identity, acme, "admin")
        catalog = (await client.get(f"{API}/connectors/catalog")).json()
        entry = next(item for item in catalog if item["key"] == kind)
        assert (entry["category"], entry["read_only"]) == ("project", True)
        for name in secrets:
            assert entry["credentials_schema"]["properties"][name]["writeOnly"] is True

        source = await _create(client, **body)
        for secret in secrets.values():
            assert secret not in json.dumps(source)
        url = f"{API}/sources/{source['id']}"

        tested = (await client.post(f"{url}/test")).json()
        assert tested["ok"] is True, tested
        assert sorted(tested["source"]["capabilities"]) == ["issues", "projects"]

        offered = (await client.get(f"{url}/scope/options")).json()
        assert offered["options"][0]["key"] == first
        scoped = await client.patch(url, json={"config": {field: [pasted]}})
        assert scoped.json()["config"][field] == [kept]
        wrong = await client.patch(url, json={"config": {field: ["http://10.0.0.1/admin"]}})
        assert wrong.status_code == 422

        assert (await client.post(f"{url}/test")).json()["ok"] is True
        assert (await client.post(f"{url}/activate")).json()["status"] == "active"
        assert (await client.post(f"{url}/health-check")).json()["health_status"] == "healthy"

        _as(identity, acme, "member")
        page = (await client.get(url)).text
        assert all(secret not in page for secret in secrets.values())
        assert (await client.post(f"{url}/test")).status_code == 403
    finally:
        app.dependency_overrides.pop(get_connector_transport, None)


# ── Slab, Guru, end to end ─────────────────────────────────────────────────

# kind, the stand-in, its credentials, the scope's field, what an admin
# gives it and what is kept, the first option offered.
KNOWLEDGE_BASES = [
    ("slab", Slab, {"token": SLAB_TOKEN}, "topics", " t-people ", "t-people", "t-eng"),
    (
        "guru",
        Guru,
        {"token": GURU_TOKEN, "username": GURU_USERNAME},
        "collections",
        "C-Sales",
        "c-sales",
        "c-onboard",
    ),
]


@pytest.mark.parametrize(
    ("kind", "stand_in", "credentials", "field", "given", "kept", "first"), KNOWLEDGE_BASES
)
async def test_a_knowledge_base_end_to_end(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    stand_in: Any,
    credentials: dict[str, str],
    field: str,
    given: str,
    kept: str,
    first: str,
) -> None:
    """Only an admin connects it; the token never comes back; test,
    activation and health go through."""
    monkeypatch.setattr("leka.connectors.slab.connector.MIN_INTERVAL", 0.0)
    vendor = stand_in()
    app.dependency_overrides[get_connector_transport] = lambda: httpx.MockTransport(vendor)
    token = credentials["token"]
    try:
        _as(identity, acme, "member")
        body = {"type": kind, "display_name": kind.title(), "credentials": credentials}
        assert (await client.post(f"{API}/sources", json=body)).status_code == 403

        _as(identity, acme, "admin")
        catalog = (await client.get(f"{API}/connectors/catalog")).json()
        entry = next(item for item in catalog if item["key"] == kind)
        assert (entry["category"], entry["read_only"]) == ("docs", True)
        assert entry["credentials_schema"]["properties"]["token"]["writeOnly"] is True

        source = await _create(client, **body)
        assert token not in json.dumps(source)
        url = f"{API}/sources/{source['id']}"

        tested = (await client.post(f"{url}/test")).json()
        assert tested["ok"] is True, tested
        assert sorted(tested["source"]["capabilities"]) == ["pages", "spaces"]

        offered = (await client.get(f"{url}/scope/options")).json()
        assert offered["options"][0]["key"] == first
        scoped = await client.patch(url, json={"config": {field: [given]}})
        assert scoped.json()["config"][field] == [kept]
        wrong = await client.patch(url, json={"config": {field: ["http://10.0.0.1/admin"]}})
        assert wrong.status_code == 422

        assert (await client.post(f"{url}/test")).json()["ok"] is True
        assert (await client.post(f"{url}/activate")).json()["status"] == "active"
        assert (await client.post(f"{url}/health-check")).json()["health_status"] == "healthy"

        _as(identity, acme, "member")
        assert token not in (await client.get(url)).text
        assert (await client.post(f"{url}/test")).status_code == 403
    finally:
        app.dependency_overrides.pop(get_connector_transport, None)


# ── Google Workspace, Microsoft 365, end to end ──────────────────────────────

# kind, the stand-in, its config and credentials, the secret that must never
# come back, the scope's field, what an admin gives it and what is kept.
OFFICE_SUITES = [
    (
        "google_workspace",
        GoogleWorkspace,
        {"subject": "Reader@Acme.test"},
        {"service_account_key": GOOGLE_KEY},
        "PRIVATE KEY",
        "drives",
        "https://drive.google.com/drive/folders/0AEngineeringDrive",
        "0AEngineeringDrive",
    ),
    (
        "microsoft_365",
        Microsoft,
        {"tenant_id": M365_TENANT},
        {"client_id": M365_CLIENT, "client_secret": M365_SECRET},
        M365_SECRET,
        "drives",
        f" {M365_DOCS} ",
        M365_DOCS,
    ),
]


@pytest.mark.parametrize(
    ("kind", "stand_in", "config", "credentials", "secret", "field", "given", "kept"),
    OFFICE_SUITES,
)
async def test_an_office_suite_end_to_end(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    kind: str,
    stand_in: Any,
    config: dict[str, str],
    credentials: dict[str, str],
    secret: str,
    field: str,
    given: str,
    kept: str,
) -> None:
    """Only an admin connects it; the secret never comes back; test,
    activation and health go through, and the scope keeps the vendor's ids."""
    vendor = stand_in()
    app.dependency_overrides[get_connector_transport] = lambda: httpx.MockTransport(vendor)
    try:
        _as(identity, acme, "member")
        body = {"type": kind, "display_name": kind, "config": config, "credentials": credentials}
        assert (await client.post(f"{API}/sources", json=body)).status_code == 403

        _as(identity, acme, "admin")
        catalog = (await client.get(f"{API}/connectors/catalog")).json()
        entry = next(item for item in catalog if item["key"] == kind)
        assert (entry["category"], entry["read_only"]) == ("docs", True)

        source = await _create(client, **body)
        assert secret not in json.dumps(source)
        url = f"{API}/sources/{source['id']}"

        tested = (await client.post(f"{url}/test")).json()
        assert tested["ok"] is True, tested
        assert sorted(tested["source"]["capabilities"]) == ["drives", "files"]

        offered = (await client.get(f"{url}/scope/options")).json()
        assert kept in [option["key"] for option in offered["options"]]
        scoped = await client.patch(url, json={"config": {**config, field: [given]}})
        assert scoped.json()["config"][field] == [kept]
        wrong = await client.patch(
            url, json={"config": {**config, field: ["http://10.0.0.1/admin"]}}
        )
        assert wrong.status_code == 422

        assert (await client.post(f"{url}/test")).json()["ok"] is True
        assert (await client.post(f"{url}/activate")).json()["status"] == "active"
        assert (await client.post(f"{url}/health-check")).json()["health_status"] == "healthy"

        _as(identity, acme, "member")
        assert secret not in (await client.get(url)).text
        assert (await client.post(f"{url}/test")).status_code == 403
    finally:
        app.dependency_overrides.pop(get_connector_transport, None)


# ── Datadog, end to end ──────────────────────────────────────────────────────


async def test_datadog_end_to_end(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    """Only an admin connects it; neither key comes back; the site is kept
    as Datadog names it and nothing else is accepted; test, scope,
    activation and health go through."""
    datadog = Datadog()
    app.dependency_overrides[get_connector_transport] = lambda: httpx.MockTransport(datadog)
    keys = {"application_key": DATADOG_APP_KEY, "api_key": DATADOG_API_KEY}
    try:
        _as(identity, acme, "member")
        body = {
            "type": "datadog",
            "display_name": "Datadog EU",
            "config": {"site": "https://app.datadoghq.eu/monitors/manage"},
            "credentials": keys,
        }
        assert (await client.post(f"{API}/sources", json=body)).status_code == 403

        _as(identity, acme, "admin")
        catalog = (await client.get(f"{API}/connectors/catalog")).json()
        entry = next(item for item in catalog if item["key"] == "datadog")
        assert (entry["category"], entry["read_only"]) == ("observability", True)

        source = await _create(client, **body)
        assert source["config"]["site"] == "datadoghq.eu"
        assert all(key not in json.dumps(source) for key in keys.values())
        url = f"{API}/sources/{source['id']}"
        elsewhere = await client.patch(url, json={"config": {"site": "10.0.0.1"}})
        assert elsewhere.status_code == 422

        tested = (await client.post(f"{url}/test")).json()
        assert tested["ok"] is True, tested
        assert sorted(tested["source"]["capabilities"]) == [
            "alerts",
            "events",
            "incidents",
            "logs",
            "metrics",
            "services",
        ]

        offered = (await client.get(f"{url}/scope/options")).json()
        assert [option["key"] for option in offered["options"]] == [
            "billing",
            "checkout",
            "search",
        ]
        scoped = await client.patch(
            url, json={"config": {"site": "datadoghq.eu", "services": ["Checkout"]}}
        )
        assert scoped.json()["config"]["services"] == ["checkout"]

        assert (await client.post(f"{url}/test")).json()["ok"] is True
        assert (await client.post(f"{url}/activate")).json()["status"] == "active"
        assert (await client.post(f"{url}/health-check")).json()["health_status"] == "healthy"

        _as(identity, acme, "member")
        page = (await client.get(url)).text
        assert all(key not in page for key in keys.values())
        assert (await client.post(f"{url}/test")).status_code == 403
    finally:
        app.dependency_overrides.pop(get_connector_transport, None)


async def test_pagerduty_end_to_end(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    """Only an admin connects it; the key never comes back; a service pasted
    as a link is kept as its id; test, activation and health go through."""
    pagerduty = PagerDuty()
    app.dependency_overrides[get_connector_transport] = lambda: httpx.MockTransport(pagerduty)
    try:
        _as(identity, acme, "member")
        body = {
            "type": "pagerduty",
            "display_name": "PagerDuty",
            "credentials": {"api_key": PAGERDUTY_KEY},
        }
        assert (await client.post(f"{API}/sources", json=body)).status_code == 403

        _as(identity, acme, "admin")
        catalog = (await client.get(f"{API}/connectors/catalog")).json()
        entry = next(item for item in catalog if item["key"] == "pagerduty")
        assert (entry["category"], entry["read_only"]) == ("observability", True)

        source = await _create(client, **body)
        assert PAGERDUTY_KEY not in json.dumps(source)
        url = f"{API}/sources/{source['id']}"

        tested = (await client.post(f"{url}/test")).json()
        assert tested["ok"] is True, tested
        assert sorted(tested["source"]["capabilities"]) == ["incidents", "services"]

        offered = (await client.get(f"{url}/scope/options")).json()
        assert [option["key"] for option in offered["options"]] == ["PCHKOUT", "PSEARCH"]
        link = "https://acme.pagerduty.com/service-directory/PCHKOUT"
        scoped = await client.patch(url, json={"config": {"services": [link]}})
        assert scoped.json()["config"]["services"] == ["PCHKOUT"]
        wrong = await client.patch(url, json={"config": {"region": "http://10.0.0.1"}})
        assert wrong.status_code == 422

        assert (await client.post(f"{url}/test")).json()["ok"] is True
        assert (await client.post(f"{url}/activate")).json()["status"] == "active"
        assert (await client.post(f"{url}/health-check")).json()["health_status"] == "healthy"

        _as(identity, acme, "member")
        assert PAGERDUTY_KEY not in (await client.get(url)).text
    finally:
        app.dependency_overrides.pop(get_connector_transport, None)


async def test_grafana_end_to_end(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    """Only an admin connects it; the token never comes back; an address
    that is not public https is refused on save; test, activation and health
    go through; there is no scope to choose."""
    grafana = Grafana()
    app.dependency_overrides[get_connector_transport] = lambda: httpx.MockTransport(grafana)
    try:
        _as(identity, acme, "admin")
        for address in ("http://grafana.acme.test", "https://10.0.0.5", "https://127.0.0.1"):
            refused = await client.post(
                f"{API}/sources",
                json={
                    "type": "grafana",
                    "display_name": "Grafana",
                    "config": {"base_url": address},
                    "credentials": {"token": GRAFANA_TOKEN},
                },
            )
            assert refused.status_code == 422, address

        source = await _create(
            client,
            type="grafana",
            display_name="Grafana",
            config={"base_url": f"https://{GRAFANA_HOST}"},
            credentials={"token": GRAFANA_TOKEN},
        )
        assert GRAFANA_TOKEN not in json.dumps(source)
        url = f"{API}/sources/{source['id']}"

        tested = (await client.post(f"{url}/test")).json()
        assert tested["ok"] is True, tested
        assert sorted(tested["source"]["capabilities"]) == ["alerts", "dashboards", "events"]
        assert (await client.get(f"{url}/scope/options")).status_code == 409

        assert (await client.post(f"{url}/activate")).json()["status"] == "active"
        assert (await client.post(f"{url}/health-check")).json()["health_status"] == "healthy"

        _as(identity, acme, "member")
        assert GRAFANA_TOKEN not in (await client.get(url)).text
    finally:
        app.dependency_overrides.pop(get_connector_transport, None)


async def test_postgresql_end_to_end(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An address that is not public is refused on save; the password never
    comes back, the hint names the role; test, scope, activation and health
    go through with a role that may read no row."""
    monkeypatch.setattr(PostgreSQLConnector, "_open", _local_postgresql)
    _as(identity, acme, "admin")
    for host in ("10.0.0.5", "127.0.0.1", "[::1]"):
        refused = await client.post(
            f"{API}/sources",
            json={
                "type": "postgresql",
                "display_name": "Billing",
                "config": {"host": host, "database": catalogue.database},
                "credentials": {"username": catalogue.reader, "password": catalogue.password},
            },
        )
        assert refused.status_code == 422, host

    source = await _create(
        client,
        type="postgresql",
        display_name="Billing",
        config={"host": "db.acme.example", "database": catalogue.database},
        credentials={"username": catalogue.reader, "password": catalogue.password},
    )
    assert catalogue.password not in json.dumps(source)
    assert source["credentials"]["hint"].startswith(catalogue.reader[:4])
    url = f"{API}/sources/{source['id']}"

    tested = (await client.post(f"{url}/test")).json()
    assert tested["ok"] is True, tested
    assert sorted(tested["source"]["capabilities"]) == ["schemas", "tables"]
    offered = (await client.get(f"{url}/scope/options")).json()
    assert catalogue.billing in [option["key"] for option in offered["options"]]
    assert catalogue.secret not in [option["key"] for option in offered["options"]]
    config = {"host": "db.acme.example", "database": catalogue.database}
    scoped = await client.patch(url, json={"config": {**config, "schemas": [catalogue.billing]}})
    assert scoped.json()["config"]["schemas"] == [catalogue.billing]
    wrong = await client.patch(url, json={"config": {**config, "host": "169.254.169.254"}})
    assert wrong.status_code == 422

    assert (await client.post(f"{url}/test")).json()["ok"] is True
    assert (await client.post(f"{url}/activate")).json()["status"] == "active"
    assert (await client.post(f"{url}/health-check")).json()["health_status"] == "healthy"

    _as(identity, acme, "member")
    assert catalogue.password not in (await client.get(url)).text


async def _local_postgresql(self: PostgreSQLConnector) -> asyncpg.Connection:
    """The tests' server, as tests/test_postgresql_connector.py reaches it."""
    return await asyncpg.connect(
        host=PG_SERVER.hostname,
        port=PG_SERVER.port or 5432,
        user=self.credentials.username,
        password=self.credentials.password.get_secret_value(),
        database=self.config.database,
    )


async def test_a_refused_scope_listing_is_an_answer_with_a_diagnostic(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    refusing = github({"/orgs/acme/repos": httpx.Response(401, json={"message": "Bad"})})
    app.dependency_overrides[get_connector_transport] = lambda: httpx.MockTransport(refusing)
    try:
        _as(identity, acme, "admin")
        source = await _create(
            client,
            type="github",
            display_name="Acme GitHub",
            config={"organization": "acme"},
            credentials={"token": GITHUB_TOKEN},
        )
        response = await client.get(f"{API}/sources/{source['id']}/scope/options")
    finally:
        app.dependency_overrides.pop(get_connector_transport, None)

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["diagnostic"]["code"] == "AUTH_INVALID"
    assert GITHUB_TOKEN not in response.text


async def test_a_connector_without_a_scope_says_so(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client)

    response = await client.get(f"{API}/sources/{source['id']}/scope/options")

    assert response.status_code == 409
    assert error_code(response) == "conflict"


async def test_the_scheduled_check_visits_every_activated_source(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    """What RQ runs every fifteen minutes: activated sources only, drafts left alone."""
    from leka.connectors.health import check_activated_sources

    _as(identity, acme, "admin")
    active = f"{API}/sources/{(await _create(client, display_name='On'))['id']}"
    await client.post(f"{active}/test")
    await client.post(f"{active}/activate")
    draft = f"{API}/sources/{(await _create(client, display_name='Off'))['id']}"

    outcome = await check_activated_sources()

    assert outcome.get("healthy", 0) >= 1
    assert (await client.get(f"{active}/health")).json()["health_status"] == "healthy"
    assert (await client.get(f"{draft}/health")).json()["health_status"] == "unknown"
