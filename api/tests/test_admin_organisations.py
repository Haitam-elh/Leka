"""The organisations module of LEKA ADMIN (LEKA-549): every organisation found
by its country, size and activity; what LEKA's team keeps about one changed
with a reason and said in both trails; internal notes the customer never
sees; what the team did to it; the alerts on its environment. Each action
behind its own permission.
"""

# ruff: noqa: F811 — the admin world's fixtures are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text

from leka.admin import ROLE_PERMISSIONS, AdminAuditEvent, AdminNote, AdminPermission, AdminRole
from leka.db import session_factory, system_scope
from leka.governance import AuditEvent
from leka.identity import CompanySize
from leka.monitoring import MonitoringAlert
from leka.platform import ORGANISATION_SIZES, Workspace
from tests.test_admin_api import API, SUPER, World, as_, world  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


def test_the_sizes_are_the_sign_up_forms_brackets() -> None:
    assert tuple(size.value for size in CompanySize) == ORGANISATION_SIZES


def test_every_role_may_write_a_note_only_the_operations_change_an_organisation() -> None:
    for role in AdminRole:
        assert AdminPermission.ORGANISATIONS_NOTES in ROLE_PERMISSIONS[role]
    writers = {r for r in AdminRole if AdminPermission.ORGANISATIONS_WRITE in ROLE_PERMISSIONS[r]}
    assert writers == {AdminRole.SUPER_ADMIN, AdminRole.OPERATIONS}


async def _keep(world: World, *, country: str, size: str) -> None:
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text("UPDATE workspaces SET country = :country, size = :size WHERE id = :id"),
                {"country": country, "size": size, "id": world.alpha},
            )
            await session.commit()


async def test_organisations_are_found_by_country_size_and_activity(
    client: AsyncClient, world: World
) -> None:
    def ids(response: httpx.Response) -> set[str]:
        return {row["id"] for row in response.json()["data"]}

    listed = await client.get(
        f"{API}/organisations", params={"q": world.marker}, headers=as_(world, SUPER)
    )
    [alpha] = listed.json()["data"]
    # Nothing kept yet, nothing declared: said unknown, never guessed.
    assert (alpha["country"], alpha["size"], alpha["size_declared"]) == (None, None, None)

    # Its owner said a size when signing up: shown as theirs, apart.
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text("UPDATE users SET company_size = '11-50' WHERE id = :id"), {"id": world.owner}
            )
            await session.commit()
    declared = await client.get(
        f"{API}/organisations",
        params={"q": world.marker, "size": "11-50"},
        headers=as_(world, SUPER),
    )
    assert ids(declared) == {str(world.alpha)}
    assert declared.json()["data"][0]["size_declared"] == "11-50"
    assert declared.json()["data"][0]["size"] is None

    # What LEKA's team keeps comes first.
    await _keep(world, country="FR", size="51-200")
    params = {"q": world.marker, "country": "fr", "size": "51-200"}
    kept = await client.get(f"{API}/organisations", params=params, headers=as_(world, SUPER))
    assert ids(kept) == {str(world.alpha)}
    assert (kept.json()["data"][0]["country"], kept.json()["data"][0]["size"]) == ("FR", "51-200")
    elsewhere = await client.get(
        f"{API}/organisations",
        params={"q": world.marker, "country": "DE"},
        headers=as_(world, SUPER),
    )
    assert ids(elsewhere) == set()

    # Alpha did something today: active, never inactive nor never.
    for activity, expected in (
        ("active", {str(world.alpha)}),
        ("inactive", set()),
        ("never", set()),
    ):
        found = await client.get(
            f"{API}/organisations",
            params={"q": world.marker, "activity": activity},
            headers=as_(world, SUPER),
        )
        assert ids(found) == expected, activity
    refused = await client.get(
        f"{API}/organisations", params={"country": "France"}, headers=as_(world, SUPER)
    )
    assert refused.status_code == 422


