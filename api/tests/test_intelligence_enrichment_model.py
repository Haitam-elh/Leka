"""Knowledge enrichment, end to end (LEKA-380): proposed, decided, applied
— and undone.

TWO COMPANIES.

The first is written into the model as a build writes it. GitHub and AWS
are connected. payment-api's code and runtime are unknown, but a repository
acme/payments and a resource payment-api-prod exist. auth-service's code is
acme/auth, which the Identity team owns and describes as "Sign-in and
tokens"; no one is named as auth-service's owner. Nadia and Thomas maintain
user-service, and both are members of Payments. checkout is said critical;
cart is part of it, and its catalogue says cart is low. checkout-worker
belongs to no application.

The second is the pipeline's own (tests/test_company_model_job.py):
normalised, resolved, enriched and built, so that a validated fact goes
through a real build. A test analysis proposes three things there:
- Billing's description;
- that Sara is a member of payments;
- that the pull request's state, which GitHub states, is something else.

What these protect:
- Each family is proposed from the evidence: the repository and the
  resource of a service's name, the team owning its repository — accepted
  by the policy, sure and adding — and the team of its maintainers, the
  application of its name, the criticality of the application holding it
  (above a source's word, so an override), the repository's description.
  Each keeps its evidence, its confidence and where it was read.
- A person accepts, rejects or sends back; a decision stands from one run
  to the next; a candidate whose evidence went is withdrawn; another
  workspace's candidates are no one's here; a member may read but not
  decide.
- Applied by the next build, a fact is in the model with the origin
  `accepted` and the decision in its provenance, read as such by the API.
  An override needs to be said, and replaces the source's word, which
  comes back when it is rejected.
- A build that fails changes nothing and keeps the fact for the next.
- An analysis that fails withdraws nothing.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from leka.api import intelligence as intelligence_api
from leka.capabilities import Gateway
from leka.capabilities.gateway import service as gateway_service
from leka.connectors.models import Source, SourceKind, SourceStatus
from leka.core.config import settings
from leka.db import session_factory, workspace_scope
from leka.intelligence import (
    ANALYZERS,
    Analyzer,
    EnrichmentCandidate,
    Material,
    Method,
    Proposal,
    Reads,
    Subject,
)
from leka.intelligence import job as intelligence_job
from leka.intelligence.job import analyse_workspace
from leka.knowledge import (
    Entity,
    EntityType,
    Lifecycle,
    ModelAssertion,
    Relationship,
    RelationshipType,
)
from leka.knowledge import job as model_job
from leka.knowledge.build import build as real_build
from leka.knowledge.job import build_workspace, sweep_models
from tests.conftest import FakeIdentity
from tests.test_company_model_job import _built, _entities
from tests.test_enrichment_job import PR, SARA, SERVICE, TEAM
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/intelligence/enrichment"
NOW = datetime.now(UTC).replace(microsecond=0)
ENRICHMENT = tuple(a for a in ANALYZERS if a.category == "enrichment")


async def _company(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    with workspace_scope(workspace):
        async with session_factory() as session:
            for kind, name in ((SourceKind.GITHUB, "GitHub"), (SourceKind.AWS, "AWS")):
                source = Source(
                    workspace_id=workspace,
                    kind=kind,
                    name=name,
                    status=SourceStatus.ACTIVE,
                    config={},
                    last_synced_at=NOW - timedelta(hours=1),
                )
                session.add(source)
                ids[name] = source.id = uuid.uuid4()
            await session.flush()

            def thing(
                name: str,
                type_: EntityType,
                source: str = "GitHub",
                *,
                stated: tuple[str, ...] = (),
                **attributes: object,
            ) -> None:
                row = Entity(
                    workspace_id=workspace,
                    type=type_,
                    key=f"{type_.value}:{name}",
                    name=name,
                    attributes=attributes,
                    provenance={
                        "sources": [{"source_id": str(ids[source]), "key": name, "kind": "id"}],
                        "attributes": {said: {"origin": "source"} for said in stated},
                    },
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                )
                session.add(row)
                ids[name] = row.id = uuid.uuid4()

            def tie(a: str, kind: RelationshipType, b: str) -> None:
                session.add(
                    Relationship(
                        workspace_id=workspace,
                        from_entity_id=ids[a],
                        to_entity_id=ids[b],
                        type=kind,
                        confidence=1.0,
                        origin="stated",
                        rule="stated",
                        provenance=[],
                    )
                )

            for service in ("payment-api", "auth-service", "user-service", "checkout-worker"):
                thing(service, EntityType.SERVICE)
            thing("cart", EntityType.SERVICE, criticality="low", stated=("criticality",))
            thing(
                "checkout", EntityType.APPLICATION, criticality="critical", stated=("criticality",)
            )
            thing("acme/payments", EntityType.REPOSITORY)
            thing("acme/auth", EntityType.REPOSITORY, description="Sign-in and tokens")
            thing("payment-api-prod", EntityType.INFRA_RESOURCE, "AWS")
            thing("Identity", EntityType.TEAM)
            thing("Payments", EntityType.TEAM)
            thing("nadia", EntityType.PERSON)
            thing("thomas", EntityType.PERSON)
            await session.flush()
            tie("acme/auth", RelationshipType.PART_OF, "auth-service")
            tie("acme/auth", RelationshipType.OWNED_BY, "Identity")
            tie("user-service", RelationshipType.MAINTAINED_BY, "nadia")
            tie("user-service", RelationshipType.MAINTAINED_BY, "thomas")
            tie("nadia", RelationshipType.MEMBER_OF, "Payments")
            tie("thomas", RelationshipType.MEMBER_OF, "Payments")
            tie("cart", RelationshipType.PART_OF, "checkout")
            await session.commit()
    return ids


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """The model builds a decision or the policy asks for, captured."""
    asked: list[uuid.UUID] = []

    async def queue(workspace_id: uuid.UUID) -> bool:
        asked.append(workspace_id)
        return True

    monkeypatch.setattr(intelligence_api, "queue_model_build", queue)
    monkeypatch.setattr(intelligence_job, "queue_model_build", queue)
    return asked


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The intelligence runs a reprocessing asks for, captured."""
    asked: list[dict[str, Any]] = []

    async def queue(workspace_id: uuid.UUID, **kwargs: Any) -> bool:
        asked.append({"workspace_id": workspace_id, **kwargs})
        return True

    monkeypatch.setattr(intelligence_api, "queue_run", queue)
    return asked


