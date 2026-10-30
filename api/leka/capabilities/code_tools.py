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
    search_code          a regular expression through every file of a branch

The code-change agent's workshop (workshop.py, 2026-10-30): it makes its
change itself in a draft LEKA keeps — never the repository, a person
decides on the change:

    edit_file            a text replaced, answered with the lines around it
    insert_lines         lines added after a line
    write_file           a whole file, new or rewritten
    delete_file, undo_edit
    show_changes         the draft's diff
    check_changes        what LEKA checks before a person sees the change
    plan                 the steps of a large change, each todo, doing, done
    think                its reasoning, written down
    ask_expert           a stronger model's advice on a hard point
"""

from __future__ import annotations

import json
import re
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
# A stronger model asked for advice, per run at most (ask_expert).
MOST_EXPERTS = 3
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
            "pattern": {
                "type": "string",
                "description": "Only files matching this glob: `*.tsx`, `web/**/*.ts`, "
                "`**/test_*.py`, `*.{ts,tsx}`.",
            },
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
        "of lines (from_line, to_line). To find where a text is in a file, however long (a "
        "label in a dictionary, a function's name), give `find`: the lines that hold it, "
        "with their numbers — then read around them. A label is found best by the words "
        "people see on the screen."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repository": {"type": "string", "description": "Its full name: owner/repo."},
            "path": {"type": "string", "description": "The file's path in the repository."},
            "branch": {"type": "string", "description": "The branch; its default when empty."},
            "from_line": {"type": "integer", "description": "The first line to read (1)."},
            "to_line": {"type": "integer", "description": "The last line to read (its last)."},
            "find": {
                "type": "string",
                "description": "A text to look for: the lines that hold it, not the file.",
            },
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

_REPOSITORY = {"type": "string", "description": "Its full name: owner/repo."}
_PATH = {"type": "string", "description": "The file's path in the repository."}

SEARCH_CODE = AgentTool(
    name="search_code",
    description=(
        "Search a regular expression through every file of a connected GitHub repository's "
        "branch (your draft's text where you changed it): the lines that match, each with its "
        "path and number. Narrow it with `path` (a folder) and `include` (a glob: `*.tsx`, "
        "`**/test_*.py`, `*.{ts,tsx}`); `literal: true` searches the text as written. Find "
        "where a name is defined and every place it is used before you change it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repository": _REPOSITORY,
            "pattern": {"type": "string", "description": "A regular expression (Python)."},
            "path": {"type": "string", "description": "Only under this folder."},
            "include": {"type": "string", "description": "Only files matching this glob."},
            "literal": {"type": "boolean", "description": "The pattern as written (false)."},
            "ignore_case": {"type": "boolean", "description": "Case aside (false)."},
            "branch": {"type": "string", "description": "The branch; its default when empty."},
        },
        "required": ["repository", "pattern"],
    },
    permission="workspace:read",
)

EDIT_FILE = AgentTool(
    name="edit_file",
    description=(
        "Change a file in LEKA's draft of your change — never the repository: a person "
        "decides on the change. `old_text`: whole lines copied exactly as read_file gave them, "
        "enough of them to be in the file once; `new_text`: what replaces them. The answer "
        "shows the lines around the edit with their numbers, and says when the file no longer "
        "parses: check them. To replace a text each time it is in the file, give "
        "`expected_replacements`, how many times it is there. Several edits of one file: one "
        "call each, from the top of the file down."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repository": _REPOSITORY,
            "path": _PATH,
            "old_text": {"type": "string", "description": "The exact lines to replace."},
            "new_text": {"type": "string", "description": "What replaces them; empty: removed."},
            "expected_replacements": {
                "type": "integer",
                "description": "How many times old_text is in the file (1).",
            },
        },
        "required": ["repository", "path", "old_text", "new_text"],
    },
    permission="workspace:read",
)

INSERT_LINES = AgentTool(
    name="insert_lines",
    description="Add lines to a file of the draft, after a line number (0: at its top).",
    parameters={
        "type": "object",
        "properties": {
            "repository": _REPOSITORY,
            "path": _PATH,
            "after_line": {"type": "integer", "description": "The line they follow (0: the top)."},
            "text": {"type": "string", "description": "The lines added."},
        },
        "required": ["repository", "path", "after_line", "text"],
    },
    permission="workspace:read",
)

WRITE_FILE = AgentTool(
    name="write_file",
    description=(
        "Write a whole file in the draft: a new one, or one you rewrite through most of its "
        "lines (a screen redesigned). Every line of it, never « … » or a comment standing for "
        "code you keep: for a few changes, use edit_file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repository": _REPOSITORY,
            "path": _PATH,
            "content": {"type": "string", "description": "The whole file."},
        },
        "required": ["repository", "path", "content"],
    },
    permission="workspace:read",
)

DELETE_FILE = AgentTool(
    name="delete_file",
    description="Remove a file in the draft, when the change takes it away.",
    parameters={
        "type": "object",
        "properties": {"repository": _REPOSITORY, "path": _PATH},
        "required": ["repository", "path"],
    },
    permission="workspace:read",
)

UNDO_EDIT = AgentTool(
    name="undo_edit",
    description="Undo your last edit of a file in the draft.",
    parameters={
        "type": "object",
        "properties": {"repository": _REPOSITORY, "path": _PATH},
        "required": ["repository", "path"],
    },
    permission="workspace:read",
)

SHOW_CHANGES = AgentTool(
    name="show_changes",
    description=(
        "Your draft's diff so far: every file you changed, or one (`path`). Read it whole "
        "before you answer, as the strictest reviewer of the team would."
    ),
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "One file; all when empty."}},
    },
    permission="workspace:read",
)

CHECK_CHANGES = AgentTool(
    name="check_changes",
    description=(
        "What LEKA checks before a person sees the change, run on your draft now: a file that "
        "no longer parses, a key written twice, an import, a name or a variant that is nowhere "
        "in the repository, something a test reads taken away. Run it after each step of a "
        "large change and before you answer; fix what it finds."
    ),
    parameters={"type": "object", "properties": {}},
    permission="workspace:read",
)

PLAN = AgentTool(
    name="plan",
    description=(
        "The plan of a change of several steps. Give `steps` to set it, the whole list each "
        "time; nothing to read it. Plan a large change before you edit, keep one step « doing » "
        "at a time, mark it « done » only once it is in the draft and checked. A step left "
        "undone is said back to you before your analysis is taken."
    ),
    parameters={
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "What the step does."},
                        "status": {"type": "string", "enum": ["todo", "doing", "done"]},
                        "note": {"type": "string", "description": "Where, or what is left."},
                    },
                    "required": ["title", "status"],
                },
            }
        },
    },
    permission="workspace:read",
)

THINK = AgentTool(
    name="think",
    description=(
        "Write your reasoning down — what you found, the ways to do it, which you choose and "
        "why — without reading or changing anything. Before a large edit, or when a check "
        "fails twice."
    ),
    parameters={
        "type": "object",
        "properties": {"thought": {"type": "string", "description": "Your reasoning."}},
        "required": ["thought"],
    },
    permission="workspace:read",
)

ASK_EXPERT = AgentTool(
    name="ask_expert",
    description=(
        "Ask a stronger model for advice on a hard point: a cause you do not find, two ways to "
        "do it, an error you do not understand. Give your `question` and the `context` it needs "
        "(code, errors); it sees your draft's diff. It recommends, it does not edit. Three "
        "times per change at most."
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "What you need to know."},
            "context": {"type": "string", "description": "The code, the errors it needs."},
        },
        "required": ["question"],
    },
    permission="workspace:read",
)

# The workshop's tools: the code-change agent's own (workshop.py).
WORKSHOP_TOOLS: tuple[AgentTool, ...] = (
    EDIT_FILE,
    INSERT_LINES,
    WRITE_FILE,
    DELETE_FILE,
    UNDO_EDIT,
    SHOW_CHANGES,
    CHECK_CHANGES,
    PLAN,
    THINK,
    ASK_EXPERT,
)
WORKSHOP_NAMES = frozenset(t.name for t in WORKSHOP_TOOLS)
# What a repair of a pull request in red is offered (changes.py): reading at
# its head, fixing in a draft of its branch, checking (2026-10-30).
REPAIR_NAMES = frozenset(
    {
        "list_files",
        "read_file",
        "search_code",
        "edit_file",
        "insert_lines",
        "write_file",
        "delete_file",
        "undo_edit",
        "show_changes",
        "check_changes",
        "think",
        "ask_expert",
    }
)

CODE_TOOLS: tuple[AgentTool, ...] = (
    LIST_FILES,
    READ_FILE,
    SEARCH_CODE,
    LIST_PULL_REQUESTS,
    READ_PULL_REQUEST,
    AUDIT_DEPENDENCIES,
    *WORKSHOP_TOOLS,
)
CODE_NAMES = frozenset(t.name for t in CODE_TOOLS)


def _said(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _line(said: object, default: int) -> int:
    try:
        return max(1, int(str(said)))
    except ValueError:
        return default


# Lines given for a text looked for, at most; and how long a file may be to
# be read by ranges when it is too long to be read whole (2026-10-28: the
# labels of a 750 KB dictionary, refused even by ranges).
MOST_FOUND = 40
MOST_LONG = 5_000_000


def found_in(text: str, wanted: str) -> dict[str, object]:
    """The lines of a file that hold a text — case aside — with their
    numbers: where to read around."""
    needle = wanted.strip().lower()
    lines = text.splitlines()
    hits = [(n, line) for n, line in enumerate(lines, 1) if needle and needle in line.lower()]
    said: dict[str, object] = {}
    # A key's path in a nested dictionary (overview.home.history) is written
    # nowhere whole: its last part, as a key (« history: »), is (2026-10-28).
    last = needle.rsplit(".", 1)[-1]
    if not hits and "." in needle and last:
        key = re.compile(rf"(?:^|[\s{{,]){re.escape(last)}\s*[:=]")
        hits = [(n, line) for n, line in enumerate(lines, 1) if key.search(line.lower())]
        said["by"] = f"{last}:"
    return {
        "lines": len(lines),
        "find": wanted,
        **said,
        "found": [{"line": n, "text": line.strip()[:300]} for n, line in hits[:MOST_FOUND]],
        "more": len(hits) > MOST_FOUND,
    }


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
    (repository:path → the file's text), `paths` (repository → the files
    list_files showed), `drafts` (repository → its branch as searched and
    changed, workshop.py) and `draft`, the one the agent changed: its
    change."""
    seen: dict[str, Any] = kept if kept is not None else {}
    # Here, not at the top: changes.py reads the catalogue, which reads the
    # registry, which reads these tools' names.
    from leka.capabilities.changes import code_for
    from leka.capabilities.workshop import (
        Draft,
        EditError,
        matches_glob,
        nearest_paths,
        plan_said,
    )

    opened: dict[str, GitHubCode | None] = {}

    async def code(repository: str) -> GitHubCode | None:
        if repository not in opened:
            found = await code_for(session, workspace_id, repository)
            opened[repository] = found[1] if found else None
        return opened[repository]

    async def branch_of(found: GitHubCode, repository: str, asked: object) -> str:
        said = str(asked or "").strip()
        return said or await found.default_branch(repository)

    def drafted(repository: str) -> Draft | None:
        held: Draft | None = seen.get("drafts", {}).get(repository)
        return held

    async def draft_of(arguments: Mapping[str, Any], *, editing: bool = False) -> Draft | Answer:
        """The repository's draft — made at its first use. One change, one
        repository: the first edited is the change's."""
        repository = str(arguments.get("repository") or "").strip()
        editing_one: Draft | None = seen.get("draft")
        if not repository and editing_one is not None:
            repository = editing_one.repository
        if editing and editing_one is not None and repository != editing_one.repository:
            return Answer(
                _said(
                    {
                        "error": "one_repository",
                        "said": f"This change is on {editing_one.repository}: one change, one "
                        "repository. Say what else is needed in « Ce qui n'est pas fait ici ».",
                    }
                ),
                "refused",
                "invalid_input",
            )
        draft = drafted(repository)
        if draft is None:
            found = await code(repository)
            if found is None:
                return Answer(_said({"error": "no_repository"}), "refused", "out_of_scope")
            try:
                branch = await branch_of(found, repository, arguments.get("branch"))
            except CodeRefusedError as refused:
                return Answer(_said({"error": refused.code}), "refused", refused.code)
            draft = Draft(found, repository, branch)
            seen.setdefault("drafts", {})[repository] = draft
        draft.read = {
            key.split(":", 1)[1]: text
            for key, text in seen.get("files", {}).items()
            if key.startswith(f"{repository}:")
        }
        if editing and editing_one is None:
            seen["draft"] = draft
            # A plan set before its first edit is the draft's.
            if not draft.plan and seen.get("plan_before", {}).get("steps"):
                draft.set_plan(seen["plan_before"]["steps"])
        return draft

    async def list_files(arguments: Mapping[str, Any]) -> Answer:
        repository = str(arguments.get("repository") or "").strip()
        found = await code(repository)
        if found is None:
            return Answer(_said({"error": "no_repository"}), "refused", "out_of_scope")
        draft = drafted(repository)
        try:
            # A draft's branch, unless another is asked: a repair's is the
            # pull request's head.
            branch = (
                draft.ref
                if draft is not None and not arguments.get("branch")
                else await branch_of(found, repository, arguments.get("branch"))
            )
            paths, more = await found.paths(repository, branch, str(arguments.get("path") or ""))
        except CodeRefusedError as refused:
            return Answer(_said({"error": refused.code}), "refused", refused.code)
        # The files the draft adds, listed with the others; those it takes
        # away, not.
        if draft is not None:
            under = str(arguments.get("path") or "")
            paths = [p for p in paths if draft.now.get(p, "") is not None]
            paths += [
                p
                for p, t in draft.now.items()
                if t is not None and p.startswith(under) and p not in paths
            ]
        pattern = str(arguments.get("pattern") or "").strip()
        if pattern:
            paths = [p for p in paths if matches_glob(p, pattern)]
        # What it saw listed: the files it may name (2026-10-28).
        listed = seen.setdefault("paths", {}).setdefault(repository, [])
        listed.extend(p for p in paths if p not in listed)
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
        # A file the draft changed: as the draft holds it now.
        draft = drafted(repository)
        if draft is not None and path in draft.now:
            text_now = draft.now[path]
            if text_now is None:
                return Answer(_said({"error": "deleted_in_draft"}), "refused", "not_found")
            wanted_now = str(arguments.get("find") or "").strip()
            return Answer(
                _said(
                    {
                        "repository": repository,
                        "branch": draft.ref,
                        "path": path,
                        "draft": True,
                        **(
                            found_in(text_now, wanted_now)
                            if wanted_now
                            else lines_of(text_now, arguments)
                        ),
                    }
                ),
                "ok",
            )
        try:
            branch = (
                draft.ref
                if draft is not None and not arguments.get("branch")
                else await branch_of(found, repository, arguments.get("branch"))
            )
            try:
                text = await found.read(repository, path, branch)
            except CodeRefusedError as refused:
                # Too long to be given whole: read whole here, given by
                # ranges or by what is looked for.
                if refused.code != "too_large":
                    raise
                text = await found.read_whole(repository, path, branch, most=MOST_LONG)
        except CodeRefusedError as refused:
            return Answer(_said({"error": refused.code}), "refused", refused.code)
        if text is None:
            # Not there: the files it most likely means, never a guess
            # left to the model (2026-10-30).
            try:
                tree, _more = await found.paths(repository, branch)
            except CodeRefusedError:
                tree = []
            near = nearest_paths(path, tree)
            return Answer(
                _said({"error": "not_found", **({"did_you_mean": near} if near else {})}),
                "refused",
                "not_found",
            )
        wanted = str(arguments.get("find") or "").strip()
        if wanted:
            return Answer(
                _said(
                    {
                        "repository": repository,
                        "branch": branch,
                        "path": path,
                        **found_in(text, wanted),
                    }
                ),
                "ok",
            )
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

    # ── the workshop (workshop.py, 2026-10-30) ───────────────────────────

    def refused(error: EditError | CodeRefusedError) -> Answer:
        return Answer(_said({"error": str(error)}), "refused", "invalid_input")

    async def search_code(arguments: Mapping[str, Any]) -> Answer:
        draft = await draft_of(arguments)
        if isinstance(draft, Answer):
            return draft
        try:
            said = await draft.search(
                str(arguments.get("pattern") or ""),
                include=str(arguments.get("include") or ""),
                under=str(arguments.get("path") or ""),
                literal=bool(arguments.get("literal")),
                ignore_case=bool(arguments.get("ignore_case")),
            )
        except (EditError, CodeRefusedError) as error:
            return refused(error)
        # What it found, it saw: files it may name (2026-10-28).
        listed = seen.setdefault("paths", {}).setdefault(draft.repository, [])
        for path in dict.fromkeys(str(m["path"]) for m in said["matches"]):
            if path not in listed:
                listed.append(path)
        return Answer(_said({"repository": draft.repository, "branch": draft.ref, **said}), "ok")

    async def edited(arguments: Mapping[str, Any], how: str) -> Answer:
        draft = await draft_of(arguments, editing=True)
        if isinstance(draft, Answer):
            return draft
        path = str(arguments.get("path") or "")
        try:
            if how == "edit":
                try:
                    count = max(1, int(arguments.get("expected_replacements") or 1))
                except (TypeError, ValueError):
                    count = 1
                said = await draft.replace(
                    path,
                    str(arguments.get("old_text") or ""),
                    str(arguments.get("new_text") or ""),
                    count,
                )
            elif how == "insert":
                said = await draft.insert(
                    path, arguments.get("after_line"), str(arguments.get("text") or "")
                )
            elif how == "write":
                said = await draft.write(path, str(arguments.get("content") or ""))
            elif how == "delete":
                said = await draft.delete(path)
            else:
                said = draft.undo(path)
            # The repository's rules for the folder it writes in, the first
            # time: they travel with the code they rule.
            rules = await draft.rules_for(draft.path_of(path)) if how != "undo" else ""
        except (EditError, CodeRefusedError) as error:
            return refused(error)
        if rules:
            said += (
                "\n\nThe repository's rules for this folder (follow them to write the code, "
                "nothing else):\n" + rules
            )
        return Answer(said, "ok")

    async def edit_file(arguments: Mapping[str, Any]) -> Answer:
        return await edited(arguments, "edit")

    async def insert_lines(arguments: Mapping[str, Any]) -> Answer:
        return await edited(arguments, "insert")

    async def write_file(arguments: Mapping[str, Any]) -> Answer:
        return await edited(arguments, "write")

    async def delete_file(arguments: Mapping[str, Any]) -> Answer:
        return await edited(arguments, "delete")

    async def undo_edit(arguments: Mapping[str, Any]) -> Answer:
        return await edited(arguments, "undo")

    def editing() -> Draft | None:
        draft: Draft | None = seen.get("draft")
        return draft

    async def show_changes(arguments: Mapping[str, Any]) -> Answer:
        draft = editing()
        if draft is None or not draft.changed():
            return Answer(_said({"diff": "", "said": "No change in the draft yet."}), "ok")
        path = str(arguments.get("path") or "").strip() or None
        return Answer(
            _said(
                {
                    "repository": draft.repository,
                    "files": sorted(draft.changed()),
                    "diff": draft.diff(path),
                }
            ),
            "ok",
        )

    async def check_changes(arguments: Mapping[str, Any]) -> Answer:
        draft = editing()
        if draft is None or not draft.changed():
            return Answer(_said({"problems": [], "said": "No change in the draft yet."}), "ok")
        await draft_of({"repository": draft.repository})
        problems = await draft.problems()
        return Answer(
            _said(
                {
                    "files_changed": len(draft.changed()),
                    "problems": problems,
                    **(
                        {}
                        if problems
                        else {
                            "said": "LEKA's checks find nothing. Read show_changes as a reviewer "
                            "would before you answer."
                        }
                    ),
                }
            ),
            "ok",
        )

    async def plan(arguments: Mapping[str, Any]) -> Answer:
        draft = editing()
        if draft is None:
            # Planned before the first edit: the draft of the repository
            # read, or one to come.
            held: dict[str, Any] = seen.setdefault("plan_before", {})
            steps = arguments.get("steps")
            if isinstance(steps, list):
                held["steps"] = steps
            return Answer(_said({"steps": held.get("steps", []), "said": "Plan kept."}), "ok")
        steps = arguments.get("steps")
        if isinstance(steps, list):
            draft.set_plan([s for s in steps if isinstance(s, Mapping)])
        elif not draft.plan and seen.get("plan_before", {}).get("steps"):
            draft.set_plan(seen["plan_before"]["steps"])
        return Answer(_said(plan_said(draft.plan)), "ok")

    async def think(arguments: Mapping[str, Any]) -> Answer:
        return Answer(_said({"noted": True}), "ok")

    async def ask_expert(arguments: Mapping[str, Any]) -> Answer:
        from leka.capabilities.workshop import expert_advice

        draft = editing()
        asked = int(seen.get("experts", 0))
        if asked >= MOST_EXPERTS:
            return Answer(
                _said({"error": f"The expert was asked {MOST_EXPERTS} times already: go on."}),
                "refused",
                "limited",
            )
        seen["experts"] = asked + 1
        said = await expert_advice(
            session,
            workspace_id,
            str(arguments.get("question") or ""),
            str(arguments.get("context") or ""),
            draft,
        )
        return Answer(_said({"advice": said}), "ok")

    return {
        "list_files": list_files,
        "read_file": read_file,
        "search_code": search_code,
        "list_pull_requests": list_pull_requests,
        "read_pull_request": read_pull_request,
        "audit_dependencies": audit_dependencies,
        "edit_file": edit_file,
        "insert_lines": insert_lines,
        "write_file": write_file,
        "delete_file": delete_file,
        "undo_edit": undo_edit,
        "show_changes": show_changes,
        "check_changes": check_changes,
        "plan": plan,
        "think": think,
        "ask_expert": ask_expert,
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
