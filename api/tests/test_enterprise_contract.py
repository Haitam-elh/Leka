"""An Enterprise organisation's contract and logo (2026-10-25).

Acme is put under an Enterprise contract, as `python -m leka.ops.enterprise`
leaves it; Globex stays on a public plan.

What these protect:
- « Contrat »: its type, the organisation, since when, its members, its
  dedicated contact — 404 on a public plan. Never a price, never credits.
- Nothing commercial under a contract, refused by the server: no checkout
  of a plan or an agent, no Stripe portal, no renewal changed (409
  `enterprise_contract`).
- No question before a source (2026-10-25: one was asked with nothing
  connected): 409 `source_required`, nothing kept, until a source is
  connected — a draft is not; a public plan asks as before.
- Its logo, given by its admin: a PNG, JPEG or WebP image, 512 KB at most,
  its bytes what its type says — no SVG; read by its members only; replaced,
  the one before removed; removed, its name again. Never set by the
  workspace's preferences, nor its contract.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from leka.connectors import Source, SourceKind, SourceStatus
from leka.db import session_factory, workspace_scope
from leka.governance import set_plan
from leka.platform import LocalObjectStore, Workspace, storage
from tests.conftest import FakeIdentity, error_code
from tests.test_billing_stripe import FakeStripe, _synced, stripe
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

_ = stripe  # a fixture, requested by name
API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalObjectStore:
    kept = LocalObjectStore(tmp_path)
    monkeypatch.setattr(storage, "_store", kept)
    return kept


async def _contracted(workspace: uuid.UUID) -> None:
    """As the provisioning leaves it: the plan, the contract kept with it."""
    with workspace_scope(workspace):
        async with session_factory() as session:
            await set_plan(session, workspace, "enterprise", by="tests", reason="a contract")
            found = await session.get(Workspace, workspace)
            assert found is not None
            found.settings = {
                **(found.settings or {}),
                "enterprise": {
                    "type": "Entreprise",
                    "since": "2026-10-25",
                    "contact": {"name": "Ada Lovelace", "email": "ada@leka.example"},
                },
            }
            await session.commit()


async def test_its_contract_said_never_a_price(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    await _contracted(acme["acme"])
    _as(identity, acme, "member")
    said = await client.get(f"{API}/billing/contract")
    assert said.status_code == 200, said.text
    contract = said.json()
    assert contract == {
        "type": "enterprise",
        "organisation": contract["organisation"],
        "since": "2026-10-25",
        "members": 2,
        "contact": {"name": "Ada Lovelace", "email": "ada@leka.example"},
    }
    assert "€" not in said.text and "credit" not in said.text
    # A public plan has none.
    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/billing/contract")).status_code == 404


async def test_nothing_is_bought_under_a_contract(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    await _synced(stripe)
    await _contracted(acme["acme"])
    _as(identity, acme, "admin")
    asked = [
        ("/billing/checkout", {"plan": "business", "interval": "month"}),
        ("/billing/add-ons/checkout", {"kind": "agent", "key": "code-review"}),
        ("/billing/portal", None),
        ("/billing/subscription/renewal", {"renew": False}),
    ]
    for path, body in asked:
        refused = await client.post(f"{API}{path}", json=body)
        assert refused.status_code == 409, (path, refused.text)
        assert refused.json()["error"]["details"][0]["message"] == "enterprise_contract", path
    # A public plan buys as before.
    _as(identity, acme, "other_admin")
    bought = await client.post(
        f"{API}/billing/checkout", json={"plan": "starter", "interval": "month"}
    )
    assert bought.status_code == 200, bought.text


async def test_its_logo_given_by_its_admin_read_by_its_members(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    store: LocalObjectStore,
) -> None:
    _as(identity, acme, "admin")
    url = f"{API}/workspaces/current/logo"
    assert (await client.get(url)).status_code == 404
    given = await client.put(url, content=PNG, headers={"Content-Type": "image/png"})
    assert given.status_code == 200, given.text
    first = given.json()["settings"]["logo"]
    assert first["type"] == "image/png"
    assert first["key"].startswith(f"{acme['acme']}/branding/")
    _as(identity, acme, "member")
    read = await client.get(url)
    assert (read.status_code, read.content) == (200, PNG)
    assert read.headers["content-type"] == "image/png"
    assert read.headers["x-content-type-options"] == "nosniff"
    # Only its admin gives one.
    refused = await client.put(url, content=JPEG, headers={"Content-Type": "image/jpeg"})
    assert refused.status_code == 403
    # Another organisation reads its own: none.
    _as(identity, acme, "other_admin")
    assert (await client.get(url)).status_code == 404

    _as(identity, acme, "admin")
    replaced = await client.put(url, content=JPEG, headers={"Content-Type": "image/jpeg"})
    assert replaced.status_code == 200, replaced.text
    assert not await store.exists(first["key"])
    assert (await client.get(url)).content == JPEG
    # What it is not: refused, nothing kept.
    for body, kind, code in (
        (SVG, "image/svg+xml", 415),
        (PNG, "text/html", 415),
        (JPEG, "image/png", 422),
        (b"", "image/png", 422),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * (512 * 1024), "image/png", 413),
    ):
        said = await client.put(url, content=body, headers={"Content-Type": kind})
        assert said.status_code == code, (kind, said.text)
    assert (await client.get(url)).content == JPEG
    # Removed: its name again.
    assert (await client.delete(url)).status_code == 204
    assert (await client.get(url)).status_code == 404
    assert (await client.delete(url)).status_code == 204


async def test_neither_its_logo_nor_its_contract_is_a_preference(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    await _contracted(acme["acme"])
    _as(identity, acme, "admin")
    for key, value in (
        ("enterprise", {"contact": {"name": "Moi"}}),
        ("logo", {"key": f"{acme['globex']}/branding/logo.png", "type": "image/png"}),
    ):
        changed = await client.patch(f"{API}/workspaces/current", json={"settings": {key: value}})
        assert changed.status_code == 422, key
        assert error_code(changed) == "validation_failed"
    contract = (await client.get(f"{API}/billing/contract")).json()
    assert contract["contact"]["name"] == "Ada Lovelace"


async def _source(workspace: uuid.UUID, status: SourceStatus) -> uuid.UUID:
    with workspace_scope(workspace):
        async with session_factory() as session:
            row = Source(
                workspace_id=workspace,
                kind=SourceKind.CONFLUENCE,
                name=f"Confluence ({status.value})",
                status=status,
                config={},
            )
            session.add(row)
            await session.commit()
            return row.id


async def test_no_question_before_a_source(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    await _contracted(acme["acme"])
    _as(identity, acme, "member")
    words = {"text": "Pourquoi Billing API est lente ?"}
    refused = await client.post(f"{API}/intentions", json=words)
    assert refused.status_code == 409, refused.text
    assert error_code(refused) == "source_required"
    assert (await client.get(f"{API}/intentions")).json()["data"] == []
    # Being set up is not connected.
    await _source(acme["acme"], SourceStatus.DRAFT)
    assert (await client.post(f"{API}/intentions", json=words)).status_code == 409
    await _source(acme["acme"], SourceStatus.ACTIVE)
    asked = await client.post(f"{API}/intentions", json=words)
    assert asked.status_code == 201, asked.text
    # A public plan asks as before, sources or not.
    _as(identity, acme, "other_admin")
    assert (await client.post(f"{API}/intentions", json=words)).status_code == 201
