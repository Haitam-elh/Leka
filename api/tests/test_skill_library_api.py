"""The skill library (LEKA-401), end to end — on Acme's operations, its
infrastructure, its data and its documentation as their tools see them,
each through the whole pipeline (test_operations_landscape and the others):
over HTTP, from an agent, in a workflow.

What these protect:
- Each skill gives what the company model holds, judged: deployments and
  the incident that followed one (a change failure rate of 1), the change
  that caused an incident, what a failure of Billing API reaches up to the
  business, what to test, the public load balancer no one owns, the
  credentials table, the undocumented processes.
- A skill that needs a source not connected is refused, said which — and
  runs once it is.
- An agent calls the skills it names, each call checked and kept about its
  run; a workflow composes skills, branches on what they concluded, and
  hands on to an agent only when something sounds an alarm.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from httpx import AsyncClient

from leka.capabilities import execute_workflow, sync_catalogue
from leka.capabilities import skills as skills_module
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import (
    Script,
    _detail,
    _run,
    gemini,
    leka_gemini,  # noqa: F401 — a fixture
    queued,  # noqa: F401 — a fixture
)
from tests.test_capabilities_api import _connect
from tests.test_data_landscape import CREDENTIALS, DATABASE
from tests.test_data_landscape import _landscape as _data
from tests.test_documentation_landscape import _knowledge
from tests.test_enrichment_job import NOW
from tests.test_infrastructure_landscape import _landscape as _infrastructure
from tests.test_operations_landscape import (
    BILLING,
    CHANGE,
    CHECKOUT,
    INVOICING,
    JIRA_INCIDENT,
    PLATFORM,
    RELEASE,
    REPO,
    _operations,
)
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures
from tests.test_workflow_runs_api import workflows_queued  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

API = "/api/v1"


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Now, as the fixtures' sources were read: their periods hold."""
    monkeypatch.setattr(skills_module, "clock", lambda: NOW)
    yield


async def _skill(client: AsyncClient, key: str, code: int = 200, **inputs: Any) -> Any:
    response = await client.post(f"{API}/skills/{key}/run", json={"inputs": inputs})
    assert response.status_code == code, response.text
    return response.json()


def _codes(ran: Any) -> dict[str, str]:
    return {s["code"]: s["level"] for s in ran["output"]["signals"]}


def _names(things: list[dict[str, Any]]) -> list[str]:
    return [t["name"] for t in things]


