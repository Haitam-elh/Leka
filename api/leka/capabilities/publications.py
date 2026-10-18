"""What LEKA proposes to send out of a run's deliverable (2026-10-18): tickets
for a Jira project, pages for a Confluence space.

    a person asks, from a finished run           (POST /agent-runs/{id}/publications)
        ──▶ kept, drafting; a worker drafts it: the model again, no tools,
            from what the agent delivered — the tickets (title, description,
            kind, priority, labels) or the pages (title, body), in markdown
        ──▶ proposed: shown, each ticket or page to keep or leave
    a person who may approve (intention:approve) accepts the ones chosen
        ──▶ LEKA creates them through the source — only when its admin
            allowed it (`issues`, `pages`), only in the project or space it
            reads; each with its key or page, or why not — applied, partly
            or failed; or rejects them, said why.

An agent proposes, people decide (ADR 004): nothing reaches Jira or
Confluence before a person accepted it, and then only new issues and new
pages — never an edit, never a deletion.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import JobQueue, enqueue_job
from leka.capabilities.catalogue import needs_of
from leka.capabilities.definition import Definition
from leka.capabilities.gateway import Gateway, Message, Needs, NoModelError, Request, Tier
from leka.capabilities.models import AgentRun, Publication
from leka.connectors import (
    ConfluencePages,
    JiraIssues,
    PublishRefusedError,
    Source,
    SourceKind,
    SourceService,
    SourceStatus,
    open_issues,
    open_pages,
)
from leka.db import session_factory, workspace_scope

logger = structlog.get_logger(__name__)

KINDS: Mapping[str, SourceKind] = {"issues": SourceKind.JIRA, "pages": SourceKind.CONFLUENCE}
FLAGS: Mapping[str, str] = {"issues": "issues", "pages": "pages"}
DRAFT_JOB = "leka.capabilities.publications.draft_job"
DRAFT_TOKENS = 12_000
DRAFT_BUDGET = 5 * 60.0
MOST_ISSUES = 15
MOST_PAGES = 10
# What the writer is given of the deliverable, at most.
MOST_DELIVERED = 80_000
CONNECTED = (SourceStatus.ACTIVE, SourceStatus.DEGRADED)
# A Jira project's key, a Confluence space's (a personal one starts with ~),
# as the connectors check them: what a target may be — it goes into an address.
PROJECT = re.compile(r"[A-Z][A-Z0-9_]{0,254}")
SPACE = re.compile(r"~?[A-Za-z0-9_]{1,255}")


class ProposedIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    title: str = Field(max_length=255, description="Le titre du ticket, court et actionnable.")
    description: str = Field(
        max_length=8_000,
        description="En markdown : le contexte, ce qu'il faut faire, les critères d'acceptation, "
        "et l'emplacement dans le code quand le livrable le donne (fichier:ligne).",
    )
    kind: Literal["task", "bug", "story"] = Field(default="task")
    priority: Literal["highest", "high", "medium", "low", "lowest"] = Field(default="medium")
    labels: list[str] = Field(default_factory=list, max_length=5)


class IssuesDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    title: str = Field(max_length=300, description="Ce que ces tickets traitent, en une ligne.")
    summary: str = Field(default="", max_length=2_000)
    issues: list[ProposedIssue] = Field(min_length=1, max_length=MOST_ISSUES)


class ProposedPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    title: str = Field(max_length=255, description="Le titre de la page.")
    body: str = Field(max_length=60_000, description="La page entière, en markdown.")


class PagesDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    title: str = Field(max_length=300, description="Ce que ces pages documentent, en une ligne.")
    summary: str = Field(default="", max_length=2_000)
    pages: list[ProposedPage] = Field(min_length=1, max_length=MOST_PAGES)


ISSUES_RULES = """You are LEKA's ticket writer. From the deliverable of the \
agent below — and from nothing else — write the tickets a team would open \
in Jira to act on it, as one JSON object:
- one ticket per thing to do: a finding to fix, a gap to close, a decision \
to take; the most important first; at most fifteen; none for what the \
deliverable says is already right;
- title: short, actionable, in the imperative; description in markdown: the \
context, what to do, acceptance criteria as a checklist, and where it is \
(file and line, the screen, the service) when the deliverable says it;
- kind: bug for something broken, story for a capability to add, task \
otherwise; priority from the deliverable's severity (critical or high: \
highest or high; medium; low or polish: low);
- labels: a few lowercase words, no spaces;
- title and summary of the whole set;
- in the language of the deliverable. Never invent a file, a person, a date \
or a figure the deliverable does not hold. Answer with the JSON object only."""

PAGES_RULES = """You are LEKA's documentation writer. From the deliverable \
of the agent below — and from nothing else — write the Confluence pages a \
team would publish from it, as one JSON object:
- a few pages, each a whole document in markdown with headings, lists, \
tables and code blocks where they help: what the thing is, how it is built \
and works, how to use or operate it, its decisions and its limits — as the \
deliverable says them; at most ten pages, one when one is enough;
- title of each page, specific (never « Documentation »); title and summary \
of the whole set;
- in the language of the deliverable. Never invent a file, a person, a date \
or a figure the deliverable does not hold; what it lacks is said as a point \
to complete. Answer with the JSON object only."""


class PublicationNotFoundError(LookupError):
    pass


class PublicationDecidedError(Exception):
    """It is no longer proposed: drafting still, or decided already."""


class PublicationRefusedError(Exception):
    """Why it cannot be asked or sent: not_finished, no_source, wrong_source,
    out_of_scope, issues_off, pages_off — or what Atlassian said."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def draft_messages(
    kind: str, definition: Definition | None, run: AgentRun, target: str
) -> list[Message]:
    rules = ISSUES_RULES if kind == "issues" else PAGES_RULES
    agent = definition.title if definition is not None else run.key
    material = {
        "agent": agent,
        "inputs": dict(run.inputs or {}),
        "target": target,
        "deliverable": (run.output or "")[:MOST_DELIVERED],
    }
    return [
        Message.system(rules),
        Message.user(json.dumps(material, ensure_ascii=False, default=str)),
    ]


