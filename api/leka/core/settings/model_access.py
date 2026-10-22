"""Which language model LEKA talks to by default, what it falls back on,
and with what keys (LEKA-394).

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
    """The default model, the fallbacks, and one key per provider.

    The default is Google's Gemini 3.8 Flash (the MVP's choice, LEKA-394):
    configured here, never written into what uses it — a capability asks for
    what it needs (structured output, tools, a long context), the router
    picks the model. Two providers at least, on purpose: an abstraction
    validated against one implementation only fits that one; the second is
    what proves the gateway holds, and what answers when the first does not.
    """

    llm_provider: Provider = "google"
    llm_model: str = "gemini-3.8-flash"
    # Tried in order when the default fails or cannot do what is asked:
    # "provider:model", comma-separated. Empty: every other provider a key
    # is set for, with its own default.
    llm_fallbacks: str = ""
    # Each failure a provider says is temporary (busy, rate-limited, down)
    # is tried again this many times, then the next model is.
    llm_retries: int = 1
    # An agent's deliverable short of a section its agent gives is said back
    # to the model this many times at most, to write again (2026-10-22: any
    # model, the same deliverable); then delivered, said incomplete. 0: not
    # checked at all.
    agent_corrections: int = 2
    # The models each kind of work tries first (LEKA-491): "code=anthropic:
    # claude-sonnet-5; vision=openai:gpt-4.1". Empty: none has its own.
    llm_task_routes: str = ""
    # Where LEKA's default model is reached when not at its provider's own
    # address: a proxy, a regional endpoint — the browser tests point it at
    # a local stand-in. https in production (config.py).
    llm_api_url: str | None = None

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
        mode="before",
    )
    @classmethod
    def _blank_model_key_is_not_configured(cls, value: object) -> object:
        """A blank key is no key. See core/settings/_blank.py."""
        return blank_is_none(value)

    @property
    def llm_api_key(self) -> SecretStr | None:
        """The key for the default provider, if it is configured.

        None means the default model is not reachable. leka.capabilities is
        the only module that reads this, and the only one entitled to fail on
        it — the rest of the platform works without a model.
        """
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
