"""The interface in every language LEKA offers, over HTTP (2026-10-30) —
public: the sign-in page speaks the visitor's language too.

    GET /interface         every language LEKA translated, or is
                           translating: how far — what the language picker
                           says of each
    GET /interface/{tag}   a language's words so far, flat by key; the first
                           visit starts its translation (LEKA's model, paid
                           by LEKA), the screens switch as its words arrive.
                           ?words=false: how far only, to follow it. 404: a
                           language with its own dictionary, or none LEKA
                           offers

No session: the words are the product's, the same for everybody. Starting a
translation is held per address.
"""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, HTTPException, Request, Response, status

from leka.api.dependencies import SessionDep
from leka.api.identity import client_ip
from leka.capabilities import (
    Interface,
    InterfaceLanguageRead,
    InterfaceWordsRead,
    interface_of,
    interfaces,
    start_translating,
)
from leka.core import ratelimit

router = APIRouter(prefix="/interface", tags=["interface"])


def _read(found: Interface) -> InterfaceWordsRead:
    return InterfaceWordsRead(
        tag=found.tag,
        status=found.status,
        done=found.done,
        total=found.total,
        model=found.model,
        words=found.words,
    )


@router.get(
    "",
    response_model=list[InterfaceLanguageRead],
    summary="The languages LEKA translated the interface into",
)
async def interface_languages(session: SessionDep) -> list[InterfaceLanguageRead]:
    return [
        InterfaceLanguageRead(
            tag=one.tag,
            status=one.status,
            done=one.done,
            total=one.total,
            model=one.model,
        )
        for one in await interfaces(session)
    ]


@router.get(
    "/{tag}",
    response_model=InterfaceWordsRead,
    summary="A language's interface, translated by LEKA",
)
async def interface_words(
    tag: str,
    request: Request,
    response: Response,
    session: SessionDep,
    words: bool = True,
) -> InterfaceWordsRead:
    found = await interface_of(session, tag, words=words)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LEKA does not translate the interface into this language: it has its own.",
        )
    if found.due:
        verdict = await ratelimit.consume(
            "interface_translations:ip", client_ip(request), ratelimit.INTERFACE_TRANSLATIONS_PER_IP
        )
        if verdict.allowed:
            await start_translating(session, tag)
            found = replace(found, status="translating", due=False)
    # Under way: read again soon. Ready: the same for a while.
    response.headers["Cache-Control"] = (
        "public, max-age=300" if found.status == "ready" else "no-store"
    )
    return _read(found)
