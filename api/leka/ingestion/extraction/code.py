"""Code hosts: GitHub, GitLab, Bitbucket — seven kinds of record, one shape.

A pull request is a pull request whichever host it is on: the same title,
body, state, author, branches, labels. What each host calls them stays in
`extractor` and in the provenance; what they mean is the same field.

The payloads are the ones the connectors store (leka/connectors/<kind>/):
GitHub's REST v3, GitLab's v4, Bitbucket's 2.0. A deployment (LEKA-367):
what ref of which commit to which environment, how it went — GitHub's
statuses, oldest first — when it started and finished.
"""

from __future__ import annotations

import json

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction.contract import Extracted
from leka.ingestion.extraction.engine import Payload, strategy
from leka.ingestion.extraction.fields import (
    content,
    dig,
    first_line,
    flag,
    lower,
    number,
    people,
    ref,
    required,
    string,
    strings,
    when,
)

C = Capability
GITHUB, GITLAB, BITBUCKET = SourceKind.GITHUB, SourceKind.GITLAB, SourceKind.BITBUCKET
# A deployment's statuses that say it started, and that it is over.
STARTED = frozenset({"in_progress"})
FINISHED = frozenset({"success", "failure", "error"})

# ── GitHub ───────────────────────────────────────────────────────────────────


@strategy("github.repositories", 1, (GITHUB, C.REPOSITORIES))
def github_repository(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "full_name"),
        url=string(p, "html_url"),
        state="archived" if flag(p, "archived") else "active",
        created_at=when(p, "created_at"),
        updated_at=when(p, "pushed_at") or when(p, "updated_at"),
        content=content("description", dig(p, "description")),
        references=ref("owner", "account", external_id=dig(p, "owner", "login")),
        metadata={
            "visibility": lower(p, "visibility") or ("private" if flag(p, "private") else "public"),
            "default_branch": string(p, "default_branch"),
            "fork": flag(p, "fork"),
        },
        signals={
            "language": string(p, "language"),
            "topics": strings(p, "topics"),
            "size_kb": number(p, "size"),
        },
    )


@strategy("github.commits", 1, (GITHUB, C.COMMITS))
def github_commit(p: Payload) -> Extracted:
    message = string(p, "commit", "message")
    return Extracted(
        title=first_line(message) or required(p, "sha"),
        url=string(p, "html_url"),
        created_at=when(p, "commit", "author", "date"),
        updated_at=when(p, "commit", "committer", "date"),
        content=content("message", message),
        references=[
            *ref(
                "author",
                "person",
                external_id=dig(p, "author", "login"),
                name=dig(p, "commit", "author", "name"),
                email=dig(p, "commit", "author", "email"),
            ),
            *ref(
                "committer",
                "person",
                external_id=dig(p, "committer", "login"),
                name=dig(p, "commit", "committer", "name"),
                email=dig(p, "commit", "committer", "email"),
            ),
        ],
        metadata={"sha": required(p, "sha")},
        signals={"merge": _parents(dig(p, "parents")) > 1},
    )


@strategy("github.pull_requests", 1, (GITHUB, C.PULL_REQUESTS))
def github_pull_request(p: Payload) -> Extracted:
    merged = string(p, "merged_at")
    return Extracted(
        title=required(p, "title"),
        url=string(p, "html_url"),
        state="merged" if merged else lower(p, "state"),
        created_at=when(p, "created_at"),
        updated_at=when(p, "updated_at"),
        content=content("body", dig(p, "body"), "markdown"),
        references=[
            *ref("author", "person", external_id=dig(p, "user", "login")),
            *people("assignee", dig(p, "assignees"), id_key="login"),
            *people("reviewer", dig(p, "requested_reviewers"), id_key="login"),
            *ref("source_branch", "branch", name=dig(p, "head", "ref")),
            *ref("target_branch", "branch", name=dig(p, "base", "ref")),
        ],
        metadata={
            "number": number(p, "number"),
            "draft": flag(p, "draft"),
            "labels": strings(p, "labels", key="name"),
            "merged_at": merged,
            "closed_at": string(p, "closed_at"),
        },
    )


