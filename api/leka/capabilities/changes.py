"""Code changes LEKA proposes — the code-change agent (`renders: code_change`).

    the run's analysis   markdown: what to change and why, from the code it
                         read (list_files, read_file — code_tools.py)
        ──▶ the model again, no tools, given the analysis and the files the
            agent read: the change, structured (ChangeProposal) — the
            repository, the branch, and for each file its edits: an exact
            text found once in the file, and what replaces it (2026-10-18:
            asked for whole files it had not been given, it wrote none)
        ──▶ each file read again on that branch, its edits applied here, its
            diff computed here — never the model's (an edit whose text is not
            in the file is said, never guessed; a file said changed but not
            is left out)
        ──▶ kept, proposed (`code_changes`) — linked to its run and intention
    a person who may approve (intention:approve)
        ──▶ rejects it, said why — or accepts it: LEKA opens a pull request on
            the source's repository — a new branch leka/…, one commit — when
            the source allows it (its `pull_requests`); never a merge. Refused,
            it stays proposed, said why: allow it, give the token write, retry.
            Each file is read again on the branch first: changed since, its
            modifications are laid again on what is there now — or refused,
            never a newer work undone (2026-10-20).
    then, read only     the pull request followed (`follow`): its checks, a
                        person's merge, the deployment that took it, the
                        version before it — until deployed, closed, or quiet
                        (run_follow_sweep)
    repaired, on asking (2026-10-24) its checks in red: « Réparer le
                        problème » — what failed read on GitHub (each check,
                        its annotations, the end of its log), the files it
                        names read at the pull request's head, the model
                        asked for the fix (exact edits, checked against those
                        files), one more commit on its leka/ branch — closed,
                        the pull request reopened first. The checks run
                        again; three repairs at most, then a person looks
    undone, on asking   (2026-10-20) not merged: its pull request closed.
                        Merged: « Annuler ce changement » proposes the change
                        that undoes it (`reverts`), each file laid back on its
                        branch as it is now — accepted like any other, its own
                        pull request, followed to production; and « Revenir à
                        la version précédente » starts the repository's
                        deployment workflow for the version before it, where
                        the source allows it (`rollbacks`, followed too)

An agent proposes, people decide (ADR 004): nothing reaches a repository
before a person accepted it, and then only as a pull request someone else
reviews and merges.
"""

from __future__ import annotations

import ast
import asyncio
import difflib
import json
import posixpath
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import JobQueue, enqueue_job
from leka.capabilities.catalogue import needs_of
from leka.capabilities.definition import Definition
from leka.capabilities.gateway import Gateway, Message, Needs, NoModelError, Request, Tier
from leka.capabilities.models import AgentRun, CodeChange
from leka.capabilities.registry import find
from leka.connectors import (
    CodeRefusedError,
    ConnectorError,
    FileChange,
    GitHubCode,
    Source,
    SourceKind,
    SourceService,
    SourceStatus,
    open_code,
)
from leka.db import session_factory, system_scope, workspace_scope

logger = structlog.get_logger(__name__)

MAX_FILES = 20
# A gateway's reason for no answer, as a change's error.
NO_MODEL = {
    "none": "no_model",
    "timeout": "timeout",
    "limited": "limited",
    "refused": "refused",
    "blocked": "refused",
    "unanswered": "unanswered",
}
# Why a file was not changed, as the summary says it.
SKIPPED_SAID = {
    "not_found": "le texte à remplacer n'y est pas",
    "ambiguous": "le texte à remplacer y est plusieurs fois",
}
# What the writer is shown of the files the agent read: each, and all.
MOST_SHOWN = 60_000
MOST_SHOWN_ALL = 240_000
# Its thinking counts: a model that thinks hard on the files it is given
# left too little of 16,000 for the edits (2026-10-18). Each model is held to
# what it gives back at most (the gateway).
CHANGE_TOKENS = 64_000
# The writer writes what the analysis decided: its model thinks at the
# standard depth (2026-10-27: thinking deep, Gemini spent 48,000 tokens on one
# 26 KB page and was cut before its edits, twice).
CHANGE_TIER = Tier.STANDARD
# A whole page redone, answered whole, is written in minutes — and asked
# again when an edit does not land (2026-10-27).
CHANGE_BUDGET = 20 * 60.0
# A diff kept, at most, per file.
MAX_DIFF_CHARS = 120_000
CONNECTED = (SourceStatus.ACTIVE, SourceStatus.DEGRADED)


class Edit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    find: str = Field(
        description="Le texte exact à remplacer, recopié du fichier lu, assez long pour n'y "
        "apparaître qu'une fois (quelques lignes entières)."
    )
    replace: str = Field(description="Le texte qui le remplace ; vide pour le retirer.")


class ProposedFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    path: str = Field(description="Le chemin du fichier dans le dépôt, ex. « api/app/main.py ».")

    @field_validator("path")
    @classmethod
    def _own(cls, path: str) -> str:
        """The path alone — a model copies « owner/repo:path » as it was
        shown the files (2026-10-28: every file then « not found »)."""
        return re.sub(r"^[\w.-]+/[\w.-]+:", "", path.strip())

    edits: list[Edit] = Field(
        default_factory=list,
        description="Un fichier qui existe : ses remplacements, dans l'ordre — jamais le fichier "
        "entier.",
    )
    content: str | None = Field(
        default=None,
        description="Un fichier nouveau, ou un fichier réécrit en grande partie quand on vous "
        "l'autorise : son contenu complet, chaque ligne.",
    )
    delete: bool = Field(default=False, description="true pour supprimer le fichier.")
    why: str = Field(default="", description="Pourquoi ce fichier change, en une phrase.")


class ChangeProposal(BaseModel):
    """What the model proposes to change."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    # What LEKA knows already, it says itself when a model leaves it out
    # (2026-10-28: Mistral forgot the repository, every answer refused).
    repository: str = Field(default="", description="Le dépôt, en nom complet : « owner/repo ».")
    base_branch: str = Field(
        default="", description="La branche lue et visée ; vide : sa branche par défaut."
    )
    title: str = Field(default="", description="Le titre de la pull request, court, à l'impératif.")
    summary: str = Field(
        default="", description="Ce qui change et pourquoi, pour la personne qui décide."
    )
    files: list[ProposedFile] = Field(description="Chaque fichier modifié, ajouté ou supprimé.")


# ── pure ────────────────────────────────────────────────────────────────────

_SEGMENT = re.compile(r"^[^\x00-\x1f\\]+$")


def safe_path(path: str) -> str | None:
    """A relative path inside the repository — None for one that escapes it,
    reaches into .git, or is not a file's."""
    said = path.strip()
    said = said[2:] if said.startswith("./") else said
    if (
        not said
        or said.startswith("/")
        or said.endswith("/")
        or len(said) > 400
        or not _SEGMENT.match(said)
    ):
        return None
    normal = posixpath.normpath(said)
    parts = normal.split("/")
    if normal.startswith("..") or ".." in parts or parts[0] == ".git" or normal.endswith("/"):
        return None
    return normal


def diff_of(path: str, before: str | None, after: str | None) -> tuple[str, int, int]:
    """The unified diff of one file, and its lines added and removed."""
    lines = difflib.unified_diff(
        (before or "").splitlines(keepends=True),
        (after or "").splitlines(keepends=True),
        fromfile="/dev/null" if before is None else f"a/{path}",
        tofile="/dev/null" if after is None else f"b/{path}",
        n=3,
    )
    said = [
        line if line.endswith("\n") else f"{line}\n\\ No newline at end of file\n" for line in lines
    ]
    added = sum(1 for line in said if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in said if line.startswith("-") and not line.startswith("---"))
    return "".join(said)[:MAX_DIFF_CHARS], added, removed


def _lines_at(text: str, find: str, *, loose: bool = False) -> list[int]:
    """Where a text's lines stand in another's, each line's trailing spaces
    aside — and, `loose`, its indentation too — the starts of its
    whole-line matches."""
    lines = text.split("\n")
    shape = str.strip if loose else str.rstrip
    wanted = [shape(line) for line in find.strip("\n").split("\n")]
    if not wanted or wanted == [""]:
        return []
    shaped = [shape(line) for line in lines]
    return [i for i in range(len(lines) - len(wanted) + 1) if shaped[i : i + len(wanted)] == wanted]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _reindented(lines: list[str], by: int) -> list[str]:
    """Lines moved right (`by` > 0) or left by that many spaces — as far as
    each has them."""
    if by > 0:
        return [" " * by + line if line.strip() else line for line in lines]
    return [line[min(-by, _indent(line)) :] for line in lines]


def apply_edits(text: str, edits: Sequence[Edit]) -> tuple[str | None, str | None]:
    """The file after its edits, in order — or why not: `not_found` when an
    edit's text is not in it, `ambiguous` when it is there more than once.
    Exact first; else line by line, trailing spaces aside (a copy that lost
    them still lands where it was copied from)."""
    after = text
    for edit in edits:
        if not edit.find:
            return None, "not_found"
        found = after.count(edit.find)
        if found == 1:
            after = after.replace(edit.find, edit.replace, 1)
            continue
        if found > 1:
            return None, "ambiguous"
        lines = after.split("\n")
        found_lines = edit.find.strip("\n").split("\n")
        replaced = edit.replace.strip("\n").split("\n") if edit.replace.strip("\n") else []
        starts = _lines_at(after, edit.find)
        if not starts:
            # Copied with other indentation (a diff pasted in markdown): the
            # same lines, the file's indentation kept for what replaces them.
            starts = _lines_at(after, edit.find, loose=True)
            if len(starts) == 1:
                first = next((i for i, line in enumerate(found_lines) if line.strip()), 0)
                by = _indent(lines[starts[0] + first]) - _indent(found_lines[first])
                replaced = _reindented(replaced, by)
        if len(starts) != 1:
            return None, "ambiguous" if starts else "not_found"
        size = len(found_lines)
        after = "\n".join([*lines[: starts[0]], *replaced, *lines[starts[0] + size :]])
    return after, None


_CODE_FILE = re.compile(
    r"`([\w.@-]+(?:/[\w.@-]+)+\.(?:tsx?|jsx?|mjs|cjs|py|css|scss|html|md|mdx|json|ya?ml|toml|"
    r"sql|go|rs|java|kt|swift|rb|php|cs|vue|svelte|sh))`"
)


