"""From a source to an intention's answer, and back (LEKA-444).

GitHub as it answers (tests/test_processing_e2e: a repository, the issue
« Webhook lost under load », the pull request that fixes it, Sara's commit)
goes the whole way with the real stages, each run by hand where the job
loop would queue it: the pass, extraction, parsing, normalisation,
validation, resolution, enrichment, the company model, the context an
intention is grounded in, its analysis and what that says it rests on.
docs/traceability.md draws the chain and what links each step to the next,
and the two breaks this found, fixed: a source connected and never read is
said as a limit; an inferred proof names the sources it rests on.

What these protect:
- One question answered from GitHub's own records, each stage asserted on
  what it made, and what is shown as proof traced back to the source, the
  context version and the record at the source.
- A record that changes at its source reaches the model, the context, and
  the next analysis; the one before still says what it read.
- A source that fails is said failing and leaves the analysis partial; one
  not synced for 20 days is said out of date, its confidence capped.
- Two sources of one repository make one thing, not two; where they
  disagree both values are kept, each with its source, and said. A source
  connected but not yet read is not counted as consulted.
- Another workspace sees nothing of it, by its questions or by its ids.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import copy
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text, update

from leka.connectors import (
    Capability,
    RawRecord,
    Source,
    SourceKind,
    SourceService,
    get_connector,
    register_connector,
    unregister_connector,
)
from leka.connectors.errors import ConnectorError, Diagnostic, DiagnosticCode
from leka.context.job import follow_workspace
from leka.db import session_factory, workspace_scope
from leka.ingestion import ResolvedEntity
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion import sync as sync_module
from leka.ingestion.enrichment import job as enrichment_job
from leka.ingestion.enrichment.job import enrich_workspace
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.normalisation.job import normalise_source
from leka.ingestion.parsing.job import parse_source
from leka.ingestion.resolution.job import resolve_workspace
from leka.ingestion.sync import sync_source
from leka.ingestion.validation.job import validate_source
from leka.intentions.processing import analyse_intention
from leka.knowledge.job import build_workspace
from leka.platform import LocalObjectStore
from tests.conftest import FakeIdentity
from tests.test_processing_e2e import RECORDS, GitHubAsItAnswers
from tests.test_sources_api import _as, acme  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

REPOSITORY = "github.com/acme/payments"
OWNER = "Qui maintient acme/payments ?"

# What each source answers, by the first letter of its token: A all of
# GitHub's records, B only the repository, saying it is written in Go.
ANSWERS: dict[str, dict[Capability, list[tuple[str, str | None, dict[str, Any]]]]] = {}
DOWN: set[str] = set()


def _answers() -> None:
    ANSWERS.clear()
    DOWN.clear()
    ANSWERS["a"] = copy.deepcopy(RECORDS)
    ANSWERS["b"] = {Capability.REPOSITORIES: copy.deepcopy(RECORDS[Capability.REPOSITORIES])}
    ANSWERS["b"][Capability.REPOSITORIES][0][2]["language"] = "Go"


class GitHubBySource(GitHubAsItAnswers):
    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        which = self.credentials.token.get_secret_value()[0]
        if which in DOWN:
            raise ConnectorError(
                Diagnostic(
                    code=DiagnosticCode.PROVIDER_ERROR,
                    retryable=False,
                    message="GitHub answered 503.",
                    remediation="Wait for GitHub.",
                )
            )
        for external_id, container, payload in ANSWERS.get(which, {}).get(capability, []):
            yield RawRecord(
                kind=capability,
                external_id=external_id,
                container=container,
                payload=payload,
                fetched_at=datetime.now(UTC),
            )


@pytest.fixture(autouse=True)
def github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """GitHub, as each source answers, in place of the real connector; a
    local store; the jobs run by hand, not queued."""
    real = get_connector(SourceKind.GITHUB)
    unregister_connector(SourceKind.GITHUB)
    register_connector(GitHubBySource)
    _answers()
    from leka.platform import storage

    monkeypatch.setattr(storage, "_store", LocalObjectStore(tmp_path))

    async def queued(job: str, *args: object, **kwargs: object) -> object:
        return object()

    for module in (sync_module, pipeline_module, enrichment_job):
        monkeypatch.setattr(module, "enqueue_job", queued)
    yield
    unregister_connector(SourceKind.GITHUB)
    register_connector(real)


async def _source(workspace: uuid.UUID, name: str, token: str) -> Source:
    with workspace_scope(workspace):
        async with session_factory() as session:
            service = SourceService(session, workspace, actor_user_id=None)
            source = await service.create(SourceKind.GITHUB, name, {}, {"token": token * 24})
            await service.test(source)
            await service.activate(source)
            await session.commit()
            return source


async def _processed(workspace: uuid.UUID, source: Source) -> dict[str, Any]:
    """One source, from its pass to validated candidates: what each made."""
    made: dict[str, Any] = {"sync": await sync_source(workspace, source.id, full=True)}
    for name, stage in (
        ("extraction", extract_source),
        ("parsing", parse_source),
        ("normalisation", normalise_source),
        ("validation", validate_source),
    ):
        made[name] = await stage(workspace, source.id)
    return made


async def _modelled(workspace: uuid.UUID) -> dict[str, object]:
    """The workspace's stages: resolution, enrichment, the company model."""
    await resolve_workspace(workspace)
    await enrich_workspace(workspace)
    return await build_workspace(workspace)


