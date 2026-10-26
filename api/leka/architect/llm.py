"""The language model the architect asks — any, chosen by configuration:

    anthropic   Claude, by Anthropic's Messages API
    openai      any API that speaks OpenAI's chat completions: OpenAI, Azure
                OpenAI, Mistral, Ollama, vLLM, LM Studio, most internal LLMs
                — its address and its model free

Configured by the environment (or a .env file, cli.py):

    ARCHITECT_LLM_PROVIDER     anthropic | openai | azure
    ARCHITECT_LLM_MODEL        the model, e.g. claude-sonnet-5, gpt-4.1, mistral-large
    ARCHITECT_LLM_API_KEY      its key (none for a local Ollama)
    ARCHITECT_LLM_BASE_URL     its address: https://api.openai.com/v1 by default;
                          http://localhost:11434/v1 for Ollama
    ARCHITECT_LLM_API_VERSION  Azure only, e.g. 2024-10-21; with azure, BASE_URL is
                          https://<resource>.openai.azure.com and MODEL its
                          deployment's name

Nothing else is called: no LEKA server, no telemetry. The key never
appears in a message.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

TIMEOUT = 300
RETRIES = 4
MAX_TOKENS = 16_000


class LLMError(Exception):
    """What the model's API refused, said so a person can act on it."""


Poster = Callable[[str, "dict[str, str]", bytes], "tuple[int, bytes]"]


def _post(url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310 - the configured model
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:  # noqa: S310
            return answer.status, answer.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


@dataclass
class LLM:
    """A model, asked one system message and one user message at a time."""

    provider: str
    model: str
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    api_version: str = ""
    max_tokens: int = MAX_TOKENS
    post: Poster | None = field(default=None, repr=False)
    pause: float = 2.0

    def __post_init__(self) -> None:
        if self.provider not in ("anthropic", "openai", "azure"):
            raise LLMError(f"Fournisseur inconnu : {self.provider} (anthropic, openai ou azure).")
        if not self.model:
            raise LLMError("Le modèle n'est pas renseigné (ARCHITECT_LLM_MODEL).")
        if self.provider == "anthropic" and not self.api_key:
            raise LLMError("La clé Anthropic n'est pas renseignée (ARCHITECT_LLM_API_KEY).")
        if self.provider == "azure" and not (self.base_url and self.api_version and self.api_key):
            raise LLMError(
                "Azure OpenAI demande ARCHITECT_LLM_BASE_URL, ARCHITECT_LLM_API_VERSION "
                "et ARCHITECT_LLM_API_KEY."
            )

    @property
    def said(self) -> str:
        """Which model, as a person reads it — never its key."""
        where = urllib.parse.urlsplit(self.base_url).netloc if self.base_url else ""
        return f"{self.provider} · {self.model}" + (f" · {where}" if where else "")

    def _request(self, system: str, user: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        if self.provider == "anthropic":
            url = (self.base_url.rstrip("/") or "https://api.anthropic.com") + "/v1/messages"
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            body: dict[str, Any] = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            return url, headers, body
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.provider == "azure":
            url = (
                f"{self.base_url.rstrip('/')}/openai/deployments/{urllib.parse.quote(self.model)}"
                f"/chat/completions?api-version={urllib.parse.quote(self.api_version)}"
            )
            headers = {"api-key": self.api_key, "content-type": "application/json"}
            return url, headers, {"messages": messages, "max_tokens": self.max_tokens}
        url = (self.base_url.rstrip("/") or "https://api.openai.com/v1") + "/chat/completions"
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return (
            url,
            headers,
            {"model": self.model, "messages": messages, "max_tokens": self.max_tokens},
        )

    @staticmethod
    def _text(provider: str, answer: Mapping[str, Any]) -> str:
        if provider == "anthropic":
            parts = answer.get("content") or []
            return "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
        choices = answer.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            return "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        return str(content or "")

    def __call__(self, system: str, user: str) -> str:
        url, headers, body = self._request(system, user)
        post = self.post or _post
        for attempt in range(RETRIES):
            try:
                status, payload = post(url, headers, json.dumps(body).encode())
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt == RETRIES - 1:
                    raise LLMError(f"Le modèle ne répond pas ({self.said}) : {error}") from None
                time.sleep(self.pause * (attempt + 1))
                continue
            if status in (429, 500, 502, 503, 504, 529) and attempt < RETRIES - 1:
                time.sleep(self.pause * 2**attempt)
                continue
            if status in (401, 403):
                raise LLMError(f"Le modèle refuse la clé ({self.said}, {status}).")
            if status >= 400:
                said = payload[:300].decode("utf-8", "replace").replace(self.api_key or "\0", "***")
                raise LLMError(f"Le modèle a répondu {status} ({self.said}) : {said}")
            text = self._text(self.provider, json.loads(payload))
            if not text.strip():
                raise LLMError(f"Le modèle n'a rien répondu ({self.said}).")
            return text
        raise LLMError(f"Le modèle ne répond pas ({self.said}).")


def from_env(environ: Mapping[str, str] | None = None) -> LLM:
    """The model the environment names."""
    env = os.environ if environ is None else environ
    return LLM(
        provider=env.get("ARCHITECT_LLM_PROVIDER", "openai").strip().lower(),
        model=env.get("ARCHITECT_LLM_MODEL", "").strip(),
        api_key=env.get("ARCHITECT_LLM_API_KEY", "").strip(),
        base_url=env.get("ARCHITECT_LLM_BASE_URL", "").strip(),
        api_version=env.get("ARCHITECT_LLM_API_VERSION", "").strip(),
        max_tokens=int(env.get("ARCHITECT_LLM_MAX_TOKENS", str(MAX_TOKENS)) or MAX_TOKENS),
    )


__all__ = ["LLM", "LLMError", "from_env"]
