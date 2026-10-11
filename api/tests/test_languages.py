"""The languages LEKA offers (docs/languages.md): the catalogue, as the
ticket listed it and as BCP 47 says it; how a browser's or a person's
language is matched; where a missing translation is looked up; what a
person and a workspace keep; what a model is told to write in.

What these protect: every one of the 140 languages offered, never one
twice, each with a tag a browser and a standard read; a language never
confused with a region; a translation never claimed where there is none;
a fallback that always ends in words; a choice kept on the account, so it
follows the person to every device.
"""

# ruff: noqa: F811 — the mailbox fixture is imported to be requested by name.

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import yaml
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select, text

from leka.capabilities import Task
from leka.capabilities.llm import LLMRuntime
from leka.capabilities.runtime import Injected, messages
from leka.core import languages
from leka.core.settings.paths import REPO_ROOT
from leka.db import session_factory, system_scope
from leka.identity import User, spoken_language, workspace_language
from leka.platform import Workspace
from tests.conftest import FakeIdentity
from tests.test_auth_api import API as AUTH
from tests.test_auth_api import (  # noqa: F401 — fixtures
    CapturingEmailSender,
    _register_and_verify,
    _sign_in,
    clean_users,
    mailbox,
)
from tests.test_workspace_api import _create_workspace, _make_user, _seat

API = "/api/v1"

# The ticket's catalogue, word for word: what was asked for.
ASKED = """English; Mandarin Chinese (Simplified); Mandarin Chinese (Traditional); Spanish;
French; Modern Standard Arabic; Egyptian Arabic; German; Portuguese; Italian; Dutch;
Russian; Ukrainian; Polish; Czech; Slovak; Slovenian; Croatian; Serbian; Bosnian;
Bulgarian; Macedonian; Romanian; Hungarian; Greek; Turkish; Azerbaijani; Armenian;
Georgian; Albanian; Lithuanian; Latvian; Estonian; Finnish; Swedish; Norwegian Bokmål;
Norwegian Nynorsk; Danish; Icelandic; Irish; Welsh; Scottish Gaelic; Basque; Catalan;
Galician; Maltese; Luxembourgish; Belarusian; Hebrew; Yiddish; Persian (Farsi); Dari;
Pashto; Urdu; Hindi; Bengali; Punjabi; Gujarati; Marathi; Nepali; Sinhala; Tamil;
Telugu; Kannada; Malayalam; Odia; Assamese; Sanskrit; Thai; Lao; Khmer; Vietnamese;
Indonesian; Malay; Javanese; Sundanese; Filipino; Cebuano; Burmese; Shan; Mongolian;
Japanese; Korean; Cantonese; Wu Chinese; Hakka Chinese; Tibetan; Uyghur; Kazakh; Uzbek;
Kyrgyz; Tajik; Turkmen; Tatar; Bashkir; Kurdish (Kurmanji); Kurdish (Sorani); Somali;
Amharic; Oromo; Tigrinya; Hausa; Yoruba; Igbo; Nigerian Pidgin; Swahili; Kinyarwanda;
Kirundi; Luganda; Lingala; Shona; Zulu; Xhosa; Afrikaans; Malagasy; Wolof; Bambara;
Fula; Akan (Twi); Ewe; Berber (Tamazight); Haitian Creole; Jamaican Patois; Papiamento;
Quechua; Aymara; Guarani; Māori; Samoan; Tongan; Fijian; Latin; Esperanto; Sindhi;
Kashmiri; Dogri; Konkani; Maithili; Meitei (Manipuri); Bodo"""


@pytest.fixture
async def people() -> AsyncIterator[dict[str, uuid.UUID]]:
    created = {name: await _make_user(name) for name in ("owner", "admin")}
    yield created
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM workspaces"))
            await session.execute(text("DELETE FROM users"))
            await session.commit()


def _asked() -> list[str]:
    return [name.strip() for name in ASKED.replace("\n", " ").split(";")]


# ── the catalogue ────────────────────────────────────────────────────────────


def test_the_catalogue_is_the_one_asked_for() -> None:
    offered = [language.english for language in languages.catalogue().languages]
    assert len(_asked()) == 140
    assert offered == _asked()


def test_each_language_has_a_tag_a_standard_reads_once() -> None:
    tags = [language.tag for language in languages.catalogue().languages]
    assert len(set(tags)) == 140
    for tag in tags:
        assert languages.canonical(tag) == tag
        assert languages.region_of(tag) is None, f"{tag}: a language, never a region"


