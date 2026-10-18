"""What LEKA proposes to send out of a deliverable — tickets for Jira, pages
for Confluence — over HTTP (2026-10-18).

    POST   /agent-runs/{id}/proposals {kind, source_id, target}
                                       drafted by a worker from the run's
                                       deliverable: 202, drafting
    GET    /proposals?run_id&intention_id   the workspace's, the latest first
    GET    /proposals/{id}             one: its tickets or pages
    POST   /proposals/{id}/accept {items?, note?}
                                       the ones chosen, created through the
                                       source — 409 when the source does not
                                       allow it: it stays proposed, said why
    POST   /proposals/{id}/reject {note?}   rejected, said why

Asking takes `intention:create`; reading, `intention:read`; deciding,
`intention:approve`. The workspace is the session's.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import (
    AgentProposal,
    CapabilityRunRepository,
    ProposalCreate,
    ProposalDecidedError,
    ProposalDecision,
    ProposalItemRead,
    ProposalNotFoundError,
    ProposalRead,
    ProposalRefusedError,
    ProposalService,
    items_read,
    queue_draft,
)
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, require_permission

router = APIRouter(tags=["capabilities"])

Reader = Annotated[Principal, Depends(require_permission(Permission.INTENTION_READ))]
Asker = Annotated[Principal, Depends(require_permission(Permission.INTENTION_CREATE))]
Approver = Annotated[Principal, Depends(require_permission(Permission.INTENTION_APPROVE))]


def _missing() -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such proposal.")


# What a person can change, then try again: the source, the run, Atlassian.
CONFLICTS = frozenset(
    {
        "issues_off",
        "pages_off",
        "no_source",
        "not_finished",
        "not_allowed",
        "not_found",
        "title_taken",
        "invalid",
        "unavailable",
    }
)


def _refused(refused: ProposalRefusedError, field: str) -> ApiError:
    conflict = refused.code in CONFLICTS
    return ApiError(
        status.HTTP_409_CONFLICT if conflict else status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.CONFLICT if conflict else ErrorCode.VALIDATION_FAILED,
        str(refused),
        details=[FieldError(field=field, message=refused.code)],
    )


async def _read(service: ProposalService, proposal: AgentProposal) -> ProposalRead:
    return ProposalRead(
        id=proposal.id,
        run_id=proposal.run_id,
        intention_id=proposal.intention_id,
        kind=proposal.kind,
        source_id=proposal.source_id,
        target=proposal.target,
        title=proposal.title,
        summary=proposal.summary,
        status=proposal.status,
        items=[ProposalItemRead.model_validate(i) for i in items_read(proposal)],
        allowed=await service.allowed(proposal),
        proposed_by=proposal.proposed_by,
        decided_by=proposal.decided_by,
        decided_at=proposal.decided_at,
        note=proposal.note,
        error=proposal.error,
        error_detail=proposal.error_detail,
        created_at=proposal.created_at,
    )


@router.post(
    "/agent-runs/{run_id}/proposals",
    response_model=ProposalRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Tickets for Jira, or pages for Confluence, drafted from a run's deliverable",
)
async def ask_proposal(
    run_id: uuid.UUID, body: ProposalCreate, session: SessionDep, principal: Asker
) -> ProposalRead:
    """Drafted by a worker — the model, from what the agent delivered.
    404 when the run is not there; 409 when it is not finished or the source
    is gone; 422 when the source is not of that kind, or the project or the
    space is not one it reads."""
    run = await CapabilityRunRepository(session, principal.workspace_id).run(run_id)
    if run is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such agent run.")
    service = ProposalService(session, principal.workspace_id)
    try:
        proposal = await service.ask(
            run,
            kind=body.kind,
            source_id=body.source_id,
            target=body.target,
            by=principal.user_id,
        )
    except ProposalRefusedError as refused:
        field = (
            "source_id"
            if "source" in refused.code
            else "run_id"
            if refused.code == "not_finished"
            else "target"
        )
        raise _refused(refused, field) from None
    await session.commit()
    if not await queue_draft(principal.workspace_id, proposal.id):
        proposal.status, proposal.error = "failed", "queue_down"
        await session.commit()
    return await _read(service, proposal)


@router.get(
    "/proposals",
    response_model=list[ProposalRead],
    summary="What LEKA proposed to send to Jira or Confluence",
)
async def list_proposals(
    session: SessionDep,
    principal: Reader,
    run_id: Annotated[uuid.UUID | None, Query()] = None,
    intention_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ProposalRead]:
    service = ProposalService(session, principal.workspace_id)
    found = await service.proposals(run_id=run_id, intention_id=intention_id)
    return [await _read(service, proposal) for proposal in found]


@router.get("/proposals/{proposal_id}", response_model=ProposalRead, summary="One proposal")
async def get_proposal(
    proposal_id: uuid.UUID, session: SessionDep, principal: Reader
) -> ProposalRead:
    service = ProposalService(session, principal.workspace_id)
    try:
        return await _read(service, await service.proposal(proposal_id))
    except ProposalNotFoundError:
        raise _missing() from None


def _decided(error: ProposalDecidedError) -> ApiError:
    return ApiError(
        status.HTTP_409_CONFLICT,
        ErrorCode.CONFLICT,
        "This proposal is not waiting for a decision.",
        details=[FieldError(field="status", message=str(error))],
    )


@router.post(
    "/proposals/{proposal_id}/accept",
    response_model=ProposalRead,
    summary="Accept a proposal: LEKA creates the tickets or pages chosen",
)
async def accept_proposal(
    proposal_id: uuid.UUID,
    session: SessionDep,
    principal: Approver,
    body: ProposalDecision | None = None,
) -> ProposalRead:
    service = ProposalService(session, principal.workspace_id)
    try:
        proposal = await service.accept(
            proposal_id,
            by=principal.user_id,
            chosen=body.items if body else None,
            note=body.note if body else None,
        )
    except ProposalNotFoundError:
        raise _missing() from None
    except ProposalDecidedError as error:
        raise _decided(error) from None
    except ProposalRefusedError as refused:
        raise _refused(refused, "items" if refused.code == "nothing_chosen" else "source") from None
    return await _read(service, proposal)


@router.post(
    "/proposals/{proposal_id}/reject", response_model=ProposalRead, summary="Reject a proposal"
)
async def reject_proposal(
    proposal_id: uuid.UUID,
    session: SessionDep,
    principal: Approver,
    body: ProposalDecision | None = None,
) -> ProposalRead:
    service = ProposalService(session, principal.workspace_id)
    try:
        proposal = await service.reject(
            proposal_id, by=principal.user_id, note=body.note if body else None
        )
    except ProposalNotFoundError:
        raise _missing() from None
    except ProposalDecidedError as error:
        raise _decided(error) from None
    return await _read(service, proposal)
