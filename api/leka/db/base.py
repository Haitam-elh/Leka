"""The declarative base every LEKA table inherits from.

Holds no columns of its own — see mixins.py for those. Its one job is to
carry a naming convention, so that constraints and indexes get deterministic
names instead of whatever PostgreSQL improvises. Without it, Alembic
autogenerate produces migrations that try to drop and recreate constraints it
cannot name, and rule 10 (never edit a merged migration) becomes painful.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every module's models.py."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
