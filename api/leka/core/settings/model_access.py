"""Which model provider LEKA talks to, and with what key.

Consumed by leka.capabilities and nowhere else (architecture rule 7). Both
keys are optional: the platform boots and serves without a model configured.
"""

from __future__ import annotations

from typing import Literal

from pydantic import SecretStr, field_validator

from leka.core.settings._blank import blank_is_none


class ModelAccessSettings:
    """Provider selection and the two API keys.

    Two providers from the start, on purpose. An abstraction validated
    against a single implementation is an abstraction that fits one
    implementation; the second provider is what proves the gateway holds.

    Mistral is the default, not Anthropic. The commercial argument is "your
    data stays in Europe", which only holds if the European path is the one
    exercised every day rather than an option discovered broken in front of
    a customer's security officer.
    """

    llm_provider: Literal["mistral", "anthropic"] = "mistral"
    anthropic_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None

    @field_validator("anthropic_api_key", "mistral_api_key", mode="before")
    @classmethod
    def _blank_model_key_is_not_configured(cls, value: object) -> object:
        """A blank key is no key. See core/settings/_blank.py."""
        return blank_is_none(value)

    @property
    def llm_api_key(self) -> SecretStr | None:
        """The key for the selected provider, if it is configured.

        None means no model is reachable. leka.capabilities is the only
        module that reads this, and the only one entitled to fail on it —
        the rest of the platform works without a model.
        """
        keys: dict[str, SecretStr | None] = {
            "anthropic": self.anthropic_api_key,
            "mistral": self.mistral_api_key,
        }
        return keys[self.llm_provider]

    @property
    def has_model_access(self) -> bool:
        return self.llm_api_key is not None


__all__ = ["ModelAccessSettings"]
