"""Skills (LEKA-396), over HTTP.

    GET   /skills                     every skill, as a caller gets it: what
                                      it does, what it takes and gives, who
                                      may run it, where it stands
    GET   /skills/runs?key&ref        the workspace's skill runs, the latest
                                      first: of one skill, about one thing
                                      (`intention:<id>`)
    GET   /skills/{key}               one, and every version of it
    POST  /skills/{key}/run           run it: what it gave — or refused, said
                                      why (404, 403, 422); a refusal is kept
                                      too

Reading takes `workspace:read`; running, the skill's own permission, from
the person's role as it is now. The workspace is read from the session,
never from the path or the payload (rule 3).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import (
    SkillRead,
    SkillRunCreate,
    SkillRunRead,
    SkillRuntime,
    all_skills,
    find_skill,
    run_read,
    skill_read,
    skill_runs,
)
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, require_permission

# LEKA's own skills, registered when imported (leka/intentions/skills.py).
from leka.intentions import SKILLS

router = APIRouter(prefix="/skills", tags=["capabilities"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
Key = Annotated[str, Path(max_length=64, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]

REFUSED = {
    "not_found": (status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND),
    "unknown": (status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND),
    "not_permitted": (status.HTTP_403_FORBIDDEN, ErrorCode.PERMISSION_DENIED),
    "not_runnable": (status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED),
    "invalid_input": (status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED),
}

_ = SKILLS  # imported for what importing it registers


def _permissions(principal: Principal) -> frozenset[str]:
    return frozenset(p.value for p in principal.permissions)


@router.get("", response_model=list[SkillRead], summary="Every skill LEKA has")
async def list_skills(principal: Reader) -> list[SkillRead]:
    permissions = _permissions(principal)
    return [skill_read(skill, permissions) for skill in all_skills()]


@router.get("/runs", response_model=list[SkillRunRead], summary="The workspace's skill runs")
async def list_runs(
    session: SessionDep,
    principal: Reader,
    key: Annotated[str | None, Query(max_length=64)] = None,
    ref: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SkillRunRead]:
    runs = await skill_runs(session, principal.workspace_id, key=key, ref=ref, limit=limit)
    return [run_read(run, by=principal.user_id) for run in runs]


@router.get("/{key}", response_model=SkillRead, summary="One skill, every version of it")
async def get_skill(key: Key, principal: Reader) -> SkillRead:
    skill = find_skill(key)
    if skill is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such skill.")
    return skill_read(skill, _permissions(principal))


@router.post("/{key}/run", response_model=SkillRunRead, summary="Run a skill")
async def run_skill(
    key: Key, body: SkillRunCreate, session: SessionDep, principal: Reader
) -> SkillRunRead:
    """What it gave — or why it did not run: no such skill or thing (404),
    the person's role may not run it (403), that version does not run or
    what it was given is not what it takes (422, each error in `details`).
    One that failed or ran out of time is said in its `status`. Every run is
    kept, refused or not."""
    runtime = SkillRuntime(
        session,
        principal.workspace_id,
        permissions=_permissions(principal),
        by=principal.user_id,
        caller="api",
    )
    outcome = await runtime.run(key, body.inputs, version=body.version)
    row = runtime.kept(outcome.run_id) if outcome.run_id else None
    # Kept, whatever came of it: a refusal as much as a run.
    await session.commit()
    if outcome.status == "refused" and outcome.reason in REFUSED:
        code, kind = REFUSED[outcome.reason]
        details = [
            FieldError(field=f"inputs.{e['field']}", message=e["message"]) for e in outcome.errors
        ]
        raise ApiError(code, kind, outcome.message or "Refused.", details=details or None)
    assert row is not None  # every run is kept
    return run_read(
        row,
        by=principal.user_id,
        output=outcome.output.model_dump(mode="json", exclude={"cited"})
        if outcome.output is not None
        else None,
    )
