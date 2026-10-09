"""The skill framework (LEKA-396): skills defined with their contract,
registered by version, run one way — against the database.

What these protect:
- A skill is registered only as it can run: its key, its semver, its
  category, a permission LEKA knows, pydantic models for what it takes and
  gives — and it reads: one that would act is refused. Every problem said.
- A version is its contract: the same version said otherwise is refused; the
  same again, or moved in its lifecycle, stands in for it.
- Which version runs: the one asked (exactly, or the latest of a major), else
  the latest active, else the latest deprecated. Draft, review, retired never
  run.
- A run is checked at every step and kept whatever came of it: no such skill,
  a version that does not run, a permission the caller lacks, what it was
  given not what it takes, a thing it does not know — refused, said why; one
  that breaks its contract, runs out of time or fails — said so. What it
  gave, its contract's fingerprint, for whom, about what: kept.
- A skill reads: the database refuses it a write.
- A skill as a model calls it: what the caller knows filled in, what it read
  handed to the caller, what is wrong said to the model.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import (
    Call,
    Cited,
    Citing,
    Lifecycle,
    Skill,
    SkillError,
    SkillOutcome,
    SkillRegistry,
    SkillRun,
    SkillRuntime,
    UnknownThingError,
    tool_schema,
)
from leka.capabilities.skills import LEKA
from leka.db import session_factory, system_scope, workspace_scope
from leka.platform import Workspace

pytestmark = pytest.mark.integration


class Word(BaseModel):
    word: str = Field(max_length=5)


class Said(Citing):
    said: str


async def echo(given: Word, call: Call) -> Said:
    return Said(
        said=given.word.upper(),
        cited=[Cited(id=f"word:{given.word}", kind="record", label=given.word)],
    )


def toy(**more: Any) -> Skill:
    said: dict[str, Any] = {
        "key": "echo",
        "version": "1.0.0",
        "title": "Echo",
        "summary": "Says a word back.",
        "category": "knowledge",
        "input": Word,
        "output": Said,
        "run": echo,
        **more,
    }
    return Skill(**said)


def registry(*skills: Skill) -> SkillRegistry:
    held = SkillRegistry()
    held.register(*skills)
    return held


# ── registered ───────────────────────────────────────────────────────────────


def test_a_skill_is_registered_only_as_it_can_run() -> None:
    skill = toy()
    contract = skill.contract()
    assert contract["input"]["properties"]["word"]["maxLength"] == 5
    assert set(contract["output"]["properties"]) == {"said", "cited"}
    assert len(skill.fingerprint()) == 64
    assert registry(skill).find("echo") == skill

    with pytest.raises(SkillError) as refused:
        SkillRegistry().register(
            toy(
                key="Echo Back",
                version="1.0",
                category="magic",
                effect="restart",
                permission="everything",
                input=dict,
            )
        )
    said = str(refused.value)
    for problem in (
        "key:",
        "semver",
        "category 'magic'",
        "effect 'restart': a skill reads",
        "unknown permission 'everything'",
        "input: a pydantic model",
    ):
        assert problem in said, said


def test_a_version_is_its_contract() -> None:
    held = registry(toy())

    class Louder(Citing):
        said: str
        volume: int

    with pytest.raises(SkillError, match="a new contract is a new version"):
        held.register(toy(output=Louder))
    # The same again, or moved in its lifecycle: it stands in for it.
    held.register(toy())
    held.register(toy(lifecycle=Lifecycle.DEPRECATED))
    assert held.find("echo") is not None
    assert held.find("echo").lifecycle is Lifecycle.DEPRECATED  # type: ignore[union-attr]
    # A new contract, a new version — both kept.
    held.register(toy(version="2.0.0", output=Louder))
    assert [s.version for s in held.versions("echo")] == ["2.0.0", "1.0.0"]


def test_which_version_runs() -> None:
    held = registry(
        toy(),
        toy(version="1.1.0", lifecycle=Lifecycle.DEPRECATED),
        toy(version="1.2.0", lifecycle=Lifecycle.RETIRED),
        toy(version="2.0.0", lifecycle=Lifecycle.DRAFT),
    )

    def found(version: str | None = None) -> str | None:
        skill = held.find("echo", version)
        return skill.version if skill else None

    # The latest active; a draft does not run, a deprecated one runs.
    assert found() == "1.0.0"
    assert found("1.1") == "1.1.0"
    assert found("1") == "1.0.0"
    # Asked, it is said — and refused when it runs (test below).
    assert found("2") == "2.0.0"
    assert found("3") is None
    assert [s.version for s in held.skills()] == ["1.0.0"]
    assert registry(toy(lifecycle=Lifecycle.DEPRECATED)).find("echo") is not None


def test_a_value_a_model_may_leave_out_is_said_not_required() -> None:
    class Asked(BaseModel):
        query: str
        since: datetime | None = Field(default=None, description="The start.")

    schema = tool_schema(Asked)
    assert schema["required"] == ["query"]
    assert schema["properties"]["since"] == {
        "type": "string",
        "format": "date-time",
        "description": "The start.",
    }

    class Nothing(BaseModel):
        pass

    assert tool_schema(Nothing) == {"properties": {}, "type": "object"}


# ── run ──────────────────────────────────────────────────────────────────────


@pytest.fixture
async def workspace() -> AsyncIterator[uuid.UUID]:
    with system_scope():
        async with session_factory() as session:
            found = Workspace(name="Skills", slug=f"skills-{uuid.uuid4().hex[:10]}")
            session.add(found)
            await session.commit()
            workspace_id = found.id
    yield workspace_id
    with system_scope():
        async with session_factory() as session:
            leftover = await session.get(Workspace, workspace_id)
            if leftover is not None:
                await session.delete(leftover)
            await session.commit()


async def _run(
    workspace_id: uuid.UUID,
    held: SkillRegistry,
    key: str,
    inputs: dict[str, Any],
    *,
    permissions: frozenset[str] = LEKA,
    version: str | None = None,
) -> tuple[SkillOutcome, SkillRun]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            runtime = SkillRuntime(
                session,
                workspace_id,
                permissions=permissions,
                by=None,
                caller="test",
                ref="intention:test",
                registry=held,
            )
            outcome = await runtime.run(key, inputs, version=version)
            await session.commit()
            assert outcome.run_id is not None
            row = runtime.kept(outcome.run_id)
            assert row is not None
            return outcome, row


async def test_a_skill_runs_checked_and_kept(workspace: uuid.UUID) -> None:
    skill = toy()
    outcome, row = await _run(workspace, registry(skill), "echo", {"word": "hi"})
    assert outcome.ok
    assert outcome.output == Said(said="HI", cited=outcome.cited)
    [cited] = outcome.cited
    assert cited.id == "word:hi"
    # A model reads what it gave, not what it cited.
    assert outcome.said() == {"said": "HI"}
    # Kept: which, its contract, for whom, about what, given what, what it gave.
    assert (row.key, row.version, row.fingerprint) == ("echo", "1.0.0", skill.fingerprint())
    assert (row.status, row.caller, row.ref) == ("succeeded", "test", "intention:test")
    assert row.inputs == {"word": "hi"}
    assert row.output == {"said": "HI"}
    assert row.detail == {"cited": 1, "size": len(json.dumps({"said": "HI"}))}
    # Deprecated, it runs — said.
    later, kept = await _run(
        workspace, registry(toy(lifecycle=Lifecycle.DEPRECATED)), "echo", {"word": "yo"}
    )
    assert later.ok and later.deprecated and kept.detail["deprecated"] is True


async def _unknown(given: Word, call: Call) -> Said:
    raise UnknownThingError("No such word.")


async def test_what_does_not_run_is_refused_said_why_and_kept(workspace: uuid.UUID) -> None:
    held = registry(
        toy(),
        toy(version="2.0.0", lifecycle=Lifecycle.DRAFT),
        toy(key="unknown", run=_unknown),
    )
    cases: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {
        "not_found": ("nope", {"word": "hi"}, {}),
        "not_runnable": ("echo", {"word": "hi"}, {"version": "2"}),
        "not_permitted": ("echo", {"word": "hi"}, {"permissions": frozenset()}),
        "invalid_input": ("echo", {"word": "too long"}, {}),
        "unknown": ("unknown", {"word": "hi"}, {}),
    }
    for reason, (key, inputs, more) in cases.items():
        outcome, row = await _run(workspace, held, key, inputs, **more)
        assert (outcome.status, outcome.reason) == ("refused", reason)
        assert (row.status, row.reason) == ("refused", reason)
        assert outcome.output is None
        assert "error" in outcome.said()
    refused, _ = await _run(workspace, held, "echo", {"word": "too long"})
    [error] = refused.errors
    assert (error["field"], error["code"]) == ("word", "string_too_long")
    assert refused.said()["errors"][0]["field"] == "word"
    nothing, _ = await _run(workspace, held, "echo", {}, permissions=frozenset())
    assert nothing.message == "Running it takes the permission workspace:read."
    unknown, _ = await _run(workspace, held, "unknown", {"word": "hi"})
    assert unknown.message == "No such word."
    not_runnable, _ = await _run(workspace, held, "echo", {"word": "hi"}, version="2")
    assert not_runnable.message == "This version does not run: it is draft."
    with workspace_scope(workspace):
        async with session_factory() as session:
            kept = [str(r) for r in (await session.scalars(select(SkillRun.reason))).all()]
    again = ["invalid_input", "not_permitted", "unknown", "not_runnable"]
    assert sorted(kept) == sorted([*cases, *again])


async def _broken(given: Word, call: Call) -> Said:
    # Not what it promised: a number where it said words.
    return cast(Said, {"said": 3})


async def _slow(given: Word, call: Call) -> Said:
    await asyncio.sleep(2)
    return Said(said=given.word)


async def _failing(given: Word, call: Call) -> Said:
    raise RuntimeError("boom")


async def _writing(given: Word, call: Call) -> Said:
    await call.session.execute(
        text("UPDATE workspaces SET name = 'Written' WHERE id = :id"), {"id": call.workspace_id}
    )
    return Said(said=given.word)


async def test_what_breaks_its_contract_its_time_or_fails_is_said(workspace: uuid.UUID) -> None:
    held = registry(
        toy(key="broken", run=_broken),
        toy(key="slow", run=_slow, timeout=0.05),
        toy(key="failing", run=_failing),
    )
    broken, row = await _run(workspace, held, "broken", {"word": "hi"})
    assert (broken.status, broken.reason) == ("failed", "invalid_output")
    assert broken.errors[0]["field"] == "said"
    assert row.output is None
    slow, _ = await _run(workspace, held, "slow", {"word": "hi"})
    assert (slow.status, slow.message) == ("timed_out", "No answer in 0.05 s.")
    failing, _ = await _run(workspace, held, "failing", {"word": "hi"})
    assert (failing.status, failing.reason, failing.message) == (
        "failed",
        "error",
        "It failed (RuntimeError).",
    )


async def test_a_skill_reads_the_database_refuses_it_a_write(workspace: uuid.UUID) -> None:
    outcome, row = await _run(
        workspace, registry(toy(key="writing", run=_writing)), "writing", {"word": "hi"}
    )
    assert (outcome.status, outcome.reason) == ("failed", "error")
    assert row.status == "failed"
    with system_scope():
        async with session_factory() as session:
            found = await session.get(Workspace, workspace)
            assert found is not None and found.name == "Skills"


async def test_a_skill_as_a_model_calls_it(workspace: uuid.UUID) -> None:
    got: list[Cited] = []
    with workspace_scope(workspace):
        async with session_factory() as session:
            runtime = SkillRuntime(
                session,
                workspace,
                permissions=LEKA,
                by=None,
                caller="analyst",
                ref="intention:test",
                registry=registry(toy()),
            )
            tool = runtime.tool("echo", fill={"word": "hi"}, cited=got.extend)
            assert (tool.name, tool.description, tool.effect) == (
                "echo",
                "Says a word back.",
                "read",
            )
            assert tool.parameters["properties"]["word"]["maxLength"] == 5
            # What the caller knows, filled in when the model leaves it out.
            assert json.loads(await tool.handler({})) == {"said": "HI"}
            # Kept as JSON keeps it: a date in ISO 8601.
            moment = datetime(2026, 10, 9, 21, 24, tzinfo=UTC)
            dated = await runtime.run("echo", {"word": "hi", "at": moment})
            assert dated.run_id is not None
            kept_inputs = runtime.kept(dated.run_id).inputs  # type: ignore[union-attr]
            assert kept_inputs["at"] == "2026-10-09T21:24:00+00:00"
            assert [c.id for c in got] == ["word:hi"]
            # What is wrong, said to the model, to ask again.
            wrong = json.loads(await tool.handler({"word": "too long"}))
            assert wrong["error"] == "What it was given is not what it takes."
            assert wrong["errors"][0]["field"] == "word"
            await session.commit()
            with pytest.raises(SkillError, match="No skill 'nope'"):
                runtime.tool("nope")
    with workspace_scope(workspace):
        async with session_factory() as session:
            kept = (await session.scalars(select(SkillRun).order_by(SkillRun.at))).all()
    assert [(r.caller, r.status) for r in kept] == [
        ("analyst", "succeeded"),
        ("analyst", "succeeded"),
        ("analyst", "refused"),
    ]


def test_a_runtime_builds_tools_without_a_session() -> None:
    runtime = SkillRuntime(
        cast(AsyncSession, None),
        uuid.uuid4(),
        permissions=LEKA,
        by=None,
        caller="test",
        registry=registry(toy()),
    )
    assert runtime.tool("echo").name == "echo"