def items_of(kind: str, draft: IssuesDraft | PagesDraft) -> list[dict[str, object]]:
    """The draft's tickets or pages, each with an id a person chooses by."""
    if isinstance(draft, IssuesDraft):
        return [
            {
                "id": uuid.uuid4().hex[:12],
                "title": issue.title.strip(),
                "body": issue.description.strip(),
                "kind": issue.kind,
                "priority": issue.priority,
                "labels": [label.strip().lower() for label in issue.labels if label.strip()],
            }
            for issue in draft.issues
        ]
    return [
        {"id": uuid.uuid4().hex[:12], "title": page.title.strip(), "body": page.body.strip()}
        for page in draft.pages
    ]


class PublicationService:
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def publications(
        self, *, run_id: uuid.UUID | None = None, intention_id: uuid.UUID | None = None
    ) -> list[Publication]:
        query = select(Publication).where(Publication.workspace_id == self._workspace_id)
        if run_id is not None:
            query = query.where(Publication.run_id == run_id)
        if intention_id is not None:
            query = query.where(Publication.intention_id == intention_id)
        found = await self._session.scalars(query.order_by(Publication.created_at.desc()).limit(50))
        return list(found)

    async def publication(self, publication_id: uuid.UUID, *, lock: bool = False) -> Publication:
        query = select(Publication).where(
            Publication.workspace_id == self._workspace_id, Publication.id == publication_id
        )
        found = await self._session.scalar(query.with_for_update() if lock else query)
        if found is None:
            raise PublicationNotFoundError(str(publication_id))
        return found

    async def _source(self, source_id: uuid.UUID, kind: str) -> Source:
        source = await self._session.get(Source, source_id)
        if source is None or source.workspace_id != self._workspace_id:
            raise PublicationRefusedError("no_source", "Cette source n'existe pas dans l'espace.")
        if source.kind != KINDS[kind]:
            raise PublicationRefusedError("wrong_source", "Cette source n'est pas du bon type.")
        if source.status not in CONNECTED:
            raise PublicationRefusedError("no_source", "Cette source n'est plus connectée.")
        return source

    async def allowed(self, publication: Publication) -> bool:
        """Whether its source lets LEKA create issues, or publish pages."""
        source = await self._session.get(Source, publication.source_id)
        return bool(source is not None and (source.config or {}).get(FLAGS[publication.kind]))

    async def ask(
        self,
        run: AgentRun,
        *,
        kind: str,
        source_id: uuid.UUID,
        target: str,
        by: uuid.UUID,
    ) -> Publication:
        """A publication of tickets or pages from a finished run, to draft."""
        if run.status != "succeeded" or not run.output:
            raise PublicationRefusedError("not_finished", "Ce livrable n'est pas terminé.")
        source = await self._source(source_id, kind)
        said = target.strip()
        key = said.upper() if kind == "issues" else said
        listed = (source.config or {}).get("projects" if kind == "issues" else "spaces")
        shaped = (PROJECT if kind == "issues" else SPACE).fullmatch(key)
        if not shaped or (isinstance(listed, list) and key not in listed):
            raise PublicationRefusedError(
                "out_of_scope",
                "Ce projet n'est pas lu par la source Jira."
                if kind == "issues"
                else "Cet espace n'est pas lu par la source Confluence.",
            )
        publication = Publication(
            workspace_id=self._workspace_id,
            run_id=run.id,
            intention_id=run.intention_id,
            kind=kind,
            source_id=source.id,
            target=key,
            status="drafting",
            proposed_by=by,
        )
        self._session.add(publication)
        await self._session.flush()
        return publication

    async def reject(
        self, publication_id: uuid.UUID, *, by: uuid.UUID, note: str | None
    ) -> Publication:
        publication = await self.publication(publication_id, lock=True)
        if publication.status != "proposed":
            raise PublicationDecidedError(publication.status)
        publication.status = "rejected"
        publication.decided_by, publication.decided_at = by, datetime.now(UTC)
        publication.note = (note or "").strip()[:2000] or None
        await self._session.commit()
        return publication

    async def accept(
        self,
        publication_id: uuid.UUID,
        *,
        by: uuid.UUID,
        chosen: Sequence[str] | None,
        note: str | None,
    ) -> Publication:
        """The tickets or pages chosen, created — each with its key or page,
        or why not. Refused before anything is sent when the source does not
        allow it: it stays proposed, said why."""
        publication = await self.publication(publication_id, lock=True)
        if publication.status != "proposed":
            raise PublicationDecidedError(publication.status)
        source = await self._source(publication.source_id, publication.kind)
        service = SourceService(self._session, self._workspace_id, actor_user_id=by)
        connector = await service.open_connector(source)
        wanted = set(chosen) if chosen else None
        items = [i for i in publication.items if wanted is None or str(i.get("id")) in wanted]
        if not items:
            raise PublicationRefusedError("nothing_chosen", "Aucun élément choisi.")
        writer: JiraIssues | ConfluencePages
        try:
            writer = await (open_issues if publication.kind == "issues" else open_pages)(connector)
            if not writer.writes:
                raise PublishRefusedError(
                    f"{publication.kind}_off",
                    "Cette source Jira n'autorise pas LEKA à créer des tickets."
                    if publication.kind == "issues"
                    else "Cette source Confluence n'autorise pas LEKA à publier des pages.",
                )
        except PublishRefusedError as refused:
            publication.error, publication.error_detail = refused.code, str(refused)[:2000]
            await self._session.commit()
            raise PublicationRefusedError(refused.code, str(refused)) from refused
        results: list[dict[str, object]] = []
        for item in items:
            title, body = str(item.get("title") or ""), str(item.get("body") or "")
            try:
                if isinstance(writer, JiraIssues):
                    labels = item.get("labels")
                    made = await writer.create(
                        publication.target,
                        title=title,
                        description=body,
                        kind=str(item.get("kind") or "task"),
                        labels=[str(label) for label in labels] if isinstance(labels, list) else [],
                    )
                    results.append({"id": item["id"], "key": made["key"], "url": made["url"]})
                else:
                    made = await writer.create(publication.target, title=title, body=body)
                    results.append({"id": item["id"], "page": made["id"], "url": made["url"]})
            except PublishRefusedError as refused:
                results.append(
                    {"id": item["id"], "error": refused.code, "said": str(refused)[:500]}
                )
        sent = [r for r in results if "url" in r]
        publication.results = results
        if not sent:
            # Nothing reached Atlassian: it stays proposed, said why, to try
            # again once the account, the project or the space allows it.
            publication.error = str(results[0].get("error") or "error")
            publication.error_detail = str(results[0].get("said") or "")[:2000]
            await self._session.commit()
            raise PublicationRefusedError(publication.error, publication.error_detail)
        publication.status = "applied" if len(sent) == len(results) else "partly"
        publication.decided_by, publication.decided_at = by, datetime.now(UTC)
        publication.note = (note or "").strip()[:2000] or None
        publication.error = publication.error_detail = None
        await self._session.commit()
        logger.info(
            "publication_applied",
            publication=str(publication.id),
            kind=publication.kind,
            sent=len(sent),
            refused=len(results) - len(sent),
        )
        return publication


