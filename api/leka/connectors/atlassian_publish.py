"""Jira and Confluence, written to — for what a person accepted LEKA to send.

    Jira         new issues, one per ticket accepted, in a project the source
                 reads — only on a source whose admin allowed it (`issues`)
    Confluence   new pages, one per page accepted, in a space the source
                 reads — only on a source whose admin allowed it (`pages`)

Nothing else: never an edit, never a deletion, never a comment, never a
transition. Everything goes through the connector's own client — its token,
public addresses only, the site's host built from its name — and a project
or a space outside the source's scope is refused before a byte is sent.
"""

from __future__ import annotations

from typing import Any

import httpx

from leka.connectors import atlassian
from leka.connectors.atlassian_markup import confluence_xhtml, jira_wiki
from leka.connectors.confluence.connector import ConfluenceConnector
from leka.connectors.jira.connector import JiraConnector

# What an issue's description, or a page, weighs at most when sent.
MAX_DESCRIPTION = 30_000
MAX_PAGE = 200_000
# The issue types LEKA proposes, as Jira projects usually name them — the
# first that the project has, else its first that is not a sub-task.
TYPE_NAMES: dict[str, tuple[str, ...]] = {
    "task": ("task", "tâche", "tache"),
    "bug": ("bug", "bogue", "anomalie"),
    "story": ("story", "récit", "recit", "user story"),
}


