"""Entity resolution, the job and the API (LEKA-357), against the database.

A workspace with four sources — shaped as GitHub, Jira, PagerDuty and
Datadog normalise — whose candidates sit in `normalised_records` as
normalisation leaves them. What these protect: the job reads every source
of the workspace and nothing of another; what it makes is replaced whole
and keeps its ids; it runs when normalisation made something, and not
otherwise; a failed run changes nothing and says so; a source removed takes
its candidates with it; and members read what the workspace resolves to —
by type, by what is doubtful, by key — never another workspace's.

The rules themselves are tests/test_resolution.py's.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from leka.connectors import SourceKind, SourceService
from leka.db import session_factory, workspace_scope
from leka.ingestion import (
    ResolutionRun,
    ResolvedEntity,
    ResolvedKey,
)
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion.lifecycle import sweep_processing
from leka.ingestion.resolution import engine
from leka.ingestion.resolution.job import RESOLVE_JOB, resolve_workspace
from tests.conftest import FakeIdentity
from tests.test_sources_api import FAKE_KEY, _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/ingestion/resolution"
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def entity(
    key: str,
    name: str,
    *,
    type: str = "person",  # noqa: A002 — normalisation's word
    aliases: tuple[str, ...] = (),
    **attributes: Any,
) -> dict[str, Any]:
    return {
        "type": type,
        "key": key,
        "external_id": key,
        "name": name,
        "aliases": list(aliases),
        "attributes": attributes,
        "confidence": 1.0,
        "observed_at": NOW.isoformat(),
    }


async def _source(workspace_id: uuid.UUID, name: str) -> uuid.UUID:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            created = await SourceService(session, workspace_id, actor_user_id=None).create(
                SourceKind.SLACK, name, {}, {"api_key": FAKE_KEY}
            )
            await session.commit()
            return created.id


async def _normalised(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    own: dict[str, Any],
    *named: dict[str, Any],
    at: datetime = NOW,
    external_id: str | None = None,
) -> None:
    """A record as normalisation leaves it: its row, and the rows it came
    from — its source's id for it its entity's key, unless another record
    names the same entity."""
    external_id = external_id or own["key"]
    checksum = hashlib.sha256(external_id.encode() + source_id.bytes).hexdigest()
    result = json.dumps({"entity": own, "related": list(named), "relationships": []})
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            values = {"w": workspace_id, "s": source_id, "c": checksum, "at": at}
            record = await session.scalar(
                text(
                    "INSERT INTO source_records (workspace_id, source_id, kind, external_id, "
                    "checksum, first_seen_at, last_seen_at) VALUES (:w, :s, 'records', :e, :c, "
                    ":at, :at) RETURNING id"
                ),
                {**values, "e": external_id},
            )
            extracted = await session.scalar(
                text(
                    "INSERT INTO extracted_records (workspace_id, source_id, source_record_id, "
                    "kind, status, checksum, result, extracted_at) VALUES (:w, :s, :r, "
                    "'records', 'extracted', :c, '{}', :at) RETURNING id"
                ),
                {**values, "r": record},
            )
            parsed = await session.scalar(
                text(
                    "INSERT INTO parsed_records (workspace_id, source_id, extracted_record_id, "
                    "kind, status, checksum, parser_version, result, parsed_at) VALUES (:w, :s, "
                    ":x, 'records', 'parsed', :c, 1, '{}', :at) RETURNING id"
                ),
                {**values, "x": extracted},
            )
            await session.execute(
                text(
                    "INSERT INTO normalised_records (workspace_id, source_id, parsed_record_id, "
                    "kind, status, checksum, parser_version, normaliser_version, entity_type, "
                    "entity_key, result, normalised_at) VALUES (:w, :s, :p, 'records', "
                    "'normalised', :c, 1, 1, :t, :k, CAST(:j AS jsonb), :at)"
                ),
                {**values, "p": parsed, "t": own["type"], "k": own["key"], "j": result},
            )
            await session.commit()


async def _entities(workspace_id: uuid.UUID) -> dict[str, ResolvedEntity]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.execute(select(ResolvedEntity))
            return {row.key: row for row in rows.scalars()}


async def _keys(workspace_id: uuid.UUID) -> dict[tuple[str, uuid.UUID], uuid.UUID]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.execute(select(ResolvedKey))
            return {(row.key, row.source_id): row.entity_id for row in rows.scalars()}


async def _runs(workspace_id: uuid.UUID) -> list[ResolutionRun]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.execute(select(ResolutionRun).order_by(ResolutionRun.started_at))
            return list(rows.scalars())


async def _tools(workspace_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Four sources, and what each normalised: the company as it comes."""
    github, jira, pagerduty, datadog = [
        await _source(workspace_id, name) for name in ("GitHub", "Jira", "PagerDuty", "Datadog")
    ]
    sara = entity("person:email:sara@acme.io", "Sara Martin", aliases=("person:github.com:sara",))
    await _normalised(
        workspace_id,
        github,
        entity("github.com/acme/api@9f2c", "Fix refunds", type="commit"),
        sara,
    )
    await _normalised(
        workspace_id,
        github,
        entity("github.com/acme/api#41", "Refunds, PAY-42", type="pull_request"),
        entity("person:github.com:sara", "sara"),
    )
    await _normalised(
        workspace_id,
        jira,
        entity(
            "acme.atlassian.net/PAY-42",
            "Refunds are doubled",
            type="issue",
            aliases=("ticket:PAY-42",),
            state="in_progress",
        ),
        entity("person:email:sara+jira@acme.io", "Sara Martin"),
    )
    await _normalised(
        workspace_id,
        pagerduty,
        entity("service:billing-api", "Billing API", type="service"),
        entity("team:payments-team", "Payments Team", type="team"),
    )
    await _normalised(
        workspace_id,
        datadog,
        entity("incident:datadog:7f3c", "Refunds failing", type="incident", state="open"),
        entity("service:billing", "billing", type="service"),
        entity("team:payments", "payments", type="team"),
    )
    return {"github": github, "jira": jira, "pagerduty": pagerduty, "datadog": datadog}


