"""Code changes LEKA proposes (the code-change agent) — end to end, on a
GitHub source whose API is faked, and with what Gemini says scripted.

What these protect:
- Pure: a path that escapes the repository or reaches into .git is
  refused; a diff is LEKA's own — lines added and removed counted, a new
  file and a removed one said; a branch is always a new leka/… one.
- The agent reads the code with its own tools (list_files, read_file),
  never offered to an agent that does not name them; its change is asked
  again of the model, structured, given the files the agent read — exact
  edits, applied here to each file read again on its branch, never whole
  files written from memory (2026-10-18: asked for them, it wrote none) —
  then diffed: a file it says changed but did not, or one outside the
  repository, is left out; kept, proposed, with its run.
- An edit whose text is not in the file is said, never guessed: no change,
  the run's analysis stands, and its change can be written again — from the
  analysis it delivered and the files it read, read again — never the run
  done again; once its change is there, not again.
- Deciding takes intention:approve: a member cannot. Accepted on a source
  that does not allow pull requests, it stays proposed, said why; allowed,
  LEKA opens ONE pull request — a new branch leka/…, one commit with the
  files, the base its branch — and says where; decided once only. Rejected,
  said why. Another workspace sees nothing.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.api import agent_runs as agent_runs_api
from leka.capabilities import CodeChange, execute_run, rewrite_change, sync_catalogue
from leka.capabilities.changes import Edit, apply_edits, branch_of, diff_of, safe_path
from leka.capabilities.code_tools import MOST_CHARS, lines_of
from leka.connectors import SourceKind, SourceService
from leka.connectors.base import Connector
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import Script, gemini, leka_gemini, queued  # noqa: F401
from tests.test_context_engine import model  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

pytestmark = pytest.mark.integration

API = "/api/v1/code-changes"
RUNS = "/api/v1/agent-runs"
REPO = "acme/payments"
BEFORE = "def balance(account):\n    return account.total\n"
AFTER = "def balance(account):\n    return account.total - account.pending\n"
README = "# Payments\n"


# ── pure ────────────────────────────────────────────────────────────────────


def test_a_path_stays_inside_the_repository() -> None:
    assert safe_path("app/balance.py") == "app/balance.py"
    assert safe_path("./app//balance.py") == "app/balance.py"
    for wrong in ("../etc/passwd", "/etc/passwd", "app/../../x", ".git/config", "", "app/"):
        assert safe_path(wrong) is None, wrong


def test_a_diff_is_leka_s_own() -> None:
    diff, added, removed = diff_of("app/balance.py", BEFORE, AFTER)
    assert diff.startswith("--- a/app/balance.py\n+++ b/app/balance.py\n@@")
    assert (added, removed) == (1, 1)
    new, added, removed = diff_of("app/new.py", None, "x = 1\n")
    assert new.startswith("--- /dev/null\n+++ b/app/new.py") and (added, removed) == (1, 0)
    gone, added, removed = diff_of("README.md", README, None)
    assert "+++ /dev/null" in gone and (added, removed) == (0, 1)
    change = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert (
        branch_of("Corriger le solde affiché !", change) == "leka/corriger-le-solde-affich-12345678"
    )


# ── a fake GitHub ───────────────────────────────────────────────────────────


class GitHub:
    """GitHub's API for one repository, as LEKA uses it — every request kept."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.asked.append((request.method, path, body))
        assert request.headers["authorization"].startswith("Bearer ghp_")
        base = f"/repos/{REPO}"
        files = {"app/balance.py": BEFORE, "README.md": README}
        if request.method == "GET" and path == base:
            return httpx.Response(200, json={"default_branch": "main"})
        if request.method == "GET" and path == f"{base}/git/trees/main":
            tree = [{"path": p, "type": "blob", "size": len(t)} for p, t in files.items()]
            return httpx.Response(200, json={"tree": tree, "truncated": False})
        if request.method == "GET" and path.startswith(f"{base}/contents/"):
            name = path.removeprefix(f"{base}/contents/")
            if name not in files:
                return httpx.Response(404, json={"message": "Not Found"})
            content = base64.b64encode(files[name].encode()).decode()
            return httpx.Response(
                200, json={"type": "file", "size": len(files[name]), "content": content}
            )
        if request.method == "GET" and path == f"{base}/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "base-sha"}})
        if request.method == "GET" and path == f"{base}/git/commits/base-sha":
            return httpx.Response(200, json={"tree": {"sha": "base-tree"}})
        if request.method == "POST" and path == f"{base}/git/trees":
            return httpx.Response(201, json={"sha": "new-tree"})
        if request.method == "POST" and path == f"{base}/git/commits":
            return httpx.Response(201, json={"sha": "new-commit"})
        if request.method == "POST" and path == f"{base}/git/refs":
            return httpx.Response(201, json={"ref": body["ref"] if body else ""})
        if request.method == "POST" and path == f"{base}/pulls":
            return httpx.Response(
                201, json={"number": 7, "html_url": f"https://github.com/{REPO}/pull/7"}
            )
        return httpx.Response(404, json={"message": f"unexpected {request.method} {path}"})

    def writes(self) -> list[tuple[str, dict[str, Any] | None]]:
        return [(path, body) for method, path, body in self.asked if method != "GET"]


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> GitHub:
    fake = GitHub()

    def http(
        self: Connector[Any, Any], base_url: str, headers: dict[str, str] | None = None
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url, headers=headers or {}, transport=httpx.MockTransport(fake)
        )

    monkeypatch.setattr(Connector, "http", http)
    return fake


