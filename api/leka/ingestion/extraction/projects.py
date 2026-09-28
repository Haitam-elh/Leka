"""Project tools beyond Jira: Linear, Asana, Trello, ClickUp, Monday (LEKA-346).

Each has projects — a Linear project, an Asana project, a Trello board, a
ClickUp list, a Monday board — and the work in them, which LEKA reads as
`issues`: a Linear issue, an Asana task, a Trello card, a ClickUp task, a
Monday item. They come out the same way as Jira's: a title, a state, dates,
the description, the people, the project, a `key` when the tool gives one.

`metadata.status_category` carries the tool's own class of state when it
has one (Linear's `started`, ClickUp's `closed`), which normalisation reads
before the state's name, as it does Jira's.

The payloads are the ones leka/connectors/{linear,asana,trello,clickup,
monday} store.
"""

from __future__ import annotations

from datetime import UTC, datetime

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction.contract import Extracted, Reference
from leka.ingestion.extraction.engine import Payload, strategy
from leka.ingestion.extraction.fields import (
    content,
    dig,
    flag,
    lower,
    number,
    ref,
    required,
    string,
    strings,
    when,
)

C = Capability
LINEAR, ASANA, TRELLO = SourceKind.LINEAR, SourceKind.ASANA, SourceKind.TRELLO
CLICKUP, MONDAY = SourceKind.CLICKUP, SourceKind.MONDAY


# ── Linear ───────────────────────────────────────────────────────────────────


@strategy("linear.projects", 1, (LINEAR, C.PROJECTS))
def linear_project(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        url=string(p, "url"),
        state=lower(p, "status", "type") or lower(p, "status", "name"),
        created_at=when(p, "createdAt"),
        updated_at=when(p, "updatedAt"),
        content=content("description", string(p, "description"), "markdown"),
        references=ref(
            "lead",
            "person",
            external_id=dig(p, "lead", "id"),
            name=dig(p, "lead", "name"),
            email=dig(p, "lead", "email"),
        ),
        metadata={
            "key": string(p, "slugId"),
            "progress": number(p, "progress"),
            "starts_at": _day(string(p, "startDate")),
            "due_at": _day(string(p, "targetDate")),
            "teams": strings(p, "teams", "nodes", key="key"),
        },
    )


@strategy("linear.issues", 1, (LINEAR, C.ISSUES))
def linear_issue(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "title"),
        url=string(p, "url"),
        state=lower(p, "state", "name"),
        created_at=when(p, "createdAt"),
        updated_at=when(p, "updatedAt"),
        content=content("description", string(p, "description"), "markdown"),
        references=[
            *_person("assignee", dig(p, "assignee")),
            *_person("creator", dig(p, "creator")),
            *ref(
                "project",
                "project",
                external_id=dig(p, "project", "id"),
                name=dig(p, "project", "name"),
            ),
            *ref("parent", "issue", external_id=dig(p, "parent", "identifier")),
            *[
                ref("related", "issue", external_id=dig(r, "relatedIssue", "identifier"))[0]
                for r in _list(dig(p, "relations", "nodes"))
                if dig(r, "relatedIssue", "identifier")
            ],
        ],
        metadata={
            "key": required(p, "identifier"),
            "status_category": lower(p, "state", "type"),
            "priority": string(p, "priorityLabel"),
            "estimate": number(p, "estimate"),
            "cycle": string(p, "cycle", "name") or string(p, "cycle", "number"),
            "labels": strings(p, "labels", "nodes", key="name"),
            "team": string(p, "team", "key"),
            "due_at": _day(string(p, "dueDate")),
        },
    )


# ── Asana ────────────────────────────────────────────────────────────────────


@strategy("asana.projects", 1, (ASANA, C.PROJECTS))
def asana_project(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        url=string(p, "permalink_url"),
        state="archived"
        if flag(p, "archived")
        else ("completed" if flag(p, "completed") else "active"),
        created_at=when(p, "created_at"),
        updated_at=when(p, "modified_at"),
        content=content("description", string(p, "notes")),
        references=_person("owner", dig(p, "owner")),
        metadata={
            "team": string(p, "team", "name"),
            "workspace": string(p, "workspace", "name"),
            "starts_at": _day(string(p, "start_on")),
            "due_at": _day(string(p, "due_on")),
        },
    )


@strategy("asana.issues", 1, (ASANA, C.ISSUES))
def asana_task(p: Payload) -> Extracted:
    memberships = dig(p, "memberships")
    projects = [
        m for m in (memberships if isinstance(memberships, list) else []) if isinstance(m, dict)
    ]
    return Extracted(
        title=required(p, "name"),
        url=string(p, "permalink_url"),
        state="closed" if flag(p, "completed") else "open",
        created_at=when(p, "created_at"),
        updated_at=when(p, "modified_at"),
        content=content("description", string(p, "notes")),
        references=[
            *_person("assignee", dig(p, "assignee")),
            *ref(
                "parent",
                "issue",
                external_id=dig(p, "parent", "gid"),
                name=dig(p, "parent", "name"),
            ),
            *[
                r
                for m in projects
                for r in ref(
                    "project",
                    "project",
                    external_id=dig(m, "project", "gid"),
                    name=dig(m, "project", "name"),
                )
            ],
        ],
        metadata={
            "type": lower(p, "resource_subtype"),
            "sections": [s for s in (string(m, "section", "name") for m in projects) if s],
            "labels": strings(p, "tags", key="name"),
            "subtasks": number(p, "num_subtasks"),
            "due_at": _iso(when(p, "due_at")) or _day(string(p, "due_on")),
            "completed_at": _iso(when(p, "completed_at")),
        },
    )