async def _ask(client: AsyncClient, workspace: uuid.UUID, words: str) -> dict[str, Any]:
    """Asked, analysed: the intention and its analysis, as the API says them."""
    response = await client.post("/api/v1/intentions", json={"text": words})
    assert response.status_code == 201, response.text
    intention: dict[str, Any] = response.json()["intention"]
    await analyse_intention(workspace, uuid.UUID(intention["id"]), trigger="created")
    analysis = await client.get(f"/api/v1/intentions/{intention['id']}/analysis")
    assert analysis.status_code == 200, analysis.text
    return {"intention": intention, "analysis": analysis.json()}


def _finding(asked: dict[str, Any], code: str) -> dict[str, Any]:
    found: dict[str, Any] = next(
        f for f in asked["analysis"]["result"]["findings"] if f["code"] == code
    )
    return found


def _evidence(asked: dict[str, Any], kind: str) -> dict[str, Any]:
    found: dict[str, Any] = next(
        e for e in asked["analysis"]["result"]["evidence"] if e["id"].startswith(f"{kind}:")
    )
    return found


def _consulted(asked: dict[str, Any]) -> dict[str, str]:
    return {s["name"]: s["state"] for s in asked["analysis"]["result"]["explanation"]["consulted"]}


# ── the whole way, once ──────────────────────────────────────────────────────


