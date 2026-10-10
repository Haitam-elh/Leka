"""Authentication routes.

Sign-in, sign-out, verification, recovery and session management.

Two rules run through every handler:

**One refusal, many causes.** An unknown address, a wrong password and an
account with no password all return the same body. A difference of any kind
turns a public form into a way to ask "does this person have an account
here?".

**Every message is safe AND useful.** "Invalid email or password" tells an
attacker nothing and tells a legitimate user exactly what to try. Where the
caller has already proved they own the account — a correct password on an
unverified address — we say more, because at that point we are not revealing
anything they do not know.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status

from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.core import ratelimit
from leka.db import DatabaseSession, SortableField, session_factory, system_scope
from leka.governance import audit_account
from leka.identity import (
    AccountDeletion,
    AccountUnverifiedError,
    AuthenticationError,
    AuthErrorCode,
    AuthService,
    ChangePasswordRequest,
    DeferredEmailSender,
    EmailTokenRepository,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    PasswordRejectedError,
    ProfileUpdate,
    RecoveryAccepted,
    RegisterRequest,
    RegistrationAccepted,
    ResetPasswordRequest,
    Session,
    SessionRead,
    SessionRepository,
    User,
    UserRead,
    UserRepository,
    WorkspaceMembershipRead,
    build_email_sender,
    load_session,
    truncate_ip,
)
from leka.identity.cookies import (
    CSRF_COOKIE_NAME,
    clear_session_cookie,
    set_csrf_cookie,
    set_session_cookie,
)
from leka.platform import AccountClosure, LastOwnerError, MembershipResolver

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = DatabaseSession
CurrentSession = Annotated[Session | None, Depends(load_session)]


def get_membership_resolver(db: SessionDep) -> MembershipResolver:
    """Where this person may go. Built here because leka.platform cannot
    depend on the API layer."""
    return MembershipResolver(db)


ResolverDep = Annotated[MembershipResolver, Depends(get_membership_resolver)]


def get_auth_service(db: SessionDep, background: BackgroundTasks) -> AuthService:
    # Emails go after the response, hence after the commit: a link never
    # names a token the database did not keep.
    return AuthService(
        UserRepository(db),
        SessionRepository(db),
        EmailTokenRepository(db),
        DeferredEmailSender(build_email_sender(), background.add_task),
    )


AuthDep = Annotated[AuthService, Depends(get_auth_service)]


def _refuse(code: AuthErrorCode, detail: str, status_code: int = 401) -> HTTPException:
    """A 4xx carrying a machine code alongside the human sentence.

    A superset of FastAPI's default {"detail": ...}, so it does not change
    the shape LEKA-331's routes already return. The code is what lets the
    interface show a "resend verification" button in one case and a countdown
    in another.
    """
    return HTTPException(status_code=status_code, detail={"detail": detail, "code": code.value})


def client_ip(request: Request) -> str:
    """The caller's address, for rate limiting only.

    Never stored as given — leka.identity.truncate_ip reduces it to a network
    prefix before it reaches the database.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# Work a refusal starts and does not wait for, held until it ends.
_pending: set[asyncio.Task[None]] = set()


def _later(work: Coroutine[object, object, None]) -> None:
    """Done after the answer, never before it: a refusal takes as long
    whether the address exists or not — the timing must not tell; a
    sign-out answers at once, before the page's other requests are refused."""
    task = asyncio.get_running_loop().create_task(work)
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def _failed_sign_in(email: str, why: str) -> None:
    """A failed sign-in to an account that exists, kept in its workspaces'
    audit trails (LEKA-407) — never the password, never whether the
    address exists: an unknown one leaves a log line only."""
    try:
        with system_scope():
            async with session_factory() as db:
                user = await UserRepository(db).get_by_email(email)
    except Exception:  # pragma: no cover - the refusal stands regardless
        return
    if user is not None:
        await audit_account(
            user.id,
            "user",
            "user.sign_in_failed",
            outcome="failure",
            detail={"why": why},
            # Anyone may try an address: its owner is the target, not the author.
            by_them=False,
        )


async def _enforce(scope: str, identifier: str, limit: ratelimit.Limit) -> None:
    verdict = await ratelimit.consume(scope, identifier, limit)
    if not verdict.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "detail": (
                    f"Too many attempts. Wait {verdict.retry_after_seconds} seconds and try again."
                ),
                "code": AuthErrorCode.RATE_LIMITED.value,
            },
            headers={"Retry-After": str(verdict.retry_after_seconds)},
        )


