"""Code changes LEKA proposes — the code-change agent (`renders: code_change`).

    the run's analysis   markdown: what to change and why, from the code it
                         read (list_files, read_file — code_tools.py)
        ──▶ the model again, no tools: the change, structured
            (ChangeProposal): the repository, the branch, each file as it
            would be — whole
        ──▶ each file read again on that branch: its diff, computed here,
            never the model's (a file it says changed but did not is left out)
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
CHANGE_TOKENS = 16_000
CHANGE_BUDGET = 8 * 60.0
# A diff kept, at most, per file.
MAX_DIFF_CHARS = 120_000
CONNECTED = (SourceStatus.ACTIVE, SourceStatus.DEGRADED)


class ProposedFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    path: str = Field(description="Le chemin du fichier dans le dépôt, ex. « api/app/main.py ».")
    content: str | None = Field(
        description="Le contenu COMPLET du fichier après la modification — pas un extrait, "
        "pas un diff. null pour supprimer le fichier."
    )
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
    if not said or said.startswith("/") or len(said) > 400 or not _SEGMENT.match(said):
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


def branch_of(title: str, change_id: uuid.UUID) -> str:
    """leka/<the title, as a slug>-<its id>: new, never one that exists."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "change"
    return f"leka/{slug}-{change_id.hex[:8]}"


CHANGE_RULES = """You are LEKA's change writer for the agent whose instructions \
follow. From its analysis — and from nothing else — write the change it \
proposes, as one JSON object:
- repository: the full name (owner/repo) the analysis read; base_branch: \
the branch it read, or empty for the default one.
- files: each file to change, add or remove, with its COMPLETE new content \
— the whole file as it must be after the change, every line, never an \
excerpt, never « … », never a diff. null removes the file. At most 20 files; \
only the files the analysis says must change.
- title: a short pull request title in the imperative; summary: what changes \
and why, for the person who decides, in the language of the inputs.
Never invent a file's content you did not read: a file the analysis did not \
read is not changed. Answer with the JSON object only."""


def change_messages(
    definition: Definition, inputs: Mapping[str, object], analysis: str
) -> list[Message]:
    system = f"{CHANGE_RULES}\n\n---\n\n{definition.instructions or ''}"
    material = {"inputs": dict(inputs), "analysis": analysis}
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


async def propose_change(
    session: AsyncSession,
    run: AgentRun,
    definition: Definition,
    analysis: str,
    *,
    budget: float = CHANGE_BUDGET,
) -> Proposed:
    """The change a run's analysis proposes, written, diffed and kept."""
    request = Request(
        purpose=f"agent:{definition.key}:change"[:100],
        messages=change_messages(definition, run.inputs, analysis),
        tier=Tier.DEEP,
        max_tokens=CHANGE_TOKENS,
        ref=f"agent_run:{run.id}",
    )
    try:
        answered = await asyncio.wait_for(
            Gateway(session, run.workspace_id).structured(
                request, ChangeProposal, replace(needs_of(definition), tools=False)
            ),
            timeout=budget,
        )
    except NoModelError as error:
        logger.warning("change_not_written", run=str(run.id), reason=error.reason)
        return Proposed(None, "no_model")
    except TimeoutError:
        return Proposed(None, "timeout")
    proposal = answered.value
    done = answered.completion
    usage = {
        "provider": done.provider,
        "model": done.model,
        "tokens_in": done.usage.tokens_in,
        "tokens_out": done.usage.tokens_out,
    }
    found = await code_for(session, run.workspace_id, proposal.repository.strip())
    if found is None:
        return Proposed(None, "no_repository", usage)
    source, code = found
    repository = proposal.repository.strip()
    try:
        base = proposal.base_branch.strip() or await code.default_branch(repository)
        files: list[dict[str, object]] = []
        for proposed in proposal.files[:MAX_FILES]:
            path = safe_path(proposed.path)
            if path is None or any(f["path"] == path for f in files):
                continue
            before = await code.read(repository, path, base)
            after = proposed.content
            if before == after or (before is None and after is None):
                continue
            diff, added, removed = diff_of(path, before, after)
            files.append(
                {
                    "path": path,
                    "status": "added"
                    if before is None
                    else "deleted"
                    if after is None
                    else "modified",
                    "content": after,
                    "diff": diff,
                    "additions": added,
                    "deletions": removed,
                    "why": proposed.why[:500],
                }
            )
    except CodeRefusedError as refused:
        logger.warning("change_not_read", run=str(run.id), code=refused.code)
        return Proposed(None, refused.code, usage)
    if not files:
        return Proposed(None, "no_change", usage)
    change = CodeChange(
        workspace_id=run.workspace_id,
        id=uuid.uuid4(),
        run_id=run.id,
        intention_id=run.intention_id,
        source_id=source.id,
        repository=repository,
        base_branch=base[:200],
        title=proposal.title.strip()[:300] or "Modification proposée par LEKA",
        summary=proposal.summary.strip(),
        files=files,
        status="proposed",
        proposed_by=run.requested_by,
    )
    session.add(change)
    await session.flush()
    return Proposed(change, None, usage)


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
        f"Proposée par LEKA (agent `code-change`), acceptée par {by}. "
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
    "Proposed",
    "ProposedFile",
    "body_of",
    "branch_of",
    "code_for",
    "diff_of",
    "files_read",
    "propose_change",
    "safe_path",
]
