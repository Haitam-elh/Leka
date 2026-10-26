"""The downloadable architect, packed: a zip a person unpacks and installs
with `pip install ./leka-architect`, or builds with Docker — the code of
this very package, renamed leka_architect, and what ships with it
(distribution.py). LEKA builds it on the fly for an organisation the agent
is dedicated to (GET /capabilities/application-architecture/package);
scripts/build_architect.py writes it to disk.

With it (2026-10-25):
- LEKA's deck renderer, the very files of leka/capabilities/deliverables —
  their imports made relative —, as leka_architect.deck: the PowerPoint and
  the PDF drawn on the same template as on LEKA;
- the instructions it follows (`instructions`): its organisation's own when
  it has them, else LEKA's — as leka_architect/consignes.md, as the prompt
  of Copilot in VS Code and of the MCP server, as the prompt pack's.

No secret is ever in it: its .env is an example, empty.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from . import __version__
from .distribution import (
    CLAUDE_CODE,
    DOCKERFILE,
    ENV_EXAMPLE,
    MCP,
    PYPROJECT,
    README,
    copilot_prompt,
    prompt_pack,
)

ROOT = "leka-architect"
HERE = Path(__file__).resolve().parent
# LEKA's deck renderer — pure, no I/O, no model (capabilities/deliverables).
DECK = HERE.parent / "capabilities" / "deliverables"
DECK_FILES = ("deck.py", "scene.py", "layout.py", "pptx_writer.py", "pdf_writer.py")
DECK_INIT = '''"""LEKA's deck renderer, shipped with the architect (2026-10-25): the same
files as LEKA's own (leka/capabilities/deliverables), their imports made
relative — the deck drawn here is drawn as on LEKA."""

from __future__ import annotations

from dataclasses import dataclass

from .deck import DECK_RULES, ArchitectureDeck
from .layout import deck_slides
from .pdf_writer import write_pdf
from .pptx_writer import write_pptx


@dataclass(frozen=True)
class Rendered:
    pptx: bytes
    pdf: bytes
    slides: int

    def of(self, fmt: str) -> bytes:
        return self.pptx if fmt == "pptx" else self.pdf


def render(deck: ArchitectureDeck) -> Rendered:
    slides = deck_slides(deck)
    title = f"Architecture applicative - Parcours {deck.parcours}"
    return Rendered(pptx=write_pptx(slides), pdf=write_pdf(slides, title), slides=len(slides))


__all__ = ["DECK_RULES", "ArchitectureDeck", "Rendered", "render"]
'''


def relative(source: str) -> str:
    """A renderer file as it ships: LEKA's absolute imports made relative."""
    return source.replace("from leka.capabilities.deliverables.", "from .")


def files(instructions: str | None = None) -> dict[str, bytes]:
    """Every file of the package, by its path in the zip — `instructions`,
    those it follows."""
    found: dict[str, bytes] = {}
    for source in sorted(HERE.glob("*.py")):
        found[f"{ROOT}/leka_architect/{source.name}"] = source.read_bytes()
    for name in DECK_FILES:
        text = (DECK / name).read_text(encoding="utf-8")
        found[f"{ROOT}/leka_architect/deck/{name}"] = relative(text).encode()
    found[f"{ROOT}/leka_architect/deck/__init__.py"] = DECK_INIT.encode()
    found[f"{ROOT}/pyproject.toml"] = PYPROJECT.encode()
    found[f"{ROOT}/README.md"] = README.encode()
    found[f"{ROOT}/.env.example"] = ENV_EXAMPLE.encode()
    found[f"{ROOT}/Dockerfile"] = DOCKERFILE.encode()
    for name, config in MCP.items():
        found[f"{ROOT}/mcp/{name}"] = (json.dumps(config, indent=2) + "\n").encode()
    found[f"{ROOT}/mcp/claude-code.txt"] = (CLAUDE_CODE + "\n").encode()
    for name, text in prompt_pack(instructions).items():
        found[f"{ROOT}/prompts/{name}"] = text.encode()
    if instructions:
        found[f"{ROOT}/leka_architect/consignes.md"] = instructions.encode()
        found[f"{ROOT}/copilot/.github/prompts/architecte-applicatif.prompt.md"] = copilot_prompt(
            instructions
        ).encode()
    return found


def build_zip(instructions: str | None = None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path, data in files(instructions).items():
            zipped.writestr(path, data)
    return out.getvalue()


def file_name() -> str:
    return f"leka-architect-{__version__}.zip"


__all__ = ["DECK_FILES", "ROOT", "build_zip", "file_name", "files", "relative"]