async def _github_source(workspace: uuid.UUID, *, pull_requests: bool = False) -> uuid.UUID:
    with workspace_scope(workspace):
        async with session_factory() as session:
            created = await SourceService(session, workspace, actor_user_id=None).create(
                SourceKind.GITHUB,
                f"GitHub {uuid.uuid4().hex[:6]}",
                {"repositories": [REPO], "pull_requests": pull_requests},
                {"token": "ghp_" + "a" * 36},
            )
            await session.execute(
                text("UPDATE sources SET status = 'active' WHERE id = :s"), {"s": created.id}
            )
            await session.commit()
            return created.id


async def _allow(workspace: uuid.UUID, source: uuid.UUID) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE sources SET config = config || '{\"pull_requests\": true}'::jsonb "
                    "WHERE id = :s"
                ),
                {"s": source},
            )
            await session.commit()


def _proposal() -> dict[str, Any]:
    return {
        "repository": REPO,
        "base_branch": "",
        "title": "Déduire les paiements en attente du solde",
        "summary": "Le solde affiché ignore les paiements en attente.",
        "files": [
            {
                "path": "app/balance.py",
                # An edit, copied from the file it read — not the whole file.
                "edits": [
                    {
                        "find": "    return account.total\n",
                        "replace": "    return account.total - account.pending\n",
                    }
                ],
                "why": "le calcul du solde",
            },
            # Outside the repository: left out.
            {"path": "../secrets.txt", "content": "x"},
            # Said changed, the same: left out.
            {"path": "README.md", "content": README},
        ],
    }


def test_edits_land_where_they_were_copied_from_or_say_why() -> None:
    text = "a\nb  \nc\nb\n"
    # Exact.
    assert apply_edits(text, [Edit(find="c\n", replace="C\n")]) == ("a\nb  \nC\nb\n", None)
    # In order, each on the file as the last left it.
    assert apply_edits("x\ny\n", [Edit(find="x", replace="z"), Edit(find="z\ny", replace="w")]) == (
        "w\n",
        None,
    )
    # A copy that lost its trailing spaces lands on its lines.
    assert apply_edits(text, [Edit(find="a\nb\nc", replace="a\nB\nc")]) == ("a\nB\nc\nb\n", None)
    # Not there, or there twice: said, never guessed.
    assert apply_edits(text, [Edit(find="zzz", replace="y")]) == (None, "not_found")
    assert apply_edits(text, [Edit(find="b", replace="y")]) == (None, "ambiguous")
    assert apply_edits(text, [Edit(find="", replace="y")]) == (None, "not_found")


def test_a_file_is_read_whole_or_by_ranges_and_says_which() -> None:
    text = "".join(f"line {n}\n" for n in range(1, 744))
    whole = lines_of(text, {})
    assert (whole["lines"], whole["from_line"], whole["to_line"], whole["complete"]) == (
        743,
        1,
        743,
        True,
    )
    assert whole["content"] == text and whole["truncated"] is False
    part = lines_of(text, {"from_line": 260, "to_line": 270})
    assert (part["from_line"], part["to_line"], part["complete"], part["truncated"]) == (
        260,
        270,
        False,
        False,
    )
    assert str(part["content"]).splitlines()[0] == "line 260"
    # Past its end, or upside down: what there is, never an error.
    assert lines_of(text, {"from_line": 900})["to_line"] == 743
    assert lines_of(text, {"from_line": 10, "to_line": 5})["to_line"] == 10
    # Too long to give at once: cut where it fits, said so.
    huge = "x" * 1_000 + "\n"
    big = lines_of(huge * 100, {})
    assert big["truncated"] is True and big["complete"] is False
    assert len(str(big["content"])) <= MOST_CHARS
    # One line longer than all it may give — a minified file: cut, said cut.
    minified = lines_of("x" * (MOST_CHARS * 3), {})
    assert len(str(minified["content"])) == MOST_CHARS
    assert (minified["truncated"], minified["complete"], minified["lines"]) == (True, False, 1)
    # An empty file: nothing, and that is all of it.
    assert lines_of("", {}) == {
        "content": "",
        "lines": 0,
        "from_line": 0,
        "to_line": 0,
        "complete": True,
        "truncated": False,
    }


