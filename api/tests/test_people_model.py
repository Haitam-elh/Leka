"""People and teams, as normalisation writes them (LEKA-365).

From the connectors' payloads through extraction, parsing and
normalisation: a GitHub team and a PagerDuty team — their parent, members
and leads; a directory's person — Microsoft 365's, Google Workspace's —
their title, department and manager; an HR system's people and teams.

What these protect: a team keyed by its name, so GitHub's, PagerDuty's and
a tag's meet; a person by their address, their accounts aliases; who
reports to whom, who leads what, as relationships a source states.
"""

from __future__ import annotations

from typing import Any

from leka.connectors import Capability, SourceKind
from leka.ingestion.normalisation import NormalisedRecord, normalise
from leka.ingestion.parsing import ParsedRecord, parse
from tests.test_extraction import _extract

C = Capability


def _normalised(
    kind: SourceKind, capability: Capability, payload: dict[str, Any], **extra: Any
) -> NormalisedRecord:
    extracted = _extract(kind, capability, payload, **extra)
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord)
    result = normalise(extracted, parsed)
    assert isinstance(result, NormalisedRecord), result
    return result


def _edges(record: NormalisedRecord) -> set[tuple[str, str, str]]:
    return {(r.from_key, r.type, r.to_key) for r in record.relationships}


def _related(record: NormalisedRecord) -> dict[str, tuple[str, str]]:
    return {e.key: (e.type, e.name) for e in record.related}


# ── teams ────────────────────────────────────────────────────────────────────


def test_a_github_team_is_its_name_its_parent_its_maintainers_and_members() -> None:
    team = _normalised(
        SourceKind.GITHUB,
        C.TEAMS,
        {
            "node_id": "T_1",
            "slug": "platform-eng",
            "name": "Platform",
            "description": "Runs the infrastructure",
            "privacy": "closed",
            "parent": {"slug": "engineering", "name": "Engineering"},
            "html_url": "https://github.com/orgs/acme/teams/platform-eng",
            "maintainers": ["sara"],
            "members": ["bob"],
        },
        external_id="T_1",
        container="acme",
    )

    entity = team.entity
    assert (entity.type, entity.key, entity.name) == ("team", "team:platform", "Platform")
    assert entity.aliases == ["team:platform-eng"]
    assert (entity.attributes["team_type"], entity.attributes["description"]) == (
        "team",
        "Runs the infrastructure",
    )
    assert _edges(team) >= {
        ("team:platform", "child_of", "team:engineering"),
        ("person:github.com:sara", "member_of", "team:platform"),
        ("team:platform", "led_by", "person:github.com:sara"),
        ("person:github.com:bob", "member_of", "team:platform"),
    }
    assert ("team:platform", "led_by", "person:github.com:bob") not in _edges(team)


def test_a_pagerduty_team_names_its_people_by_their_address() -> None:
    team = _normalised(
        SourceKind.PAGERDUTY,
        C.TEAMS,
        {
            "id": "PT1",
            "name": "Payments",
            "html_url": "https://acme.pagerduty.com/teams/PT1",
            "members": [
                {
                    "user": {"id": "PU1", "name": "Sara Martin", "email": "Sara@acme.io"},
                    "role": "manager",
                },
                {"user": {"id": "PU2", "summary": "Bob"}, "role": "responder"},
            ],
        },
        external_id="PT1",
    )

    assert team.entity.key == "team:payments"
    related = _related(team)
    assert related["person:email:sara@acme.io"] == ("person", "Sara Martin")
    assert ("team:payments", "led_by", "person:email:sara@acme.io") in _edges(team)
    assert ("person:acme.pagerduty.com:pu2", "member_of", "team:payments") in _edges(team)


# ── a directory's people ─────────────────────────────────────────────────────


