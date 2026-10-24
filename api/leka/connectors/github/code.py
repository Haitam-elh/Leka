"""GitHub, as code — for the code changes LEKA proposes.

    read        a repository's files, on a branch: its tree (what is there)
                and one file's text — for an agent that reads the code, and
                for the « before » of a proposed change
    write       ONE thing, and only for a change a person accepted, only on
                a source whose admin allowed it (`pull_requests`): a pull
                request — a new branch from the base, one commit, the pull
                request. Never a merge, never a push to a branch that exists,
                never the default branch
    repair      asked by a person, its checks in red (2026-10-24): what
                failed read — each check, its annotations, the end of its
                log — and one more commit on the leka/ branch of the pull
                request LEKA opened, on top of where it stands, never forced;
                closed, the pull request reopened first
    follow      the pull request after, read only (2026-10-20): its checks,
                whether a person merged it, the deployment that took it, the
                version before its merge
    undo        asked by a person (2026-10-20): its pull request closed when
                it was not merged; merged, the repository's deployment
                workflow started for the version before it — on a source
                that allows it (`deploys`, `deploy_workflow`) — and that run
                followed. Undoing a merged change in the code is a pull
                request like any other (changes.py)

Everything goes through the connector's own client: its token, public
addresses only, pinned against DNS rebinding (connectors/network.py).
A repository outside the source's scope is refused before a byte is sent.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from leka.connectors.github.connector import API_VERSION, FULL_NAME, GitHubConnector

# A file LEKA reads, or writes, at most.
MAX_FILE_BYTES = 200_000
# A lock file LEKA reads whole, at most: read by the server, never given to
# a model as it is (2026-10-22: the dependency analysis).
MAX_LOCK_BYTES = 20_000_000
# The paths a tree gives back, at most.
MAX_PATHS = 2_000


class CodeRefusedError(Exception):
    """Why GitHub, or the source, refused: out_of_scope, not_found,
    not_allowed (the token cannot write), workflow_scope (a workflow file
    needs its own right), branch_exists, too_large, binary, unavailable."""

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


# A check's conclusions that fail it; the rest — success, neutral, skipped —
# pass. A commit status says failure or error.
FAILED = frozenset(
    {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale", "error"}
)
# The deployments read after a merge, at most, and those compared with it.
MAX_DEPLOYMENTS = 20
MAX_COMPARED = 4
# The checks a pull request names, at most.
MAX_CHECKS = 100
# What is read of a pull request in red (2026-10-24), at most: the checks
# that failed, the annotations of one, a log as GitHub gives it, and what of
# it is kept — where it fails, and how it ends.
MAX_FAILED_READ = 4
MAX_ANNOTATIONS = 20
MAX_LOG_BYTES = 5_000_000
MOST_LOG = 12_000
LOG_TAIL = 60
LOG_AROUND = 6
_STAMP = re.compile(r"^\ufeff?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# What a log says where it fails: GitHub's own mark, a test runner's, a
# compiler's, a stack's.
_FAILING = re.compile(
    r"##\[error\]|\bFAIL(?:ED)?\b|\bERROR\b|\berror(?:\[|:| TS\d)|Error:|AssertionError|"
    r"Traceback|\bexpected\b|\bReceived\b|✗|\u00d7|✕|E {3}",
)


def log_excerpt(text: str, *, most: int = MOST_LOG) -> str:
    """A check's log as the repair needs it: its times and colours taken
    out, the lines where it fails with a few around each — the first ones
    first — then how it ends; `[…]` where lines are left out."""
    lines = [_ANSI.sub("", _STAMP.sub("", line)).rstrip() for line in text.splitlines()]
    lines = [line for line in lines if not line.startswith(("##[group]", "##[endgroup]"))]
    wanted: set[int] = set(range(max(0, len(lines) - LOG_TAIL), len(lines)))
    budget = most
    for i, line in enumerate(lines):
        if budget <= 0:
            break
        if _FAILING.search(line):
            around = range(max(0, i - LOG_AROUND), min(len(lines), i + LOG_AROUND + 1))
            budget -= sum(len(lines[j]) + 1 for j in around if j not in wanted)
            wanted.update(around)
    said: list[str] = []
    last = -1
    for i in sorted(wanted):
        if i != last + 1:
            said.append("[…]")
        said.append(lines[i][:500])
        last = i
    out = "\n".join(said)
    # Over: what comes first — where it fails first — kept, with its end.
    return out if len(out) <= most else out[: most - 2000] + "\n[…]\n" + out[-2000:]


def checks_of(runs: Sequence[dict[str, Any]], statuses: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """A commit's checks, as one word and what makes it: each check's latest
    run (a run again replaces the first), and the commit statuses.
    `none` when nothing ran yet."""
    latest: dict[str, dict[str, Any]] = {}
    for run in runs:
        name = str(run.get("name") or "")
        if name not in latest or int(run.get("id") or 0) > int(latest[name].get("id") or 0):
            latest[name] = run
    seen: list[tuple[str, str, str]] = []
    for name, run in latest.items():
        if run.get("status") != "completed":
            state = "pending"
        else:
            state = "failure" if run.get("conclusion") in FAILED else "success"
        seen.append((name, state, str(run.get("html_url") or "")))
    for status in statuses:
        said = str(status.get("state") or "pending")
        state = "failure" if said in FAILED else "success" if said == "success" else "pending"
        seen.append((str(status.get("context") or ""), state, str(status.get("target_url") or "")))
    failed = [name for name, state, _ in seen if state == "failure"]
    pending = sum(1 for _, state, _ in seen if state == "pending")
    overall = "none" if not seen else "failure" if failed else "pending" if pending else "success"
    return {
        "state": overall,
        "total": len(seen),
        "passed": sum(1 for _, state, _ in seen if state == "success"),
        "pending": pending,
        "failed": failed[:10],
        "failed_url": next((url for name, state, url in seen if state == "failure" and url), None),
    }


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


def _message(response: httpx.Response) -> str:
    """What GitHub said, when it said it in JSON."""
    try:
        found = response.json()
    except ValueError:
        return ""
    return str(found.get("message") or "")[:300] if isinstance(found, dict) else ""


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

    @property
    def deploy_workflow(self) -> str | None:
        """The workflow that deploys a version, when its admin allowed LEKA
        to start it for the version before a change (`deploys`)."""
        if not getattr(self._config, "deploys", False):
            return None
        return getattr(self._config, "deploy_workflow", None) or None

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
        if status in (403, 404, 422) and "workflow" in response.text.lower():
            # A classic token without `workflow`, an app without Workflows.
            return CodeRefusedError(
                "workflow_scope",
                "Ce changement touche .github/workflows : la clé GitHub de cette source doit "
                "aussi avoir le droit Workflows en écriture.",
            )
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

    async def head(self, repository: str, branch: str) -> str:
        """The commit a branch stands at."""
        async with self._client() as client:
            answer = await client.get(f"/repos/{self._checked(repository)}/git/ref/heads/{branch}")
        if answer.status_code != 200:
            raise self._refused(answer, f"la branche {branch}")
        return str(answer.json()["object"]["sha"])

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

    async def read_whole(
        self, repository: str, path: str, ref: str, *, most: int = MAX_LOCK_BYTES
    ) -> str | None:
        """A file's text however long, up to `most` bytes — a lock file the
        server parses itself (2026-10-22) — None when it is not there."""
        async with (
            self._client() as client,
            client.stream(
                "GET",
                f"/repos/{self._checked(repository)}/contents/{path}",
                params={"ref": ref},
                headers={"Accept": "application/vnd.github.raw"},
            ) as answer,
        ):
            if answer.status_code == 404:
                return None
            if answer.status_code != 200:
                await answer.aread()
                raise self._refused(answer, path)
            body = bytearray()
            async for chunk in answer.aiter_bytes():
                body += chunk
                if len(body) > most:
                    raise CodeRefusedError("too_large", f"{path} est trop gros pour être lu ici.")
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CodeRefusedError("binary", f"{path} n'est pas un fichier texte.") from error

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
            meta = head.json()
            # Its CI, as its head stands (2026-10-21): what a review or an
            # acceptance reads beside the diff — never taken for a proof of
            # behaviour.
            sha = str((meta.get("head") or {}).get("sha") or "")
            checks = await self._checks(client, name, sha) if sha else None
        if listed.status_code != 200:
            raise self._refused(listed, f"les fichiers de la pull request #{number}")
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
            "checks": checks,
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
        parent: str | None = None,
    ) -> PullRequest:
        """A new branch from `base` — at `parent`, the commit its files were
        read at, else where it stands — one commit with `changes`, its pull
        request. Refused when the source does not allow it. A branch that
        exists is never overwritten: the pull request already open from it
        is the one (a try whose answer was lost), else the next name
        (2026-10-20)."""
        if not self.writes:
            raise CodeRefusedError(
                "pull_requests_off",
                "Cette source GitHub n'autorise pas LEKA à ouvrir des pull requests.",
            )
        name = self._checked(repository)
        if branch == base or not branch.startswith("leka/"):
            raise CodeRefusedError("branch_exists", "LEKA n'écrit que sur une branche leka/ neuve.")
        async with self._client() as client:
            opened = await client.get(
                f"/repos/{name}/pulls", params={"state": "open", "base": base, "per_page": 100}
            )
            if opened.status_code != 200:
                raise self._refused(opened, f"les pull requests de {repository}")
            for each in opened.json():
                head_ref = str(((each or {}).get("head") or {}).get("ref") or "")
                if head_ref == branch or head_ref.startswith(f"{branch}-"):
                    sha = str((each.get("head") or {}).get("sha") or "")
                    return PullRequest(int(each["number"]), str(each["html_url"]), head_ref, sha)
            if parent is None:
                head = await client.get(f"/repos/{name}/git/ref/heads/{base}")
                if head.status_code != 200:
                    raise self._refused(head, f"la branche {base}")
                parent = str(head.json()["object"]["sha"])
            sha = await self._commit(client, name, parent, changes, title)
            # Its name, else the next: one a try left without a pull request.
            for name_tried in [branch, *(f"{branch}-{n}" for n in range(2, 6))]:
                ref = await client.post(
                    f"/repos/{name}/git/refs", json={"ref": f"refs/heads/{name_tried}", "sha": sha}
                )
                if ref.status_code == 201:
                    branch = name_tried
                    break
                refused = self._refused(ref, f"la branche {name_tried}")
                if refused.code != "branch_exists":
                    raise refused
            else:
                raise CodeRefusedError("branch_exists", f"Les branches {branch}… existent déjà.")
            pull = await client.post(
                f"/repos/{name}/pulls",
                json={"title": title, "head": branch, "base": base, "body": body},
            )
            if pull.status_code != 201:
                raise self._refused(pull, "la pull request")
        made_pull = pull.json()
        return PullRequest(int(made_pull["number"]), str(made_pull["html_url"]), branch, sha)

    async def _commit(
        self,
        client: httpx.AsyncClient,
        name: str,
        parent: str,
        changes: Sequence[FileChange],
        message: str,
    ) -> str:
        """One commit of `changes` on top of `parent` — no branch moved."""
        commit = await client.get(f"/repos/{name}/git/commits/{parent}")
        if commit.status_code != 200:
            raise self._refused(commit, f"le commit {parent[:7]}")
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
            json={"message": message, "tree": tree.json()["sha"], "parents": [parent]},
        )
        if made.status_code != 201:
            raise self._refused(made, "le commit")
        return str(made.json()["sha"])

    # ── a pull request in red: what failed, its repair (2026-10-24) ─────────

    async def failures(self, repository: str, sha: str) -> list[dict[str, Any]]:
        """What failed on a commit, as its checks say it, read only: each
        failed check's name, where to see it, its summary, its annotations —
        file, line, message — and its log as it ends (GitHub Actions); a
        commit status in failure, what it says. Nothing failed: []."""
        name = self._checked(repository)
        found: list[dict[str, Any]] = []
        async with self._client() as client:
            runs = await client.get(
                f"/repos/{name}/commits/{sha}/check-runs", params={"per_page": MAX_CHECKS}
            )
            latest: dict[str, dict[str, Any]] = {}
            for run in (runs.json().get("check_runs") or []) if runs.status_code == 200 else []:
                check = str(run.get("name") or "")
                newer = int(run.get("id") or 0) > int((latest.get(check) or {}).get("id") or 0)
                if check not in latest or newer:
                    latest[check] = run
            failed = [
                run
                for run in latest.values()
                if run.get("status") == "completed" and run.get("conclusion") in FAILED
            ]
            for run in failed[:MAX_FAILED_READ]:
                output = run.get("output") or {}
                summary = " — ".join(
                    str(part) for part in (output.get("title"), output.get("summary")) if part
                )
                entry: dict[str, Any] = {
                    "name": str(run.get("name") or ""),
                    "url": run.get("html_url"),
                    "conclusion": run.get("conclusion"),
                    "summary": summary[:2000],
                    "annotations": [],
                    "log": "",
                }
                notes = await client.get(
                    f"/repos/{name}/check-runs/{run['id']}/annotations", params={"per_page": 50}
                )
                if notes.status_code == 200:
                    entry["annotations"] = [
                        {
                            "path": str(note.get("path") or ""),
                            "line": note.get("start_line"),
                            "title": str(note.get("title") or "")[:300],
                            "message": str(note.get("message") or "")[:2000],
                        }
                        for note in notes.json()
                        if isinstance(note, dict) and note.get("annotation_level") == "failure"
                    ][:MAX_ANNOTATIONS]
                if ((run.get("app") or {}).get("slug") or "github-actions") == "github-actions":
                    entry["log"] = log_excerpt(await self._log(client, name, int(run["id"])))
                found.append(entry)
            statuses = await client.get(f"/repos/{name}/commits/{sha}/status")
            listed = (statuses.json().get("statuses") or []) if statuses.status_code == 200 else []
            for status in listed:
                if str(status.get("state") or "") in FAILED:
                    found.append(
                        {
                            "name": str(status.get("context") or ""),
                            "url": status.get("target_url"),
                            "conclusion": status.get("state"),
                            "summary": str(status.get("description") or "")[:2000],
                            "annotations": [],
                            "log": "",
                        }
                    )
        return found

    async def _log(self, client: httpx.AsyncClient, name: str, job: int) -> str:
        """A GitHub Actions job's log, as text — "" when it cannot be read
        (a token without Actions read, a log gone)."""
        answer = await client.get(f"/repos/{name}/actions/jobs/{job}/logs")
        if answer.status_code == 200:
            return answer.text[-MAX_LOG_BYTES:]
        location = answer.headers.get("location")
        if answer.status_code not in (301, 302, 303, 307, 308) or not location:
            return ""
        where = urlsplit(location)
        if where.scheme != "https" or not where.netloc:
            return ""
        # A signed address of GitHub's storage: no token sent there.
        async with self._connector.http(f"https://{where.netloc}") as storage:
            path = where.path + (f"?{where.query}" if where.query else "")
            got = await storage.get(path)
        return got.text[-MAX_LOG_BYTES:] if got.status_code == 200 else ""

    async def push_commit(
        self,
        repository: str,
        *,
        branch: str,
        parent: str,
        changes: Sequence[FileChange],
        message: str,
    ) -> str:
        """One commit on the leka/ branch of a pull request LEKA opened — its
        repair, a person asked for it — on top of where it stands
        (`parent`): fast-forward only, never forced, never another branch.
        Moved since — someone pushed — refused: `moved`."""
        if not self.writes:
            raise CodeRefusedError(
                "pull_requests_off",
                "Cette source GitHub n'autorise pas LEKA à écrire sur ses pull requests.",
            )
        name = self._checked(repository)
        if not branch.startswith("leka/"):
            raise CodeRefusedError(
                "not_leka_branch", "LEKA n'écrit que sur les branches leka/ qu'il a ouvertes."
            )
        async with self._client() as client:
            sha = await self._commit(client, name, parent, changes, message)
            moved = await client.patch(
                f"/repos/{name}/git/refs/heads/{branch}", json={"sha": sha, "force": False}
            )
            if moved.status_code == 422:
                raise CodeRefusedError(
                    "moved",
                    f"La branche {branch} a bougé pendant la réparation : relancez-la, LEKA "
                    "repartira de là où elle est.",
                )
            if moved.status_code != 200:
                raise self._refused(moved, f"la branche {branch}")
        return sha

    async def parent_of(self, repository: str, sha: str) -> str | None:
        """The commit a commit was made on — None when GitHub cannot say."""
        async with self._client() as client:
            answer = await client.get(f"/repos/{self._checked(repository)}/git/commits/{sha}")
        if answer.status_code != 200:
            return None
        parents = answer.json().get("parents") or []
        return str(parents[0].get("sha") or "") or None if parents else None

    async def reopen_pull_request(self, repository: str, number: int) -> None:
        """A pull request LEKA opened and a person closed in red, reopened to
        be repaired (2026-10-24)."""
        if not self.writes:
            raise CodeRefusedError(
                "pull_requests_off",
                "Cette source GitHub n'autorise pas LEKA à toucher aux pull requests.",
            )
        async with self._client() as client:
            answer = await client.patch(
                f"/repos/{self._checked(repository)}/pulls/{number}", json={"state": "open"}
            )
        if answer.status_code == 422:
            raise CodeRefusedError(
                "cannot_reopen",
                f"GitHub refuse de rouvrir la pull request #{number} : {_message(answer)} — sa "
                "branche a peut-être été supprimée.",
            )
        if answer.status_code != 200:
            raise self._refused(answer, f"la pull request #{number}")

    # ── after, read only: its checks, its merge, its deployment (2026-10-20) ─

    async def follow(self, repository: str, number: int) -> dict[str, Any]:
        """Where a pull request stands: open, merged or closed; its checks
        while open; merged, the latest deployment that took its merge — any
        environment, production first."""
        name = self._checked(repository)
        async with self._client() as client:
            pull = await client.get(f"/repos/{name}/pulls/{number}")
            if pull.status_code != 200:
                raise self._refused(pull, f"la pull request #{number}")
            meta = pull.json()
            merged_at = meta.get("merged_at")
            head_sha = str((meta.get("head") or {}).get("sha") or "")
            seen: dict[str, Any] = {
                "state": "merged" if merged_at else str(meta.get("state") or "open"),
                "head_sha": head_sha,
                "mergeable": meta.get("mergeable"),
                "mergeable_state": meta.get("mergeable_state"),
                "merged_at": merged_at,
                "merge_sha": meta.get("merge_commit_sha") if merged_at else None,
                "checks": None,
                "deployment": None,
            }
            if seen["state"] == "open" and head_sha:
                seen["checks"] = await self._checks(client, name, head_sha)
            if merged_at and seen["merge_sha"]:
                seen["deployment"] = await self._deployment(
                    client, name, str(seen["merge_sha"]), str(merged_at)
                )
                # The version before it: what going back deploys.
                merged = await client.get(f"/repos/{name}/commits/{seen['merge_sha']}")
                if merged.status_code == 200:
                    parents = merged.json().get("parents") or []
                    seen["before_sha"] = str(parents[0].get("sha") or "") if parents else None
                # What its branch took since: what going back takes out too.
                base = str((meta.get("base") or {}).get("ref") or "")
                if base:
                    since = await client.get(f"/repos/{name}/compare/{seen['merge_sha']}...{base}")
                    if since.status_code == 200:
                        seen["newer"] = int(since.json().get("ahead_by") or 0)
        return seen

    async def close_pull_request(self, repository: str, number: int) -> None:
        """A pull request LEKA opened, closed unmerged — a person asked to
        undo it before it was merged."""
        if not self.writes:
            raise CodeRefusedError(
                "pull_requests_off",
                "Cette source GitHub n'autorise pas LEKA à toucher aux pull requests.",
            )
        async with self._client() as client:
            answer = await client.patch(
                f"/repos/{self._checked(repository)}/pulls/{number}", json={"state": "closed"}
            )
        if answer.status_code != 200:
            raise self._refused(answer, f"la pull request #{number}")

    async def redeploy(self, repository: str, *, ref: str, version: str) -> None:
        """The repository's deployment workflow started for `version` — the
        version before a change, a person asked to go back to it. Refused
        when the source does not allow it or names no workflow."""
        workflow = self.deploy_workflow
        if workflow is None:
            raise CodeRefusedError(
                "deploys_off",
                "Cette source GitHub n'autorise pas LEKA à relancer un déploiement : son admin "
                "l'active et nomme le workflow de déploiement.",
            )
        field = str(getattr(self._config, "deploy_input", None) or "release")
        async with self._client() as client:
            answer = await client.post(
                f"/repos/{self._checked(repository)}/actions/workflows/{workflow}/dispatches",
                json={"ref": ref, "inputs": {field: version}},
            )
        if answer.status_code == 204:
            return
        if answer.status_code == 422:
            raise CodeRefusedError(
                "deploy_refused",
                f"GitHub refuse de lancer {workflow} : {_message(answer)} — il doit accepter "
                f"l'entrée « {field} » (workflow_dispatch).",
            )
        raise self._refused(answer, f"le workflow {workflow}")

    async def redeployed(self, repository: str, since: str) -> dict[str, Any] | None:
        """The run of the deployment workflow LEKA started at `since`: its
        state — queued, in_progress, success, failure — and where to read it.
        None until GitHub lists it."""
        workflow = self.deploy_workflow
        if workflow is None:
            return None
        async with self._client() as client:
            answer = await client.get(
                f"/repos/{self._checked(repository)}/actions/workflows/{workflow}/runs",
                params={"event": "workflow_dispatch", "per_page": 20},
            )
        if answer.status_code != 200:
            return None
        runs = [
            r
            for r in answer.json().get("workflow_runs") or []
            if isinstance(r, dict) and str(r.get("created_at") or "") >= since[:19]
        ]
        if not runs:
            return None
        run = min(runs, key=lambda r: str(r.get("created_at") or ""))
        if run.get("status") != "completed":
            state = "in_progress" if run.get("status") == "in_progress" else "queued"
        else:
            state = "success" if run.get("conclusion") == "success" else "failure"
        return {"state": state, "url": run.get("html_url"), "at": run.get("updated_at")}

    async def _checks(self, client: httpx.AsyncClient, name: str, sha: str) -> dict[str, Any]:
        runs = await client.get(
            f"/repos/{name}/commits/{sha}/check-runs", params={"per_page": MAX_CHECKS}
        )
        statuses = await client.get(f"/repos/{name}/commits/{sha}/status")
        if runs.status_code != 200 and statuses.status_code != 200:
            return {"state": "unreadable", "total": 0, "passed": 0, "pending": 0, "failed": []}
        found = (runs.json().get("check_runs") or []) if runs.status_code == 200 else []
        said = (statuses.json().get("statuses") or []) if statuses.status_code == 200 else []
        return checks_of(found, said)

    async def _deployment(
        self, client: httpx.AsyncClient, name: str, merge_sha: str, merged_at: str
    ) -> dict[str, Any] | None:
        """The latest deployment made since the merge whose commit holds it
        — production's first — and how it went."""
        listed = await client.get(
            f"/repos/{name}/deployments", params={"per_page": MAX_DEPLOYMENTS}
        )
        if listed.status_code != 200:
            return None
        since = [
            d
            for d in listed.json()
            if isinstance(d, dict) and str(d.get("created_at")) >= merged_at
        ]
        since.sort(key=lambda d: "prod" not in str(d.get("environment") or "").lower())
        for deployment in since[:MAX_COMPARED]:
            sha = str(deployment.get("sha") or "")
            if sha != merge_sha:
                compared = await client.get(f"/repos/{name}/compare/{merge_sha}...{sha}")
                if compared.status_code != 200 or compared.json().get("status") not in (
                    "ahead",
                    "identical",
                ):
                    continue
            statuses = await client.get(
                f"/repos/{name}/deployments/{deployment['id']}/statuses", params={"per_page": 1}
            )
            latest = statuses.json()[0] if statuses.status_code == 200 and statuses.json() else {}
            return {
                "environment": str(deployment.get("environment") or ""),
                "state": str(latest.get("state") or "pending"),
                "url": latest.get("environment_url") or latest.get("log_url") or None,
                "at": latest.get("created_at") or deployment.get("created_at"),
            }
        return None


async def open_code(connector: object) -> GitHubCode:
    """A GitHub source's code, from its connector — opened by
    SourceService.open_connector, its credentials decrypted for this use."""
    if not isinstance(connector, GitHubConnector):
        raise CodeRefusedError("not_found", "Cette source n'est pas une source GitHub.")
    return GitHubCode(connector)


__all__ = [
    "CodeRefusedError",
    "FileChange",
    "GitHubCode",
    "PullRequest",
    "checks_of",
    "log_excerpt",
    "open_code",
]