# ── drafting, in a worker ───────────────────────────────────────────────────


async def queue_draft(workspace_id: uuid.UUID, publication_id: uuid.UUID) -> bool:
    """Its drafting, for a worker: the model takes a minute."""
    job = await enqueue_job(
        DRAFT_JOB,
        str(workspace_id),
        str(publication_id),
        for_workspace_id=workspace_id,
        queue=JobQueue.HIGH,
        concurrency_key=f"publication:{publication_id}",
    )
    return job is not None


async def draft(
    workspace_id: uuid.UUID, publication_id: uuid.UUID, *, budget: float = DRAFT_BUDGET
) -> dict[str, object]:
    """Its tickets or pages, drafted from the run's deliverable — or failed,
    said why: never left drafting."""
    # Here, not at the top: the registry reads every module's capabilities.
    from leka.capabilities.registry import find

    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = PublicationService(session, workspace_id)
            publication = await service.publication(publication_id)
            if publication.status != "drafting":
                return {"status": publication.status}
            run = await session.get(AgentRun, publication.run_id) if publication.run_id else None
            if run is None or not run.output:
                publication.status, publication.error = "failed", "not_finished"
                await session.commit()
                return {"status": "failed"}
            definition = find(run.key)
            model: type[IssuesDraft] | type[PagesDraft] = (
                IssuesDraft if publication.kind == "issues" else PagesDraft
            )
            request = Request(
                purpose=f"agent:{run.key}:{publication.kind}"[:100],
                messages=draft_messages(publication.kind, definition, run, publication.target),
                tier=Tier.DEEP,
                max_tokens=DRAFT_TOKENS,
                ref=f"publication:{publication.id}",
            )
            needs = replace(needs_of(definition), tools=False) if definition else Needs()
            # Nothing held while the model writes.
            await session.commit()
            error: str | None = None
            drafted: IssuesDraft | PagesDraft | None = None
            try:
                answered = await asyncio.wait_for(
                    Gateway(session, workspace_id).structured(request, model, needs),
                    timeout=budget,
                )
                drafted = answered.value
            except NoModelError as failed:
                error = "no_model" if failed.reason == "none" else failed.reason
            except TimeoutError:
                error = "timeout"
            except Exception:
                logger.exception("publication_not_drafted", publication=str(publication_id))
                error = "error"
            publication = await service.publication(publication_id, lock=True)
            if drafted is None:
                publication.status, publication.error = "failed", error or "error"
            else:
                publication.title = drafted.title.strip()[:300]
                publication.summary = drafted.summary.strip()
                publication.items = items_of(publication.kind, drafted)
                publication.status = "proposed"
            await session.commit()
            return {"status": publication.status}