# ── the job ──────────────────────────────────────────────────────────────────


async def test_a_workspace_s_candidates_are_resolved_across_its_sources(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    tools = await _tools(workspace)
    # Another workspace's candidates are none of this one's.
    elsewhere = await _source(acme["globex"], "GitHub")
    await _normalised(acme["globex"], elsewhere, entity("person:email:sara@acme.io", "Sara M"))

    counts = await resolve_workspace(workspace)

    entities = await _entities(workspace)
    assert sorted((e.type, key) for key, e in entities.items()) == [
        ("commit", "github.com/acme/api@9f2c"),
        ("incident", "incident:datadog:7f3c"),
        ("issue", "acme.atlassian.net/PAY-42"),
        ("person", "person:email:sara@acme.io"),
        ("pull_request", "github.com/acme/api#41"),
        ("service", "service:billing-api"),
        # Named, not described, by both: the shorter key says it.
        ("team", "team:payments"),
    ]
    sara = entities["person:email:sara@acme.io"]
    assert (sara.name, sara.confidence, sara.sources) == ("Sara Martin", 0.95, 2)
    assert (counts["entities"], counts["merged"], counts["links"]) == (7, 3, 0)
    keys = await _keys(workspace)
    assert keys[("person:github.com:sara", tools["github"])] == sara.id
    assert keys[("person:email:sara+jira@acme.io", tools["jira"])] == sara.id
    assert keys[("ticket:PAY-42", tools["jira"])] == entities["acme.atlassian.net/PAY-42"].id
    assert entities["service:billing-api"].sources == 2
    [run] = await _runs(workspace)
    assert (run.status, run.counts["mentions"]) == ("succeeded", 11)
    assert await _entities(acme["globex"]) == {}


async def test_a_source_s_two_records_of_one_thing_say_it_together(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    github = await _source(workspace, "GitHub")
    key = "github.com/acme/api"
    await _normalised(
        workspace,
        github,
        entity(key, "acme/api", type="repository", visibility="private", language="python"),
    )
    # What the repository is made of, read after it, from its tree.
    laid = entity(key, "acme/api", type="repository", modules=[{"path": "api"}], language="Python")
    laid["observed_at"] = (NOW + timedelta(minutes=1)).isoformat()
    await _normalised(workspace, github, laid, external_id="R_api:_layout")

    await resolve_workspace(workspace)

    repository = (await _entities(workspace))[key]
    # Nothing either said is lost; where both speak, the latest.
    assert repository.attributes == {
        "visibility": "private",
        "modules": [{"path": "api"}],
        "language": "Python",
    }


async def test_what_it_made_keeps_its_ids_from_one_run_to_the_next(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    tools = await _tools(workspace)
    await resolve_workspace(workspace)
    before = {key: e.id for key, e in (await _entities(workspace)).items()}

    # Sara is seen once more, under an address that says her login; a new person.
    await _normalised(
        workspace,
        tools["github"],
        entity("github.com/acme/api@a1b2", "Fix refunds, again", type="commit"),
        entity("person:email:1+sara@users.noreply.github.com", "Sara Martin"),
        entity("person:email:omar@acme.io", "Omar Haddad"),
        at=NOW + timedelta(hours=1),
    )
    await resolve_workspace(workspace)

    after = {key: e.id for key, e in (await _entities(workspace)).items()}
    assert {key: after[key] for key in before} == before
    assert "person:email:omar@acme.io" in after
    keys = await _keys(workspace)
    assert (
        keys[("person:email:1+sara@users.noreply.github.com", tools["github"])]
        == before["person:email:sara@acme.io"]
    )


async def test_nothing_new_is_nothing_to_run(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    await _tools(workspace)
    await resolve_workspace(workspace)

    counts = await resolve_workspace(workspace)

    assert counts == {"status": "nothing"}
    assert len(await _runs(workspace)) == 1


async def test_new_rules_resolve_everything_again(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    await _tools(workspace)
    await resolve_workspace(workspace)
    from leka.ingestion.resolution import job

    monkeypatch.setattr(job, "RESOLVER_VERSION", engine.RESOLVER_VERSION + 1)

    await resolve_workspace(workspace)

    runs = await _runs(workspace)
    assert [run.resolver_version for run in runs] == [
        engine.RESOLVER_VERSION,
        engine.RESOLVER_VERSION + 1,
    ]


async def test_a_source_removed_takes_its_candidates_out(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    tools = await _tools(workspace)
    await resolve_workspace(workspace)
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(text("DELETE FROM sources WHERE id = :s"), {"s": tools["jira"]})
            await session.commit()

    await resolve_workspace(workspace)

    entities = await _entities(workspace)
    assert "acme.atlassian.net/PAY-42" not in entities
    assert entities["person:email:sara@acme.io"].sources == 1


async def test_a_failed_run_changes_nothing_and_says_why(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    tools = await _tools(workspace)
    await resolve_workspace(workspace)
    before = await _entities(workspace)
    await _normalised(
        workspace,
        tools["github"],
        entity("github.com/acme/api@c3d4", "Another", type="commit"),
        at=NOW + timedelta(hours=2),
    )
    from leka.ingestion.resolution import job

    def broken(mentions: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(job, "resolve", broken)

    with pytest.raises(RuntimeError):
        await resolve_workspace(workspace)

    assert set(await _entities(workspace)) == set(before)
    last = (await _runs(workspace))[-1]
    assert (last.status, last.error) == ("failed", "RuntimeError")


async def test_normalisation_done_queues_the_workspace_s_resolution_once(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    await _tools(workspace)
    queued: list[dict[str, Any]] = []

    async def capture(job: str, *args: object, **kwargs: Any) -> object:
        queued.append({"job": job, "args": args, **kwargs})
        return object()

    monkeypatch.setattr(pipeline_module, "enqueue_job", capture)
    with workspace_scope(workspace):
        async with session_factory() as session:
            assert await pipeline_module.resolve_if_pending(session, workspace)
    [call] = queued
    assert (call["job"], call["args"], call["concurrency_key"]) == (
        RESOLVE_JOB,
        (str(workspace),),
        f"resolve:{workspace}",
    )

    await resolve_workspace(workspace)
    with workspace_scope(workspace):
        async with session_factory() as session:
            assert not await pipeline_module.resolve_if_pending(session, workspace)
    assert len(queued) == 1


async def test_the_history_of_runs_is_kept_ninety_days(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    await _tools(workspace)
    await resolve_workspace(workspace)

    result = await sweep_processing(now=datetime.now(UTC) + timedelta(days=91))

    assert result["resolution_runs"] >= 1
    assert await _runs(workspace) == []
    assert await _entities(workspace) != {}  # what the runs made is not history


# ── the API ──────────────────────────────────────────────────────────────────


async def test_members_read_what_the_workspace_resolves_to(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    tools = await _tools(workspace)
    await resolve_workspace(workspace)
    _as(identity, acme, "member")

    status = (await client.get(API)).json()
    people = (await client.get(f"{API}/entities", params={"type": "person"})).json()["data"]
    [sara] = people
    detail = (await client.get(f"{API}/entities/{sara['id']}")).json()
    found = (await client.get(f"{API}/lookup", params={"key": "ticket:PAY-42"})).json()
    merged = (await client.get(f"{API}/entities", params={"only": "merged"})).json()["data"]

    assert status["pending"] is False
    assert status["last_run"]["status"] == "succeeded"
    assert status["counts"]["entities"] == 7
    assert (sara["name"], sara["key"]) == ("Sara Martin", "person:email:sara@acme.io")
    assert {(k["key"], k["source_id"], k["kind"]) for k in detail["keys"]} >= {
        ("person:email:sara@acme.io", str(tools["github"]), "key"),
        ("person:email:sara+jira@acme.io", str(tools["jira"]), "key"),
    }
    assert {(d["kind"], d["rule"]) for d in detail["decisions"]} >= {
        ("merge", "alias"),
        ("merge", "plus_address"),
    }
    assert [e["key"] for e in found] == ["acme.atlassian.net/PAY-42"]
    assert {e["key"] for e in merged} == {
        "person:email:sara@acme.io",
        "service:billing-api",
        "team:payments",
    }


async def test_what_is_doubtful_is_found_by_what_it_is(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    jira, linear, other = [await _source(workspace, n) for n in ("Jira", "Linear", "Jira 2")]
    await _normalised(
        workspace,
        jira,
        entity(
            "acme.atlassian.net/ENG-42", "Login fails", type="issue", aliases=("ticket:ENG-42",)
        ),
        entity("person:acme.atlassian.net:5b10ac8d82e05b22cc7d4ef5", "Sara Martin"),
    )
    await _normalised(
        workspace,
        linear,
        entity("linear.app/acme/ENG-42", "Dark mode", type="issue", aliases=("ticket:ENG-42",)),
        entity("person:email:sara.martin@acme.io", "Sara Martin"),
    )
    await _normalised(
        workspace,
        other,
        entity("acme.atlassian.net/PAY-1", "Old title", type="issue", state="closed"),
        at=NOW - timedelta(days=1),
    )
    await _normalised(
        workspace,
        jira,
        entity("acme.atlassian.net/PAY-1", "New title", type="issue", state="open"),
    )
    await resolve_workspace(workspace)
    _as(identity, acme, "member")

    def keys(only: str) -> set[str]:
        return {e["key"] for e in pages[only]}

    pages = {
        only: (await client.get(f"{API}/entities", params={"only": only})).json()["data"]
        for only in ("ambiguous", "linked", "conflicted")
    }
    found = (await client.get(f"{API}/lookup", params={"key": "ticket:ENG-42"})).json()

    assert keys("ambiguous") == {"acme.atlassian.net/ENG-42", "linear.app/acme/ENG-42"}
    assert keys("linked") == {
        "person:acme.atlassian.net:5b10ac8d82e05b22cc7d4ef5",
        "person:email:sara.martin@acme.io",
    }
    [conflicted] = pages["conflicted"]
    assert conflicted["key"] == "acme.atlassian.net/PAY-1"
    assert conflicted["name"] == "New title"
    assert {c["attribute"] for c in conflicted["conflicts"]} == {"name", "state"}
    assert sorted(e["key"] for e in found) == [
        "acme.atlassian.net/ENG-42",
        "linear.app/acme/ENG-42",
    ]


async def test_another_workspace_s_entities_are_not_found(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    await _tools(acme["acme"])
    await resolve_workspace(acme["acme"])
    [some] = [e for key, e in (await _entities(acme["acme"])).items() if key.startswith("person")]
    _as(identity, acme, "other_admin")

    assert (await client.get(f"{API}/entities/{some.id}")).status_code == 404
    assert (await client.get(f"{API}/entities")).json()["data"] == []
    assert (await client.get(f"{API}/lookup", params={"key": "ticket:PAY-42"})).json() == []
