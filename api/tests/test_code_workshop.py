"""The code-change agent's workshop (2026-10-30): the agent makes its change
itself, edit by edit, in a draft LEKA keeps — never the repository.

What these protect:
- An edit lands where its lines are — exactly, or copied with other spaces
  or indentation, as the file indents — and is answered with the lines
  around it, numbered, and a file that no longer parses said; one that does
  not land says why and where the closest lines are; a text there several
  times says each line, or is replaced each time when said so. Lines are
  inserted after a line; a whole file is written, never with « … » standing
  for code kept; a file deleted; each edit undone.
- A search goes through every file of the branch (its archive, read once),
  the draft's text where it changed, narrowed by folder and glob; a pattern
  that is no regular expression is said; the archive refused, the files
  read are searched, said so.
- The draft is checked as LEKA checks a change: a file that no longer
  parses, an import of no file. A plan's steps left undone and the checks'
  problems are said to the agent before its analysis is taken.
- The conversation of a long task is kept short, the oldest results
  dropped first, said dropped; the same call answered the same three times
  is said stuck.
- End to end: the agent searches, reads, plans, edits and checks; told its
  plan is not done, it finishes it; LEKA proposes the draft as the change,
  no model asked to write it again.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import io
import json
import tarfile
import uuid
from collections.abc import Callable, Mapping
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from leka.capabilities import AgentRun, execute_run, sync_catalogue
from leka.capabilities.gateway import Gateway, Message, Needs, Request, Tool
from leka.capabilities.gateway.contract import Role
from leka.capabilities.gateway.service import DROPPED, KEPT_WHOLE, condensed, stuck_said
from leka.capabilities.workshop import (
    EMPTY_SEARCHES,
    Draft,
    EditError,
    expert_advice,
    judged,
    matches_glob,
    nearest_paths,
)
from leka.connectors import CodeRefusedError
from leka.db import session_factory, workspace_scope
from leka.monitoring.now import _run_step
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import Script, gemini, leka_gemini, queued  # noqa: F401
from tests.test_code_changes_api import (
    BEFORE,
    REPO,
    GitHub,
    _github_source,
    github,  # noqa: F401
)
from tests.test_context_engine import model  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

API = "/api/v1/code-changes"
RUNS = "/api/v1/agent-runs"

PAGE = """export function Total({ amount }: { amount: number }) {
  return (
    <div className="total">
      <span>{amount}</span>
    </div>
  );
}
"""
SERVICE = """def balance(account):
    total = account.total
    return total


def owed(account):
    total = account.total
    return total