def draft_job(workspace_id: str, publication_id: str) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(draft(uuid.UUID(workspace_id), uuid.UUID(publication_id)))


def items_read(publication: Publication) -> list[dict[str, Any]]:
    """Its tickets or pages as the API says them, each with what came of it."""
    results = {str(r.get("id")): r for r in publication.results if isinstance(r, dict)}
    return [
        {
            "id": str(item.get("id")),
            "title": str(item.get("title") or ""),
            "body": str(item.get("body") or ""),
            "kind": item.get("kind"),
            "priority": item.get("priority"),
            "labels": list(item.get("labels") or []),  # type: ignore[call-overload]
            "key": results.get(str(item.get("id")), {}).get("key")
            or results.get(str(item.get("id")), {}).get("page"),
            "url": results.get(str(item.get("id")), {}).get("url"),
            "error": results.get(str(item.get("id")), {}).get("error"),
        }
        for item in publication.items
    ]


__all__ = [
    "DRAFT_JOB",
    "KINDS",
    "IssuesDraft",
    "PagesDraft",
    "PublicationDecidedError",
    "PublicationNotFoundError",
    "PublicationRefusedError",
    "PublicationService",
    "draft",
    "draft_job",
    "draft_messages",
    "items_of",
    "items_read",
    "queue_draft",
]
