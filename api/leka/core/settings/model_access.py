"""How LEKA reaches language models, and with what keys (LEKA-394).

Which model each agent runs on is not set here: it is the agent's own
configuration, agents/models.yaml (LEKA-530) — chosen and validated by the
LEKA team, changed by a reviewed pull request, never by an environment.

Consumed by leka.capabilities and nowhere else (architecture rule 7). Every
key is optional: the platform boots and serves without a model — what needs
one says so, and what does not works the same.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import SecretStr, field_validator

from leka.core.settings._blank import blank_is_none
from leka.core.settings._rotation import RotateEvery

Provider = Literal["google", "mistral", "anthropic", "openai"]


class ModelAccessSettings:
    """One key per provider, where a provider is reached, how often a
    temporary failure is tried again — and, outside production, one model
    for every agent while a candidate is tried."""

    # The provider LEKA_LLM_API_URL reaches, when it is set.
    llm_provider: Provider = "google"
    # Each failure a provider says is temporary (busy, rate-limited, down)
    # is tried again this many times, then the agent's approved fallback
    # is, if it has one (agents/models.yaml).
    llm_retries: int = 1
    # An agent's deliverable short of a section its agent gives is said back
    # to the model this many times at most, to write again (2026-10-22: any
    # model, the same deliverable); then delivered, said incomplete. 0: not
    # checked at all.
    agent_corrections: int = 2
    # Where LEKA_LLM_PROVIDER's models are reached when not at its own
    # address: a proxy, a regional endpoint — the browser tests point it at
    # a local stand-in. https in production (config.py).
    llm_api_url: str | None = None
    # Every agent and LEKA's own work on this one model, "provider:model",
    # instead of the one assigned to it (LEKA-530): a candidate tried before
    # it is validated, a development machine without the assigned model's
    # key. Never in production (config.py).
    llm_trial_model: str | None = None

    google_api_key: Annotated[SecretStr | None, RotateEvery(days=90)] = None
    mistral_api_key: Annotated[SecretStr | None, RotateEvery(days=90)] = None
    anthropic_api_key: Annotated[SecretStr | None, RotateEvery(days=90)] = None
    openai_api_key: Annotated[SecretStr | None, RotateEvery(days=90)] = None

    @field_validator(
        "google_api_key",
        "anthropic_api_key",
        "mistral_api_key",
        "openai_api_key",
        "llm_api_url",
        "llm_trial_model",
        mode="before",
    )
    @classmethod
    def _blank_model_key_is_not_configured(cls, value: object) -> object:
        """A blank key is no key. See core/settings/_blank.py."""
        return blank_is_none(value)

    @property
    def llm_api_key(self) -> SecretStr | None:
        """The key of LEKA_LLM_PROVIDER — the provider LEKA_LLM_API_URL
        reaches — if it is configured. leka.capabilities is the only module
        that reads a model key (architecture rule 7)."""
        keys: dict[str, SecretStr | None] = {
            "google": self.google_api_key,
            "mistral": self.mistral_api_key,
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
        }
        return keys[self.llm_provider]

    @property
    def has_model_access(self) -> bool:
        return any(
            key is not None
            for key in (
                self.google_api_key,
                self.mistral_api_key,
                self.anthropic_api_key,
                self.openai_api_key,
            )
        )


__all__ = ["ModelAccessSettings", "Provider"]