# ── Trello ───────────────────────────────────────────────────────────────────


@strategy("trello.projects", 1, (TRELLO, C.PROJECTS))
def trello_board(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        url=string(p, "url"),
        state="closed" if flag(p, "closed") else "open",
        updated_at=when(p, "dateLastActivity"),
        content=content("description", string(p, "desc"), "markdown"),
        metadata={
            "key": string(p, "shortLink"),
            "workspace": string(p, "organization", "displayName"),
            "lists": strings(p, "lists", key="name"),
            "labels": strings(p, "labels", key="name"),
        },
    )


@strategy("trello.issues", 1, (TRELLO, C.ISSUES))
def trello_card(p: Payload) -> Extracted:
    members = dig(p, "idMembers")
    return Extracted(
        title=required(p, "name"),
        url=string(p, "url"),
        state="closed" if flag(p, "closed") else "open",
        updated_at=when(p, "dateLastActivity"),
        content=content("description", string(p, "desc"), "markdown"),
        references=[
            *[
                r
                for member in (members if isinstance(members, list) else [])
                for r in ref("assignee", "person", external_id=member)
            ],
            *ref("project", "project", external_id=dig(p, "idBoard")),
        ],
        metadata={
            "number": number(p, "idShort"),
            "list_id": string(p, "idList"),
            "labels": strings(p, "labels", key="name"),
            "due_at": _iso(when(p, "due")),
            "due_complete": flag(p, "dueComplete"),
        },
    )


# ── ClickUp ──────────────────────────────────────────────────────────────────


@strategy("clickup.projects", 1, (CLICKUP, C.PROJECTS))
def clickup_list(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        state="archived" if flag(p, "archived") else "active",
        content=content("description", string(p, "content"), "markdown"),
        metadata={
            "folder": string(p, "folder", "name"),
            "space": string(p, "space", "name"),
            "tasks": number(p, "task_count"),
            "due_at": _iso(_millis(dig(p, "due_date"))),
        },
    )


@strategy("clickup.issues", 1, (CLICKUP, C.ISSUES))
def clickup_task(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        url=string(p, "url"),
        state=lower(p, "status", "status"),
        created_at=_millis(dig(p, "date_created")),
        updated_at=_millis(dig(p, "date_updated")),
        content=content(
            "description",
            string(p, "markdown_description") or string(p, "text_content"),
            "markdown",
        ),
        references=[
            *[
                r
                for who in _list(dig(p, "assignees"))
                for r in _person("assignee", who, name_key="username")
            ],
            *_person("creator", dig(p, "creator"), name_key="username"),
            *ref(
                "project", "project", external_id=dig(p, "list", "id"), name=dig(p, "list", "name")
            ),
            *ref("parent", "issue", external_id=dig(p, "parent")),
        ],
        metadata={
            "key": string(p, "custom_id"),
            "status_category": lower(p, "status", "type"),
            "priority": string(p, "priority", "priority"),
            "labels": strings(p, "tags", key="name"),
            "space": string(p, "space", "id"),
            "due_at": _iso(_millis(dig(p, "due_date"))),
            "closed_at": _iso(_millis(dig(p, "date_closed"))),
        },
    )


# ── Monday ───────────────────────────────────────────────────────────────────


@strategy("monday.projects", 1, (MONDAY, C.PROJECTS))
def monday_board(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        url=string(p, "url"),
        state=lower(p, "state"),
        updated_at=when(p, "updated_at"),
        content=content("description", string(p, "description")),
        references=[
            r
            for owner in _list(dig(p, "owners"))
            for r in ref("owner", "person", external_id=dig(owner, "id"), name=dig(owner, "name"))
        ],
        metadata={
            "workspace": string(p, "workspace", "name"),
            "kind": lower(p, "board_kind"),
            "items": number(p, "items_count"),
            "groups": strings(p, "groups", key="title"),
        },
    )


@strategy("monday.issues", 1, (MONDAY, C.ISSUES))
def monday_item(p: Payload) -> Extracted:
    columns = dig(p, "column_values")
    values = [c for c in _list(columns) if isinstance(c, dict)]
    status = next((string(c, "text") for c in values if c.get("type") == "status"), None)
    return Extracted(
        title=required(p, "name"),
        url=string(p, "url"),
        state=status.lower() if status else lower(p, "state"),
        created_at=when(p, "created_at"),
        updated_at=when(p, "updated_at"),
        references=[
            *ref(
                "creator",
                "person",
                external_id=dig(p, "creator", "id"),
                name=dig(p, "creator", "name"),
            ),
            *ref("parent", "issue", external_id=dig(p, "parent_item", "id")),
        ],
        metadata={
            "group": string(p, "group", "title"),
            "columns": sorted(
                f"{string(c, 'id')}={string(c, 'text')}" for c in values if string(c, "text")
            ),
            "subitems": len(_list(dig(p, "subitems"))),
        },
    )


# ── shared ───────────────────────────────────────────────────────────────────


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _person(role: str, who: object, *, name_key: str = "name") -> list[Reference]:
    """A person the tool names: by email when it says one, else its id."""
    return ref(
        role,
        "person",
        external_id=dig(who, "id") or dig(who, "gid"),
        name=dig(who, name_key),
        email=dig(who, "email"),
    )


def _millis(value: object) -> datetime | None:
    """ClickUp's dates: milliseconds since the epoch, as text."""
    text = str(value) if value is not None else ""
    return datetime.fromtimestamp(int(text) / 1000, tz=UTC) if text.isdigit() else None


def _day(value: str | None) -> str | None:
    """A day as the tool wrote it ('2026-10-01'), kept as a day."""
    return value[:10] if value else None


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat() if moment else None
