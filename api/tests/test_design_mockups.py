"""The designer's simulator: the screen it proposes, drawn before and after
(`renders: design_mockups`).

What these protect:
- A mock-up runs nothing and reaches nothing: no script, frame or embedded
  object, no event handler, no link out, no fetched source, no @import —
  data: images kept; its page opens with a Content-Security-Policy that
  allows inline styles and data: only.
- A proposal holds one to three proposals; the one recommended is one of
  them.
- A review that proposes no design draws nothing, and no model is asked.
- An image the code shows from the repository — its logo — is never
  redrawn by hand: the mock-up names it (<img data-asset>), LEKA puts its
  real bytes there, read from the repository (2026-10-19: « il fait des
  erreurs comme le logo »).
- One mock-up is corrected as a person asks, the rest as it was — the
  correction kept in the run's history (2026-10-19: « lui demander de
  corriger certaines parties de l'écran depuis la proposition »).
- A design not drawn is said: which step, and what its model said — and is
  drawn again on asking, from the review it delivered, never the run done
  again; once drawn, not again.
- A review proposes a design by LEKA's mark — or, the mark left out, by its
  section « La proposition » (2026-10-18: a whole proposal drew nothing).
- End to end: the designer reads the code, its review opens « La
  proposition » with LEKA's mark; LEKA asks the model again, no tools, one
  mock-up at a time — its plan without HTML, the screen today, then each
  direction from today's mock-up, at once (2026-10-18: asked all at once,
  the answer outgrew its tokens and the review came alone) — from the
  review and the files the run read, cleans them and keeps them; the run says it drew; its report
  has no mark; GET /agent-runs/{id}/design gives each mock-up as its page,
  to whoever may read the run — another workspace sees nothing.
- « Implémenter le design » (2026-10-24: it changed four classes and left
  the rest « for a later step »): the code change asked from a design
  review's deliverable is given that review's recommended direction — its
  mock-up, its changes, the screen today — as it works and as its change is
  written; an analysis that puts part of it off is asked again; a deferral
  is told apart from an ordinary sentence.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from leka.api import agent_runs as agent_runs_api
from leka.capabilities import correct_design_run, execute_run, redraw_design, sync_catalogue
from leka.capabilities import runs as runs_module
from leka.capabilities.deliverable_check import deferred
from leka.capabilities.deliverables.design import (
    BASE,
    POLICY,
    DesignDirection,
    DesignMockup,
    DesignProposal,
    MockupDrawing,
    asset_paths,
    candidates,
    clean_body,
    clean_css,
    cleaned,
    corrected,
    page,
    unchanged,
    unstyled,
    with_assets,
    without_assets,
)
from leka.capabilities.mockups import MARK, proposes, read_files, without_mark
from leka.core.config import settings
from leka.platform import LocalObjectStore
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import Script, gemini, leka_gemini, queued, store  # noqa: F401
from tests.test_code_changes_api import README, REPO, GitHub, _github_source, github  # noqa: F401
from tests.test_context_engine import model  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

RUNS = "/api/v1/agent-runs"


def _mockup(
    name: str, body: str = "<main><h1>Accueil</h1></main>", css: str = ""
) -> dict[str, str]:
    return {
        "name": name,
        "axis": f"L'axe de {name}",
        "when": "…",
        "cost": "…",
        "css": css,
        "body": body,
    }


def _proposal(**over: Any) -> dict[str, Any]:
    return {
        "screen": "Accueil",
        "viewport": "desktop",
        "before": _mockup("Aujourd'hui", css="h1 { font-size: 20px; }"),
        "after": [
            _mockup(
                "Calme",
                body='<main><h1>Accueil</h1><button onclick="steal()">Lancer</button>'
                '<script>fetch("https://evil.example")</script></main>',
                css="@import url('https://evil.example/x.css');"
                " button:active { transform: scale(0.97); }",
            ),
            _mockup("Dense"),
        ],
        "recommended": 0,
        "why": "Un outil de tous les jours : sobre.",
        "changes": [
            {"where": "web/app/page.tsx:12", "before": "3 boutons", "after": "1 action", "why": "…"}
        ],
        **over,
    }


# ── a mock-up runs nothing, reaches nothing ─────────────────────────────────


def test_a_body_runs_nothing_and_reaches_nothing() -> None:
    dirty = (
        '<html><head><title>x</title><base href="https://evil.example/"></head><body>'
        '<script src="https://evil.example/a.js"></script><script>alert(1)</script>'
        '<iframe src="https://evil.example"></iframe><object data="x.swf"></object>'
        '<a href="https://evil.example" onclick="go()">Lien</a>'
        '<img src="https://evil.example/p.png" onerror="x()"><img src="data:image/png;base64,AAAA">'
        '<div style="background: url(https://evil.example/bg.png)">'
        '<a href="javascript:alert(1)">js</a><a href="#top">haut</a></div>'
        '<meta http-equiv="refresh" content="0;url=https://evil.example"></body></html>'
    )
    said = clean_body(dirty)
    for gone in (
        "<script",
        "<iframe",
        "<object",
        "<base",
        "<meta",
        "onclick",
        "onerror",
        "evil.example",
        "javascript:",
        "<html",
        "<body",
        "<title",
    ):
        assert gone not in said, gone
    assert '<img src="data:image/png;base64,AAAA">' in said
    # Every link leads nowhere: the page is a picture of a screen.
    assert said.count('href="#"') == 3
    assert "Lien" in said and "haut" in said


def test_a_style_sheet_fetches_nothing_and_stays_one() -> None:
    said = clean_css(
        "@import url('https://evil.example/x.css');\n"
        '.a { background: url("https://evil.example/b.png"); }\n'
        ".b { background: url(data:image/png;base64,AAAA); }\n"
        "</style><script>alert(1)</script>"
    )
    assert "@import" not in said and "evil.example" not in said
    assert "url(data:image/png;base64,AAAA)" in said
    assert "</style" not in said.lower()


def test_a_page_opens_with_its_policy_and_holds_what_it_shows() -> None:
    shown = page(
        DesignMockup(name="Calme <b>", css="h1 { color: #1e1b4b; }", body="<h1>Accueil</h1>")
    )
    assert shown.startswith("<!doctype html>")
    head = shown.split("<style>")[0]
    assert f'content="{POLICY}"' in head and "default-src 'none'" in POLICY
    assert "<title>Calme &lt;b&gt;</title>" in head
    assert "h1 { color: #1e1b4b; }" in shown and "<body><h1>Accueil</h1></body>" in shown


def test_a_proposal_holds_one_to_three_proposals_and_recommends_one_of_them() -> None:
    proposal = cleaned(DesignProposal.model_validate(_proposal(recommended=7)))
    assert proposal.recommended == 1
    assert "<script" not in proposal.after[0].body and "onclick" not in proposal.after[0].body
    assert "@import" not in proposal.after[0].css
    with pytest.raises(ValidationError):
        DesignProposal.model_validate(_proposal(after=[]))
    with pytest.raises(ValidationError):
        DesignProposal.model_validate(_proposal(after=[_mockup(str(i)) for i in range(4)]))


def test_only_a_review_with_the_mark_is_drawn_and_the_mark_is_not_read() -> None:
    review = f"# Revue\n\n## La proposition\n\n{MARK}\n\nL'écran aujourd'hui…"
    assert proposes(review) and not proposes("# Revue\n\nAucun constat.")
    # The mark left out, its section said: still drawn.
    assert proposes("Ce qui a été relu\n\nLa proposition\n1. L'écran aujourd'hui")
    assert proposes("## 2. Les directions de design\n\n| # | Direction |")
    assert not proposes("Les constats ne proposent rien ; la proposition de la PR tient.")
    assert MARK not in without_mark(review) and "La proposition" in without_mark(review)


def test_an_image_from_the_repository_is_its_own_bytes_never_redrawn() -> None:
    body = '<header><img alt="LEKA" data-asset="/brand/logo.svg" src="x.png"> Menu</header>'
    proposal = DesignProposal.model_validate(
        _proposal(before=_mockup("Aujourd'hui", body=body), after=[_mockup("Calme", body=body)])
    )
    assert asset_paths(proposal) == ["/brand/logo.svg"]
    assert candidates("/brand/logo.svg?v=2")[:2] == ["brand/logo.svg", "public/brand/logo.svg"]
    uri = "data:image/svg+xml;base64,PHN2Zy8+"
    put = with_assets(proposal, {"/brand/logo.svg": uri})
    assert f'src="{uri}"' in put.after[0].body and "x.png" not in put.after[0].body
    assert 'data-asset="/brand/logo.svg"' in put.before.body
    # Shown as its page: the image kept, policy allowing data: only.
    assert f'src="{uri}"' in page(put.after[0])
    # Given back to the model, its bytes left out, its path kept.
    bare = without_assets(put.before.body)
    assert 'data-asset="/brand/logo.svg"' in bare and "data:image" not in bare
    # One mock-up drawn again, the others as they were.
    again = corrected(put, "0", MockupDrawing(css="", body="<main>Corrigé</main>"))
    assert again.after[0].body == "<main>Corrigé</main>" and again.before == put.before


def test_the_writer_is_given_the_files_read_within_its_budget() -> None:
    given = read_files({"a.css": "a" * 50_000, "b.tsx": "b" * 200_000, "c.tsx": "c"})
    assert len(given["a.css"]) == 40_000
    assert len(given["b.tsx"]) == 40_000
    assert sum(len(t) for t in given.values()) <= 160_000


# ── end to end ─────────────────────────────────────────────────────────────


def _plan(*names: str) -> dict[str, Any]:
    return {
        "screen": "Accueil",
        "viewport": "desktop",
        "directions": [
            {"name": n, "axis": f"L'axe de {n}", "when": "…", "cost": "…", "changes": "…"}
            for n in names
        ],
        "recommended": 0,
        "why": "Un outil de tous les jours : sobre.",
        "changes": [
            {"where": "web/app/page.tsx:12", "before": "3 boutons", "after": "1 action", "why": "…"}
        ],
    }


TODAY_DRAWN = {
    "css": "h1 { font-size: 20px; }",
    "body": '<main><img data-asset="/brand/logo.svg" alt="LEKA"><h1>Accueil</h1></main>',
}
LOGO = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h10v10z"/></svg>'
# Drawn for each direction, whichever answers first: scripts and handlers
# in it are cleaned away.
DRAWN = {
    "css": "@import url('https://evil.example/x.css'); button:active { transform: scale(0.97); }",
    "body": '<main><h1>Accueil</h1><button onclick="steal()">Lancer</button>'
    '<script>fetch("https://evil.example")</script></main>',
}

REVIEW = (
    "# Revue de design\n\n## Ce qui a été relu\n\n`README.md`.\n\n## La proposition\n\n"
    f"{MARK}\n\nL'écran aujourd'hui : un titre « Payments ». Deux propositions : Calme, Dense. "
    "Je recommande Calme.\n\n## Constats\n\nAucun constat."
)


@pytest.mark.integration
async def test_the_designer_draws_the_screen_before_and_after(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    github: GitHub,
    store: LocalObjectStore,
) -> None:
    _as(identity, acme, "member")
    await _github_source(acme["acme"])
    await sync_catalogue()
    # The logo the code shows, in the app's public folder.
    github.extra["public/brand/logo.svg"] = LOGO
    script = leka_gemini(
        gemini(call={"name": "read_file", "args": {"repository": REPO, "path": "README.md"}}),
        gemini(REVIEW),
        gemini(json.dumps(_plan("Calme", "Dense"))),
        gemini(json.dumps(TODAY_DRAWN)),
        gemini(json.dumps(DRAWN)),
        gemini(json.dumps(DRAWN)),
    )
    started = await client.post(
        RUNS,
        json={"key": "design-review", "inputs": {"depot": REPO, "demande": "propose un design"}},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}

    # Asked again, structured, no tools: the review and the files it read —
    # the plan first, then today, then each direction from today's mock-up.
    asked = script.asked[2]
    assert asked["generationConfig"]["responseMimeType"] == "application/json"
    assert "tools" not in asked
    material = json.loads(asked["contents"][-1]["parts"][0]["text"])
    assert material["files"] == {f"{REPO}:README.md": README}
    assert MARK not in material["review"]
    assert len(script.asked) == 6
    directions = [json.loads(a["contents"][-1]["parts"][0]["text"]) for a in script.asked[4:]]
    assert {d["direction"]["name"] for d in directions} == {"Calme", "Dense"}
    assert all(d["today"] == TODAY_DRAWN for d in directions)
    # Each with room to think and draw.
    assert script.asked[3]["generationConfig"]["maxOutputTokens"] == 48_000

    detail = (await client.get(f"{RUNS}/{run_id}")).json()
    assert detail["design"] == {
        "screen": "Accueil",
        "viewport": "desktop",
        "proposals": ["Calme", "Dense"],
        "recommended": 0,
    }
    assert MARK not in detail["report"] and "La proposition" in detail["report"]
    assert [e["kind"] for e in detail["events"]][-2:] == ["designed", "succeeded"]

    design = (await client.get(f"{RUNS}/{run_id}/design")).json()
    assert (design["screen"], design["recommended"], design["why"]) == (
        "Accueil",
        0,
        "Un outil de tous les jours : sobre.",
    )
    assert [m["name"] for m in design["after"]] == ["Calme", "Dense"]
    calm = design["after"][0]["page"]
    assert "default-src 'none'" in calm and "transform: scale(0.97)" in calm
    for gone in ("<script", "onclick", "evil.example", "@import"):
        assert gone not in calm, gone
    assert design["before"]["page"].count("<h1>Accueil</h1>") == 1
    # Its real logo, from the repository — never redrawn by hand.
    assert 'src="data:image/svg+xml;base64,' in design["before"]["page"]
    assert design["changes"][0]["where"] == "web/app/page.tsx:12"

    # Another workspace sees nothing.
    _as(identity, acme, "other_admin")
    assert (await client.get(f"{RUNS}/{run_id}/design")).status_code == 404


@pytest.mark.integration
async def test_a_review_without_a_proposal_draws_nothing(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    github: GitHub,
    store: LocalObjectStore,
) -> None:
    _as(identity, acme, "member")
    await _github_source(acme["acme"])
    await sync_catalogue()
    script = leka_gemini(gemini("# Revue des animations\n\nAucun constat."))
    started = await client.post(RUNS, json={"key": "design-review", "inputs": {"depot": REPO}})
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}
    assert len(script.asked) == 1
    detail = (await client.get(f"{RUNS}/{run_id}")).json()
    assert (detail["design"], detail["drawable"]) == (None, [])
    assert (await client.get(f"{RUNS}/{run_id}/design")).status_code == 404


@pytest.mark.integration
async def test_a_design_not_drawn_says_which_step_and_why(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    github: GitHub,
    store: LocalObjectStore,
) -> None:
    _as(identity, acme, "member")
    await _github_source(acme["acme"])
    await sync_catalogue()
    cut = gemini('{"css": "h1 {", "body": "<main>')
    cut["candidates"][0]["finishReason"] = "MAX_TOKENS"
    leka_gemini(gemini(REVIEW), gemini(json.dumps(_plan("Calme"))), cut, cut)
    started = await client.post(
        RUNS,
        json={"key": "design-review", "inputs": {"depot": REPO, "demande": "propose un design"}},
    )
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}
    detail = (await client.get(f"{RUNS}/{run_id}")).json()
    assert detail["design"] is None
    assert detail["draw_failed"] == "unanswered"
    assert detail["draw_said"].startswith("aujourd'hui : Cut at its limit")
    # Its review proposes a design it does not have: drawable, on asking.
    assert "design" in detail["drawable"]


@pytest.mark.integration
async def test_a_design_not_drawn_is_drawn_again_on_asking(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    github: GitHub,
    store: LocalObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _as(identity, acme, "member")
    await _github_source(acme["acme"])
    await sync_catalogue()
    asked: list[tuple[uuid.UUID, str]] = []

    async def queue(workspace_id: uuid.UUID, run_id: uuid.UUID, renders: str) -> bool:
        asked.append((run_id, renders))
        return True

    monkeypatch.setattr(agent_runs_api, "queue_redraw", queue)
    cut = gemini('{"screen": "Acc')
    cut["candidates"][0]["finishReason"] = "MAX_TOKENS"
    leka_gemini(
        gemini(REVIEW),
        cut,
        cut,
        # Drawn again: the plan, today, its one direction.
        gemini(json.dumps(_plan("Calme"))),
        gemini(json.dumps(TODAY_DRAWN)),
        gemini(json.dumps(DRAWN)),
    )
    started = await client.post(
        RUNS,
        json={"key": "design-review", "inputs": {"depot": REPO, "demande": "propose un design"}},
    )
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}
    failed = (await client.get(f"{RUNS}/{run_id}")).json()
    assert (failed["design"], failed["draw_failed"]) == (None, "unanswered")
    assert failed["draw_said"].startswith("plan : Cut at its limit")

    again = await client.post(f"{RUNS}/{run_id}/design")
    assert again.status_code == 202, again.text
    assert (again.json()["drawing"], again.json()["draw_failed"]) == (["design"], None)
    assert asked == [(uuid.UUID(run_id), "design_mockups")]
    assert (await client.post(f"{RUNS}/{run_id}/design")).status_code == 409
    done = await redraw_design(acme["acme"], uuid.UUID(run_id))
    assert done["error"] is None
    drawn = (await client.get(f"{RUNS}/{run_id}")).json()
    assert drawn["design"]["proposals"] == ["Calme"] and drawn["drawing"] == []
    assert (await client.get(f"{RUNS}/{run_id}/design")).status_code == 200
    # Drawn: never again.
    assert (await client.post(f"{RUNS}/{run_id}/design")).status_code == 409


@pytest.mark.integration
async def test_one_mock_up_is_corrected_as_asked_the_rest_as_it_was(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    github: GitHub,
    store: LocalObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _as(identity, acme, "member")
    await _github_source(acme["acme"])
    await sync_catalogue()
    github.extra["public/brand/logo.svg"] = LOGO
    asked: list[tuple[str, str]] = []

    async def queue(workspace_id: uuid.UUID, run_id: uuid.UUID, target: str, note: str) -> bool:
        asked.append((target, note))
        return True

    monkeypatch.setattr(agent_runs_api, "queue_correction", queue)
    script = leka_gemini(
        gemini(REVIEW),
        gemini(json.dumps(_plan("Calme"))),
        gemini(json.dumps(TODAY_DRAWN)),
        gemini(json.dumps(DRAWN)),
        # Corrected: its logo, as asked.
        gemini(
            json.dumps(
                {
                    "css": "",
                    "body": '<main><img data-asset="/brand/logo.svg" alt="LEKA">Corrigé</main>',
                }
            )
        ),
    )
    started = await client.post(
        RUNS,
        json={"key": "design-review", "inputs": {"depot": REPO, "demande": "propose un design"}},
    )
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}
    first = (await client.get(f"{RUNS}/{run_id}/design")).json()

    url = f"{RUNS}/{run_id}/design/corrections"
    assert (await client.post(url, json={"target": "4", "note": "le logo"})).status_code == 422
    sent = await client.post(
        url, json={"target": "0", "note": "Le logo est faux : utilise le vrai."}
    )
    assert sent.status_code == 202, sent.text
    assert sent.json()["correcting"] == "0"
    assert asked == [("0", "Le logo est faux : utilise le vrai.")]
    assert (await client.post(url, json={"target": "before", "note": "encore"})).status_code == 409
    done = await correct_design_run(acme["acme"], uuid.UUID(run_id), "0", asked[0][1])
    assert done == {"corrected": True, "error": None}

    # The mock-up given back to the model: the correction, without its bytes.
    material = json.loads(script.asked[-1]["contents"][-1]["parts"][0]["text"])
    assert material["correction"] == "Le logo est faux : utilise le vrai."
    assert "data:image" not in material["mockup"]["body"] and "today" in material
    design = (await client.get(f"{RUNS}/{run_id}/design")).json()
    assert "Corrigé" in design["after"][0]["page"]
    assert 'src="data:image/svg+xml;base64,' in design["after"][0]["page"]
    assert design["before"]["page"] == first["before"]["page"]
    run = (await client.get(f"{RUNS}/{run_id}")).json()
    assert (run["correcting"], run["correction_failed"]) == (None, None)
    assert [(c["target"], c["note"]) for c in run["corrections"]] == [
        ("0", "Le logo est faux : utilise le vrai.")
    ]


def test_a_mock_up_drawn_bare_is_said_so_and_every_page_has_a_base() -> None:
    """2026-10-21: a model wrote its classes — Tailwind's — and no rule for
    them; the screen showed as bare HTML. Told why, it draws again; and every
    page has a base style first, never a browser's default."""
    rows = "".join(
        f'<div class="flex gap-2 rounded-lg p-4"><span class="text-sm">Ligne {n}</span></div>'
        for n in range(20)
    )
    [bare] = unstyled(MockupDrawing(css="", body=f"<main>{rows}</main>"))
    assert "css is empty" in bare
    [classes] = unstyled(
        MockupDrawing(css="main { padding: 24px; }" * 10, body=f"<main>{rows}</main>")
    )
    assert "have no rule in css" in classes and "flex" in classes
    styled = ".row{display:flex;gap:8px;border-radius:8px;padding:16px}.label{font-size:13px}" * 3
    drawn = rows.replace('class="flex gap-2 rounded-lg p-4"', 'class="row"').replace(
        'class="text-sm"', 'class="label"'
    )
    assert unstyled(MockupDrawing(css=styled, body=f"<main>{drawn}</main>")) == []
    # A short screen, or one styled inline, is never refused.
    assert unstyled(MockupDrawing(css="", body="<main><h1>Accueil</h1></main>")) == []
    inline = "".join(f'<p style="margin:{n}px">x</p>' for n in range(60))
    assert unstyled(MockupDrawing(css="", body=inline)) == []
    shown = page(DesignMockup(name="Calme", css="", body="<main>x</main>"))
    assert shown.index(BASE) < shown.index("<body>")


