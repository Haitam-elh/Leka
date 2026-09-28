"""A source's settings over the API (LEKA-351): read, checked, versioned, audited.

The fake connector of test_sources_api.py, whose credentials "see" two
repositories. What is asserted: anyone reads the settings, only a manager
checks or changes them; errors are refused with each one named, warnings are
saved and said; every change is a new version with its author and an event;
a scope change on an active source publishes the event its full pass hangs
from; another workspace sees none of it.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.background import Event
from leka.connectors import ScopeListing, ScopeOption
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity, error_code
from tests.test_sources_api import (  # noqa: F401 — fixtures
    FakeConnector,
    _as,
    _create,
    acme,
    fake_connector,
)

pytestmark = pytest.mark.integration

API = "/api/v1"
SCOPE = {"include": ["acme/*"], "exclude": ["acme/legacy-*"]}
MAPPING = {
    "entity_types": {"issues": "incident"},
    "states": {"QA Review": "in_progress"},
    "tag_keys": {"environment": ["stage"], "service": [], "owner": []},
}


@pytest.fixture(autouse=True)
def visible(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the fake credentials can see: two repositories."""

    async def list_scope(self: FakeConnector) -> ScopeListing:
        return ScopeListing(
            options=[ScopeOption(key=k, name=k) for k in ("acme/api", "acme/legacy-billing")]
        )

    monkeypatch.setattr(FakeConnector, "list_scope", list_scope, raising=False)


def _url(source: dict[str, Any], suffix: str = "") -> str:
    return f"{API}/sources/{source['id']}/settings{suffix}"


async def _activated(client: AsyncClient) -> dict[str, Any]:
    source = await _create(client, display_name=f"Fake {uuid.uuid4().hex[:6]}")
    await client.post(f"{API}/sources/{source['id']}/test")
    activated: dict[str, Any] = (await client.post(f"{API}/sources/{source['id']}/activate")).json()
    return activated


async def test_a_new_source_has_the_defaults_at_version_zero(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client)

    _as(identity, acme, "member")
    read = (await client.get(_url(source))).json()

    assert read["version"] == 0
    assert read["settings"]["scope"] == {"include": [], "exclude": []}
    assert read["settings"]["mapping"]["entity_types"] == {}


async def test_settings_are_saved_as_versions_with_their_author_and_an_event(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client)  # before activation: allowed

    first = await client.put(_url(source), json={"scope": SCOPE, "mapping": MAPPING})
    same = await client.put(_url(source), json={"scope": SCOPE, "mapping": MAPPING})
    second = await client.put(_url(source), json={"scope": SCOPE, "mapping": {}})

    assert first.status_code == 200
    assert (first.json()["version"], first.json()["changed"]) == (1, ["scope", "mapping"])
    assert first.json()["full_sync_queued"] is False  # a draft: nothing to sync yet
    assert (same.json()["version"], same.json()["changed"]) == (1, [])
    assert (second.json()["version"], second.json()["changed"]) == (2, ["mapping"])
    read = (await client.get(_url(source))).json()
    assert read["version"] == 2 and read["settings"]["scope"] == SCOPE

    versions = (await client.get(_url(source, "/versions"))).json()["data"]
    assert [v["version"] for v in versions] == [2, 1]
    assert {v["created_by"] for v in versions} == {str(acme["admin"])}
    events = (await client.get(f"{API}/sources/{source['id']}/events")).json()["data"]
    changed = [e for e in events if e["type"] == "settings_changed"]
    assert [e["payload"]["version"] for e in changed] == [2, 1]


async def test_a_retention_of_its_own_is_a_version_and_the_policy_is_said(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client)

    read = (await client.get(_url(source))).json()
    shorter = await client.put(_url(source), json={"retention": {"days": 14}})
    longer = await client.put(_url(source), json={"retention": {"days": 60}})
    refused = await client.put(_url(source), json={"retention": {"days": 0}})

    assert read["retention_policy_days"] == 30  # the fake's kind, Slack
    assert read["settings"]["retention"] == {"days": None}
    assert (shorter.json()["changed"], shorter.json()["findings"]) == (["retention"], [])
    assert longer.status_code == 200
    assert [f["path"] for f in longer.json()["findings"]] == ["retention.days"]
    assert refused.status_code == 422
    versions = (await client.get(_url(source, "/versions"))).json()["data"]
    assert [v["retention"] for v in versions] == [{"days": 60}, {"days": 14}]


async def test_errors_are_refused_each_one_named(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client)

    refused = await client.put(
        _url(source),
        json={
            "scope": {"include": ["acme/*"], "exclude": ["acme/*"]},
            "mapping": {"entity_types": {"commits": "incident"}, "states": {"Parked": "asleep"}},
        },
    )

    assert refused.status_code == 422
    assert error_code(refused) == "validation_failed"
    fields = {d["field"] for d in refused.json()["error"]["details"]}
    assert fields == {"scope", "mapping.entity_types.commits", "mapping.states.Parked"}
    assert (await client.get(_url(source))).json()["version"] == 0  # nothing saved


async def test_the_check_says_what_the_credentials_cannot_see(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client)

    checked = await client.post(
        _url(source, "/check"), json={"scope": {"include": ["acme/api", "acme/apii"]}}
    )

    assert checked.status_code == 200
    assert [(f["level"], f["path"]) for f in checked.json()["findings"]] == [
        ("warning", "scope.include[1]")
    ]
    assert (await client.get(_url(source))).json()["version"] == 0  # a check saves nothing


async def test_a_scope_change_on_an_active_source_queues_its_full_pass(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)

    saved = (await client.put(_url(source), json={"scope": SCOPE})).json()
    mapping_only = (
        await client.put(_url(source), json={"scope": SCOPE, "mapping": MAPPING})
    ).json()

    assert saved["full_sync_queued"] is True
    assert mapping_only["full_sync_queued"] is False
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            rows = await session.execute(select(Event).where(Event.type == "source.scope_changed"))
            mine = [e for e in rows.scalars() if e.payload["source_id"] == source["id"]]
    assert [e.payload["version"] for e in mine] == [1]


async def test_a_member_reads_the_settings_but_cannot_change_or_check_them(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client)

    _as(identity, acme, "member")
    assert (await client.get(_url(source))).status_code == 200
    assert (await client.get(_url(source, "/versions"))).status_code == 200
    assert (await client.put(_url(source), json={"scope": SCOPE})).status_code == 403
    assert (await client.post(_url(source, "/check"), json={})).status_code == 403


async def test_another_workspace_sees_none_of_it(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client)

    _as(identity, acme, "other_admin")
    assert (await client.get(_url(source))).status_code == 404
    assert (await client.put(_url(source), json={"scope": SCOPE})).status_code == 404
    assert (await client.get(_url(source, "/versions"))).status_code == 404
