"""Canonical identifiers: one name for one thing, whichever source names it.

A pull request's link in a Jira comment, its number in a commit message and
the pull request itself, read from GitHub, must come out with the same key —
that is what lets entity resolution (LEKA-357) join them. So a key is built
from what every mention of the thing carries, spelled one way:

    repository        github.com/acme/api                      host + path, lower-cased, no .git
    issue, PR (GitHub) github.com/acme/api#41                  one numbering for both, on GitHub
    issue (GitLab…)   gitlab.com/acme/api#3                    issues: #
    PR, MR            gitlab.com/acme/api!12                   pull and merge requests: !
    commit            github.com/acme/api@9f2c…                the full sha, lower-cased
    branch            github.com/acme/api:main
    release           github.com/acme/api/releases/v1.2.0
    Jira              acme.atlassian.net/PAY-42, …/PAY         the site, the key upper-cased
    a ticket, alone   ticket:PAY-42                            a key with no site: resolved later
    person            person:email:sara@acme.io                the email when known,
                      person:github.com:sara                   else the account on its host
    cloud resource    aws:arn:…, azure:/subscriptions/…, gcp://…   the provider's global id
    service, team     service:billing, team:payments           a slug of the name
    incident          incident:pagerduty:Q1ABC…                the tool and its own id
    Linear issue      linear.app/acme/ENG-42                   its workspace, its identifier;
                                                               alias ticket:ENG-42
    another tool's    asana:issue:1204…, trello:project:5f1e…  the tool, what it is, its id
    document          notion:document:1a2b…, acme.atlassian.net/wiki/pages/1001
    knowledge space   acme.atlassian.net/wiki/spaces/ENG,      where documents are kept:
                      notion:space:…, google_workspace:space:…  the tool and its own id
    capability        capability:payments                      a slug of the name (LEKA-366)
    process           process:order-to-cash,                   an activity under its
                      process:order-to-cash/invoice            process's name
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qs, urlsplit

DEFAULT_HOSTS = {"github": "github.com", "gitlab": "gitlab.com", "bitbucket": "bitbucket.org"}
JIRA_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,9}-\d+$")
# A Notion page's or database's id, ending its link's last segment.
NOTION_ID = re.compile(r"([0-9a-f]{32})$")
# What a Google Docs link opens: a document, a sheet, slides, a form.
GOOGLE_EDITORS = frozenset({"document", "spreadsheets", "presentation", "forms"})
# A code host's own pages, not a repository's: github.com/orgs/acme/…
NOT_OWNERS = frozenset(
    {"orgs", "settings", "notifications", "marketplace", "sponsors", "topics", "features"}
    | {"about", "login", "enterprise", "explore", "search", "users", "groups", "dashboard"}
)


def host_of(url: str | None, kind: str) -> str:
    """The host a code-host record lives on: its link's, else the vendor's
    public one (a self-hosted GitLab without a link is the one case wrong)."""
    host = (urlsplit(url).hostname or "") if url else ""
    return host.lower().removeprefix("www.") or DEFAULT_HOSTS.get(kind, kind)


def path(value: str) -> str:
    """A repository path, one way: 'Acme/API.git/' → 'acme/api'."""
    return value.strip().strip("/").lower().removesuffix(".git")


def repository(host: str, repo: str) -> str:
    return f"{host}/{path(repo)}"


def numbered(host: str, repo: str, number: object, *, pull: bool) -> str:
    """An issue or a pull request by its number. On GitHub both share one
    numbering, so both are '#'; elsewhere pull and merge requests are '!'."""
    mark = "!" if pull and host != "github.com" else "#"
    return f"{repository(host, repo)}{mark}{number}"


def commit(host: str, repo: str, sha: str) -> str:
    return f"{repository(host, repo)}@{sha.strip().lower()}"


def branch(host: str, repo: str, name: str) -> str:
    return f"{repository(host, repo)}:{name.strip()}"


def release(host: str, repo: str, tag: str) -> str:
    return f"{repository(host, repo)}/releases/{tag.strip()}"


def jira(site: str, key: str) -> str:
    return f"{site.lower()}/{key.strip().upper()}"


def ticket(key: str, *, site: str | None) -> str:
    """A ticket key: on its site when known, else alone — 'PAY-42' written
    in a GitHub pull request could be any Jira's."""
    return jira(site, key) if site else f"ticket:{key.strip().upper()}"


