"""The whole interface in any language LEKA offers (2026-10-30): « quand on
clique sur une langue, ce n'est pas que la réponse de LEKA dans la langue
choisie, mais toute l'interface ».

English and French have their dictionaries, written and reviewed. Every
other language of the catalogue is translated by LEKA's own model the first
time someone chooses it — in the background, by batches, the first screens
first — and kept for everyone who chooses it after: one translation a
language, paid by LEKA once, never by a customer's credits.

    interface_of(session, tag)        what is translated so far, and whether
                                      a translation is due
    start_translating(session, tag)   marks it under way, for a worker
    translate_interface(tag)          the worker: what is missing or whose
                                      English changed, translated and kept
                                      batch by batch — the screens switch as
                                      it goes

A translation keeps every {placeholder} and every {count|one|other} of its
English, or it is asked again with what was wrong; still wrong, the word
stays in English (`failed`) — never a broken screen.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import JobQueue, enqueue_job
from leka.capabilities.gateway import (
    Completion,
    Message,
    NoModelError,
    Request,
    Tier,
    leka_complete,
)
from leka.capabilities.models import InterfaceWords
from leka.core.languages import describe, interface_english, language, status
from leka.db import session_factory

logger = structlog.get_logger(__name__)

TRANSLATE_JOB = "leka.capabilities.interface.translate_interface_job"
# Words asked at once, and batches at once: ~7 000 words in a few minutes.
BATCH = 120
AT_ONCE = 4
# The words a model got wrong, asked again together, told why.
RETRY_BATCH = 40
# A translation under way that said nothing for this long died with its
# worker: started again, from where it stopped.
STALE = timedelta(minutes=20)
# No model answered: tried again after this long, at the next visit.
RETRY_AFTER = timedelta(hours=1)
# The sections people meet first, translated first; the others in the
# dictionary's order.
FIRST = (
    "nav",
    "pillars",
    "shell",
    "tabs",
    "states",
    "language",
    "auth",
    "overview",
    "composer",
    "forms",
    "validation",
    "interactions",
    "palette",
    "notifications",
    "intentions",
    "intent",
    "decisions",
    "environment",
)

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_PLURAL = re.compile(r"\{(\w+)\|[^{}|]*\|[^{}]*\}")

INSTRUCTIONS = """You translate the user interface of LEKA, a business platform that \
understands a company's IT environment (its sources, applications, data, people) and carries \
out what people ask of it (« intentions ») with AI agents. Translate from English into \
{language}.

You are given a JSON object: for each id, where the text appears in the interface (`at`) and \
the English text (`en`). Answer with one JSON object only, every id given, its translation as \
a string: {{"1": "...", "2": "..."}}. Nothing before or after it.

- Natural and short, the words software in that language uses for menus, buttons and \
messages; the same plain, direct tone as the English. Address the reader as the English does.
- Keep every placeholder in braces exactly as it is: {{name}}, {{count}}, {{date}}.
- A plural is written {{count|one form|other form}}: keep the braces, the name before the \
first « | » and both « | », and translate the two forms (singular, plural) as the language \
says them with that number.
- Keep as they are: product and company names (LEKA, LEKA CORE, GitHub, Jira, Confluence, \
Slack, Stripe, Mistral, Gemini, Claude…), code, URLs, file names, e-mail addresses, keys of \
the keyboard (⌘K, Esc), units and acronyms everyone uses (API, PDF, CSV, SQL, SSO, PR).
- Keep the line breaks (\\n) where the English has them.
- Never use the long dash (—): a colon, a comma or parentheses instead.
"""


@dataclass(frozen=True)
class Interface:
    """A language's interface as translated so far."""

    tag: str
    # translating, ready, failed — or none: never asked yet.
    status: str
    done: int
    total: int
    words: dict[str, str]
    model: str | None
    # Whether a translation should start: never asked, English changed since,
    # a worker that died, a failure long enough ago.
    due: bool


def translatable(tag: str) -> bool:
    """A language of the catalogue whose app has no dictionary: translated
    by LEKA. English and French have theirs."""
    return language(tag) is not None and status("app", tag) is None


def _missing(row: InterfaceWords | None, english: dict[str, str]) -> list[str]:
    """The words still to translate: never asked, or whose English changed
    since — those a model failed on stay in English, unless their English
    changed too."""
    if row is None:
        return list(english)
    sources, words, failed = row.sources, row.words, set(row.failed)
    return [
        key
        for key, text in english.items()
        if sources.get(key) != text or (key not in words and key not in failed)
    ]


def _current(row: InterfaceWords, english: dict[str, str]) -> dict[str, str]:
    """Its words still translating the English as it is now."""
    return {
        key: said
        for key, said in row.words.items()
        if key in english and row.sources.get(key) == english[key]
    }


async def _row(session: AsyncSession, tag: str) -> InterfaceWords | None:
    found: InterfaceWords | None = await session.scalar(
        select(InterfaceWords).where(InterfaceWords.tag == tag)
    )
    return found


