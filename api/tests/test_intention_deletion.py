"""« Supprimer l'analyse » (LEKA-487), on Acme (test_sources_api).

What these protect: an intention deleted whatever its status — by its asker
or who may approve, never another member; gone at once when nothing works
on it: read, listed, counted, its history — 404 everywhere; while an
analysis still runs: stopped, the intention out of every list and refused
any move, gone at the sweep once past its grace — not before; what the bill
reads (its usage, its runs) kept; another workspace's is 404.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from leka.db import session_factory, system_scope, workspace_scope
from leka.intentions import Intention, IntentionAnalysis, deletion
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_intentions_api import API, ASKED, _ask, _get
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name


async def _rows(intention_id: str) -> int:
    with system_scope():
        async with session_factory() as session:
            found = await session.scalar(
                select(func.count())
                .select_from(Intention)
                .where(Intention.id == uuid.UUID(intention_id))
            )
            return int(found or 0)


async def test_deleted_at_once_by_its_asker_or_an_approver_never_another(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    theirs = (await _ask(client))["intention"]
    _as(identity, acme, "member")
    mine = (await _ask(client, "Qui est responsable de Billing API ?"))["intention"]
    before = await _get(client, "/counts")

    refused = await client.delete(f"{API}/{theirs['id']}")
    assert refused.status_code == 403
    assert await _rows(theirs["id"]) == 1

    gone = await client.delete(f"{API}/{mine['id']}")
    assert gone.status_code == 200, gone.text
    assert gone.json() == {"status": "deleted"}
    assert await _rows(mine["id"]) == 0
    assert (await client.get(f"{API}/{mine['id']}")).status_code == 404
    assert (await client.get(f"{API}/{mine['id']}/history")).status_code == 404
    assert mine["id"] not in {i["id"] for i in (await _get(client))["data"]}
    assert (await _get(client, "/counts"))["all"] == before["all"] - 1
    # Deleted twice — a click twice: not found, nothing else.
    assert (await client.delete(f"{API}/{mine['id']}")).status_code == 404

    # Who may approve deletes anyone's, whatever its status: cancelled, archived.
    _as(identity, acme, "member")
    other = (await _ask(client, ASKED))["intention"]
    await client.post(f"{API}/{other['id']}/cancel", json={})
    await client.post(f"{API}/{other['id']}/archive")
    _as(identity, acme, "admin")
    assert (await client.delete(f"{API}/{other['id']}")).json() == {"status": "deleted"}
    assert (await client.delete(f"{API}/{theirs['id']}")).json() == {"status": "deleted"}


async def test_while_its_analysis_runs_pending_then_gone_at_the_sweep(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "member")
    intention = (await _ask(client))["intention"]
    analysis = uuid.uuid4()
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            session.add(
                IntentionAnalysis(
                    workspace_id=acme["acme"],
                    id=analysis,
                    intention_id=uuid.UUID(intention["id"]),
                    number=1,
                    trigger="created",
                    status="running",
                    intention_version=1,
                    started_at=datetime.now(UTC),
                    selection=[],
                    steps=[],
                    detail={},
                )
            )
            await session.commit()

    said = await client.delete(f"{API}/{intention['id']}")
    assert said.json() == {"status": "pending"}
    # Stopped; out of every list, archived included; read as gone; no move.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            row = await session.get(IntentionAnalysis, analysis)
            assert row is not None and row.status == "stopped"
    assert (await client.get(f"{API}/{intention['id']}")).status_code == 404
    for phase in (None, "archived"):
        listed = await _get(client, **({"phase": phase} if phase else {}))
        assert intention["id"] not in {i["id"] for i in listed["data"]}
    assert (await _get(client, "/counts"))["archived"] == 0
    assert (await client.post(f"{API}/{intention['id']}/restore")).status_code == 404
    assert (await client.post(f"{API}/{intention['id']}/analyse")).status_code in (404, 409)
    assert (await client.delete(f"{API}/{intention['id']}")).json() == {"status": "pending"}

    # The sweep: not before its grace, then gone.
    assert (await deletion.sweep())["deleted"] == 0
    assert await _rows(intention["id"]) == 1
    later = datetime.now(UTC) + deletion.GRACE + timedelta(minutes=1)
    assert (await deletion.sweep(now=later))["deleted"] == 1
    assert await _rows(intention["id"]) == 0


async def test_another_workspace_s_is_not_found(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    intention = (await _ask(client))["intention"]
    identity.sign_in(acme["admin"], uuid.uuid4())
    assert (await client.delete(f"{API}/{intention['id']}")).status_code in (403, 404)
    assert await _rows(intention["id"]) == 1
