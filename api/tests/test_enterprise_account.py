"""An Enterprise account (2026-10-25): an organisation made from the server's
shell, its account, its plan, its dedicated agents — and what an
Enterprise organisation runs its own: who may reach its sources, how much
its agents ran, who ran which.

What these protect:
- `provision` makes the account — its first password hashed, never said —,
  the organisation and its owner, the plan Enterprise with the contract's
  AI capacity, its dedicated agents, its contract; run again it changes
  nothing and makes nothing twice. An account that exists is seated as it
  is, no password asked; an unknown agent, a short password, no password
  for a new account: refused, said why. An agent is taken back on asking.
- No organisation's name is LEKA's: the same command makes a second one.
- Its own instructions — its architect's prompt — given from a file or the
  standard input, said by their length only, run in place of the
  registry's; taken back, the registry's again. Without an agent, or a file
  that is not there: refused.
- On Enterprise, members and sources have no limit.
- A source's credentials are revoked by who manages sources: erased, the
  source disabled, its data kept, said in its history and the audit trail;
  a member may not.
- Each agent's use is counted — runs, succeeded, failed, the latest — never
  priced; the journal says who ran which agent, held to which sources, on
  what, when, how it ended; both for who may read the audit trail only.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import io
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from leka.billing.limits import limit_of
from leka.capabilities import AgentRun, DedicatedAgent
from leka.capabilities.dedicated import instructions_of, own_definition
from leka.capabilities.definition import Definition
from leka.capabilities.registry import find
from leka.connectors import SourceCredential, SourceEvent
from leka.core.security import verify_password
from leka.db import session_factory, system_scope, workspace_scope
from leka.governance.models import AuditEvent, WorkspacePlan
from leka.governance.plans import plan_of
from leka.identity.models import User
from leka.ops import enterprise
from leka.ops.enterprise import ProvisioningError, provision
from leka.platform import Membership, Workspace
from tests.conftest import FakeIdentity
from tests.test_sources_api import _as, _create, acme, fake_connector  # noqa: F401

pytestmark = pytest.mark.integration

PASSWORD = "un-mot-de-passe-de-test"


@pytest.fixture
async def organisations() -> AsyncIterator[list[str]]:
    """The names provisioned here — their workspaces and accounts removed
    after."""
    made: list[str] = []
    yield made
    with system_scope():
        async with session_factory() as session:
            for name in made:
                await session.execute(text("DELETE FROM workspaces WHERE name = :n"), {"n": name})
            await session.execute(text("DELETE FROM users WHERE email LIKE '%@client.example'"))
            await session.commit()


def _name(organisations: list[str], label: str) -> str:
    name = f"{label} {uuid.uuid4().hex[:6]}"
    organisations.append(name)
    return name


async def test_an_organisation_is_provisioned_once_and_run_again_unchanged(
    organisations: list[str],
) -> None:
    name = _name(organisations, "Client Alpha")
    email = f"admin-{uuid.uuid4().hex[:6]}@client.example"
    done = await provision(
        email.upper(),
        name,
        password=PASSWORD,
        agents=["application-architecture"],
        first_name="Ada",
        last_name="Admin",
        monthly_credits=250_000,
        contact_name="Équipe LEKA",
        contact_email="contact@leka.example",
    )
    assert (done.organisation, done.email, done.account, done.role, done.plan) == (
        name,
        email,
        "créé",
        "owner",
        "enterprise",
    )
    assert done.agents == ["application-architecture"]
    assert done.contract["type"] == "Entreprise"
    assert done.contract["contact"] == {"name": "Équipe LEKA", "email": "contact@leka.example"}
    assert {"compte créé", "organisation créée", "plan Entreprise", "contrat créé"} <= set(
        done.changed
    )
    workspace_id = uuid.UUID(done.workspace_id)
    with system_scope():
        async with session_factory() as session:
            user = await session.scalar(select(User).where(User.email == email))
            assert user is not None and user.is_verified and user.language == "fr"
            # Its password hashed, never kept as it was given.
            assert user.password_hash and PASSWORD not in user.password_hash
            assert verify_password(PASSWORD, user.password_hash)
            seat = await session.scalar(
                select(Membership).where(
                    Membership.workspace_id == workspace_id, Membership.user_id == user.id
                )
            )
            assert seat is not None and seat.role.value == "owner"
            workspace = await session.get(Workspace, workspace_id)
            assert workspace is not None and not workspace.demo
            with workspace_scope(workspace_id):
                plan = await plan_of(session, workspace_id)
                assert (plan.name, plan.monthly_credits) == ("enterprise", 250_000)
                # Enterprise: members and sources without a limit.
                assert await limit_of(session, workspace_id, "users") is None
                assert await limit_of(session, workspace_id, "sources") is None

    # Again, the same: nothing changed, nothing made twice — no password asked.
    again = await provision(
        email, name, agents=["application-architecture"], monthly_credits=250_000
    )
    assert (again.workspace_id, again.account, again.changed) == (
        done.workspace_id,
        "existant",
        [],
    )
    with system_scope():
        async with session_factory() as session:
            counted = {
                table.__name__: await session.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(table.workspace_id == workspace_id)
                )
                for table in (WorkspacePlan, DedicatedAgent, Membership)
            }
            assert counted == {"WorkspacePlan": 1, "DedicatedAgent": 1, "Membership": 1}
            provisioned = (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.workspace_id == workspace_id,
                        AuditEvent.action == "workspace.enterprise_provisioned",
                    )
                )
            ).all()
            assert len(provisioned) == 1
            assert PASSWORD not in json.dumps(provisioned[0].detail)

    # Its agent taken back on asking; the contact kept when not said.
    back = await provision(email, name, remove=["application-architecture"])
    assert back.agents == [] and back.changed == ["agent dédié retiré application-architecture"]
    assert back.contract["contact"] == {"name": "Équipe LEKA", "email": "contact@leka.example"}


async def test_a_second_organisation_is_the_same_command(organisations: list[str]) -> None:
    first = await provision(
        f"a-{uuid.uuid4().hex[:6]}@client.example",
        _name(organisations, "Client Un"),
        password=PASSWORD,
        agents=["application-architecture"],
    )
    second = await provision(
        f"b-{uuid.uuid4().hex[:6]}@client.example",
        _name(organisations, "Client Deux"),
        password=PASSWORD,
    )
    assert first.workspace_id != second.workspace_id
    assert (first.agents, second.agents) == (["application-architecture"], [])


async def test_an_existing_account_is_seated_and_what_cannot_be_is_said(
    organisations: list[str], acme: dict[str, uuid.UUID]
) -> None:
    with system_scope():
        async with session_factory() as session:
            member = await session.get(User, acme["member"])
            admin = await session.get(User, acme["admin"])
            assert member is not None and admin is not None
            emails = (member.email, admin.email)
    name = _name(organisations, "Client Existant")
    done = await provision(emails[0], name)
    assert (done.account, done.role) == ("existant", "owner")
    assert "organisation créée" in done.changed
    # A second account of the same organisation: seated in it, as owner.
    other = await provision(emails[1], name)
    assert (other.workspace_id, other.account) == (done.workspace_id, "existant")
    assert "compte rattaché, propriétaire" in other.changed

    name = _name(organisations, "Client Refusé")
    for asked, said in (
        ({"email": "nouveau@client.example"}, "mot de passe est demandé"),
        ({"email": "court@client.example", "password": "court"}, "caractères"),
        ({"email": "x@client.example", "password": PASSWORD, "agents": ["inconnu"]}, "inconnu"),
        ({"email": "pas-une-adresse", "password": PASSWORD}, "adresse e-mail"),
    ):
        with pytest.raises(ProvisioningError, match=said):
            await provision(organisation=name, **asked)


async def test_the_command_reads_the_password_hidden_and_never_prints_it(
    organisations: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(enterprise.PASSWORD_ENV, PASSWORD)
    name = _name(organisations, "Client Commande")
    email = f"cli-{uuid.uuid4().hex[:6]}@client.example"
    code = await enterprise.main(
        [
            "provision",
            "--email",
            email,
            "--organisation",
            name,
            "--agent",
            "application-architecture",
        ],
        interactive=False,
    )
    assert code == 0
    printed = capsys.readouterr().out
    said = json.loads(printed)
    assert (said["email"], said["agents"]) == (email, ["application-architecture"])
    assert PASSWORD not in printed
    assert await enterprise.main(["show", "--organisation", name], interactive=False) == 0
    shown = json.loads(capsys.readouterr().out)
    assert (shown["plan"], shown["agents"]) == ("enterprise", ["application-architecture"])
    # Refused: said, a code an operator's script can read.
    monkeypatch.delenv(enterprise.PASSWORD_ENV)
    refused = await enterprise.main(
        ["provision", "--email", "autre@client.example", "--organisation", name],
        interactive=False,
    )
    assert refused == 1 and "Refusé" in capsys.readouterr().out


async def test_a_source_s_credentials_are_revoked_its_data_kept(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    fake_connector: None,
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client)
    url = f"/api/v1/sources/{source['id']}"
    _as(identity, acme, "member")
    assert (await client.post(f"{url}/revoke")).status_code == 403
    _as(identity, acme, "admin")
    revoked = await client.post(f"{url}/revoke")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "disabled"
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            source_id = uuid.UUID(source["id"])
            kept = await session.scalar(
                select(SourceCredential).where(SourceCredential.source_id == source_id)
            )
            assert kept is None
            events = (
                await session.scalars(
                    select(SourceEvent.type).where(SourceEvent.source_id == source_id)
                )
            ).all()
            assert "credentials_revoked" in [str(e) for e in events]
            audited = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.workspace_id == acme["acme"],
                    AuditEvent.action == "source.credentials_revoked",
                )
            )
            assert audited is not None and audited.target_id == source["id"]
    # The source is still there, its data with it: new credentials bring it back.
    assert (await client.get(url)).status_code == 200


async def _runs(workspace: uuid.UUID, by: uuid.UUID, source: uuid.UUID) -> None:
    now = datetime.now(UTC)
    with workspace_scope(workspace):
        async with session_factory() as session:
            for key, status, ago, detail, inputs in (
                ("code-review", "succeeded", 1, {}, {"depot": "acme/payments"}),
                ("code-review", "failed", 2, {}, {}),
                ("security-review", "succeeded", 3, {"sources": [str(source)]}, {}),
                ("code-review", "succeeded", 60, {}, {}),
            ):
                session.add(
                    AgentRun(
                        workspace_id=workspace,
                        key=key,
                        version="1.0.0",
                        status=status,
                        inputs=inputs,
                        requested_by=by,
                        format="markdown",
                        detail=detail,
                        queued_at=now - timedelta(days=ago),
                        finished_at=now - timedelta(days=ago),
                    )
                )
            await session.commit()


async def test_each_agent_s_use_is_counted_never_priced_and_its_runs_journaled(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    fake_connector: None,
) -> None:
    _as(identity, acme, "admin")
    source = await _create(client, display_name="Slack de l'équipe")
    await _runs(acme["acme"], acme["admin"], uuid.UUID(source["id"]))
    _as(identity, acme, "member")
    assert (await client.get("/api/v1/agent-runs/usage")).status_code == 403
    assert (await client.get("/api/v1/agent-runs/journal")).status_code == 403
    _as(identity, acme, "admin")
    usage = (await client.get("/api/v1/agent-runs/usage")).json()
    by_key = {u["key"]: u for u in usage}
    # The last 30 days: the run of 60 days ago is not counted.
    assert (by_key["code-review"]["runs"], by_key["code-review"]["succeeded"]) == (2, 1)
    assert by_key["code-review"]["failed"] == 1
    assert by_key["security-review"]["runs"] == 1
    assert usage[0]["key"] == "code-review" and by_key["code-review"]["title"] == "Revue de code"
    assert not any(k in json.dumps(usage) for k in ("price", "credit", "€", "cost"))
    longer = (await client.get("/api/v1/agent-runs/usage", params={"days": 90})).json()
    assert {u["key"]: u["runs"] for u in longer}["code-review"] == 3

    journal = (await client.get("/api/v1/agent-runs/journal", params={"limit": 10})).json()
    assert [j["key"] for j in journal] == [
        "code-review",
        "code-review",
        "security-review",
        "code-review",
    ]
    first, _, held, _ = journal
    assert (first["status"], first["scope"], first["sources"]) == (
        "succeeded",
        "acme/payments",
        [],
    )
    assert first["by"] == str(acme["admin"]) and first["by_name"]
    assert held["sources"] == ["Slack de l'équipe"] and held["title"] == "Revue de sécurité"
    # Before a moment: the older ones only.
    older = (
        await client.get("/api/v1/agent-runs/journal", params={"before": journal[1]["queued_at"]})
    ).json()
    assert [j["key"] for j in older] == ["security-review", "code-review"]
    # Another workspace's runs are not its.
    _as(identity, acme, "other_admin")
    assert (await client.get("/api/v1/agent-runs/journal")).json() == []


# An organisation's own instructions, as LEKA is given them — never a real one
# in the code (2026-10-25).
OWN = "PROMPT SYSTÈME — AGENT « ARCHITECTE APPLICATIF » — consignes du client\nPRINCIPE ABSOLU."


async def test_its_own_instructions_given_never_printed_and_taken_back(
    organisations: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(enterprise.PASSWORD_ENV, PASSWORD)
    name = _name(organisations, "Client Consignes")
    email = f"own-{uuid.uuid4().hex[:6]}@client.example"
    told = tmp_path / "consignes.md"
    told.write_text(OWN, encoding="utf-8")
    asked = ["provision", "--email", email, "--organisation", name]
    architect = ["--agent", "application-architecture"]
    assert (
        await enterprise.main([*asked, *architect, "--instructions", str(told)], interactive=False)
        == 0
    )
    printed = capsys.readouterr().out
    said = json.loads(printed)
    assert said["instructions"] == {"application-architecture": len(OWN)}
    assert "consignes de application-architecture" in said["changed"]
    assert "PRINCIPE" not in printed  # their length, never their words
    workspace = uuid.UUID(said["workspace_id"])
    with workspace_scope(workspace):
        async with session_factory() as session:
            kept = await instructions_of(session, workspace, "application-architecture")
            ran = await own_definition(session, workspace, find_agent("application-architecture"))
    assert kept == OWN and ran.instructions == OWN
    # The same, again: nothing changed. From the standard input: the same.
    monkeypatch.setattr("sys.stdin", io.StringIO(OWN))
    assert (
        await enterprise.main([*asked, *architect, "--instructions", "-"], interactive=False) == 0
    )
    assert (
        "consignes de application-architecture"
        not in json.loads(capsys.readouterr().out)["changed"]
    )
    # Given without an agent, empty, or a file that is not there: refused, said.
    for wrong in (
        ["--instructions", str(told)],
        [*architect, "--instructions", str(tmp_path / "nope.md")],
    ):
        assert await enterprise.main([*asked, *wrong], interactive=False) == 1
        assert "Refusé" in capsys.readouterr().out
    # Taken back: the registry's again.
    assert (
        await enterprise.main([*asked, *architect, "--clear-instructions"], interactive=False) == 0
    )
    assert json.loads(capsys.readouterr().out)["instructions"] == {}
    with workspace_scope(workspace):
        async with session_factory() as session:
            ran = await own_definition(session, workspace, find_agent("application-architecture"))
    assert ran.instructions == find_agent("application-architecture").instructions


def find_agent(key: str) -> Definition:
    found = find(key)
    assert found is not None
    return found