# ── end to end ─────────────────────────────────────────────────────────────


async def test_a_change_is_proposed_diffed_and_accepted_as_a_pull_request(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    github: GitHub,
) -> None:
    _as(identity, acme, "member")
    source = await _github_source(acme["acme"])
    await sync_catalogue()
    analysis = "# Analyse\n\n`app/balance.py` ignore les paiements en attente."
    script = leka_gemini(
        gemini(call={"name": "list_files", "args": {"repository": REPO}}),
        gemini(call={"name": "read_file", "args": {"repository": REPO, "path": "app/balance.py"}}),
        gemini(analysis),
        gemini(json.dumps(_proposal())),
    )
    started = await client.post(
        RUNS,
        json={"key": "code-change", "inputs": {"demande": "Corrige le solde", "depot": REPO}},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}

    # Its own tools: the code tools and its method's guides (an interface's
    # change follows the designer's), declared — never the others'.
    assert set(script.declared()) == {
        "search_entities",
        "read_entity",
        "list_files",
        "read_file",
        "read_method",
    }
    read = json.loads(
        script.asked[2]["contents"][-1]["parts"][0]["functionResponse"]["response"]["result"]
    )
    assert read["content"] == BEFORE and read["branch"] == "main"
    # The change, asked structured with no tool, from the analysis and the
    # files the agent read.
    asked = script.asked[3]
    assert asked["generationConfig"]["responseMimeType"] == "application/json"
    assert "tools" not in asked
    material = json.loads(asked["contents"][-1]["parts"][0]["text"])
    assert material["analysis"] == analysis
    assert material["files"] == {f"{REPO}:app/balance.py": BEFORE}

    run = (await client.get(f"{RUNS}/{run_id}")).json()
    assert [e["kind"] for e in run["events"]][-2:] == ["proposed", "succeeded"]
    [change] = (await client.get(API, params={"run_id": run_id})).json()
    assert (change["status"], change["repository"], change["base_branch"]) == (
        "proposed",
        REPO,
        "main",
    )
    [file] = change["files"]
    assert (file["path"], file["status"], file["additions"], file["deletions"]) == (
        "app/balance.py",
        "modified",
        1,
        1,
    )
    assert "+    return account.total - account.pending" in file["diff"]
    assert change["pull_requests_allowed"] is False
    # Its content never travels: only its diff.
    assert "content" not in file

    # A member may not decide; an admin may — not yet on this source.
    accept = f"{API}/{change['id']}/accept"
    assert (await client.post(accept, json={})).status_code == 403
    _as(identity, acme, "admin")
    refused = await client.post(accept, json={})
    assert refused.status_code == 409
    assert refused.json()["error"]["details"][0]["message"] == "pull_requests_off"
    assert github.writes() == []
    still = (await client.get(f"{API}/{change['id']}")).json()
    assert (still["status"], still["error"]) == ("proposed", "pull_requests_off")

    # Allowed: one pull request, from a new branch, one commit.
    await _allow(acme["acme"], source)
    applied = await client.post(accept, json={"note": "OK pour la démo"})
    assert applied.status_code == 200, applied.text
    done = applied.json()
    assert (done["status"], done["pull_request_number"], done["error"]) == ("applied", 7, None)
    assert done["pull_request_url"] == f"https://github.com/{REPO}/pull/7"
    assert done["branch"].startswith("leka/deduire") or done["branch"].startswith("leka/d")
    writes = {path: body or {} for path, body in github.writes()}
    tree = writes[f"/repos/{REPO}/git/trees"]
    assert tree["base_tree"] == "base-tree"
    assert tree["tree"] == [
        {"path": "app/balance.py", "mode": "100644", "type": "blob", "content": AFTER}
    ]
    assert writes[f"/repos/{REPO}/git/commits"]["parents"] == ["base-sha"]
    assert writes[f"/repos/{REPO}/git/refs"]["ref"] == f"refs/heads/{done['branch']}"
    pull = writes[f"/repos/{REPO}/pulls"]
    assert (pull["base"], pull["head"]) == ("main", done["branch"])
    assert "acceptée par" in pull["body"] and "app/balance.py" in pull["body"]
    # Decided once.
    assert (await client.post(accept, json={})).status_code == 409


