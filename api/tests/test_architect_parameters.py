"""The architect's deck as Haitam tested it (2026-10-23): its parameters
reached the PDF as written ({{ENTITE}}, {{ESPACES_CONFLUENCE}}…), it drew
bricks no source names without reading the code, and a long title fell
over its subtitle.

What these protect:
- Its parameters are filled by LEKA before the model reads them: the
  organisation by its workspace when the request names none, where LEKA
  reads for the others; one unknown goes with its dash — never a {{…}}.
- What the deck writer copied as written is filled too.
- It reads the code when a repository is connected, and draws only what a
  source shows.
- A slide's title holds on one line.
"""

from __future__ import annotations

from leka.capabilities.deliverables.layout import TITLE_LEAST, header
from leka.capabilities.deliverables.scene import MARGIN, WIDTH, Box, Slide, text_width
from leka.capabilities.delivery import _cleaned, deck_messages
from leka.capabilities.registry import catalogue
from leka.capabilities.runs import READ_CODE, code_tools_of
from leka.capabilities.runtime import PARAMETER, Injected, filled, messages, parameters_of

ARCHITECT = {d.key: d for d in catalogue()}["application-architecture"]
ASKED = {"parcours": "De l'intention à l'action", "perimetre": "Plateforme LEKA"}


def test_its_parameters_are_filled_never_written_as_is() -> None:
    said = parameters_of(ASKED, "Acme Corp")
    assert (said["ORGANISATION"], said["ENTITE"], said["SERVICE"]) == ("Acme Corp", "", "")
    engie = parameters_of({**ASKED, "organisation": "ENGIE"}, "Acme Corp")
    assert engie["ORGANISATION"] == "ENGIE"
    line = "« {{ORGANISATION}} - {{ENTITE}} - {{SERVICE}} | Couche métier »"
    assert filled(line, said) == "« Acme Corp | Couche métier »"
    assert filled("{{ESPACES_CONFLUENCE}}", said) == "les espaces Confluence connectés à LEKA"
    assert filled("{{INCONNU}}", said) == ""
    told = messages(ARCHITECT, ASKED, Injected(elements=()), organisation="Acme Corp")
    system = str(told[0].content)
    assert not PARAMETER.search(system) and "Acme Corp" in system
    deck = str(deck_messages(ARCHITECT, ASKED, "## Analyse", organisation="Acme Corp")[0].content)
    assert not PARAMETER.search(deck)
    # What the deck writer copied as written, filled all the same.
    assert _cleaned({"rows": [["{{ANNUAIRE_CONTACTS}}", "LEKA - {{ENTITE}}"]]}, said) == {
        "rows": [
            [
                "les personnes et les équipes que le modèle de l'entreprise LEKA connaît "
                "(search_entities, read_entity)",
                "LEKA",
            ]
        ]
    }


def test_it_reads_the_code_and_draws_only_what_a_source_shows() -> None:
    # It names no tools: every read-only one, the code's reading with them.
    assert ARCHITECT.tools == () and code_tools_of(ARCHITECT) == READ_CODE
    assert "list_files" not in code_tools_of({d.key: d for d in catalogue()}["code-review"])
    system = str(messages(ARCHITECT, ASKED, Injected(elements=()))[0].content)
    assert "read the journey in its code before" in system
    assert "Never a generic brick no" in system


def test_a_slide_title_holds_on_one_line() -> None:
    slide = Slide()
    title = (
        "Parcours De l'intention à l'action - Vue globale - process B : "
        "B - TRAITEMENT DE L'INTENTION"
    )
    header(slide, title, "Couche métier complète")
    drawn = slide.items[0]
    assert isinstance(drawn, Box) and drawn.text == title
    assert text_width(title, drawn.size, bold=True) <= WIDTH - 2 * MARGIN
    assert drawn.size >= TITLE_LEAST
