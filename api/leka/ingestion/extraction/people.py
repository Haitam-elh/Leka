"""People and teams (LEKA-365): who works there, and how they are organised.

A TEAM — GitHub's, PagerDuty's — comes out with its name, its description,
its parent team as a reference (role `parent`), and its people as person
references: role `lead` for who leads it — a GitHub team's maintainers, a
PagerDuty team's managers — `member` for the others. GitHub names them by
login; PagerDuty by its user, with their address.

A PERSON — Microsoft 365's directory, Google Workspace's — comes out with
their name, their address, their title, department and office or
organisational unit as metadata, whether their account is on (`active`),
themselves as a reference (role `self`: their id at the directory)
and their manager as another (role `manager`).

The payloads are the ones leka/connectors/{github,pagerduty,microsoft_365,
google_workspace} store.
"""

from __future__ import annotations

from typing import Any

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction.contract import Extracted, Reference
from leka.ingestion.extraction.engine import Payload, strategy
from leka.ingestion.extraction.fields import content, dig, lower, ref, required, string, strings

C = Capability


@strategy("github.teams", 1, (SourceKind.GITHUB, C.TEAMS))
def github_team(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        url=string(p, "html_url"),
        content=content("description", string(p, "description")),
        references=[
            *ref(
                "parent",
                "team",
                external_id=string(p, "parent", "slug"),
                name=string(p, "parent", "name"),
            ),
            *(
                r
                for login in strings(p, "maintainers")
                for r in ref("lead", "person", external_id=login)
            ),
            *(
                r
                for login in strings(p, "members")
                for r in ref("member", "person", external_id=login)
            ),
        ],
        metadata={"slug": string(p, "slug"), "privacy": lower(p, "privacy")},
        signals={"kind": "team"},
    )


@strategy("pagerduty.teams", 1, (SourceKind.PAGERDUTY, C.TEAMS))
def pagerduty_team(p: Payload) -> Extracted:
    people: list[Reference] = []
    for member in _dicts(p.get("members")):
        user = member.get("user") if isinstance(member.get("user"), dict) else {}
        role = "lead" if str(member.get("role") or "").lower() == "manager" else "member"
        people += ref(
            role,
            "person",
            external_id=string(user, "id"),
            name=string(user, "name") or string(user, "summary"),
            email=string(user, "email"),
        )
    return Extracted(
        title=required(p, "name"),
        url=string(p, "html_url"),
        content=content("description", string(p, "description")),
        references=[
            *ref(
                "parent",
                "team",
                external_id=string(p, "parent", "id"),
                name=string(p, "parent", "summary"),
            ),
            *people,
        ],
        signals={"kind": "team"},
    )


@strategy("microsoft_365.people", 1, (SourceKind.MICROSOFT_365, C.PEOPLE))
def microsoft_365_person(p: Payload) -> Extracted:
    identifier = required(p, "id")
    email = string(p, "mail") or string(p, "userPrincipalName")
    name = string(p, "displayName") or email or identifier
    manager = dig(p, "manager")
    enabled = p.get("accountEnabled")
    return Extracted(
        title=name,
        references=[
            *ref("self", "person", external_id=identifier, name=name, email=email),
            *ref(
                "manager",
                "person",
                external_id=string(manager, "id"),
                name=string(manager, "displayName"),
                email=string(manager, "mail") or string(manager, "userPrincipalName"),
            ),
        ],
        metadata={
            "email": email,
            "job_title": string(p, "jobTitle"),
            "department": string(p, "department"),
            "location": string(p, "officeLocation"),
            "user_type": lower(p, "userType"),
            "active": enabled if isinstance(enabled, bool) else None,
        },
        signals={"kind": "person"},
    )


@strategy("google_workspace.people", 1, (SourceKind.GOOGLE_WORKSPACE, C.PEOPLE))
def google_workspace_person(p: Payload) -> Extracted:
    identifier = required(p, "id")
    email = string(p, "primaryEmail")
    name = string(p, "name", "fullName") or email or identifier
    organizations = _dicts(p.get("organizations"))
    work = next(
        (o for o in organizations if o.get("primary")), organizations[0] if organizations else {}
    )
    manager = next(
        (r for r in _dicts(p.get("relations")) if str(r.get("type") or "").lower() == "manager"),
        {},
    )
    suspended = p.get("suspended")
    return Extracted(
        title=name,
        references=[
            *ref("self", "person", external_id=identifier, name=name, email=email),
            *ref("manager", "person", email=string(manager, "value")),
        ],
        metadata={
            "email": email,
            "job_title": string(work, "title"),
            "department": string(work, "department"),
            "location": string(p, "orgUnitPath"),
            "active": not suspended if isinstance(suspended, bool) else None,
        },
        signals={"kind": "person"},
    )


def _dicts(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
