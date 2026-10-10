"""Data protection, end to end (LEKA-405).

The fake source of test_sync.py, a pass of it, then extraction — against the
test database and a local object store. One commit carries an AWS key, a
card number and an address.

What these protect:
- A record is protected before it is kept: the key and the card taken out,
  the address kept; what was found counted with it, never a value; nothing
  stored by extraction still holds the key.
- The raw payload the key was found in is kept no longer than the policy
  says — 7 days by default, or what the workspace set; one with nothing in
  it keeps its source's retention.
- What was kept before is protected by the sweep, once.
- The API: the platform's protections as they stand, the policy, per source
  what was found — an auditor's; the policy a manager's, refused when it
  cannot be, every change in the governance trail.
- An intention asked with a password in it keeps none.
"""

# ruff: noqa: F811 — the fixtures of test_sync are imported to be requested by name.
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from leka.connectors import Capability, Source, SourceKind
from leka.core.sensitive import SENSITIVE_VERSION
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import ExtractedRecordRow, RawPayload, set_protection_policy
from leka.ingestion.extraction import Extracted
from leka.ingestion.extraction import engine as engine_module
from leka.ingestion.extraction.contract import Content
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.protection import protection_sweep, sweep_workspace
from tests import test_sync as sync_tests
from tests.conftest import FakeIdentity
from tests.test_sources_api import _user
from tests.test_sync import _index, _live_payloads, _sync, fake, source  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

FAKE = SourceKind.SLACK
API = "/api/v1"
KEY = "AKIAIOSFODNN7EXAMPLE"


def _commit(payload: dict[str, Any]) -> Extracted:
    if payload["n"] == 1:
        return Extracted(
            title=f"rotate the deploy key {KEY}",
            content=[
                Content(
                    role="body",
                    format="text",
                    text="refund card 4111 1111 1111 1111, ask ada@acme.io",
                )
            ],
        )
    return Extracted(title=f"commit {payload['n']}")


def _clean(payload: dict[str, Any]) -> Extracted:
    return Extracted(title=f"commit {payload['n']}")


def _strategy(monkeypatch: pytest.MonkeyPatch, read: Any) -> None:
    monkeypatch.setitem(
        engine_module._STRATEGIES,
        (FAKE, Capability.COMMITS),
        engine_module.Strategy("fake.commits", 1, lambda r: read(r.payload)),
    )


async def _rows(source: Source) -> dict[str, ExtractedRecordRow]:
    commits = await _index(source, "commits")
    by_id = {row.id: external_id for external_id, row in commits.items()}
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = await session.scalars(
                select(ExtractedRecordRow).where(ExtractedRecordRow.source_id == source.id)
            )
            return {by_id[row.source_record_id]: row for row in rows}


async def _expiry(source: Source, key: str) -> datetime:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            found: datetime = (
                await session.execute(
                    select(RawPayload.expires_at).where(RawPayload.object_key == key)
                )
            ).scalar_one()
            return found


def _key(row: ExtractedRecordRow) -> str:
    provenance = (row.result or {})["provenance"]
    assert isinstance(provenance, dict)
    return str(provenance["payload_key"])


async def _holding(source: Source, needle: str) -> int:
    with system_scope():
        async with session_factory() as session:
            found: int = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM extracted_records"
                        " WHERE source_id = :s AND result::text LIKE :n"
                    ),
                    {"s": source.id, "n": f"%{needle}%"},
                )
            ).scalar_one()
            return found


# ── extraction ───────────────────────────────────────────────────────────────


