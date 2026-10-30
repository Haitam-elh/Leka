"""What a person says, written (2026-10-29): an intention dictated.

The browser records it as WAV, 16 kHz, one channel — every browser can,
where its own speech recognition fails without a word (Brave, Arc,
Firefox, Safari without dictation turned on: « je clique, je parle, rien ne
s'écrit ») — and it is transcribed by the first provider LEKA holds a key
for, the cheapest first:

    mistral    Voxtral, its transcription endpoint
    openai     its transcription endpoint
    google     Gemini, the audio read as part of the question

A fraction of a cent a dictation. None reachable: NoModelError, said as such.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
import structlog

from leka.capabilities.gateway.profiles import DEFAULTS
from leka.capabilities.gateway.service import NoModelError
from leka.core.config import settings

logger = structlog.get_logger(__name__)

MISTRAL_URL = "https://api.mistral.ai/v1/audio/transcriptions"
MISTRAL_MODEL = "voxtral-mini-latest"
OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_MODEL = "gpt-4o-mini-transcribe"
GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Two minutes of speech at most, as the browser records it.
MAX_AUDIO_BYTES = 10 * 1024 * 1024
TIMEOUT = 60.0
SAID_AS = (
    "Transcribe this recording exactly as it is spoken, in its own language. "
    "Answer with the spoken words only: no title, no comment, no quotes."
)


@dataclass(frozen=True)
class Transcript:
    text: str
    provider: str
    model: str


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT)


def _language(tag: str | None) -> str | None:
    """« fr-FR » → « fr »: the providers want the language alone."""
    if not tag:
        return None
    short = tag.split("-")[0].lower()
    return short if short.isalpha() and len(short) in (2, 3) else None


async def _mistral(key: str, audio: bytes, language: str | None) -> Transcript:
    data = {"model": MISTRAL_MODEL, **({"language": language} if language else {})}
    async with _client() as client:
        answer = await client.post(
            MISTRAL_URL,
            headers={"Authorization": f"Bearer {key}"},
            data=data,
            files={"file": ("dictee.wav", audio, "audio/wav")},
        )
    answer.raise_for_status()
    return Transcript(str(answer.json().get("text") or ""), "mistral", MISTRAL_MODEL)


async def _openai(key: str, audio: bytes, language: str | None) -> Transcript:
    data = {"model": OPENAI_MODEL, **({"language": language} if language else {})}
    async with _client() as client:
        answer = await client.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {key}"},
            data=data,
            files={"file": ("dictee.wav", audio, "audio/wav")},
        )
    answer.raise_for_status()
    return Transcript(str(answer.json().get("text") or ""), "openai", OPENAI_MODEL)


async def _google(key: str, audio: bytes, language: str | None) -> Transcript:
    model = DEFAULTS["google"]
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": SAID_AS},
                    {
                        "inline_data": {
                            "mime_type": "audio/wav",
                            "data": base64.b64encode(audio).decode(),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {"temperature": 0},
    }
    async with _client() as client:
        answer = await client.post(
            GOOGLE_URL.format(model=model), headers={"x-goog-api-key": key}, json=body
        )
    answer.raise_for_status()
    parts = ((answer.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    text = "".join(str(p.get("text") or "") for p in parts if not p.get("thought"))
    return Transcript(text, "google", model)


Transcriber = Callable[[str, bytes, str | None], Awaitable[Transcript]]
ORDER: tuple[tuple[str, Transcriber], ...] = (
    ("mistral", _mistral),
    ("openai", _openai),
    ("google", _google),
)


def _key(provider: str) -> str | None:
    secret = {
        "mistral": settings.mistral_api_key,
        "openai": settings.openai_api_key,
        "google": settings.google_api_key,
    }[provider]
    return secret.get_secret_value() if secret is not None else None


async def transcribe(audio: bytes, *, language: str | None = None) -> Transcript:
    """What `audio` (WAV) says, by the first provider that answers — the
    next one tried when it fails. NoModelError when none could."""
    short = _language(language)
    tried: list[str] = []
    for provider, call in ORDER:
        key = _key(provider)
        if not key:
            continue
        try:
            done = await call(key, audio, short)
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
            logger.warning("transcription_failed", provider=provider, error=str(error)[:300])
            tried.append(provider)
            continue
        logger.info("transcribed", provider=provider, model=done.model, chars=len(done.text))
        return Transcript(done.text.strip(), done.provider, done.model)
    raise NoModelError(
        "No provider could transcribe it." if tried else "No provider to transcribe with.",
        reason="unanswered" if tried else "none",
    )