@pytest.fixture
async def company(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    ids = await _company(acme["acme"])
    _as(identity, acme, "admin")
    return ids


async def _get(client: AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _candidates(workspace: uuid.UUID) -> dict[tuple[str, str], EnrichmentCandidate]:
    with workspace_scope(workspace):
        async with session_factory() as session:
            rows = await session.execute(select(EnrichmentCandidate))
            return {(c.code, c.subject_name): c for c in rows.scalars()}


async def _assertions(workspace: uuid.UUID) -> list[ModelAssertion]:
    with workspace_scope(workspace):
        async with session_factory() as session:
            return list((await session.execute(select(ModelAssertion))).scalars())


# ── proposed from the evidence ─────────────────────────────────────────────


async def test_each_family_is_proposed_from_the_evidence(
    acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID], builds: list[uuid.UUID]
) -> None:
    await analyse_workspace(acme["acme"], trigger="model", analyzers=ANALYZERS)
    found = await _candidates(acme["acme"])

    assert {(code, name): (c.status, c.family) for (code, name), c in found.items()} == {
        ("enrichment.code", "payment-api"): ("proposed", "relationship"),
        ("enrichment.runtime", "payment-api"): ("proposed", "relationship"),
        # The team owning its code: sure, adding — the policy's.
        ("enrichment.owner", "auth-service"): ("accepted", "organisation"),
        ("enrichment.owner", "user-service"): ("proposed", "organisation"),
        ("enrichment.application", "checkout-worker"): ("proposed", "business"),
        ("enrichment.criticality", "cart"): ("proposed", "semantic"),
        ("enrichment.description", "auth-service"): ("proposed", "semantic"),
    }
    code = found[("enrichment.code", "payment-api")]
    assert (code.relationship, code.start_id, code.end_id, code.confidence) == (
        "part_of",
        company["acme/payments"],
        company["payment-api"],
        0.8,
    )
    assert code.provenance["analyzer"] == "enrich_code"
    assert code.provenance["sources"] == ["github"]
    maintainers = found[("enrichment.owner", "user-service")]
    assert (maintainers.end_id, maintainers.confidence) == (company["Payments"], 0.85)
    critical = found[("enrichment.criticality", "cart")]
    assert (critical.value, critical.current, critical.overrides) == ("critical", "low", True)

    # Accepted by the policy: a fact of the model, a build asked for.
    owner = found[("enrichment.owner", "auth-service")]
    assert (owner.decided_via, owner.decided_by) == ("policy", None)
    [fact] = await _assertions(acme["acme"])
    assert (fact.id, fact.kind, fact.relationship_type) == (owner.id, "relationship", "owned_by")
    assert (fact.from_entity_id, fact.to_entity_id) == (
        company["auth-service"],
        company["Identity"],
    )
    assert fact.provenance["decided_via"] == "policy"
    assert builds == [acme["acme"]]


async def test_the_api_lists_summarises_and_details_them(
    client: AsyncClient, acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID], builds: Any
) -> None:
    await analyse_workspace(acme["acme"], trigger="model", analyzers=ANALYZERS)

    summary = await _get(client, "/summary")
    assert summary == {
        "proposed": 6,
        "accepted": 1,
        "rejected": 0,
        "withdrawn": 0,
        "by_policy": 1,
        "families": {"business": 1, "organisation": 1, "relationship": 2, "semantic": 2},
    }
    waiting = (await _get(client, "/candidates", status="proposed", limit=50))["data"]
    assert len(waiting) == 6
    semantic = (await _get(client, "/candidates", family="semantic"))["data"]
    assert {c["code"] for c in semantic} == {"enrichment.criticality", "enrichment.description"}
    about = (await _get(client, "/candidates", subject=str(company["acme/payments"])))["data"]
    assert [c["code"] for c in about] == ["enrichment.code"]

    [code] = about
    detail = await _get(client, f"/candidates/{code['id']}")
    assert detail["subject"]["name"] == "payment-api"
    assert detail["start"]["name"] == "acme/payments"
    assert detail["end"]["id"] == str(company["payment-api"])
    assert detail["evidence"][0]["name"] == "acme/payments"
    assert detail["provenance"]["analyzer"] == "enrich_code"
    assert detail["history"] == []
    assert detail["status"] == "proposed"