async def require_session(session: CurrentSession) -> Session:
    """The signed-in session, or a refusal. A dependency, not a body check.

    Every route that needs a session used to call _require_session(session)
    as its first statement. That works, and it is invisible: nothing outside
    the function body says the route is protected, so no check can tell a
    route that forgot from a route that is deliberately open. LEKA-333's
    route enumeration test reads the dependency tree, which is why this is a
    dependency.
    """
    return _require_session(session)


RequiredSession = Annotated[Session, Depends(require_session)]


def _require_session(session: Session | None) -> Session:
    if session is None:
        raise _refuse(AuthErrorCode.NOT_AUTHENTICATED, "You are not signed in.")
    return session


# ── Registration and verification ────────────────────────────────────────────


@router.post("/register", response_model=RegistrationAccepted, status_code=202)
async def register(
    payload: RegisterRequest, request: Request, auth: AuthDep
) -> RegistrationAccepted:
    """Create an account. Answers the same whether the address was free."""
    await _enforce("register:ip", client_ip(request), ratelimit.REGISTER_PER_IP)
    try:
        await auth.register(payload.email, payload.password, payload)
    except PasswordRejectedError as error:
        raise _refuse(AuthErrorCode.PASSWORD_BREACHED, error.reason, 422) from error
    return RegistrationAccepted()


# Declared BEFORE /verify/{token}: routes are matched in order, and
# "resend" is a perfectly good-looking token. The other way round it was
# checked as one, refused, and no new link was ever sent.
# tests/test_route_protection.py fails on any route hidden that way.
@router.post("/verify/resend", response_model=RegistrationAccepted, status_code=202)
async def resend_verification(
    payload: ForgotPasswordRequest, request: Request, auth: AuthDep
) -> RegistrationAccepted:
    await _enforce("verify:email", payload.email, ratelimit.VERIFICATION_RESEND_PER_ACCOUNT)
    await auth.resend_verification(payload.email)
    return RegistrationAccepted()


@router.post("/verify/{token}", response_model=UserRead)
async def verify_email(token: str, auth: AuthDep) -> UserRead:
    """Confirm an address. Single use, and time limited."""
    try:
        user = await auth.verify_email(token)
    except AuthenticationError as error:
        raise _refuse(
            AuthErrorCode.TOKEN_INVALID,
            "This confirmation link is no longer valid. Ask for a new one.",
            status.HTTP_400_BAD_REQUEST,
        ) from error
    return UserRead.model_validate(user)


# ── Signing in and out ───────────────────────────────────────────────────────


@router.post("/login", response_model=MeResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth: AuthDep,
    memberships: ResolverDep,
) -> MeResponse:
    """Sign in and open a NEW session.

    Always new: reusing an identifier that existed before authentication is
    session fixation, and an attacker who can set a cookie beforehand then
    holds one that is valid after.
    """
    ip = client_ip(request)
    await _enforce("login:ip", ip, ratelimit.LOGIN_PER_IP)
    await _enforce("login:email", payload.email, ratelimit.LOGIN_PER_ACCOUNT)

    try:
        result = await auth.login(
            payload.email,
            payload.password,
            user_agent=request.headers.get("user-agent"),
            ip=ip,
            remember=payload.remember,
        )
    except AccountUnverifiedError as error:
        _later(_failed_sign_in(payload.email, "unverified"))
        raise _refuse(
            AuthErrorCode.ACCOUNT_UNVERIFIED,
            "Confirm your email address before signing in. Check your inbox, "
            "or ask for a new link.",
            status.HTTP_403_FORBIDDEN,
        ) from error
    except AuthenticationError as error:
        # One sentence for every cause. The reason is logged, not returned.
        _later(_failed_sign_in(payload.email, "invalid_credentials"))
        raise _refuse(AuthErrorCode.INVALID_CREDENTIALS, "Invalid email or password.") from error

    await audit_account(
        result.user.id, "user", "user.signed_in", detail={"remember": payload.remember}
    )
    await ratelimit.reset("login:ip", ip, ratelimit.LOGIN_PER_IP)
    await ratelimit.reset("login:email", payload.email, ratelimit.LOGIN_PER_ACCOUNT)

    # Land them somewhere. Someone who belongs to exactly one workspace is
    # put in it: asking them to choose between one option is friction with
    # nothing on the other side of it, and until the workspace switcher
    # exists (LEKA-337) there is no way to choose at all.
    #
    # Several memberships means no automatic choice — picking for them would
    # be guessing, and the interface asks.
    #
    # This does not weaken architecture rule 3: the server reads the
    # memberships from the database and decides. Nothing is taken from the
    # request.
    pairs = await memberships.list_workspaces_for_user(result.user.id)
    if len(pairs) == 1:
        result.session.active_workspace_id = pairs[0][0].id

    csrf_token = set_session_cookie(response, result.token, persistent=payload.remember)
    return await _me(result.user, result.session, memberships, csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, session: CurrentSession, auth: AuthDep) -> Response:
    """End this session. The old cookie stops working immediately."""
    if session is not None:
        await auth.logout(session)
        # After the answer: the page that asked is navigating away, and its
        # other requests, refused now, must not get there first.
        _later(audit_account(session.user_id, "user", "user.signed_out"))
    clear_session_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_everywhere(
    response: Response, current: RequiredSession, auth: AuthDep, db: SessionDep
) -> Response:
    """Sign out of every device, including this one."""
    user = await UserRepository(db).get(current.user_id)
    if user is not None:
        await auth.logout_everywhere(user)
        _later(audit_account(user.id, "user", "user.signed_out_everywhere"))
    clear_session_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