def person_email(email: str) -> str:
    return f"person:email:{email.strip().lower()}"


def person_account(host: str, account: str) -> str:
    """An account on its host: a login (case-insensitive on code hosts), a
    Jira account id, a Bitbucket uuid."""
    account = account.strip()
    return f"person:{host}:{account.lower() if not account.startswith('{') else account}"


def cloud(provider: str, resource_id: str) -> str:
    """The provider's own global id: an ARN, an ARM id (case-insensitive,
    lower-cased), a Google full resource name."""
    resource_id = resource_id.strip()
    return f"{provider}:{resource_id.lower() if provider == 'azure' else resource_id}"


def cloud_account(provider: str, account_id: str) -> str:
    """What a provider's resources are in, by its own id (LEKA-363): an AWS
    account, `aws:account:123456789012`; an Azure subscription, by its ARM
    id as its resources' keys begin; a Google Cloud project, by its id —
    `gcp:project:acme-prod`."""
    account_id = account_id.strip()
    if provider == "azure":
        return cloud("azure", f"/subscriptions/{account_id}")
    return f"{provider}:{'project' if provider == 'gcp' else 'account'}:{account_id}"


def database(engine: str, host: str, port: int | None, name: str | None) -> str:
    """What a database source reads (LEKA-364): its engine, server and
    database — `db:postgresql://ledger.abc.rds.amazonaws.com:5432/ledger`;
    a MySQL, MariaDB or MongoDB server, whose databases are its schemas,
    without one. Whichever source reads it, the same key."""
    where = f"{host.strip().lower()}:{port}" if port else host.strip().lower()
    return f"db:{engine}://{where}" + (f"/{name.strip()}" if name and name.strip() else "")


def data_schema(database_key: str, schema: str) -> str:
    """A schema of a database: `<database>/billing`."""
    return f"{database_key}/{schema}"


def data_object(database_key: str, schema: str, name: str) -> str:
    """A table, a view, a collection: `<database>/billing/invoices`."""
    return f"{database_key}/{schema}/{name}"


def endpoint(host: str, port: int | str | None) -> str:
    """Where a client connects to a database server: what a cloud database
    instance is also known by, and what a database source names."""
    return f"endpoint:{host.strip().lower()}:{port}" if port else f"endpoint:{host.strip().lower()}"


def slug(name: str) -> str:
    """'Billing API ' → 'billing-api'; accents dropped, anything else a dash."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def incident(system: str, incident_id: str) -> str:
    """An incident by the tool that holds it and that tool's id: PagerDuty's
    are global, Datadog's a uuid — not their per-account numbers."""
    return f"incident:{system}:{incident_id.strip()}"


def item(system: str, what: str, item_id: str) -> str:
    """A project, an issue or a document of a tool whose ids are its own —
    global, or at least the tool's: asana:issue:1204…"""
    return f"{system}:{what}:{item_id.strip()}"


def document(
    system: str, document_id: str, *, site: str | None = None, drive: str | None = None
) -> str:
    """A document: its tool and its id. Confluence's ids are its site's, so
    its key is the site's; a Microsoft 365 item's, its drive's."""
    if system == "confluence":
        return (
            f"{site}/wiki/pages/{document_id}" if site else item("confluence", "page", document_id)
        )
    if system == "microsoft_365" and drive:
        return item("microsoft_365", "document", f"{drive}/{document_id}")
    return item(system, "document", document_id)


def space(system: str, space_id: str, *, site: str | None = None) -> str:
    """Where documents are kept (LEKA-366), by its tool and its own id — a
    Confluence space by its key on its site, as its pages name it."""
    if system == "confluence":
        key = space_id.strip().upper()
        return f"{site}/wiki/spaces/{key}" if site else item("confluence", "space", key)
    return item(system, "space", space_id)


