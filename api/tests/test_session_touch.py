"""A session's idle clock (2026-11-06): moved on at most once a minute, and
never waited for. A page polling live sends several requests every few
seconds with one session; each wrote its row in its own transaction, so one
slow request held every other, and the connection pool with them, until
LEKA answered 503.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from leka.core.config import settings
from leka.core.security import hash_token
from leka.db import session_factory
from leka.identity import Session, User
from leka.identity.repository import SessionRepository

pytestmark = pytest.mark.integration

MINUTE = timedelta(minutes=1)


async def _session(seen: datetime) -> tuple[uuid.UUID, str]:
    marker = uuid.uuid4().hex[:8]
    token = f"touch-{marker}"
    async with session_factory() as db:
        user = User(email=f"touch-{marker}@acme.test", password_hash="x")
        db.add(user)
        await db.flush()
        row = Session(
            user_id=user.id,
            token_hash=hash_token(token),
            last_seen_at=seen,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        db.add(row)
        await db.commit()
        return row.id, token


async def _seen(session_id: uuid.UUID) -> datetime:
    async with session_factory() as db:
        seen = await db.scalar(select(Session.last_seen_at).where(Session.id == session_id))
        assert seen is not None
        return seen


async def test_the_idle_clock_moves_at_most_once_a_minute() -> None:
    now = datetime.now(UTC)
    fresh, _ = await _session(now - timedelta(seconds=10))
    stale, _ = await _session(now - timedelta(minutes=5))
    async with session_factory() as db:
        sessions = SessionRepository(db)
        assert await sessions.touch(fresh, now, every=MINUTE) is False
        assert await sessions.touch(stale, now, every=MINUTE) is True
        await db.commit()
    assert await _seen(fresh) == now - timedelta(seconds=10)
    assert await _seen(stale) == now


async def test_a_row_another_request_holds_is_never_waited_for() -> None:
    now = datetime.now(UTC)
    held, _ = await _session(now - timedelta(minutes=5))
    async with session_factory() as slow, session_factory() as other:
        # A slow request: it moved the clock and has not ended.
        await slow.execute(text("SELECT id FROM sessions WHERE id = :id FOR UPDATE"), {"id": held})
        started = time.monotonic()
        moved = await asyncio.wait_for(
            SessionRepository(other).touch(held, now, every=MINUTE), timeout=5
        )
        assert moved is False
        assert time.monotonic() - started < 2
        await other.commit()
        await slow.rollback()
    # Once it ended, the next request moves it.
    async with session_factory() as db:
        assert await SessionRepository(db).touch(held, now, every=MINUTE) is True
        await db.commit()


async def test_a_request_moves_a_stale_clock_and_leaves_a_fresh_one(client: AsyncClient) -> None:
    now = datetime.now(UTC)
    stale, token = await _session(now - timedelta(minutes=5))
    client.cookies.set(settings.session_cookie_name, token)
    first = await client.get("/api/v1/auth/me")
    assert first.status_code == 200, first.text
    moved = await _seen(stale)
    assert moved > now - timedelta(seconds=5)
    # A minute has not passed: the next requests leave the row alone.
    for _ in range(3):
        assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert await _seen(stale) == moved