def test_the_scripts_that_need_it_are_told_apart() -> None:
    """zh-Hans and zh-Hant are two languages to the picker; Serbian is one."""
    assert languages.language("zh-Hans") is not None
    assert languages.language("zh-Hant") is not None
    assert languages.language("zh") is None


def test_the_right_to_left_languages() -> None:
    rtl = {language.tag for language in languages.catalogue().languages if language.dir == "rtl"}
    # The ones the ticket names, and the others written in Arabic or Hebrew.
    assert {"ar", "fa", "ur", "ps", "ckb"} <= rtl
    assert rtl == {"ar", "arz", "he", "yi", "fa", "prs", "ps", "ur", "ug", "ckb", "sd", "ks"}
    assert languages.direction("kmr") == "ltr", "Kurmanji is written in Latin letters"


def test_every_native_name_is_written_in_its_own_script() -> None:
    """Not a transliteration: Japanese says 日本語, Arabic العربية."""
    by = {language.tag: language.native for language in languages.catalogue().languages}
    assert by["ja"] == "日本語" and by["ko"] == "한국어" and by["hi"] == "हिन्दी"
    assert by["ru"] == "Русский" and by["el"] == "Ελληνικά" and by["he"] == "עברית"
    assert by["ar"].startswith("العربية") and by["th"] == "ไทย" and by["am"] == "አማርኛ"
    for language in languages.catalogue().languages:
        assert language.native == language.native.strip() and language.native


def test_what_is_translated_is_said_and_nothing_more() -> None:
    """French and English everywhere, approved; the site's five other
    languages partly translated — its newest pages are in French and English
    only; the rest translated nowhere."""
    translated = {
        language.tag: dict(language.ui)
        for language in languages.catalogue().languages
        if language.ui
    }
    full = {"app": "reviewed", "site": "reviewed", "emails": "reviewed"}
    assert translated == {
        "en": full,
        "fr": full,
        **{tag: {"site": "partial"} for tag in ("de", "es", "it", "nl", "pt")},
    }


def test_the_web_reads_the_same_catalogue() -> None:
    copy = REPO_ROOT / "web" / "public" / "languages.json"
    assert json.loads(copy.read_text(encoding="utf-8")) == languages.export(), (
        "web/public/languages.json differs from leka/core/languages.yaml: run "
        "`python -m leka.core.languages > ../web/public/languages.json` in api/"
    )


@pytest.mark.parametrize(
    ("change", "refused"),
    [
        (lambda c: c["languages"].append(dict(c["languages"][0])), "twice"),
        (lambda c: c["languages"][0].update(tag="EN"), "canonical"),
        (lambda c: c["languages"][0].update(tag="en-GB"), "region"),
        (lambda c: c["languages"][5].update(dir="ltr"), "not written ltr"),
        (lambda c: c["languages"][6].update(parent="xx"), "parent"),
        (lambda c: c["aliases"].update(fr="en"), "alias"),
        (lambda c: c.update(default="xx"), "default"),
        (lambda c: c["languages"][0]["ui"].pop("emails"), "reviewed on every surface"),
        (lambda c: c["regions"].append("fr"), "regions"),
        (lambda c: c["languages"][1].update(ui={"app": "machine"}), "ui"),
    ],
)
def test_a_broken_catalogue_is_refused(change: Any, refused: str) -> None:
    said = yaml.safe_load(languages.CATALOGUE_FILE.read_text(encoding="utf-8"))
    change(said)
    with pytest.raises(ValidationError, match=refused):
        languages.Catalogue.model_validate(said)


# ── matching what a browser or a person says ─────────────────────────────────


@pytest.mark.parametrize(
    ("said", "offered", "region"),
    [
        ("fr", "fr", None),
        ("fr-CA", "fr", "CA"),
        ("pt-BR", "pt", "BR"),
        ("pt_PT", "pt", "PT"),
        ("en-GB", "en", "GB"),
        ("EN-us", "en", "US"),
        ("zh-CN", "zh-Hans", "CN"),
        ("zh-TW", "zh-Hant", "TW"),
        ("zh-HK", "zh-Hant", "HK"),
        ("zh-Hant-HK", "zh-Hant", "HK"),
        ("zh", "zh-Hans", None),
        ("fa-AF", "prs", "AF"),
        ("fa-IR", "fa", "IR"),
        ("ku-Arab", "ckb", None),
        ("iw", "he", None),
        ("no", "nb", None),
        ("nn-NO", "nn", "NO"),
        ("sr-Latn-RS", "sr", "RS"),
        ("tl", "fil", None),
        ("de-CH-1996", "de", "CH"),
        ("xx", None, None),
        ("not a tag", None, None),
        ("", None, None),
    ],
)
def test_a_tag_as_said_anywhere(said: str, offered: str | None, region: str | None) -> None:
    found = languages.match(said)
    assert (found.tag if found else None) == offered
    assert languages.region_of(said) == region