# ── decided ────────────────────────────────────────────────────────────────


async def test_a_person_accepts_rejects_and_sends_back(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    company: dict[str, uuid.UUID],
    builds: list[uuid.UUID],
    runs: list[dict[str, Any]],
) -> None:
    workspace = acme["acme"]
    await analyse_workspace(workspace, trigger="model", analyzers=ANALYZERS)
    found = await _candidates(workspace)
    code = found[("enrichment.code", "payment-api")]
    runtime = found[("enrichment.runtime", "payment-api")]
    critical = found[("enrichment.criticality", "cart")]
    by_policy = found[("enrichment.owner", "auth-service")]
    builds.clear()

    # A member reads, and does not decide.
    _as(identity, acme, "member")
    assert (await client.get(f"{API}/candidates/{code.id}")).status_code == 200
    refused = await client.post(f"{API}/candidates/{code.id}/accept", json={})
    assert refused.status_code == 403
    _as(identity, acme, "admin")

    accepted = await client.post(
        f"{API}/candidates/{code.id}/accept", json={"reason": "It is its repository."}
    )
    assert accepted.status_code == 200, accepted.text
    said = accepted.json()
    assert (said["status"], said["decided_via"], said["reason"]) == (
        "accepted",
        "person",
        "It is its repository.",
    )
    assert said["decided_by"] == str(acme["admin"])
    assert [h["status"] for h in said["history"]] == ["accepted"]
    assert builds == [workspace]
    # Decided: not again.
    again = await client.post(f"{API}/candidates/{code.id}/accept", json={})
    assert again.status_code == 409

    # Replacing a source's word: only by saying so.
    unsaid = await client.post(f"{API}/candidates/{critical.id}/accept", json={})
    assert unsaid.status_code == 409
    assert "override" in unsaid.json()["error"]["message"]
    overridden = await client.post(
        f"{API}/candidates/{critical.id}/accept", json={"override": True}
    )
    assert overridden.status_code == 200, overridden.text

    rejected = await client.post(
        f"{API}/candidates/{runtime.id}/reject", json={"reason": "A staging copy."}
    )
    assert rejected.json()["status"] == "rejected"
    # The policy's acceptance, undone by a person: withdrawn from the model.
    undone = await client.post(f"{API}/candidates/{by_policy.id}/reject", json={})
    assert undone.status_code == 200
    facts = {fact.id for fact in await _assertions(workspace)}
    assert facts == {code.id, critical.id}

    # Sent back: proposed again, its analysis run now; one in the model is
    # rejected first.
    sent = await client.post(f"{API}/candidates/{runtime.id}/reprocess")
    assert sent.status_code == 202
    assert sent.json()["candidate"]["status"] == "proposed"
    assert runs[-1]["analyzers"] == ["enrich_runtime"]
    assert (await client.post(f"{API}/candidates/{code.id}/reprocess")).status_code == 409

    # The next run: the decisions stand, the reprocessed one is proposed
    # again — its evidence still holds — and the rejected owner stays so.
    await analyse_workspace(workspace, trigger="model", analyzers=ANALYZERS)
    after = await _candidates(workspace)
    assert after[("enrichment.code", "payment-api")].status == "accepted"
    assert after[("enrichment.runtime", "payment-api")].status == "proposed"
    assert after[("enrichment.owner", "auth-service")].status == "rejected"
    history = [h["status"] for h in after[("enrichment.runtime", "payment-api")].history]
    assert history == ["rejected", "reprocessed"]