@strategy("github.issues", 1, (GITHUB, C.ISSUES))
def github_issue(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "title"),
        url=string(p, "html_url"),
        state=lower(p, "state"),
        created_at=when(p, "created_at"),
        updated_at=when(p, "updated_at"),
        content=content("body", dig(p, "body"), "markdown"),
        references=[
            *ref("author", "person", external_id=dig(p, "user", "login")),
            *people("assignee", dig(p, "assignees"), id_key="login"),
        ],
        metadata={
            "number": number(p, "number"),
            "labels": strings(p, "labels", key="name"),
            "closed_at": string(p, "closed_at"),
            "state_reason": lower(p, "state_reason"),
        },
    )


@strategy("github.releases", 1, (GITHUB, C.RELEASES))
def github_release(p: Payload) -> Extracted:
    tag = required(p, "tag_name")
    return Extracted(
        title=string(p, "name") or tag,
        url=string(p, "html_url"),
        state="draft" if flag(p, "draft") else "published",
        created_at=when(p, "created_at"),
        updated_at=when(p, "published_at") or when(p, "created_at"),
        content=content("notes", dig(p, "body"), "markdown"),
        references=ref("author", "person", external_id=dig(p, "author", "login")),
        metadata={"tag": tag, "prerelease": flag(p, "prerelease")},
    )


@strategy("github.branches", 1, (GITHUB, C.BRANCHES))
def github_branch(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        references=ref("head", "commit", external_id=dig(p, "commit", "sha")),
        metadata={"protected": flag(p, "protected")},
    )


@strategy("github.components", 2, (GITHUB, C.COMPONENTS))
def github_component(p: Payload) -> Extracted:
    """What a repository's code says it runs (LEKA-369): a service, a store
    or a service outside — leka.connectors.components read it — its links
    to the others as JSON lines, where each thing was read as text. And
    what the repository is made of (v2): its modules, as JSON lines."""
    if string(p, "kind") == "layout":
        return _layout(p)
    said = [e for e in _listed(p, "evidence") if isinstance(e, dict)]
    evidence = [
        f"{e.get('path')}:{e.get('line')} — {e.get('says')}"
        if e.get("line")
        else f"{e.get('path')} — {e.get('says')}"
        for e in said
    ]
    links = [
        json.dumps(link, sort_keys=True, ensure_ascii=False)
        for link in _listed(p, "links")
        if isinstance(link, dict)
    ]
    first = said[0] if said else None
    repository_url = string(p, "repository_url")
    url = (
        f"{repository_url}/blob/{string(p, 'default_branch')}/{first['path']}"
        + (f"#L{first['line']}" if first.get("line") else "")
        if repository_url and first and string(p, "default_branch")
        else repository_url
    )
    return Extracted(
        title=required(p, "display_name"),
        url=url,
        content=content("description", _component_said(p)),
        metadata={
            "component": required(p, "name"),
            "component_kind": string(p, "kind"),
            "role": string(p, "role"),
            "repository": string(p, "repository"),
            "repository_url": repository_url,
            "environment": string(p, "environment"),
            "engine": string(p, "engine"),
            "provider": string(p, "provider"),
            "region": string(p, "region"),
            "vendor": string(p, "vendor"),
            "image": string(p, "image"),
            "code_path": string(p, "code_path"),
            "public_url": string(p, "public_url"),
            "deployed_by": string(p, "deployed_by"),
            "deploy_method": string(p, "deploy_method"),
            "technology": strings(p, "technology"),
            "ports": strings(p, "ports"),
            "public_addresses": strings(p, "public_addresses"),
            "links": links,
            "evidence": evidence,
        },
    )


def _layout(p: Payload) -> Extracted:
    """A repository's modules — its top-level folders, their roles, files,
    languages and parts — read from its tree."""
    modules = [
        json.dumps(module, sort_keys=True, ensure_ascii=False)
        for module in _listed(p, "modules")
        if isinstance(module, dict)
    ]
    return Extracted(
        title=required(p, "display_name"),
        url=string(p, "repository_url"),
        content=content(
            "description",
            ", ".join(
                f"{m.get('path')} ({m.get('role')}, {m.get('files')})"
                for m in _listed(p, "modules")
                if isinstance(m, dict)
            ),
        ),
        metadata={
            "component": required(p, "name"),
            "component_kind": "layout",
            "repository": string(p, "repository"),
            "repository_url": string(p, "repository_url"),
            "default_branch": string(p, "default_branch"),
            "modules": modules,
            "files": number(p, "files"),
            "truncated": flag(p, "truncated"),
        },
    )


