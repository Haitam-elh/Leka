"""What an agent works by, read while it runs: a method library
(agents/_library/README.md) and the read_method tool — the designer's, LEKA's
own design guides (agents/_library/design).

What these protect:
- A library is never an agent: the loader skips every directory named `_…`,
  whatever SKILL.md it holds.
- An agent names one directory under _library/, nothing else; read_method
  and a library go together, and the library must be there.
- read_method gives the index — every guide, with what it is for — or one
  guide's text; never a file outside the library, never anything but a .md
  file; a guide too long is cut, said so. Without a library, no tool.
- The library is LEKA's own: its fifteen guides and their index, each with
  what it is for, all in French; none names an author, a repository or a
  licence — a deliverable speaks as LEKA (provenance: THIRD_PARTY_LICENSES.md).
- End to end, the designer reads a guide while it runs: the tool declared to
  the model, the guide's text given back to it, the call kept with the run.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from httpx import AsyncClient

from leka.capabilities import execute_run, sync_catalogue
from leka.capabilities.loader import AgentLoadError, discover
from leka.capabilities.method_tools import MOST_CHARS, about, guide, index, method_handlers
from leka.capabilities.registry import agents, catalogue
from leka.core.config import settings
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import Script, gemini, leka_gemini, queued  # noqa: F401
from tests.test_code_changes_api import REPO, GitHub, _github_source, github  # noqa: F401
from tests.test_context_engine import model  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

LIBRARY = settings.agents_dir / "_library" / "design"
GUIDES = (
    "audit-mouvement",
    "bibliotheques",
    "construire-animation",
    "directions",
    "interfaces-fluides",
    "notifications-sonner",
    "opportunites-animation",
    "performance-animation",
    "pire-des-cas",
    "principes",
    "react-native",
    "revue-animations",
    "swift",
    "telephone-web",
    "vocabulaire-mouvement",
)
# What a guide must never say: where a method came from.
SOURCES = re.compile(r"kowalski|emilkowalski|github\.com|licen[cs]e|copyright|©", re.IGNORECASE)

HEADER = """---
name: {name}
description: Use when a test needs an agent that reads its own method library.
version: 1.0.0
entity_types: [repository]
mode: read_only
risk: low
outputs: analysis
origin: internal
category: development
{extra}
---