def test_a_direction_drawn_as_today_is_said_so_with_what_it_changes() -> None:
    """2026-10-22: asked a new design, a proposal came back the screen as it
    is. Told so — with what its direction changes — it draws again."""
    rows = "".join(f'<li class="row"><span class="name">Agent {n}</span></li>' for n in range(30))
    css = ".row{display:flex;gap:8px;padding:12px}.name{font-weight:600}" * 4
    today = MockupDrawing(css=css, body=f"<main><h1>Mon environnement</h1><ul>{rows}</ul></main>")
    direction = DesignDirection(
        name="Un seul système",
        axis="La hiérarchie",
        changes="Le score passe en tête, en grand ; les cartes en grille de trois.",
    )
    [said] = unchanged(today, today.model_copy(), direction)
    assert "drawn the same as today's screen" in said
    assert "Un seul système" in said and "Le score passe en tête" in said
    redrawn = MockupDrawing(
        css=css + ".score{font-size:48px}.grid{display:grid;grid-template-columns:repeat(3,1fr)}",
        body='<main><p class="score">67 %</p><h1>Mon environnement</h1>'
        f'<div class="grid">{rows.replace("li", "div")}</div></main>',
    )
    assert unchanged(today, redrawn, direction) == []


# ── « Implémenter le design »: the mock-up, implemented whole (2026-10-24) ──