def edits_from_diff(analysis: str) -> list[ProposedFile]:
    """The unified diffs an analysis holds, as edits: each hunk its lines
    before (context and removed) for its lines after (context and added); a
    file new, its content (2026-10-18: the analysis held the exact diff, and
    the change was still « not written »)."""
    found: dict[str, dict[str, Any]] = {}
    lines = analysis.replace("\r\n", "\n").split("\n")
    current: dict[str, Any] | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            old, new = line[4:].strip(), lines[i + 1][4:].strip()
            deleted = new == "/dev/null"
            named = old if deleted else new
            path = named[2:] if named[:2] in ("a/", "b/") else named
            current = found.setdefault(
                path, {"edits": [], "content": None, "delete": deleted, "new": old == "/dev/null"}
            )
            i += 2
            continue
        if line.startswith("@@") and current is not None:
            before: list[str] = []
            after: list[str] = []
            i += 1
            while i < len(lines):
                said = lines[i]
                if said.startswith(("@@", "```", "--- ", "+++ ")):
                    break
                if said.startswith("\\"):
                    i += 1
                    continue
                if said.startswith("+"):
                    after.append(said[1:])
                elif said.startswith("-"):
                    before.append(said[1:])
                elif said.startswith(" "):
                    before.append(said[1:])
                    after.append(said[1:])
                elif said == "" and i + 1 < len(lines) and lines[i + 1][:1] in (" ", "+", "-"):
                    # A blank context line that lost its leading space.
                    before.append("")
                    after.append("")
                else:
                    break
                i += 1
            if current["new"]:
                current["content"] = "\n".join(after) + "\n"
            elif before and before != after:
                current["edits"].append(Edit(find="\n".join(before), replace="\n".join(after)))
            continue
        i += 1
    return [
        ProposedFile(
            path=path,
            edits=said["edits"],
            content=said["content"],
            delete=said["delete"],
            why="d'après le diff de l'analyse",
        )
        for path, said in found.items()
        if said["edits"] or said["content"] is not None or said["delete"]
    ][:MAX_FILES]


def paths_named(analysis: str) -> list[str]:
    """The code files an analysis names — in its diffs, or quoted — in the
    order it names them."""
    named = [p.path for p in edits_from_diff(analysis)]
    named += _CODE_FILE.findall(analysis)
    return [p for p in dict.fromkeys(named) if safe_path(p)][:MAX_FILES]


def branch_of(title: str, change_id: uuid.UUID) -> str:
    """leka/<the title, as a slug>-<its id>: new, never one that exists."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "change"
    return f"leka/{slug}-{change_id.hex[:8]}"


CHANGE_RULES = """You are LEKA's change writer for the agent whose instructions \
follow. From its analysis and the files it read — and from nothing else — \
write the change it proposes, as one JSON object:
- repository: the full name (owner/repo) the analysis read; base_branch: \
the branch it read, or empty for the default one.
- files: each file to change, add or remove. A file that exists changes by \
edits: each edit's `find` is a text copied exactly from that file as you were \
given it — whole lines, enough of them to appear only once — and `replace` \
what stands there after. Never the whole file, never « … », never a diff. A \
new file gives its whole `content`; `delete: true` removes one. At most 20 \
files; only the files the analysis says must change.
- title: a short pull request title in the imperative; summary: what changes \
and why, for the person who decides, in the language of the inputs.
Never change a file you were not given: a file the agent did not read is not \
changed.
- The tests stay green: the tests you are given (beside the files) are what \
the CI runs. What a test reads of a file (a data-testid, a text, a role, an \
export it imports) is kept on what stands for it now, or that test is changed \
in this same change to read what the file now holds. Never delete a test, \
never skip one, never weaken what it checks. `tests_read` lists, test by \
test, the lines that check something: each link and its href, role and \
accessible name, text, test id, class and attribute they read stays on the \
screen as it is (the element kept, with its role, name and href) unless the \
analysis removes it; then that test changes with it, in this same change.
Answer with the JSON object only.

