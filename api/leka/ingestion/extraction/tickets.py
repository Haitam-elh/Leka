"""Project tools: Jira — its projects and its issues.

The payloads are Jira Cloud's REST v3, as leka/connectors/jira stores them:
/project/search (expanded with its description), /search/jql with every
field. Rich text (description, comments) is Atlassian Document Format,
flattened to plain text here; its structure is parsing's to read (LEKA-355).
"""

from __future__ import annotations

from urllib.parse import urlsplit

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction.contract import Content, Extracted, Reference
from leka.ingestion.extraction.engine import Payload, strategy
from leka.ingestion.extraction.fields import (
    adf_text,
    content,
    dig,
    lower,
    ref,
    required,
    string,
    strings,
    when,
)

JIRA = SourceKind.JIRA
MAX_COMMENTS = 50  # the latest ones; Jira returns them oldest first


@strategy("jira.projects", 1, (JIRA, Capability.PROJECTS))
def jira_project(p: Payload) -> Extracted:
    key = required(p, "key")
    return Extracted(
        title=string(p, "name") or key,
        url=_browse(p, key),
        state="archived" if dig(p, "archived") is True else "active",
        content=content("description", adf_text(dig(p, "description"))),
        references=ref(
            "lead",
            "person",
            external_id=dig(p, "lead", "accountId"),
            name=dig(p, "lead", "displayName"),
        ),
        metadata={
            "key": key,
            "type": lower(p, "projectTypeKey"),
            "category": string(p, "projectCategory", "name"),
        },
    )


@strategy("jira.issues", 2, (JIRA, Capability.ISSUES))
def jira_issue(p: Payload) -> Extracted:
    key = required(p, "key")
    f = dig(p, "fields")
    return Extracted(
        title=required(f, "summary"),
        url=_browse(p, key),
        state=lower(f, "status", "name"),
        created_at=when(f, "created"),
        updated_at=when(f, "updated"),
        content=[*content("description", adf_text(dig(f, "description"))), *_comments(f)],
        references=[
            *_person("assignee", dig(f, "assignee")),
            *_person("reporter", dig(f, "reporter")),
            *_person("creator", dig(f, "creator")),
            *ref(
                "project",
                "project",
                external_id=dig(f, "project", "key"),
                name=dig(f, "project", "name"),
            ),
            *ref("parent", "issue", external_id=dig(f, "parent", "key")),
            *_causes(f),
        ],
        metadata={
            "key": key,
            "type": lower(f, "issuetype", "name"),
            "status_category": lower(
                f, "status", "statusCategory", "key"
            ),  # new, indeterminate, done
            "priority": lower(f, "priority", "name"),
            "labels": strings(f, "labels"),
            "components": strings(f, "components", key="name"),
            "fix_versions": strings(f, "fixVersions", key="name"),
            "resolution": lower(f, "resolution", "name"),
            "resolved_at": string(f, "resolutiondate"),
            "due": string(f, "duedate"),
        },
    )


def _causes(fields: object) -> list[Reference]:
    """What this issue is caused by, and what it causes, as Jira's links of
    a type that says so — `Causes`, Jira Service Management's
    `Problem/Incident` — read (LEKA-367): the issue on the other end, as
    `caused_by` or `causes`."""
    links = dig(fields, "issuelinks")
    found: list[Reference] = []
    for link in links if isinstance(links, list) else []:
        words = " ".join(lower(link, "type", part) or "" for part in ("name", "inward", "outward"))
        if "cause" not in words:
            continue
        # An inward issue: this one "is caused by" it; an outward: "causes" it.
        found += ref("caused_by", "issue", external_id=dig(link, "inwardIssue", "key"))
        found += ref("causes", "issue", external_id=dig(link, "outwardIssue", "key"))
    return found


def _person(role: str, user: object) -> list[Reference]:
    return ref(role, "person", external_id=dig(user, "accountId"), name=dig(user, "displayName"))


def _comments(fields: object) -> list[Content]:
    comments = dig(fields, "comment", "comments")
    if not isinstance(comments, list):
        return []
    out: list[Content] = []
    for comment in comments[-MAX_COMMENTS:]:
        out += content("comment", adf_text(dig(comment, "body")))
    return out


def _browse(p: Payload, key: str) -> str | None:
    """The page a person opens: the site of the API `self` link, /browse/KEY."""
    self_link = string(p, "self")
    if not self_link:
        return None
    parts = urlsplit(self_link)
    return f"{parts.scheme}://{parts.netloc}/browse/{key}" if parts.netloc else None