async def test_a_change_is_rejected_and_another_workspace_sees_nothing(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github: GitHub,
) -> None:
    source = await _github_source(acme["acme"], pull_requests=True)
    change_id = uuid.uuid4()
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            session.add(
                CodeChange(
                    workspace_id=acme["acme"],
                    id=change_id,
                    source_id=source,
                    repository=REPO,
                    base_branch="main",
                    title="Renommer",
                    summary="",
                    files=[
                        {
                            "path": "README.md",
                            "status": "modified",
                            "content": "# Paiements\n",
                            "diff": "",
                            "additions": 1,
                            "deletions": 1,
                            "why": "",
                        }
                    ],
                    status="proposed",
                )
            )
            await session.commit()
    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/{change_id}")).status_code == 404
    assert (await client.post(f"{API}/{change_id}/reject", json={})).status_code == 404
    _as(identity, acme, "admin")
    rejected = await client.post(f"{API}/{change_id}/reject", json={"note": "Pas maintenant"})
    assert rejected.status_code == 200
    assert (rejected.json()["status"], rejected.json()["note"]) == ("rejected", "Pas maintenant")
    assert (await client.post(f"{API}/{change_id}/accept", json={})).status_code == 409
    assert github.writes() == []


async def test_an_edit_not_found_is_said_and_the_change_written_again(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    github: GitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _as(identity, acme, "member")
    await _github_source(acme["acme"])
    await sync_catalogue()
    asked: list[uuid.UUID] = []

    async def queue(workspace_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        asked.append(run_id)
        return True

    monkeypatch.setattr(agent_runs_api, "queue_change", queue)
    wrong = _proposal()
    wrong["files"][0]["edits"] = [{"find": "    return total\n", "replace": "x"}]
    leka_gemini(
        gemini(call={"name": "read_file", "args": {"repository": REPO, "path": "app/balance.py"}}),
        gemini("# Analyse\n\nLe solde ignore les paiements en attente."),
        gemini(json.dumps(wrong)),
        # Written again: the edit copied right.
        gemini(json.dumps(_proposal())),
    )
    started = await client.post(
        RUNS,
        json={"key": "code-change", "inputs": {"demande": "Corrige le solde", "depot": REPO}},
    )
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}

    # No change, said why: the analysis stands.
    run = (await client.get(f"{RUNS}/{run_id}")).json()
    assert (run["status"], run["draw_failed"]) == ("succeeded", "edits_not_applied")
    failed = [e["detail"] for e in run["events"] if e["kind"] == "render_failed"]
    assert failed[-1]["code"] == "edits_not_applied" and "app/balance.py" in failed[-1]["said"]
    assert (await client.get(API, params={"run_id": run_id})).json() == []

    # Written again, from its analysis: queued, being written.
    again = await client.post(f"{RUNS}/{run_id}/change")
    assert again.status_code == 202, again.text
    assert (again.json()["drawing"], again.json()["draw_failed"]) == (["change"], None)
    assert asked == [uuid.UUID(run_id)]
    assert (await client.post(f"{RUNS}/{run_id}/change")).status_code == 409
    done = await rewrite_change(acme["acme"], uuid.UUID(run_id))
    assert done["error"] is None and done["proposed"]
    [change] = (await client.get(API, params={"run_id": run_id})).json()
    assert "+    return account.total - account.pending" in change["files"][0]["diff"]
    run = (await client.get(f"{RUNS}/{run_id}")).json()
    assert (run["drawing"], run["draw_failed"]) == ([], None)
    # Its change there: never written twice.
    assert (await client.post(f"{RUNS}/{run_id}/change")).status_code == 409
    # Only a code change is written again.
    architect = (await client.post(f"{RUNS}/{uuid.uuid4()}/change")).status_code
    assert architect == 404


async def test_a_change_not_written_says_why_as_it_was(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    github: GitHub,
) -> None:
    # 2026-10-18: answers cut at the token limit were said « no model »;
    # the change writer now has room, and why it failed is said as it was.
    _as(identity, acme, "member")
    await _github_source(acme["acme"])
    await sync_catalogue()
    cut = gemini('{"repository": "acme/pay')
    cut["candidates"][0]["finishReason"] = "MAX_TOKENS"
    script = leka_gemini(
        gemini(call={"name": "read_file", "args": {"repository": REPO, "path": "app/balance.py"}}),
        gemini("# Analyse\n\nLe solde ignore les paiements en attente."),
        cut,
        cut,
    )
    started = await client.post(
        RUNS,
        json={"key": "code-change", "inputs": {"demande": "Corrige le solde", "depot": REPO}},
    )
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}
    assert script.asked[2]["generationConfig"]["maxOutputTokens"] == 48_000
    run = (await client.get(f"{RUNS}/{run_id}")).json()
    assert run["draw_failed"] == "unanswered"
    assert "Cut at its limit of 48000 tokens" in (run["draw_said"] or "")