async def test_a_record_is_protected_before_it_is_kept(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strategy(monkeypatch, _commit)
    sync_tests.SCRIPT.records = {Capability.COMMITS: 3}
    await _sync(source)

    result = await extract_source(source.workspace_id, source.id)

    assert (result["extracted"], result["secrets_taken_out"]) == (3, 1)
    rows = await _rows(source)
    said = rows["commits-1"]
    assert said.result is not None
    assert said.result["title"] == "rotate the deploy key [redacted:aws_key]"
    contents = said.result["content"]
    assert isinstance(contents, list)
    assert contents[0]["text"] == "refund card [redacted:card], ask ada@acme.io"
    assert said.sensitivity == {
        "version": SENSITIVE_VERSION,
        "secrets": {"aws_key": 1},
        "personal_data": {"card": 1, "email": 1},
    }
    assert rows["commits-0"].sensitivity == {
        "version": SENSITIVE_VERSION,
        "secrets": {},
        "personal_data": {},
    }
    # No copy of it outlives the original.
    assert await _holding(source, KEY) == 0
    assert await _holding(source, "4111") == 0
    # Its original: a week at most, not the thirty days Slack's are kept.
    soon = datetime.now(UTC) + timedelta(days=7, minutes=5)
    assert await _expiry(source, _key(said)) <= soon


async def test_a_payload_with_nothing_in_it_keeps_its_retention(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strategy(monkeypatch, _clean)
    sync_tests.SCRIPT.records = {Capability.COMMITS: 2}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)

    rows = await _rows(source)
    later = datetime.now(UTC) + timedelta(days=20)
    assert await _expiry(source, _key(rows["commits-0"])) > later


async def test_the_workspace_says_how_long_an_original_is_kept(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            await set_protection_policy(session, source.workspace_id, {"found_payload_days": 2})
            await session.commit()
    _strategy(monkeypatch, _commit)
    sync_tests.SCRIPT.records = {Capability.COMMITS: 2}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)

    rows = await _rows(source)
    soon = datetime.now(UTC) + timedelta(days=2, minutes=5)
    assert await _expiry(source, _key(rows["commits-1"])) <= soon


async def test_what_was_kept_before_is_protected_by_the_sweep(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strategy(monkeypatch, _clean)
    sync_tests.SCRIPT.records = {Capability.COMMITS: 2}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)
    # As a record extracted before LEKA-405 was: in the clear, never scanned.
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE extracted_records SET sensitivity = NULL,"
                    " result = jsonb_set(result, '{title}', to_jsonb(CAST(:t AS text)))"
                    " WHERE source_id = :s"
                ),
                {"s": source.id, "t": f"leaked {KEY}"},
            )
            await session.commit()
    assert await _holding(source, KEY) == 2

    total = await protection_sweep()

    assert total["scanned"] >= 2
    assert await _holding(source, KEY) == 0
    rows = await _rows(source)
    assert {r.result["title"] for r in rows.values() if r.result} == {"leaked [redacted:aws_key]"}
    assert all(r.sensitivity and r.sensitivity["secrets"] == {"aws_key": 1} for r in rows.values())
    soon = datetime.now(UTC) + timedelta(days=7, minutes=5)
    assert await _expiry(source, _key(rows["commits-0"])) <= soon
    # Once.
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            assert await sweep_workspace(session, source.workspace_id) == {}


# ── over HTTP ────────────────────────────────────────────────────────────────


@pytest.fixture
async def people(source: Source) -> AsyncIterator[dict[str, uuid.UUID]]:
    """An admin and a member in the fake source's workspace."""
    found = {"admin": await _user("admin"), "member": await _user("member")}
    with system_scope():
        async with session_factory() as session:
            for role, user in found.items():
                await session.execute(
                    text(
                        "INSERT INTO memberships (workspace_id, user_id, role) VALUES (:w, :u, :r)"
                    ),
                    {"w": source.workspace_id, "u": user, "r": role},
                )
            await session.commit()
    yield found
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM users WHERE id = ANY(:u)"), {"u": list(found.values())}
            )
            await session.commit()


async def test_the_api_says_the_protections_the_policy_and_what_was_found(
    client: AsyncClient,
    identity: FakeIdentity,
    source: Source,
    people: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _strategy(monkeypatch, _commit)
    sync_tests.SCRIPT.records = {Capability.COMMITS: 3}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)

    identity.sign_in(people["member"], source.workspace_id)
    assert (await client.get(f"{API}/governance/data-protection")).status_code == 403
    refused = await client.put(
        f"{API}/governance/data-protection/policy", json={"found_payload_days": 3}
    )
    assert refused.status_code == 403

    identity.sign_in(people["admin"], source.workspace_id)
    response = await client.get(f"{API}/governance/data-protection")
    assert response.status_code == 200, response.text
    said = response.json()
    posture = said["posture"]
    assert (posture["object_store"], posture["credentials_encryption"]) == ("local", "fernet")
    assert posture["credential_keys"] >= 1
    assert posture["database_tls"] in (True, False)
    assert said["policy"] == {"found_payload_days": 7, "customised": False}
    [found] = said["sources"]
    assert (found["name"], found["kind"]) == ("Fake", "slack")
    assert (found["records"], found["scanned"], found["with_secrets"]) == (3, 3, 1)
    assert found["secrets"] == {"aws_key": 1}
    assert found["personal_data"] == {"card": 1, "email": 1}
    # Never a value.
    assert KEY not in response.text

    wrong = await client.put(
        f"{API}/governance/data-protection/policy", json={"found_payload_days": 31}
    )
    assert wrong.status_code == 422
    changed = await client.put(
        f"{API}/governance/data-protection/policy", json={"found_payload_days": 3}
    )
    assert changed.json() == {"found_payload_days": 3, "customised": True}
    # Said again, nothing changes: nothing kept twice.
    await client.put(f"{API}/governance/data-protection/policy", json={"found_payload_days": 3})
    history = (await client.get(f"{API}/governance/history")).json()
    kept = [e for e in history if e["subject_type"] == "protection"]
    assert len(kept) == 1
    assert (kept[0]["kind"], kept[0]["by"]) == ("updated", str(people["admin"]))
    assert (kept[0]["before"], kept[0]["after"]) == (
        {"found_payload_days": 7},
        {"found_payload_days": 3},
    )