Never write the em dash « — »: a colon, a comma, a semicolon or \
parentheses, as the sentence needs."""


# A test, as repositories name them: test_x.py, x_test.go, x.test.tsx,
# x.spec.ts, under tests/ or __tests__/.
_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|e2e)/|(^|/)test_[^/]+$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$"
)
# Words a file's name shares with many others: no sign it is the same thing.
_COMMON = frozenset(
    {
        "web",
        "api",
        "app",
        "src",
        "lib",
        "components",
        "index",
        "main",
        "test",
        "tests",
        "spec",
        "e2e",
        "page",
        "pages",
        "utils",
        "util",
        "types",
        "common",
        "shared",
        "core",
        "base",
    }
)
# A change whose files to rewrite pass BIG_CHANGE characters is written file
# by file, ALONGSIDE at once, each answer the size of its file (2026-10-27: a
# whole home page, two files, answered at once, was cut at 48,000 tokens).
BIG_CHANGE = 30_000
ALONGSIDE = 4
# The tests given beside a change, at most: the closest first.
MOST_TESTS = 6
# Answers held to the test ids they keep: past these, the change is kept and
# the CI, then « Réparer le problème », says the rest.
ASKED_FOR_IDS = 2
# What a test reads of a screen, by its test id: getByTestId("x"),
# [data-testid="x"], data-testid="x".
_READS_ID = re.compile(r"""(?:ByTestId\(\s*|data-testid=\\?)["'`]([\w:./-]+)["'`]""")
_HAS_ID = re.compile(r"""data-testid=["']([\w:./-]+)["']""")


# A line of a test that checks something: an expectation, a query.
_CHECKS = re.compile(
    r"\b(?:expect|assert|(?:get|getAll|find|findAll|query|queryAll)By\w+|locator|getBy\w+)\s*\("
)
MOST_CHECKS = 80


def assertions_of(test: str) -> list[str]:
    """What a test checks, line by line, as written: what the writer keeps
    (2026-10-28: Mistral dropped a link and an href two tests read)."""
    lines = (line.strip() for line in test.split("\n"))
    return list(dict.fromkeys(line for line in lines if _CHECKS.search(line)))[:MOST_CHECKS]


def is_test(path: str) -> bool:
    return bool(_TEST_PATH.search(path))


def _words(path: str) -> set[str]:
    stem = path.rpartition("/")[2].split(".")[0]
    return {w for w in re.split(r"[^a-z0-9]+", stem.lower()) if len(w) > 2 and w not in _COMMON}


def _stem(path: str) -> str:
    name = path.rpartition("/")[2].split(".")[0]
    return name.removeprefix("test_").removesuffix("_test")


def covering_tests(paths: Sequence[str], tree: Sequence[str]) -> list[str]:
    """The tests that cover `paths` (2026-10-27, #423: a design applied to
    the home broke the test that read its blocks): first those of the same
    name (overview.tsx → overview.test.tsx, payments.py → test_payments.py),
    then those whose name shares a word with one (home-sections.tsx →
    e2e/home.spec.ts) — MOST_TESTS at most, none of `paths` itself."""
    code = [p for p in paths if not is_test(p)]

    def near(test: str) -> int:
        return -max((len(posixpath.commonpath([test, p])) for p in code), default=0)

    tests = sorted((t for t in tree if is_test(t) and t not in paths), key=near)
    stems = {_stem(p) for p in code}
    found = [t for t in tests if _stem(t) in stems]
    words = set().union(*(_words(p) for p in code)) if code else set()
    found += [t for t in tests if t not in found and _words(t) & words]
    return found[:MOST_TESTS]


# What opens, and what closes it, in code with braces.
_PAIRS = {")": "(", "]": "[", "}": "{"}
_BRACED = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".scss", ".java", ".go", ".cs")
# What may come before a quote that opens a string — not an apostrophe in
# JSX text (« L'environnement »).
_BEFORE_STRING = set("=(,:[{?!&|+-*/%<>;")


def _braces(text: str) -> str | None:
    """Where the brackets of code stop matching — strings, template literals
    and comments passed over — or None when they all match."""
    stack: list[tuple[str, int]] = []
    line, i, n = 1, 0, len(text)
    last = ""
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
        if text.startswith("//", i):
            i = text.find("\n", i)
            i = n if i < 0 else i
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            line += text.count("\n", i, end)
            i = end
            continue
        # A regular expression where a value starts: /…/flags, its own
        # brackets passed over.
        if c == "/" and (last in _BEFORE_STRING or last == "") and not text.startswith("/>", i):
            j, kind = i + 1, False
            while j < n and text[j] != "\n" and (text[j] != "/" or kind):
                if text[j] == "\\":
                    j += 1
                elif text[j] == "[":
                    kind = True
                elif text[j] == "]":
                    kind = False
                j += 1
            if j < n and text[j] == "/":
                i, last = j + 1, "/"
                while i < n and text[i].isalpha():
                    i += 1
                continue
        if c in '"`' or (c == "'" and (last in _BEFORE_STRING or last == "")):
            j = i + 1
            while j < n and text[j] != c:
                if text[j] == "\\":
                    j += 1
                elif c != "`" and text[j] == "\n":
                    break
                j += 1
            line += text.count("\n", i, min(j, n))
            i, last = j + 1, c
            continue
        if c in "([{":
            stack.append((c, line))
        elif c in ")]}":
            if not stack or stack[-1][0] != _PAIRS[c]:
                return f"a « {c} » at line {line} closes nothing open"
            stack.pop()
        if not c.isspace():
            last = c
        i += 1
    if stack:
        opened, at = stack[-1]
        return f"the « {opened} » opened at line {at} is never closed"
    return None


def broken(path: str, before: str, after: str) -> str | None:
    """Whether a change leaves a file that held together broken — Python
    parsed, JSON read, code with braces matched — said where (2026-10-28:
    Mistral's edits cut a JSX block, a « } » lost). A file that did not
    hold together before is not judged."""
    if path.endswith(".py"):
        try:
            ast.parse(before)
        except SyntaxError:
            return None
        try:
            ast.parse(after)
        except SyntaxError as error:
            return f"it no longer parses: {error.msg} at line {error.lineno}"
        return None
    if path.endswith(".json"):
        try:
            json.loads(before)
        except ValueError:
            return None
        try:
            json.loads(after)
        except ValueError as error:
            return f"it is no longer JSON: {error}"
        return None
    if path.endswith(_BRACED) and _braces(before) is None:
        return _braces(after)
    return None


def to_rewrite(analysis: str, read: Mapping[str, str]) -> list[str]:
    """The files given, tests apart, that the analysis names: what it changes."""
    given = {key.split(":", 1)[-1] for key in read}
    return [p for p in paths_named(analysis) if p in given and not is_test(p)]


def is_big(analysis: str, read: Mapping[str, str]) -> bool:
    """Too much to rewrite in one answer: more than one file, BIG_CHANGE
    characters of them."""
    given = {key.split(":", 1)[-1]: text for key, text in read.items()}
    paths = to_rewrite(analysis, read)
    return len(paths) > 1 and sum(len(given[p]) for p in paths) > BIG_CHANGE


def _only(proposal: ChangeProposal, paths: Sequence[str]) -> ChangeProposal:
    kept = [f for f in proposal.files if safe_path(f.path) in paths]
    return proposal.model_copy(update={"files": kept})


# What stands for code left out of a file given whole: « … », « // ... »,
# « {/* rest unchanged */} » — a file cut, never to be written as it is.
_ELIDED = re.compile(
    r"^\s*(?:"
    # A line that is only an ellipsis.
    r"(?:…|\.\.\.)\s*$"
    # A comment that opens on one.
    r"|(?://|#|/\*|\{/\*|<!--)\s*(?:…|\.\.\.)"
    # A comment standing for code: « rest of the file », « unchanged ».
    r"|(?://|#|/\*|\{/\*|<!--)\s*(?:rest of (?:the )?(?:file|code|component|function)"
    r"|reste du (?:fichier|code)|(?:the )?same as before|existing code|code existant"
    r"|(?:\w+ )?(?:unchanged|inchangée?s?)\s*(?:\*/\}?|-->)?\s*$)"
    r")",
    re.IGNORECASE | re.MULTILINE,
)
# A file given whole and this much shorter than it was is taken as cut.
SHORTEST_WHOLE = 0.4


def whole_problems(path: str, before: str, after: str) -> list[str]:
    """A file given whole in place of its edits (2026-10-27: a page
    redesigned, written as edits, ran past 48,000 tokens): whole, or said
    why not."""
    if _ELIDED.search(after):
        return [
            f"{path}: given whole, it stands for code it leaves out (« … », « rest "
            "unchanged »): write every line, or give edits."
        ]
    if before.strip() and len(after) < SHORTEST_WHOLE * len(before):
        return [
            f"{path}: given whole, it is {len(after)} characters where it had {len(before)}: "
            "write every line it keeps, or give edits."
        ]
    return []


def _ids(text: str) -> set[str]:
    return set(_HAS_ID.findall(text))


# A value a test checks, quoted in its line: a class, an address, a label
# the code writes.
_QUOTED = re.compile(r"""(["'`])((?:(?!\1)[^\\\n]|\\.){3,120})\1""")


def _checked(test: str) -> set[str]:
    """The quoted values a test's checks name — never a template."""
    return {
        value
        for line in assertions_of(test)
        for _quote, value in _QUOTED.findall(line)
        if "${" not in value
    }


def lost_ids(read: Mapping[str, str], after: Mapping[str, str]) -> list[str]:
    """What a change takes out of the code while a test still checks it —
    a test id (2026-10-27, #423), and any value a test names that the code
    wrote: a class, an address, a label (2026-10-28: Mistral dropped a link's
    href and a grid's class, two tests red) — each said with its test."""
    now = {**read, **after}
    code_now = [t for p, t in now.items() if not is_test(p)]
    code_before = [t for p, t in read.items() if not is_test(p)]
    before = set().union(*(_ids(t) for t in code_before))
    # Still named, however: a constant, an id built in a map — not lost.
    gone = {
        each
        for each in before - set().union(*(_ids(t) for t in code_now))
        if not any(f"{q}{each}{q}" in t for t in code_now for q in "\"'`")
    }
    said: list[str] = []
    for path, text in read.items():
        if not is_test(path):
            continue
        test = after.get(path, text)
        reads = set(_READS_ID.findall(test)) & gone
        for each in sorted(reads):
            said.append(
                f'{path} still reads data-testid "{each}", which this change removes: keep it '
                "on the element that stands for it now, or change that test in this same change."
            )
        values = _checked(test) - reads - before
        for each in sorted(values):
            if any(each in t for t in code_before) and not any(each in t for t in code_now):
                said.append(
                    f'{path} still checks "{each}", which this change takes out of the code: '
                    "keep it where it stands for the same thing now, or change that test in this "
                    "same change."
                )
    return said


def change_problems(
    proposal: ChangeProposal, read: Mapping[str, str], *, ids: bool = True, empty: bool = False
) -> list[str]:
    """Why a change cannot be applied as written — said to the model, which
    writes it again (2026-10-25: edits that did not land left the change
    unwritten until a person asked again). Each edit held to the file as
    the writer was given it; a change of no file is none — unless `empty`:
    a test adapted that still holds as it is (2026-10-28)."""
    if not proposal.files and not empty:
        return ["No file is changed: write the edits the analysis proposes."]
    given = {key.split(":", 1)[-1]: text for key, text in read.items()}
    problems: list[str] = []
    after: dict[str, str] = {}
    for each in proposal.files:
        # A path outside the repository is left out, never asked again for.
        path = safe_path(each.path)
        if path is None:
            continue
        if path not in given:
            if each.content is not None and not each.delete:
                after[path] = each.content
            continue
        if each.delete:
            after[path] = ""
            continue
        if not each.edits:
            if each.content is not None:
                problems += whole_problems(path, given[path], each.content)
                after[path] = each.content
            continue
        changed, why = apply_edits(given[path], each.edits)
        if why is not None:
            where = "there more than once" if why == "ambiguous" else "not in the file"
            problems.append(
                f"{path}: an edit's `find` is {where} as you were given it: copy whole "
                "lines exactly, enough of them to appear once."
            )
        elif changed is not None:
            after[path] = changed
    # Each file still holds together (2026-10-28).
    for path, text in after.items():
        why = broken(path, given.get(path, ""), text) if path in given else None
        if why and text:
            problems.append(
                f"{path}: {why} once your edits are applied — copy whole blocks in `find`, "
                "and give each `replace` every bracket its block closes."
            )
    # The tests given beside it stay green (2026-10-27, #423) — asked
    # ASKED_FOR_IDS times at most: past that, the CI says it.
    if ids:
        problems += lost_ids(given, after)
    return problems


def _anchor(path: str, text: str, analysis: str) -> int:
    """Where in a long file the analysis' change is: the first line its diff
    copies for that file — 0, its top, when it says none."""
    for each in edits_from_diff(analysis):
        if each.path.strip("/") != path and not path.endswith(f"/{each.path.strip('/')}"):
            continue
        for edit in each.edits:
            for line in edit.find.split("\n"):
                found = text.find(line.strip()) if len(line.strip()) >= 8 else -1
                if found >= 0:
                    return found
    return 0


def shown(read: Mapping[str, str], analysis: str = "") -> dict[str, str]:
    """The files the agent read, as the writer is shown them: each whole up
    to MOST_SHOWN, all up to MOST_SHOWN_ALL — the last ones read left out
    first, said so. A file longer, around where the analysis changes it
    (2026-10-28: a label 47 KB into a 750 KB dictionary)."""
    given: dict[str, str] = {}
    left = MOST_SHOWN_ALL
    for name, text in read.items():
        if left <= 0:
            given[name] = "[non montré : trop de fichiers lus]"
            continue
        room = min(MOST_SHOWN, left)
        start = 0
        if len(text) > room:
            at = _anchor(name.split(":", 1)[-1], text, analysis)
            start = max(0, min(at - room // 2, len(text) - room))
            start = text.rfind("\n", 0, start) + 1 if start else 0
        cut = text[start : start + room]
        head = f"[… lignes 1 à {text.count(chr(10), 0, start)} non montrées]\n" if start else ""
        tail = "" if start + len(cut) >= len(text) else "\n[… coupé]"
        given[name] = head + cut + tail
        left -= len(cut)
    return given


BY_FILE_RULES = """This change is written file by file, each apart and at \
the same time: write ONLY the files named in `only` (none when they do not \
change); the analysis says what the others hold after, and what this one uses \
of them (names, props, exports, test ids) is that. `changed`, when given, \
holds files as they are once changed: a test is adapted to them, its edits \
copied from `files`. A file this change reworks through most of its lines \
(a screen redesigned) is given whole in `content` instead of edits: every \
line of it as it stands after, never « … » nor a comment standing for code \
left out."""


def change_messages(
    definition: Definition,
    inputs: Mapping[str, object],
    analysis: str,
    read: Mapping[str, str] | None = None,
    *,
    only: Sequence[str] = (),
    changed: Mapping[str, str] | None = None,
) -> list[Message]:
    system = f"{CHANGE_RULES}\n\n---\n\n{definition.instructions or ''}"
    if only:
        system = f"{CHANGE_RULES}\n\n{BY_FILE_RULES}\n\n---\n\n{definition.instructions or ''}"
    # The files it read, keyed « owner/repo:path »: what the edits copy from.
    material: dict[str, object] = {
        "inputs": dict(inputs),
        "analysis": analysis,
        "files": shown(read or {}, analysis),
    }
    checked = {
        key.split(":", 1)[-1]: assertions_of(text)
        for key, text in (read or {}).items()
        if is_test(key.split(":", 1)[-1])
    }
    if any(checked.values()):
        material["tests_read"] = {path: lines for path, lines in checked.items() if lines}
    if only:
        material["only"] = list(only)
    if changed:
        material["changed"] = shown(changed)
    return [
        Message.system(system),
        Message.user(json.dumps(material, ensure_ascii=False, default=str)),
    ]


# ── a run's proposal ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Proposed:
    """What a run's proposal came to: the change kept — or why not."""

    change: CodeChange | None
    error: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    # The files it could not change, each with why (an edit not found…).
    skipped: list[dict[str, str]] = field(default_factory=list)
    # What the model's provider, or LEKA, said when it was not written.
    said: str = ""


async def github_sources(session: AsyncSession, workspace_id: uuid.UUID) -> list[Source]:
    found = await session.scalars(
        select(Source).where(
            Source.workspace_id == workspace_id,
            Source.kind == SourceKind.GITHUB,
            Source.status.in_(CONNECTED),
        )
    )
    return list(found)


# The repositories a workspace's sources list, read when one lists none, at
# most; a name, as a word of a request.
MAX_LISTED = 200
_WORD = re.compile(r"[a-z0-9][a-z0-9._-]*")


async def repositories_here(session: AsyncSession, workspace_id: uuid.UUID) -> list[str]:
    """The repositories the workspace's connected GitHub sources read: the
    list an admin chose, else what the source sees."""
    names: list[str] = []
    service = SourceService(session, workspace_id, actor_user_id=None)
    for source in await github_sources(session, workspace_id):
        listed = (source.config or {}).get("repositories")
        if isinstance(listed, list) and listed:
            names += [str(name) for name in listed]
            continue
        try:
            scope = await (await service.open_connector(source)).list_scope()
        except ConnectorError as error:
            # Its credentials gone: said in a line, the next source read.
            logger.warning("repositories_not_listed", source=str(source.id), code=str(error)[:120])
            continue
        except Exception:
            logger.warning("repositories_not_listed", source=str(source.id), exc_info=True)
            continue
        names += [option.key for option in scope.options[:MAX_LISTED]]
    return list(dict.fromkeys(names))


def repository_named(text: str, repositories: Sequence[str]) -> str | None:
    """The repository a request means (2026-10-25: « propose un design de la
    page d'accueil de LEKA » drew another screen; « … de Haitam-elh/Leka »,
    the right one): named in full; else by its own name, a word of the
    request (« LEKA » is Haitam-elh/Leka), when one only answers to it; else
    the only one there is. None when it cannot be told."""
    said = text.casefold()
    full = [r for r in repositories if r.casefold() in said]
    if full:
        return max(full, key=len)
    words = set(_WORD.findall(said))
    named = [r for r in repositories if r.rsplit("/", 1)[-1].casefold() in words]
    if len(named) == 1:
        return named[0]
    return repositories[0] if len(repositories) == 1 else None


async def repository_for(session: AsyncSession, workspace_id: uuid.UUID, text: str) -> str | None:
    """The repository a request means, among those the workspace reads."""
    return repository_named(text, await repositories_here(session, workspace_id))


async def code_for(
    session: AsyncSession, workspace_id: uuid.UUID, repository: str
) -> tuple[Source, GitHubCode] | None:
    """The workspace's GitHub source whose scope holds this repository, and
    its code — None when none does. A source that does not open (its
    credentials gone) is passed over, never the end of the search
    (2026-10-27: one source without its token hid the one that had it)."""
    service = SourceService(session, workspace_id, actor_user_id=None)
    for source in await github_sources(session, workspace_id):
        try:
            code = await open_code(await service.open_connector(source))
        except ConnectorError as error:
            logger.warning("code_source_not_opened", source=str(source.id), code=str(error)[:120])
            continue
        if code.in_scope(repository):
            return source, code
    return None


async def _changed(
    code: GitHubCode, repository: str, base: str, proposed: Sequence[ProposedFile]
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Each file proposed, read on the branch, changed here: its diff — or
    why it could not be."""
    files: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    for each in proposed[:MAX_FILES]:
        path = safe_path(each.path)
        if path is None or any(f["path"] == path for f in files):
            continue
        before = await code.read(repository, path, base)
        after: str | None
        if each.delete:
            if before is None:
                continue
            after = None
        elif each.edits:
            if before is None:
                skipped.append({"path": path, "why": "not_found"})
                continue
            after, why = apply_edits(before, each.edits)
            if after is None:
                skipped.append({"path": path, "why": why or "not_found"})
                continue
        elif each.content is not None:
            after = each.content
        else:
            continue
        if before == after:
            continue
        diff, added, removed = diff_of(path, before, after)
        files.append(
            {
                "path": path,
                "status": "added" if before is None else "deleted" if after is None else "modified",
                "content": after,
                "diff": diff,
                "additions": added,
                "deletions": removed,
                "why": each.why[:500],
            }
        )
    return files, skipped


async def _repository_of(
    session: AsyncSession, run: AgentRun, analysis: str
) -> tuple[Source, GitHubCode, str] | None:
    """The repository the change is for: the one it was asked, else the
    first the analysis names that a connected GitHub source reads."""
    asked = str((run.inputs or {}).get("depot") or "").strip()
    named = [asked] if asked else []
    named += re.findall(r"\b([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)\b", analysis)
    for repository in dict.fromkeys(named):
        if repository.count("/") != 1 or "." in repository.split("/")[0]:
            continue
        found = await code_for(session, run.workspace_id, repository)
        if found is not None:
            return found[0], found[1], repository
    return None


async def code_of(
    session: AsyncSession, run: AgentRun, analysis: str
) -> tuple[GitHubCode, str, str] | None:
    """The code a run's report is about — its reader, its repository, its
    default branch — or None when no connected GitHub source reads it."""
    found = await _repository_of(session, run, analysis)
    if found is None:
        return None
    _, code, repository = found
    try:
        return code, repository, await code.default_branch(repository)
    except CodeRefusedError:
        return None


async def files_named(session: AsyncSession, run: AgentRun, analysis: str) -> dict[str, str]:
    """The code files an analysis names, read on its repository's default
    branch (« owner/repo:path » → text) — for a run that did not keep the
    files it read."""
    found = await _repository_of(session, run, analysis)
    if found is None:
        return {}
    _, code, repository = found
    read: dict[str, str] = {}
    try:
        base = await code.default_branch(repository)
        for path in paths_named(analysis):
            text = await code.read(repository, path, base)
            if text is not None:
                read[f"{repository}:{path}"] = text
    except CodeRefusedError:
        pass
    return read


def _summary_of(analysis: str) -> str:
    """What the analysis says first, without its code: the change's summary
    when it is written from the analysis' own diff."""
    prose = re.sub(r"```.*?```", "", analysis, flags=re.DOTALL)
    paragraphs = [
        p.strip()
        for p in prose.split("\n\n")
        if p.strip() and not p.strip().startswith(("#", "---", "+++", "@@"))
    ]
    return " ".join(paragraphs[:2])[:800]


def _kept(
    run: AgentRun,
    source: Source,
    repository: str,
    base: str,
    title: str,
    summary: str,
    files: list[dict[str, object]],
    skipped: list[dict[str, str]],
) -> CodeChange:
    if skipped:
        summary += "\n\nNon appliqué : " + ", ".join(
            f"`{s['path']}` ({SKIPPED_SAID.get(s['why'], s['why'])})" for s in skipped
        )
    return CodeChange(
        workspace_id=run.workspace_id,
        id=uuid.uuid4(),
        run_id=run.id,
        intention_id=run.intention_id,
        source_id=source.id,
        repository=repository,
        base_branch=base[:200],
        title=title.strip()[:300] or "Modification proposée par LEKA",
        summary=summary,
        files=files,
        status="proposed",
        proposed_by=run.requested_by,
    )


async def _with_tests(
    code: GitHubCode, repository: str, base: str, read: Mapping[str, str]
) -> dict[str, str]:
    """What the writer is given, and the tests of it (covering_tests) — read here,
    whatever the agent read: a change keeps them green or changes them."""
    given = dict(read)
    paths = [key.split(":", 1)[-1] for key in given]
    if not paths or not any(not is_test(p) for p in paths):
        return given
    try:
        tree, _more = await code.paths(repository, base)
    except CodeRefusedError:
        return given
    except Exception:
        logger.exception("change_tests_not_listed", repository=repository)
        return given
    for path in covering_tests(paths, tree):
        try:
            text = await code.read(repository, path, base)
        except CodeRefusedError:
            continue
        if text is not None:
            given[f"{repository}:{path}"] = text
    return given


async def propose_change(
    session: AsyncSession,
    run: AgentRun,
    definition: Definition,
    analysis: str,
    *,
    read: Mapping[str, str] | None = None,
    budget: float = CHANGE_BUDGET,
    target: Mapping[str, object] | None = None,
) -> Proposed:
    """The change a run's analysis proposes, applied, diffed and kept:

    1. its own diff, when it holds one that lands whole on the files read
       again — no model asked again;
    2. else the model, given the analysis and the files the agent read — or,
       none kept, the files the analysis names, read again;
    3. the model failing, what of its own diff did land.

    Implementing a design review's direction (`target`, mockups.design_target):
    the writer is given its mock-up too (2026-10-24)."""
    found = await _repository_of(session, run, analysis)
    from_diff: tuple[list[dict[str, object]], list[dict[str, str]]] = ([], [])
    base = ""
    if found is not None:
        source, code, repository = found
        try:
            base = await code.default_branch(repository)
            proposed = edits_from_diff(analysis)
            if proposed:
                from_diff = await _changed(code, repository, base, proposed)
        except CodeRefusedError as refused:
            logger.warning("change_not_read", run=str(run.id), code=refused.code)
        except Exception:
            logger.exception("change_not_read", run=str(run.id))
        files, skipped = from_diff
        if files and not skipped:
            title = str((run.inputs or {}).get("demande") or "").strip().split("\n")[0][:120]
            change = _kept(
                run, source, repository, base, title, _summary_of(analysis), files, skipped
            )
            session.add(change)
            await session.flush()
            return Proposed(change, None, {"from": "analysis"}, skipped)
        if not read:
            read = {}
            for path in paths_named(analysis):
                try:
                    text = await code.read(repository, path, base)
                except CodeRefusedError:
                    continue
                if text is not None:
                    read[f"{repository}:{path}"] = text
        read = await _with_tests(code, repository, base, read)
    request = Request(
        purpose=f"agent:{definition.key}:change"[:100],
        messages=change_messages(
            definition,
            {**run.inputs, "maquette": target} if target else run.inputs,
            analysis,
            read,
        ),
        tier=CHANGE_TIER,
        max_tokens=CHANGE_TOKENS,
        ref=f"agent_run:{run.id}",
    )
    failed: Proposed | None = None
    verified = [0]
    inputs = {**run.inputs, "maquette": target} if target else run.inputs

    def verify(proposal: ChangeProposal) -> list[str]:
        verified[0] += 1
        return change_problems(proposal, read or {}, ids=verified[0] <= ASKED_FOR_IDS)

    deadline = asyncio.get_running_loop().time() + budget
    usage: dict[str, Any] = {}
    try:
        if is_big(analysis, read or {}):
            proposal = await asyncio.wait_for(
                _by_file(session, run, definition, inputs, analysis, read or {}, usage),
                timeout=budget,
            )
        else:
            try:
                answered = await asyncio.wait_for(
                    Gateway(session, run.workspace_id).structured(
                        request,
                        ChangeProposal,
                        replace(needs_of(definition), tools=False),
                        verify=verify,
                    ),
                    timeout=budget,
                )
            except NoModelError as error:
                # Cut at its limit: too much at once — written file by file.
                if not _cut(error) or not to_rewrite(analysis, read or {}):
                    raise
                logger.info("change_written_by_file", run=str(run.id))
                left = deadline - asyncio.get_running_loop().time()
                proposal = await asyncio.wait_for(
                    _by_file(session, run, definition, inputs, analysis, read or {}, usage),
                    timeout=max(left, 60.0),
                )
            else:
                proposal = answered.value
                done = answered.completion
                usage = {
                    "provider": done.provider,
                    "model": done.model,
                    "tokens_in": done.usage.tokens_in,
                    "tokens_out": done.usage.tokens_out,
                }
    except NoModelError as error:
        # Why, as it was: no model at all, or models that answered and were
        # not kept — never all said « no model » (2026-10-18).
        said = next((a.error for a in reversed(error.attempts) if a.error), None)
        logger.warning("change_not_written", run=str(run.id), reason=error.reason, said=said)
        failed = Proposed(None, NO_MODEL.get(error.reason, "unanswered"), said=(said or "")[:300])
    except TimeoutError:
        failed = Proposed(None, "timeout")
    except Exception:
        # Whatever else: the run's analysis stands, said why no change is.
        logger.exception("change_not_written", run=str(run.id))
        failed = Proposed(None, "error")
    if failed is not None:
        return _from_diff_else(session, run, analysis, found, base, from_diff, failed)
    proposal = completed(proposal, run, analysis, found[2] if found else None, read or {})
    written = await code_for(session, run.workspace_id, proposal.repository.strip())
    if written is None:
        return _from_diff_else(
            session, run, analysis, found, base, from_diff, Proposed(None, "no_repository", usage)
        )
    source, code = written
    repository = proposal.repository.strip()
    try:
        base = proposal.base_branch.strip() or await code.default_branch(repository)
        files, skipped = await _changed(code, repository, base, proposal.files)
    except CodeRefusedError as refused:
        logger.warning("change_not_read", run=str(run.id), code=refused.code)
        return Proposed(None, refused.code, usage)
    except Exception:
        logger.exception("change_not_read", run=str(run.id))
        return Proposed(None, "error", usage)
    if not files:
        # Its edits did not land: said, never guessed — unless the
        # analysis' own diff did.
        none = Proposed(None, "edits_not_applied" if skipped else "no_change", usage, skipped)
        return _from_diff_else(session, run, analysis, found, base, from_diff, none)
    change = _kept(
        run, source, repository, base, proposal.title, proposal.summary.strip(), files, skipped
    )
    session.add(change)
    await session.flush()
    return Proposed(change, None, usage, skipped)


async def _all[T](asked: Sequence[Awaitable[T]]) -> list[T]:
    """Each at once: the first to fail stops the others, and is raised."""
    tasks = [asyncio.ensure_future(each) for each in asked]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        raise


def completed(
    proposal: ChangeProposal,
    run: AgentRun,
    analysis: str,
    repository: str | None,
    read: Mapping[str, str],
) -> ChangeProposal:
    """What a model left out and LEKA knows, said by LEKA: the repository
    the change was read from, a title from the request, a summary from the
    analysis (2026-10-28)."""
    named = repository or next((key.split(":", 1)[0] for key in read if ":" in key), "")
    asked = str((run.inputs or {}).get("demande") or "").strip().split("\n")[0]
    return proposal.model_copy(
        update={
            "repository": proposal.repository.strip() or named,
            "title": proposal.title.strip() or asked[:120] or "Modification proposée",
            "summary": proposal.summary.strip() or _summary_of(analysis),
        }
    )


def _cut(error: NoModelError) -> bool:
    return any("Cut at its limit" in (a.error or "") for a in error.attempts)


async def _by_file(
    session: AsyncSession,
    run: AgentRun,
    definition: Definition,
    inputs: Mapping[str, object],
    analysis: str,
    read: Mapping[str, str],
    usage: dict[str, Any],
) -> ChangeProposal:
    """A change too big for one answer, written file by file (2026-10-27):
    each file the analysis names, alongside, every file given to each; the
    new files it names, apart; then each test given, adapted to the files as
    they now are. One file not written fails it all: never half a change."""
    given = {key.split(":", 1)[-1]: text for key, text in read.items()}
    code = to_rewrite(analysis, read) or [p for p in given if not is_test(p)][:MAX_FILES]
    new = [p for p in paths_named(analysis) if p not in given]
    needs = replace(needs_of(definition), tools=False)
    limit = asyncio.Semaphore(ALONGSIDE)
    # Nothing held while the files are written, each in its own session.
    await session.commit()

    async def one(
        paths: Sequence[str],
        changed: Mapping[str, str] | None = None,
        also: Callable[[ChangeProposal], list[str]] | None = None,
    ) -> ChangeProposal:
        request = Request(
            purpose=f"agent:{definition.key}:change-file"[:100],
            messages=change_messages(
                definition, inputs, analysis, read, only=paths, changed=changed
            ),
            tier=CHANGE_TIER,
            max_tokens=CHANGE_TOKENS,
            ref=f"agent_run:{run.id}",
        )

        def verify(proposal: ChangeProposal) -> list[str]:
            mine = _only(proposal, paths)
            # A test that still holds is left as it is: no file is an answer.
            problems = change_problems(mine, read, ids=False, empty=changed is not None)
            return problems + (also(mine) if also else [])

        async with limit, session_factory() as own:
            try:
                answered = await Gateway(own, run.workspace_id).structured(
                    request, ChangeProposal, needs, verify=verify
                )
            finally:
                await own.commit()
        done = answered.completion
        usage["provider"], usage["model"] = done.provider, done.model
        usage["tokens_in"] = int(usage.get("tokens_in", 0)) + done.usage.tokens_in
        usage["tokens_out"] = int(usage.get("tokens_out", 0)) + done.usage.tokens_out
        return _only(answered.value, paths)

    written = await _all([one([path]) for path in code] + ([one(new)] if new else []))
    files = [f for each in written for f in each.files]
    after: dict[str, str] = {}
    for each in files:
        path = safe_path(each.path)
        if path is None:
            continue
        if path in given and each.edits:
            changed, _why = apply_edits(given[path], each.edits)
            if changed is not None:
                after[path] = changed
        elif each.delete:
            after[path] = ""
        elif each.content is not None:
            after[path] = each.content
    tests = [p for p in given if is_test(p)]
    if after and tests:

        def kept_ids(path: str) -> Callable[[ChangeProposal], list[str]]:
            asked_ids = [0]

            def check(proposal: ChangeProposal) -> list[str]:
                asked_ids[0] += 1
                if asked_ids[0] > ASKED_FOR_IDS:
                    return []
                now = dict(after)
                for each in proposal.files:
                    if each.edits and safe_path(each.path) == path:
                        test, _why = apply_edits(given[path], each.edits)
                        if test is not None:
                            now[path] = test
                return [p for p in lost_ids(given, now) if p.startswith(f"{path} ")]

            return check

        adapted = await _all([one([t], after, kept_ids(t)) for t in tests])
        files += [f for each in adapted for f in each.files]
    first = written[0]
    return first.model_copy(update={"files": files[:MAX_FILES]})


def _from_diff_else(
    session: AsyncSession,
    run: AgentRun,
    analysis: str,
    found: tuple[Source, GitHubCode, str] | None,
    base: str,
    from_diff: tuple[list[dict[str, object]], list[dict[str, str]]],
    failed: Proposed,
) -> Proposed:
    """What of the analysis' own diff landed, when the model gave nothing
    better — else why nothing did."""
    files, skipped = from_diff
    if found is None or not files:
        return failed
    source, _, repository = found
    title = str((run.inputs or {}).get("demande") or "").strip().split("\n")[0][:120]
    change = _kept(run, source, repository, base, title, _summary_of(analysis), files, skipped)
    session.add(change)
    return Proposed(change, None, {"from": "analysis"}, skipped)


# ── deciding ────────────────────────────────────────────────────────────────


class ChangeNotFoundError(LookupError):
    pass


class ChangeDecidedError(Exception):
    """It is no longer proposed: decided already."""


class ChangeRefusedError(Exception):
    """GitHub, or the source, refused the pull request — it stays proposed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def on_base(path: str, now: str | None, content: str | None, diff: str) -> tuple[str | None, str]:
    """A file of a change, as it would be on its branch as it is now, and
    what it is there: `changes` — as proposed when the file has not changed
    since, else its modifications laid again on what is there — `same` when
    the branch already has it, `moved` when they no longer land (2026-10-20:
    a change accepted a day later must not undo what was merged in
    between)."""
    if diff_of(path, now, content)[0] == diff:
        return content, "changes"
    if now == content:
        return content, "same"
    if now is None or content is None or len(diff) >= MAX_DIFF_CHARS:
        return None, "moved"
    found = [each for each in edits_from_diff(diff) if each.path == path and each.edits]
    if len(found) != 1:
        return None, "moved"
    after, _why = apply_edits(now, found[0].edits)
    if after is None:
        return None, "moved"
    return after, "changes" if after != now else "same"


async def _on_base(
    code: GitHubCode, change: CodeChange, sha: str
) -> tuple[list[FileChange], list[dict[str, object]]]:
    """Each file of a change read again at `sha` and laid on it — or
    ChangeRefusedError: changed_since, naming what moved; already_applied,
    when nothing is left to change."""
    changes: list[FileChange] = []
    files: list[dict[str, object]] = []
    moved: list[str] = []
    for f in change.files:
        path = str(f["path"])
        content = c if isinstance(c := f.get("content"), str) else None
        now = await code.read(change.repository, path, sha)
        after, state = on_base(path, now, content, str(f.get("diff") or ""))
        if state == "moved":
            moved.append(path)
        if state != "changes":
            continue
        diff, added, removed = diff_of(path, now, after)
        files.append(
            {**f, "content": after, "diff": diff, "additions": added, "deletions": removed}
        )
        changes.append(FileChange(path, after))
    if moved:
        raise ChangeRefusedError(
            "changed_since",
            f"{', '.join(moved)} a changé sur {change.base_branch} depuis la proposition, là où "
            "LEKA le modifie : LEKA n'écrase pas ce travail. Réécrivez le changement.",
        )
    if not changes:
        raise ChangeRefusedError(
            "already_applied", f"Ce changement est déjà sur {change.base_branch}."
        )
    return changes, files


# How long a pull request is followed after it was opened, and its merge
# without any deployment seen; how long its checks may take to appear.
FOLLOW_FOR = timedelta(days=14)
QUIET_AFTER_MERGE = timedelta(hours=3)
CHECKS_APPEAR = timedelta(minutes=10)
# Where a pull request stands, as LEKA says it — those that end the follow.
FOLLOW_DONE = frozenset({"deployed", "deploy_failed", "closed", "rolled_back", "rollback_failed"})
# A run of the deployment workflow LEKA started, as said by GitHub, and the
# stage it gives the change; listed from a minute before it was asked.
ROLLED = {"success": "rolled_back", "failure": "rollback_failed"}
RUN_SLACK = timedelta(minutes=1)
DEPLOYED = {"success": "deployed", "inactive": "deployed", "failure": "deploy_failed"}


def stage_of(seen: Mapping[str, Any], *, opened_at: datetime, now: datetime) -> str:
    """One word for where a pull request stands, from what GitHub said:
    checks, no_checks, checks_failed, checks_unreadable, conflict, ready —
    for a person to merge — merged, deploying, deployed, deploy_failed,
    closed."""
    if seen["state"] == "closed":
        return "closed"
    if seen["state"] == "merged":
        deployment = seen.get("deployment")
        if not deployment:
            return "merged"
        state = str(deployment.get("state"))
        return DEPLOYED.get(state, "deploy_failed" if state == "error" else "deploying")
    checks = str((seen.get("checks") or {}).get("state") or "none")
    if checks == "failure":
        return "checks_failed"
    if seen.get("mergeable") is False:
        return "conflict"
    if checks == "none":
        return "no_checks" if now - opened_at > CHECKS_APPEAR else "checks"
    return {"pending": "checks", "success": "ready", "unreadable": "checks_unreadable"}.get(
        checks, "checks"
    )


_HUNK = re.compile(r"^@@ -(\S+) \+(\S+) @@(.*)$")


def reversed_diff(diff: str) -> str:
    """A unified diff the other way: what it adds, removed; what it
    removes, added; a file it made, removed — what undoing it does."""

    def swapped(name: str) -> str:
        if name.startswith("a/"):
            return f"b/{name[2:]}"
        if name.startswith("b/"):
            return f"a/{name[2:]}"
        return name

    said: list[str] = []
    lines = diff.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            said += [f"--- {swapped(lines[i + 1][4:])}", f"+++ {swapped(line[4:])}"]
            i += 2
            continue
        hunk = _HUNK.match(line)
        if hunk:
            said.append(f"@@ -{hunk[2]} +{hunk[1]} @@{hunk[3]}")
        elif line.startswith("+"):
            said.append(f"-{line[1:]}")
        elif line.startswith("-"):
            said.append(f"+{line[1:]}")
        else:
            said.append(line)
        i += 1
    return "\n".join(said)


def before_of(path: str, after: str | None, diff: str) -> tuple[str | None, bool]:
    """A file as it was before a change, from what the change made of it and
    its diff — and whether the diff could say it (one cut cannot)."""
    if len(diff) >= MAX_DIFF_CHARS:
        return None, False
    found = [each for each in edits_from_diff(reversed_diff(diff)) if each.path == path]
    if not found:
        return None, False
    back = found[0]
    if after is None:
        # It removed the file: back, the file as it was.
        return back.content, back.content is not None
    if back.delete:
        # It made the file: back, there is none.
        return None, True
    if not back.edits:
        return None, False
    before, _why = apply_edits(after, back.edits)
    return before, before is not None


# The ids an analysis cites ([uuid]): LEKA's, never said on GitHub.
_CITED_ID = re.compile(
    r"\s*\[[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\]", re.IGNORECASE
)


def body_of(change: CodeChange, *, by: str) -> str:
    files = "\n".join(
        f"- `{f['path']}` ({f['status']}, +{f['additions']} -{f['deletions']})"
        + (f" — {f['why']}" if f.get("why") else "")
        for f in change.files
    )
    return (
        f"{_CITED_ID.sub('', change.summary)}\n\n### Fichiers\n{files}\n\n---\n"
        f"Proposée par LEKA, acceptée par {by}. "
        "LEKA ouvre la pull request ; la relire et la fusionner reste votre décision. "
        "Fusionnée, LEKA suit son déploiement."
    )


class ChangeService:
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def changes(
        self, *, intention_id: uuid.UUID | None = None, run_id: uuid.UUID | None = None
    ) -> list[CodeChange]:
        query = select(CodeChange).where(CodeChange.workspace_id == self._workspace_id)
        if intention_id is not None:
            query = query.where(CodeChange.intention_id == intention_id)
        if run_id is not None:
            query = query.where(CodeChange.run_id == run_id)
        found = await self._session.scalars(query.order_by(CodeChange.created_at.desc()).limit(50))
        return list(found)

    async def change(self, change_id: uuid.UUID, *, lock: bool = False) -> CodeChange:
        query = select(CodeChange).where(
            CodeChange.workspace_id == self._workspace_id, CodeChange.id == change_id
        )
        found = await self._session.scalar(query.with_for_update() if lock else query)
        if found is None:
            raise ChangeNotFoundError(str(change_id))
        return found

    async def allowed(self, change: CodeChange) -> bool:
        """Whether its source lets LEKA open a pull request."""
        source = await self._session.get(Source, change.source_id)
        return bool(source is not None and (source.config or {}).get("pull_requests"))

    async def reject(self, change_id: uuid.UUID, *, by: uuid.UUID, note: str | None) -> CodeChange:
        change = await self.change(change_id, lock=True)
        if change.status != "proposed":
            raise ChangeDecidedError(change.status)
        change.status = "rejected"
        change.decided_by, change.decided_at = by, datetime.now(UTC)
        change.note = (note or "").strip()[:2000] or None
        await self._session.commit()
        return change

    async def accept(
        self, change_id: uuid.UUID, *, by: uuid.UUID, by_name: str, note: str | None
    ) -> CodeChange:
        """Its pull request, opened — or ChangeRefusedError, and it stays
        proposed with why."""
        change = await self.change(change_id, lock=True)
        if change.status != "proposed":
            raise ChangeDecidedError(change.status)
        source = await self._session.get(Source, change.source_id)
        if source is None or source.status not in CONNECTED:
            raise ChangeRefusedError("no_source", "La source GitHub n'est plus connectée.")
        service = SourceService(self._session, self._workspace_id, actor_user_id=by)
        code = await open_code(await service.open_connector(source))
        branch = branch_of(change.title, change.id)
        try:
            # The branch as it is now: each file laid on it, never as it was
            # read when proposed (2026-10-20).
            sha = await code.head(change.repository, change.base_branch)
            changes, files = await _on_base(code, change, sha)
            opened = await code.open_pull_request(
                change.repository,
                base=change.base_branch,
                branch=branch,
                title=change.title,
                body=body_of(change, by=by_name),
                changes=changes,
                parent=sha,
            )
        except (CodeRefusedError, ChangeRefusedError) as refused:
            change.error, change.error_detail = refused.code, str(refused)[:2000]
            await self._session.commit()
            raise ChangeRefusedError(refused.code, str(refused)) from refused
        change.files = files
        change.follow = {"stage": "checks", "done": False, "checked_at": None}
        change.status = "applied"
        change.decided_by, change.decided_at = by, datetime.now(UTC)
        change.note = (note or "").strip()[:2000] or None
        change.branch, change.commit_sha = opened.branch, opened.commit
        change.pull_request_number, change.pull_request_url = opened.number, opened.url
        change.error = change.error_detail = None
        await self._session.commit()
        logger.info("code_change_applied", change=str(change.id), pull_request=opened.number)
        return change

    async def _code(self, change: CodeChange, by: uuid.UUID | None) -> GitHubCode:
        source = await self._session.get(Source, change.source_id)
        if source is None or source.status not in CONNECTED:
            raise ChangeRefusedError("no_source", "La source GitHub n'est plus connectée.")
        service = SourceService(self._session, self._workspace_id, actor_user_id=by)
        return await open_code(await service.open_connector(source))

    async def deploys(self, change: CodeChange) -> bool:
        """Whether its source lets LEKA start its deployment workflow."""
        source = await self._session.get(Source, change.source_id)
        config = (source.config or {}) if source is not None else {}
        return bool(config.get("deploys") and config.get("deploy_workflow"))

    async def reverting(self, change: CodeChange) -> CodeChange | None:
        """The change that undoes it, still proposed or applied."""
        found = await self._session.scalar(
            select(CodeChange)
            .where(
                CodeChange.workspace_id == self._workspace_id,
                CodeChange.reverts == change.id,
                CodeChange.status.in_(("proposed", "applied")),
            )
            .order_by(CodeChange.created_at.desc())
            .limit(1)
        )
        return found

    async def undo(self, change_id: uuid.UUID, *, by: uuid.UUID) -> CodeChange:
        """« Annuler ce changement » (2026-10-20). Its pull request not
        merged: closed — the change itself. Merged: the change that undoes
        it, proposed — each file back to what it was before it, laid on its
        branch as it is now; refused (`changed_since`) where the code moved
        since, never a newer work undone. Asked twice, the same one."""
        change = await self.change(change_id, lock=True)
        if change.status != "applied" or change.pull_request_number is None:
            raise ChangeRefusedError(
                "not_applied", "Ce changement n'a pas de pull request : rien à annuler."
            )
        already = await self.reverting(change)
        if already is not None:
            return already
        code = await self._code(change, by)
        number = change.pull_request_number
        try:
            seen = await code.follow(change.repository, number)
            if seen["state"] == "open":
                await code.close_pull_request(change.repository, number)
                change.follow = {
                    **(change.follow or {}),
                    "stage": "closed",
                    "done": True,
                    "checked_at": datetime.now(UTC).isoformat(),
                }
                await self._session.commit()
                logger.info("code_change_withdrawn", change=str(change.id), pull_request=number)
                return change
            if seen["state"] != "merged":
                raise ChangeRefusedError(
                    "already_closed",
                    "Sa pull request a été fermée sans être fusionnée : rien à annuler.",
                )
            sha = await code.head(change.repository, change.base_branch)
            files: list[dict[str, object]] = []
            moved: list[str] = []
            for f in change.files:
                path = str(f["path"])
                after = c if isinstance(c := f.get("content"), str) else None
                before, known = before_of(path, after, str(f.get("diff") or ""))
                now = await code.read(change.repository, path, sha)
                back, state = (
                    on_base(path, now, before, diff_of(path, after, before)[0])
                    if known
                    else (None, "moved")
                )
                if state == "moved":
                    moved.append(path)
                if state != "changes":
                    continue
                diff, added, removed = diff_of(path, now, back)
                kind = "added" if now is None else "deleted" if back is None else "modified"
                files.append(
                    {
                        "path": path,
                        "status": kind,
                        "content": back,
                        "diff": diff,
                        "additions": added,
                        "deletions": removed,
                        "why": f"revient à ce qu'il était avant la pull request #{number}",
                    }
                )
        except CodeRefusedError as refused:
            raise ChangeRefusedError(refused.code, str(refused)) from refused
        if moved:
            raise ChangeRefusedError(
                "changed_since",
                f"{', '.join(moved)} a changé sur {change.base_branch} depuis, là où ce changement "
                "l'avait modifié : LEKA ne peut pas l'annuler sans écraser ce travail.",
            )
        if not files:
            raise ChangeRefusedError(
                "already_applied", f"Ce changement n'est déjà plus sur {change.base_branch}."
            )
        revert = CodeChange(
            workspace_id=self._workspace_id,
            id=uuid.uuid4(),
            run_id=change.run_id,
            intention_id=change.intention_id,
            source_id=change.source_id,
            repository=change.repository,
            base_branch=change.base_branch,
            title=f"Annuler : {change.title}"[:300],
            summary=(
                f"Annule la pull request #{number} « {change.title} » : chaque fichier revient à "
                f"ce qu'il était avant elle, sur {change.base_branch} tel qu'il est maintenant."
            ),
            files=files,
            status="proposed",
            proposed_by=by,
            reverts=change.id,
        )
        self._session.add(revert)
        await self._session.commit()
        logger.info("code_change_undo_proposed", change=str(change.id), revert=str(revert.id))
        return revert

    async def go_back(self, change_id: uuid.UUID, *, by: uuid.UUID) -> CodeChange:
        """« Revenir à la version précédente » (2026-10-20): the repository's
        deployment workflow started for the version before its merge — the
        change stays on its branch until undone; kept (`rollbacks`) and
        followed until that run ends."""
        change = await self.change(change_id, lock=True)
        not_merged = ChangeRefusedError(
            "not_merged",
            "Ce changement n'est pas fusionné, ou sa version d'avant n'est pas connue : "
            "rien à redéployer.",
        )
        if change.status != "applied" or change.pull_request_number is None:
            raise not_merged
        rollbacks = list(change.rollbacks or [])
        if rollbacks and rollbacks[-1].get("state") in ("queued", "in_progress"):
            raise ChangeRefusedError("rolling_back", "Un retour en arrière est déjà en cours.")
        code = await self._code(change, by)
        follow = dict(change.follow or {})
        before = follow.get("before_sha")
        try:
            if not before:
                # Followed to the end before the version before was kept
                # (2026-10-21: the first change LEKA shipped): read now.
                seen = await code.follow(change.repository, change.pull_request_number)
                if seen["state"] == "merged":
                    before = seen.get("before_sha")
                    follow = {
                        **follow,
                        "merged_at": seen.get("merged_at"),
                        "merge_sha": seen.get("merge_sha"),
                        "before_sha": before,
                        "newer": seen.get("newer"),
                    }
            if not follow.get("merged_at") or not before:
                raise not_merged
            await code.redeploy(change.repository, ref=change.base_branch, version=str(before))
        except CodeRefusedError as refused:
            raise ChangeRefusedError(refused.code, str(refused)) from refused
        rollbacks.append(
            {
                "sha": before,
                "asked_at": datetime.now(UTC).isoformat(),
                "by": str(by),
                "state": "queued",
                "url": None,
                "at": None,
            }
        )
        change.rollbacks = rollbacks
        change.follow = {**follow, "stage": "rolling_back", "done": False}
        await self._session.commit()
        logger.info("code_change_rollback_asked", change=str(change.id), version=before)
        return change

    async def repair(
        self, change_id: uuid.UUID, *, by: uuid.UUID, now: datetime | None = None
    ) -> CodeChange:
        """« Réparer le problème » (2026-10-24), asked: kept running for a
        worker. Refused with no pull request to repair, merged, a repair
        running, three pushed already, or a source that does not let LEKA
        write."""
        moment = now or datetime.now(UTC)
        change = await self.change(change_id, lock=True)
        if change.status != "applied" or change.pull_request_number is None or not change.branch:
            raise ChangeRefusedError(
                "not_applied", "Ce changement n'a pas de pull request à réparer."
            )
        follow = dict(change.follow or {})
        if follow.get("merged_at") or follow.get("stage") in MERGED_STAGES:
            raise ChangeRefusedError(
                "merged",
                "Sa pull request est fusionnée : ce qui reste à corriger est un nouveau "
                "changement.",
            )
        repairs = list(change.repairs or [])
        last = repairs[-1] if repairs else None
        if last is not None and last.get("state") == "running":
            if moment - datetime.fromisoformat(str(last["asked_at"])) < REPAIR_LOST:
                raise ChangeRefusedError("repairing", "LEKA répare déjà cette pull request.")
            repairs[-1] = {
                **last,
                "state": "failed",
                "error": "error",
                "said": "Interrompue avant la fin.",
                "finished_at": moment.isoformat(),
            }
        if sum(1 for r in repairs if r.get("state") == "pushed") >= MAX_REPAIRS:
            raise ChangeRefusedError(
                "too_many_repairs",
                f"LEKA a déjà réparé cette pull request {MAX_REPAIRS} fois : regardez l'échec sur "
                "GitHub avant d'aller plus loin.",
            )
        if not await self.allowed(change):
            raise ChangeRefusedError(
                "pull_requests_off",
                "Cette source GitHub n'autorise pas LEKA à écrire sur ses pull requests : son "
                "admin l'active.",
            )
        checks = follow.get("checks")
        failed = (checks.get("failed") if isinstance(checks, dict) else None) or []
        repairs.append(
            {
                "state": "running",
                "asked_at": moment.isoformat(),
                "by": str(by),
                "failed": [str(name) for name in failed],
            }
        )
        change.repairs = repairs
        await self._session.commit()
        logger.info("code_change_repair_asked", change=str(change.id))
        return change

    async def repair_ended(
        self, change_id: uuid.UUID, state: str, **said: object
    ) -> dict[str, object]:
        """Its running repair, ended: how, and what it found."""
        change = await self.change(change_id, lock=True)
        await self._session.refresh(change)
        repairs = list(change.repairs or [])
        if repairs and repairs[-1].get("state") == "running":
            repairs[-1] = {
                **repairs[-1],
                **{k: v for k, v in said.items() if v is not None},
                "state": state,
                "finished_at": datetime.now(UTC).isoformat(),
            }
            change.repairs = repairs
        await self._session.commit()
        logger.info("code_change_repair_ended", change=str(change_id), state=state)
        return {"state": state, **{k: v for k, v in said.items() if k in ("error", "commit")}}

    async def _read_for_repair(
        self,
        code: GitHubCode,
        change: CodeChange,
        head: str,
        failures: Sequence[Mapping[str, Any]],
    ) -> dict[str, str]:
        """The files a repair is written from, as they are at the pull
        request's head: the change's own, then those what failed names —
        found as they are named, else under the folders the change's files
        are in (a test runner names them from its own folder)."""
        read: dict[str, str] = {}
        own = [str(f["path"]) for f in change.files if f.get("status") != "deleted"]
        folders = list(dict.fromkeys(p.split("/")[0] for p in own if "/" in p))
        for path in own:
            text = await code.read(change.repository, path, head)
            if text is not None:
                read[path] = text
        for cited in cited_paths(failures):
            if len(read) >= MAX_FILES:
                break
            tried = [cited, *(f"{d}/{cited}" for d in folders if not cited.startswith(f"{d}/"))]
            for path in tried:
                if path in read:
                    break
                try:
                    text = await code.read(change.repository, path, head)
                except CodeRefusedError:
                    text = None
                if text is not None:
                    read[path] = text
                    break
        return read

    async def repaired(
        self, change_id: uuid.UUID, *, budget: float = CHANGE_BUDGET
    ) -> dict[str, object]:
        """The repair asked, done: what failed read on GitHub, the files it
        names and the change's own read at the pull request's head, the
        model asked for the fix — its edits held to those files, asked
        again when they do not land — then applied here, one commit pushed
        on its branch, the pull request reopened first when closed. The
        change then holds its files as its pull request does."""
        change = await self.change(change_id)
        if not change.repairs or change.repairs[-1].get("state") != "running":
            return {"state": "not_asked"}
        repository, number, branch = change.repository, change.pull_request_number, change.branch
        if number is None or branch is None:
            return await self.repair_ended(change_id, "failed", error="not_applied")
        try:
            code = await self._code(change, None)
            seen = await code.follow(repository, number)
            if seen["state"] == "merged":
                return await self.repair_ended(
                    change_id,
                    "failed",
                    error="merged",
                    said="Sa pull request a été fusionnée entre-temps : rien à réparer sur sa "
                    "branche.",
                )
            head = str(seen.get("head_sha") or "")
            failures = await code.failures(repository, head)
            if not failures:
                return await self.repair_ended(
                    change_id,
                    "unneeded",
                    said="La CI ne signale plus d'échec sur la dernière version de la pull "
                    "request.",
                )
            read = await self._read_for_repair(code, change, head, failures)
        except (CodeRefusedError, ChangeRefusedError) as refused:
            return await self.repair_ended(
                change_id, "failed", error=refused.code, said=str(refused)[:500]
            )
        failed = [str(f.get("name") or "") for f in failures]
        definition = find("code-change")
        needs = (
            replace(needs_of(definition), tools=False)
            if definition is not None
            else Needs(structured=True, quality=3, task="code")
        )
        request = Request(
            purpose="agent:code-change:repair",
            messages=repair_messages(change, failures, read),
            tier=Tier.DEEP,
            max_tokens=CHANGE_TOKENS,
            ref=f"code_change:{change.id}",
        )
        try:
            answered = await asyncio.wait_for(
                Gateway(self._session, self._workspace_id).structured(
                    request,
                    RepairProposal,
                    needs,
                    verify=lambda proposal: repair_problems(proposal, read),
                ),
                timeout=budget,
            )
        except NoModelError as error:
            said = next((a.error for a in reversed(error.attempts) if a.error), None)
            logger.warning("code_change_repair_not_written", reason=error.reason, said=said)
            return await self.repair_ended(
                change_id,
                "failed",
                error=NO_MODEL.get(error.reason, "unanswered"),
                said="Aucun modèle n'est disponible dans cet espace."
                if error.reason == "none"
                else "Le modèle n'a pas écrit de correction qui s'applique aux fichiers.",
                failed=failed,
            )
        except TimeoutError:
            return await self.repair_ended(
                change_id,
                "failed",
                error="timeout",
                said="Le modèle n'a pas répondu à temps.",
                failed=failed,
            )
        proposal = answered.value
        model = answered.completion.model
        found = {
            "cause": proposal.cause.strip()[:2000],
            "summary": proposal.summary.strip()[:1000],
            "model": model,
            "failed": failed,
        }
        if not proposal.files:
            # The cause is not in the code: said, nothing written.
            return await self.repair_ended(change_id, "outside", **found)
        fixes: list[FileChange] = []
        for each in proposal.files[:MAX_FILES]:
            path = safe_path(each.path)
            if path is None or any(f.path == path for f in fixes):
                continue
            before = read.get(path)
            if each.delete:
                after: str | None = None
            elif each.edits:
                after = apply_edits(before, each.edits)[0] if before is not None else None
                if after is None:
                    continue
            elif each.content is not None:
                after = each.content
            else:
                continue
            if after != before:
                fixes.append(FileChange(path, after))
        if not fixes:
            return await self.repair_ended(
                change_id,
                "failed",
                error="edits_not_applied",
                said="Les corrections proposées ne s'appliquent pas aux fichiers de la pull "
                "request.",
                **found,
            )
        reopened = False
        try:
            if seen["state"] == "closed":
                await code.reopen_pull_request(repository, number)
                reopened = True
            sha = await code.push_commit(
                repository,
                branch=branch,
                parent=head,
                changes=fixes,
                message=_commit_message(proposal, failed, number),
            )
        except CodeRefusedError as refused:
            return await self.repair_ended(
                change_id,
                "failed",
                error=refused.code,
                said=str(refused)[:500],
                reopened=reopened,
                **found,
            )
        # Pushed. Its files, said against where its pull request started —
        # as they were when that cannot be read: the commit is there.
        base = next((str(r["base"]) for r in change.repairs or [] if r.get("base")), None)
        files = list(change.files)
        try:
            base = base or await code.parent_of(repository, change.commit_sha or head)
            files = await self._with_repair(code, change, base, fixes, proposal.summary)
        except CodeRefusedError:
            logger.warning("code_change_repair_files_not_read", change=str(change_id))
        repaired_files = []
        for fix in fixes:
            diff, added, removed = diff_of(fix.path, read.get(fix.path), fix.content)
            kind = (
                "added"
                if read.get(fix.path) is None
                else "deleted"
                if fix.content is None
                else "modified"
            )
            repaired_files.append(
                {
                    "path": fix.path,
                    "status": kind,
                    "diff": diff,
                    "additions": added,
                    "deletions": removed,
                    "why": "",
                }
            )
        change = await self.change(change_id, lock=True)
        # Read again, locked: the follow may have moved it meanwhile.
        await self._session.refresh(change)
        change.files = files
        change.commit_sha = sha
        change.follow = {
            **(change.follow or {}),
            "stage": "checks",
            "done": False,
            "checks": None,
            "error": None,
            "checked_at": None,
        }
        await self._session.flush()
        return await self.repair_ended(
            change_id,
            "pushed",
            commit=sha,
            base=base,
            reopened=reopened,
            files=repaired_files,
            **found,
        )

    async def _with_repair(
        self,
        code: GitHubCode,
        change: CodeChange,
        base: str | None,
        fixes: Sequence[FileChange],
        summary: str,
    ) -> list[dict[str, object]]:
        """The change's files as its pull request holds them after a repair:
        each file it fixed said against where the pull request started — the
        change's own updated, a new one added, one back as it was dropped —
        so that undoing it undoes the repair too."""
        files = [dict(f) for f in change.files]
        for fix in fixes:
            before = await code.read(change.repository, fix.path, base) if base else None
            at = next((i for i, f in enumerate(files) if f.get("path") == fix.path), None)
            if fix.content == before:
                if at is not None:
                    files.pop(at)
                continue
            diff, added, removed = diff_of(fix.path, before, fix.content)
            entry: dict[str, object] = {
                "path": fix.path,
                "status": "added"
                if before is None
                else "deleted"
                if fix.content is None
                else "modified",
                "content": fix.content,
                "diff": diff,
                "additions": added,
                "deletions": removed,
                "why": str(files[at].get("why") or "")
                if at is not None
                else f"réparation : {summary}"[:500],
            }
            if at is None:
                files.append(entry)
            else:
                files[at] = entry
        return files

    async def follow(
        self, change_id: uuid.UUID, *, now: datetime | None = None, unless_within: float = 0
    ) -> CodeChange:
        """Its pull request read again on GitHub — read only — and where it
        stands kept; a read that fails is said, the last word kept. Not
        again when read less than `unless_within` seconds ago."""
        moment = now or datetime.now(UTC)
        change = await self.change(change_id, lock=True)
        checked = (change.follow or {}).get("checked_at")
        if (
            isinstance(checked, str)
            and unless_within
            and (moment - datetime.fromisoformat(checked)).total_seconds() < unless_within
        ):
            return change
        await self._observe(change, now=moment)
        await self._session.commit()
        return change

    async def _observe(self, change: CodeChange, *, now: datetime) -> None:
        if change.status != "applied" or change.pull_request_number is None:
            return
        last = dict(change.follow or {})
        source = await self._session.get(Source, change.source_id)
        try:
            if source is None or source.status not in CONNECTED:
                raise CodeRefusedError("no_source", "La source GitHub n'est plus connectée.")
            service = SourceService(self._session, self._workspace_id, actor_user_id=None)
            code = await open_code(await service.open_connector(source))
            seen = await code.follow(change.repository, change.pull_request_number)
            rollbacks = list(change.rollbacks or [])
            if rollbacks and rollbacks[-1].get("state") in ("queued", "in_progress"):
                asked = datetime.fromisoformat(str(rollbacks[-1]["asked_at"]))
                run = await code.redeployed(change.repository, (asked - RUN_SLACK).isoformat())
                if run is not None:
                    rollbacks[-1] = {**rollbacks[-1], **run}
                    change.rollbacks = rollbacks
        except CodeRefusedError as refused:
            change.follow = {**last, "error": str(refused)[:300], "checked_at": now.isoformat()}
            return
        except Exception:
            logger.exception("code_change_not_followed", change=str(change.id))
            change.follow = {
                **last,
                "error": "GitHub n'a pas répondu.",
                "checked_at": now.isoformat(),
            }
            return
        opened_at = change.decided_at or change.created_at
        stage = stage_of(seen, opened_at=opened_at, now=now)
        if rollbacks and seen["state"] == "merged":
            # Gone back to the version before it: that run says where it is.
            stage = ROLLED.get(str(rollbacks[-1].get("state")), "rolling_back")
        merged_at = seen.get("merged_at")
        quiet = (
            stage == "merged"
            and isinstance(merged_at, str)
            and now - datetime.fromisoformat(merged_at.replace("Z", "+00:00")) > QUIET_AFTER_MERGE
        )
        change.follow = {
            "stage": stage,
            "done": stage in FOLLOW_DONE or quiet or now - opened_at > FOLLOW_FOR,
            "checks": seen.get("checks") or last.get("checks"),
            "merged_at": merged_at,
            "merge_sha": seen.get("merge_sha"),
            "before_sha": seen.get("before_sha") or last.get("before_sha"),
            "newer": seen.get("newer", last.get("newer")),
            "deployment": seen.get("deployment"),
            "error": None,
            "checked_at": now.isoformat(),
        }
        if stage != last.get("stage"):
            logger.info("code_change_followed", change=str(change.id), stage=stage)


# ── a pull request in red, repaired on asking (2026-10-24) ──────────────────

# Repairs pushed on one pull request, at most: past that, a person looks.
MAX_REPAIRS = 3
# Asked longer ago and not done: lost (a worker gone) — asked again.
REPAIR_LOST = timedelta(minutes=20)
REPAIR_JOB = "leka.capabilities.changes.repair_change_job"
# The files what failed names, read at the pull request's head, at most —
# beyond the change's own.
MAX_CITED = 8
# The change's diff as the repair writer is shown it, at most.
MOST_DIFF_SHOWN = 40_000
# After a merge: nothing left to repair on its branch.
MERGED_STAGES = frozenset(
    {
        "merged",
        "deploying",
        "deployed",
        "deploy_failed",
        "rolling_back",
        "rolled_back",
        "rollback_failed",
    }
)
_CITED = re.compile(
    r"[\w.@/-]+\.(?:tsx?|jsx?|mjs|cjs|py|css|scss|html|json|ya?ml|toml|sql|go|rs|java|kt|"
    r"rb|php|cs|vue|svelte)\b"
)
# Where a runner checks a repository out: /home/runner/work/<repo>/<repo>/.
_RUNNER = re.compile(r"^.*?/work/[^/]+/[^/]+/")
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)
_NOT_OURS = ("node_modules/", "site-packages/", ".venv/", "dist-packages/", "/usr/")


class RepairProposal(BaseModel):
    """What the model proposes to fix a pull request in red."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    cause: str = Field(
        default="",
        description="Ce qui a échoué et pourquoi, en une ou deux phrases, pour la personne qui "
        "décide.",
    )
    summary: str = Field(default="", description="Ce que la réparation change, en une phrase.")
    files: list[ProposedFile] = Field(
        default_factory=list,
        description="Chaque fichier à corriger, par remplacements ; aucun quand la cause n'est "
        "pas dans le code (un runner en panne, un secret manquant).",
    )


REPAIR_RULES = """You are LEKA's repair writer. A pull request LEKA opened, \
for a change a person accepted, failed its checks. You are given the change \
(its title, its summary, its diff), what failed — each check, its \
annotations (file, line, message), the end of its log — and the files at \
the pull request's head. Find why the checks fail and write the smallest fix \
that makes them pass while keeping what the change was for, as one JSON \
object:
- cause: what failed and why, in one or two sentences, in the language of \
the change's summary.
- summary: what the fix changes, in one sentence, in that language.
- files: each file to fix, by edits — each `find` a text copied exactly from \
that file as you were given it, whole lines, enough of them to appear only \
once; `replace` what stands there after. A new file gives its whole \
`content`. Only files you were given, or new ones.
Rules:
- Fix the cause, never hide it: never delete, skip or weaken a test, an \
assertion, a lint rule or a type check to make it pass, and never add an \
ignore comment (eslint-disable, @ts-ignore, type: ignore, noqa).
- When the change moved or renamed something a test relies on — an id, a \
data-testid, a label, an export, a name — keep it in the new code where it \
still makes sense; when the change meant to change what the test checks, \
update the test to the new behaviour, as strict as it was.
- When the failure is not in the code — a runner down, a secret missing, a \
service that did not start, a network error — give no files, and say so in \
cause.
Answer with the JSON object only.

Never write the em dash « — »: a colon, a comma, a semicolon or \
parentheses, as the sentence needs."""


def cited_paths(failures: Sequence[Mapping[str, Any]]) -> list[str]:
    """The files what failed names — its annotations first, then their
    messages, its summary, its log — as paths in the repository where they
    can be told, in order: never a dependency's own."""
    named: list[str] = []

    def files_in(text: object) -> list[str]:
        # An address is not a file of the repository.
        return list(_CITED.findall(_URL.sub(" ", str(text or ""))))

    for failure in failures:
        for note in failure.get("annotations") or []:
            named.append(str(note.get("path") or ""))
            named += files_in(note.get("message"))
        named += files_in(failure.get("summary"))
        named += files_in(failure.get("log"))
    found: list[str] = []
    for said in named:
        path = safe_path(_RUNNER.sub("", said).lstrip("/"))
        if (
            path is None
            or "/" not in path
            or "." not in path.rsplit("/", 1)[-1]
            or any(part in f"/{path}" for part in _NOT_OURS)
        ):
            continue
        found.append(path)
    return list(dict.fromkeys(found))[:MAX_CITED]


def repair_problems(proposal: RepairProposal, read: Mapping[str, str]) -> list[str]:
    """Why a repair cannot be applied as written, file by file — each edit
    held to the file as the writer was given it (2026-10-24: a cheap model
    is asked again, told why, rather than its fix lost)."""
    problems: list[str] = []
    for each in proposal.files:
        path = safe_path(each.path)
        if path is None:
            problems.append(f"{each.path}: not a path in the repository.")
        elif each.edits and path not in read:
            problems.append(f"{path}: you were not given this file; edit only those you were.")
        elif each.edits:
            _after, why = apply_edits(read[path], each.edits)
            if why is not None:
                where = "there more than once" if why == "ambiguous" else "not in the file"
                problems.append(
                    f"{path}: an edit's `find` is {where} as you were given it — copy whole "
                    "lines exactly."
                )
    return problems


def repair_messages(
    change: CodeChange, failures: Sequence[Mapping[str, Any]], read: Mapping[str, str]
) -> list[Message]:
    diff = "\n".join(str(f.get("diff") or "") for f in change.files)
    material = {
        "change": {
            "repository": change.repository,
            "title": change.title,
            "summary": change.summary,
            "diff": diff[:MOST_DIFF_SHOWN],
        },
        "failed": [
            {
                "check": f.get("name"),
                "summary": f.get("summary"),
                "annotations": f.get("annotations") or [],
                "log": f.get("log") or "",
            }
            for f in failures
        ],
        "files": shown(read),
    }
    return [
        Message.system(REPAIR_RULES),
        Message.user(json.dumps(material, ensure_ascii=False, default=str)),
    ]


def _commit_message(proposal: RepairProposal, failed: Sequence[str], number: int) -> str:
    first = (proposal.summary or proposal.cause).strip().split("\n")[0][:72] or "Réparer la CI"
    return (
        f"{first}\n\n{proposal.cause.strip()}\n\n"
        f"Réparation par LEKA de la pull request #{number} : {', '.join(failed)} en échec."
    )


async def repair_change(workspace_id: uuid.UUID, change_id: uuid.UUID) -> dict[str, object]:
    """A repair asked, done by a worker; whatever goes wrong, said in it."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = ChangeService(session, workspace_id)
            try:
                return await service.repaired(change_id)
            except Exception:
                logger.exception("code_change_not_repaired", change=str(change_id))
                await session.rollback()
                return await service.repair_ended(
                    change_id,
                    "failed",
                    error="error",
                    said="La réparation s'est arrêtée sur une erreur de LEKA.",
                )


def repair_change_job(workspace_id: str, change_id: str) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(repair_change(uuid.UUID(workspace_id), uuid.UUID(change_id)))


async def queue_repair(workspace_id: uuid.UUID, change_id: uuid.UUID) -> bool:
    """Its repair, for a worker: the model takes minutes."""
    queued = await enqueue_job(
        REPAIR_JOB,
        str(workspace_id),
        str(change_id),
        for_workspace_id=workspace_id,
        queue=JobQueue.HIGH,
        concurrency_key=f"code-change-repair:{change_id}",
    )
    return queued is not None


async def follow_pull_requests(*, now: datetime | None = None) -> dict[str, int]:
    """Every pull request LEKA opened and still follows, read again."""
    moment = now or datetime.now(UTC)
    with system_scope():
        async with session_factory() as session:
            due = (
                (
                    await session.execute(
                        select(CodeChange.workspace_id, CodeChange.id).where(
                            CodeChange.status == "applied",
                            CodeChange.pull_request_number.is_not(None),
                            CodeChange.decided_at > moment - FOLLOW_FOR,
                            or_(
                                CodeChange.follow.is_(None),
                                CodeChange.follow["done"].astext.is_distinct_from("true"),
                            ),
                        )
                    )
                )
                .tuples()
                .all()
            )
    counts = {"followed": 0}
    for workspace_id, change_id in due:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                await ChangeService(session, workspace_id).follow(change_id, now=moment)
                counts["followed"] += 1
    if counts["followed"]:
        logger.info("code_changes_followed", **counts)
    return counts


def run_follow_sweep() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(follow_pull_requests())


def files_read(files: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """A change's files as the API says them: no content, its diff."""
    return [
        {
            "path": str(f.get("path")),
            "status": str(f.get("status")),
            "additions": int(str(f.get("additions") or 0)),
            "deletions": int(str(f.get("deletions") or 0)),
            "diff": str(f.get("diff") or ""),
            "why": str(f.get("why") or ""),
        }
        for f in files
    ]


__all__ = [
    "MAX_FILES",
    "MAX_REPAIRS",
    "ChangeDecidedError",
    "ChangeNotFoundError",
    "ChangeProposal",
    "ChangeRefusedError",
    "ChangeService",
    "Edit",
    "Proposed",
    "ProposedFile",
    "RepairProposal",
    "apply_edits",
    "before_of",
    "body_of",
    "branch_of",
    "change_problems",
    "cited_paths",
    "code_for",
    "code_of",
    "diff_of",
    "files_named",
    "files_read",
    "follow_pull_requests",
    "on_base",
    "propose_change",
    "queue_repair",
    "repair_change",
    "repair_change_job",
    "repair_problems",
    "repositories_here",
    "repository_for",
    "repository_named",
    "reversed_diff",
    "run_follow_sweep",
    "safe_path",
    "stage_of",
]
