"""Identity tables: a person, their sessions, and their one-time tokens.

None of these carries workspace_id, and that is deliberate — they are the two
exceptions to architecture rule 2, plus their natural extensions:

  users         a person is a person. A consultant working for two customers
                signs in once; which workspaces they may enter is recorded in
                platform.Membership.
  sessions      belong to a person, not to a tenant. A session carries an
                ACTIVE workspace, which is a different thing: it is where
                this browser currently is, and it changes when they switch.
  email_tokens  belong to a person, and exist before any workspace does.

Because they do not inherit WorkspaceScopedMixin, the scope guard in leka.db
does not apply to them. That is correct rather than convenient: there is no
tenant to scope to.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _values(enum_class: type[enum.StrEnum]) -> list[str]:
    """Store the enum VALUE, not the member name."""
    return [member.value for member in enum_class]


class CompanySize(enum.StrEnum):
    """How many people work where someone works, as they said when
    registering — the brackets of the site's own forms.

    Text with a CHECK constraint, not a PostgreSQL ENUM — see
    docs/adr/006-enum-storage.md.
    """

    UP_TO_10 = "1-10"
    UP_TO_50 = "11-50"
    UP_TO_200 = "51-200"
    UP_TO_1000 = "201-1000"
    OVER_1000 = "1000+"


class TokenPurpose(enum.StrEnum):
    """What a one-time email token is for.

    Text with a CHECK constraint, not a PostgreSQL ENUM — see
    docs/adr/006-enum-storage.md.
    """

    VERIFICATION = "verification"
    RESET = "reset"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A person who can sign in."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "company_size IN (" + ", ".join(f"'{size}'" for size in _values(CompanySize)) + ")",
            name="company_size",
        ),
    )

    # Globally unique: one account per person across the whole platform.
    # Lower-cased on the way in, so Nora@ and nora@ are the same account and
    # cannot become two.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)

    # NULLABLE, and not an oversight. NULL means "this account cannot sign in
    # with a password": someone who accepted an invitation before choosing
    # one, or — later — an SSO account. Forcing NOT NULL would mean inventing
    # a hash that must never verify, which is a landmine.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # NULL until the address is proven. An unverified account cannot sign in:
    # otherwise anyone can occupy someone else's address.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # When the password last changed. Every reset token issued before this
    # moment is dead, which is what makes "changing your password kills the
    # pending reset link" true without hunting for rows.
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Counted for observability — a sudden rise across many accounts is worth
    # an alert. NOT used to lock the account: locking after N failures means
    # anyone who knows an email address can deny that person access. Rate
    # limiting handles abuse; see docs/security.md.
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Who they are, as they said when registering: what an operator needs
    # to know before granting a workspace, and what the interface calls
    # them. Asked of every new account; NULL for the accounts made before
    # the site asked, and never required to sign in.
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company_size: Mapped[CompanySize | None] = mapped_column(
        Enum(
            CompanySize,
            name="company_size",
            native_enum=False,
            length=20,
            values_callable=_values,
            create_constraint=False,
        ),
        nullable=True,
    )

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def can_sign_in_with_password(self) -> bool:
        return self.password_hash is not None


class Session(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One signed-in browser.

    Opaque and server-side. The client holds a random token; this row holds
    its hash and everything that decides whether it is still valid. No JWT:
    a JWT cannot be revoked, and LEKA-331 requires that removing someone's
    membership cuts their access immediately. See
    docs/adr/008-opaque-sessions.md.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        # The cleanup job sweeps by expiry.
        Index("ix_sessions_expires_at", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # sha256 of the token in the cookie. The clear value exists only in the
    # browser: a leaked backup is not a set of usable sessions.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # Where this browser currently is. THIS is what makes LEKA-331's workspace
    # switching work, and why the workspace never travels in a header.
    # ON DELETE SET NULL: deleting a workspace must not delete the sessions of
    # people who happened to be looking at it.
    active_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Two limits, not one. expires_at is the absolute maximum; last_seen_at
    # drives the idle timeout. A session is dead when either is exceeded.
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Set when signing out, or when another session revokes this one. Kept
    # rather than deleted so "you were signed out elsewhere" can be explained.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # For the "your active sessions" screen: enough to recognise a device,
    # not enough to track a person.
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # TRUNCATED before storage: /24 for IPv4, /48 for IPv6. A full address is
    # personal data under GDPR and we have no use for one — the purpose is
    # "was this roughly the same network", not "where exactly were you".
    ip_prefix: Mapped[str | None] = mapped_column(String(45), nullable=True)


class EmailToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single-use token emailed to someone.

    Verification and reset share a table because they share every rule:
    hashed at rest, single use, time limited, and consumed rather than
    deleted so a replay can be told apart from a token that never existed.
    """

    __tablename__ = "email_tokens"
    __table_args__ = (Index("ix_email_tokens_user_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    purpose: Mapped[TokenPurpose] = mapped_column(
        Enum(
            TokenPurpose,
            name="purpose",
            native_enum=False,
            length=50,
            values_callable=_values,
        ),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
