"""What models were asked, for the LEKA team only (LEKA-530): the backoffice
of `python -m leka.metering.cli usage`.

What these protect: every call, across workspaces — its workspace, the
person, the agent and the operation, the provider and the model, when, how
it ended, its tokens in, out and in all, its cost in US dollars with the
rate it was priced on said, a cost not known said not known, the AI credits
it used (none for a workspace's own model, none for a failure); filtered by
period, workspace, person (an id or an address), agent, provider, model,
operation, status; summed by any of them; by workspace, the AI capacity of
its month beside it. And none of it is served to customers: no route of the
API returns tokens or a provider's cost.

Every call is in February 2020: no other test's data is in that month.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from leka.capabilities import ModelCall
from leka.core.config import settings
from leka.db import session_factory, system_scope, workspace_scope
from leka.main import app
from leka.metering import cli, reports
from tests.test_sources_api import acme  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

START, END = date(2020, 2, 1), date(2020, 3, 1)


def _call(workspace_id: uuid.UUID, **fields: Any) -> ModelCall:
    base: dict[str, Any] = {
        "workspace_id": workspace_id,
        "id": uuid.uuid4(),
        "purpose": "intention.understanding",
        "tier": "fast",
        "provider": "google",
        "model": "gemini-3.8-flash",
        "version": "gemini-3.8-flash-001",
        "route": "assigned",
        "attempt": 1,
        "owner": "leka",
        "status": "ok",
        "tokens_in": 1000,
        "tokens_out": 200,
        "tokens_thinking": 0,
        "tool_calls": 0,
        "cost_usd": 0.02,
        "latency_ms": 800,
        "at": datetime(2020, 2, 10, 9, tzinfo=UTC),
    }
    return ModelCall(**{**base, **fields})


@pytest.fixture
async def asked(acme: dict[str, uuid.UUID]) -> dict[str, Any]:
    with system_scope():
        async with session_factory() as session:
            found = await session.execute(
                text("SELECT id, email FROM users WHERE id IN (:a, :m)"),
                {"a": acme["admin"], "m": acme["member"]},
            )
            emails: dict[uuid.UUID, str] = {row.id: row.email for row in found}
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            session.add_all(
                [
                    _call(acme["acme"], user_id=acme["member"]),
                    _call(
                        acme["acme"],
                        purpose="agent:code-review:review",
                        user_id=acme["admin"],
                        tokens_in=5000,
                        tokens_out=900,
                        cost_usd=0.1,
                    ),
                    _call(
                        acme["acme"],
                        purpose="agent:code-review",
                        user_id=acme["admin"],
                        status="failed",
                        error="503: overloaded",
                        tokens_in=0,
                        tokens_out=0,
                        cost_usd=None,
                    ),
                ]
            )
            await session.commit()
    with workspace_scope(acme["globex"]):
        async with session_factory() as session:
            session.add(
                _call(
                    acme["globex"],
                    provider="azure_openai",
                    model="gpt-prod",
                    owner="workspace",
                    route="own",
                    cost_usd=None,
                    at=datetime(2020, 2, 20, tzinfo=UTC),
                )
            )
            await session.commit()
    return {**acme, "emails": {k: str(v) for k, v in emails.items()}}


async def _usage(**given: Any) -> list[dict[str, Any]]:
    with system_scope():
        async with session_factory() as session:
            return await reports.usage(session, start=START, end=END, **given)


async def test_every_call_said_whole_its_cost_on_its_basis_and_its_credits(
    asked: dict[str, Any],
) -> None:
    rows = await _usage(workspace=asked["acme"])
    assert len(rows) == 3
    review = next(r for r in rows if r["operation"] == "agent:code-review:review")
    assert (review["agent"], review["provider"], review["model"], review["status"]) == (
        "code-review",
        "google",
        "gemini-3.8-flash",
        "ok",
    )
    assert review["user_email"] == asked["emails"][asked["admin"]]
    assert (review["tokens_in"], review["tokens_out"], review["tokens_total"]) == (5000, 900, 5900)
    assert (review["cost_usd"], review["currency"]) == (0.1, "USD")
    assert review["credits_used"] == pytest.approx(0.1 / settings.credit_usd)
    assert review["cost_basis"].startswith("list price") or review["cost_basis"].startswith("rate")
    failed = next(r for r in rows if r["status"] == "failed")
    assert (failed["cost_usd"], failed["credits_used"], failed["error"]) == (
        None,
        0.0,
        "503: overloaded",
    )
    assert failed["cost_basis"].startswith("not known")
    # The workspace's own model: its account, no credits of LEKA's.
    [own] = await _usage(workspace=asked["globex"])
    assert (own["owner"], own["credits_used"]) == ("workspace", 0.0)
    assert own["cost_basis"].startswith("the workspace's own model")


async def test_filtered_by_person_agent_model_operation_status(asked: dict[str, Any]) -> None:
    member = asked["emails"][asked["member"]]
    assert [r["operation"] for r in await _usage(user=member.upper())] == [
        "intention.understanding"
    ]
    assert len(await _usage(user=str(asked["admin"]))) == 2
    assert {r["operation"] for r in await _usage(agent="code-review")} == {
        "agent:code-review",
        "agent:code-review:review",
    }
    assert [r["model"] for r in await _usage(provider="azure_openai")] == ["gpt-prod"]
    assert len(await _usage(model="gemini-3.8-flash")) == 3
    assert len(await _usage(operation="intention")) == 2
    assert len(await _usage(operation="intention", workspace=asked["acme"])) == 1
    assert len(await _usage(operation="agent:code-review")) == 2
    assert [r["status"] for r in await _usage(status="failed")] == ["failed"]
    # Another period: nothing.
    with system_scope():
        async with session_factory() as session:
            assert await reports.usage(session, start=date(2019, 1, 1), end=START) == []


async def test_summed_by_agent_and_by_workspace_with_its_month_s_capacity(
    asked: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    by_agent = {r["agent"]: r for r in await _usage(workspace=asked["acme"], by="agent")}
    assert (by_agent["code-review"]["calls"], by_agent["code-review"]["failed"]) == (2, 1)
    assert by_agent["code-review"]["cost_not_known"] == 1
    assert by_agent[None]["tokens_total"] == 1200
    by_model = await _usage(by="model", provider="google")
    assert [(r["provider"], r["model"], r["calls"]) for r in by_model] == [
        ("google", "gemini-3.8-flash", 3)
    ]

    given = SimpleNamespace(
        start="2020-02-01",
        end="2020-03-01",
        workspace=None,
        user=None,
        agent=None,
        provider=None,
        model=None,
        operation=None,
        status=None,
        by="workspace",
        limit=1000,
        format="json",
    )
    assert await cli._usage(given) == 0  # type: ignore[arg-type]
    said = json.loads(capsys.readouterr().out)
    mine = next(r for r in said if r["workspace_id"] == str(asked["acme"]))
    assert (mine["calls"], mine["cost_usd"], mine["currency"]) == (3, 0.12, "USD")
    assert {"plan", "allowance", "month_used", "period_start", "period_end"} <= set(mine)


def test_no_route_of_the_api_serves_tokens_or_a_provider_s_cost() -> None:
    """LEKA-530: what models used is the LEKA team's, never a customer's —
    their tokens, their cost, the prices of LEKA's models."""
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    forbidden = {"tokens_in", "tokens_out", "tokens_cached", "cost_usd", "per_million_in"}

    def refs(node: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref":
                    found.add(str(value).rsplit("/", 1)[-1])
                else:
                    found |= refs(value)
        elif isinstance(node, list):
            for value in node:
                found |= refs(value)
        return found

    def reached(names: set[str]) -> set[str]:
        seen, todo = set(), set(names)
        while todo:
            name = todo.pop()
            if name in seen or name not in schemas:
                continue
            seen.add(name)
            todo |= refs(schemas[name])
        return seen

    # LEKA ADMIN (LEKA-544) is the LEKA team's own, behind an admin's token
    # no customer holds (tests/test_admin_access.py): what models cost is
    # what it reads. Every other route is a customer's, and stays clean.
    admin = f"{settings.api_v1_prefix}/admin/"
    leaking = []
    for path, operations in spec["paths"].items():
        if path.startswith(admin):
            continue
        for method, operation in operations.items():
            for name in reached(refs(operation.get("responses", {}))):
                said = set(schemas[name].get("properties") or {}) & forbidden
                if said:
                    leaking.append(f"{method.upper()} {path}: {name} {sorted(said)}")
    assert leaking == []