# Test
"""


def _agent(root: Path, name: str, extra: str) -> None:
    folder = root / "test" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(HEADER.format(name=name, extra=extra), encoding="utf-8")


# ── a library is never an agent ─────────────────────────────────────────────


def test_a_library_is_never_loaded_as_an_agent() -> None:
    assert sorted(p.stem for p in LIBRARY.glob("*.md") if p.name != "README.md") == list(GUIDES)
    found = discover(settings.agents_dir)
    assert not any("_library" in path.parts for path in found)
    assert {d.key for d in catalogue()}.isdisjoint(GUIDES)


def test_an_agent_names_a_library_that_is_there_and_reads_it_with_read_method(
    tmp_path: Path,
) -> None:
    (tmp_path / "_library" / "guides").mkdir(parents=True)
    _agent(tmp_path, "reads-its-method", "tools: [read_method]\nmethod: _library/guides")
    [read] = agents(tmp_path)
    assert (read.method, read.tools) == ("_library/guides", ("read_method",))

    for extra, said in (
        ("tools: [read_method]", "go together"),
        ("method: _library/guides", "go together"),
        ("tools: [read_method]\nmethod: _library/missing", "no library"),
        ("tools: [read_method]\nmethod: _library/../registry", "_library/"),
        ("tools: [read_method]\nmethod: vendor/acme", "_library/"),
    ):
        wrong = tmp_path / f"wrong-{abs(hash(extra))}"
        (wrong / "_library" / "guides").mkdir(parents=True)
        _agent(wrong, "wrong", extra)
        with pytest.raises(AgentLoadError, match=said):
            agents(wrong)


# ── read_method ─────────────────────────────────────────────────────────────


def test_a_guide_is_a_markdown_file_under_the_library_and_nothing_else(tmp_path: Path) -> None:
    library = tmp_path / "_library" / "guides"
    (library / "skills" / "one").mkdir(parents=True)
    (library / "skills" / "one" / "SKILL.md").write_text("# One\n", encoding="utf-8")
    (library / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (tmp_path / "secret.md").write_text("# Not the library's\n", encoding="utf-8")
    (library / "link.md").symlink_to(tmp_path / "secret.md")

    assert guide(library, "skills/one/SKILL.md") == (library / "skills/one/SKILL.md").resolve()
    assert guide(library, " ./skills/one/SKILL.md ") is not None
    for wrong in (
        "",
        "../secret.md",
        "skills/../../secret.md",
        str(tmp_path / "secret.md"),
        "~/secret.md",
        "skills\\one\\SKILL.md",
        "LICENSE",
        "skills/one",
        "link.md",
        "missing.md",
    ):
        assert guide(library, wrong) is None, wrong


def test_what_a_guide_is_for_its_description_or_its_title_and_first_line() -> None:
    assert about("---\nname: x\ndescription: Build an animation.\n---\n# X\n") == (
        "Build an animation."
    )
    assert about("# Animation Recipes\n\nReady-to-build implementations.\n") == (
        "Animation Recipes: Ready-to-build implementations."
    )
    assert about("<a href='x'>\n\n# Skills\n\nFor designers.\n") == "Skills: For designers."


async def test_read_method_gives_the_index_or_one_guide_never_more() -> None:
    designer = {d.key: d for d in catalogue()}["design-review"]
    read = method_handlers(designer, settings.agents_dir)["read_method"]

    listed = await read({})
    said = json.loads(listed.text)
    assert (listed.outcome, said["library"]) == ("ok", "_library/design")
    paths = {f["path"]: f for f in said["files"]}
    assert {f"{g}.md" for g in GUIDES} | {"README.md"} == set(paths)
    assert paths["construire-animation.md"]["about"].startswith("Écrire une animation")
    assert all(f["about"] and f["lines"] > 1 for f in said["files"])

    review = await read({"path": "revue-animations.md"})
    text = json.loads(review.text)
    assert review.outcome == "ok"
    assert text["path"] == "revue-animations.md"
    assert "jamais `ease-in`" in text["text"] and text["truncated"] is False

    for wrong in ("../registry.yaml", "/etc/passwd", "LICENSE", "design"):
        refused = await read({"path": wrong})
        assert (refused.outcome, refused.why) == ("refused", "not_in_method"), wrong

    # An agent without a library has no such tool.
    assert (
        method_handlers({d.key: d for d in catalogue()}["code-review"], settings.agents_dir) == {}
    )


async def test_a_guide_too_long_is_cut_and_said_cut(tmp_path: Path) -> None:
    library = tmp_path / "_library" / "long"
    library.mkdir(parents=True)
    (library / "LONG.md").write_text("# Long\n" + "x" * (MOST_CHARS + 10), encoding="utf-8")
    index.cache_clear()
    designer = {d.key: d for d in catalogue()}["design-review"]
    read = method_handlers(replace(designer, method="_library/long"), tmp_path)["read_method"]
    said = json.loads((await read({"path": "LONG.md"})).text)
    assert (len(said["text"]), said["truncated"]) == (MOST_CHARS, True)


# ── the library: LEKA's own ─────────────────────────────────────────────────


def test_the_library_is_leka_s_own_guides_and_names_no_source() -> None:
    for name in (*GUIDES, "README"):
        text = (LIBRARY / f"{name}.md").read_text(encoding="utf-8")
        front = text.split("\n---\n", 1)[0]
        # The index reads each guide's title and what it is for.
        assert front.startswith("---\ntitre: ") and "\ndescription: " in front, name
        assert not SOURCES.search(text), (name, SOURCES.search(text))
    # Its provenance is in the licence notices, with the licence's text.
    notices = (settings.agents_dir.parent / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    assert "`agents/_library/design/`" in notices
    assert (
        settings.agents_dir.parent / "third_party" / "licenses" / "emilkowalski-skills-MIT.txt"
    ).is_file()


# ── end to end: the designer reads a guide while it runs ────────────────────

REPORT = "# Revue de design\n\n## Constats\n\nAucun constat : dis-le."


@pytest.mark.integration
async def test_the_designer_reads_its_method_while_it_runs(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    github: GitHub,
) -> None:
    _as(identity, acme, "member")
    await _github_source(acme["acme"])
    await sync_catalogue()
    script = leka_gemini(
        gemini(call={"name": "read_method", "args": {}}),
        gemini(call={"name": "read_method", "args": {"path": "revue-animations.md"}}),
        gemini(call={"name": "read_method", "args": {"path": "../registry.yaml"}}),
        gemini(REPORT),
    )
    started = await client.post(
        "/api/v1/agent-runs",
        json={"key": "design-review", "inputs": {"depot": REPO, "demande": "les animations"}},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}

    # Declared to the model with the code tools; its method in its instructions.
    assert set(script.declared()) == {
        "search_entities",
        "read_entity",
        "list_files",
        "read_file",
        "list_pull_requests",
        "read_pull_request",
        "read_method",
        "repository-profile",
    }
    system = script.asked[0]["systemInstruction"]["parts"][0]["text"]
    assert "Le cœur de sa méthode" in system and "`ease-in` retarde le premier mouvement" in system
    # It speaks as LEKA: no source named, and told never to name one.
    assert "Your deliverable speaks as LEKA" in system
    assert not SOURCES.search(
        system.split("Your deliverable speaks as LEKA", 1)[1].split("\n", 1)[1]
    )

    def answered(asked: int) -> dict[str, object]:
        part = script.asked[asked]["contents"][-1]["parts"][0]["functionResponse"]
        said: dict[str, object] = json.loads(part["response"]["result"])
        return said

    assert answered(1)["library"] == "_library/design"
    assert "jamais `ease-in`" in str(answered(2)["text"])
    assert answered(3) == {"error": "not_in_method", "path": "../registry.yaml"}

    run = (await client.get(f"/api/v1/agent-runs/{run_id}")).json()
    calls = [e["detail"] for e in run["events"] if e["kind"] == "tool"]
    assert [(c["name"], c["outcome"]) for c in calls] == [
        ("read_method", "ok"),
        ("read_method", "ok"),
        ("read_method", "refused"),
    ]
    assert run["output"] == REPORT
