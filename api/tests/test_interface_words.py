"""The whole interface in any language (2026-10-30): « quand on clique sur
une langue, ce n'est pas que la réponse de LEKA dans la langue choisie, mais
toute l'interface ».

What these protect: a language without a dictionary is translated by LEKA's
own model the first time someone asks for it — never English or French,
never a language LEKA does not offer; its words kept batch by batch, each
with the English it translates; a translation that loses a placeholder or a
plural asked again, told why, then left in English; a word whose English
changed translated again, the others never; no model answering said, and
tried again later; the route public, starting it once; LEKA's own model
answering for no workspace, the next one when the first fails.
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from leka.capabilities import (
    InterfaceWords,
    Message,
    NoModelError,
    Request,
    translate_interface,
)
from leka.capabilities.gateway import Completion, Usage, leka_complete
from leka.db import session_factory

interface = importlib.import_module("leka.capabilities.interface")

pytestmark = pytest.mark.integration

API = "/api/v1/interface"
ENGLISH = {
    "nav.overview": "My Dashboard",
    "nav.newIntention": "New intention",
    "language.saved": "Language saved: {name}",
    "sources.count": "{count} {count|source|sources}",
    "billing.features.0": "Unlimited sources",
}
SPANISH = {
    "My Dashboard": "Mi panel",
    "New intention": "Nueva intención",
    "Language saved: {name}": "Idioma guardado: {name}",
    "{count} {count|source|sources}": "{count} {count|fuente|fuentes}",
    "Unlimited sources": "Fuentes ilimitadas",
}


@pytest.fixture(autouse=True)
async def small_interface(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict[str, str]]:
    """Five words for the interface, not seven thousand; no row left."""
    english = dict(ENGLISH)
    monkeypatch.setattr(interface, "interface_english", lambda: english)
    async with session_factory() as session:
        await session.execute(delete(InterfaceWords))
        await session.commit()
    yield english
    async with session_factory() as session:
        await session.execute(delete(InterfaceWords))
        await session.commit()


def _done(text: str) -> Completion:
    return Completion(
        text=text,
        tool_calls=(),
        provider="mistral",
        model="mistral-medium-latest",
        version="mistral-medium-latest",
        usage=Usage(),
        latency_ms=1,
    )


def _asked(request: Request) -> dict[str, dict[str, str]]:
    said = request.messages[-1].content
    # What it is told comes first, the words to translate last.
    start = said.rindex("\n\n{") + 2 if "\n\n{" in said else 0
    asked: dict[str, dict[str, str]] = json.loads(said[start:])
    return asked


class Translator:
    """A model that translates as told: SPANISH, except what `wrong` says."""

    def __init__(self, wrong: dict[str, list[str]] | None = None) -> None:
        self.wrong = {key: list(value) for key, value in (wrong or {}).items()}
        self.requests: list[Request] = []

    async def __call__(self, request: Request) -> Completion:
        self.requests.append(request)
        answer: dict[str, str] = {}
        for at, asked in _asked(request).items():
            english = asked["en"]
            bad = self.wrong.get(english)
            answer[at] = bad.pop(0) if bad else SPANISH[english]
        return _done("```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```")


async def _row(tag: str = "es") -> InterfaceWords:
    async with session_factory() as session:
        found = await session.scalar(select(InterfaceWords).where(InterfaceWords.tag == tag))
        assert found is not None
        return found


async def test_a_language_is_translated_whole_and_kept_with_the_english_it_translates() -> None:
    model = Translator()
    said = await translate_interface("es", complete=model)

    assert said == {"translated": 5, "failed": 0}
    row = await _row()
    assert row.status == "ready"
    assert row.words == {key: SPANISH[text] for key, text in ENGLISH.items()}
    assert row.sources == ENGLISH
    assert row.failed == []
    assert row.model == "mistral:mistral-medium-latest"
    # Told the language, the placeholders, and where each word appears.
    asked = model.requests[0]
    assert "Spanish (Español, es)" in asked.messages[0].content
    assert "{{" not in asked.messages[0].content
    assert _asked(asked)["1"] == {"at": "nav.overview", "en": "My Dashboard"}
    assert asked.purpose == "interface.translation"


async def test_a_word_that_loses_a_placeholder_is_asked_again_then_left_in_english() -> None:
    model = Translator(
        wrong={
            # Wrong once, right the second time.
            "Language saved: {name}": ["Idioma guardado: {nombre}"],
            # Wrong twice: stays in English.
            "{count} {count|source|sources}": ["{count} fuentes", "{count} fuentes"],
        }
    )
    said = await translate_interface("es", complete=model)

    assert said == {"translated": 4, "failed": 1}
    row = await _row()
    assert row.words["language.saved"] == "Idioma guardado: {name}"
    assert "sources.count" not in row.words
    assert row.failed == ["sources.count"]
    assert row.status == "ready"
    # Asked again told why, the words alone.
    again = model.requests[-1].messages[-1].content
    assert "{count|one form|other form}" in again
    assert "must keep exactly the placeholders of the English: {name}" in again
    assert set(_asked(model.requests[-1])) == {"1", "2"}


async def test_only_what_changed_in_english_is_translated_again(
    small_interface: dict[str, str],
) -> None:
    await translate_interface("es", complete=Translator())
    small_interface["nav.overview"] = "New intention"  # its English changed
    small_interface["nav.help"] = "My Dashboard"  # a new word

    async with session_factory() as session:
        found = await interface.interface_of(session, "es")
    assert found is not None
    assert found.due
    assert found.done == 4
    assert "nav.overview" not in found.words  # its translation no longer says it

    model = Translator()
    await translate_interface("es", complete=model)
    assert [asked["at"] for asked in _asked(model.requests[0]).values()] == [
        "nav.overview",
        "nav.help",
    ]
    row = await _row()
    assert row.words["nav.overview"] == "Nueva intención"
    assert row.words["nav.help"] == "Mi panel"


async def test_no_model_answering_is_said_and_nothing_is_left_in_english_for_it() -> None:
    async def none(request: Request) -> Completion:
        raise NoModelError("No language model is configured.", reason="none")

    said = await translate_interface("es", complete=none)

    assert said == {"translated": 0, "failed": 0}
    row = await _row()
    assert row.status == "failed"
    assert row.error is not None and "No model answered" in row.error
    assert row.failed == []
    assert row.words == {}


async def test_a_long_dash_never_reaches_the_screens() -> None:
    model = Translator(wrong={"My Dashboard": ["Mi panel — inicio"]})
    await translate_interface("es", complete=model)
    assert (await _row()).words["nav.overview"] == "Mi panel, inicio"


def test_what_a_translation_must_keep() -> None:
    assert interface.wrong("Saved: {name}", "Guardado: {name}") is None
    assert interface.wrong("{count} {count|a|b}", "{count} {count|x|y}") is None
    assert interface.wrong("Saved: {name}", "Guardado") is not None
    assert interface.wrong("{count} {count|a|b}", "{count} fuentes") is not None
    assert interface.wrong("Hello", "") is not None
    assert interface.wrong("Hi", "Hola " * 50) is not None


async def test_english_french_and_unknown_languages_are_not_translated() -> None:
    model = Translator()
    for tag in ("en", "fr", "tlh", "en-XA"):
        assert await translate_interface(tag, complete=model) == {"translated": 0, "failed": 0}
    assert model.requests == []


# ── over HTTP ───────────────────────────────────────────────────────────────


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    jobs: list[tuple[Any, ...]] = []

    async def enqueue(job: str, *args: object, **kwargs: object) -> object:
        jobs.append((job, *args, kwargs.get("concurrency_key")))
        return object()

    monkeypatch.setattr(interface, "enqueue_job", enqueue)
    return jobs


async def test_the_first_ask_starts_the_translation_once_without_a_session(
    client: AsyncClient, queued: list[tuple[Any, ...]]
) -> None:
    first = await client.get(f"{API}/es")
    assert first.status_code == 200, first.text
    assert first.json() == {
        "tag": "es",
        "status": "translating",
        "done": 0,
        "total": 5,
        "model": None,
        "words": {},
    }
    assert first.headers["cache-control"] == "no-store"
    assert queued == [
        ("leka.capabilities.interface.translate_interface_job", "es", "interface-words:es")
    ]

    # Under way: asked again, not started again.
    again = await client.get(f"{API}/es", params={"words": "false"})
    assert again.json()["status"] == "translating"
    assert len(queued) == 1


async def test_its_words_once_translated_and_every_language_said(
    client: AsyncClient, queued: list[tuple[Any, ...]]
) -> None:
    await translate_interface("es", complete=Translator())

    said = await client.get(f"{API}/es")
    assert said.status_code == 200
    assert said.json()["status"] == "ready"
    assert said.json()["done"] == said.json()["total"] == 5
    assert said.json()["words"]["nav.overview"] == "Mi panel"
    assert said.headers["cache-control"] == "public, max-age=300"
    assert queued == []

    light = await client.get(f"{API}/es", params={"words": "false"})
    assert light.json()["words"] == {}

    every = await client.get(API)
    assert every.status_code == 200
    assert every.json() == [
        {
            "tag": "es",
            "status": "ready",
            "done": 5,
            "total": 5,
            "model": "mistral:mistral-medium-latest",
        }
    ]


async def test_a_language_with_its_own_dictionary_is_not_lekas(
    client: AsyncClient, queued: list[tuple[Any, ...]]
) -> None:
    for tag in ("fr", "en", "tlh"):
        assert (await client.get(f"{API}/{tag}")).status_code == 404
    assert queued == []


# ── LEKA's own model, for no workspace ─────────────────────────────────────


def _mistral(text: str) -> dict[str, Any]:
    return {
        "id": "x",
        "model": "mistral-medium-latest",
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


async def test_leka_s_own_model_answers_and_the_next_one_when_it_fails() -> None:
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.host)
        if request.url.host == "api.openai.com":
            return httpx.Response(503, json={"error": {"message": "down"}})
        assert request.headers["authorization"] == "Bearer mistral-key"
        return httpx.Response(200, json=_mistral('{"1": "Mi panel"}'))

    done = await leka_complete(
        Request(purpose="interface.translation", messages=[Message.user("Translate")]),
        transport=httpx.MockTransport(answer),
        keys={"openai": "openai-key", "mistral": "mistral-key"},
        default=("openai", "gpt-4.1-mini"),
        fallbacks=[("mistral", "mistral-medium-latest")],
        retries=0,
    )
    assert done.provider == "mistral"
    assert done.text == '{"1": "Mi panel"}'
    assert asked == ["api.openai.com", "api.mistral.ai"]


async def test_no_key_at_all_is_said() -> None:
    with pytest.raises(NoModelError, match=re.escape("No language model is configured.")):
        await leka_complete(
            Request(purpose="interface.translation", messages=[Message.user("Translate")]),
            keys={},
            default=("mistral", "mistral-medium-latest"),
            fallbacks=[],
        )
