"""The intelligence engine, end to end (LEKA-377): runs, steps, findings.

Analyses run as the job runs them (analyse_workspace) against PostgreSQL —
probes whose conclusions a test sets, then the real ones over LEKA's own
repository as the company model holds it.

What these protect: a run is recorded with why it ran, from which build,
which job ran it, and what each analysis did; a finding is kept across
runs — opened, seen again, resolved when no longer seen, reopened when
seen once more — with what shows it and where that was read; an analysis
that raises, or whose findings cannot be written, fails alone — the run is
partial, the others' findings kept, its own left as they were; a
model-assisted one is skipped, said so; none succeeding is a failed run;
over LEKA's own code, what many things rely on and what no one owns are
found — and the API serves them to a member, never to another workspace.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import structlog
from httpx import AsyncClient
from sqlalchemy import select

from leka.db import session_factory, workspace_scope
from leka.intelligence import (
    ANALYZERS,
    Analyzer,
    Draft,
    Evidence,
    Finding,
    IntelligenceRun,
    IntelligenceStep,
    Material,
    Method,
    Severity,
    Subject,
)
from leka.intelligence.job import analyse_workspace
from tests.conftest import FakeIdentity
from tests.test_architecture_model import POSTGRES, _leka
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/intelligence"
T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


class Probe:
    """An analysis whose conclusions the test sets between runs."""

    def __init__(self, name: str = "probe") -> None:
        self.name = name
        self.keys: list[str] = []
        self.error: Exception | None = None
        self.subject_id = uuid.uuid4()

    def run(self, _: Material) -> list[Draft]:
        if self.error is not None:
            raise self.error
        return [
            Draft(
                key=key,
                code="probe.found",
                severity=Severity.MEDIUM,
                subject=Subject(type="entity", id=self.subject_id, name=f"thing {key}", kind="api"),
                statement=f"Found {key}.",
                params={"key": key},
                score=0.5,
                confidence=0.75,
                evidence=(Evidence(kind="entity", name=f"thing {key}", detail="it is there"),),
                sources=("github",),
            )
            for key in self.keys
        ]

    def analyzer(self, *, method: Method = Method.RULES) -> Analyzer:
        return Analyzer(
            name=self.name,
            version=2,
            category="test",
            method=method,
            reads=frozenset(),
            summary="A probe.",
            run=self.run,
        )


async def _analyse(
    workspace: uuid.UUID,
    analyzers: Sequence[Analyzer],
    at: datetime = T0,
    **kwargs: Any,
) -> dict[str, object]:
    return await analyse_workspace(
        workspace, trigger="request", analyzers=analyzers, now=at, **kwargs
    )


async def _rows[T](workspace: uuid.UUID, model: type[T], *where: Any) -> list[T]:
    with workspace_scope(workspace):
        async with session_factory() as session:
            found = await session.execute(select(model).where(*where))
            return list(found.scalars())


def _findings(workspace: uuid.UUID) -> Callable[[], Any]:
    async def read() -> dict[str, Finding]:
        return {f.key: f for f in await _rows(workspace, Finding)}

    return read


async def test_a_run_says_why_from_what_who_ran_it_and_what_each_analysis_did(
    acme: dict[str, uuid.UUID],
) -> None:
    probe = Probe()
    probe.keys = ["a", "b"]
    job = uuid.uuid4()
    structlog.contextvars.bind_contextvars(run_id=str(job))
    try:
        result = await _analyse(acme["acme"], [probe.analyzer()], by=acme["member"])
    finally:
        structlog.contextvars.unbind_contextvars("run_id")

    [run] = await _rows(acme["acme"], IntelligenceRun)
    assert result["status"] == run.status == "succeeded"
    assert (run.trigger, run.requested_by, run.job_run_id) == ("request", acme["member"], job)
    assert (run.started_at, run.finished_at) == (T0, T0)
    assert run.counts["opened"] == 2
    [step] = await _rows(acme["acme"], IntelligenceStep)
    assert (step.analyzer, step.version, step.status) == ("probe", 2, "succeeded")
    assert step.counts == {"found": 2, "opened": 2, "seen": 0, "resolved": 0, "reopened": 0}

    found = await _findings(acme["acme"])()
    assert set(found) == {"a", "b"}
    a = found["a"]
    assert (a.status, a.severity, a.rank, a.confidence) == ("open", "medium", 250, 0.75)
    assert (a.first_run_id, a.last_run_id, a.occurrences) == (run.id, run.id, 1)
    assert a.provenance == {
        "analyzer": "probe",
        "version": 2,
        "method": "rules",
        "run_id": str(run.id),
        "model_built_at": None,
        "sources": ["github"],
        "context_version": None,
    }
    assert a.evidence == [
        {"kind": "entity", "id": None, "name": "thing a", "detail": "it is there"}
    ]


async def test_a_finding_is_kept_across_runs_seen_resolved_and_reopened(
    acme: dict[str, uuid.UUID],
) -> None:
    probe = Probe()
    read = _findings(acme["acme"])

    probe.keys = ["a", "b"]
    await _analyse(acme["acme"], [probe.analyzer()], T0)
    probe.keys = ["b", "c"]
    second = await _analyse(acme["acme"], [probe.analyzer()], T0 + timedelta(hours=1))
    found = await read()
    assert (found["a"].status, found["a"].resolved_at) == ("resolved", T0 + timedelta(hours=1))
    assert found["a"].resolved_run_id == uuid.UUID(str(second["run"]))
    assert (found["b"].status, found["b"].occurrences) == ("open", 2)
    assert found["b"].first_seen_at == T0
    assert found["b"].last_seen_at == T0 + timedelta(hours=1)
    assert found["c"].status == "open"

    probe.keys = ["a"]
    third = await _analyse(acme["acme"], [probe.analyzer()], T0 + timedelta(hours=2))
    found = await read()
    assert (found["a"].status, found["a"].reopened, found["a"].resolved_at) == ("open", 1, None)
    assert {found["b"].status, found["c"].status} == {"resolved"}
    assert third["opened"] == 0
    assert (third["reopened"], third["resolved"]) == (1, 2)


async def test_an_analysis_that_fails_fails_alone_and_resolves_nothing(
    acme: dict[str, uuid.UUID],
) -> None:
    flaky, steady = Probe("flaky"), Probe("steady")
    flaky.keys, steady.keys = ["x"], ["y"]
    await _analyse(acme["acme"], [flaky.analyzer(), steady.analyzer()], T0)

    flaky.error = RuntimeError("the model moved")
    steady.keys = ["y", "z"]
    result = await _analyse(
        acme["acme"], [flaky.analyzer(), steady.analyzer()], T0 + timedelta(hours=1)
    )

    assert result["status"] == "partial"
    steps = {
        s.analyzer: s
        for s in await _rows(
            acme["acme"], IntelligenceStep, IntelligenceStep.started_at == T0 + timedelta(hours=1)
        )
    }
    assert (steps["flaky"].status, steps["flaky"].error) == ("failed", "RuntimeError")
    assert steps["steady"].status == "succeeded"
    found = await _findings(acme["acme"])()
    # Not seeing it is not knowing it is gone.
    assert found["x"].status == "open"
    assert found["x"].last_seen_at == T0
    assert found["z"].status == "open"


async def test_findings_that_cannot_be_written_fail_their_step_alone(
    acme: dict[str, uuid.UUID],
) -> None:
    unwritable, steady = Probe("unwritable"), Probe("steady")
    unwritable.keys = ["k" * 400]  # past the key's 300 characters
    steady.keys = ["y"]

    result = await _analyse(acme["acme"], [unwritable.analyzer(), steady.analyzer()])

    assert result["status"] == "partial"
    steps = {s.analyzer: s for s in await _rows(acme["acme"], IntelligenceStep)}
    assert steps["unwritable"].status == "failed"
    assert steps["unwritable"].error
    assert steps["steady"].status == "succeeded"
    assert set(await _findings(acme["acme"])()) == {"y"}


async def test_a_model_assisted_analysis_is_skipped_and_none_succeeding_is_a_failed_run(
    acme: dict[str, uuid.UUID],
) -> None:
    waiting, broken = Probe("waiting"), Probe("broken")
    skipped = await _analyse(acme["acme"], [waiting.analyzer(method=Method.MODEL)])
    [step] = await _rows(acme["acme"], IntelligenceStep)
    assert (skipped["status"], step.status, step.reason) == ("succeeded", "skipped", "no_model")

    broken.error = ValueError("no")
    failed = await _analyse(acme["acme"], [broken.analyzer()], T0 + timedelta(hours=1))
    assert failed["status"] == "failed"


# ── the real analyses, over LEKA's own repository ──────────────────────


@pytest.fixture
async def analysed(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    ids = await _leka(acme["acme"])
    await analyse_workspace(acme["acme"], trigger="model", analyzers=ANALYZERS)
    _as(identity, acme, "member")
    return ids


async def _get(client: AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_over_leka_s_own_code_what_many_rely_on_and_what_no_one_owns_are_found(
    client: AsyncClient, analysed: dict[str, uuid.UUID]
) -> None:
    findings = (await _get(client, "/findings", status="open", limit=100))["data"]
    by = {(f["code"], f["subject"]["name"]): f for f in findings}

    # PostgreSQL: the API, the worker and the scheduler keep their data in
    # it, and nothing watches it — no monitoring source.
    postgres = next(
        f
        for f in findings
        if f["code"] == "dependency.concentration" and f["subject"]["id"] == str(analysed[POSTGRES])
    )
    assert postgres["params"]["dependents"] >= 3
    assert postgres["params"]["watched"] is False
    assert postgres["severity"] in ("medium", "high")
    # No owner is named for any of it: a personal GitHub account has no
    # teams, and its code says no one owns it.
    assert any(code == "ownership.no_owner" for code, _ in by)
    # The most pressing first.
    ranks = [f["rank"] for f in findings]
    assert ranks == sorted(ranks, reverse=True)

    detail = await _get(client, f"/findings/{postgres['id']}")
    assert detail["evidence"][0]["kind"] == "entity"
    assert any(e["kind"] == "relationship" for e in detail["evidence"])
    assert detail["provenance"]["analyzer"] == "dependency_concentration"
    assert detail["provenance"]["model_built_at"] is not None
    # The kinds of the sources it rests on: the test's code host is a fake.
    assert detail["provenance"]["sources"]

    about = (await _get(client, "/findings", subject=str(analysed[POSTGRES])))["data"]
    assert {f["code"] for f in about} >= {"dependency.concentration"}


async def test_the_runs_and_the_summary_are_served_to_a_member(
    client: AsyncClient, analysed: dict[str, uuid.UUID]
) -> None:
    [run] = (await _get(client, "/runs"))["data"]
    assert (run["trigger"], run["status"]) == ("model", "succeeded")
    detail = await _get(client, f"/runs/{run['id']}")
    assert {s["analyzer"] for s in detail["steps"]} == {a.name for a in ANALYZERS}
    # No context in use yet: nothing to read for it, nothing said.
    context = next(s for s in detail["steps"] if s["analyzer"] == "context_health")
    assert context["status"] == "succeeded"
    assert context["counts"]["found"] == 0

    summary = await _get(client, "/summary")
    assert sum(summary["open"].values()) == len(
        (await _get(client, "/findings", status="open", limit=100))["data"]
    )
    assert summary["top"][0]["rank"] >= summary["top"][-1]["rank"]
    assert summary["latest"]["id"] == run["id"]


async def test_another_workspace_sees_none_of_it(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    analysed: dict[str, uuid.UUID],
) -> None:
    finding = (await _get(client, "/findings"))["data"][0]
    run = (await _get(client, "/runs"))["data"][0]

    _as(identity, acme, "other_admin")
    assert (await _get(client, "/findings"))["data"] == []
    assert (await _get(client, "/runs"))["data"] == []
    assert (await client.get(f"{API}/findings/{finding['id']}")).status_code == 404
    assert (await client.get(f"{API}/runs/{run['id']}")).status_code == 404
    assert (await _get(client, "/summary"))["open"] == {"high": 0, "medium": 0, "low": 0}
