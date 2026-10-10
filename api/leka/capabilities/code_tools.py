"""What an agent may read of a repository's code while it runs — the
code-change agent's: a branch's files, one file's text. Read-only, through
the workspace's GitHub sources, only a repository in one's scope; offered
only to an agent that names them (`tools:`), never by default.

    list_files   the files of a repository's branch, under a path
    read_file    one file's text
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.runtime import AgentTool
from leka.capabilities.tools import Answer, Handler
from leka.connectors import CodeRefusedError, GitHubCode

# What a file gives the model, at most.
MOST_CHARS = 60_000
MOST_PATHS = 400

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
    description="The text of one file of a connected GitHub repository, on a branch.",
    parameters={
        "type": "object",
        "properties": {
            "repository": {"type": "string", "description": "Its full name: owner/repo."},
            "path": {"type": "string", "description": "The file's path in the repository."},
            "branch": {"type": "string", "description": "The branch; its default when empty."},
        },
        "required": ["repository", "path"],
    },
    permission="workspace:read",
)

CODE_TOOLS: tuple[AgentTool, ...] = (LIST_FILES, READ_FILE)
CODE_NAMES = frozenset(t.name for t in CODE_TOOLS)


def _said(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def code_handlers(session: AsyncSession, workspace_id: uuid.UUID) -> dict[str, Handler]:
    """Each code tool, bound to the workspace's GitHub sources — each opened
    once per run, its credentials decrypted for this run only."""
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
        return Answer(
            _said(
                {
                    "repository": repository,
                    "branch": branch,
                    "files": paths[:MOST_PATHS],
                    "more": more or len(paths) > MOST_PATHS,
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
        return Answer(
            _said(
                {
                    "repository": repository,
                    "branch": branch,
                    "path": path,
                    "content": text[:MOST_CHARS],
                    "truncated": len(text) > MOST_CHARS,
                }
            ),
            "ok",
        )

    return {"list_files": list_files, "read_file": read_file}


__all__ = ["CODE_NAMES", "CODE_TOOLS", "LIST_FILES", "READ_FILE", "code_handlers"]
