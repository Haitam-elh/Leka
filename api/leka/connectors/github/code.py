"""GitHub, as code — for the code changes LEKA proposes.

    read        a repository's files, on a branch: its tree (what is there)
                and one file's text — for an agent that reads the code, and
                for the « before » of a proposed change
    write       ONE thing, and only for a change a person accepted, only on
                a source whose admin allowed it (`pull_requests`): a pull
                request — a new branch from the base, one commit, the pull
                request. Never a merge, never a push to a branch that exists,
                never the default branch.

Everything goes through the connector's own client: its token, public
addresses only, pinned against DNS rebinding (connectors/network.py).
A repository outside the source's scope is refused before a byte is sent.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from leka.connectors.github.connector import API_VERSION, FULL_NAME, GitHubConnector

# A file LEKA reads, or writes, at most.
MAX_FILE_BYTES = 200_000
# The paths a tree gives back, at most.
MAX_PATHS = 2_000


class CodeRefusedError(Exception):
    """Why GitHub, or the source, refused: out_of_scope, not_found,
    not_allowed (the token cannot write), branch_exists, too_large,
    binary, unavailable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FileChange:
    """What a commit does to one file: its new text — None removes it."""

    path: str
    content: str | None


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    branch: str
    commit: str


# Read of its pull requests, at most: how many listed, how many files of
# one, how much of a file's diff, how much in all, how much of what it says.
MAX_PULLS = 30
MAX_PULL_FILES = 100
MAX_PATCH_CHARS = 20_000
MAX_PULL_CHARS = 120_000
MAX_BODY = 4_000


def _pull_brief(found: dict[str, Any]) -> dict[str, object]:
    user = found.get("user")
    return {
        "number": int(found.get("number") or 0),
        "title": str(found.get("title") or ""),
        "state": str(found.get("state") or ""),
        "merged": bool(found.get("merged_at")),
        "draft": bool(found.get("draft")),
        "author": str(user.get("login") or "") if isinstance(user, dict) else "",
        "url": str(found.get("html_url") or ""),
        "created_at": found.get("created_at"),
        "updated_at": found.get("updated_at"),
        "merged_at": found.get("merged_at"),
    }