async def test_a_candidate_whose_evidence_went_is_withdrawn_and_cannot_be_accepted(
    client: AsyncClient, acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID], builds: Any
) -> None:
    workspace = acme["acme"]
    await analyse_workspace(workspace, trigger="model", analyzers=ANALYZERS)
    code = (await _candidates(workspace))[("enrichment.code", "payment-api")]
    application = (await _candidates(workspace))[("enrichment.application", "checkout-worker")]

    with workspace_scope(workspace):
        async with session_factory() as session:
            for name in ("acme/payments", "checkout"):
                gone = await session.get(Entity, company[name])
                assert gone is not None
                gone.lifecycle = Lifecycle.REMOVED
                gone.removed_at = NOW
            await session.commit()

    # Before any run sees it, accepting says it is gone.
    late = await client.post(f"{API}/candidates/{application.id}/accept", json={})
    assert late.status_code == 409
    assert "no longer" in late.json()["error"]["message"]

    await analyse_workspace(workspace, trigger="model", analyzers=ANALYZERS)
    after = await _candidates(workspace)
    assert after[("enrichment.code", "payment-api")].status == "withdrawn"
    assert [h["status"] for h in after[("enrichment.code", "payment-api")].history] == ["withdrawn"]
    assert code.id == after[("enrichment.code", "payment-api")].id


async def test_an_analysis_that_fails_withdraws_nothing(
    acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID], builds: Any
) -> None:
    workspace = acme["acme"]
    await analyse_workspace(workspace, trigger="model", analyzers=ANALYZERS)

    def broken(material: Material) -> list[Proposal]:
        raise RuntimeError("boom")

    failing = tuple(
        Analyzer(a.name, a.version, a.category, a.method, a.reads, a.summary, broken)
        if a.name == "enrich_code"
        else a
        for a in ANALYZERS
    )
    result = await analyse_workspace(workspace, trigger="request", analyzers=failing)

    assert result["status"] == "partial"
    assert (await _candidates(workspace))[("enrichment.code", "payment-api")].status == "proposed"


async def test_another_workspace_s_candidates_are_no_one_s_here(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    company: dict[str, uuid.UUID],
    builds: Any,
) -> None:
    await analyse_workspace(acme["acme"], trigger="model", analyzers=ANALYZERS)
    code = (await _candidates(acme["acme"]))[("enrichment.code", "payment-api")]

    _as(identity, acme, "other_admin")
    assert (await _get(client, "/candidates"))["data"] == []
    assert (await client.get(f"{API}/candidates/{code.id}")).status_code == 404
    assert (await client.post(f"{API}/candidates/{code.id}/accept", json={})).status_code == 404
    assert (await _get(client, "/summary"))["proposed"] == 0


# ── applied through a real build — and undone ──────────────────────────────