def _listed(p: Payload, key: str) -> list[object]:
    found = dig(p, key)
    return found if isinstance(found, list) else []


def _component_said(p: Payload) -> str:
    """A component in a sentence: what it is, in what, where it is reached."""
    said = [f"{string(p, 'display_name')}: {string(p, 'role') or string(p, 'kind')}"]
    if strings(p, "technology"):
        said.append("in " + ", ".join(strings(p, "technology")))
    if string(p, "public_url"):
        said.append(f"reached at {string(p, 'public_url')}")
    return " — ".join(said)


@strategy("github.deployments", 1, (GITHUB, C.DEPLOYMENTS))
def github_deployment(p: Payload) -> Extracted:
    environment = string(p, "environment") or string(p, "original_environment")
    shipped = string(p, "ref") or required(p, "sha")
    found = dig(p, "statuses")
    statuses = (
        [s for s in reversed(found) if isinstance(s, dict)] if isinstance(found, list) else []
    )
    latest = statuses[-1] if statuses else None
    history = [
        {"state": lower(s, "state"), "at": string(s, "created_at")}
        for s in statuses
        if lower(s, "state")
    ]
    return Extracted(
        title=f"{shipped} to {environment}" if environment else shipped,
        url=string(latest, "log_url")
        or string(latest, "target_url")
        or string(latest, "environment_url"),
        state=lower(latest, "state") or "created",
        created_at=when(p, "created_at"),
        updated_at=when(latest, "created_at") or when(p, "updated_at"),
        content=content("description", string(p, "description")),
        references=ref("creator", "person", external_id=dig(p, "creator", "login")),
        metadata={
            "id": number(p, "id"),
            # Its API link: where its repository lives — its own link is
            # its pipeline's.
            "api_url": string(p, "url"),
            "sha": string(p, "sha"),
            "ref": string(p, "ref"),
            "task": string(p, "task"),
            "environment": environment,
            "production": flag(p, "production_environment"),
            "environment_url": string(latest, "environment_url"),
            # Each status as `state@when`, the oldest first: metadata holds text.
            "status_history": [f"{h['state']}@{h['at'] or ''}" for h in history],
            "started_at": _first_at(history, STARTED),
            "finished_at": _first_at(history, FINISHED),
        },
        signals={"environment": environment},
    )


# ── GitLab ───────────────────────────────────────────────────────────────────


@strategy("gitlab.repositories", 1, (GITLAB, C.REPOSITORIES))
def gitlab_project(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "path_with_namespace"),
        url=string(p, "web_url"),
        state="archived" if flag(p, "archived") else "active",
        created_at=when(p, "created_at"),
        updated_at=when(p, "last_activity_at"),
        content=content("description", dig(p, "description"), "markdown"),
        references=ref("owner", "account", external_id=dig(p, "namespace", "full_path")),
        metadata={
            "visibility": lower(p, "visibility"),
            "default_branch": string(p, "default_branch"),
            "fork": dig(p, "forked_from_project") is not None,
        },
        signals={"topics": strings(p, "topics") or strings(p, "tag_list")},
    )


@strategy("gitlab.commits", 1, (GITLAB, C.COMMITS))
def gitlab_commit(p: Payload) -> Extracted:
    message = string(p, "message")
    return Extracted(
        title=string(p, "title") or first_line(message) or required(p, "id"),
        url=string(p, "web_url"),
        created_at=when(p, "authored_date"),
        updated_at=when(p, "committed_date"),
        content=content("message", message),
        references=[
            *ref("author", "person", name=dig(p, "author_name"), email=dig(p, "author_email")),
            *ref(
                "committer",
                "person",
                name=dig(p, "committer_name"),
                email=dig(p, "committer_email"),
            ),
        ],
        metadata={"sha": required(p, "id")},
        signals={"merge": _parents(dig(p, "parent_ids")) > 1},
    )