async def interface_of(
    session: AsyncSession, tag: str, *, now: datetime | None = None, words: bool = True
) -> Interface | None:
    """A language's interface: its words so far, and whether a translation
    is due. None: not a language LEKA translates this way."""
    if not translatable(tag):
        return None
    moment = now or datetime.now(UTC)
    english = interface_english()
    row = await _row(session, tag)
    if row is None:
        return Interface(tag, "none", 0, len(english), {}, None, due=True)
    current = _current(row, english)
    missing = _missing(row, english)
    due = bool(missing) and (
        row.status == "ready"
        or (row.status == "translating" and (row.started_at or row.updated_at) < moment - STALE)
        or (row.status == "failed" and row.updated_at < moment - RETRY_AFTER)
    )
    return Interface(
        tag,
        "ready" if not missing and row.status != "translating" else row.status,
        len(english) - len(missing),
        len(english),
        current if words else {},
        row.model,
        due=due,
    )


async def interfaces(session: AsyncSession) -> list[Interface]:
    """Every language LEKA translated, or is translating — without their
    words: what the language picker says of each."""
    english = interface_english()
    rows = (await session.scalars(select(InterfaceWords).order_by(InterfaceWords.tag))).all()
    out: list[Interface] = []
    for row in rows:
        if not translatable(row.tag):
            continue
        missing = _missing(row, english)
        out.append(
            Interface(
                row.tag,
                "ready" if not missing and row.status != "translating" else row.status,
                len(english) - len(missing),
                len(english),
                {},
                row.model,
                due=False,
            )
        )
    return out


async def start_translating(
    session: AsyncSession, tag: str, *, now: datetime | None = None
) -> bool:
    """Its translation marked under way and handed to a worker. False: one
    is already under way."""
    moment = now or datetime.now(UTC)
    await session.execute(
        insert(InterfaceWords)
        .values(tag=tag, status="translating", started_at=moment)
        .on_conflict_do_nothing(constraint="uq_interface_words_tag")
    )
    row = await _row(session, tag)
    if row is None:  # pragma: no cover - inserted just above
        return False
    row.status = "translating"
    row.started_at = moment
    row.error = None
    # Committed before the worker reads it: it may start at once.
    await session.commit()
    queued = await enqueue_job(
        TRANSLATE_JOB,
        tag,
        queue=JobQueue.DEFAULT,
        concurrency_key=f"interface-words:{tag}",
    )
    return queued is not None


# ── translating ─────────────────────────────────────────────────────────────


def wrong(english: str, said: str) -> str | None:
    """Why a translation cannot be shown in place of its English — None:
    it can."""
    if not said.strip():
        return "It is empty."
    if sorted(_PLACEHOLDER.findall(english)) != sorted(_PLACEHOLDER.findall(said)):
        kept = " ".join(f"{{{name}}}" for name in _PLACEHOLDER.findall(english)) or "none"
        return f"It must keep exactly the placeholders of the English: {kept}."
    if sorted(_PLURAL.findall(english)) != sorted(_PLURAL.findall(said)):
        return "It must keep each plural as {count|one form|other form}."
    if english.count("{") != said.count("{") or english.count("}") != said.count("}"):
        return "It must keep the braces of the English, no more, no less."
    if len(said) > 6 * len(english) + 80:
        return "It must be the translation alone."
    return None


def tidy(said: str) -> str:
    """No long dash in LEKA's words (2026-10-28), whatever the model wrote."""
    return said.replace(" — ", ", ").replace("—", "-").strip()


def _ordered(keys: Sequence[str]) -> list[str]:
    """The first screens first, then the dictionary's order."""
    rank = {section: at for at, section in enumerate(FIRST)}
    position = {key: at for at, key in enumerate(keys)}
    return sorted(keys, key=lambda key: (rank.get(key.split(".")[0], len(FIRST)), position[key]))


Complete = Callable[[Request], Awaitable[Completion]]


async def _leka(request: Request) -> Completion:
    return await leka_complete(request)


def _request(tag: str, batch: dict[str, str], english: dict[str, str], told: str = "") -> Request:
    ids = {str(at): key for at, key in enumerate(batch, start=1)}
    asked = {at: {"at": key, "en": english[key]} for at, key in ids.items()}
    question = json.dumps(asked, ensure_ascii=False, indent=0)
    if told:
        question = f"{told}\n\n{question}"
    return Request(
        purpose="interface.translation",
        tier=Tier.STANDARD,
        max_tokens=12_000,
        temperature=0.2,
        messages=[
            Message.system(INSTRUCTIONS.format(language=describe(tag))),
            Message.user(question),
        ],
        ref=f"interface:{tag}",
    )


def _answer(done: Completion) -> dict[str, object]:
    """The JSON object a model answered — fenced or not."""
    text = done.text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    text = fenced.group(1) if fenced else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        found = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return found if isinstance(found, dict) else {}


