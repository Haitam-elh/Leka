"""What an agent may read of a repository's code while it runs — the
code-change agent's: a branch's files, one file's text; the code review's:
its pull requests, one with its diff. Read-only, through the workspace's
GitHub sources, only a repository in one's scope; offered only to an agent
that names them (`tools:`), never by default.

    list_files           the files of a repository's branch, under a path
    read_file            one file's text
    list_pull_requests   its latest pull requests
    read_pull_request    one, each file it changes with its diff — kept
                         with the run, as the agent read it: what its
                         deliverable shows its comments on (review.py)
    audit_dependencies   a lock file's or manifest's packages, parsed by the
                         server (lockfiles.py), each with its known
                         vulnerabilities (advisories.py) — the dependency
                         analysis's (2026-10-22)
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.advisories import RANK, AdvisoriesUnavailableError, lookup
from leka.capabilities.lockfiles import KNOWN, UnreadableError, parse, parser_for
from leka.capabilities.runtime import AgentTool
from leka.capabilities.tools import Answer, Handler
from leka.connectors import CodeRefusedError, GitHubCode
from leka.core.config import settings

# What a file gives the model, at most.
MOST_CHARS = 60_000
MOST_PATHS = 400
# What an audit gives the model, at most: the vulnerable packages, the
# ranges asked without an exact version.
MOST_VULNERABLE = 60
MOST_RANGES = 60

LIST_FILES = AgentTool(
    name="list_files",
    description=(
        "The files of a connected GitHub repository, on a branch (its default one when "
        "none is given), under a path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repository": {"type": "string", "description": "Its full name: owner/repo."},
            "branch": {"type": "string", "description": "The branch; its default when empty."},
            "path": {"type": "string", "description": "Only files under this path."},
        },
        "required": ["repository"],
    },
    permission="workspace:read",
)

READ_FILE = AgentTool(
    name="read_file",
    description=(
        "The text of one file of a connected GitHub repository, on a branch — with how many "
        "lines it has and whether you were given all of them. A long file is read by ranges "
        "of lines (from_line, to_line)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repository": {"type": "string", "description": "Its full name: owner/repo."},
            "path": {"type": "string", "description": "The file's path in the repository."},
            "branch": {"type": "string", "description": "The branch; its default when empty."},
            "from_line": {"type": "integer", "description": "The first line to read (1)."},
            "to_line": {"type": "integer", "description": "The last line to read (its last)."},
        },
        "required": ["repository", "path"],
    },
    permission="workspace:read",
)

LIST_PULL_REQUESTS = AgentTool(
    name="list_pull_requests",
    description=(
        "The latest pull requests of a connected GitHub repository — open, merged or "
        "closed, the latest updated first: number, title, state, author, dates."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repository": {"type": "string", "description": "Its full name: owner/repo."},
            "limit": {"type": "integer", "description": "How many, at most 30 (10)."},
        },
        "required": ["repository"],
    },
    permission="workspace:read",
)

READ_PULL_REQUEST = AgentTool(
    name="read_pull_request",
    description=(
        "One pull request of a connected GitHub repository: what it says, and each file "
        "it changes with its diff (unified, cut when very long)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repository": {"type": "string", "description": "Its full name: owner/repo."},
            "number": {"type": "integer", "description": "Its number."},
        },
        "required": ["repository", "number"],
    },
    permission="workspace:read",
)

AUDIT_DEPENDENCIES = AgentTool(
    name="audit_dependencies",
    description=(
        "The third-party packages one lock file or manifest of a connected GitHub repository "
        "names — read by the server, exact: how many, which the project asks for itself "
        "(direct), which serve development only — and, for each package from a public "
        "registry, its known vulnerabilities from the public OSV database: id, aliases (CVE), "
        "severity, the versions that fix it. Files: package-lock.json, yarn.lock, "
        "pnpm-lock.yaml, package.json, poetry.lock, uv.lock, pdm.lock, Pipfile.lock, "
        "requirements*.txt, pyproject.toml, go.mod, Cargo.lock, Gemfile.lock, composer.lock, "
        "pom.xml, packages.lock.json."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repository": {"type": "string", "description": "Its full name: owner/repo."},
            "path": {"type": "string", "description": "The lock file's or manifest's path."},
            "branch": {"type": "string", "description": "The branch; its default when empty."},
        },
        "required": ["repository", "path"],
    },
    permission="workspace:read",
)

CODE_TOOLS: tuple[AgentTool, ...] = (
    LIST_FILES,
    READ_FILE,
    LIST_PULL_REQUESTS,
    READ_PULL_REQUEST,
    AUDIT_DEPENDENCIES,
)
CODE_NAMES = frozenset(t.name for t in CODE_TOOLS)


def _said(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _line(said: object, default: int) -> int:
    try:
        return max(1, int(str(said)))
    except ValueError:
        return default


def lines_of(text: str, arguments: Mapping[str, Any]) -> dict[str, object]:
    """A file's lines as the model is given them: those asked (all by
    default), within MOST_CHARS — with how many it has, which ones it got,
    and whether that is the whole file. It never has to guess a cut."""
    lines = text.splitlines()
    total = len(lines)
    first = _line(arguments.get("from_line"), 1) if arguments.get("from_line") else 1
    last = _line(arguments.get("to_line"), total) if arguments.get("to_line") else total
    first, last = min(first, max(total, 1)), min(max(last, first), total)
    given: list[str] = []
    size = 0
    for line in lines[first - 1 : last]:
        if size + len(line) + 1 > MOST_CHARS and given:
            break
        given.append(line)
        size += len(line) + 1
    shown_to = first + len(given) - 1
    content = "\n".join(given)
    # One line longer than all a file may give (a minified file): cut too.
    cut = len(content) > MOST_CHARS
    content = content[:MOST_CHARS]
    # To its very end: as the file is, its last newline included.
    if given and not cut and shown_to >= total and text.endswith("\n"):
        content += "\n"
    return {
        "content": content,
        "lines": total,
        "from_line": first if given else 0,
        "to_line": shown_to if given else 0,
        "complete": first == 1 and shown_to >= total and not cut,
        "truncated": cut or shown_to < last,
    }


def folders_of(paths: list[str], under: str) -> dict[str, int]:
    """The folders right under `under`, each with how many of the files
    listed it holds — two levels down for a folder that holds most."""
    prefix = under.strip("/")
    prefix = f"{prefix}/" if prefix else ""
    counts: dict[str, int] = {}
    for path in paths:
        if not path.startswith(prefix):
            continue
        rest = path[len(prefix) :].split("/")
        if len(rest) > 1:
            counts[prefix + rest[0]] = counts.get(prefix + rest[0], 0) + 1
            if len(rest) > 2:
                inner = f"{prefix}{rest[0]}/{rest[1]}"
                counts[inner] = counts.get(inner, 0) + 1
    return dict(sorted(counts.items()))


def code_handlers(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    kept: dict[str, Any] | None = None,
) -> dict[str, Handler]:
    """Each code tool, bound to the workspace's GitHub sources — each opened
    once per run, its credentials decrypted for this run only. What it read
    goes into `kept`: `listed` (repository → its pulls), `pulls`
    (repository#number → the pull and its files), `files`
    (repository:path → the file's text)."""
    seen: dict[str, Any] = kept if kept is not None else {}
    # Here, not at the top: changes.py reads the catalogue, which reads the
    # registry, which reads these tools' names.
    from leka.capabilities.changes import code_for

    opened: dict[str, GitHubCode | None] = {}

    async def code(repository: str) -> GitHubCode | None:
        if repository not in opened:
            found = await code_for(session, workspace_id, repository)
            opened[repository] = found[1] if found else None
        return opened[repository]

    async def branch_of(found: GitHubCode, repository: str, asked: object) -> str:
        said = str(asked or "").strip()
        return said or await found.default_branch(repository)

    async def list_files(arguments: Mapping[str, Any]) -> Answer:
        repository = str(arguments.get("repository") or "").strip()
        found = await code(repository)
        if found is None:
            return Answer(_said({"error": "no_repository"}), "refused", "out_of_scope")
        try:
            branch = await branch_of(found, repository, arguments.get("branch"))
            paths, more = await found.paths(repository, branch, str(arguments.get("path") or ""))
        except CodeRefusedError as refused:
            return Answer(_said({"error": refused.code}), "refused", refused.code)
        cut = more or len(paths) > MOST_PATHS
        return Answer(
            _said(
                {
                    "repository": repository,
                    "branch": branch,
                    "files": paths[:MOST_PATHS],
                    "more": cut,
                    # Cut, the folders the list holds — and how many files
                    # each: never « no front end » for a list that stopped
                    # before web/ (2026-10-23). List one by its `path`.
                    **(
                        {"folders": folders_of(paths, str(arguments.get("path") or ""))}
                        if cut
                        else {}
                    ),
                }
            ),
            "ok",
        )

    async def read_file(arguments: Mapping[str, Any]) -> Answer:
        repository = str(arguments.get("repository") or "").strip()
        path = str(arguments.get("path") or "").strip()
        found = await code(repository)
        if found is None:
            return Answer(_said({"error": "no_repository"}), "refused", "out_of_scope")
        try:
            branch = await branch_of(found, repository, arguments.get("branch"))
            text = await found.read(repository, path, branch)
        except CodeRefusedError as refused:
            return Answer(_said({"error": refused.code}), "refused", refused.code)
        if text is None:
            return Answer(_said({"error": "not_found"}), "refused", "not_found")
        # What it read, kept with the run: the designer's mock-ups are drawn
        # from it (mockups.py).
        seen.setdefault("files", {})[f"{repository}:{path}"] = text
        return Answer(
            _said(
                {
                    "repository": repository,
                    "branch": branch,
                    "path": path,
                    **lines_of(text, arguments),
                }
            ),
            "ok",
        )

    async def list_pull_requests(arguments: Mapping[str, Any]) -> Answer:
        repository = str(arguments.get("repository") or "").strip()
        found = await code(repository)
        if found is None:
            return Answer(_said({"error": "no_repository"}), "refused", "out_of_scope")
        try:
            limit = int(arguments.get("limit") or 10)
        except (TypeError, ValueError):
            limit = 10
        try:
            pulls = await found.pulls(repository, limit=limit)
        except CodeRefusedError as refused:
            return Answer(_said({"error": refused.code}), "refused", refused.code)
        seen.setdefault("listed", {})[repository] = pulls
        return Answer(_said({"repository": repository, "pull_requests": pulls}), "ok")

    async def read_pull_request(arguments: Mapping[str, Any]) -> Answer:
        repository = str(arguments.get("repository") or "").strip()
        found = await code(repository)
        if found is None:
            return Answer(_said({"error": "no_repository"}), "refused", "out_of_scope")
        try:
            number = int(arguments.get("number") or 0)
        except (TypeError, ValueError):
            number = 0
        if number <= 0:
            return Answer(_said({"error": "no_number"}), "refused", "invalid_input")
        try:
            pull = await found.pull(repository, number)
        except CodeRefusedError as refused:
            return Answer(_said({"error": refused.code}), "refused", refused.code)
        seen.setdefault("pulls", {})[f"{repository}#{number}"] = {
            "repository": repository,
            **pull,
        }
        return Answer(_said({"repository": repository, **pull}), "ok")

    async def audit_dependencies(arguments: Mapping[str, Any]) -> Answer:
        repository = str(arguments.get("repository") or "").strip()
        path = str(arguments.get("path") or "").strip()
        if parser_for(path) is None:
            return Answer(
                _said({"error": "unknown_format", "known": list(KNOWN)}),
                "refused",
                "invalid_input",
            )
        found = await code(repository)
        if found is None:
            return Answer(_said({"error": "no_repository"}), "refused", "out_of_scope")
        try:
            branch = await branch_of(found, repository, arguments.get("branch"))
            text = await found.read_whole(repository, path, branch)
        except CodeRefusedError as refused:
            return Answer(_said({"error": refused.code}), "refused", refused.code)
        if text is None:
            return Answer(_said({"error": "not_found"}), "refused", "not_found")
        said = await audited(text, path)
        seen.setdefault("audits", {})[f"{repository}:{path}"] = said
        return Answer(_said({"repository": repository, "branch": branch, **said}), "ok")

    return {
        "list_files": list_files,
        "read_file": read_file,
        "list_pull_requests": list_pull_requests,
        "read_pull_request": read_pull_request,
        "audit_dependencies": audit_dependencies,
    }


async def audited(text: str, path: str, *, url: str | None = None) -> dict[str, object]:
    """One file's packages and their known vulnerabilities, as the model is
    given them: the counts, the vulnerable packages (the worst first), the
    ranges asked — and whether the vulnerabilities were checked, and why
    not."""
    try:
        parsed = parse(path, text)
    except UnreadableError as error:
        return {"path": path, "error": "unreadable", "why": str(error)[:300]}
    if parsed is None:
        return {"path": path, "error": "unknown_format", "known": list(KNOWN)}
    packages = parsed.packages
    public = [p for p in packages if p.public]
    looked = settings.advisories_url if url is None else url
    said: dict[str, object] = {
        "path": path,
        "ecosystem": parsed.ecosystem,
        "kind": parsed.kind,
        "packages": len(packages),
        "direct": sum(1 for p in packages if p.direct)
        if any(p.direct is not None for p in packages)
        else None,
        "dev_only": sum(1 for p in packages if p.dev),
        "not_public": sum(1 for p in packages if not p.public),
        "ranges": parsed.ranges[:MOST_RANGES],
        "ranges_total": len(parsed.ranges),
    }
    if not looked:
        return {**said, "checked": False, "why": "not_configured", "vulnerable": []}
    try:
        found = await lookup(((parsed.ecosystem, p.name, p.version) for p in public), url=looked)
    except AdvisoriesUnavailableError:
        return {**said, "checked": False, "why": "unavailable", "vulnerable": []}
    hit = [p for p in public if (parsed.ecosystem, p.name, p.version) in found]
    # The worst first, then those the project asks for itself.
    hit.sort(
        key=lambda p: (
            min(RANK[a.severity] for a in found[(parsed.ecosystem, p.name, p.version)]),
            not p.direct,
            p.name,
        )
    )
    vulnerable = [
        {
            "name": p.name,
            "version": p.version,
            "direct": p.direct,
            "dev_only": p.dev,
            "advisories": [a.said() for a in found[(parsed.ecosystem, p.name, p.version)]],
        }
        for p in hit
    ]
    return {
        **said,
        "checked": True,
        "source": "OSV (osv.dev)",
        "checked_packages": len(public),
        "vulnerable_total": len(vulnerable),
        "vulnerable": vulnerable[:MOST_VULNERABLE],
    }


__all__ = [
    "AUDIT_DEPENDENCIES",
    "CODE_NAMES",
    "CODE_TOOLS",
    "LIST_FILES",
    "LIST_PULL_REQUESTS",
    "READ_FILE",
    "READ_PULL_REQUEST",
    "audited",
    "code_handlers",
]