def test_a_design_put_off_is_told_apart_from_an_ordinary_sentence() -> None:
    for said in (
        "Le bandeau unifié est réservé pour une étape suivante.",
        "La grille sera reprise dans un second temps.",
        "Phase 1 : la typographie ; le reste dans une prochaine pull request.",
        "The layout is left for a follow-up step.",
    ):
        assert deferred(said), said
    for said in (
        "Le bouton suivant ouvre la page.",
        "Étape 2 : lancer les tests.",
        "Ce qui n'est pas fait ici : la donnée « tendance » n'existe pas dans l'API.",
    ):
        assert deferred(said) == [], said


async def test_the_code_change_implements_the_design_it_comes_from_whole(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    github: GitHub,
    store: LocalObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _as(identity, acme, "member")
    await _github_source(acme["acme"])
    await sync_catalogue()
    github.extra["public/brand/logo.svg"] = LOGO
    leka_gemini(
        gemini(call={"name": "read_file", "args": {"repository": REPO, "path": "README.md"}}),
        gemini(REVIEW),
        gemini(json.dumps(_plan("Calme", "Dense"))),
        gemini(json.dumps(TODAY_DRAWN)),
        gemini(json.dumps(DRAWN)),
        gemini(json.dumps(DRAWN)),
    )
    review = await client.post(
        RUNS,
        json={"key": "design-review", "inputs": {"depot": REPO, "demande": "propose un design"}},
    )
    review_id = review.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(review_id)) == {"status": "succeeded"}
    assert (await client.get(f"{RUNS}/{review_id}")).json()["design"]["proposals"] == [
        "Calme",
        "Dense",
    ]

    # « Implémenter le design », from the review's deliverable — told when
    # it puts part of it off.
    monkeypatch.setattr(
        runs_module, "settings", settings.model_copy(update={"agent_corrections": 1})
    )
    halves = (
        "## Résumé\nLa typographie d'abord.\n## Le problème\nx\n## La modification\n"
        "Le titre seulement ; le reste est réservé pour une étape suivante.\n## Les risques\nx\n"
        "## Comment tester\nx\n## Ce qui n'est pas fait ici\nx\n## Plan d'action\n1. x"
    )
    whole = halves.replace(
        "Le titre seulement ; le reste est réservé pour une étape suivante.",
        "Tout l'écran de la direction Calme : le titre et l'action unique.",
    )
    change = {
        "repository": REPO,
        "title": "Appliquer la direction Calme",
        "summary": "L'accueil comme la maquette Calme [0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41].",
        "files": [
            {
                "path": "README.md",
                "edits": [{"find": "# Payments\n", "replace": "# Payments — Calme\n"}],
            }
        ],
    }
    script = leka_gemini(
        gemini(call={"name": "read_file", "args": {"repository": REPO, "path": "README.md"}}),
        gemini(halves),
        gemini(whole),
        gemini(json.dumps(change)),
    )
    started = await client.post(
        RUNS,
        json={
            "key": "code-change",
            "inputs": {
                "demande": "Implémente dans le code la direction retenue de cette revue de design.",
                "depot": REPO,
                "livrable": review_id,
            },
        },
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}

    # It works from the mock-up of the recommended direction — never the
    # review's words alone.
    material = json.loads(script.asked[0]["contents"][0]["parts"][0]["text"])
    target = material["inputs"]["maquette"]
    assert (target["screen"], target["direction"]) == ("Accueil", "Calme")
    assert "<h1>Accueil</h1>" in target["mockup"]["html"]
    assert "transform: scale(0.97)" in target["mockup"]["css"]
    assert "<script" not in target["mockup"]["html"] and "data:image" not in target["today"]["html"]
    assert target["changes"][0]["where"]
    # Part of it put off: asked again, told to do it all.
    told = json.dumps(script.asked[2], ensure_ascii=False)
    assert "Part of the design to implement is put off" in told
    detail = (await client.get(f"{RUNS}/{run_id}")).json()
    assert detail["output"] == whole
    assert any(e["kind"] == "design_target" for e in detail["events"])
    # Its change is written from the mock-up too.
    writer = json.loads(script.asked[3]["contents"][-1]["parts"][0]["text"])
    assert writer["inputs"]["maquette"]["direction"] == "Calme"
    [proposed] = (await client.get("/api/v1/code-changes", params={"run_id": run_id})).json()
    assert proposed["files"][0]["path"] == "README.md"
