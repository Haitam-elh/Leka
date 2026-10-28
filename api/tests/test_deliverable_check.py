"""An agent's deliverable holds what its agent gives, whatever model wrote it
(2026-10-22: « whatever the model, the same deliverable — or better »).

What these protect:
- Pure: the sections an agent's « Ce qu'il produit » lists are read — those
  that say when they apply may be left out; a deliverable in French is read
  by the words of each title, headings worded their own way still count; in
  another language, by how many sections it has.
- An agent's run: a deliverable short of a section is said back to the
  model, with what it lacks — it writes it again, and the whole one is
  delivered; told twice and still short, delivered and said incomplete,
  never shown as whole.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient

from leka.capabilities import runs as runs_module
from leka.capabilities import sync_catalogue
from leka.capabilities.deliverable_check import (
    PLAN,
    SUMMARY,
    expected,
    missing,
    sections,
    unread,
)
from leka.capabilities.registry import catalogue
from leka.capabilities.runtime import FRAME_NOTE, Injected, framed, messages
from leka.core.config import settings
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import (  # noqa: F401
    API,
    Script,
    _detail,
    _kinds,
    _run,
    gemini,
    leka_gemini,
)
from tests.test_capabilities_api import _connect
from tests.test_context_engine import model  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

pytestmark = pytest.mark.integration

FOUND = {d.key: d for d in catalogue()}


def _said(key: str) -> str:
    return FOUND[key].instructions or ""


def test_every_deliverable_opens_on_a_summary_and_ends_on_an_action_plan() -> None:
    """Karim, 2026-10-23: « pas que du texte d'analyse — un résumé et un plan
    d'action concret et exécutable », every agent — but the architect's
    deck, whose order is the deck's."""
    reliability = FOUND["reliability-analysis"]
    own = [s.title for s in sections(reliability.instructions or "")]
    framed_ = [s.title for s in expected(reliability.instructions or "", framed=True)]
    # Its own « Actions » is the plan.
    assert "Actions" in own and "Actions" not in framed_
    assert (framed_[0], framed_[-1]) == (SUMMARY.title, PLAN.title)
    assert framed_[1:-1] == [t for t in own if t != "Actions"]
    # An agent that lists no section is framed all the same.
    assert [s.title for s in expected("", framed=True)] == ["Résumé", "Plan d'action"]
    whole = "\n\n".join(f"## {t}\n\nDit." for t in framed_)
    assert missing(reliability.instructions or "", whole, framed=True) == []
    unframed = "\n\n".join(f"## {t}\n\nDit." for t in own)
    [said] = missing(reliability.instructions or "", unframed, framed=True)
    assert "« Résumé »" in said and "« Plan d'action »" in said
    # Every markdown agent is told so; the deck is not.
    assert framed(reliability) and not framed(FOUND["application-architecture"])
    told = messages(reliability, {}, _nothing())[0].content
    assert FRAME_NOTE in str(told)
    assert FRAME_NOTE not in str(
        messages(FOUND["application-architecture"], {}, _nothing())[0].content
    )


def _nothing() -> Injected:
    return Injected(elements=())


def test_the_sections_an_agent_gives_are_read_and_those_that_say_when_may_be_left_out() -> None:
    qa = sections(_said("qa-acceptance"))
    assert [s.title for s in qa][:3] == ["Verdict", "Ce qui était attendu", "Critère par critère"]
    assert not any(s.optional for s in qa)
    design = {s.title: s.optional for s in sections(_said("design-review"))}
    # « dès que la demande est de proposer », « quand des données réelles… »,
    # « pour une application web » — the rest expected.
    assert design["La proposition"] and design["Le pire des cas"] and design["Sur téléphone"]
    assert not design["Le verdict"] and not design["Constats"]
    assert sections(_said("application-architecture")) == []


def test_a_french_deliverable_is_read_by_its_titles_worded_its_own_way() -> None:
    instructions = _said("test-analysis")
    whole = (
        "## Périmètre\nx\n## Par ricochet\nx\n**Zones à risque**\nx\n"
        "### 4. Plan de test\nx\n## Limites\nx"
    )
    assert missing(instructions, whole) == []
    [said] = missing(instructions, "## Périmètre\nx\n## Limites\nx")
    assert "« Par ricochet »" in said and "« Zones à risque »" in said
    assert "« Périmètre »" not in said


def test_another_language_is_read_by_how_many_sections_it_has() -> None:
    instructions = _said("test-analysis")
    english = "## Scope\nx\n## Knock-on\nx\n## Risky areas\nx"
    assert missing(instructions, english, language="en") == []
    [said] = missing(instructions, "Just a paragraph.", language="en")
    assert "0 of the 5 sections" in said