def _proposing(ids: dict[str, uuid.UUID]) -> Analyzer:
    """A test analysis proposing, of the pipeline's company: Billing's
    description; that Sara is a member of payments; that the pull request
    GitHub says merged is closed — an override."""

    def entity(key: str, kind: str) -> Subject:
        return Subject(type="entity", id=ids[key], name=key, kind=kind)

    def run(material: Material) -> list[Proposal]:
        billing, sara, payments = (
            entity(SERVICE, "service"),
            entity(SARA, "person"),
            entity(TEAM, "team"),
        )
        pr = entity(PR, "pull_request")
        return [
            Proposal(
                key="test.description",
                family="semantic",
                code="enrichment.description",
                subject=billing,
                statement="Billing takes card payments.",
                confidence=0.7,
                attribute="description",
                value="Takes card payments",
            ),
            Proposal(
                key="test.member",
                family="organisation",
                code="enrichment.member",
                subject=sara,
                statement="Sara is a member of payments.",
                confidence=0.8,
                relationship="member_of",
                start=sara,
                end=payments,
            ),
            Proposal(
                key="test.state",
                family="semantic",
                code="enrichment.state",
                subject=pr,
                statement="The pull request is closed.",
                confidence=0.6,
                attribute="state",
                value="closed",
                current="merged",
                overrides=True,
            ),
        ]

    return Analyzer(
        name="test_proposing",
        version=1,
        category="enrichment",
        method=Method.RULES,
        reads=frozenset({Reads.MODEL}),
        summary="Proposes for the test.",
        run=run,
    )


async def _decide(
    client: AsyncClient, workspace: uuid.UUID, key: str, action: str, **body: Any
) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            candidate = (
                await session.execute(
                    select(EnrichmentCandidate).where(EnrichmentCandidate.key == key)
                )
            ).scalar_one()
    response = await client.post(f"{API}/candidates/{candidate.id}/{action}", json=body)
    assert response.status_code == 200, response.text


async def _member_of(workspace: uuid.UUID, a: uuid.UUID, b: uuid.UUID) -> Relationship | None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            found = await session.execute(
                select(Relationship).where(
                    Relationship.from_entity_id == a,
                    Relationship.to_entity_id == b,
                    Relationship.type == RelationshipType.MEMBER_OF,
                )
            )
            return found.scalar_one_or_none()


@pytest.fixture
async def pipeline(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID], builds: Any
) -> tuple[uuid.UUID, dict[str, uuid.UUID], Callable[[], Analyzer]]:
    workspace = acme["acme"]
    ids = await _built(workspace)
    await analyse_workspace(workspace, trigger="model", analyzers=(_proposing(ids),))
    _as(identity, acme, "admin")
    return workspace, ids, lambda: _proposing(ids)


async def test_a_validated_fact_is_in_the_model_with_its_decision_and_undone(
    client: AsyncClient,
    pipeline: tuple[uuid.UUID, dict[str, uuid.UUID], Callable[[], Analyzer]],
) -> None:
    workspace, ids, _ = pipeline
    await _decide(client, workspace, "test.description", "accept")
    await _decide(client, workspace, "test.member", "accept")
    await _decide(client, workspace, "test.state", "accept", override=True)

    counts = await build_workspace(workspace)
    assert counts["assertions_applied"] == 2

    model = await _entities(workspace)
    billing = model[SERVICE]
    assert billing.attributes["description"] == "Takes card payments"
    said = billing.provenance["attributes"]["description"]  # type: ignore[index]
    assert (said["origin"], said["rule"], said["decided_via"]) == (
        "accepted",
        "enrichment.test_proposing",
        "person",
    )
    pr = model[PR]
    assert pr.attributes["state"] == "closed"
    assert pr.provenance["attributes"]["state"]["replaced"] == "merged"  # type: ignore[index]
    member = await _member_of(workspace, ids[SARA], ids[TEAM])
    assert member is not None
    assert (member.origin, member.rule) == ("accepted", "enrichment.test_proposing")
    assert member.provenance[0]["decided_via"] == "person"

    # Downstream, as the knowledge API says it.
    knowledge = await client.get(
        "/api/v1/knowledge/relationships", params={"origin": "accepted", "limit": 10}
    )
    assert knowledge.status_code == 200, knowledge.text
    assert [r["type"] for r in knowledge.json()["data"]] == ["member_of"]

    # Rejected: the next build undoes it, and GitHub's word comes back.
    await _decide(client, workspace, "test.member", "reject")
    await _decide(client, workspace, "test.state", "reject")
    await build_workspace(workspace)
    model = await _entities(workspace)
    assert model[PR].attributes["state"] == "merged"
    assert model[PR].provenance["attributes"]["state"] == {"origin": "source"}  # type: ignore[index]
    assert await _member_of(workspace, ids[SARA], ids[TEAM]) is None
    assert model[SERVICE].attributes["description"] == "Takes card payments"


