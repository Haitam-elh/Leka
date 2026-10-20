"""The designer's mock-ups (`renders: design_mockups`): the screen as its code
draws it today, and the proposals — each a page LEKA shows side by side,
before and after. Pure: no I/O, no model.

The model writes each mock-up as two strings — its CSS and its body — and
LEKA makes the page itself: a document that can reach nothing. No script
survives (none would run: the screen draws it in a frame sandboxed with no
permission at all), no link leads anywhere, no resource is fetched — its
Content-Security-Policy allows inline styles and `data:` images, nothing
else. What a mock-up shows, it holds.
"""

from __future__ import annotations

import html
import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# What one mock-up may weigh, as the model writes it.
MOST_CSS = 40_000
# Its body, kept — its images from the repository included (data: URIs).
MOST_BODY = 600_000
# The images LEKA puts in, from the repository: at most, each and how many.
MOST_ASSET_BYTES = 300_000
MOST_ASSETS = 12
_ASSET = re.compile(r"<img\b([^>]*?)\bdata-asset\s*=\s*([\"'])([^\"']+)\2([^>]*)>", re.IGNORECASE)
_IMG_SRC = re.compile(r"\ssrc\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "ico": "image/x-icon",
}
MOST_PROPOSALS = 3

# The page's own rules: inline styles and data: images only — nothing
# fetched, nothing run.
POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
    "media-src data:; form-action 'none'; base-uri 'none'"
)


class DesignMockup(BaseModel):
    """One screen, drawn: today's, or a proposal."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str = Field(
        max_length=80, description="Son nom : « Aujourd'hui », ou la direction — « Calme »."
    )
    axis: str = Field(
        default="",
        max_length=400,
        description="Ce que cette proposition change, en une phrase : son axe.",
    )
    when: str = Field(default="", max_length=400, description="Quand c'est le bon choix.")
    cost: str = Field(default="", max_length=400, description="Ce qu'elle coûte.")
    css: str = Field(
        default="",
        max_length=MOST_CSS,
        description="Sa feuille de style, complète : aucune ressource externe, aucun @import.",
    )
    body: str = Field(
        max_length=MOST_BODY,
        description="Le contenu de son <body>, en HTML : aucun script, aucun lien externe.",
    )


class DesignChange(BaseModel):
    """What the recommended proposal changes, as the review says it."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    where: str = Field(default="", max_length=300, description="Le fichier et la ligne.")
    before: str = Field(max_length=600)
    after: str = Field(max_length=600)
    why: str = Field(max_length=600)


class DesignProposal(BaseModel):
    """The screen today, its proposals, the one recommended and why."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    screen: str = Field(max_length=120, description="L'écran dessiné, ex. « Accueil ».")
    viewport: Literal["desktop", "mobile"] = Field(
        default="desktop", description="La largeur pour laquelle il est dessiné."
    )
    before: DesignMockup = Field(description="L'écran tel que son code le dessine aujourd'hui.")
    after: list[DesignMockup] = Field(
        min_length=1,
        max_length=MOST_PROPOSALS,
        description="Les propositions : une à trois, chacune sur son axe.",
    )
    recommended: int = Field(default=0, ge=0, description="L'indice de la proposition conseillée.")
    why: str = Field(default="", max_length=1_200, description="Pourquoi celle-là.")
    changes: list[DesignChange] = Field(default_factory=list, max_length=20)


# ── drawn one mock-up at a time (2026-10-18) ────────────────────────────────
# Asked whole — today and up to three proposals, each its CSS and its body —
# one answer outgrew its tokens, thinking included, and the review came
# alone, said nothing. Now: a plan, without a line of HTML; then each
# mock-up, drawn on its own.


class DesignDirection(BaseModel):
    """One proposal, planned: what it is before it is drawn."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str = Field(max_length=80, description="Son nom, ex. « Galerie orientée métiers ».")
    axis: str = Field(default="", max_length=400, description="Son axe, en une phrase.")
    when: str = Field(default="", max_length=400, description="Quand c'est le bon choix.")
    cost: str = Field(default="", max_length=400, description="Ce qu'elle coûte.")
    changes: str = Field(
        default="",
        max_length=4_000,
        description="Ce qu'elle change, élément par élément, avec les valeurs — ce qu'on dessine.",
    )