@dataclass
class _Batch:
    translated: dict[str, str]
    # Each word not translated usably, and why.
    refused: dict[str, str]
    model: str | None


async def _translate(
    tag: str,
    keys: list[str],
    english: dict[str, str],
    complete: Complete,
    told: str = "",
) -> _Batch:
    batch = {key: english[key] for key in keys}
    try:
        done = await complete(_request(tag, batch, english, told))
    except NoModelError as error:
        return _Batch({}, dict.fromkeys(keys, f"No model answered: {error}"), None)
    answered = _answer(done)
    translated: dict[str, str] = {}
    refused: dict[str, str] = {}
    for at, key in enumerate(keys, start=1):
        said = answered.get(str(at))
        if not isinstance(said, str):
            refused[key] = "It was not translated."
            continue
        said = tidy(said)
        why = wrong(english[key], said)
        if why is None:
            translated[key] = said
        else:
            refused[key] = why
    return _Batch(translated, refused, f"{done.provider}:{done.model}")


async def _keep(tag: str, batch: _Batch, english: dict[str, str], *, failed: bool) -> None:
    """A batch's words kept at once: the screens show them at their next
    look. `failed`: the words refused stay in English."""
    async with session_factory() as session:
        row = await _row(session, tag)
        if row is None:  # pragma: no cover - started_translating made it
            return
        words = dict(row.words)
        sources = dict(row.sources)
        words.update(batch.translated)
        for key in batch.translated:
            sources[key] = english[key]
        gave_up = set(row.failed) - set(batch.translated)
        # A model that answered wrong, twice: left in English. No model
        # answering says nothing of the words — asked again next time.
        if failed and batch.model is not None:
            for key in batch.refused:
                sources[key] = english[key]
                words.pop(key, None)
            gave_up |= set(batch.refused)
        row.words = words
        row.sources = sources
        row.failed = sorted(gave_up)
        if batch.model:
            row.model = batch.model
        row.started_at = datetime.now(UTC)
        await session.commit()


async def translate_interface(tag: str, *, complete: Complete | None = None) -> dict[str, int]:
    """What is missing of a language's interface, translated and kept batch
    by batch; what a model got wrong, asked again once, told why; then left
    in English. Ready at the end — failed when no model answered at all."""
    if not translatable(tag):
        return {"translated": 0, "failed": 0}
    ask = complete or _leka
    english = interface_english()
    async with session_factory() as session:
        row = await _row(session, tag)
        if row is None:
            await session.execute(
                insert(InterfaceWords)
                .values(tag=tag, status="translating", started_at=datetime.now(UTC))
                .on_conflict_do_nothing(constraint="uq_interface_words_tag")
            )
            await session.commit()
            row = await _row(session, tag)
        missing = _ordered(_missing(row, english))
    logger.info("interface_translation_started", tag=tag, words=len(missing))

    gate = asyncio.Semaphore(AT_ONCE)
    refused: dict[str, str] = {}
    translated = 0
    answered = False

    async def one(keys: list[str]) -> _Batch:
        async with gate:
            return await _translate(tag, keys, english, ask)

    answered_wrong: set[str] = set()
    batches = [missing[at : at + BATCH] for at in range(0, len(missing), BATCH)]
    for finished in asyncio.as_completed([one(keys) for keys in batches]):
        batch = await finished
        answered = answered or batch.model is not None
        refused.update(batch.refused)
        if batch.model is not None:
            answered_wrong |= set(batch.refused)
        translated += len(batch.translated)
        await _keep(tag, batch, english, failed=False)

    # Once again, the words refused, told why — then left in English.
    again = [key for key in missing if key in refused and answered]
    for at in range(0, len(again), RETRY_BATCH):
        keys = again[at : at + RETRY_BATCH]
        # What was wrong with each, when a model answered it at all.
        why = [f"- {english[key]!r}: {refused[key]}" for key in keys if key in answered_wrong]
        told = (
            "Your previous translation of these could not be used:\n" + "\n".join(why)
            if why
            else ""
        )
        batch = await _translate(tag, keys, english, ask, told)
        translated += len(batch.translated)
        for key in batch.translated:
            refused.pop(key, None)
        await _keep(tag, batch, english, failed=True)

    async with session_factory() as session:
        row = await _row(session, tag)
        if row is not None:
            if answered or not missing:
                row.status = "ready"
                row.error = None
            else:
                row.status = "failed"
                row.error = next(iter(refused.values()), "No model answered.")[:2000]
            await session.commit()
    logger.info(
        "interface_translation_done",
        tag=tag,
        translated=translated,
        failed=len(refused) if answered else 0,
    )
    return {"translated": translated, "failed": len(refused) if answered else 0}


def translate_interface_job(tag: str) -> dict[str, int]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(translate_interface(tag))