async def test_a_failed_build_changes_nothing_and_the_next_applies_the_fact(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    pipeline: tuple[uuid.UUID, dict[str, uuid.UUID], Callable[[], Analyzer]],
) -> None:
    workspace, ids, _ = pipeline
    await _decide(client, workspace, "test.member", "accept")

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(model_job, "build", broken)
    with pytest.raises(RuntimeError):
        await build_workspace(workspace)
    assert await _member_of(workspace, ids[SARA], ids[TEAM]) is None
    assert len(await _assertions(workspace)) == 1

    # The sweep sees a fact no build applied, and asks for one.
    queued: list[str] = []

    async def capture(job: str, *args: object, **kwargs: object) -> object:
        queued.append(str(args[0]))
        return object()

    monkeypatch.setattr(model_job, "enqueue_job", capture)
    await sweep_models()
    assert str(workspace) in queued

    monkeypatch.setattr(model_job, "build", real_build)
    await build_workspace(workspace)
    assert await _member_of(workspace, ids[SARA], ids[TEAM]) is not None
    # Built: nothing more to build for it.
    queued.clear()
    await sweep_models()
    assert str(workspace) not in queued


# ── written by a model (LEKA-394) ──────────────────────────────────────────


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """LEKA holds a Gemini key; Gemini, scripted, describes each thing from
    its first fact — and cites one more it was never given."""
    asked: list[dict[str, Any]] = []
    configured = settings.model_copy(
        update={
            "google_api_key": SecretStr("g-key"),
            "mistral_api_key": None,
            "anthropic_api_key": None,
            "llm_fallbacks": "",
        }
    )
    monkeypatch.setattr(gateway_service, "settings", configured)

    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        things = json.loads(body["contents"][0]["parts"][0]["text"])["things"]
        asked.append({"names": [t["name"] for t in things]})
        written = {
            "things": [
                {
                    "id": t["id"],
                    "description": f"{t['name']} : rédigé d'après ses faits.",
                    "confidence": 0.95,
                    "uses": [t["facts"][0]["id"], "made-up"],
                }
                for t in things
            ]
        }
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": json.dumps(written)}]}}],
                "usageMetadata": {"promptTokenCount": 2000, "candidatesTokenCount": 400},
                "modelVersion": "gemini-3.8-flash-001",
            },
        )

    monkeypatch.setattr(
        Gateway,
        "_client",
        lambda self, endpoint, tier: httpx.AsyncClient(transport=httpx.MockTransport(answer)),
    )
    return asked


async def test_a_model_describes_what_lacks_a_description_for_a_person_to_validate(
    client: AsyncClient,
    acme: dict[str, uuid.UUID],
    company: dict[str, uuid.UUID],
    builds: list[uuid.UUID],
    gemini: list[dict[str, Any]],
) -> None:
    await analyse_workspace(acme["acme"], trigger="model", analyzers=ANALYZERS)
    found = await _candidates(acme["acme"])
    written = {name: c for (code, name), c in found.items() if code == "enrichment.summary"}
    # Every service and repository without a description, asked once.
    assert set(written) == {
        "payment-api",
        "auth-service",
        "user-service",
        "checkout-worker",
        "cart",
        "acme/payments",
    }
    assert len(gemini) == 1
    pay = written["payment-api"]
    assert (pay.status, pay.method, pay.attribute) == ("proposed", "model", "description")
    assert pay.value == "payment-api : rédigé d'après ses faits."
    # Never sure enough for the policy: a person validates what a model wrote.
    assert pay.confidence == 0.6
    assert pay.decided_via is None
    # What it rests on, what LEKA gave it — never what it made up.
    assert [e["kind"] for e in pay.evidence] == ["fact"]
    assert pay.params["model"] == "gemini-3.8-flash"

    # Rejected by a person: never asked again; the others stand, unasked.
    rejected = await client.post(
        f"{API}/candidates/{written['cart'].id}/reject", json={"reason": "Not what it does."}
    )
    assert rejected.status_code == 200, rejected.text
    await analyse_workspace(acme["acme"], trigger="model", analyzers=ANALYZERS)
    again = await _candidates(acme["acme"])
    assert len(gemini) == 1
    assert again[("enrichment.summary", "cart")].status == "rejected"
    assert again[("enrichment.summary", "payment-api")].status == "proposed"
    assert again[("enrichment.summary", "payment-api")].occurrences == 2
