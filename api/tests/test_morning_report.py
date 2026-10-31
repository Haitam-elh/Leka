"""The morning report (2026-10-29): the night review, told in the centre
and e-mailed in the morning.

What these protect: a night with something to look at told to every
member — once, the morning's (2026-10-31: a review every hour of the night,
never a bell each hour) —, a quiet one told to no one; the morning's e-mail
sent once, to each member in their language, never to who muted the
watch, in LEKA's dress, each point in words — only those that still stand
— and the way to Mon environnement.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from leka.db import session_factory, workspace_scope
from leka.identity import EmailMessage
from leka.monitoring import MonitoringAlert, NightReview
from leka.notifications import morning
from leka.notifications.models import NotificationPreference
from tests.conftest import FakeIdentity
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

POINTS: list[dict[str, Any]] = [
    {
        "kind": "alert",
        "severity": "high",
        "name": "payment-api",
        "count": 1,
        "href": "/environment",
        "ask": True,
        "params": {"trouble": "unavailable"},
    },
    {
        "kind": "decisions",
        "severity": "medium",
        "name": "",
        "count": 2,
        "href": "/approvals",
        "ask": False,
        "params": {},
    },
]


def _review(workspace_id: uuid.UUID, points: list[dict[str, Any]], **more: Any) -> NightReview:
    return NightReview(
        workspace_id=workspace_id,
        id=uuid.uuid4(),
        at=more.pop("at", datetime.now(UTC) - timedelta(hours=3)),
        trigger="night",
        checked={"things": 42, "sources": 3, "alerts": 1, "findings": 7},
        points=points,
        **more,
    )


async def _kept(workspace_id: uuid.UUID, *rows: Any) -> None:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            session.add_all(rows)
            await session.commit()


async def test_a_night_with_points_is_told_a_quiet_one_is_not(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    morning_at = datetime.now(UTC) - timedelta(hours=1)
    await _kept(
        acme["acme"],
        # The night's hourly reviews: only the one the morning took rings.
        _review(acme["acme"], POINTS, at=datetime.now(UTC) - timedelta(hours=4)),
        _review(acme["acme"], POINTS, reported_at=morning_at),
        _review(acme["acme"], [], reported_at=morning_at),
    )
    _as(identity, acme, "member")
    said = (await client.get("/api/v1/notifications", params={"category": "monitoring"})).json()
    [night] = [n for n in said["data"] if n["kind"] == "alert.night_review"]
    assert (night["severity"], night["params"], night["link"]) == (
        "warning",
        {"count": 2, "high": 1},
        "/environment",
    )


async def test_the_morning_report_is_mailed_once_never_to_who_muted_the_watch(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[EmailMessage] = []

    class Sender:
        async def send(self, message: EmailMessage) -> None:
            sent.append(message)

    monkeypatch.setattr(morning, "build_email_sender", Sender)
    review = _review(acme["acme"], POINTS)
    now = datetime.now(UTC)
    await _kept(
        acme["acme"],
        review,
        # The alert still open this morning; the decisions taken since.
        MonitoringAlert(
            workspace_id=acme["acme"],
            id=uuid.uuid4(),
            subject_type="entity",
            subject_id=uuid.uuid4(),
            subject_name="payment-api",
            family="health",
            kind="unavailable",
            severity="high",
            certainty="confirmed",
            status="open",
            opened_at=now,
            last_seen_at=now,
        ),
        NotificationPreference(
            workspace_id=acme["acme"], id=uuid.uuid4(), user_id=acme["member"], muted=["monitoring"]
        ),
    )
    done = await morning.send_morning_reports()
    assert done["sent"] == 1
    [message] = sent
    # In the member's language: this one's is English — only what still
    # stands this morning: the decisions taken since are not said.
    assert message.subject.startswith("LEKA · Night review: 1 point to look at")
    assert "- payment-api: unavailable" in message.body
    assert "decision" not in message.body
    html = message.html or ""
    assert "leka-wordmark.png" in html and ">Open My environment</a>" in html
    assert "/environment" in html
    french = morning.report(review, "Acme", "fr")
    assert french.subject == "LEKA · Revue de la nuit : 2 points à regarder sur Acme"
    assert "- payment-api : indisponible" in french.body
    assert ">Ouvrir Mon environnement</a>" in (french.html or "")
    # Once: the next morning sends nothing more.
    assert (await morning.send_morning_reports())["sent"] == 1 - 1
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            kept = await session.get(NightReview, review.id)
            assert kept is not None and kept.reported_at is not None


def test_each_point_is_said_in_english_too() -> None:
    words = morning.WORDS["en"]
    assert morning.point_said(POINTS[0], words) == "payment-api: unavailable"
    change = {"kind": "change", "name": "Fix the balance", "params": {"number": 7}}
    assert morning.point_said(change, words) == "Pull request #7 is red: Fix the balance"
    finding = {"kind": "finding", "name": "Redis", "params": {"finding": "f1"}}
    assert morning.point_said(finding, words) == "Important finding from LEKA on Redis"
    run = {"kind": "run", "name": "Documentation assistant", "count": 2, "params": {}}
    assert (
        morning.point_said(run, words)
        == "The agent « Documentation assistant » failed 2 time(s) since yesterday"
    )