def test_an_accept_language_header_most_wanted_first() -> None:
    header = "da, en-GB;q=0.8, en;q=0.7, *;q=0.5, fr;q=0, garbage;q=x"
    assert languages.preferences(header) == ["da", "en-GB", "en"]
    assert languages.negotiate(header).tag == "da"  # type: ignore[union-attr]
    # The first one LEKA offers, not the first one said.
    assert languages.negotiate("xx-YY, tlh, pt-BR;q=0.6").tag == "pt"  # type: ignore[union-attr]
    assert languages.negotiate("xx, tlh") is None
    assert languages.negotiate(None) is None
    assert languages.negotiate(["xx", "ja-JP"]).tag == "ja"  # type: ignore[union-attr]


# ── the fallback chain ───────────────────────────────────────────────────────


def test_a_missing_translation_falls_back_along_the_chain() -> None:
    """The language, its parents, its base, the workspace's, then English —
    each once."""
    assert languages.chain("prs", workspace="fr") == ["prs", "fa", "fr", "en"]
    assert languages.chain("yue", workspace="de") == ["yue", "zh-Hant", "de", "en"]
    assert languages.chain("nn") == ["nn", "nb", "en"]
    assert languages.chain("arz", workspace="ar") == ["arz", "ar", "en"]
    assert languages.chain("en", workspace="en") == ["en"]


@pytest.mark.parametrize(
    ("surface", "chosen", "workspace", "shown"),
    [
        ("app", "fr", None, "fr"),
        ("app", "de", "fr", "fr"),  # the application is not in German yet
        ("site", "de", "fr", "de"),  # the site is
        ("app", "ja", None, "en"),
        ("app", "ar", "fr", "fr"),
        ("emails", "prs", None, "en"),
        ("emails", None, "fr", "fr"),
        ("emails", "unknown", "fr", "fr"),
    ],
)
def test_what_a_surface_shows_is_never_empty(
    surface: languages.Surface, chosen: str | None, workspace: str | None, shown: str
) -> None:
    assert languages.shown(surface, chosen, workspace=workspace) == shown


def test_a_language_and_a_region_make_the_formatting_locale() -> None:
    assert languages.locale("pt", "BR") == "pt-BR"
    assert languages.locale("zh-Hant", "HK") == "zh-Hant-HK"
    assert languages.locale("fr") == "fr"


# ── what a person keeps ──────────────────────────────────────────────────────