@strategy("gitlab.pull_requests", 1, (GITLAB, C.PULL_REQUESTS))
def gitlab_merge_request(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "title"),
        url=string(p, "web_url"),
        state=lower(p, "state"),  # opened, closed, merged, locked
        created_at=when(p, "created_at"),
        updated_at=when(p, "updated_at"),
        content=content("body", dig(p, "description"), "markdown"),
        references=[
            *ref(
                "author",
                "person",
                external_id=dig(p, "author", "username"),
                name=dig(p, "author", "name"),
            ),
            *people("assignee", dig(p, "assignees"), id_key="username", name_key="name"),
            *people("reviewer", dig(p, "reviewers"), id_key="username", name_key="name"),
            *ref("source_branch", "branch", name=dig(p, "source_branch")),
            *ref("target_branch", "branch", name=dig(p, "target_branch")),
        ],
        metadata={
            "number": number(p, "iid"),
            "draft": flag(p, "draft"),
            "labels": strings(p, "labels"),
            "merged_at": string(p, "merged_at"),
            "closed_at": string(p, "closed_at"),
        },
    )


@strategy("gitlab.issues", 1, (GITLAB, C.ISSUES))
def gitlab_issue(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "title"),
        url=string(p, "web_url"),
        state=lower(p, "state"),  # opened, closed
        created_at=when(p, "created_at"),
        updated_at=when(p, "updated_at"),
        content=content("body", dig(p, "description"), "markdown"),
        references=[
            *ref(
                "author",
                "person",
                external_id=dig(p, "author", "username"),
                name=dig(p, "author", "name"),
            ),
            *people("assignee", dig(p, "assignees"), id_key="username", name_key="name"),
        ],
        metadata={
            "number": number(p, "iid"),
            "labels": strings(p, "labels"),
            "closed_at": string(p, "closed_at"),
            "type": lower(p, "issue_type"),
        },
    )


@strategy("gitlab.releases", 1, (GITLAB, C.RELEASES))
def gitlab_release(p: Payload) -> Extracted:
    tag = required(p, "tag_name")
    return Extracted(
        title=string(p, "name") or tag,
        url=string(p, "_links", "self"),
        state="upcoming" if flag(p, "upcoming_release") else "published",
        created_at=when(p, "created_at"),
        updated_at=when(p, "released_at") or when(p, "created_at"),
        content=content("notes", dig(p, "description"), "markdown"),
        references=ref(
            "author",
            "person",
            external_id=dig(p, "author", "username"),
            name=dig(p, "author", "name"),
        ),
        metadata={"tag": tag},
    )


@strategy("gitlab.branches", 1, (GITLAB, C.BRANCHES))
def gitlab_branch(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        url=string(p, "web_url"),
        references=ref("head", "commit", external_id=dig(p, "commit", "id")),
        metadata={"protected": flag(p, "protected"), "default": flag(p, "default")},
    )


@strategy("gitlab.deployments", 1, (GITLAB, C.DEPLOYMENTS))
def gitlab_deployment(p: Payload) -> Extracted:
    environment = string(p, "environment", "name")
    shipped = string(p, "ref") or required(p, "sha")
    return Extracted(
        title=f"{shipped} to {environment}" if environment else shipped,
        url=string(p, "deployable", "web_url") or string(p, "environment", "external_url"),
        state=lower(p, "status"),
        created_at=when(p, "created_at"),
        updated_at=when(p, "updated_at") or when(p, "created_at"),
        references=ref(
            "creator", "person", external_id=dig(p, "user", "username"), name=dig(p, "user", "name")
        ),
        metadata={
            "id": number(p, "id"),
            "iid": number(p, "iid"),
            "sha": string(p, "sha"),
            "ref": string(p, "ref"),
            "environment": environment,
            "tier": lower(p, "environment", "tier"),
            "environment_url": string(p, "environment", "external_url"),
            "job": string(p, "deployable", "name"),
            "job_url": string(p, "deployable", "web_url"),
            "pipeline_url": string(p, "deployable", "pipeline", "web_url"),
            "started_at": string(p, "deployable", "started_at"),
            "finished_at": string(p, "finished_at") or string(p, "deployable", "finished_at"),
        },
        signals={"environment": environment},
    )


# ── Bitbucket ────────────────────────────────────────────────────────────────