def test_a_microsoft_365_person_their_department_and_manager() -> None:
    nora = _normalised(
        SourceKind.MICROSOFT_365,
        C.PEOPLE,
        {
            "id": "u-nora",
            "displayName": "Nora Diallo",
            "mail": "Nora@acme.io",
            "jobTitle": "Site reliability engineer",
            "department": "Platform",
            "officeLocation": "Paris",
            "accountEnabled": True,
            "manager": {"id": "u-sara", "displayName": "Sara Martin", "mail": "sara@acme.io"},
        },
        external_id="u-nora",
    )

    entity = nora.entity
    assert (entity.type, entity.key, entity.name) == (
        "person",
        "person:email:nora@acme.io",
        "Nora Diallo",
    )
    assert "person:microsoft_365:u-nora" in entity.aliases
    a = entity.attributes
    assert (a["job_title"], a["department"], a["location"], a["active"]) == (
        "Site reliability engineer",
        "Platform",
        "Paris",
        True,
    )
    assert _related(nora)["team:platform"] == ("team", "Platform")
    assert _edges(nora) >= {
        ("person:email:nora@acme.io", "member_of", "team:platform"),
        ("person:email:nora@acme.io", "reports_to", "person:email:sara@acme.io"),
    }
    department = next(e for e in nora.related if e.key == "team:platform")
    assert department.attributes == {"team_type": "department"}


def test_a_google_workspace_person_and_their_manager_by_address() -> None:
    nora = _normalised(
        SourceKind.GOOGLE_WORKSPACE,
        C.PEOPLE,
        {
            "id": "g-1",
            "primaryEmail": "nora@acme.io",
            "name": {"fullName": "Nora Diallo"},
            "organizations": [{"title": "SRE", "department": "Platform", "primary": True}],
            "relations": [{"type": "manager", "value": "sara@acme.io"}],
            "orgUnitPath": "/Engineering",
            "suspended": True,
        },
        external_id="g-1",
    )

    a = nora.entity.attributes
    assert (a["job_title"], a["location"], a["active"]) == ("SRE", "/Engineering", False)
    assert ("person:email:nora@acme.io", "reports_to", "person:email:sara@acme.io") in _edges(nora)


# ── an HR system ─────────────────────────────────────────────────────────────


def _hr(entity: str, record_id: str, title: str, metadata: dict[str, Any]) -> NormalisedRecord:
    return _normalised(
        SourceKind.CUSTOM_REST,
        C.RECORDS,
        {
            "resource": entity + "s",
            "entity": entity,
            "fields": {"id": record_id, "title": title, "metadata": metadata},
        },
        external_id=f"{entity}s:{record_id}",
    )


def test_an_hr_system_s_person_by_address_their_teams_and_manager() -> None:
    bob = _hr(
        "person",
        "e-42",
        "Bob Lee",
        {
            "email": "Bob@acme.io",
            "job_title": "Data engineer",
            "department": "Data",
            "teams": "Analytics",
            "manager": "sara@acme.io",
        },
    )

    entity = bob.entity
    assert (entity.type, entity.key) == ("person", "person:email:bob@acme.io")
    assert (entity.attributes["job_title"], entity.attributes["email"]) == (
        "Data engineer",
        "bob@acme.io",
    )
    assert {"manager", "teams", "department_name"}.isdisjoint(entity.attributes)
    assert _edges(bob) >= {
        ("person:email:bob@acme.io", "member_of", "team:data"),
        ("person:email:bob@acme.io", "member_of", "team:analytics"),
        ("person:email:bob@acme.io", "reports_to", "person:email:sara@acme.io"),
    }


def test_an_hr_system_s_team_its_parent_members_and_lead() -> None:
    analytics = _hr(
        "team",
        "t-7",
        "Analytics",
        {"parent": "Data", "members": "bob@acme.io, e-43", "lead": "sara@acme.io"},
    )

    key = analytics.entity.key
    assert key == "team:analytics"
    edges = _edges(analytics)
    assert {
        (key, "child_of", "team:data"),
        ("person:email:bob@acme.io", "member_of", key),
        ("person:email:sara@acme.io", "member_of", key),
        (key, "led_by", "person:email:sara@acme.io"),
    } <= edges
    # One the system names by its own id: an account of the system.
    assert any(f.endswith(":e-43") and kind == "member_of" for f, kind, _ in edges)
