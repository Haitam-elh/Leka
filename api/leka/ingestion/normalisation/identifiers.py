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
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

DEFAULT_HOSTS = {"github": "github.com", "gitlab": "gitlab.com", "bitbucket": "bitbucket.org"}
JIRA_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,9}-\d+$")


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