async def test_a_deliverable_short_of_a_section_is_written_again_then_said_incomplete(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runs_module, "settings", settings.model_copy(update={"agent_corrections": 2})
    )
    await sync_catalogue()
    await _connect(acme, "github")
    _as(identity, acme, "member")
    short = "## Périmètre\nLe paiement.\n## Limites\nAucune."
    whole = (
        "## Périmètre\nLe paiement.\n## Par ricochet\ncheckout.\n## Zones à risque\n"
        "Aucune connue.\n## Plan de test proposé\n1. Payer.\n## Limites\nAucune."
    )
    script = leka_gemini(gemini(short), gemini(whole))

    async def started() -> dict[str, Any]:
        response = await client.post(
            API, json={"key": "test-analysis", "inputs": {"sujet": "checkout"}}
        )
        assert response.status_code == 202, response.text
        found: dict[str, Any] = response.json()
        return found

    first = await started()
    assert await _run(acme, first["id"]) == {"status": "succeeded"}
    done = await _detail(client, first["id"])
    # Told what it lacked, it wrote it again: the whole one delivered.
    assert done["output"] == whole
    told = script.asked[1]["contents"][-1]["parts"][0]["text"]
    assert "Par ricochet" in told and "Write the whole deliverable again" in told
    assert "incomplete" not in _kinds(done)

    # Told twice and still short: delivered, said incomplete.
    leka_gemini(gemini(short), gemini(short), gemini(short))
    second = await started()
    assert await _run(acme, second["id"]) == {"status": "succeeded"}
    done = await _detail(client, second["id"])
    assert done["output"] == short
    [incomplete] = [e for e in done["events"] if e["kind"] == "incomplete"]
    assert "Zones à risque" in incomplete["detail"]["said"]


def test_a_line_cited_is_a_line_read() -> None:
    """2026-10-23: the API review cited `intentions.py:250` of a file of 121
    lines, and `errors.py:100` it never read."""
    read = {"acme/api:api/app/intentions.py": "x\n" * 120, "acme/api:api/app/main.py": "y\n" * 300}
    said = (
        "Où : `api/app/intentions.py:250`, `main.py:103`, `api/app/errors.py:100`, "
        "l'hôte db.x.supabase.co:5432, [schema-health:4021], `intentions.py:12`"
    )
    [told] = unread(said, read)
    assert "api/app/intentions.py:250 (it has 121 lines)" in told
    assert "api/app/errors.py:100 (never read)" in told
    assert "main.py:103" not in told and "supabase" not in told and "schema-health" not in told
    assert unread("`main.py:103`, `api/app/intentions.py:12-14`", read) == []


def test_an_agent_that_reads_code_reads_it_and_names_only_what_it_saw() -> None:
    # 2026-10-28: Mistral, asked how acme/frontend is organised, read no file
    # and described `app/main.py`, `requirements.txt` — none of them there.
    from leka.capabilities.deliverable_check import invented

    said = "Le point d'entrée est `app/main.py`, les dépendances `requirements.txt`."
    [nothing] = invented(said, {}, {}, {}, reads_code=True)
    assert nothing.startswith("No file of the repository was read")
    # An agent that may answer from elsewhere (a document) need not read code
    # — but names no file it never saw (2026-10-28: a performance analysis
    # described `app/routes/payments.py`, read by no one).
    [named] = invented(said, {}, {}, {}, reads_code=False)
    assert "app/main.py, requirements.txt." in named
    assert invented("Le service est lent depuis hier.", {}, {}, {}, reads_code=False) == []
    files = {"acme/web:src/app/page.tsx": "x"}
    listed = {"acme/web": ["src/app/page.tsx", "package.json", "src/lib/api.ts"]}
    pulls = {"acme/web#7": {"files": [{"path": "src/lib/new.ts"}]}}
    fine = "Lire `src/app/page.tsx:3`, `package.json`, `lib/api.ts` et `src/lib/new.ts`."
    assert invented(fine, files, listed, pulls, reads_code=True) == []
    [unseen] = invented(said + fine, files, listed, pulls, reads_code=True)
    assert "app/main.py, requirements.txt." in unseen


def test_a_model_caught_in_a_loop_is_told_so() -> None:
    # 2026-10-28: « Je vais lister les fichiers dans `public`. », ten times,
    # delivered as the deliverable.
    from leka.capabilities.deliverable_check import repeats

    looped = "Le fichier est trop long. " + "Je vais lister les fichiers dans `public`. " * 6
    [said] = repeats(looped)
    assert "Je vais lister les fichiers dans `public`." in said
    assert repeats("## Résumé\n\nUne phrase.\n\n## Risques\n\nAucun risque connu ici.") == []


def test_an_agent_asked_about_one_repository_reads_that_one() -> None:
    # 2026-10-28: asked how acme/frontend is organised, Mistral read and
    # described acme/backend.
    from leka.capabilities.deliverable_check import elsewhere

    read = {"acme/backend:leka/api/intentions.py": "x"}
    [said] = elsewhere("Explique le code de acme/frontend", read, {})
    assert said.startswith("You were asked about acme/frontend and read acme/backend")
    assert elsewhere("Explique le code de acme/frontend", read, {"acme/frontend": ["a.ts"]}) == []
    # A path is no repository; nothing read, nothing said.
    assert elsewhere("Corrige components/overview dans le dépôt", read, {}) == []
    assert elsewhere("Explique acme/frontend", {}, {}) == []


def test_a_deliverable_says_no_em_dash_outside_its_code() -> None:
    # 2026-10-28: Mistral writes « — » whatever it is told; a person reads
    # it as a machine's. Its code is left as it is.
    from leka.capabilities.runtime import output_of

    said = (
        "# Architecture — Billing API\n\nSert Checkout — et Ledger.\n```py\nx = 1  # a — b\n```\n"
    )
    assert output_of(said, "markdown") == (
        "# Architecture : Billing API\n\nSert Checkout : et Ledger.\n```py\nx = 1  # a — b\n```"
    )
