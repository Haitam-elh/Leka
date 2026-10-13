"""The lifecycle: intention -> decision -> action (LEKA-384).

The gate every action passes through. An agent in proposes_action mode
proposes; it never executes. Execution happens here, and only after an
approval that carries a user and a timestamp.

That is not a policy this module implements on behalf of someone else — it
is the reason this module exists.

    create     an intention kept — submitted — and the context it asks for
               assembled (LEKA-373), its subject the intention, linked:
               then analysing. One transaction: nothing to start from
               (no thing named, no word to search) keeps nothing
    ask_again  its words or scope changed: its context made again, a new
               version (LEKA-374) — analysed again
    move       a transition the lifecycle allows, by the actor it allows
               (lifecycle.py) — what the analysis, a decision, an action
               (LEKA-388 to 392) call
    cancel, archive, restore
    link, unlink   what it rests on, what came of it

Every change is an event of its history, numbered, never rewritten: who
— a person, or LEKA itself — when, from where to where, why.

Depends on leka.context; reads leka.intelligence and leka.knowledge to
check what is linked.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime

from leka.context import (
    AssembledContext,
    ContextRepository,
    ContextService,
    IntentAsk,
    IntentPlan,
)
from leka.core.sensitive import guarded
from leka.intelligence import IntelligenceRepository
from leka.intentions.brief import answered, answered_ask, brief_of, tidy
from leka.intentions.grounding import acting, readiness, refined
from leka.intentions.lifecycle import (
    CLOSED,
    Actor,
    IllegalTransitionError,
    IntentionStatus,
    move,
    moves,
    phase,
)
from leka.intentions.models import (
    Intention,
    IntentionAnalysis,
    IntentionEvent,
    IntentionLink,
)
from leka.intentions.repository import IntentionRepository
from leka.intentions.schemas import (
    ContextReadiness,
    IntentionAnalysisRead,
    IntentionAnswer,
    IntentionBrief,
    IntentionCounts,
    IntentionDetail,
    IntentionEventRead,
    IntentionLinkRead,
    IntentionRead,
    IntentionRequest,
    Understanding,
)
from leka.intentions.understanding import understand
from leka.knowledge import GraphRepository

S = IntentionStatus
TITLE = 300
REASON = 500


class NothingToStartError(ValueError):
    """Its words name nothing in the company model and say no word to
    search: nothing is kept."""


class IntentionArchivedError(ValueError):
    """An archived intention does not move until it is restored."""


class NotYoursError(PermissionError):
    """Handled by someone who neither asked it nor may approve: an
    intention is its asker's — and its approvers' (LEKA-390)."""


class LinkRefusedError(ValueError):
    """What it would be linked to is not there — or not this workspace's."""


def _yours(intention: Intention, by: uuid.UUID | None, steward: bool) -> None:
    """Its asker, or someone who may approve: who may handle it."""
    if not steward and (by is None or intention.created_by != by):
        raise NotYoursError


def _flagged(understood: Understanding) -> dict[str, object]:
    """What a move says of an understanding: its goal, and what blocks it."""
    return {
        "goal": understood.goal.code,
        "ambiguities": [a.kind for a in understood.ambiguities if a.blocking],
    }


# What `_scope` keeps of what was asked, to ask it again.
ASKED_SCOPE = frozenset({"environment", "since", "until", "services", "sources"})


def _answers(ask: IntentAsk | IntentionRequest) -> list[IntentionAnswer]:
    """What was answered with it (LEKA-439): one per question, the latest."""
    return tidy(ask.answers) if isinstance(ask, IntentionRequest) else []


def _kept(intention: Intention) -> list[IntentionAnswer]:
    """Its answers, as kept."""
    return [IntentionAnswer.model_validate(a) for a in (intention.answers or [])]


def _brief(intention: Intention) -> IntentionBrief | None:
    """What LEKA knows and asks of it (LEKA-439) — from its understanding,
    which already holds its answers, and the answers themselves."""
    if not intention.understanding:
        return None
    return brief_of(Understanding.model_validate(intention.understanding), _kept(intention))


