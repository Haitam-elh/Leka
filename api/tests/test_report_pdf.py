"""Every agent's deliverable as a PDF (2026-10-23: « un vrai livrable »).

What these protect: whatever the model wrote — headings, tables, lists,
code, a fence left open, markup characters, signs Helvetica cannot draw,
cited ids — the PDF is drawn, never a failure.
"""

from __future__ import annotations

from datetime import UTC, datetime

from leka.capabilities.deliverables import report_pdf
from leka.capabilities.deliverables.report_pdf import _inline


def test_a_report_is_laid_out_whatever_it_holds() -> None:
    markdown = "\n".join(
        [
            "## Résumé",
            "Verdict : **À risque** — `orders` <b>sans</b> réplique & délai → 5 s ✓",
            "",
            "| Constat | Où |",
            "|---|:--|",
            "| Pas de délai | `api/x.py:12` |",
            "| Ligne courte |",
            "",
            "## Plan d'action",
            "1. Ajouter un délai",
            "   sur l'appel sortant",
            "2. Créer l'alerte [12345678-1234-1234-1234-123456789012]",
            "- un point *important*",
            "```python",
            "httpx.get(url, timeout=5)",
        ]
    )
    drawn = report_pdf(
        title="Fiabilité de payment-api",
        agent="Analyse de fiabilité",
        when=datetime(2026, 10, 23, 9, 30, tzinfo=UTC),
        markdown=markdown,
    )
    assert drawn.startswith(b"%PDF") and len(drawn) > 2_000
    assert report_pdf(title="Vide", agent="Agent", when=None, markdown="").startswith(b"%PDF")


def test_a_line_s_markup_is_escaped_then_read() -> None:
    said = _inline("**gras** et *italique*, `code` <script> & [lien](https://leka-core.com)")
    assert "<b>gras</b>" in said and "<i>italique</i>" in said
    assert '<font face="Courier">code</font>' in said
    assert "&lt;script&gt; &amp;" in said
    assert '<link href="https://leka-core.com"' in said
    # The ids it cites stay out of the page, as on the screen.
    assert _inline("Vu [12345678-1234-1234-1234-123456789012].") == "Vu."