@strategy("bitbucket.repositories", 1, (BITBUCKET, C.REPOSITORIES))
def bitbucket_repository(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "full_name"),
        url=string(p, "links", "html", "href"),
        state="active",
        created_at=when(p, "created_on"),
        updated_at=when(p, "updated_on"),
        content=content("description", dig(p, "description")),
        references=ref(
            "owner",
            "account",
            external_id=dig(p, "owner", "uuid"),
            name=dig(p, "owner", "display_name"),
        ),
        metadata={
            "visibility": "private" if flag(p, "is_private") else "public",
            "default_branch": string(p, "mainbranch", "name"),
            "fork": dig(p, "parent") is not None,
        },
        signals={"language": string(p, "language"), "size_bytes": number(p, "size")},
    )


@strategy("bitbucket.commits", 1, (BITBUCKET, C.COMMITS))
def bitbucket_commit(p: Payload) -> Extracted:
    message = string(p, "message")
    name, email = _raw_author(string(p, "author", "raw"))
    return Extracted(
        title=first_line(message) or required(p, "hash"),
        url=string(p, "links", "html", "href"),
        created_at=when(p, "date"),
        updated_at=when(p, "date"),
        content=content("message", message),
        references=ref(
            "author",
            "person",
            external_id=dig(p, "author", "user", "uuid"),
            name=dig(p, "author", "user", "display_name") or name,
            email=email,
        ),
        metadata={"sha": required(p, "hash")},
        signals={"merge": _parents(dig(p, "parents")) > 1},
    )


@strategy("bitbucket.pull_requests", 1, (BITBUCKET, C.PULL_REQUESTS))
def bitbucket_pull_request(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "title"),
        url=string(p, "links", "html", "href"),
        state=lower(p, "state"),  # open, merged, declined, superseded
        created_at=when(p, "created_on"),
        updated_at=when(p, "updated_on"),
        content=content("body", dig(p, "description"), "markdown"),
        references=[
            *ref(
                "author",
                "person",
                external_id=dig(p, "author", "uuid"),
                name=dig(p, "author", "display_name"),
            ),
            *people("reviewer", dig(p, "reviewers"), id_key="uuid", name_key="display_name"),
            *ref("source_branch", "branch", name=dig(p, "source", "branch", "name")),
            *ref("target_branch", "branch", name=dig(p, "destination", "branch", "name")),
        ],
        metadata={"number": number(p, "id"), "draft": flag(p, "draft")},
    )


@strategy("bitbucket.issues", 1, (BITBUCKET, C.ISSUES))
def bitbucket_issue(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "title"),
        url=string(p, "links", "html", "href"),
        state=lower(
            p, "state"
        ),  # new, open, resolved, on hold, invalid, duplicate, wontfix, closed
        created_at=when(p, "created_on"),
        updated_at=when(p, "updated_on"),
        content=content("body", dig(p, "content", "raw"), "markdown"),
        references=[
            *ref(
                "author",
                "person",
                external_id=dig(p, "reporter", "uuid"),
                name=dig(p, "reporter", "display_name"),
            ),
            *ref(
                "assignee",
                "person",
                external_id=dig(p, "assignee", "uuid"),
                name=dig(p, "assignee", "display_name"),
            ),
        ],
        metadata={
            "number": number(p, "id"),
            "type": lower(p, "kind"),
            "priority": lower(p, "priority"),
        },
    )


@strategy("bitbucket.branches", 1, (BITBUCKET, C.BRANCHES))
def bitbucket_branch(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        url=string(p, "links", "html", "href"),
        references=ref("head", "commit", external_id=dig(p, "target", "hash")),
    )


# ── shared ───────────────────────────────────────────────────────────────────


def _parents(parents: object) -> int:
    return len(parents) if isinstance(parents, list) else 0


def _raw_author(raw: str | None) -> tuple[str | None, str | None]:
    """Git's 'Name <email>', as Bitbucket gives it when no account matches."""
    if not raw:
        return None, None
    name, _, rest = raw.partition("<")
    email = rest.rstrip(">").strip() or None
    return name.strip() or None, email


def _first_at(history: list[dict[str, str | None]], states: frozenset[str]) -> str | None:
    """When a deployment's statuses first said one of these."""
    return next((h["at"] for h in history if h["state"] in states and h["at"]), None)