def _ready(ready: ContextReadiness) -> dict[str, object]:
    """What a move says of its context: whether it can ground an analysis,
    and what stands in the way."""
    return {"readiness": ready.status, "critical": [issue.kind for issue in ready.critical]}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _guarded(ask: IntentAsk) -> IntentAsk:
    """Its words and title as kept: a secret or an identity number typed in
    them taken out (core.sensitive)."""
    text = guarded(ask.text)
    title = guarded(ask.title) if ask.title else ask.title
    if text == ask.text and title == ask.title:
        return ask
    return ask.model_copy(update={"text": text, "title": title})


def _scope(ask: IntentAsk) -> dict[str, object]:
    """The scope asked, as it is kept: what the asker chose, not the words."""
    said = ask.model_dump(
        mode="json",
        include={"environment", "since", "until", "services", "sources"},
        exclude_none=True,
    )
    return {key: value for key, value in said.items() if value not in ([], None)}


def intention_read(intention: Intention) -> IntentionRead:
    status = S(intention.status)
    return IntentionRead.model_validate(
        {
            **{
                column: getattr(intention, column)
                for column in (
                    "id",
                    "title",
                    "text",
                    "kind",
                    "scope",
                    "status_changed_at",
                    "summary",
                    "created_by",
                    "created_at",
                    "updated_at",
                    "context_id",
                    "archived_at",
                )
            },
            "status": status,
            "phase": phase(status),
            "moves": [m.to for m in moves(status)] if intention.archived_at is None else [],
            "goal": intention.goal,
        }
    )