class DesignPlan(BaseModel):
    """The screen and the proposals to draw, the one recommended and why —
    no HTML yet."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    screen: str = Field(max_length=120, description="L'écran dessiné, ex. « Agents ».")
    viewport: Literal["desktop", "mobile"] = Field(default="desktop")
    directions: list[DesignDirection] = Field(min_length=1, max_length=MOST_PROPOSALS)
    recommended: int = Field(default=0, ge=0)
    why: str = Field(default="", max_length=1_200)
    changes: list[DesignChange] = Field(default_factory=list, max_length=20)


class MockupDrawing(BaseModel):
    """One mock-up, drawn: its style sheet and its body."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    css: str = Field(default="", max_length=MOST_CSS, description="Sa feuille de style, complète.")
    body: str = Field(max_length=MOST_BODY, description="Le contenu de son <body>, en HTML.")


def assembled(
    plan: DesignPlan, before: MockupDrawing, drawn: list[tuple[DesignDirection, MockupDrawing]]
) -> DesignProposal:
    """The proposal as one: today, and each direction drawn — the one
    recommended kept among those drawn."""
    wanted = plan.directions[min(plan.recommended, len(plan.directions) - 1)].name
    names = [d.name for d, _ in drawn]
    return DesignProposal(
        screen=plan.screen,
        viewport=plan.viewport,
        before=DesignMockup(name="Aujourd'hui", css=before.css, body=before.body),
        after=[
            DesignMockup(name=d.name, axis=d.axis, when=d.when, cost=d.cost, css=m.css, body=m.body)
            for d, m in drawn
        ],
        recommended=names.index(wanted) if wanted in names else 0,
        why=plan.why,
        changes=plan.changes,
    )


# ── what a mock-up may not hold ─────────────────────────────────────────────

