"""The night review, an alert each workspace chooses (LEKA-526).

What these protect: on until someone chooses — what every workspace had
before; said with when it runs and whether the reader may change it; turned
off or on only by who manages the sources and the alerts, kept on the
server — the same answer to another session — and in the audit trail, once
per change; off, the night makes no review and the morning tells nothing,
while what was reviewed before stays and a person may still ask for one;
on again, the next night reviews.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.db import session_factory, system_scope, workspace_scope
from leka.governance import AuditEvent
from leka.identity import EmailMessage, User
from leka.monitoring import NightReview, set_night_review_enabled
from leka.monitoring.night import review_every_workspace
from leka.notifications import morning
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_morning_report import POINTS, _kept, _review
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/monitoring/night-review"
SETTING = f"{API}/setting"


async def _audited(workspace_id: uuid.UUID) -> list[str]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = (
                await session.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.action.like("monitoring.night_review%"))
                    .order_by(AuditEvent.at)
                )
            ).all()
    return [row.action for row in rows]


async def _night_reviews(workspace_id: uuid.UUID) -> list[NightReview]:
    with system_scope():
        async with session_factory() as session:
            return list(
                (
                    await session.scalars(
                        select(NightReview).where(
                            NightReview.workspace_id == workspace_id, NightReview.trigger == "night"
                        )
                    )
                ).all()
            )


async def test_on_until_someone_chooses_said_with_when_and_who_may_change_it(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "member")
    said: dict[str, Any] = (await client.get(SETTING)).json()
    assert (said["enabled"], said["default"], said["can_change"]) == (True, True, False)
    assert said["hours_utc"][0] == "21:30" and said["hours_utc"][-1] == "05:30"
    # A member reads it; only who manages the sources and the alerts turns it.
    refused = await client.put(SETTING, json={"enabled": False})
    assert refused.status_code == 403
    _as(identity, acme, "admin")
    assert (await client.get(SETTING)).json()["can_change"] is True
    assert (await client.put(SETTING, json={"enabled": False, "when": "now"})).status_code == 422


async def test_turned_off_on_the_server_and_in_the_audit_trail_once_per_change(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    off = await client.put(SETTING, json={"enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False
    # Another session, the same answer: the server's, not the page's.
    _as(identity, acme, "member")
    assert (await client.get(SETTING)).json()["enabled"] is False
    _as(identity, acme, "admin")
    # The same state again changes nothing, and records nothing.
    assert (await client.put(SETTING, json={"enabled": False})).json()["enabled"] is False
    assert await _audited(acme["acme"]) == ["monitoring.night_review_disabled"]
    assert (await client.put(SETTING, json={"enabled": True})).json()["enabled"] is True
    assert await _audited(acme["acme"]) == [
        "monitoring.night_review_disabled",
        "monitoring.night_review_enabled",
    ]


async def test_off_the_night_makes_no_review_what_was_stays_and_a_person_may_ask(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    before = await client.post(API)
    assert before.status_code == 200
    assert (await client.put(SETTING, json={"enabled": False})).status_code == 200

    done = await review_every_workspace()
    assert done["off"] >= 1 and done["failed"] == 0
    assert await _night_reviews(acme["acme"]) == []
    # What was reviewed before stays, read as it stands.
    kept = await client.get(API)
    assert kept.status_code == 200 and kept.json()["id"] == before.json()["id"]
    # Asked by a person: made whether the night review is on or off.
    asked = await client.post(API)
    assert asked.status_code == 200 and asked.json()["trigger"] == "asked"

    # On again: the next night reviews it.
    assert (await client.put(SETTING, json={"enabled": True})).status_code == 200
    await review_every_workspace()
    assert len(await _night_reviews(acme["acme"])) == 1


async def test_off_the_morning_tells_nothing_even_of_a_review_made_before(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[EmailMessage] = []

    class Sender:
        async def send(self, message: EmailMessage) -> None:
            sent.append(message)

    monkeypatch.setattr(morning, "build_email_sender", Sender)
    review = _review(acme["acme"], POINTS)
    await _kept(acme["acme"], review)
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            await set_night_review_enabled(session, acme["acme"], False)
            await session.commit()

    await morning.send_morning_reports()
    # None to its members — other workspaces' mornings are theirs.
    with system_scope():
        async with session_factory() as session:
            members = (
                await session.scalars(
                    select(User.email).where(User.id.in_([acme["admin"], acme["member"]]))
                )
            ).all()
    assert members and not [m for m in sent if m.to in set(members)]
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            untold = await session.get(NightReview, review.id)
            # Not told, and never marked told: no bell rings for it either.
            assert untold is not None and untold.reported_at is None
