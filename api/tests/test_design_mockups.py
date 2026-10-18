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
- End to end: the designer reads the code, its review opens « La
  proposition » with LEKA's mark; LEKA asks the model again, no tools, for
  the screen today and its proposals — from the review and the files the
  run read —, cleans them and keeps them; the run says it drew; its report
  has no mark; GET /agent-runs/{id}/design gives each mock-up as its page,
  to whoever may read the run — another workspace sees nothing.
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

from leka.capabilities import execute_run, sync_catalogue
from leka.capabilities.deliverables.design import (
    POLICY,
    DesignMockup,
    DesignProposal,
    clean_body,
    clean_css,
    cleaned,
    page,
)
from leka.capabilities.mockups import MARK, proposes, read_files, without_mark
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
    assert MARK not in without_mark(review) and "La proposition" in without_mark(review)


def test_the_writer_is_given_the_files_read_within_its_budget() -> None:
    given = read_files({"a.css": "a" * 50_000, "b.tsx": "b" * 200_000, "c.tsx": "c"})
    assert len(given["a.css"]) == 40_000
    assert len(given["b.tsx"]) == 40_000
    assert sum(len(t) for t in given.values()) <= 160_000


# ── end to end ─────────────────────────────────────────────────────────────

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
    script = leka_gemini(
        gemini(call={"name": "read_file", "args": {"repository": REPO, "path": "README.md"}}),
        gemini(REVIEW),
        gemini(json.dumps(_proposal())),
    )
    started = await client.post(
        RUNS,
        json={"key": "design-review", "inputs": {"depot": REPO, "demande": "propose un design"}},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}

    # Asked again, structured, no tools: the review and the files it read.
    asked = script.asked[2]
    assert asked["generationConfig"]["responseMimeType"] == "application/json"
    assert "tools" not in asked
    material = json.loads(asked["contents"][-1]["parts"][0]["text"])
    assert material["files"] == {f"{REPO}:README.md": README}
    assert MARK not in material["review"]

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
    assert detail["design"] is None
    assert (await client.get(f"{RUNS}/{run_id}/design")).status_code == 404