async def test_changing_an_organisation_is_the_operations_with_a_reason_said_in_both_trails(
    client: AsyncClient, world: World
) -> None:
    path = f"{API}/organisations/{world.alpha}"
    key = {"Idempotency-Key": f"update-{world.marker}"}
    change = {"country": "BE", "size": "11-50", "reason": "said by their CTO on the phone"}

    # Support reads it, never changes it.
    support = await client.patch(
        path, json=change, headers={**as_(world, AdminRole.SUPPORT), **key}
    )
    assert support.status_code == 403

    done = await client.patch(
        path, json=change, headers={**as_(world, AdminRole.OPERATIONS), **key}
    )
    assert done.status_code == 200
    body = done.json()
    assert (body["action"], body["replayed"]) == ("updated", False)
    assert body["changed"] == {"country": [None, "BE"], "size": [None, "11-50"]}
    again = await client.patch(
        path, json=change, headers={**as_(world, AdminRole.OPERATIONS), **key}
    )
    assert again.json()["replayed"] is True

    detail = (await client.get(path, headers=as_(world, SUPER))).json()
    assert (detail["country"], detail["size"]) == ("BE", "11-50")

    # The customer's trail: LEKA changed these fields, never why.
    with system_scope():
        async with session_factory() as session:
            [said] = (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.workspace_id == world.alpha,
                        AuditEvent.action == "workspace.updated",
                    )
                )
            ).all()
            [kept] = (
                await session.scalars(
                    select(AdminAuditEvent).where(
                        AdminAuditEvent.for_workspace_id == world.alpha,
                        AdminAuditEvent.action == "admin.organisation_updated",
                    )
                )
            ).all()
    assert said.detail == {"by": "LEKA", "fields": ["country", "size"]}
    assert kept.detail["reason"] == "said by their CTO on the phone"
    assert kept.detail["changed"] == {"country": [None, "BE"], "size": [None, "11-50"]}

    # Nothing to change, a country that is not one: refused before anything.
    operations = {**as_(world, AdminRole.OPERATIONS), "Idempotency-Key": f"none-{world.marker}"}
    nothing = await client.patch(path, json={"reason": "nothing at all"}, headers=operations)
    assert nothing.status_code == 422
    wrong = await client.patch(
        path, json={"country": "France", "reason": "a name, not a code"}, headers=operations
    )
    assert wrong.status_code == 422
    no_reason = await client.patch(path, json={"size": "1-10"}, headers=operations)
    assert no_reason.status_code == 422


async def test_a_note_is_for_leka_s_team_never_for_the_customer(
    client: AsyncClient, world: World
) -> None:
    path = f"{API}/organisations/{world.alpha}/notes"
    first = await client.post(
        path, json={"body": "  Prefers calls on Tuesdays.  "}, headers=as_(world, AdminRole.SUPPORT)
    )
    assert first.status_code == 201
    assert first.json()["body"] == "Prefers calls on Tuesdays."
    assert first.json()["admin_email"] == f"support-{world.marker}@leka.test"
    second = await client.post(
        path, json={"body": "Invoice sent again by hand."}, headers=as_(world, AdminRole.FINANCE)
    )
    assert second.status_code == 201
    assert (
        await client.post(path, json={"body": "   "}, headers=as_(world, AdminRole.SUPPORT))
    ).status_code == 422

    listed = await client.get(path, headers=as_(world, AdminRole.OPERATIONS))
    notes = listed.json()["data"]
    assert [n["body"] for n in notes] == [
        "Invoice sent again by hand.",
        "Prefers calls on Tuesdays.",
    ]
    assert notes[0]["admin_name"] == "finance"

    # The customer's trail never hears of it; the admin trail, never its words.
    with system_scope():
        async with session_factory() as session:
            customer = (
                await session.scalars(
                    select(AuditEvent.action).where(AuditEvent.workspace_id == world.alpha)
                )
            ).all()
            trail = (
                await session.scalars(
                    select(AdminAuditEvent).where(
                        AdminAuditEvent.for_workspace_id == world.alpha,
                        AdminAuditEvent.action == "admin.note_added",
                    )
                )
            ).all()
    assert not any("note" in action for action in customer)
    assert {str(t.detail) for t in trail} == {
        str({"characters": 26}),
        str({"characters": 27}),
    }
    missing = await client.post(
        f"{API}/organisations/{uuid.uuid4()}/notes",
        json={"body": "nobody"},
        headers=as_(world, SUPER),
    )
    assert missing.status_code == 404


