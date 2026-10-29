"""An intention dictated (2026-10-29): the browser's own speech recognition
wrote nothing in some browsers — « je clique, je parle, rien ne s'écrit ».
The voice, recorded as WAV, is written by LEKA's providers.

What these protect: the recording written by the first provider LEKA holds
a key for — Mistral's Voxtral first, the language alone — the next tried
when it fails, Gemini reading the audio itself; nothing recorded refused,
too long refused, no provider said as unavailable; nothing of it kept.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from leka.capabilities.gateway import transcription
from leka.core.config import settings
from tests.test_context_engine import model
from tests.test_sources_api import acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/intentions/transcriptions"
WAV = b"RIFF" + b"\x00" * 40


def _keys(monkeypatch: pytest.MonkeyPatch, **keys: str | None) -> None:
    update = {
        f"{name}_api_key": SecretStr(value) if value else None
        for name, value in {"mistral": None, "openai": None, "google": None, **keys}.items()
    }
    monkeypatch.setattr(transcription, "settings", settings.model_copy(update=update))


def _providers(monkeypatch: pytest.MonkeyPatch, answer: httpx.MockTransport) -> None:
    monkeypatch.setattr(
        transcription, "_client", lambda: httpx.AsyncClient(transport=answer, timeout=5)
    )


async def test_what_is_said_is_written_by_mistral_first(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _keys(monkeypatch, mistral="m-key", google="g-key")
    asked: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, json={"text": " Pourquoi le paiement est lent ? "})

    _providers(monkeypatch, httpx.MockTransport(answer))
    said = await client.post(
        f"{API}?language=fr-FR", content=WAV, headers={"Content-Type": "audio/wav"}
    )
    assert said.status_code == 200, said.text
    assert said.json() == {"text": "Pourquoi le paiement est lent ?"}
    [request] = asked
    assert str(request.url) == transcription.MISTRAL_URL
    assert request.headers["authorization"] == "Bearer m-key"
    body = request.content
    assert b'name="model"\r\n\r\nvoxtral-mini-latest' in body
    assert b'name="language"\r\n\r\nfr' in body and WAV in body


async def test_a_provider_failing_hands_over_to_the_next_gemini_reading_the_audio(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _keys(monkeypatch, mistral="m-key", google="g-key")
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.host)
        if request.url.host == "api.mistral.ai":
            return httpx.Response(500, json={"message": "down"})
        sent = json.loads(request.content)
        [said, audio] = sent["contents"][0]["parts"]
        assert "Transcribe" in said["text"] and audio["inline_data"]["mime_type"] == "audio/wav"
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "Qui gère billing ?"}]}}]}
        )

    _providers(monkeypatch, httpx.MockTransport(answer))
    said = await client.post(API, content=WAV, headers={"Content-Type": "audio/wav"})
    assert said.json() == {"text": "Qui gère billing ?"}
    assert asked == ["api.mistral.ai", "generativelanguage.googleapis.com"]


async def test_nothing_recorded_too_long_or_no_provider_is_said(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _keys(monkeypatch)
    assert (await client.post(API, content=b"")).status_code == 422
    monkeypatch.setattr(transcription, "MAX_AUDIO_BYTES", 10)
    from leka.api import intentions as intentions_api

    monkeypatch.setattr(intentions_api, "MAX_AUDIO_BYTES", 10)
    assert (await client.post(API, content=WAV)).status_code == 413
    monkeypatch.setattr(intentions_api, "MAX_AUDIO_BYTES", 10_000)
    unavailable = await client.post(API, content=WAV, headers={"Content-Type": "audio/wav"})
    assert unavailable.status_code == 503