class IntentionService:
    """Carries an intention from proposal to execution, or to rejection."""

    def __init__(
        self,
        repository: IntentionRepository,
        *,
        contexts: ContextService | None = None,
        context_repository: ContextRepository | None = None,
        findings: IntelligenceRepository | None = None,
        entities: GraphRepository | None = None,
        reading: Callable[[str, Understanding], Awaitable[Understanding]] | None = None,
    ) -> None:
        self._repository = repository
        # A language model reading it with the rules (LEKA-394): none, the
        # rules alone.
        self._reading = reading
        # What it is analysed from (LEKA-373) — and what links are checked
        # against: each module's own, never a query here.
        self._contexts = contexts
        self._context_repository = context_repository
        self._findings = findings
        self._entities = entities

    # ── its history ─────────────────────────────────────────────────────

    def _record(
        self,
        intention: Intention,
        kind: str,
        *,
        actor: Actor,
        by: uuid.UUID | None,
        at: datetime,
        name: str | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        reason: str | None = None,
        detail: Mapping[str, object] | None = None,
    ) -> IntentionEvent:
        intention.events_count += 1
        event = IntentionEvent(
            workspace_id=self._repository.workspace_id,
            id=uuid.uuid4(),
            intention_id=intention.id,
            sequence=intention.events_count,
            kind=kind,
            name=name,
            from_status=from_status,
            to_status=to_status,
            actor=actor.value,
            by=by if actor is Actor.PERSON else None,
            at=at,
            reason=reason[:REASON] if reason else None,
            detail=dict(detail or {}),
        )
        self._repository.add(event)
        intention.updated_at = at
        return event

    def _move(
        self,
        intention: Intention,
        to: IntentionStatus,
        *,
        actor: Actor,
        by: uuid.UUID | None,
        at: datetime,
        reason: str | None = None,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        if intention.archived_at is not None:
            raise IntentionArchivedError
        at_status = S(intention.status)
        allowed = move(at_status, to, actor)
        intention.status = to.value
        intention.status_changed_at = at
        self._record(
            intention,
            "moved",
            actor=actor,
            by=by,
            at=at,
            name=allowed.name,
            from_status=at_status.value,
            to_status=to.value,
            reason=reason,
            detail=detail,
        )

    # ── asking ──────────────────────────────────────────────────────────

    async def create(
        self,
        ask: IntentAsk | IntentionRequest,
        *,
        by: uuid.UUID | None,
        now: datetime | None = None,
    ) -> tuple[Intention, AssembledContext]:
        """An intention kept, its context assembled and linked — analysing.
        NothingToStartError when nothing can start it: the caller's
        transaction is rolled back, and nothing is kept."""
        if self._contexts is None:
            msg = "Creating an intention assembles its context: a ContextService is needed."
            raise RuntimeError(msg)
        # A secret typed in it is never kept, nor read by a model (LEKA-405).
        ask = _guarded(ask)
        given = _answers(ask)
        at = _now(now)
        intention = Intention(
            workspace_id=self._repository.workspace_id,
            id=uuid.uuid4(),
            text=ask.text,
            title=(ask.title or ask.text)[:TITLE],
            scope=_scope(ask),
            answers=[a.model_dump(mode="json") for a in given],
            status=S.SUBMITTED.value,
            status_changed_at=at,
            created_by=by,
            events_count=0,
        )
        self._repository.add(intention)
        self._record(
            intention,
            "created",
            actor=Actor.PERSON,
            by=by,
            at=at,
            to_status=None,
            detail={"scope": intention.scope},
        )
        await self._repository.flush()
        # Read with what its asker answered (LEKA-439): their words with the
        # rest, a thing chosen, an environment.
        asked = answered_ask(ask, given).model_copy(update={"intention_id": str(intention.id)})
        # Understood first (LEKA-385, 386), then its context assembled from
        # its scope (LEKA-387): what it excludes is never held.
        understood = answered(
            await self._understand(asked.text, await self._contexts.plan_intent(asked), at=at),
            given,
        )
        context = await self._contexts.assemble_intent(refined(asked, understood), by=by)
        if context is None:
            raise NothingToStartError
        await self._follow(intention, context, by=by, at=at)
        ready = self._keep(intention, understood, context)
        self._move(
            intention,
            S.ANALYSING if understood.clear else S.NEEDS_CLARIFICATION,
            actor=Actor.SYSTEM,
            by=None,
            at=at,
            detail={"context_id": str(context.context_id), "version": context.version}
            | _flagged(understood)
            | _ready(ready),
        )
        return intention, context

    async def ask_again(
        self,
        intention_id: uuid.UUID,
        ask: IntentAsk | IntentionRequest,
        *,
        by: uuid.UUID | None,
        steward: bool = False,
        now: datetime | None = None,
    ) -> tuple[Intention, AssembledContext] | None:
        """Its words or scope as they now stand: its context made again — a
        new version that says what LEKA reads differently (LEKA-374) — and
        analysed again. IllegalTransitionError once cancelled, or while its
        actions run."""
        if self._contexts is None:
            msg = "Asking again assembles its context: a ContextService is needed."
            raise RuntimeError(msg)
        ask = _guarded(ask)
        intention = await self._repository.intention(intention_id, lock=True)
        if intention is None:
            return None
        at = _now(now)
        # Checked before anything is touched: a refusal changes nothing.
        _yours(intention, by, steward)
        if intention.archived_at is not None:
            raise IntentionArchivedError
        to, actor = S.ANALYSING, Actor.PERSON
        move(S(intention.status), to, actor)
        # Its answers (LEKA-439): those given now; none given, the ones kept
        # while its words are the same — new words, new questions.
        given = _answers(ask) or (_kept(intention) if ask.text == intention.text else [])
        asked = answered_ask(ask, given).model_copy(update={"intention_id": str(intention.id)})
        understood = answered(
            await self._understand(asked.text, await self._contexts.plan_intent(asked), at=at),
            given,
        )
        scoped = refined(asked, understood)
        context: AssembledContext | None
        if intention.context_id is not None:
            context = await self._contexts.reask(intention.context_id, scoped, by=by)
        else:
            context = None
        if context is None:
            context = await self._contexts.assemble_intent(scoped, by=by)
        if context is None:
            raise NothingToStartError
        before = {"title": intention.title, "text": intention.text, "scope": intention.scope}
        intention.text = ask.text
        intention.title = (ask.title or ask.text)[:TITLE]
        intention.scope = _scope(ask)
        intention.answers = [a.model_dump(mode="json") for a in given]
        await self._follow(intention, context, by=by, at=at)
        ready = self._keep(intention, understood, context)
        self._move(
            intention,
            to,
            actor=actor,
            by=by,
            at=at,
            detail={
                "before": before,
                "scope": intention.scope,
                "context_id": str(context.context_id),
                "version": context.version,
            }
            | ({"answers": [a.question for a in given]} if given else {})
            | _ready(ready),
        )
        if not understood.clear:
            # Read again, and still not understood enough: said, again.
            self._move(
                intention,
                S.NEEDS_CLARIFICATION,
                actor=Actor.SYSTEM,
                by=None,
                at=at,
                detail=_flagged(understood),
            )
        return intention, context

    @staticmethod
    def _keep(
        intention: Intention, understood: Understanding, context: AssembledContext
    ) -> ContextReadiness:
        """What LEKA understood (LEKA-385, 386) and whether its context can
        ground an analysis (LEKA-387) — kept with it."""
        intention.understanding = understood.model_dump(mode="json")
        intention.goal = understood.goal.code
        ready = readiness(context, acts=acting(understood))
        intention.readiness = ready.model_dump(mode="json")
        return ready

    async def context(
        self, intention_id: uuid.UUID, *, version: int | None = None
    ) -> tuple[AssembledContext, ContextReadiness] | None:
        """Its context, as downstream capabilities read it (LEKA-387): the
        context engine's contract (LEKA-376) — its latest version, or the
        one asked — and whether it can ground an analysis."""
        if self._contexts is None:
            msg = "Reading its context needs a ContextService."
            raise RuntimeError(msg)
        intention = await self._repository.intention(intention_id)
        if intention is None or intention.context_id is None:
            return None
        found = await self._contexts.assembled(intention.context_id, version=version)
        if found is None:
            return None
        understood = (
            Understanding.model_validate(intention.understanding)
            if intention.understanding
            else None
        )
        return found, readiness(found, acts=acting(understood))

    async def _understand(
        self, text: str, plan: IntentPlan | None, *, at: datetime
    ) -> Understanding:
        """Read with what the company model says now: each thing's
        lifecycle, the environments it knows."""
        lifecycles: dict[uuid.UUID, str] = {}
        environments: list[str] = []
        if self._entities is not None:
            ids = [s.entity_id for s in plan.subjects] if plan is not None else []
            found = await self._entities.by_ids(ids)
            lifecycles = {ident: entity.lifecycle.value for ident, entity in found.items()}
            environments = await self._entities.environments()
        understood = understand(
            text, plan, lifecycles=lifecycles, environments=environments, now=at
        )
        if self._reading is not None:
            understood = await self._reading(text, understood)
        return understood

    async def understand(
        self, ask: IntentAsk | IntentionRequest, *, now: datetime | None = None
    ) -> Understanding:
        """What LEKA would understand of these words — nothing kept."""
        understood, _plan = await self.read(ask, now=now)
        return understood

    async def read(
        self, ask: IntentAsk | IntentionRequest, *, now: datetime | None = None
    ) -> tuple[Understanding, IntentPlan | None]:
        """What LEKA would understand of these words, its answers taken
        (LEKA-439), and what it would read for them — nothing kept."""
        if self._contexts is None:
            msg = "Understanding reads the company model: a ContextService is needed."
            raise RuntimeError(msg)
        given = _answers(ask)
        asked = answered_ask(_guarded(ask), given)
        plan = await self._contexts.plan_intent(asked)
        return answered(await self._understand(asked.text, plan, at=_now(now)), given), plan

    async def answer(
        self,
        intention_id: uuid.UUID,
        answers: Sequence[IntentionAnswer],
        *,
        by: uuid.UUID | None,
        steward: bool = False,
        now: datetime | None = None,
    ) -> tuple[Intention, AssembledContext] | None:
        """What its asker answered to LEKA's questions (LEKA-439), with those
        answered before — the latest for each: it is asked again with them,
        its words and scope as they are."""
        intention = await self._repository.intention(intention_id)
        if intention is None:
            return None
        scope = {k: v for k, v in (intention.scope or {}).items() if k in ASKED_SCOPE}
        ask = IntentionRequest.model_validate(
            {
                "text": intention.text,
                "title": intention.title,
                **scope,
                "answers": [*_kept(intention), *answers],
            }
        )
        return await self.ask_again(intention_id, ask, by=by, steward=steward, now=now)

    async def _follow(
        self, intention: Intention, context: AssembledContext, *, by: uuid.UUID | None, at: datetime
    ) -> None:
        """Its context, as it now is: what it is read as, and linked."""
        intention.context_id = context.context_id
        if context.intent is not None:
            intention.kind = context.intent.kind
        found = await self._repository.link(intention.id, "context", context.context_id)
        if found is not None:
            found.detail = {**found.detail, "version": context.version}
            return
        self._add_link(
            intention,
            "context",
            context.context_id,
            label=context.title,
            detail={"version": context.version},
            actor=Actor.SYSTEM,
            by=by,
            at=at,
        )

    # ── moving ──────────────────────────────────────────────────────────

    async def move(
        self,
        intention_id: uuid.UUID,
        to: IntentionStatus,
        *,
        actor: Actor,
        by: uuid.UUID | None = None,
        reason: str | None = None,
        detail: Mapping[str, object] | None = None,
        summary: str | None = None,
        now: datetime | None = None,
    ) -> Intention | None:
        """A transition the lifecycle allows by this actor — what the
        analysis, a decision, an action (LEKA-388 to 392) call. Its summary,
        when it concluded one. IllegalTransitionError otherwise."""
        intention = await self._repository.intention(intention_id, lock=True)
        if intention is None:
            return None
        if actor is Actor.PERSON and by is None:
            # A person's move says which person: never an anonymous one.
            raise IllegalTransitionError(S(intention.status), to, actor)
        self._move(intention, to, actor=actor, by=by, at=_now(now), reason=reason, detail=detail)
        if summary is not None:
            intention.summary = summary
        return intention

    async def cancel(
        self,
        intention_id: uuid.UUID,
        *,
        by: uuid.UUID,
        steward: bool = False,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> Intention | None:
        """Withdrawn by its asker, or by someone who may approve."""
        intention = await self._repository.intention(intention_id, lock=True)
        if intention is None:
            return None
        _yours(intention, by, steward)
        self._move(intention, S.CANCELLED, actor=Actor.PERSON, by=by, at=_now(now), reason=reason)
        return intention

    async def archive(
        self,
        intention_id: uuid.UUID,
        *,
        by: uuid.UUID,
        steward: bool = False,
        now: datetime | None = None,
    ) -> Intention | None:
        """Set aside — only once it is done with: completed, rejected or
        cancelled. IllegalTransitionError otherwise."""
        intention = await self._repository.intention(intention_id, lock=True)
        if intention is None:
            return None
        _yours(intention, by, steward)
        status = S(intention.status)
        if status not in CLOSED:
            raise IllegalTransitionError(status, status, Actor.PERSON)
        if intention.archived_at is None:
            at = _now(now)
            intention.archived_at = at
            self._record(intention, "archived", actor=Actor.PERSON, by=by, at=at)
        return intention

    async def restore(
        self,
        intention_id: uuid.UUID,
        *,
        by: uuid.UUID,
        steward: bool = False,
        now: datetime | None = None,
    ) -> Intention | None:
        intention = await self._repository.intention(intention_id, lock=True)
        if intention is None:
            return None
        _yours(intention, by, steward)
        if intention.archived_at is not None:
            at = _now(now)
            intention.archived_at = None
            self._record(intention, "restored", actor=Actor.PERSON, by=by, at=at)
        return intention

    # ── links ───────────────────────────────────────────────────────────

    def _add_link(
        self,
        intention: Intention,
        kind: str,
        ref_id: uuid.UUID,
        *,
        label: str,
        detail: Mapping[str, object],
        actor: Actor,
        by: uuid.UUID | None,
        at: datetime,
    ) -> IntentionLink:
        link = IntentionLink(
            workspace_id=self._repository.workspace_id,
            id=uuid.uuid4(),
            intention_id=intention.id,
            kind=kind,
            ref_id=ref_id,
            label=label[:500],
            detail=dict(detail),
            linked_at=at,
            linked_by=by if actor is Actor.PERSON else None,
        )
        self._repository.add(link)
        self._record(
            intention,
            "linked",
            actor=actor,
            by=by,
            at=at,
            detail={
                "kind": kind,
                "ref_id": str(ref_id),
                "label": link.label,
                # A finding's code and values, for the history to word it.
                **{k: link.detail[k] for k in ("code", "params") if k in link.detail},
            },
        )
        return link

    async def _label(self, kind: str, ref_id: uuid.UUID) -> tuple[str, dict[str, object]]:
        """What a context, a finding or an entity is called — checked
        through the module that owns it. LinkRefusedError when it is not
        this workspace's."""
        if kind == "context" and self._context_repository is not None:
            context = await self._context_repository.context(ref_id)
            if context is not None:
                return context.title, {"version": context.current_version}
        elif kind == "finding" and self._findings is not None:
            finding = await self._findings.finding(ref_id)
            if finding is not None:
                # Its code and values: the interface words it, as Insights
                # does — its statement is English.
                return finding.statement, {
                    "code": finding.code,
                    "analyzer": finding.analyzer,
                    "params": dict(finding.params or {}),
                }
        elif kind == "entity" and self._entities is not None:
            entity = (await self._entities.by_ids([ref_id])).get(ref_id)
            if entity is not None:
                return entity.name, {"type": entity.type.value}
        raise LinkRefusedError(kind)

    async def link(
        self,
        intention_id: uuid.UUID,
        kind: str,
        ref_id: uuid.UUID,
        *,
        actor: Actor,
        by: uuid.UUID | None = None,
        label: str | None = None,
        detail: Mapping[str, object] | None = None,
        steward: bool = False,
        now: datetime | None = None,
    ) -> IntentionLink | None:
        """Linked to what it rests on or what came of it. A context, a
        finding, an entity is checked and named here; a decision, an action,
        an outcome is named by what makes it (LEKA-390 to 392). Linked twice,
        the same link."""
        intention = await self._repository.intention(intention_id, lock=True)
        if intention is None:
            return None
        if actor is Actor.PERSON:
            _yours(intention, by, steward)
        found = await self._repository.link(intention.id, kind, ref_id)
        if found is not None:
            return found
        if kind in ("context", "finding", "entity"):
            named, said = await self._label(kind, ref_id)
        elif label:
            named, said = label, {}
        else:
            raise LinkRefusedError(kind)
        return self._add_link(
            intention,
            kind,
            ref_id,
            label=named,
            detail={**said, **(detail or {})},
            actor=actor,
            by=by,
            at=_now(now),
        )

    async def unlink(
        self,
        intention_id: uuid.UUID,
        link_id: uuid.UUID,
        *,
        by: uuid.UUID,
        steward: bool = False,
        now: datetime | None = None,
    ) -> bool:
        """A link a person made, undone — never its context's, which is what
        it is analysed from. False when there is no such link."""
        intention = await self._repository.intention(intention_id, lock=True)
        if intention is None:
            return False
        _yours(intention, by, steward)
        link = next(
            (found for found in await self._repository.links(intention.id) if found.id == link_id),
            None,
        )
        if link is None:
            return False
        if link.kind == "context" and link.ref_id == intention.context_id:
            raise LinkRefusedError("context")
        await self._repository.unlink(link)
        self._record(
            intention,
            "unlinked",
            actor=Actor.PERSON,
            by=by,
            at=_now(now),
            detail={"kind": link.kind, "ref_id": str(link.ref_id), "label": link.label},
        )
        return True

    # ── reads ───────────────────────────────────────────────────────────

    async def detail(self, intention_id: uuid.UUID) -> IntentionDetail | None:
        intention = await self._repository.intention(intention_id)
        if intention is None:
            return None
        return self.detail_of(intention, await self._repository.links(intention.id))

    @staticmethod
    def detail_of(intention: Intention, links: Sequence[IntentionLink]) -> IntentionDetail:
        return IntentionDetail(
            **intention_read(intention).model_dump(),
            links=[IntentionLinkRead.model_validate(link) for link in links],
            understanding=(
                Understanding.model_validate(intention.understanding)
                if intention.understanding
                else None
            ),
            readiness=(
                ContextReadiness.model_validate(intention.readiness)
                if intention.readiness
                else None
            ),
            answers=_kept(intention),
            brief=_brief(intention),
        )

    async def detail_now(self, intention: Intention) -> IntentionDetail:
        """As it now is, once written: what a route answers after a change."""
        await self._repository.refresh(intention)
        return self.detail_of(intention, await self._repository.links(intention.id))

    async def history(self, intention_id: uuid.UUID) -> list[IntentionEventRead] | None:
        intention = await self._repository.intention(intention_id)
        if intention is None:
            return None
        return [
            IntentionEventRead.model_validate(event)
            for event in await self._repository.events(intention.id)
        ]

    async def counts(self, *, created_by: uuid.UUID | None = None) -> IntentionCounts:
        by_status = await self._repository.counts(created_by=created_by)
        counted = dict.fromkeys(("active", "scheduled", "finished"), 0)
        for status, count in by_status.items():
            if status != "archived":
                counted[phase(S(status))] += count
        return IntentionCounts(
            all=sum(counted.values()),
            archived=by_status.get("archived", 0),
            **counted,
        )

    # ── its analyses (LEKA-388) ─────────────────────────────────────────

    async def analyses(
        self, intention_id: uuid.UUID, *, limit: int = 20
    ) -> list[IntentionAnalysisRead] | None:
        """Its analyses, the latest first, each with the version its context
        is at now (LEKA-441); None when it does not exist."""
        intention = await self._repository.intention(intention_id)
        if intention is None:
            return None
        ready = intention.readiness or {}
        now = ready.get("version") if isinstance(ready.get("version"), int) else None
        return [
            analysis_read(row, context_now=now)  # type: ignore[arg-type]
            for row in await self._repository.analyses(intention_id, limit=limit)
        ]

    async def analyse_again(
        self,
        intention_id: uuid.UUID,
        *,
        by: uuid.UUID | None,
        steward: bool = False,
        now: datetime | None = None,
    ) -> Intention | None:
        """Analysed again, as it now stands: analysing, it is run again;
        failed, it is retried first. IllegalTransitionError otherwise."""
        intention = await self._repository.intention(intention_id, lock=True)
        if intention is None:
            return None
        _yours(intention, by, steward)
        if intention.status == S.FAILED.value:
            self._move(
                intention,
                S.ANALYSING,
                actor=Actor.PERSON,
                by=by,
                at=_now(now),
                reason="Analysed again.",
            )
        elif intention.status != S.ANALYSING.value:
            raise IllegalTransitionError(S(intention.status), S.ANALYSING, Actor.PERSON)
        if intention.archived_at is not None:
            raise IntentionArchivedError
        return intention


def analysis_read(
    row: IntentionAnalysis, *, context_now: int | None = None
) -> IntentionAnalysisRead:
    """One analysis, as it is read (LEKA-388) — with the version its
    intention's context is at now: a newer one says it read an older one."""
    return IntentionAnalysisRead.model_validate(
        {
            "id": row.id,
            "intention_id": row.intention_id,
            "number": row.number,
            "trigger": row.trigger,
            "status": row.status,
            "requested_by": row.requested_by,
            "context_id": row.context_id,
            "context_version": row.context_version,
            "readiness": row.readiness,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "selection": row.selection,
            "steps": row.steps,
            "result": row.result,
            "error": row.error,
            "detail": row.detail,
            "context_now": context_now,
        }
    )