class GitHubCode:
    """One GitHub source's code, read — and, when allowed, proposed back as
    a pull request."""

    def __init__(self, connector: GitHubConnector) -> None:
        self._connector = connector
        self._config = connector.config

    # ── scope ────────────────────────────────────────────────────────────────

    def in_scope(self, repository: str) -> bool:
        """A full name the source may read: its list when it has one, its
        organisation's otherwise."""
        if not FULL_NAME.match(repository):
            return False
        listed = self._config.repositories
        if listed is not None:
            return repository.lower() in {name.lower() for name in listed}
        organisation = self._config.organization
        return organisation is None or repository.split("/")[0].lower() == organisation.lower()

    @property
    def writes(self) -> bool:
        """Whether its admin allowed LEKA to open pull requests here."""
        return bool(getattr(self._config, "pull_requests", False))

    def _checked(self, repository: str) -> str:
        if not self.in_scope(repository):
            raise CodeRefusedError(
                "out_of_scope", f"{repository} n'est pas dans le périmètre de cette source GitHub."
            )
        return repository

    def _client(self) -> httpx.AsyncClient:
        secret = self._connector.credentials.token.get_secret_value()
        return self._connector.http(
            str(self._config.base_url).rstrip("/"),
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "LEKA",
                "Authorization": f"Bearer {secret}",
            },
        )

    @staticmethod
    def _refused(response: httpx.Response, what: str) -> CodeRefusedError:
        status = response.status_code
        if status == 404:
            return CodeRefusedError("not_found", f"GitHub ne trouve pas {what}.")
        if status in (401, 403):
            return CodeRefusedError(
                "not_allowed",
                "La clé GitHub de cette source ne permet pas cette opération : donnez-lui "
                "Contents et Pull requests en écriture sur ce dépôt.",
            )
        if status == 422 and "reference already exists" in response.text.lower():
            return CodeRefusedError("branch_exists", "Cette branche existe déjà sur GitHub.")
        return CodeRefusedError("unavailable", f"GitHub a répondu {status} pour {what}.")

    # ── reading ──────────────────────────────────────────────────────────────

    async def default_branch(self, repository: str) -> str:
        async with self._client() as client:
            answer = await client.get(f"/repos/{self._checked(repository)}")
        if answer.status_code != 200:
            raise self._refused(answer, repository)
        return str(answer.json().get("default_branch") or "main")

    async def paths(self, repository: str, ref: str, prefix: str = "") -> tuple[list[str], bool]:
        """The files of a branch, under `prefix` — and whether there were
        more than MAX_PATHS."""
        async with self._client() as client:
            answer = await client.get(
                f"/repos/{self._checked(repository)}/git/trees/{ref}", params={"recursive": "1"}
            )
        if answer.status_code != 200:
            raise self._refused(answer, f"la branche {ref} de {repository}")
        listing = answer.json()
        found = [
            str(entry["path"])
            for entry in listing.get("tree") or []
            if entry.get("type") == "blob" and str(entry.get("path", "")).startswith(prefix)
        ]
        return found[:MAX_PATHS], len(found) > MAX_PATHS or bool(listing.get("truncated"))

    async def read(self, repository: str, path: str, ref: str) -> str | None:
        """A file's text on a branch — None when it is not there."""
        async with self._client() as client:
            answer = await client.get(
                f"/repos/{self._checked(repository)}/contents/{path}", params={"ref": ref}
            )
        if answer.status_code == 404:
            return None
        if answer.status_code != 200:
            raise self._refused(answer, path)
        found = answer.json()
        if not isinstance(found, dict) or found.get("type") != "file":
            raise CodeRefusedError("not_found", f"{path} n'est pas un fichier.")
        if int(found.get("size") or 0) > MAX_FILE_BYTES:
            raise CodeRefusedError("too_large", f"{path} est trop gros pour être lu ici.")
        try:
            return base64.b64decode(str(found.get("content") or "")).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise CodeRefusedError("binary", f"{path} n'est pas un fichier texte.") from error

    async def read_bytes(
        self, repository: str, path: str, ref: str, *, most: int = MAX_FILE_BYTES
    ) -> bytes | None:
        """A file's bytes on a branch — an image a mock-up shows as the app
        does (2026-10-19) — None when it is not there or weighs over `most`."""
        async with self._client() as client:
            answer = await client.get(
                f"/repos/{self._checked(repository)}/contents/{path}", params={"ref": ref}
            )
        if answer.status_code == 404:
            return None
        if answer.status_code != 200:
            raise self._refused(answer, path)
        found = answer.json()
        if not isinstance(found, dict) or found.get("type") != "file":
            return None
        if int(found.get("size") or 0) > most:
            return None
        try:
            return base64.b64decode(str(found.get("content") or ""))
        except ValueError:
            return None

    # ── its pull requests, read (2026-10-14: the code review's deliverable) ──

    async def pulls(self, repository: str, *, limit: int = 10) -> list[dict[str, object]]:
        """Its latest pull requests, the latest updated first — open, merged
        or closed."""
        async with self._client() as client:
            answer = await client.get(
                f"/repos/{self._checked(repository)}/pulls",
                params={
                    "state": "all",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": max(1, min(limit, MAX_PULLS)),
                },
            )
        if answer.status_code != 200:
            raise self._refused(answer, f"les pull requests de {repository}")
        found = answer.json()
        return [_pull_brief(each) for each in found if isinstance(each, dict)]

    async def pull(self, repository: str, number: int) -> dict[str, object]:
        """One pull request: what it says, and each file it changes with its
        diff — cut to what a reader can take."""
        name = self._checked(repository)
        async with self._client() as client:
            head = await client.get(f"/repos/{name}/pulls/{number}")
            if head.status_code != 200:
                raise self._refused(head, f"la pull request #{number} de {repository}")
            listed = await client.get(
                f"/repos/{name}/pulls/{number}/files", params={"per_page": MAX_PULL_FILES}
            )
        if listed.status_code != 200:
            raise self._refused(listed, f"les fichiers de la pull request #{number}")
        meta = head.json()
        files: list[dict[str, object]] = []
        room = MAX_PULL_CHARS
        for each in listed.json():
            if not isinstance(each, dict):
                continue
            patch = str(each.get("patch") or "")
            kept = patch[: max(0, min(MAX_PATCH_CHARS, room))]
            room -= len(kept)
            files.append(
                {
                    "path": str(each.get("filename") or ""),
                    "status": str(each.get("status") or "modified"),
                    "additions": int(each.get("additions") or 0),
                    "deletions": int(each.get("deletions") or 0),
                    "patch": kept,
                    "truncated": len(kept) < len(patch),
                }
            )
        return {
            **_pull_brief(meta),
            "body": str(meta.get("body") or "")[:MAX_BODY],
            "base": str((meta.get("base") or {}).get("ref") or ""),
            "head": str((meta.get("head") or {}).get("ref") or ""),
            "additions": int(meta.get("additions") or 0),
            "deletions": int(meta.get("deletions") or 0),
            "changed_files": int(meta.get("changed_files") or len(files)),
            "files": files,
        }

    # ── the one write: a pull request ────────────────────────────────────────

    async def open_pull_request(
        self,
        repository: str,
        *,
        base: str,
        branch: str,
        title: str,
        body: str,
        changes: Sequence[FileChange],
    ) -> PullRequest:
        """A new branch from `base`, one commit with `changes`, its pull
        request. Refused when the source does not allow it — and GitHub
        refuses a branch that exists: nothing is ever overwritten."""
        if not self.writes:
            raise CodeRefusedError(
                "pull_requests_off",
                "Cette source GitHub n'autorise pas LEKA à ouvrir des pull requests.",
            )
        name = self._checked(repository)
        if branch == base or not branch.startswith("leka/"):
            raise CodeRefusedError("branch_exists", "LEKA n'écrit que sur une branche leka/ neuve.")
        async with self._client() as client:
            head = await client.get(f"/repos/{name}/git/ref/heads/{base}")
            if head.status_code != 200:
                raise self._refused(head, f"la branche {base}")
            parent = str(head.json()["object"]["sha"])
            commit = await client.get(f"/repos/{name}/git/commits/{parent}")
            if commit.status_code != 200:
                raise self._refused(commit, f"le dernier commit de {base}")
            tree_entries: list[dict[str, object]] = []
            for change in changes:
                entry: dict[str, object] = {"path": change.path, "mode": "100644", "type": "blob"}
                if change.content is None:
                    entry["sha"] = None
                else:
                    if len(change.content.encode()) > MAX_FILE_BYTES:
                        raise CodeRefusedError("too_large", f"{change.path} est trop gros.")
                    entry["content"] = change.content
                tree_entries.append(entry)
            tree = await client.post(
                f"/repos/{name}/git/trees",
                json={"base_tree": commit.json()["tree"]["sha"], "tree": tree_entries},
            )
            if tree.status_code != 201:
                raise self._refused(tree, "l'arbre du commit")
            made = await client.post(
                f"/repos/{name}/git/commits",
                json={"message": title, "tree": tree.json()["sha"], "parents": [parent]},
            )
            if made.status_code != 201:
                raise self._refused(made, "le commit")
            sha = str(made.json()["sha"])
            ref = await client.post(
                f"/repos/{name}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha}
            )
            if ref.status_code != 201:
                raise self._refused(ref, f"la branche {branch}")
            pull = await client.post(
                f"/repos/{name}/pulls",
                json={"title": title, "head": branch, "base": base, "body": body},
            )
            if pull.status_code != 201:
                raise self._refused(pull, "la pull request")
        opened = pull.json()
        return PullRequest(int(opened["number"]), str(opened["html_url"]), branch, sha)


async def open_code(connector: object) -> GitHubCode:
    """A GitHub source's code, from its connector — opened by
    SourceService.open_connector, its credentials decrypted for this use."""
    if not isinstance(connector, GitHubConnector):
        raise CodeRefusedError("not_found", "Cette source n'est pas une source GitHub.")
    return GitHubCode(connector)


__all__ = ["CodeRefusedError", "FileChange", "GitHubCode", "PullRequest", "open_code"]