async def test_what_leka_s_team_did_to_an_organisation_never_what_it_read(
    client: AsyncClient, world: World
) -> None:
    await client.get(f"{API}/organisations/{world.alpha}", headers=as_(world, SUPER))
    await client.post(
        f"{API}/organisations/{world.alpha}/credits",
        json={"credits": 50, "reason": "a goodwill gesture"},
        headers={**as_(world, AdminRole.FINANCE), "Idempotency-Key": f"credits-{world.marker}"},
    )
    await client.post(
        f"{API}/organisations/{world.alpha}/notes",
        json={"body": "Called back."},
        headers=as_(world, AdminRole.SUPPORT),
    )
    history = await client.get(
        f"{API}/organisations/{world.alpha}/history", headers=as_(world, AdminRole.SUPPORT)
    )
    assert history.status_code == 200
    rows = history.json()["data"]
    assert [r["action"] for r in rows] == ["admin.note_added", "admin.credits_added"]
    assert rows[1]["detail"] == {"credits": 50, "reason": "a goodwill gesture"}
    assert rows[1]["admin_email"] == f"finance-{world.marker}@leka.test"


async def test_the_alerts_on_its_environment_are_for_who_reads_environments(
    client: AsyncClient, world: World
) -> None:
    with system_scope():
        async with session_factory() as session:
            session.add(
                MonitoringAlert(
                    workspace_id=world.alpha,
                    subject_type="source",
                    subject_id=uuid.uuid4(),
                    subject_name=f"github-{world.marker}",
                    family="source",
                    kind="source_failing",
                    severity="medium",
                    certainty="confirmed",
                    status="open",
                    opened_at=NOW - timedelta(hours=2),
                    last_seen_at=NOW,
                )
            )
            await session.commit()
    path = f"{API}/organisations/{world.alpha}/incidents"
    alerts = await client.get(path, headers=as_(world, AdminRole.OPERATIONS))
    assert alerts.status_code == 200
    [alert] = alerts.json()["data"]
    assert (alert["subject_name"], alert["status"], alert["severity"]) == (
        f"github-{world.marker}",
        "open",
        "medium",
    )
    resolved = await client.get(
        path, params={"status": "resolved"}, headers=as_(world, AdminRole.OPERATIONS)
    )
    assert resolved.json()["data"] == []
    assert (await client.get(path, headers=as_(world, AdminRole.FINANCE))).status_code == 403

    detail = (
        await client.get(f"{API}/organisations/{world.alpha}", headers=as_(world, SUPER))
    ).json()
    assert detail["counts"]["alerts_open"] == 1
    assert (detail["counts"]["analyses_completed"], detail["counts"]["analyses_failed"]) == (0, 0)


async def test_an_organisation_deleted_takes_its_notes_with_it(
    client: AsyncClient, world: World
) -> None:
    gone = Workspace(id=uuid.uuid4(), name=f"Gone {world.marker}", slug=f"gone-{world.marker}")
    with system_scope():
        async with session_factory() as session:
            session.add(gone)
            await session.commit()
    await client.post(
        f"{API}/organisations/{gone.id}/notes",
        json={"body": "Asked to leave."},
        headers=as_(world, SUPER),
    )
    with system_scope():
        async with session_factory() as session:
            await session.execute(delete(Workspace).where(Workspace.id == gone.id))
            await session.commit()
            left = (
                await session.scalars(
                    select(AdminNote).where(AdminNote.for_workspace_id == gone.id)
                )
            ).all()
    assert left == []