class PublishRefusedError(Exception):
    """Why Atlassian, or the source, refused: issues_off, pages_off,
    out_of_scope, not_allowed (the account cannot create there), not_found
    (no such project or space), invalid (Jira or Confluence refused the
    content, said why), title_taken (a page of that title is there),
    unavailable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _refused(response: httpx.Response, what: str) -> PublishRefusedError:
    status, body = response.status_code, response.text[:600]
    if status in (401, 403):
        return PublishRefusedError(
            "not_allowed", f"Le compte de la source ne peut pas créer {what} ici."
        )
    if status == 404:
        return PublishRefusedError("not_found", f"Atlassian ne trouve pas {what}.")
    if status == 400 and "title" in body.lower() and "exist" in body.lower():
        return PublishRefusedError("title_taken", "Une page de ce titre existe déjà dans l'espace.")
    if status == 400:
        return PublishRefusedError("invalid", f"Atlassian refuse le contenu : {body[:300]}")
    return PublishRefusedError("unavailable", f"Atlassian a répondu {status}.")


class JiraIssues:
    """One Jira source's projects — written to, when allowed, with new
    issues."""

    def __init__(self, connector: JiraConnector) -> None:
        self._connector = connector
        self._config = connector.config

    @property
    def writes(self) -> bool:
        """Whether its admin allowed LEKA to create issues."""
        return bool(getattr(self._config, "issues", False))

    @property
    def site(self) -> str:
        return atlassian.site_url(self._config.site)

    def in_scope(self, project: str) -> bool:
        listed = self._config.projects
        return listed is None or project.upper() in listed

    def _client(self) -> httpx.AsyncClient:
        said = atlassian.headers(self._connector.credentials)
        return self._connector.http(self.site, headers={**said, "Content-Type": "application/json"})

    async def _type_id(self, client: httpx.AsyncClient, project: str, kind: str) -> str:
        answer = await client.get(f"/rest/api/2/issue/createmeta/{project}/issuetypes")
        if answer.status_code != 200:
            raise _refused(answer, f"le projet {project}")
        found = answer.json()
        types: list[dict[str, Any]] = [
            t
            for t in (found.get("values") or found.get("issueTypes") or [])
            if isinstance(t, dict) and not t.get("subtask")
        ]
        if not types:
            raise PublishRefusedError("not_allowed", f"Le projet {project} n'accepte aucun ticket.")
        wanted = TYPE_NAMES.get(kind, TYPE_NAMES["task"])
        for t in types:
            if str(t.get("name") or "").strip().lower() in wanted:
                return str(t["id"])
        return str(types[0]["id"])

    async def create(
        self, project: str, *, title: str, description: str, kind: str, labels: list[str]
    ) -> dict[str, str]:
        """One issue, created — its key and its address."""
        if not self.writes:
            raise PublishRefusedError(
                "issues_off", "Cette source Jira n'autorise pas LEKA à créer des tickets."
            )
        key = project.strip().upper()
        if not self.in_scope(key):
            raise PublishRefusedError(
                "out_of_scope", f"Le projet {key} n'est pas lu par cette source."
            )
        async with self._client() as client:
            type_id = await self._type_id(client, key, kind)
            answer = await client.post(
                "/rest/api/2/issue",
                json={
                    "fields": {
                        "project": {"key": key},
                        "summary": title.strip()[:255],
                        "description": jira_wiki(description)[:MAX_DESCRIPTION],
                        "issuetype": {"id": type_id},
                        "labels": [
                            "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:50]
                            for label in dict.fromkeys(["leka", *labels])
                            if label.strip()
                        ][:10],
                    }
                },
            )
        if answer.status_code not in (200, 201):
            raise _refused(answer, f"un ticket dans {key}")
        made = answer.json()
        issue = str(made.get("key") or "")
        return {"key": issue, "url": f"{self.site}/browse/{issue}"}


class ConfluencePages:
    """One Confluence source's spaces — written to, when allowed, with new
    pages."""

    def __init__(self, connector: ConfluenceConnector) -> None:
        self._connector = connector
        self._config = connector.config

    @property
    def writes(self) -> bool:
        """Whether its admin allowed LEKA to publish pages."""
        return bool(getattr(self._config, "pages", False))

    @property
    def site(self) -> str:
        return atlassian.site_url(self._config.site)

    def in_scope(self, space: str) -> bool:
        listed = self._config.spaces
        return listed is None or space in listed

    def _client(self) -> httpx.AsyncClient:
        said = atlassian.headers(self._connector.credentials)
        return self._connector.http(
            self.site + "/wiki", headers={**said, "Content-Type": "application/json"}
        )

    async def _space_id(self, client: httpx.AsyncClient, space: str) -> str:
        answer = await client.get("/api/v2/spaces", params={"keys": space, "limit": 1})
        if answer.status_code != 200:
            raise _refused(answer, f"l'espace {space}")
        found = [s for s in answer.json().get("results") or [] if isinstance(s, dict)]
        if not found:
            raise PublishRefusedError("not_found", f"Atlassian ne trouve pas l'espace {space}.")
        return str(found[0]["id"])

    async def create(self, space: str, *, title: str, body: str) -> dict[str, str]:
        """One page, published at the space's root — its id and its address."""
        if not self.writes:
            raise PublishRefusedError(
                "pages_off", "Cette source Confluence n'autorise pas LEKA à publier des pages."
            )
        key = space.strip()
        if not self.in_scope(key):
            raise PublishRefusedError(
                "out_of_scope", f"L'espace {key} n'est pas lu par cette source."
            )
        async with self._client() as client:
            space_id = await self._space_id(client, key)
            answer = await client.post(
                "/api/v2/pages",
                json={
                    "spaceId": space_id,
                    "status": "current",
                    "title": title.strip()[:255],
                    "body": {
                        "representation": "storage",
                        "value": confluence_xhtml(body)[:MAX_PAGE],
                    },
                },
            )
        if answer.status_code not in (200, 201):
            raise _refused(answer, f"une page dans {key}")
        made = answer.json()
        links = made.get("_links") if isinstance(made.get("_links"), dict) else {}
        web = str(links.get("webui") or "")
        return {
            "id": str(made.get("id") or ""),
            "url": f"{self.site}/wiki{web}" if web else f"{self.site}/wiki/spaces/{key}",
        }


async def open_issues(connector: object) -> JiraIssues:
    """A Jira source's projects, from its connector — opened by
    SourceService.open_connector, its credentials decrypted for this use."""
    if not isinstance(connector, JiraConnector):
        raise PublishRefusedError("not_found", "Cette source n'est pas une source Jira.")
    return JiraIssues(connector)


async def open_pages(connector: object) -> ConfluencePages:
    """A Confluence source's spaces, from its connector."""
    if not isinstance(connector, ConfluenceConnector):
        raise PublishRefusedError("not_found", "Cette source n'est pas une source Confluence.")
    return ConfluencePages(connector)


__all__ = [
    "ConfluencePages",
    "JiraIssues",
    "PublishRefusedError",
    "open_issues",
    "open_pages",
]
