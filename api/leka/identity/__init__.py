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
from leka.identity.email_layout import layout as branded_layout
from leka.identity.email_layout import paragraphs as email_paragraphs
from leka.identity.language import spoken_language, workspace_language
from leka.identity.messages import email_language
from leka.identity.messages import invitation as invitation_message
from leka.identity.models import CompanySize, EmailToken, Session, TokenPurpose, User
from leka.identity.repository import (
    EmailTokenRepository,
    SessionRepository,
    UserRepository,
)
from leka.identity.schemas import (
    AccountDeletion,
    AccountProfile,
    AuthErrorCode,
    AuthErrorResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    ProfileUpdate,
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
    password_is_breached,
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
    "AccountDeletion",
    "AccountProfile",
    "AccountUnverifiedError",
    "AuthErrorCode",
    "AuthErrorResponse",
    "AuthService",
    "AuthenticationError",
    "ChangePasswordRequest",
    "CompanySize",
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
    "ProfileUpdate",
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
    "branded_layout",
    "build_email_sender",
    "configure_identity",
    "current_user_id",
    "email_language",
    "email_paragraphs",
    "invitation_message",
    "load_session",
    "password_is_breached",
    "read_session_token",
    "session_store",
    "spoken_language",
    "truncate_ip",
    "workspace_language",
]