async def test_a_record_reaches_an_answer_and_the_answer_traces_back_to_it(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    github = await _source(workspace, "Acme GitHub", "a")

    made = await _processed(workspace, github)
    # The pass: what GitHub answered, stored.
    assert made["sync"].status == "succeeded"
    assert made["sync"].records == {
        "repositories": 1,
        "issues": 1,
        "pull_requests": 1,
        "commits": 1,
    }
    # Extraction, parsing, normalisation: each record through, none lost.
    for stage in ("extraction", "parsing", "normalisation"):
        assert made[stage]["failed"] == 0, stage
    assert (
        made["extraction"]["extracted"],
        made["parsing"]["parsed"],
        made["normalisation"]["normalised"],
    ) == (4, 4, 4)
    # Validation: GitHub as it answers, nothing quarantined.
    assert made["validation"]["quarantined"] == 0

    built = await _modelled(workspace)
    # Resolution made one Sara of her address and her login; enrichment
    # joined them: the model holds the repository, the issue, the pull
    # request, the commit and two people — nothing twice.
    assert (built["entities"], built["type.person"], built["relationships_invalid"]) == (6, 2, 0)

    _as(identity, acme, "admin")
    asked = await _ask(client, workspace, OWNER)
    intention, analysis = asked["intention"], asked["analysis"]
    # Understood: who, about the repository LEKA knows by that name.
    assert intention["goal"] == "find_owner"
    [about] = intention["understanding"]["entities"]
    assert (about["name"], about["type"], about["how"]) == ("acme/payments", "repository", "named")

    result = analysis["result"]
    assert result["status"] == "complete"
    maintainers = _finding(asked, "ownership.maintainers")
    assert sorted(maintainers["params"]["people"]) == ["Sara K.", "omar"]
    # The context it read, by its version, kept with the analysis.
    assert analysis["context_id"] == intention["context_id"]
    assert result["explanation"]["context_version"] == analysis["context_version"] == 1
    # The source it really read, and in what state.
    assert _consulted(asked) == {"Acme GitHub": "read"}

    # Each proof, traced back: the repository to its source…
    repository = _evidence(asked, "entity")
    assert (repository["origin"], [s["name"] for s in repository["sources"]]) == (
        "stated",
        ["Acme GitHub"],
    )
    # …and through its context's version to the record GitHub gave.
    traced = await client.get(
        f"/api/v1/context/{analysis['context_id']}/elements/{repository['ref_id']}/evidence",
        params={"version": analysis["context_version"]},
    )
    assert traced.status_code == 200, traced.text
    [record] = traced.json()["records"]
    assert (record["source_name"], record["kind"], record["external_id"]) == (
        "Acme GitHub",
        "repositories",
        "R_kgDO1",
    )
    assert record["url"] == "https://github.com/acme/payments"
    # Who maintains it is LEKA's inference, said so, never a record's word.
    maintained = next(e for e in result["evidence"] if e["ref_type"] == "maintained_by")
    assert (maintained["kind"], maintained["origin"]) == ("inference", "inferred")
    assert 0 < maintained["confidence"] < 1


# ── a change at the source ───────────────────────────────────────────────────


async def test_a_change_at_the_source_reaches_the_context_and_the_next_analysis(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    github = await _source(workspace, "Acme GitHub", "a")
    await _processed(workspace, github)
    await _modelled(workspace)
    _as(identity, acme, "admin")
    before = await _ask(client, workspace, OWNER)
    assert "language: Python" in _evidence(before, "entity")["detail"]

    # The repository is rewritten in Rust; the next pass reads it.
    ANSWERS["a"][Capability.REPOSITORIES][0][2]["language"] = "Rust"
    await _processed(workspace, github)
    built = await _modelled(workspace)
    assert built["changed"] == 1  # the repository, nothing else
    # The model changed under the context: it is made again.
    followed = await follow_workspace(workspace)
    assert followed["version"] >= 1

    after = await _ask(client, workspace, OWNER)
    assert "language: Rust" in _evidence(after, "entity")["detail"]
    # The analysis before still says what it read, and from which version.
    kept = await client.get(f"/api/v1/intentions/{before['intention']['id']}/analysis")
    assert "language: Python" in _evidence({"analysis": kept.json()}, "entity")["detail"]


# ── a source in trouble ──────────────────────────────────────────────────────


async def test_a_failing_then_stale_source_is_never_said_up_to_date(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    github = await _source(workspace, "Acme GitHub", "a")
    await _processed(workspace, github)
    await _modelled(workspace)
    _as(identity, acme, "admin")

    DOWN.add("a")
    failed = await sync_source(workspace, github.id)
    assert (failed.status, failed.error) == ("failed", "PROVIDER_ERROR")
    asked = await _ask(client, workspace, OWNER)
    result = asked["analysis"]["result"]
    # What it read is as of its last good pass: said, the answer partial.
    assert _consulted(asked) == {"Acme GitHub": "error"}
    assert result["status"] == "partial"
    assert "limit.source_error" in [n["code"] for n in result["explanation"]["limits"]]
    assert "analysis.sources_pending" in [n["code"] for n in result["missing"]]

    # GitHub answers again, but nothing has been read for 20 days.
    DOWN.clear()
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE sources SET status = 'active', sync_status = 'idle', "
                    "last_error = NULL, last_synced_at = :at WHERE id = :id"
                ),
                {"at": datetime.now(UTC) - timedelta(days=20), "id": github.id},
            )
            await session.commit()
    asked = await _ask(client, workspace, OWNER)
    explanation = asked["analysis"]["result"]["explanation"]
    assert _consulted(asked) == {"Acme GitHub": "stale"}
    assert [n["code"] for n in explanation["stale"]] == ["stale.source"]
    assert explanation["confidence"]["level"] in ("medium", "low")
    assert "confidence.sources_unsure" in [r["code"] for r in explanation["confidence"]["reasons"]]


# ── two sources, one thing ───────────────────────────────────────────────────


async def test_two_sources_of_one_repository_make_one_thing_their_disagreement_said(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    a = await _source(workspace, "GitHub A", "a")
    b = await _source(workspace, "GitHub B", "b")
    await _source(workspace, "GitHub C", "c")  # connected, never read
    await _processed(workspace, a)
    await _processed(workspace, b)
    await _modelled(workspace)

    with workspace_scope(workspace):
        async with session_factory() as session:
            repositories = await session.scalar(
                select(func.count())
                .select_from(ResolvedEntity)
                .where(ResolvedEntity.key == REPOSITORY)
            )
    assert repositories == 1

    _as(identity, acme, "admin")
    asked = await _ask(client, workspace, OWNER)
    explanation = asked["analysis"]["result"]["explanation"]
    repository = _evidence(asked, "entity")
    assert sorted(s["name"] for s in repository["sources"]) == ["GitHub A", "GitHub B"]
    [conflict] = explanation["conflicts"]
    assert conflict["about"] == "language"
    assert sorted((v["value"], v["by"][0]) for v in conflict["values"]) == [
        ("Go", "GitHub B"),
        ("Python", "GitHub A"),
    ]
    assert explanation["confidence"]["level"] == "medium"
    # Consulted are the sources it read from — not C, connected and empty.
    assert _consulted(asked) == {"GitHub A": "read", "GitHub B": "read"}


# ── another workspace ────────────────────────────────────────────────────────


async def test_another_workspace_sees_nothing_of_it(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    github = await _source(workspace, "Acme GitHub", "a")
    await _processed(workspace, github)
    await _modelled(workspace)
    _as(identity, acme, "admin")
    ours = await _ask(client, workspace, OWNER)

    _as(identity, acme, "other_admin")
    theirs = await _ask(client, acme["globex"], OWNER)
    assert theirs["intention"]["understanding"]["entities"] == []
    assert theirs["analysis"]["result"]["evidence"] == []
    assert _consulted(theirs) == {}
    # Nor by its ids.
    intention, analysis = ours["intention"], ours["analysis"]
    repository = _evidence(ours, "entity")
    for path in (
        f"/api/v1/intentions/{intention['id']}/analysis",
        f"/api/v1/context/{analysis['context_id']}/elements/{repository['ref_id']}/evidence",
    ):
        assert (await client.get(path)).status_code == 404, path


# ── breaks found (LEKA-444), fixed ───────────────────────────────────────────


async def test_a_source_connected_but_never_read_is_said_as_a_limit(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    github = await _source(workspace, "Acme GitHub", "a")
    await _source(workspace, "GitHub C", "c")
    await _processed(workspace, github)
    await _modelled(workspace)
    _as(identity, acme, "admin")
    asked = await _ask(client, workspace, OWNER)
    explanation = asked["analysis"]["result"]["explanation"]
    # It may hold the answer: the analysis should say it has not read it.
    assert any("GitHub C" in n["text"] for n in explanation["limits"])


async def test_a_source_never_read_is_a_limit_only_when_it_may_hold_the_answer(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    # Who maintains a repository: code may say it, monitoring does not (LEKA-448).
    workspace = acme["acme"]
    github = await _source(workspace, "Acme GitHub", "a")
    await _source(workspace, "GitHub C", "c")
    monitoring = await _source(workspace, "Acme Datadog", "d")
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                update(Source).where(Source.id == monitoring.id).values(kind=SourceKind.DATADOG)
            )
            await session.commit()
    await _processed(workspace, github)
    await _modelled(workspace)
    _as(identity, acme, "admin")
    asked = await _ask(client, workspace, OWNER)
    limits = asked["analysis"]["result"]["explanation"]["limits"]
    unread = [n["params"]["source"] for n in limits if n["code"] == "limit.source_unread"]
    assert unread == ["GitHub C"]


async def test_an_inferred_proof_names_the_sources_it_was_inferred_from(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    github = await _source(workspace, "Acme GitHub", "a")
    await _processed(workspace, github)
    await _modelled(workspace)
    _as(identity, acme, "admin")
    asked = await _ask(client, workspace, OWNER)
    maintained = next(
        e for e in asked["analysis"]["result"]["evidence"] if e["ref_type"] == "maintained_by"
    )
    # Inferred from the commit and the pull request: GitHub, said.
    assert [s["name"] for s in maintained["sources"]] == ["Acme GitHub"]