async def read_me(
    request: Request,
    response: Response,
    current: RequiredSession,
    db: SessionDep,
) -> MeResponse:
    """Who I am, where I may go, and where I currently am — and this
    session's CSRF token, which the page cannot read from its cookie.

    One call: three round-trips for this would show as a flicker on every
    page load. A session from before the token was handed back in the body
    may have lost its cookie: it gets a new one, for as long as it lives.
    """
    user = await UserRepository(db).get(current.user_id)
    if user is None:  # pragma: no cover - cascade makes this unreachable
        raise _refuse(AuthErrorCode.SESSION_EXPIRED, "Your session has expired.")
    csrf_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not csrf_token:
        left = int((current.expires_at - datetime.now(UTC)).total_seconds())
        csrf_token = set_csrf_cookie(response, max_age=max(left, 0))
    return await _me(user, current, MembershipResolver(db), csrf_token)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    payload: AccountDeletion,
    response: Response,
    current: RequiredSession,
    auth: AuthDep,
    db: SessionDep,
) -> Response:
    """Close my account, for good.

    The password again, first. Then what the account owns: a workspace it
    is alone in starts its deletion (its grace period, then its erasure); a
    workspace others use, of which it is the last owner, refuses the whole
    thing, by name — nothing is changed. Then the person: sessions, tokens
    and seats go with them, and the cookies are cleared.
    """
    user = await UserRepository(db).get(current.user_id)
    if user is None:  # pragma: no cover - cascade makes this unreachable
        raise _refuse(AuthErrorCode.SESSION_EXPIRED, "Your session has expired.")
    try:
        await auth.confirm_password(user, payload.password)
    except AuthenticationError as error:
        raise _refuse(
            AuthErrorCode.INVALID_CREDENTIALS, "Your password is not correct.", 403
        ) from error
    try:
        await AccountClosure(db).close(user.id)
    except LastOwnerError as error:
        raise _refuse(
            AuthErrorCode.LAST_OWNER,
            f"You are the last owner of {error.workspace_name!r}, which others use: "
            "make someone else its owner first.",
            status.HTTP_409_CONFLICT,
        ) from error
    # Said before the seats go: afterwards, no workspace would hear of it.
    await audit_account(user.id, "user", "user.account_closed")
    await auth.delete_account(user)
    clear_session_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/me", response_model=UserRead)