_GONE = re.compile(
    r"<(script|iframe|object|embed|noscript|template)\b[^>]*>.*?</\1\s*>"
    r"|<(script|iframe|object|embed|base|link|meta|frame|frameset)\b[^>]*/?>"
    r"|<!doctype[^>]*>|</?(html|head|body)\b[^>]*>|<title\b[^>]*>.*?</title\s*>",
    re.IGNORECASE | re.DOTALL,
)
_HANDLERS = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
_LINKS = re.compile(
    r"\s(href|xlink:href|action|formaction|poster|srcset)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.IGNORECASE,
)
_SOURCES = re.compile(r"\ssrc\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
_URLS = re.compile(r"url\(\s*(['\"]?)(?!data:)[^)]*\1\s*\)", re.IGNORECASE)
_IMPORTS = re.compile(r"@import\b[^;]*;?", re.IGNORECASE)
_SCRIPTED = re.compile(r"(java|vb)script\s*:", re.IGNORECASE)
_STYLE_END = re.compile(r"</\s*style", re.IGNORECASE)


def _source(match: re.Match[str]) -> str:
    """An image's own bytes stay (data:image/…); any address goes."""
    value = match.group(1).strip("\"'")
    return f' src="{value}"' if value.lower().startswith("data:image/") else ""


def clean_body(body: str) -> str:
    """A body that runs nothing and reaches nothing: no script, frame or
    embedded object, no handler, no link out, no fetched source."""
    said = _GONE.sub("", body)
    said = _HANDLERS.sub("", said)
    said = _LINKS.sub(lambda m: ' href="#"' if m.group(1).lower() == "href" else "", said)
    said = _SOURCES.sub(_source, said)
    said = _URLS.sub("none", said)
    return _SCRIPTED.sub("", said)


def clean_css(css: str) -> str:
    """A style sheet that fetches nothing and stays a style sheet."""
    said = _IMPORTS.sub("", css)
    said = _URLS.sub("none", said)
    said = _STYLE_END.sub("", said)
    return _SCRIPTED.sub("", said)


def cleaned(proposal: DesignProposal) -> DesignProposal:
    """The proposal as LEKA shows it: every mock-up cleaned, the one
    recommended one of its proposals."""

    def one(mockup: DesignMockup) -> DesignMockup:
        return mockup.model_copy(
            update={"css": clean_css(mockup.css), "body": clean_body(mockup.body)}
        )

    after = [one(m) for m in proposal.after]
    return proposal.model_copy(
        update={
            "before": one(proposal.before),
            "after": after,
            "recommended": min(proposal.recommended, len(after) - 1),
        }
    )


def _rest(match: re.Match[str]) -> str:
    """An image tag's other attributes, its source aside, spaced once — the
    same however many times it is given its bytes."""
    rest = " ".join(_IMG_SRC.sub("", match.group(1) + match.group(4)).split())
    return f" {rest}" if rest else ""


def asset_paths(proposal: DesignProposal) -> list[str]:
    """The images its mock-ups show from the repository, as the code names
    them (<img data-asset="/brand/logo.png">) — a logo is never redrawn by
    hand (2026-10-19: « il fait des erreurs, comme le logo »)."""
    found: list[str] = []
    for mockup in (proposal.before, *proposal.after):
        found += [m.group(3).strip() for m in _ASSET.finditer(mockup.body)]
    return list(dict.fromkeys(p for p in found if p))[:MOST_ASSETS]


def candidates(path: str) -> list[str]:
    """Where an image the code names may sit in the repository: as named,
    or under the app's public folder."""
    said = path.split("?")[0].split("#")[0].lstrip("/")
    return list(
        dict.fromkeys([said, f"public/{said}", f"web/public/{said}", f"apps/web/public/{said}"])
    )


def with_assets(proposal: DesignProposal, assets: dict[str, str]) -> DesignProposal:
    """Its mock-ups, each image from the repository given its own bytes
    (`assets`: the path as named → a data: URI); one not found keeps its
    alt text."""

    def one(mockup: DesignMockup) -> DesignMockup:
        def put(match: re.Match[str]) -> str:
            path = match.group(3).strip()
            uri = assets.get(path)
            named = f' data-asset="{html.escape(path, quote=True)}"{_rest(match)}'
            return f'<img src="{uri}"{named}>' if uri else f"<img{named}>"

        return mockup.model_copy(update={"body": _ASSET.sub(put, mockup.body)})

    return proposal.model_copy(
        update={"before": one(proposal.before), "after": [one(m) for m in proposal.after]}
    )


def without_assets(body: str) -> str:
    """A body as the model wrote it: each image from the repository its
    path again, its bytes left out — what a correction is given."""

    def bare(match: re.Match[str]) -> str:
        return f'<img data-asset="{match.group(3)}"{_rest(match)}>'

    return _ASSET.sub(bare, body)


def corrected(proposal: DesignProposal, target: str, drawing: MockupDrawing) -> DesignProposal:
    """The proposal with one mock-up — today's (`before`) or a direction (its
    index) — drawn again."""
    if target == "before":
        mockup = proposal.before.model_copy(update={"css": drawing.css, "body": drawing.body})
        return proposal.model_copy(update={"before": mockup})
    index = int(target)
    after = list(proposal.after)
    after[index] = after[index].model_copy(update={"css": drawing.css, "body": drawing.body})
    return proposal.model_copy(update={"after": after})


def page(mockup: DesignMockup, *, language: str = "fr") -> str:
    """One mock-up as the page LEKA shows: its policy first, then its style,
    then its body — cleaned again, whatever was kept."""
    return (
        "<!doctype html>"
        f'<html lang="{html.escape(language, quote=True)}"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(mockup.name)}</title>"
        f"<style>{clean_css(mockup.css)}</style></head>"
        f"<body>{clean_body(mockup.body)}</body></html>"
    )


def design_key(workspace_id: uuid.UUID, run_id: uuid.UUID) -> str:
    return f"{workspace_id}/agent-runs/{run_id}/design.json"


def summary(proposal: DesignProposal, key: str) -> dict[str, object]:
    """What a run's detail keeps of it: where it is, and what it holds."""
    return {
        "key": key,
        "screen": proposal.screen,
        "viewport": proposal.viewport,
        "proposals": [m.name for m in proposal.after],
        "recommended": proposal.recommended,
    }


__all__ = [
    "MOST_PROPOSALS",
    "POLICY",
    "DesignChange",
    "DesignDirection",
    "DesignMockup",
    "DesignPlan",
    "DesignProposal",
    "MockupDrawing",
    "assembled",
    "asset_paths",
    "candidates",
    "clean_body",
    "clean_css",
    "cleaned",
    "corrected",
    "design_key",
    "page",
    "summary",
    "with_assets",
    "without_assets",
]