async def test_operations_read_by_the_library(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ops = await _operations(acme["acme"])
    _as(identity, acme, "member")
    billing = f"entity:{ops[BILLING]}"
    # The repository's profile needs a code host connected.
    refused = await _skill(client, "repository-profile", 422, id=str(ops[REPO]))
    assert refused["error"]["details"] == [
        {"field": "sources", "message": "one of github, gitlab, bitbucket"}
    ]
    listed = {s["key"]: s for s in (await client.get(f"{API}/skills")).json()}
    assert listed["repository-profile"]["missing_sources"] == [["github", "gitlab", "bitbucket"]]
    assert listed["repository-profile"]["usable"] is False
    await _connect(acme, "github")

    profile = (await _skill(client, "repository-profile", id=str(ops[REPO]), days=30))["output"]
    assert profile["of"] == "acme/billing-api"
    assert _names(profile["builds"]) == ["Billing API"]
    assert profile["maintainers"] == ["sara"]
    assert profile["activity"]["deployments"] == 2

    # Delivery: one deployment to production, an incident followed it.
    delivery = await _skill(client, "delivery-metrics", id=billing)
    said = delivery["output"]
    assert (said["deployments"], said["followed_by_incident"]) == (1, 1)
    assert (said["change_failure_rate"], said["mttr_minutes"]) == (1.0, 60)
    assert said["tiers"] == {"frequency": "low", "failure_rate": "low", "recovery": "high"}
    assert _names(said["latest"]) == ["v1.4.0 to production"]
    assert _codes(delivery) == {"delivery.high_failure_rate": "critical"}
    everywhere = (await _skill(client, "delivery-metrics", environment=None))["output"]
    assert (everywhere["deployments"], everywhere["change_failure_rate"]) == (2, 0.5)

    history = (await _skill(client, "incident-history", id=billing, days=30))["output"]
    assert (history["total"], history["by_severity"], history["mttr_minutes"]) == (
        1,
        {"high": 1},
        60,
    )
    assert _names(history["latest"]) == ["Invoices fail to send"]

    # A change request its source says caused an incident.
    change = await _skill(client, "change-review", id=str(ops[CHANGE]))
    [caused] = change["output"]["incidents_after"]
    assert (caused["id"], caused["how"]) == (f"event:{ops[JIRA_INCIDENT]}", "caused")
    assert _codes(change) == {"change.followed_by_incident": "critical"}
    # A deployment: what it touched, how far it reaches, what followed.
    deployed = await _skill(client, "change-review", id=str(ops[RELEASE]))
    review = deployed["output"]
    assert (review["kind"], review["environment"], review["by"]) == (
        "deployment",
        "production",
        "sara",
    )
    assert _names(review["touches"]) == ["Billing API"]
    assert _names(review["reach"]["dependents"]) == ["Checkout"]
    assert _names(review["reach"]["applications"]) == ["Billing platform"]
    assert _names(review["reach"]["business"]) == ["Invoicing"]
    assert set(_codes(deployed)) == {
        "change.followed_by_incident",
        "change.wide_reach",
        "change.production",
    }

    radius = await _skill(client, "blast-radius", id=billing)
    assert [t["id"] for t in radius["output"]["direct"]] == [f"entity:{ops[CHECKOUT]}"]
    assert [a["id"] for a in radius["output"]["applications"]] == [f"entity:{ops[PLATFORM]}"]
    assert [b["id"] for b in radius["output"]["business"]] == [f"entity:{ops[INVOICING]}"]
    assert _codes(radius) == {
        "architecture.business_critical": "warning",
        "architecture.unowned": "warning",
    }
    scope = (await _skill(client, "test-scope", id=billing))["output"]
    assert [(t["name"], t["steps"]) for t in scope["to_test"]] == [("Checkout", 1)]
    assert scope["total"] == 1

    # Every run kept, the workspace's, for whom.
    runs = (await client.get(f"{API}/skills/runs", params={"limit": 50})).json()
    assert len(runs) == 9
    assert {(r["caller"], r["mine"]) for r in runs} == {("api", True)}
    assert (runs[-1]["key"], runs[-1]["status"], runs[-1]["reason"]) == (
        "repository-profile",
        "refused",
        "unavailable",
    )


async def test_the_estate_read_by_the_library(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    await _infrastructure(acme["acme"])
    _as(identity, acme, "member")
    await _skill(client, "infrastructure-inventory", 422)
    await _connect(acme, "aws")
    inventory = await _skill(client, "infrastructure-inventory")
    said = inventory["output"]
    assert said["total"] == 12
    assert said["by_state"]["terminated"] == 1
    assert (said["public"], said["by_provider"]["aws"]) == (1, 9)
    assert _codes(inventory) == {
        "infra.unowned": "warning",
        "infra.not_running": "info",
        "infra.public": "info",
    }
    posture = await _skill(client, "security-posture")
    [exposed] = posture["output"]["public_resources"]
    assert (exposed["name"], exposed["kind"], exposed["owned"]) == ("web", "load_balancer", False)
    assert _codes(posture) == {
        "security.unowned_exposed": "critical",
        "security.public_resources": "warning",
    }


async def test_the_data_read_by_the_library(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    data = await _data(acme["acme"])
    _as(identity, acme, "member")
    await _connect(acme, "postgresql")
    ledger = await _skill(client, "data-landscape", id=str(data[DATABASE]))
    [store] = ledger["output"]["databases"]
    assert (store["name"], store["engine"], store["classification"]) == (
        "ledger",
        "postgresql",
        "restricted",
    )
    assert {"credential", "contact"} <= set(store["categories"])
    sensitive = {o["id"]: o for o in ledger["output"]["sensitive_objects"]}
    assert sensitive[f"entity:{data[CREDENTIALS]}"]["categories"] == ["credential"]
    assert _codes(ledger) == {
        "data.secrets": "warning",
        "data.personal": "info",
        "data.unowned": "warning",
    }
    everywhere = (await _skill(client, "data-landscape"))["output"]
    assert {"ledger", "shop.acme.io"} <= set(_names(everywhere["databases"]))
    posture = await _skill(client, "security-posture")
    assert set(_codes(posture)) == {"security.secrets_stored", "security.personal_data"}


async def test_the_documentation_read_by_the_library(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    await _knowledge(acme["acme"])
    _as(identity, acme, "member")
    await _skill(client, "documentation-coverage", 422)
    await _connect(acme, "confluence")
    coverage = await _skill(client, "documentation-coverage")
    said = coverage["output"]
    assert (said["documents"], said["spaces"]) == (3, 1)
    kinds = {k["type"]: k["percent"] for k in said["coverage"]}
    assert (kinds["service"], kinds["application"], kinds["repository"]) == (100, 100, 0)
    assert {"acme/billing-api", "Order to cash"} <= set(_names(said["undocumented"]))
    assert set(_codes(coverage)) == {"docs.low_coverage", "docs.gaps"}
    only = (await _skill(client, "documentation-coverage", kind="repository"))["output"]
    assert _names(only["undocumented"]) == ["acme/billing-api"]


# ── from an agent, in a workflow ─────────────────────────────────────────────


def _answered(script: Script, asked: int) -> Any:
    part = script.asked[asked]["contents"][-1]["parts"][0]["functionResponse"]
    return json.loads(part["response"]["result"])


async def test_an_agent_calls_the_skills_it_names(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    ops = await _operations(acme["acme"])
    _as(identity, acme, "member")
    await sync_catalogue()
    billing = str(ops[BILLING])
    report = f"# Post-mortem — Billing API\n\nUn incident en 30 jours [{billing}]."
    script = leka_gemini(
        gemini(call={"name": "incident-history", "args": {"id": billing, "days": 30}}),
        gemini(call={"name": "blast-radius", "args": {"id": billing}}),
        gemini(report),
    )
    started = await client.post(
        f"{API}/agent-runs",
        json={"key": "incident-investigation", "inputs": {"incident": "Billing API"}},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    assert await _run(acme, run_id) == {"status": "succeeded"}
    # Offered the skills it names, beside its tools.
    assert script.declared()[-2:] == ["incident-history", "blast-radius"]
    assert _answered(script, 1)["total"] == 1
    assert _names(_answered(script, 2)["direct"]) == ["Checkout"]
    done = await _detail(client, run_id)
    assert [
        (e["detail"]["name"], e["detail"]["outcome"]) for e in done["events"] if e["kind"] == "tool"
    ] == [("incident-history", "ok"), ("blast-radius", "ok")]
    kept = (await client.get(f"{API}/skills/runs", params={"ref": f"agent_run:{run_id}"})).json()
    assert {(r["key"], r["caller"], r["status"]) for r in kept} == {
        ("incident-history", "agent:incident-investigation", "succeeded"),
        ("blast-radius", "agent:incident-investigation", "succeeded"),
    }


async def test_a_workflow_composes_skills_and_hands_on_when_one_alarms(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    ops = await _operations(acme["acme"])
    _as(identity, acme, "member")
    await _connect(acme, "github")
    await sync_catalogue()
    billing = str(ops[BILLING])
    leka_gemini(
        gemini(call={"name": "delivery-metrics", "args": {"id": billing}}),
        gemini("# Release de Billing API\n\nUn déploiement sur un a été suivi d'un incident."),
    )
    started = await client.post(
        f"{API}/workflow-runs", json={"key": "release-readiness", "inputs": {"service": billing}}
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    assert (await execute_workflow(acme["acme"], uuid.UUID(run_id)))["status"] == "succeeded"
    detail = (await client.get(f"{API}/workflow-runs/{run_id}")).json()
    steps = {s["step"]: s for s in detail["steps"]}
    assert {k: s["status"] for k, s in steps.items()} == {
        "delivery": "succeeded",
        "incidents": "succeeded",
        "reach": "succeeded",
        # Delivery sounded the alarm: the release analysed by its agent.
        "review": "succeeded",
    }
    assert steps["delivery"]["output"]["codes"] == ["delivery.high_failure_rate"]
    assert steps["delivery"]["output"]["change_failure_rate"] == 1.0
    assert steps["delivery"]["output"]["ref"].startswith("skill_run:")
    assert "architecture.business_critical" in steps["reach"]["output"]["codes"]
    assert steps["review"]["output"]["text"].startswith("# Release de Billing API")
    kept = (await client.get(f"{API}/skills/runs", params={"ref": f"workflow_run:{run_id}"})).json()
    assert sorted((r["key"], r["caller"]) for r in kept) == [
        ("blast-radius", "workflow:release-readiness"),
        ("delivery-metrics", "workflow:release-readiness"),
        ("incident-history", "workflow:release-readiness"),
    ]