"""


class Code:
    """A GitHub repository as the draft reads it — its files, its archive."""

    def __init__(self, files: Mapping[str, str], *, archive: bool = True) -> None:
        self.files = dict(files)
        self.archived = archive
        self.reads: list[str] = []

    async def read(self, repository: str, path: str, ref: str) -> str | None:
        self.reads.append(path)
        return self.files.get(path)

    async def read_whole(self, repository: str, path: str, ref: str, *, most: int = 0) -> str:
        return self.files[path]

    async def paths(self, repository: str, ref: str, prefix: str = "") -> tuple[list[str], bool]:
        return [p for p in self.files if p.startswith(prefix)], False

    async def archive(self, repository: str, ref: str) -> dict[str, str]:
        if not self.archived:
            raise CodeRefusedError("too_large", "trop gros")
        return dict(self.files)


def draft(files: Mapping[str, str], **kwargs: Any) -> Draft:
    return Draft(Code(files, **kwargs), REPO, "main")  # type: ignore[arg-type]


# ── editing ─────────────────────────────────────────────────────────────────


async def test_an_edit_lands_where_its_lines_are_answered_with_them_numbered() -> None:
    work = draft({"app/total.tsx": PAGE})
    said = await work.replace(
        "app/total.tsx",
        "      <span>{amount}</span>\n",
        '      <span className="sum">{amount}</span>\n',
    )
    assert said.startswith("Edited app/total.tsx, lines 4-4 now:")
    assert '     4\t      <span className="sum">{amount}</span>' in said
    # The lines around it, each side.
    assert "     1\texport function Total" in said and "     7\t}" in said
    assert work.changed() == {
        "app/total.tsx": (PAGE, PAGE.replace("<span>", '<span className="sum">'))
    }
    # Undone: as it was, nothing changed.
    assert work.undo("app/total.tsx") == "Undid the last edit of app/total.tsx."
    assert work.changed() == {}


async def test_an_edit_copied_with_other_indentation_lands_as_the_file_indents() -> None:
    work = draft({"app/total.tsx": PAGE})
    await work.replace("app/total.tsx", "<span>{amount}</span>", "<strong>{amount}</strong>")
    await work.replace(
        f"{REPO}:app/total.tsx",
        '<div className="total">\n<strong>{amount}</strong>\n</div>',
        '<section className="total">\n  <strong>{amount}</strong>\n</section>',
    )
    after = work.changed()["app/total.tsx"][1]
    assert '    <section className="total">\n      <strong>{amount}</strong>\n    </section>' in (
        after or ""
    )


async def test_an_edit_that_does_not_land_says_why_and_where_the_closest_lines_are() -> None:
    work = draft({"app/service.py": SERVICE})
    with pytest.raises(EditError) as missed:
        await work.replace("app/service.py", "def balance(acount):\n", "def balance(a):\n")
    said = str(missed.value)
    assert "is not in app/service.py as you wrote it" in said
    assert "The closest lines in the file:\n     1\tdef balance(account):" in said
    # There twice: each line said — or replaced each time, when said so.
    with pytest.raises(EditError, match=r"2 times \(lines \[2, 7\]\)"):
        await work.replace("app/service.py", "    total = account.total\n", "    total = 0\n")
    await work.replace(
        "app/service.py", "    total = account.total\n", "    total = account.due\n", count=2
    )
    assert (work.changed()["app/service.py"][1] or "").count("account.due") == 2
    for wrong, why in (
        (("x.py", "a", "b"), "is not in the repository: create it with write_file"),
        (("../etc/passwd", "a", "b"), "is not a path inside the repository"),
        (("app/service.py", "", "b"), "old_text is empty"),
        (("app/service.py", "return total", "return total"), "are the same"),
    ):
        with pytest.raises(EditError, match=why):
            await work.replace(*wrong)


async def test_a_file_that_no_longer_parses_is_said_at_once() -> None:
    work = draft({"app/service.py": SERVICE})
    said = await work.replace("app/service.py", "    return total\n\n\n", "    return (total\n\n\n")
    assert "WARNING: app/service.py: it no longer parses" in said
    assert any("no longer parses" in p for p in await work.problems())


async def test_lines_are_inserted_and_whole_files_written_never_cut() -> None:
    work = draft({"app/service.py": SERVICE})
    said = await work.insert("app/service.py", 0, "import logging\n")
    assert "     1\timport logging" in said
    with pytest.raises(EditError, match="after_line goes from 0 to"):
        await work.insert("app/service.py", 99, "x")
    created = await work.write("app/new.py", "VALUE = 1\n")
    assert created.startswith("Created app/new.py (2 lines).")
    with pytest.raises(EditError, match="stands for code it leaves out"):
        await work.write("app/service.py", "def balance(account):\n    # ... rest unchanged\n")
    assert (await work.delete("app/new.py")).startswith("Deleted app/new.py")
    proposal = work.proposal(title="t")
    assert [(f.path, f.delete, f.content is not None) for f in proposal.files] == [
        ("app/service.py", False, True)
    ]
    await work.write("app/other.py", "B = 2\n")
    await work.delete("app/service.py")
    assert {(f.path, f.delete) for f in work.proposal().files} == {
        ("app/other.py", False),
        ("app/service.py", True),
    }


# ── searching ───────────────────────────────────────────────────────────────


async def test_a_search_goes_through_the_branch_as_the_draft_holds_it() -> None:
    work = draft({"app/service.py": SERVICE, "web/total.tsx": PAGE, "README.md": "# total\n"})
    found = await work.search(r"total\b", include="*.py")
    assert found["files_matched"] == 1 and found["searched"] == 1
    assert found["matches"][0] == {
        "path": "app/service.py",
        "line": 2,
        "text": "total = account.total",
    }
    # The draft's text where it changed it.
    await work.replace("app/service.py", "def owed(account):", "def debt(account):")
    assert (await work.search("debt", literal=True))["matches"][0]["line"] == 6
    assert (await work.search("{amount}", literal=True, under="web"))["files_matched"] == 1
    assert (await work.search("TOTAL", ignore_case=True, include="*.md"))["files_matched"] == 1
    with pytest.raises(EditError, match="is not a regular expression"):
        await work.search("(amount")


async def test_a_search_without_the_archive_reads_what_was_read_and_says_so() -> None:
    work = draft({"app/service.py": SERVICE, "web/total.tsx": PAGE}, archive=False)
    work.read = {"app/service.py": SERVICE}
    found = await work.search("total")
    assert found["searched"] == 1
    assert "Only the 1 files read so far were searched" in found["note"]


async def test_searches_that_find_nothing_again_and_again_are_said_fruitless() -> None:
    # 2026-10-30: Mistral searched 30 times for a class the repository has not.
    work = draft({"app/service.py": SERVICE})
    for _ in range(EMPTY_SEARCHES - 1):
        assert "note" not in await work.search("class Nowhere")
    assert "searches found nothing" in (await work.search("class Nowhere"))["note"]
    assert "note" not in await work.search("def balance")


def test_a_path_not_found_says_the_files_it_most_likely_means() -> None:
    tree = ["api/leka/capabilities/models.py", "api/leka/monitoring/models.py", "web/app/page.tsx"]
    assert (
        nearest_paths("leka/capabilities/models.py", tree)[0] == "api/leka/capabilities/models.py"
    )
    assert "web/app/page.tsx" in nearest_paths("web/app/pages.tsx", tree)
    assert nearest_paths("nothing/like/it.go", tree) == []


def test_a_glob_is_read_as_people_write_them() -> None:
    assert matches_glob("web/app/page.tsx", "*.tsx")
    assert matches_glob("web/app/page.tsx", "web/**/*.tsx")
    assert matches_glob("page.tsx", "**/*.tsx")
    assert matches_glob("api/tests/test_x.py", "**/test_*.py")
    assert matches_glob("web/a.ts", "*.{ts,tsx}") and matches_glob("web/a.tsx", "*.{ts,tsx}")
    assert not matches_glob("web/a.css", "*.{ts,tsx}")


# ── checked before it is taken ──────────────────────────────────────────────


async def test_an_import_of_no_file_and_a_plan_left_undone_are_said_before_the_answer() -> None:
    files = {"web/app/page.tsx": 'import { Total } from "@/components/total";\n'}
    files["web/components/total.tsx"] = PAGE
    work = draft(files)
    await work.replace(
        "web/app/page.tsx",
        'import { Total } from "@/components/total";\n',
        'import { Total } from "@/components/total";\n'
        'import { Fancy } from "@/components/fancy";\n',
    )
    work.set_plan(
        [
            {"title": "Importer le composant", "status": "completed"},
            {"title": "L'afficher", "status": "in_progress"},
            {"title": ""},
        ]
    )
    assert [(s.title, s.status) for s in work.plan] == [
        ("Importer le composant", "done"),
        ("L'afficher", "doing"),
    ]
    said = await judged(work)
    assert said[0].startswith("Your draft still has these problems:")
    assert "@/components/fancy" in said[0]
    assert said[1].startswith("Your plan still has steps not done: « L'afficher » (doing)")
    # Nothing changed: nothing to say.
    assert await judged(draft(files)) == []
    assert await judged(None) == []


# ── a long task's conversation ──────────────────────────────────────────────


def test_a_long_conversation_drops_its_oldest_results_first_said_dropped() -> None:
    asked = [Message.system("rules"), Message.user("x" * 1000)]
    results = [
        Message(Role.TOOL, "y" * 1000, tool_call_id=str(n), name="read_file") for n in range(20)
    ]
    kept = condensed([*asked, *results], 2, 15_000)
    assert kept[:2] == asked
    dropped = [m for m in kept if m.content == DROPPED]
    assert dropped and all(m.tool_call_id is not None for m in dropped)
    # The latest ones whole, every call still answered.
    assert all(m.content == "y" * 1000 for m in kept[-KEPT_WHOLE:])
    assert len(kept) == len(asked) + len(results)
    assert sum(len(m.content) for m in kept) <= 15_000
    # Short enough: as it is.
    assert condensed([*asked, *results[:2]], 2, 15_000) == [*asked, *results[:2]]


def test_the_same_call_answered_the_same_three_times_is_said_stuck() -> None:
    calls: list[str] = []
    args = {"path": "a.py"}
    assert stuck_said(calls, "read_file", args, "same") == "same"
    assert stuck_said(calls, "read_file", args, "same") == "same"
    assert "you made this same call 3 times" in stuck_said(calls, "read_file", args, "same")
    assert stuck_said(calls, "read_file", {"path": "b.py"}, "same") == "same"


# ── end to end ──────────────────────────────────────────────────────────────


def _tarball(files: Mapping[str, str]) -> bytes:
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w:gz") as tar:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"acme-payments-abc123/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return packed.getvalue()


class Archived(GitHub):
    """The fake GitHub, its branch's archive given too."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/repos/{REPO}/tarball/main":
            self.asked.append((request.method, request.url.path, None))
            files = {"app/balance.py": BEFORE, "README.md": "# Payments\n"} | self.listed
            return httpx.Response(200, content=_tarball(files))
        return super().__call__(request)


