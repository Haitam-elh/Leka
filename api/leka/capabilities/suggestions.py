"""An agent or a skill someone wishes LEKA had (LEKA-501) — « Demander une
compétence » on the Agents page: kept for LEKA's team, never an intention,
nothing run on it.

    suggest   one more, from a member: refused when the same one is still
              open in the workspace (conflict), or after SUGGESTIONS_A_DAY
              from the same person in a day (rate_limited)
    listed    the workspace's, newest first — where each stands

LEKA's team reads and moves them on the server, as its billing commands:

    python -m leka.capabilities.suggestions list [--status received]
    python -m leka.capabilities.suggestions set-status <id> reviewing|planned|declined|done
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.models import CapabilitySuggestion

STATUSES = ("received", "reviewing", "planned", "declined", "done")
# Still being looked at: the same one again is a duplicate.
OPEN = ("received", "reviewing", "planned")
# Enough for anyone with ideas; not a flood.
SUGGESTIONS_A_DAY = 5


class SuggestionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=120)
    problem: str = Field(min_length=10, max_length=2000)
    use_case: str = Field(min_length=10, max_length=2000)
    systems: str | None = Field(default=None, max_length=300)
    context: str | None = Field(default=None, max_length=4000)

    @field_validator("name", "problem", "use_case", "systems", "context")
    @classmethod
    def _trimmed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class SuggestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    problem: str
    use_case: str
    systems: str | None
    context: str | None
    status: str
    created_at: datetime


class SuggestionRefusedError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _same(name: str) -> str:
    return " ".join(name.lower().split())


async def suggest(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    body: SuggestionWrite,
    *,
    now: datetime,
) -> CapabilitySuggestion:
    if not body.name or not body.problem or not body.use_case:
        raise SuggestionRefusedError("empty", "A name, a problem and a use case are needed.")
    today = await session.scalar(
        select(func.count())
        .select_from(CapabilitySuggestion)
        .where(
            CapabilitySuggestion.user_id == user_id,
            CapabilitySuggestion.created_at > now - timedelta(days=1),
        )
    )
    if (today or 0) >= SUGGESTIONS_A_DAY:
        raise SuggestionRefusedError("rate_limited", "Enough suggestions for today.")
    open_names = await session.scalars(
        select(CapabilitySuggestion.name).where(
            CapabilitySuggestion.workspace_id == workspace_id,
            CapabilitySuggestion.status.in_(OPEN),
        )
    )
    if _same(body.name) in {_same(n) for n in open_names}:
        raise SuggestionRefusedError("duplicate", "This one is already suggested.")
    row = CapabilitySuggestion(
        workspace_id=workspace_id,
        user_id=user_id,
        name=body.name,
        problem=body.problem,
        use_case=body.use_case,
        systems=body.systems,
        context=body.context,
        status="received",
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def listed(session: AsyncSession, workspace_id: uuid.UUID) -> list[CapabilitySuggestion]:
    rows = await session.scalars(
        select(CapabilitySuggestion)
        .where(CapabilitySuggestion.workspace_id == workspace_id)
        .order_by(CapabilitySuggestion.created_at.desc())
        .limit(100)
    )
    return list(rows)


# ── LEKA's team, on the server ──────────────────────────────────────────────


async def _list(status: str | None) -> int:
    from leka.db import load_schema, session_factory, system_scope

    load_schema()
    with system_scope():
        async with session_factory() as session:
            query = select(CapabilitySuggestion).order_by(CapabilitySuggestion.created_at.desc())
            if status:
                query = query.where(CapabilitySuggestion.status == status)
            for row in await session.scalars(query):
                said = SuggestionRead.model_validate(row).model_dump(mode="json")
                said["workspace_id"] = str(row.workspace_id)
                sys.stdout.write(json.dumps(said, ensure_ascii=False) + "\n")
    return 0


async def _set_status(suggestion: uuid.UUID, status: str) -> int:
    from leka.db import load_schema, session_factory, system_scope

    load_schema()
    with system_scope():
        async with session_factory() as session:
            row = await session.get(CapabilitySuggestion, suggestion)
            if row is None:
                sys.stderr.write(f"No suggestion {suggestion}.\n")
                return 1
            row.status = status
            await session.commit()
    sys.stdout.write(f"{suggestion}: {status}\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m leka.capabilities.suggestions")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="every suggestion, newest first, one JSON a line")
    listing.add_argument("--status", choices=STATUSES)
    moving = commands.add_parser("set-status", help="where one stands")
    moving.add_argument("suggestion", type=uuid.UUID)
    moving.add_argument("status", choices=STATUSES)
    asked = parser.parse_args(argv)
    if asked.command == "list":
        return asyncio.run(_list(asked.status))
    return asyncio.run(_set_status(asked.suggestion, asked.status))


if __name__ == "__main__":
    raise SystemExit(main())
