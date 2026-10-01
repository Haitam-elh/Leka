"""An organisation, modelled from five sources (LEKA-365).

Acme's people and teams, as its tools see them — the connectors' payloads
through the whole pipeline: extraction, parsing, normalisation, stored as
normalisation leaves them, then entity resolution, enrichment and the
company model's build, then the API.

    GitHub          the teams Engineering and Platform — Platform under
                    Engineering, Sara (`sara`) its maintainer, Bob a member;
                    acme/billing-api, and Sara's work there: three commits
                    with her address, a pull request
    PagerDuty       the service Billing API, Payments'; the team Payments —
                    Sara its manager, Bob a responder, by their addresses
    Microsoft 365   the directory: Karim, CTO, in the Leadership department;
                    Sara, head of payments, who reports to Karim, and Nora,
                    who reports to Sara, in Engineering
    an HR system    a custom source: the team Data, under Engineering, Nora
                    its lead
    Datadog         nothing: what the others say is enough

What these protect: one person whatever names them — a login, an address,
a directory's account — with every source kept; teams and their hierarchy;
who reports to whom, up to the top; who owns a service and a repository —
said, or inherited — who leads the owning team, whose work shows they
know it; members read the organisation, never another workspace's.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.connectors import Capability, SourceKind
from leka.db import session_factory, workspace_scope
from leka.ingestion.enrichment.job import enrich_workspace
from leka.ingestion.normalisation import NormalisedRecord
from leka.ingestion.resolution.job import resolve_workspace
from leka.knowledge import Entity
from leka.knowledge.job import build_workspace
from tests.conftest import FakeIdentity
from tests.test_application_landscape import _edge, _entity, _record, _store
from tests.test_enrichment_job import NOW
from tests.test_resolution_job import _source
from tests.test_sources_api import FAKE_KEY, _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/knowledge"
C = Capability
SARA = "person:email:sara@acme.io"
BOB = "person:email:bob@acme.io"
NORA = "person:email:nora@acme.io"
KARIM = "person:email:karim@acme.io"
ENGINEERING = "team:engineering"
PLATFORM = "team:platform"
PAYMENTS = "team:payments"
DATA = "team:data"
REPO = "github.com/acme/billing-api"
BILLING = "service:billing-api"


def _github_team(
    name: str, maintainers: list[str], members: list[str], **extra: Any
) -> NormalisedRecord:
    slug = name.lower()
    return _record(
        SourceKind.GITHUB,
        C.TEAMS,
        {
            "node_id": f"T_{slug}",
            "slug": slug,
            "name": name,
            "html_url": f"https://github.com/orgs/acme/teams/{slug}",
            "maintainers": maintainers,
            "members": members,
            **extra,
        },
        external_id=f"T_{slug}",
        container="acme",
    )


def _commit(sha: str, day: int) -> NormalisedRecord:
    return _record(
        SourceKind.GITHUB,
        C.COMMITS,
        {
            "sha": sha,
            "node_id": f"C_{sha}",
            "html_url": f"https://github.com/acme/billing-api/commit/{sha}",
            "commit": {
                "message": f"Retry the webhook, take {day}",
                "author": {
                    "name": "Sara Martin",
                    "email": "sara@acme.io",
                    "date": f"2026-09-{day:02d}T09:00:00Z",
                },
                "committer": {
                    "name": "Sara Martin",
                    "email": "sara@acme.io",
                    "date": f"2026-09-{day:02d}T09:00:00Z",
                },
            },
            "author": {"login": "sara"},
            "committer": {"login": "sara"},
            "parents": [{"sha": "a"}],
        },
        external_id=f"C_{sha}",
        container="acme/billing-api",
    )


def _directory(
    identifier: str,
    name: str,
    email: str,
    title: str,
    manager: str | None,
    department: str = "Engineering",
) -> NormalisedRecord:
    return _record(
        SourceKind.MICROSOFT_365,
        C.PEOPLE,
        {
            "id": identifier,
            "displayName": name,
            "mail": email,
            "jobTitle": title,
            "department": department,
            "accountEnabled": True,
            **({"manager": {"id": f"m-{manager}", "mail": manager}} if manager else {}),
        },
        external_id=identifier,
        container=None,
    )


async def _organisation(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    """The five sources, normalised, stored, resolved, enriched, built: the
    model's ids, by key."""
    github, pagerduty, microsoft, hr = [
        await _source(workspace, name) for name in ("GitHub", "PagerDuty", "Microsoft 365", "HR")
    ]
    records = [
        (github, _github_team("Engineering", [], [])),
        (
            github,
            _github_team(
                "Platform", ["sara"], ["bob"], parent={"slug": "engineering", "name": "Engineering"}
            ),
        ),
        (
            github,
            _record(
                SourceKind.GITHUB,
                C.REPOSITORIES,
                {"full_name": "acme/billing-api", "owner": {"login": "acme"}, "language": "Python"},
            ),
        ),
        *((github, _commit(f"{n:040x}", n)) for n in (20, 25, 28)),
        (
            pagerduty,
            _record(
                SourceKind.PAGERDUTY,
                C.SERVICES,
                {
                    "id": "PBILL01",
                    "name": "Billing API",
                    "status": "active",
                    "teams": [{"summary": "Payments"}],
                    "escalation_policy": {"summary": "Payments on call"},
                },
            ),
        ),
        (
            pagerduty,
            _record(
                SourceKind.PAGERDUTY,
                C.TEAMS,
                {
                    "id": "PT1",
                    "name": "Payments",
                    "html_url": "https://acme.pagerduty.com/teams/PT1",
                    "members": [
                        {
                            "user": {"id": "PU1", "name": "Sara Martin", "email": "sara@acme.io"},
                            "role": "manager",
                        },
                        {
                            "user": {"id": "PU2", "name": "Bob Lee", "email": "bob@acme.io"},
                            "role": "responder",
                        },
                    ],
                },
                external_id="PT1",
            ),
        ),
        (
            microsoft,
            _directory("u-karim", "Karim Haddad", "karim@acme.io", "CTO", None, "Leadership"),
        ),
        (
            microsoft,
            _directory(
                "u-sara", "Sara Martin", "sara@acme.io", "Head of payments", "karim@acme.io"
            ),
        ),
        (
            microsoft,
            _directory("u-nora", "Nora Diallo", "nora@acme.io", "Data engineer", "sara@acme.io"),
        ),
        (
            hr,
            _record(
                SourceKind.CUSTOM_REST,
                C.RECORDS,
                {
                    "resource": "teams",
                    "entity": "team",
                    "fields": {
                        "id": "t-data",
                        "title": "Data",
                        "metadata": {"parent": "Engineering", "lead": "nora@acme.io"},
                    },
                },
                external_id="teams:t-data",
            ),
        ),
    ]
    for source, record in records:
        await _store(workspace, source, record)
    await resolve_workspace(workspace)
    await enrich_workspace(workspace, now=NOW)
    await build_workspace(workspace)
    with workspace_scope(workspace):
        async with session_factory() as session:
            rows = await session.execute(select(Entity.key, Entity.id))
            return dict(rows.tuples().all())