def linked(url: str) -> tuple[str, str] | None:
    """What a link opens, when its address says which — (`document`, key),
    (`knowledge_space`, key) or (`repository`, key) — keyed as that thing's
    own record is: a Confluence page, a Notion page, a Google document, a
    Slab post, a Guru card; a Confluence space, a Slab topic, a shared
    drive's folder; a repository on a code host."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    path = [p for p in parts.path.split("/") if p]
    if host.endswith(".atlassian.net") and path[:1] == ["wiki"]:
        return _confluence_link(host, path[1:], parts.query)
    if host in ("notion.so", "www.notion.so") or host.endswith(".notion.site"):
        found = NOTION_ID.search(path[-1].lower()) if path else None
        if found is None:
            return None
        h = found.group(1)
        return "document", item(
            "notion", "document", f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
        )
    if host == "docs.google.com":
        rest = path[2:] if path[1:3] == ["u", "0"] else path[1:]
        if path[:1] and path[0] in GOOGLE_EDITORS and rest[:1] == ["d"] and len(rest) > 1:
            return "document", item("google_workspace", "document", rest[1])
        return None
    if host == "drive.google.com":
        if path[:2] == ["file", "d"] and len(path) > 2:
            return "document", item("google_workspace", "document", path[2])
        opened = parse_qs(parts.query).get("id")
        if path == ["open"] and opened:
            return "document", item("google_workspace", "document", opened[0])
        if "folders" in path[:-1]:
            return "knowledge_space", item(
                "google_workspace", "space", path[path.index("folders") + 1]
            )
        return None
    if host.endswith(".slab.com") and len(path) == 2 and path[0] in ("posts", "topics"):
        own = path[1].rsplit("-", 1)[-1]
        what = "document" if path[0] == "posts" else "knowledge_space"
        return what, item("slab", "document" if what == "document" else "space", own)
    if host == "app.getguru.com" and len(path) >= 2 and path[0] == "card":
        return "document", item("guru", "card", path[1])
    return _repository_link(host, path)


def _confluence_link(host: str, path: list[str], query: str) -> tuple[str, str] | None:
    """A Confluence page — /spaces/ENG/pages/1001/Title, or
    /pages/viewpage.action?pageId=1001 — or a space: /spaces/ENG."""
    if path[:1] == ["spaces"] and len(path) >= 4 and path[2] == "pages" and path[3].isdigit():
        return "document", document("confluence", path[3], site=host)
    if path == ["pages", "viewpage.action"]:
        page = parse_qs(query).get("pageId")
        if page and page[0].isdigit():
            return "document", document("confluence", page[0], site=host)
        return None
    if path[:1] == ["spaces"] and len(path) in (2, 3) and path[2:] in ([], ["overview"]):
        return "knowledge_space", space("confluence", path[1], site=host)
    return None


def _repository_link(host: str, path: list[str]) -> tuple[str, str] | None:
    """A repository on a code host, from any of its pages: a GitLab
    project's path ends where `/-/` starts."""
    host = host.removeprefix("www.")
    if host not in DEFAULT_HOSTS.values() or len(path) < 2 or path[0].lower() in NOT_OWNERS:
        return None
    if host == "gitlab.com":
        project = path[: path.index("-")] if "-" in path else path
        return ("repository", repository(host, "/".join(project))) if len(project) >= 2 else None
    return "repository", repository(host, "/".join(path[:2]))


def capability(name: str) -> str:
    """A business capability by its name, as every source that names it
    writes it (LEKA-366)."""
    return f"capability:{slug(name)}"


def process(path: str) -> str:
    """A business process by its name — an activity by its path under its
    process, `Order to cash/Invoicing`: two processes may each have an
    `Approve`."""
    return "process:" + "/".join(part for part in map(slug, path.split("/")) if part)


def service(name: str) -> str:
    return f"service:{slug(name)}"


def team(name: str) -> str:
    return f"team:{slug(name)}"


def application(name: str) -> str:
    """An application — a group of services — by its name, as every tool
    that names it writes it (LEKA-362)."""
    return f"application:{slug(name)}"


def environment(name: str) -> str:
    """One of the company's environments, by its canonical name:
    `environment:production`."""
    return f"environment:{slug(name)}"


def site_of(url: str | None) -> str | None:
    """A Jira site from any of its links: 'acme.atlassian.net'."""
    host = (urlsplit(url).hostname or "") if url else ""
    return host.lower() or None