async def update_me(
    payload: ProfileUpdate,
    current: RequiredSession,
    db: SessionDep,
) -> UserRead:
    """Change who I said I am — only the fields sent.

    How an account made before registration asked gets a name, and how
    anyone corrects theirs. The address is not here: changing it needs the
    new one proven, which is another flow.
    """
    user = await UserRepository(db).get(current.user_id)
    if user is None:  # pragma: no cover - cascade makes this unreachable
        raise _refuse(AuthErrorCode.SESSION_EXPIRED, "Your session has expired.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.flush()
    return UserRead.model_validate(user)


async def _me(
    user: User, session: Session, memberships: MembershipResolver, csrf_token: str | None = None
) -> MeResponse:
    pairs = await memberships.list_workspaces_for_user(user.id)
    return MeResponse(
        user=UserRead.model_validate(user),
        workspaces=[
            WorkspaceMembershipRead(
                id=workspace.id,
                name=workspace.name,
                slug=workspace.slug,
                role=membership.role.value,
            )
            for workspace, membership in pairs
        ],
        active_workspace_id=session.active_workspace_id,
        csrf_token=csrf_token,
    )


# ── Passwords ────────────────────────────────────────────────────────────────


@router.post("/password/forgot", response_model=RecoveryAccepted, status_code=202)
async def forgot_password(
    payload: ForgotPasswordRequest, request: Request, auth: AuthDep
) -> RecoveryAccepted:
    """Ask for a reset link. The answer never says whether the account exists."""
    await _enforce("reset:ip", client_ip(request), ratelimit.PASSWORD_RESET_PER_IP)
    await _enforce("reset:email", payload.email, ratelimit.PASSWORD_RESET_PER_EMAIL)
    await auth.request_password_reset(payload.email)
    return RecoveryAccepted()


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest, response: Response, auth: AuthDep
) -> Response:
    """Set a new password from a link.

    Every session is revoked, including any the attacker may hold: if the
    reason for the reset was that someone else knew the old password,
    leaving their sessions alive makes the reset pointless.
    """
    try:
        reset = await auth.reset_password(payload.token, payload.password)
    except PasswordRejectedError as error:
        raise _refuse(AuthErrorCode.PASSWORD_BREACHED, error.reason, 422) from error
    except AuthenticationError as error:
        raise _refuse(
            AuthErrorCode.TOKEN_INVALID,
            "This reset link is no longer valid. Ask for a new one.",
            status.HTTP_400_BAD_REQUEST,
        ) from error
    await audit_account(reset.id, "user", "user.password_reset")
    clear_session_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    current: RequiredSession,
    auth: AuthDep,
    db: SessionDep,
) -> Response:
    """Change a password while signed in.

    Keeps this session and revokes the others: signing someone out of the
    browser they are using, as a reward for improving their security,
    teaches them not to.
    """
    user = await UserRepository(db).get(current.user_id)
    if user is None:  # pragma: no cover
        raise _refuse(AuthErrorCode.SESSION_EXPIRED, "Your session has expired.")
    try:
        await auth.change_password(
            user, payload.current_password, payload.new_password, keep=current.id
        )
    except PasswordRejectedError as error:
        raise _refuse(AuthErrorCode.PASSWORD_BREACHED, error.reason, 422) from error
    except AuthenticationError as error:
        await audit_account(
            user.id, "user", "user.password_changed", outcome="failure", detail={"why": "invalid"}
        )
        raise _refuse(
            AuthErrorCode.INVALID_CREDENTIALS, "Your current password is not correct."
        ) from error
    await audit_account(user.id, "user", "user.password_changed")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Sessions ─────────────────────────────────────────────────────────────────


# What /auth/sessions may be sorted by.
#
# last_seen_at is what somebody actually wants — "which of these did I use
# most recently?" — and neither it nor created_at has an index. Both are
# bounded by ix_sessions_user_id, and a person has a handful of sessions.
SESSION_SORTS = SortCatalogue(
    fields=(
        SortableField("last_seen_at", Session.last_seen_at, "no index; bounded by user_id"),
        SortableField("created_at", Session.created_at, "no index; bounded by user_id"),
        SortableField("expires_at", Session.expires_at, "ix_sessions_expires_at"),
    ),
    default="last_seen_at",
)


@router.get("/sessions", response_model=PageEnvelope[SessionRead])
async def list_my_sessions(
    current: RequiredSession, db: SessionDep, page: PageParams
) -> PageEnvelope[SessionRead]:
    """My signed-in devices."""
    result = await serve_page(
        db,
        SessionRepository(db).live_for_user(current.user_id),
        request=page,
        catalogue=SESSION_SORTS,
        id_column=Session.id,
    )
    rows = result.items
    return PageEnvelope(
        data=[
            SessionRead(
                id=row.id,
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
                expires_at=row.expires_at,
                user_agent=row.user_agent,
                ip_prefix=row.ip_prefix,
                is_current=row.id == current.id,
            )
            for row in rows
        ],
        next_cursor=result.next_cursor,
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID, current: RequiredSession, db: SessionDep, auth: AuthDep
) -> Response:
    """Sign out one device.

    Scoped to my own sessions: revoking someone else's by guessing an id is
    not reachable from here.
    """
    sessions = SessionRepository(db)
    target = await sessions.get_for_user(current.user_id, session_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session.")
    await auth.logout(target)
    await audit_account(
        current.user_id, "user", "user.session_revoked", detail={"session": str(session_id)}
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["client_ip", "router", "truncate_ip"]
