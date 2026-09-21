"""What the database refuses to store about job runs.

LEKA-334. Two workers must not run the same sync at once, one event must not
create the same job's run twice, a run must not point at another customer's
event. Application code that "checks first" has a race between the check and
the write; a constraint does not — so PostgreSQL holds these.

Written before the table existed, and run to watch every one of them fail. They
talk SQL rather than the model on purpose: the invariants belong to the schema.

Nothing here commits. The `session` fixture rolls back, which is also how rows
with no workspace — system runs — are cleaned up: the fixture's own cleanup
only knows about workspaces.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine.interfaces import ReflectedColumn
from sqlalchemy.exc import IntegrityError, NoSuchTableError
from sqlalchemy.ext.asyncio import AsyncSession

from leka.db import Base, engine
from leka.platform import Workspace
from tests.test_tenant_isolation import TENANT_FREE_TABLES

pytestmark = pytest.mark.integration

JOB_RUN_COLUMNS = {
    "id",
    "for_workspace_id",
    "event_id",
    "job",
    "args",
    "kwargs",
    "queue",
    "status",
    "attempts",
    "max_attempts",
    "concurrency_key",
    "request_id",
    "next_run_at",
    "locked_until",
    "enqueued_at",
    "last_error",
    "started_at",
    "finished_at",
    "created_at",
    "updated_at",
}


async def _workspace(session: AsyncSession) -> uuid.UUID:
    workspace = Workspace(name="jr", slug=f"jr-{uuid.uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    return workspace.id


async def _event(session: AsyncSession, workspace_id: uuid.UUID) -> uuid.UUID:
    result = await session.execute(
        text(
            "INSERT INTO events (workspace_id, type) VALUES (:w, 'source.sync_requested') "
            "RETURNING id"
        ),
        {"w": workspace_id},
    )
    identifier: uuid.UUID = result.scalar_one()
    return identifier


async def _run(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    job: str = "leka.example.tasks.run",
    key: str | None = None,
    status: str = "queued",
    attempts: int = 0,
    max_attempts: int = 3,
    queue: str = "leka",
) -> uuid.UUID:
    result = await session.execute(
        text(
            "INSERT INTO job_runs (for_workspace_id, event_id, job, concurrency_key, "
            "status, attempts, max_attempts, queue) "
            "VALUES (:w, :e, :j, :k, :s, :a, :m, :q) RETURNING id"
        ),
        {
            "w": workspace_id,
            "e": event_id,
            "j": job,
            "k": key,
            "s": status,
            "a": attempts,
            "m": max_attempts,
            "q": queue,
        },
    )
    identifier: uuid.UUID = result.scalar_one()
    return identifier


async def _refused(session: AsyncSession, statement: str, **params: object) -> None:
    """The database must reject this. A savepoint keeps the session usable."""
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(text(statement), params)


async def _columns(table: str) -> dict[str, ReflectedColumn]:
    async with engine.connect() as connection:
        try:
            return await connection.run_sync(
                lambda sync: {column["name"]: column for column in inspect(sync).get_columns(table)}
            )
        except NoSuchTableError:
            pytest.fail(f"table {table!r} does not exist")


# ── Shape ─────────────────────────────────────────────────────────────────


async def test_job_runs_has_the_columns_the_design_names() -> None:
    assert set(await _columns("job_runs")) == JOB_RUN_COLUMNS


async def test_job_runs_has_no_workspace_id_column() -> None:
    """It names the customer `for_workspace_id`, on purpose.

    A column called workspace_id reads as the isolation column, and the session
    guard only protects models that inherit WorkspaceScopedMixin — a nullable
    one would look protected and not be. The different name is what keeps anyone
    from assuming so.
    """
    columns = await _columns("job_runs")
    assert "workspace_id" not in columns
    assert columns["for_workspace_id"]["nullable"] is True


def test_the_table_is_listed_as_tenant_free_with_a_reason() -> None:
    """Rule 2 has two documented exceptions per table, in one visible list.

    The reason is written beside the entry in test_tenant_isolation; this only
    proves the entry exists, because without it that file's own test fails and
    somebody "fixes" it by loosening the assertion.
    """
    assert "job_runs" in TENANT_FREE_TABLES
    assert "job_runs" in Base.metadata.tables


# ── Defaults and closed sets ──────────────────────────────────────────────


async def test_a_run_starts_queued_on_the_default_queue_with_three_attempts(
    session: AsyncSession,
) -> None:
    result = await session.execute(
        text(
            "INSERT INTO job_runs (job) VALUES ('leka.example.tasks.run') "
            "RETURNING status, queue, attempts, max_attempts, enqueued_at"
        )
    )
    assert tuple(result.one()) == ("queued", "leka", 0, 3, None)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO job_runs (job, status) VALUES ('leka.example.tasks.run', 'bogus')",
        "INSERT INTO job_runs (job, queue) VALUES ('leka.example.tasks.run', 'leka:urgent')",
    ],
    ids=["status", "queue"],
)
async def test_a_value_outside_the_closed_set_is_refused(
    session: AsyncSession, statement: str
) -> None:
    await _refused(session, statement)


async def test_a_run_may_not_promise_zero_attempts(session: AsyncSession) -> None:
    """A maximum of 0 reads as "disabled" to whoever types it and as "never
    try" to the code. Refuse it rather than pick a meaning."""
    await _refused(
        session,
        "INSERT INTO job_runs (job, max_attempts) VALUES ('leka.example.tasks.run', 0)",
    )