def _result(script: Script, asked: int) -> Any:
    part = script.asked[asked]["contents"][-1]["parts"][0]
    return part["functionResponse"]["response"]["result"]


@pytest.mark.integration
async def test_the_agent_makes_its_change_itself_and_leka_proposes_its_draft(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = Archived()
    from leka.connectors.base import Connector

    def http(
        self: Connector[Any, Any], base_url: str, headers: dict[str, str] | None = None
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url, headers=headers or {}, transport=httpx.MockTransport(fake)
        )

    monkeypatch.setattr(Connector, "http", http)
    _as(identity, acme, "member")
    await _github_source(acme["acme"])
    await sync_catalogue()
    step = {"title": "Déduire les paiements en attente du solde", "status": "doing"}
    analysis = (
        "# Analyse\n\n`app/balance.py` ignore les paiements en attente : le solde les déduit."
    )
    script = leka_gemini(
        gemini(call={"name": "search_code", "args": {"repository": REPO, "pattern": "account\\."}}),
        gemini(call={"name": "read_file", "args": {"repository": REPO, "path": "app/balance.py"}}),
        gemini(call={"name": "plan", "args": {"steps": [step]}}),
        gemini(
            call={
                "name": "edit_file",
                "args": {
                    "repository": REPO,
                    "path": "app/balance.py",
                    "old_text": "    return account.total\n",
                    "new_text": "    return account.total - account.pending\n",
                },
            }
        ),
        gemini(call={"name": "check_changes", "args": {}}),
        gemini(analysis),
        # Told its plan is not done: it marks it done, and answers again.
        gemini(call={"name": "plan", "args": {"steps": [{**step, "status": "done"}]}}),
        gemini(analysis),
    )
    started = await client.post(
        RUNS,
        json={"key": "code-change", "inputs": {"demande": "Corrige le solde", "depot": REPO}},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}

    declared = set(script.declared())
    assert {"search_code", "edit_file", "write_file", "check_changes", "plan"} <= declared
    found = json.loads(_result(script, 1))
    assert found["matches"][0] == {
        "path": "app/balance.py",
        "line": 2,
        "text": "return account.total",
    }
    edited = _result(script, 4)
    assert edited.startswith("Edited app/balance.py, lines 2-2 now:")
    assert "     2\t    return account.total - account.pending" in edited
    checked = json.loads(_result(script, 5))
    assert checked["problems"] == [] and checked["files_changed"] == 1
    told = script.asked[6]["contents"][-1]["parts"][0]["text"]
    assert "Your plan still has steps not done" in told
    # Eight answers, no more: no writer asked to write the change again.
    assert len(script.asked) == 8 and script.answers == []

    run = (await client.get(f"{RUNS}/{run_id}")).json()
    assert [e["kind"] for e in run["events"]][-2:] == ["proposed", "succeeded"]
    [change] = (await client.get(API, params={"run_id": run_id})).json()
    assert (change["repository"], change["base_branch"], change["status"]) == (
        REPO,
        "main",
        "proposed",
    )
    [file] = change["files"]
    assert (file["path"], file["additions"], file["deletions"]) == ("app/balance.py", 1, 1)
    assert "+    return account.total - account.pending" in file["diff"]
    # Nothing written to GitHub: the draft is LEKA's.
    assert fake.writes() == []


@pytest.mark.integration
async def test_an_empty_answer_is_told_and_asked_again_never_a_failure(
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    # 2026-10-30: Mistral answered nothing after its last tool.
    script = leka_gemini(
        gemini(call={"name": "think", "args": {"thought": "lire, puis répondre"}}),
        gemini(""),
        gemini("L'analyse."),
    )

    async def think(arguments: Mapping[str, Any]) -> str:
        return json.dumps({"noted": True})

    request = Request(
        purpose="agent:code-change",
        messages=[Message.system("rules"), Message.user("asked")],
        tools=[Tool("think", "Write your reasoning down.", {"type": "object"})],
    )
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            done = await Gateway(session, acme["acme"]).run_tools(
                request, {"think": think}, Needs(tools=True), rounds=6
            )
            await session.commit()
    assert done.text == "L'analyse."
    told = script.asked[2]["contents"][-1]["parts"][0]["text"]
    assert told.startswith("Your last answer was empty. Give your deliverable now")
    assert len(script.asked) == 3


@pytest.mark.integration
async def test_the_expert_is_a_stronger_model_shown_the_draft(
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    script = leka_gemini(gemini("Garde le calcul dans balance(), pas dans l'API."))
    work = draft({"app/service.py": SERVICE})
    await work.replace("app/service.py", "def owed(account):", "def debt(account):")
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            said = await expert_advice(
                session, acme["acme"], "Où mettre le calcul ?", "app/api.py l'appelle", work
            )
            await session.commit()
    assert said == "Garde le calcul dans balance(), pas dans l'API."
    asked = script.asked[0]
    material = asked["contents"][-1]["parts"][0]["text"]
    assert material.startswith("Question:\nOù mettre le calcul ?")
    assert "+def debt(account):" in material and "app/api.py l'appelle" in material
    assert "second opinion" in asked["systemInstruction"]["parts"][0]["text"]


def test_a_run_writing_its_draft_is_said_editing_live() -> None:
    running = AgentRun(status="running", detail={"drafting": {"files": 2, "edits": 5}})
    assert _run_step(running) == "editing"
    assert _run_step(AgentRun(status="running", detail={})) == "working"
