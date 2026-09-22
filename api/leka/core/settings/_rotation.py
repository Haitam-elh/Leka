"""How long a secret should live before it is rotated.

Declared next to each secret's field, in its own domain file:

    secret_key: Annotated[SecretStr, RotateEvery(days=365)] = Field(...)

rather than in one table, because one table is the file two tickets collide
in. The number is a policy, so it lives in the code. When a secret WAS last
rotated is a fact about one environment, so it lives in that environment:
LEKA_SECRETS_ROTATED_ON.

    90 days    keys another company issued and sees used: cloud access keys,
               API keys. AWS recommends 90 days for its own access keys.
    365 days   what only we hold: our signing and encryption keys, and the
               passwords of the services we run.

tests/test_secret_age.py fails if a secret field declares none.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RotateEvery:
    """The recommended lifetime of the secret held by the annotated field."""

    days: int


__all__ = ["RotateEvery"]
