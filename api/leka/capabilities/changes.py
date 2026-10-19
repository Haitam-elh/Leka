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

An agent proposes, people decide (ADR 004): nothing reaches a repository
before a person accepted it, and then only as a pull request someone else
reviews and merges.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import posixpath
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.catalogue import needs_of
from leka.capabilities.definition import Definition
from leka.capabilities.gateway import Gateway, Message, NoModelError, Request, Tier
from leka.capabilities.models import AgentRun, CodeChange
from leka.connectors import (
    CodeRefusedError,
    FileChange,
    GitHubCode,
    Source,
    SourceKind,
    SourceService,
    SourceStatus,
    open_code,
)

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
CHANGE_TOKENS = 48_000
CHANGE_BUDGET = 8 * 60.0
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
    edits: list[Edit] = Field(
        default_factory=list,
        description="Un fichier qui existe : ses remplacements, dans l'ordre — jamais le fichier "
        "entier.",
    )
    content: str | None = Field(
        default=None, description="Seulement pour un fichier nouveau : son contenu complet."
    )
    delete: bool = Field(default=False, description="true pour supprimer le fichier.")
    why: str = Field(default="", description="Pourquoi ce fichier change, en une phrase.")


class ChangeProposal(BaseModel):
    """What the model proposes to change."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    repository: str = Field(description="Le dépôt, en nom complet : « owner/repo ».")
    base_branch: str = Field(
        default="", description="La branche lue et visée ; vide : sa branche par défaut."
    )
    title: str = Field(description="Le titre de la pull request, court, à l'impératif.")
    summary: str = Field(description="Ce qui change et pourquoi, pour la personne qui décide.")
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
changed. Answer with the JSON object only."""


def shown(read: Mapping[str, str]) -> dict[str, str]:
    """The files the agent read, as the writer is shown them: each whole up
    to MOST_SHOWN, all up to MOST_SHOWN_ALL — the last ones read left out
    first, said so."""
    given: dict[str, str] = {}
    left = MOST_SHOWN_ALL
    for name, text in read.items():
        if left <= 0:
            given[name] = "[non montré : trop de fichiers lus]"
            continue
        cut = text[: min(MOST_SHOWN, left)]
        given[name] = cut if len(cut) == len(text) else cut + "\n[… coupé]"
        left -= len(cut)
    return given


def change_messages(
    definition: Definition,
    inputs: Mapping[str, object],
    analysis: str,
    read: Mapping[str, str] | None = None,
) -> list[Message]:
    system = f"{CHANGE_RULES}\n\n---\n\n{definition.instructions or ''}"
    # The files it read, keyed « owner/repo:path »: what the edits copy from.
    material = {"inputs": dict(inputs), "analysis": analysis, "files": shown(read or {})}
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


async def code_for(
    session: AsyncSession, workspace_id: uuid.UUID, repository: str
) -> tuple[Source, GitHubCode] | None:
    """The workspace's GitHub source whose scope holds this repository, and
    its code — None when none does."""
    service = SourceService(session, workspace_id, actor_user_id=None)
    for source in await github_sources(session, workspace_id):
        code = await open_code(await service.open_connector(source))
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


async def propose_change(
    session: AsyncSession,
    run: AgentRun,
    definition: Definition,
    analysis: str,
    *,
    read: Mapping[str, str] | None = None,
    budget: float = CHANGE_BUDGET,
) -> Proposed:
    """The change a run's analysis proposes, applied, diffed and kept:

    1. its own diff, when it holds one that lands whole on the files read
       again — no model asked again;
    2. else the model, given the analysis and the files the agent read — or,
       none kept, the files the analysis names, read again;
    3. the model failing, what of its own diff did land."""
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
    request = Request(
        purpose=f"agent:{definition.key}:change"[:100],
        messages=change_messages(definition, run.inputs, analysis, read),
        tier=Tier.DEEP,
        max_tokens=CHANGE_TOKENS,
        ref=f"agent_run:{run.id}",
    )
    failed: Proposed | None = None
    try:
        answered = await asyncio.wait_for(
            Gateway(session, run.workspace_id).structured(
                request, ChangeProposal, replace(needs_of(definition), tools=False)
            ),
            timeout=budget,
        )
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
    proposal = answered.value
    done = answered.completion
    usage = {
        "provider": done.provider,
        "model": done.model,
        "tokens_in": done.usage.tokens_in,
        "tokens_out": done.usage.tokens_out,
    }
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


def body_of(change: CodeChange, *, by: str) -> str:
    files = "\n".join(
        f"- `{f['path']}` ({f['status']}, +{f['additions']} -{f['deletions']})"
        + (f" — {f['why']}" if f.get("why") else "")
        for f in change.files
    )
    return (
        f"{change.summary}\n\n### Fichiers\n{files}\n\n---\n"
        f"Proposée par LEKA, acceptée par {by}. "
        "LEKA ouvre la pull request ; la relire et la fusionner reste votre décision."
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
            opened = await code.open_pull_request(
                change.repository,
                base=change.base_branch,
                branch=branch,
                title=change.title,
                body=body_of(change, by=by_name),
                changes=[
                    FileChange(str(f["path"]), c if isinstance(c := f["content"], str) else None)
                    for f in change.files
                ],
            )
        except CodeRefusedError as refused:
            change.error, change.error_detail = refused.code, str(refused)[:2000]
            await self._session.commit()
            raise ChangeRefusedError(refused.code, str(refused)) from refused
        change.status = "applied"
        change.decided_by, change.decided_at = by, datetime.now(UTC)
        change.note = (note or "").strip()[:2000] or None
        change.branch, change.commit_sha = opened.branch, opened.commit
        change.pull_request_number, change.pull_request_url = opened.number, opened.url
        change.error = change.error_detail = None
        await self._session.commit()
        logger.info("code_change_applied", change=str(change.id), pull_request=opened.number)
        return change


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
    "ChangeDecidedError",
    "ChangeNotFoundError",
    "ChangeProposal",
    "ChangeRefusedError",
    "ChangeService",
    "Edit",
    "Proposed",
    "ProposedFile",
    "apply_edits",
    "body_of",
    "branch_of",
    "code_for",
    "diff_of",
    "files_named",
    "files_read",
    "propose_change",
    "safe_path",
]