async def test_a_person_s_language_and_region_follow_them_everywhere(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """Kept on the account: every session, every device, reads it back."""
    await _register_and_verify(client, mailbox, "nora@acme.example")
    me = await _sign_in(client, "nora@acme.example")
    assert (me["user"]["language"], me["user"]["region"]) == ("fr", None)

    changed = await client.patch(f"{AUTH}/me", json={"language": "pt", "region": "br"})
    assert changed.status_code == 200, changed.text
    assert (changed.json()["language"], changed.json()["region"]) == ("pt", "BR")

    # Another device: a session of its own, the same choice.
    client.cookies.clear()
    again = await _sign_in(client, "nora@acme.example")
    assert (again["user"]["language"], again["user"]["region"]) == ("pt", "BR")

    cleared = await client.patch(f"{AUTH}/me", json={"region": None})
    assert (cleared.json()["language"], cleared.json()["region"]) == ("pt", None)


@pytest.mark.parametrize(
    "body",
    [
        {"language": "xx"},
        {"language": "pt-BR"},  # a language and a region are two settings
        {"language": "zh"},  # Simplified or Traditional: said which
        {"region": "ZZ"},
        {"region": "France"},
    ],
)
async def test_what_leka_does_not_offer_is_refused(
    client: AsyncClient, mailbox: CapturingEmailSender, body: dict[str, str]
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")

    refused = await client.patch(f"{AUTH}/me", json=body)

    assert refused.status_code == 422


async def test_registering_keeps_the_language_the_form_was_shown_in(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    from tests.test_auth_api import PASSWORD, PROFILE

    await client.post(
        f"{AUTH}/register",
        json={"email": "nora@acme.example", "password": PASSWORD, **PROFILE, "language": "ja"},
    )
    with system_scope():
        async with session_factory() as session:
            user = await session.scalar(select(User).where(User.email == "nora@acme.example"))
    assert user is not None and user.language == "ja"


# ── what a workspace keeps ───────────────────────────────────────────────────


async def test_a_workspace_speaks_its_creator_s_language_unless_told(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    with system_scope():
        async with session_factory() as session:
            owner = await session.get(User, people["owner"])
            assert owner is not None
            owner.language = "es"
            await session.commit()

    created = await _create_workspace(client, identity, people["owner"], "Acme Corp")
    assert created["default_language"] == "es"

    identity.sign_in(people["owner"])
    told = await client.post(f"{API}/workspaces", json={"name": "Globex", "default_language": "ja"})
    assert told.status_code == 201 and told.json()["default_language"] == "ja"


async def test_nobody_said_means_english(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    created = await _create_workspace(client, identity, people["owner"], "Acme Corp")
    assert created["default_language"] == "en"


async def test_changing_a_workspace_s_language_is_an_admin_s_and_is_kept(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    workspace = await _create_workspace(client, identity, people["owner"], "Acme Corp")

    changed = await client.patch(f"{API}/workspaces/current", json={"default_language": "de"})
    assert changed.status_code == 200 and changed.json()["default_language"] == "de"
    current = (await client.get(f"{API}/workspaces/current")).json()
    assert current["workspace"]["default_language"] == "de"

    refused = await client.patch(f"{API}/workspaces/current", json={"default_language": "xx"})
    assert refused.status_code == 422

    trail = (await client.get(f"{API}/governance/audit")).json()
    said = next(e for e in trail["events"] if e["action"] == "workspace.updated")
    assert said["detail"]["default_language"] == {"before": "en", "after": "de"}

    # A member may not.
    await _seat(uuid.UUID(workspace["id"]), people["admin"], datetime.now(UTC))
    identity.sign_in(people["admin"], uuid.UUID(workspace["id"]))
    denied = await client.patch(f"{API}/workspaces/current", json={"default_language": "fr"})
    assert denied.status_code == 403


# ── what a model is told ─────────────────────────────────────────────────────


async def test_a_model_writes_to_a_person_in_theirs_else_the_workspace_s(
    people: dict[str, uuid.UUID],
) -> None:
    with system_scope():
        async with session_factory() as session:
            workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:6]}")
            session.add(workspace)
            await session.flush()
            assert workspace.default_language == "en"
            workspace.default_language = "fr"
            owner = await session.get(User, people["owner"])
            assert owner is not None
            await session.flush()

            assert await spoken_language(session, people["owner"], workspace.id) == "fr"
            owner.language = "ja"
            await session.flush()
            # Japanese: the screens fall back, the model does not.
            assert await spoken_language(session, people["owner"], workspace.id) == "ja"
            assert await spoken_language(session, None, workspace.id) == "fr"
            assert await workspace_language(session, workspace.id) == "fr"
            assert await spoken_language(session, None, None) == "en"
            await session.rollback()


def test_the_writing_rule_names_the_language_whichever_the_input_s() -> None:
    said = languages.writing_rule("ja")
    assert "Japanese (日本語, ja)" in said
    assert "whatever language the question" in said
    assert "explicitly asks for another language" in said


def test_a_task_tells_the_model_its_language_and_none_without_one() -> None:
    runtime = LLMRuntime.__new__(LLMRuntime)
    told = runtime._messages(Task(purpose="t", instructions="Do.", input="x", language="ar"))
    assert "Modern Standard Arabic (العربية الفصحى, ar)" in told[0].content
    plain = runtime._messages(Task(purpose="t", instructions="Do.", input="x"))
    assert "Write every word" not in plain[0].content


def test_an_agent_answers_in_the_asker_s_language_unless_its_own_rules_say() -> None:
    from tests.test_agent_runtime import ARCHITECT

    told = messages(ARCHITECT, {}, Injected(()), language="de")
    assert "in German (Deutsch, de) — the language of the person who asked" in told[0].content
    assert "unless the agent's instructions below require another" in told[0].content
    assert "in the language of the inputs" in messages(ARCHITECT, {}, Injected(()))[0].content