async def test_a_run_cannot_have_attempted_more_than_its_maximum(session: AsyncSession) -> None:
    await _refused(
        session,
        "INSERT INTO job_runs (job, attempts, max_attempts) "
        "VALUES ('leka.example.tasks.run', 4, 3)",
    )


# ── Concurrency: at most one active run per key ───────────────────────────


@pytest.mark.parametrize("status", ["queued", "running", "retrying"])
async def test_only_one_active_run_per_concurrency_key(session: AsyncSession, status: str) -> None:
    workspace = await _workspace(session)
    await _run(session, workspace_id=workspace, key="sync:source-1", status=status)

    await _refused(
        session,
        "INSERT INTO job_runs (for_workspace_id, job, concurrency_key) "
        "VALUES (:w, 'leka.example.tasks.run', 'sync:source-1')",
        w=workspace,
    )


@pytest.mark.parametrize("status", ["succeeded", "failed"])
async def test_a_finished_run_frees_its_concurrency_key(session: AsyncSession, status: str) -> None:
    workspace = await _workspace(session)
    await _run(session, workspace_id=workspace, key="sync:source-1", status=status)
    await _run(session, workspace_id=workspace, key="sync:source-1")


async def test_the_same_key_in_two_workspaces_does_not_collide(session: AsyncSession) -> None:
    first = await _workspace(session)
    second = await _workspace(session)
    await _run(session, workspace_id=first, key="sync:source-1")
    await _run(session, workspace_id=second, key="sync:source-1")


async def test_system_runs_with_no_workspace_still_collide(session: AsyncSession) -> None:
    """NULLs are distinct in a unique index, so a naive one would let two
    workers run the same retention sweep at once."""
    await _run(session, key="sweep:retention")

    await _refused(
        session,
        "INSERT INTO job_runs (job, concurrency_key) "
        "VALUES ('leka.example.tasks.run', 'sweep:retention')",
    )


async def test_runs_without_a_concurrency_key_never_collide(session: AsyncSession) -> None:
    await _run(session)
    await _run(session)


# ── Idempotency: one event, one run per job ───────────────────────────────


async def test_one_event_yields_one_run_per_job(session: AsyncSession) -> None:
    """The dispatcher can die after creating the runs and before marking the
    event dispatched, and will then do it again. This is what turns that second
    attempt into a refusal instead of a second execution."""
    workspace = await _workspace(session)
    event = await _event(session, workspace)
    await _run(session, workspace_id=workspace, event_id=event, job="leka.a.tasks.one")

    await _refused(
        session,
        "INSERT INTO job_runs (for_workspace_id, event_id, job) "
        "VALUES (:w, :e, 'leka.a.tasks.one')",
        w=workspace,
        e=event,
    )


async def test_one_event_may_fan_out_to_different_jobs(session: AsyncSession) -> None:
    workspace = await _workspace(session)
    event = await _event(session, workspace)
    await _run(session, workspace_id=workspace, event_id=event, job="leka.a.tasks.one")
    await _run(session, workspace_id=workspace, event_id=event, job="leka.b.tasks.two")


# ── Tenancy ───────────────────────────────────────────────────────────────


async def test_a_run_cannot_point_at_another_workspaces_event(session: AsyncSession) -> None:
    """The composite foreign key, as for entities and raw_payloads."""
    mine = await _workspace(session)
    theirs = await _workspace(session)
    their_event = await _event(session, theirs)

    await _refused(
        session,
        "INSERT INTO job_runs (for_workspace_id, event_id, job) "
        "VALUES (:w, :e, 'leka.example.tasks.run')",
        w=mine,
        e=their_event,
    )


async def test_a_run_with_an_event_must_name_its_workspace(session: AsyncSession) -> None:
    """With for_workspace_id NULL the composite foreign key is not checked at
    all — that is how MATCH SIMPLE works — so an event reference with no
    workspace beside it would be unconstrained. A CHECK closes it."""
    workspace = await _workspace(session)
    event = await _event(session, workspace)

    await _refused(
        session,
        "INSERT INTO job_runs (event_id, job) VALUES (:e, 'leka.example.tasks.run')",
        e=event,
    )


async def test_deleting_a_workspace_deletes_its_runs_only(session: AsyncSession) -> None:
    """Erasing a customer erases their history. A system run belongs to no
    customer and stays."""
    workspace = await _workspace(session)
    event = await _event(session, workspace)
    await _run(session, workspace_id=workspace, event_id=event)
    system_run = await _run(session)

    await session.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace})

    runs = await session.execute(
        text("SELECT count(*) FROM job_runs WHERE for_workspace_id = :w"), {"w": workspace}
    )
    survivors = await session.execute(
        text("SELECT count(*) FROM job_runs WHERE id = :r"), {"r": system_run}
    )
    assert (runs.scalar_one(), survivors.scalar_one()) == (0, 1)


async def test_deleting_an_event_keeps_its_run_and_its_workspace(session: AsyncSession) -> None:
    """Events are pruned on a retention schedule; the execution history is not.
    Losing the event must not turn a customer's run into a system run — that
    would silently move it out of their view and into ours."""
    workspace = await _workspace(session)
    event = await _event(session, workspace)
    run = await _run(session, workspace_id=workspace, event_id=event)

    await session.execute(text("DELETE FROM events WHERE id = :e"), {"e": event})

    row = (
        await session.execute(
            text("SELECT event_id, for_workspace_id FROM job_runs WHERE id = :r"), {"r": run}
        )
    ).one()
    assert tuple(row) == (None, workspace)