def _sources(entity: Entity) -> set[str]:
    return {str(s["source_id"]) for s in entity.provenance["sources"]}  # type: ignore[attr-defined]


# ── the model ────────────────────────────────────────────────────────────────


async def test_one_person_whatever_names_them(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _organisation(workspace)

    sara = await _entity(workspace, ids[SARA])
    # Her login, her address on PagerDuty and in the directory: one person.
    assert len(_sources(sara)) == 3
    assert "person:github.com:sara" not in ids
    a = sara.attributes
    assert (a["job_title"], a["department"], a["active"]) == (
        "Head of payments",
        "Engineering",
        True,
    )


async def test_teams_their_hierarchy_members_and_leads(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _organisation(workspace)

    for a, kind, b in (
        (PLATFORM, "child_of", ENGINEERING),
        (DATA, "child_of", ENGINEERING),
        (SARA, "member_of", PLATFORM),
        (BOB, "member_of", PAYMENTS),
        (PLATFORM, "led_by", SARA),
        (PAYMENTS, "led_by", SARA),
        (DATA, "led_by", NORA),
        (NORA, "member_of", ENGINEERING),  # the directory's department
    ):
        edge = await _edge(workspace, ids[a], kind, ids[b])
        assert edge.origin == "stated", (a, kind, b)
    # The GitHub team and the directory's department are one Engineering.
    engineering = await _entity(workspace, ids[ENGINEERING])
    assert len(_sources(engineering)) >= 2


async def test_who_reports_to_whom_up_to_the_top(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _organisation(workspace)

    await _edge(workspace, ids[NORA], "reports_to", ids[SARA])
    await _edge(workspace, ids[SARA], "reports_to", ids[KARIM])


async def test_who_owns_said_or_inherited(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _organisation(workspace)

    said = await _edge(workspace, ids[BILLING], "owned_by", ids[PAYMENTS])
    assert said.origin == "stated"
    # The repository of Billing API's name is Payments' too, inherited.
    inherited = await _edge(workspace, ids[REPO], "owned_by", ids[PAYMENTS])
    assert (inherited.origin, inherited.rule) == ("inferred", "inherited")


async def test_expertise_is_sourced_from_the_work(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _organisation(workspace)

    edge = await _edge(workspace, ids[SARA], "contributes_to", ids[REPO])
    assert (edge.origin, edge.rule) == ("inferred", "work")
    sara = await _entity(workspace, ids[SARA])
    expertise = sara.attributes["expertise"]
    assert isinstance(expertise, list)
    shown = expertise[0]
    # She wrote them and committed them: both said.
    assert (shown["key"], shown["items"], shown["roles"]) == (
        REPO,
        3,
        {"authored": 3, "committed": 3},
    )
    assert sara.attributes["languages"] == ["python"]
    assert sara.provenance["attributes"]["expertise"]["rule"] == "work"  # type: ignore[index]


# ── the API ──────────────────────────────────────────────────────────────────


async def test_members_read_the_teams(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _organisation(acme["acme"])
    _as(identity, acme, "member")

    listed = {
        row["key"]: row
        for row in (await client.get(f"{API}/teams", params={"limit": 100})).json()["data"]
    }
    payments = listed[PAYMENTS]
    assert (payments["member_count"], [lead["key"] for lead in payments["leads"]]) == (2, [SARA])
    assert payments["owns"].get("service") == 1
    assert listed[PLATFORM]["parent"]["key"] == ENGINEERING
    assert listed[ENGINEERING]["sub_team_count"] == 2

    engineering = (await client.get(f"{API}/teams/{ids[ENGINEERING]}")).json()
    assert [t["key"] for t in engineering["sub_teams"]] == [DATA, PLATFORM]
    assert {m["entity"]["key"] for m in engineering["members"]} >= {SARA, NORA}
    platform = (await client.get(f"{API}/teams/{ids[PLATFORM]}")).json()
    assert [a["key"] for a in platform["ancestors"]] == [ENGINEERING]
    owned = (await client.get(f"{API}/teams/{ids[PAYMENTS]}")).json()["owned"]
    assert [(o["entity"]["key"], o["origin"]) for o in owned][:1] == [(BILLING, "stated")]
    assert (REPO, "inferred") in [(o["entity"]["key"], o["origin"]) for o in owned]
    # Engineering is a GitHub team too, and says so; Leadership, the
    # directory's alone, is a department.
    departments = await client.get(f"{API}/teams", params={"team_type": "department"})
    assert [row["key"] for row in departments.json()["data"]] == ["team:leadership"]
    wrong = await client.get(f"{API}/teams/{ids[SARA]}")
    assert wrong.status_code == 404


async def test_members_read_the_people(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _organisation(acme["acme"])
    _as(identity, acme, "member")

    async def keys(**params: str | int) -> set[str]:
        response = await client.get(f"{API}/people", params={"limit": 100, **params})
        assert response.status_code == 200, response.text
        return {row["key"] for row in response.json()["data"]}

    rows = {
        row["key"]: row
        for row in (await client.get(f"{API}/people", params={"limit": 100})).json()["data"]
    }
    sara = rows[SARA]
    assert (sara["email"], sara["job_title"], sara["manager"]["key"]) == (
        "sara@acme.io",
        "Head of payments",
        KARIM,
    )
    assert sara["report_count"] == 1
    assert {t["key"] for t in sara["teams"]} == {ENGINEERING, PLATFORM, PAYMENTS}
    assert [e["key"] for e in sara["expertise"]][:1] == [REPO]
    assert await keys(team_id=str(ids[PAYMENTS])) == {SARA, BOB}
    assert await keys(contributors="true") == {SARA}
    assert await keys(q="nora@") == {NORA}

    nora = (await client.get(f"{API}/people/{ids[NORA]}")).json()
    assert [m["key"] for m in nora["managers"]] == [SARA, KARIM]
    sara_detail = (await client.get(f"{API}/people/{ids[SARA]}")).json()
    assert [r["key"] for r in sara_detail["reports"]] == [NORA]
    assert {c["entity"]["key"] for c in sara_detail["contributions"]} >= {REPO}
    assert sara_detail["all_expertise"][0]["roles"] == {"authored": 3, "committed": 3}


async def test_who_is_responsible_for_a_service_and_a_repository(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _organisation(acme["acme"])
    _as(identity, acme, "member")

    service = (await client.get(f"{API}/entities/{ids[BILLING]}/responsibility")).json()
    assert [(o["entity"]["key"], o["origin"]) for o in service["owners"]] == [(PAYMENTS, "stated")]
    assert [lead["key"] for lead in service["leads"]] == [SARA]
    assert service["escalation_policy"] == "Payments on call"
    assert SARA in [e["entity"]["key"] for e in service["experts"]]
    repository = (await client.get(f"{API}/entities/{ids[REPO]}/responsibility")).json()
    [owner] = repository["owners"]
    assert (owner["entity"]["key"], owner["rule"]) == (PAYMENTS, "inherited")


async def test_another_workspace_s_organisation_is_not_found(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _organisation(acme["acme"])
    _as(identity, acme, "other_admin")  # Globex's

    for path in (
        f"/teams/{ids[PAYMENTS]}",
        f"/people/{ids[SARA]}",
        f"/entities/{ids[BILLING]}/responsibility",
    ):
        assert (await client.get(f"{API}{path}")).status_code == 404, path
    assert (await client.get(f"{API}/teams")).json()["data"] == []
    assert (await client.get(f"{API}/people")).json()["data"] == []
