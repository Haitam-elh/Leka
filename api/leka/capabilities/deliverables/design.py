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
MOST_BODY = 80_000
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
    "DesignMockup",
    "DesignProposal",
    "clean_body",
    "clean_css",
    "cleaned",
    "design_key",
    "page",
    "summary",
]
