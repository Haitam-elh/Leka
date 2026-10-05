"""The context API's security, route by route (LEKA-376).

tests/test_route_protection.py says every route of the API asks for a
session or says why not; this says what each context route asks for, and
that it holds when asked.

What these protect: every context route asks a permission — reading,
`intention:read`; making, `intention:create`; the records behind an element
`source:read` too; archiving a context or changing how it follows the model,
its maker or an admin — so a new route cannot slip in unguarded; nobody
signed in is refused everywhere; another workspace's context is not there,
on any route, whatever is asked of it; a member archives or stops following
their own contexts, not another's, which takes an admin; a suspended
workspace reads its contexts and makes none.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import inspect
import uuid
from typing import Any

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy import text

from leka.api.context import _steward
from leka.db import session_factory, system_scope
from tests.conftest import FakeIdentity, error_code
from tests.test_context_engine import API, _create, model
from tests.test_knowledge_graph import BILLING
from tests.test_route_protection import _operations
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name

READ, MAKE, SOURCES = "intention:read", "intention:create", "source:read"

# What each context route asks for, besides a session.
EXPECTED: dict[tuple[str, str], set[str]] = {
    ("POST", "/api/v1/context"): {MAKE},
    ("POST", "/api/v1/context/intents/plan"): {READ},
    ("POST", "/api/v1/context/intents"): {MAKE},
    ("GET", "/api/v1/context"): {READ},
    ("GET", "/api/v1/context/feedback"): {READ},
    ("GET", "/api/v1/context/contract"): {READ},
    ("GET", "/api/v1/context/{context_id}"): {READ},
    ("PATCH", "/api/v1/context/{context_id}"): {MAKE},
    ("POST", "/api/v1/context/{context_id}/refresh"): {MAKE},
    ("POST", "/api/v1/context/{context_id}/expand"): {MAKE},
    ("POST", "/api/v1/context/{context_id}/compress"): {MAKE},
    ("POST", "/api/v1/context/{context_id}/intent"): {MAKE},
    ("GET", "/api/v1/context/{context_id}/checks"): {READ},
    ("POST", "/api/v1/context/{context_id}/archive"): {MAKE},
    ("GET", "/api/v1/context/{context_id}/versions"): {READ},
    ("GET", "/api/v1/context/{context_id}/assembled"): {READ},
    ("GET", "/api/v1/context/{context_id}/diff"): {READ},
    ("GET", "/api/v1/context/{context_id}/quality"): {READ},
    ("POST", "/api/v1/context/{context_id}/feedback"): {MAKE},
    ("GET", "/api/v1/context/{context_id}/elements/{ref_id}"): {READ},
    ("GET", "/api/v1/context/{context_id}/elements/{ref_id}/evidence"): {READ, SOURCES},
    ("GET", "/api/v1/context/{context_id}/events"): {READ},
}
STEWARDED = {
    ("PATCH", "/api/v1/context/{context_id}"),
    ("POST", "/api/v1/context/{context_id}/archive"),
}
# What a request needs to reach its route's checks.
BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/api/v1/context"): {"title": "x", "purpose": "Why is it slow?"},
    ("POST", "/api/v1/context/intents/plan"): {"text": "Pourquoi est-il lent ?"},
    ("POST", "/api/v1/context/intents"): {"text": "Pourquoi est-il lent ?"},
    ("PATCH", "/api/v1/context/{context_id}"): {"follow": False},
    ("POST", "/api/v1/context/{context_id}/intent"): {"text": "Pourquoi est-il lent ?"},
    ("POST", "/api/v1/context/{context_id}/feedback"): {"verdict": "missing", "note": "x"},
}
QUERIES: dict[tuple[str, str], dict[str, Any]] = {
    ("GET", "/api/v1/context/{context_id}/diff"): {"from": 1, "to": 2},
}


def _routes() -> list[tuple[str, str, APIRoute]]:
    """The context routes, walked as tests/test_route_protection.py walks
    them — app.routes is not flat, and a list found empty would pass every
    check below, meaning nothing."""
    found = [(m, p, r) for m, p, r in _operations() if p.startswith("/api/v1/context")]
    assert len(found) >= len(EXPECTED), "the context routes were not found"
    return found


def _calls(dependant: Any) -> list[Any]:
    found = [dependant.call] if dependant.call is not None else []
    for sub in dependant.dependencies:
        found += _calls(sub)
    return found


def _permissions(route: APIRoute) -> set[str]:
    """The permissions a route's dependencies ask — require_permission's."""
    asked: set[str] = set()
    for call in _calls(route.dependant):
        if call.__qualname__.startswith("require_permission."):
            asked.add(str(inspect.getclosurevars(call).nonlocals["permission"].value))
    return asked


def _url(path: str, context_id: object, ref_id: object) -> str:
    return path.replace("{context_id}", str(context_id)).replace("{ref_id}", str(ref_id))


def test_every_context_route_asks_what_it_should() -> None:
    routes = {(method, path): route for method, path, route in _routes()}
    assert set(routes) == set(EXPECTED), "a context route is new, gone or renamed: say what it asks"
    for key, route in routes.items():
        assert _permissions(route) == EXPECTED[key], key
        assert (_steward in _calls(route.dependant)) == (key in STEWARDED), key


async def test_nobody_signed_in_is_refused_everywhere(client: AsyncClient) -> None:
    for method, path, _route in _routes():
        response = await client.request(
            method,
            _url(path, uuid.uuid4(), uuid.uuid4()),
            json=BODIES.get((method, path)),
            params=QUERIES.get((method, path)),
        )
        assert response.status_code == 401, (method, path, response.text)
        assert error_code(response) == "not_authenticated"


async def test_another_workspace_s_context_is_not_there_on_any_route(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    made = await _create(client, model)
    _as(identity, acme, "other_admin")
    for method, path, _route in _routes():
        if "{context_id}" not in path:
            continue
        response = await client.request(
            method,
            _url(path, made["context_id"], model[BILLING]),
            json=BODIES.get((method, path)),
            params=QUERIES.get((method, path)),
        )
        assert response.status_code == 404, (method, path, response.text)
    # Nor listed, nor found by what it holds.
    listed = await client.get(API, params={"holds": str(model[BILLING])})
    assert listed.json()["data"] == []


async def test_archiving_or_unfollowing_another_s_context_takes_an_admin(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    mine = (await _create(client, model))["context_id"]
    _as(identity, acme, "admin")
    theirs = (await _create(client, model, purpose="Who runs Billing API?"))["context_id"]

    _as(identity, acme, "member")
    for refused in (
        await client.patch(f"{API}/{theirs}", json={"follow": False}),
        await client.post(f"{API}/{theirs}/archive"),
    ):
        assert refused.status_code == 403, refused.text
        assert error_code(refused) == "permission_denied"
    # Making it again is anyone's: it changes nothing anyone reads of it.
    assert (await client.post(f"{API}/{theirs}/refresh")).status_code == 200
    assert (await client.patch(f"{API}/{mine}", json={"follow": False})).status_code == 200
    assert (await client.post(f"{API}/{mine}/archive")).status_code == 200

    _as(identity, acme, "admin")
    assert (await client.post(f"{API}/{theirs}/archive")).status_code == 200


async def test_a_suspended_workspace_reads_its_contexts_and_makes_none(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    made = await _create(client, model)
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text("UPDATE workspaces SET status = 'suspended' WHERE id = :id"),
                {"id": acme["acme"]},
            )
            await session.commit()

    for read in (
        await client.get(API),
        await client.get(f"{API}/{made['context_id']}/assembled"),
        await client.get(f"{API}/{made['context_id']}/quality"),
    ):
        assert read.status_code == 200, read.text
    for write in (
        await client.post(API, json=BODIES[("POST", "/api/v1/context")]),
        await client.post(f"{API}/{made['context_id']}/refresh"),
        await client.post(
            f"{API}/{made['context_id']}/feedback", json={"verdict": "missing", "note": "x"}
        ),
    ):
        assert write.status_code == 403, write.text
