"""Identity: who someone is, and how they prove it.

LEKA-330. Registration, sign-in, sessions, email verification and password
recovery — and nothing about workspaces, memberships or permissions, which
belong to leka.platform and leka.governance.

This module IMPLEMENTS the seam leka.platform declares. LEKA-331's routes
consume get_current_user_id and get_session_store without knowing anything
about cookies or passwords, and nothing in those modules changed to make
this work.

Depends on leka.core, leka.db and leka.platform. Nothing imports it except
leka.api.identity and the wiring in leka.main.
"""

from leka.identity.email import (
    ConsoleEmailSender,
    DeferredEmailSender,
    EmailMessage,
    EmailSender,
    ResendEmailSender,
    SmtpEmailSender,
    build_email_sender,
)
from leka.identity.models import EmailToken, Session, TokenPurpose, User
from leka.identity.repository import (
    EmailTokenRepository,
    SessionRepository,
    UserRepository,
)
from leka.identity.schemas import (
    AuthErrorCode,
    AuthErrorResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    RecoveryAccepted,
    RegisterRequest,
    RegistrationAccepted,
    ResetPasswordRequest,
    SessionRead,
    UserRead,
    WorkspaceMembershipRead,
)
from leka.identity.service import (
    AccountUnverifiedError,
    AuthenticationError,
    AuthService,
    LoginResult,
    PasswordRejectedError,
    truncate_ip,
)
from leka.identity.wiring import (
    DatabaseSessionStore,
    configure_identity,
    current_user_id,
    load_session,
    read_session_token,
    session_store,
)

__all__ = [
    "AccountUnverifiedError",
    "AuthErrorCode",
    "AuthErrorResponse",
    "AuthService",
    "AuthenticationError",
    "ChangePasswordRequest",
    "ConsoleEmailSender",
    "DatabaseSessionStore",
    "DeferredEmailSender",
    "EmailMessage",
    "EmailSender",
    "EmailToken",
    "EmailTokenRepository",
    "ForgotPasswordRequest",
    "LoginRequest",
    "LoginResult",
    "MeResponse",
    "PasswordRejectedError",
    "RecoveryAccepted",
    "RegisterRequest",
    "RegistrationAccepted",
    "ResendEmailSender",
    "ResetPasswordRequest",
    "Session",
    "SessionRead",
    "SessionRepository",
    "SmtpEmailSender",
    "TokenPurpose",
    "User",
    "UserRead",
    "UserRepository",
    "WorkspaceMembershipRead",
    "build_email_sender",
    "configure_identity",
    "current_user_id",
    "load_session",
    "read_session_token",
    "session_store",
    "truncate_ip",
]
