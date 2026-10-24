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
- Its pull request in red, « Réparer le problème » (2026-10-24): what
  failed read on GitHub — each check, its annotations, the end of its log
  fetched from GitHub's storage without the token — the files it names read
  at the pull request's head; the model's fix held to those files, asked
  again when an edit does not land; one commit on its leka/ branch, on top
  of where it stands, never forced; closed, reopened first. The change
  then holds what its pull request holds, so undoing it undoes the repair.
  A cause outside the code writes nothing; a branch moved meanwhile is
  said; merged, three repairs, one running, a member: refused.
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
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.api import agent_runs as agent_runs_api
from leka.api import code_changes as code_changes_api
from leka.capabilities import CodeChange, execute_run, rewrite_change, sync_catalogue
from leka.capabilities.changes import (
    Edit,
    ProposedFile,
    RepairProposal,
    apply_edits,
    before_of,
    body_of,
    branch_of,
    cited_paths,
    diff_of,
    edits_from_diff,
    follow_pull_requests,
    on_base,
    paths_named,
    repair_change,
    repair_problems,
    reversed_diff,
    safe_path,
    stage_of,
)
from leka.capabilities.code_tools import MOST_CHARS, lines_of
from leka.connectors import SourceKind, SourceService
from leka.connectors.base import Connector
from leka.connectors.github.code import MOST_LOG, checks_of, log_excerpt
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
# A longer file: what moves far from a change, and what moves where it is.
LEDGER = "".join(f"line {n}\n" for n in range(1, 13))
LEDGER_AFTER = LEDGER.replace("line 2\n", "line 2 changed\n")


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


def test_a_pull_request_says_no_id_of_leka_s_own() -> None:
    # 2026-10-24: #426 said « … pour le dépôt [f4ad4e4d-7670-5f9f-83c6-ae09e8cfd613] ».
    change = CodeChange(
        summary="Prête pour le dépôt [f4ad4e4d-7670-5f9f-83c6-ae09e8cfd613]. Elle change le titre.",
        files=[{"path": "a.py", "status": "modified", "additions": 1, "deletions": 1}],
    )
    body = body_of(change, by="Nora")
    assert body.startswith("Prête pour le dépôt. Elle change le titre.")
    assert "f4ad4e4d" not in body


# ── a fake GitHub ───────────────────────────────────────────────────────────


class GitHub:
    """GitHub's API for one repository, as LEKA uses it — every request kept."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, dict[str, Any] | None]] = []
        # Files read but never listed — an image a mock-up shows (2026-10-19).
        self.extra: dict[str, str] = {}
        # The branch as it is now, when it moved since the change was read
        # (2026-10-20); the pull requests open, the branches that exist.
        self.moved: dict[str, str] = {}
        self.open: list[dict[str, Any]] = []
        self.branches: set[str] = set()
        # The pull request #7 as GitHub tells it, its checks, the
        # deployments after its merge.
        self.pull: dict[str, Any] = {"state": "open", "head": {"sha": "new-commit"}}
        self.check_runs: list[dict[str, Any]] = []
        self.statuses: list[dict[str, Any]] = []
        self.deployments: list[dict[str, Any]] = []
        self.deployment_states: dict[int, str] = {}
        # Its deployment workflow's runs, started by LEKA (2026-10-20); the
        # commits main took since the merge.
        self.runs: list[dict[str, Any]] = []
        self.newer = 0
        # A pull request in red (2026-10-24): files as they are at a commit,
        # each check's annotations and log, its branch moved by someone.
        self.at: dict[str, dict[str, str]] = {}
        self.annotations: dict[int, list[dict[str, Any]]] = {}
        self.logs: dict[int, str] = {}
        self.branch_moved = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.asked.append((request.method, path, body))
        if request.url.host == "storage.example":
            # GitHub's storage, at a signed address: never given the token.
            assert "authorization" not in request.headers
            return httpx.Response(200, text=self.logs[int(path.split("/")[-1])])
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
            readable = (
                files | self.extra | self.moved | self.at.get(request.url.params.get("ref", ""), {})
            )
            if name not in readable:
                return httpx.Response(404, json={"message": "Not Found"})
            content = base64.b64encode(readable[name].encode()).decode()
            return httpx.Response(
                200, json={"type": "file", "size": len(readable[name]), "content": content}
            )
        if request.method == "GET" and path == f"{base}/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "base-sha"}})
        if request.method == "GET" and path == f"{base}/git/commits/base-sha":
            return httpx.Response(200, json={"tree": {"sha": "base-tree"}})
        if request.method == "POST" and path == f"{base}/git/trees":
            return httpx.Response(201, json={"sha": "new-tree"})
        if request.method == "GET" and path == f"{base}/git/commits/new-commit":
            return httpx.Response(
                200, json={"tree": {"sha": "head-tree"}, "parents": [{"sha": "base-sha"}]}
            )
        if request.method == "POST" and path == f"{base}/git/commits":
            # LEKA's commit on the base; its repair, on the pull request's head.
            repaired = body is not None and body["parents"] == ["new-commit"]
            return httpx.Response(201, json={"sha": "fix-commit" if repaired else "new-commit"})
        if request.method == "PATCH" and path.startswith(f"{base}/git/refs/heads/"):
            if self.branch_moved:
                return httpx.Response(422, json={"message": "Update is not a fast forward"})
            return httpx.Response(200, json={"object": {"sha": body["sha"] if body else ""}})
        if request.method == "GET" and path.startswith(f"{base}/check-runs/"):
            number = int(path.split("/")[-2])
            return httpx.Response(200, json=self.annotations.get(number, []))
        if request.method == "GET" and path.startswith(f"{base}/actions/jobs/"):
            number = int(path.split("/")[-2])
            if number not in self.logs:
                return httpx.Response(410, json={"message": "Gone"})
            where = f"https://storage.example/logs/{number}?sig=abc"
            return httpx.Response(302, headers={"location": where})
        if request.method == "POST" and path == f"{base}/git/refs":
            ref = body["ref"] if body else ""
            if ref.removeprefix("refs/heads/") in self.branches:
                return httpx.Response(422, json={"message": "Reference already exists"})
            return httpx.Response(201, json={"ref": ref})
        if request.method == "GET" and path == f"{base}/pulls":
            return httpx.Response(200, json=self.open)
        if request.method == "POST" and path == f"{base}/pulls":
            return httpx.Response(
                201, json={"number": 7, "html_url": f"https://github.com/{REPO}/pull/7"}
            )
        if request.method == "GET" and path == f"{base}/pulls/7":
            return httpx.Response(200, json={"number": 7, "base": {"ref": "main"}, **self.pull})
        if request.method == "GET" and path == f"{base}/commits/new-commit/check-runs":
            return httpx.Response(200, json={"check_runs": self.check_runs})
        if request.method == "GET" and path == f"{base}/commits/new-commit/status":
            return httpx.Response(200, json={"statuses": self.statuses})
        if request.method == "GET" and path == f"{base}/deployments":
            return httpx.Response(200, json=self.deployments)
        if request.method == "GET" and path.startswith(f"{base}/deployments/"):
            number = int(path.split("/")[-2])
            state = self.deployment_states.get(number)
            said = [{"state": state, "created_at": "2026-10-20T12:30:00Z"}] if state else []
            return httpx.Response(200, json=said)
        if request.method == "PATCH" and path == f"{base}/pulls/7":
            self.pull = {**self.pull, "state": (body or {}).get("state", "closed")}
            return httpx.Response(200, json={"number": 7, **self.pull})
        if request.method == "GET" and path == f"{base}/commits/merge-sha":
            return httpx.Response(
                200, json={"sha": "merge-sha", "parents": [{"sha": "before-sha"}]}
            )
        if request.method == "POST" and path == f"{base}/actions/workflows/cd.yml/dispatches":
            return httpx.Response(204)
        if request.method == "GET" and path == f"{base}/actions/workflows/cd.yml/runs":
            return httpx.Response(200, json={"workflow_runs": self.runs})
        if request.method == "GET" and path.startswith(f"{base}/compare/"):
            # A deployment after the merge holds it — unless it is "old".
            status = "behind" if "old" in path else "ahead"
            return httpx.Response(200, json={"status": status, "ahead_by": self.newer})
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


# Haitam's analysis, 2026-10-18, as its deliverable gave it: the diff was
# there, the change still « not written ».
HIS_DIFF = """Diff proposé pour web/components/intentions/intention-composer.tsx :
```diff
--- a/web/components/intentions/intention-composer.tsx
+++ b/web/components/intentions/intention-composer.tsx
@@ -221,7 +221,7 @@ export function IntentionComposer({
               placeholder={t.composer.compactPlaceholder}
               rows={1}
               data-testid="intention-input"
-              className="px-1 py-3 text-[0.9375rem] shadow-none"
+              className="px-1 py-3 text-base shadow-none md:text-[0.9375rem]"
             />
```
B. `web/e2e/home.spec.ts` gagne une assertion.
"""
COMPOSER = (
    "export function IntentionComposer() {\n"
    "  return (\n"
    "            <Textarea\n"
    "              placeholder={t.composer.compactPlaceholder}\n"
    "              rows={1}\n"
    '              data-testid="intention-input"\n'
    '              className="px-1 py-3 text-[0.9375rem] shadow-none"\n'
    "            />\n"
    "  );\n"
    "}\n"
)


def test_an_analysis_diff_becomes_edits_that_land_on_the_file() -> None:
    [proposed] = edits_from_diff(HIS_DIFF)
    assert proposed.path == "web/components/intentions/intention-composer.tsx"
    [edit] = proposed.edits
    after, why = apply_edits(COMPOSER, [edit])
    assert why is None and after is not None
    assert 'className="px-1 py-3 text-base shadow-none md:text-[0.9375rem]"' in after
    assert "text-[0.9375rem] shadow-none" not in after
    # The files it names, in its diffs or quoted, in order.
    assert paths_named(HIS_DIFF) == [
        "web/components/intentions/intention-composer.tsx",
        "web/e2e/home.spec.ts",
    ]
    # A new file, its whole content; a context line that lost its space.
    [new] = edits_from_diff("--- /dev/null\n+++ b/app/new.py\n@@ -0,0 +1,2 @@\n+a = 1\n+b = 2\n")
    assert (new.path, new.content) == ("app/new.py", "a = 1\nb = 2\n")
    [blank] = edits_from_diff("--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n a\n\n-b\n+c\n")
    assert blank.edits[0].find == "a\n\nb" and blank.edits[0].replace == "a\n\nc"


def test_an_edit_copied_with_other_indentation_lands_with_the_file_s() -> None:
    text = "def f():\n    if x:\n        return 1\n"
    edit = Edit(find="if x:\n    return 1", replace="if x:\n    return 2")
    assert apply_edits(text, [edit]) == ("def f():\n    if x:\n        return 2\n", None)


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
        # And again, its branch moved where it changes (2026-10-20).
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
    # Unless refused because its branch moved where it changes: written
    # again on the branch as it is now, the old one failed (2026-10-20).
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE code_changes SET error = 'changed_since' WHERE id = :c"),
                {"c": change["id"]},
            )
            await session.commit()
    assert (await client.post(f"{RUNS}/{run_id}/change")).status_code == 202
    assert (await rewrite_change(acme["acme"], uuid.UUID(run_id)))["error"] is None
    written = (await client.get(API, params={"run_id": run_id})).json()
    assert [(c["status"], c["id"] == change["id"]) for c in written] == [
        ("proposed", False),
        ("failed", True),
    ]
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


async def test_the_analysis_own_diff_is_the_change_no_model_asked_again(
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
    analysis = (
        "# Analyse\n\nLe solde ignore les paiements en attente.\n\n```diff\n"
        "--- a/app/balance.py\n+++ b/app/balance.py\n@@ -1,2 +1,2 @@\n"
        " def balance(account):\n-    return account.total\n"
        "+    return account.total - account.pending\n```\n"
    )
    # The analysis only: no answer scripted for a change — none is asked.
    script = leka_gemini(gemini(analysis))
    started = await client.post(
        RUNS,
        json={"key": "code-change", "inputs": {"demande": "Corrige le solde", "depot": REPO}},
    )
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}
    assert len(script.asked) == 1
    [change] = (await client.get(API, params={"run_id": run_id})).json()
    assert change["title"] == "Corrige le solde" and change["repository"] == REPO
    assert "Le solde ignore les paiements en attente." in change["summary"]
    assert "+    return account.total - account.pending" in change["files"][0]["diff"]


async def test_a_run_without_its_files_kept_reads_those_its_analysis_names(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    github: GitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 2026-10-18: a run from before its files were kept, written again, was
    # given no file — and wrote none.
    _as(identity, acme, "member")
    await _github_source(acme["acme"])
    await sync_catalogue()

    async def queue(workspace_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        return True

    monkeypatch.setattr(agent_runs_api, "queue_change", queue)
    script = leka_gemini(
        gemini("# Analyse\n\n`app/balance.py` ignore les paiements en attente."),
        gemini(json.dumps({"repository": REPO, "title": "x", "summary": "y", "files": []})),
        gemini(json.dumps(_proposal())),
    )
    started = await client.post(
        RUNS,
        json={"key": "code-change", "inputs": {"demande": "Corrige le solde", "depot": REPO}},
    )
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE agent_runs SET detail = detail - 'read_files' WHERE id = :r"),
                {"r": uuid.UUID(run_id)},
            )
            await session.commit()
    assert (await client.post(f"{RUNS}/{run_id}/change")).status_code == 202
    done = await rewrite_change(acme["acme"], uuid.UUID(run_id))
    assert done["error"] is None
    material = json.loads(script.asked[2]["contents"][-1]["parts"][0]["text"])
    assert material["files"] == {f"{REPO}:app/balance.py": BEFORE}


# ── accepted later, then followed (2026-10-20) ──────────────────────────────


def test_a_change_is_laid_on_its_branch_as_it_is_now_or_refused() -> None:
    path = "app/ledger.py"
    diff = diff_of(path, LEDGER, LEDGER_AFTER)[0]
    # Unchanged since: as proposed.
    assert on_base(path, LEDGER, LEDGER_AFTER, diff) == (LEDGER_AFTER, "changes")
    # Changed far from it: laid again, the newer line kept.
    newer = LEDGER.replace("line 11\n", "line 11 newer\n")
    after, state = on_base(path, newer, LEDGER_AFTER, diff)
    assert state == "changes"
    assert after == newer.replace("line 2\n", "line 2 changed\n")
    # Changed where it changes: refused, never undone.
    assert on_base(path, LEDGER.replace("line 3\n", "line 3 newer\n"), LEDGER_AFTER, diff) == (
        None,
        "moved",
    )
    # Already there; removed since; a file to add that exists now.
    assert on_base(path, LEDGER_AFTER, LEDGER_AFTER, diff)[1] == "same"
    assert on_base(path, None, LEDGER_AFTER, diff) == (None, "moved")
    added = diff_of("new.py", None, "x = 1\n")[0]
    assert on_base("new.py", None, "x = 1\n", added) == ("x = 1\n", "changes")
    assert on_base("new.py", "x = 2\n", "x = 1\n", added) == (None, "moved")
    # A file to remove: removed as it was read, refused when it changed.
    removed = diff_of(path, LEDGER, None)[0]
    assert on_base(path, LEDGER, None, removed) == (None, "changes")
    assert on_base(path, None, None, removed)[1] == "same"
    assert on_base(path, newer, None, removed) == (None, "moved")


def test_checks_say_one_word_from_each_check_s_latest_run() -> None:
    assert checks_of([], [])["state"] == "none"
    running = [{"id": 1, "name": "api", "status": "in_progress"}]
    assert checks_of(running, [])["state"] == "pending"
    failed = [
        {"id": 1, "name": "api", "status": "completed", "conclusion": "failure", "html_url": "u"},
        {"id": 2, "name": "web", "status": "completed", "conclusion": "success"},
        {"id": 3, "name": "main", "status": "completed", "conclusion": "skipped"},
    ]
    said = checks_of(failed, [])
    assert (said["state"], said["failed"], said["failed_url"], said["passed"]) == (
        "failure",
        ["api"],
        "u",
        2,
    )
    # Run again, green: the latest run is the one.
    again = [*failed, {"id": 4, "name": "api", "status": "completed", "conclusion": "success"}]
    assert checks_of(again, [])["state"] == "success"
    # A commit status counts too.
    assert checks_of(again, [{"context": "ci/x", "state": "pending"}])["state"] == "pending"
    assert checks_of(again, [{"context": "ci/x", "state": "error"}])["failed"] == ["ci/x"]


def test_a_pull_request_s_stage_is_one_word() -> None:
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)
    soon, later = now - timedelta(minutes=2), now - timedelta(hours=1)

    def stage(seen: dict[str, Any], opened: datetime = soon) -> str:
        return stage_of({"state": "open", **seen}, opened_at=opened, now=now)

    assert stage({"checks": {"state": "none"}}) == "checks"
    assert stage({"checks": {"state": "none"}}, later) == "no_checks"
    assert stage({"checks": {"state": "pending"}}) == "checks"
    assert stage({"checks": {"state": "failure"}, "mergeable": False}) == "checks_failed"
    assert stage({"checks": {"state": "success"}, "mergeable": False}) == "conflict"
    assert stage({"checks": {"state": "success"}, "mergeable": True}) == "ready"
    assert stage({"state": "closed"}) == "closed"
    assert stage({"state": "merged"}) == "merged"
    for said, word in (
        ("queued", "deploying"),
        ("in_progress", "deploying"),
        ("success", "deployed"),
        ("inactive", "deployed"),
        ("failure", "deploy_failed"),
        ("error", "deploy_failed"),
    ):
        assert stage({"state": "merged", "deployment": {"state": said}}) == word


async def _proposed(
    workspace: uuid.UUID, source: uuid.UUID, path: str, before: str, after: str
) -> uuid.UUID:
    """A change proposed from `before` as it was read — `after` its file."""
    diff, added, removed = diff_of(path, before, after)
    change_id = uuid.uuid4()
    with workspace_scope(workspace):
        async with session_factory() as session:
            session.add(
                CodeChange(
                    workspace_id=workspace,
                    id=change_id,
                    source_id=source,
                    repository=REPO,
                    base_branch="main",
                    title="Changer la ligne 2",
                    summary="La ligne 2 change.",
                    files=[
                        {
                            "path": path,
                            "status": "modified",
                            "content": after,
                            "diff": diff,
                            "additions": added,
                            "deletions": removed,
                            "why": "",
                        }
                    ],
                    status="proposed",
                )
            )
            await session.commit()
    return change_id


async def test_a_change_accepted_later_never_undoes_what_was_merged_since(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github: GitHub,
) -> None:
    source = await _github_source(acme["acme"], pull_requests=True)
    github.extra["app/ledger.py"] = LEDGER
    change_id = await _proposed(acme["acme"], source, "app/ledger.py", LEDGER, LEDGER_AFTER)
    _as(identity, acme, "admin")
    accept = f"{API}/{change_id}/accept"

    # Changed since where LEKA changes it: refused, said, nothing written.
    github.moved["app/ledger.py"] = LEDGER.replace("line 3\n", "line 3 newer\n")
    refused = await client.post(accept, json={})
    assert refused.status_code == 409
    assert refused.json()["error"]["details"][0]["message"] == "changed_since"
    assert "app/ledger.py" in refused.json()["error"]["message"]
    assert github.writes() == []
    # Already there: said so, nothing written.
    github.moved["app/ledger.py"] = LEDGER_AFTER
    already = await client.post(accept, json={})
    assert already.json()["error"]["details"][0]["message"] == "already_applied"
    assert github.writes() == []

    # Changed far from it: the pull request holds the newer line and LEKA's,
    # from the commit the files were read at; the change says what it did.
    newer = LEDGER.replace("line 11\n", "line 11 newer\n")
    github.moved["app/ledger.py"] = newer
    done = await client.post(accept, json={})
    assert done.status_code == 200, done.text
    writes = {path: body or {} for path, body in github.writes()}
    [entry] = writes[f"/repos/{REPO}/git/trees"]["tree"]
    assert entry["content"] == newer.replace("line 2\n", "line 2 changed\n")
    assert writes[f"/repos/{REPO}/git/commits"]["parents"] == ["base-sha"]
    [file] = done.json()["files"]
    assert "+line 2 changed" in file["diff"] and (file["additions"], file["deletions"]) == (1, 1)
    assert (done.json()["status"], done.json()["error"]) == ("applied", None)
    assert done.json()["follow"]["stage"] == "checks"


async def test_a_pull_request_already_open_is_the_one_and_a_branch_never_overwritten(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github: GitHub,
) -> None:
    source = await _github_source(acme["acme"], pull_requests=True)
    github.extra["app/ledger.py"] = LEDGER
    _as(identity, acme, "admin")

    # A try whose answer was lost: its pull request is the one, nothing new.
    first = await _proposed(acme["acme"], source, "app/ledger.py", LEDGER, LEDGER_AFTER)
    branch = branch_of("Changer la ligne 2", first)
    github.open = [
        {
            "number": 9,
            "html_url": f"https://github.com/{REPO}/pull/9",
            "head": {"ref": f"{branch}-2", "sha": "earlier"},
        }
    ]
    adopted = (await client.post(f"{API}/{first}/accept", json={})).json()
    assert (adopted["pull_request_number"], adopted["branch"]) == (9, f"{branch}-2")
    assert github.writes() == []

    # A branch left without a pull request: the next name, never a push.
    second = await _proposed(acme["acme"], source, "app/ledger.py", LEDGER, LEDGER_AFTER)
    branch = branch_of("Changer la ligne 2", second)
    github.open, github.branches = [], {branch}
    opened = (await client.post(f"{API}/{second}/accept", json={})).json()
    assert (opened["pull_request_number"], opened["branch"]) == (7, f"{branch}-2")
    refs = [body["ref"] for path, body in github.writes() if path.endswith("/git/refs") and body]
    assert refs == [f"refs/heads/{branch}", f"refs/heads/{branch}-2"]


def _at(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


async def test_a_pull_request_is_followed_to_its_deployment_never_merged_by_leka(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github: GitHub,
) -> None:
    source = await _github_source(acme["acme"], pull_requests=True)
    github.extra["app/ledger.py"] = LEDGER
    change_id = await _proposed(acme["acme"], source, "app/ledger.py", LEDGER, LEDGER_AFTER)
    _as(identity, acme, "member")
    assert (await client.post(f"{API}/{change_id}/follow")).status_code == 200
    _as(identity, acme, "admin")
    assert (await client.post(f"{API}/{change_id}/accept", json={})).status_code == 200
    now = datetime.now(UTC)

    async def stage_at(minutes: int) -> dict[str, Any]:
        await follow_pull_requests(now=now + timedelta(minutes=minutes))
        read = (await client.get(f"{API}/{change_id}")).json()
        return dict(read["follow"])

    # Its checks running, then one failed, then run again green: for a
    # person to merge — LEKA never does.
    github.check_runs = [
        {"id": 1, "name": "api", "status": "in_progress"},
        {"id": 2, "name": "web", "status": "completed", "conclusion": "success"},
    ]
    _as(identity, acme, "member")
    clicked = (await client.post(f"{API}/{change_id}/follow")).json()["follow"]
    assert (clicked["stage"], clicked["checks"]["pending"], clicked["checks"]["passed"]) == (
        "checks",
        1,
        1,
    )
    github.check_runs[0] = {
        "id": 1,
        "name": "api",
        "status": "completed",
        "conclusion": "failure",
        "html_url": "https://github.com/run/1",
    }
    failed = await stage_at(2)
    assert (failed["stage"], failed["checks"]["failed"]) == ("checks_failed", ["api"])
    assert failed["checks"]["failed_url"] == "https://github.com/run/1"
    github.check_runs.append(
        {"id": 3, "name": "api", "status": "completed", "conclusion": "success"}
    )
    github.pull["mergeable"] = True
    assert (await stage_at(4))["stage"] == "ready"

    # A person merged it: a deployment from before is not its own; the one
    # after, holding its merge, is followed to its end.
    merged_at = now + timedelta(minutes=5)
    github.pull = {
        "state": "closed",
        "merged_at": _at(merged_at),
        "merge_commit_sha": "merge-sha",
        "head": {"sha": "new-commit"},
    }
    github.deployments = [
        {"id": 5, "sha": "old-sha", "environment": "production", "created_at": _at(now)},
    ]
    assert (await stage_at(6))["stage"] == "merged"
    github.deployments.insert(
        0,
        {
            "id": 6,
            "sha": "later-sha",
            "environment": "production",
            "created_at": _at(merged_at + timedelta(minutes=10)),
        },
    )
    github.deployment_states[6] = "in_progress"
    assert (await stage_at(16))["stage"] == "deploying"
    github.deployment_states[6] = "success"
    deployed = await stage_at(20)
    assert (deployed["stage"], deployed["done"], deployed["deployment"]["environment"]) == (
        "deployed",
        True,
        "production",
    )
    assert deployed["merged_at"] is not None

    # Done: no longer read; and never a merge, never a write after the PR.
    asked = len(github.asked)
    await follow_pull_requests(now=now + timedelta(minutes=30))
    assert len(github.asked) == asked
    assert not [path for path in (p for p, _ in github.writes()) if path.endswith("/merge")]
    assert [path for path, _ in github.writes()][-1] == f"/repos/{REPO}/pulls"


# ── undone, on asking (2026-10-20) ──────────────────────────────────────────


def test_a_diff_the_other_way_gives_the_file_back_as_it_was() -> None:
    path = "app/ledger.py"
    diff = diff_of(path, LEDGER, LEDGER_AFTER)[0]
    back = reversed_diff(diff)
    assert "-line 2 changed" in back and "+line 2" in back
    assert reversed_diff(back) == diff
    assert before_of(path, LEDGER_AFTER, diff) == (LEDGER, True)
    # A file it made: before, none; one it removed: before, the file.
    assert before_of("new.py", "x = 1\n", diff_of("new.py", None, "x = 1\n")[0]) == (None, True)
    assert before_of(path, None, diff_of(path, LEDGER, None)[0]) == (LEDGER, True)
    # A diff cut: it cannot say.
    assert before_of(path, LEDGER_AFTER, "x" * 200_000) == (None, False)


async def _config(workspace: uuid.UUID, source: uuid.UUID, **values: object) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE sources SET config = config || CAST(:v AS jsonb) WHERE id = :s"),
                {"v": json.dumps(values), "s": source},
            )
            await session.commit()


async def _merged(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID], github: GitHub
) -> tuple[uuid.UUID, str, datetime]:
    """A change accepted, its pull request merged by a person, deployed."""
    source = await _github_source(acme["acme"], pull_requests=True)
    github.extra["app/ledger.py"] = LEDGER
    change_id = await _proposed(acme["acme"], source, "app/ledger.py", LEDGER, LEDGER_AFTER)
    _as(identity, acme, "admin")
    assert (await client.post(f"{API}/{change_id}/accept", json={})).status_code == 200
    now = datetime.now(UTC)
    github.pull = {
        "state": "closed",
        "merged_at": _at(now),
        "merge_commit_sha": "merge-sha",
        "head": {"sha": "new-commit"},
    }
    github.deployments = [
        {"id": 6, "sha": "merge-sha", "environment": "production", "created_at": _at(now)}
    ]
    github.deployment_states[6] = "success"
    await follow_pull_requests(now=now + timedelta(minutes=1))
    # Merged: main holds it — and a newer line, far from it.
    github.moved["app/ledger.py"] = LEDGER_AFTER.replace("line 11\n", "line 11 newer\n")
    return source, str(change_id), now


async def test_a_merged_change_is_undone_by_a_change_proposed_on_the_branch_as_it_is(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github: GitHub,
) -> None:
    _source, change_id, _now = await _merged(client, identity, acme, github)
    read = (await client.get(f"{API}/{change_id}")).json()
    assert (read["follow"]["stage"], read["follow"]["before_sha"]) == ("deployed", "before-sha")
    assert read["follow"]["newer"] == 0

    # A member may not; an approver asks: the change that undoes it.
    _as(identity, acme, "member")
    assert (await client.post(f"{API}/{change_id}/undo")).status_code == 403
    _as(identity, acme, "admin")
    undone = await client.post(f"{API}/{change_id}/undo")
    assert undone.status_code == 200, undone.text
    revert = undone.json()
    assert (revert["status"], revert["reverts"]) == ("proposed", change_id)
    assert revert["title"].startswith("Annuler : ")
    [file] = revert["files"]
    assert "-line 2 changed" in file["diff"] and "+line 2" in file["diff"]
    # Asked again: the same one.
    assert (await client.post(f"{API}/{change_id}/undo")).json()["id"] == revert["id"]

    # Accepted like any other: its own pull request, the newer line kept.
    writes = len(github.writes())
    github.pull = {"state": "open", "head": {"sha": "new-commit"}}
    assert (await client.post(f"{API}/{revert['id']}/accept", json={})).status_code == 200
    trees = [b for p, b in github.writes()[writes:] if p.endswith("/git/trees") and b]
    assert trees[0]["tree"][0]["content"] == LEDGER.replace("line 11\n", "line 11 newer\n")


async def test_a_change_moved_where_it_was_cannot_be_undone_without_overwriting(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github: GitHub,
) -> None:
    _source, change_id, _now = await _merged(client, identity, acme, github)
    github.moved["app/ledger.py"] = LEDGER_AFTER.replace("line 3\n", "line 3 newer\n")
    refused = await client.post(f"{API}/{change_id}/undo")
    assert refused.status_code == 409
    assert refused.json()["error"]["details"][0]["message"] == "changed_since"
    # Already gone from main: said so.
    github.moved["app/ledger.py"] = LEDGER
    gone = await client.post(f"{API}/{change_id}/undo")
    assert gone.json()["error"]["details"][0]["message"] == "already_applied"


async def test_a_pull_request_not_merged_is_closed_when_undone(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github: GitHub,
) -> None:
    source = await _github_source(acme["acme"], pull_requests=True)
    github.extra["app/ledger.py"] = LEDGER
    change_id = await _proposed(acme["acme"], source, "app/ledger.py", LEDGER, LEDGER_AFTER)
    _as(identity, acme, "admin")
    assert (await client.post(f"{API}/{change_id}/accept", json={})).status_code == 200
    closed = await client.post(f"{API}/{change_id}/undo")
    assert closed.status_code == 200, closed.text
    assert (closed.json()["id"], closed.json()["follow"]["stage"]) == (str(change_id), "closed")
    assert (f"/repos/{REPO}/pulls/7", {"state": "closed"}) in github.writes()
    # Closed unmerged: nothing more to undo.
    again = await client.post(f"{API}/{change_id}/undo")
    assert again.json()["error"]["details"][0]["message"] == "already_closed"


async def test_going_back_starts_the_deployment_of_the_version_before_where_allowed(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github: GitHub,
) -> None:
    source, change_id, now = await _merged(client, identity, acme, github)
    # Not allowed by its source: refused, nothing started.
    refused = await client.post(f"{API}/{change_id}/rollback")
    assert refused.status_code == 409
    assert refused.json()["error"]["details"][0]["message"] == "deploys_off"
    assert not [p for p, _ in github.writes() if p.endswith("/dispatches")]

    await _config(acme["acme"], source, deploys=True, deploy_workflow="cd.yml")
    assert (await client.get(f"{API}/{change_id}")).json()["deploys_allowed"] is True
    _as(identity, acme, "member")
    assert (await client.post(f"{API}/{change_id}/rollback")).status_code == 403
    _as(identity, acme, "admin")
    asked = await client.post(f"{API}/{change_id}/rollback")
    assert asked.status_code == 200, asked.text
    done = asked.json()
    assert done["follow"]["stage"] == "rolling_back"
    [rollback] = done["rollbacks"]
    assert (rollback["sha"], rollback["state"]) == ("before-sha", "queued")
    dispatched = [
        b for p, b in github.writes() if p.endswith("/actions/workflows/cd.yml/dispatches")
    ]
    assert dispatched == [{"ref": "main", "inputs": {"release": "before-sha"}}]
    # Once at a time.
    again = await client.post(f"{API}/{change_id}/rollback")
    assert again.json()["error"]["details"][0]["message"] == "rolling_back"

    # Its run followed: running, then green — the version before is back.
    started = _at(datetime.now(UTC))
    github.runs = [
        {"status": "in_progress", "created_at": started, "html_url": "https://github.com/r/9"}
    ]
    await follow_pull_requests(now=now + timedelta(minutes=5))
    read = (await client.get(f"{API}/{change_id}")).json()
    assert (read["follow"]["stage"], read["rollbacks"][0]["state"]) == (
        "rolling_back",
        "in_progress",
    )
    github.runs[0] = {**github.runs[0], "status": "completed", "conclusion": "success"}
    await follow_pull_requests(now=now + timedelta(minutes=9))
    read = (await client.get(f"{API}/{change_id}")).json()
    assert (read["follow"]["stage"], read["follow"]["done"]) == ("rolled_back", True)
    assert read["rollbacks"][0]["url"] == "https://github.com/r/9"


async def test_a_change_followed_before_its_version_before_was_kept_still_goes_back(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github: GitHub,
) -> None:
    """2026-10-21: the first change LEKA shipped was followed to the end
    before the version before a merge was kept — going back reads it."""
    source, change_id, _now = await _merged(client, identity, acme, github)
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE code_changes SET follow = follow - 'before_sha' WHERE id = :c"),
                {"c": change_id},
            )
            await session.commit()
    assert (await client.get(f"{API}/{change_id}")).json()["follow"]["before_sha"] is None
    await _config(acme["acme"], source, deploys=True, deploy_workflow="cd.yml")
    github.newer = 3
    asked = await client.post(f"{API}/{change_id}/rollback")
    assert asked.status_code == 200, asked.text
    # And what main took since, said: going back takes it out too.
    assert (asked.json()["follow"]["before_sha"], asked.json()["follow"]["newer"]) == (
        "before-sha",
        3,
    )
    dispatched = [b for p, b in github.writes() if p.endswith("/workflows/cd.yml/dispatches")]
    assert dispatched == [{"ref": "main", "inputs": {"release": "before-sha"}}]


# ── a pull request in red, repaired on asking (2026-10-24) ─────────────────


def test_a_log_is_cut_to_where_it_fails_and_how_it_ends() -> None:
    lines = ["2026-10-24T16:20:01.1234567Z ##[group]Run npm test"]
    lines += [f"2026-10-24T16:20:02.0000000Z ok {n}" for n in range(2000)]
    lines += [
        "2026-10-24T16:21:00.0000000Z \x1b[31m FAIL \x1b[0m components/overview/overview.test.tsx",
        "2026-10-24T16:21:00.0000000Z TestingLibraryElementError: Unable to find overview-now",
    ]
    lines += [f"2026-10-24T16:21:01.0000000Z after {n}" for n in range(500)]
    lines += ["2026-10-24T16:22:00.0000000Z ##[error]Process completed with exit code 1."]
    said = log_excerpt("\n".join(lines))
    assert len(said) <= MOST_LOG
    # Its times, colours and groups out; where it fails, with what is around.
    assert "2026-10-24T" not in said and "\x1b" not in said and "##[group]" not in said
    assert " FAIL  components/overview/overview.test.tsx" in said
    assert "Unable to find overview-now" in said and "ok 1999" in said
    # How it ends; what is left out, said.
    assert said.endswith("##[error]Process completed with exit code 1.")
    assert "[…]" in said and "ok 10\n" not in said


def test_what_failed_names_its_files_as_paths_of_the_repository() -> None:
    failures = [
        {
            "name": "web",
            "annotations": [
                {"path": ".github", "message": "Process completed with exit code 1."},
                {
                    "path": "web/components/overview/overview.test.tsx",
                    "message": "at web/components/overview/home-sections.tsx:254",
                },
            ],
            "summary": "",
            "log": (
                " FAIL  components/overview/overview.test.tsx > the overview\n"
                "    at /home/runner/work/Leka/Leka/api/leka/main.py:12\n"
                "    at node_modules/react-dom/cjs/react-dom.development.js:100\n"
                "see https://example.com/a/b.html"
            ),
        }
    ]
    assert cited_paths(failures) == [
        "web/components/overview/overview.test.tsx",
        "web/components/overview/home-sections.tsx",
        "components/overview/overview.test.tsx",
        "api/leka/main.py",
    ]


def test_a_repair_whose_edits_do_not_land_is_asked_again_told_why() -> None:
    read = {"app/ledger.py": LEDGER}
    landing = RepairProposal(
        cause="c",
        files=[ProposedFile(path="app/ledger.py", edits=[Edit(find="line 2\n", replace="x\n")])],
    )
    assert repair_problems(landing, read) == []
    wrong = RepairProposal(
        cause="c",
        files=[
            ProposedFile(path="app/ledger.py", edits=[Edit(find="line 99\n", replace="x\n")]),
            ProposedFile(path="app/other.py", edits=[Edit(find="a", replace="b")]),
            ProposedFile(path="app/new.py", content="print(1)\n"),
        ],
    )
    problems = repair_problems(wrong, read)
    assert len(problems) == 2
    assert problems[0].startswith("app/ledger.py: an edit's `find` is not in the file")
    assert problems[1].startswith("app/other.py: you were not given this file")


TEST_LEDGER = (
    "from app.ledger import lines\n\n\ndef test_line_2():\n    assert lines()[1] == 'line 2'\n"
)
TEST_LEDGER_FIXED = TEST_LEDGER.replace("== 'line 2'", "== 'line 2 changed'")


def _red(github: GitHub) -> None:
    """Its pull request's head in red: the test that reads line 2 still
    expects it as it was."""
    github.at = {
        "base-sha": {"app/ledger.py": LEDGER, "tests/test_ledger.py": TEST_LEDGER},
        "new-commit": {"app/ledger.py": LEDGER_AFTER, "tests/test_ledger.py": TEST_LEDGER},
    }
    github.check_runs = [
        {"id": 10, "name": "api", "status": "completed", "conclusion": "success"},
        {
            "id": 11,
            "name": "web",
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://github.com/run/11",
            "app": {"slug": "github-actions"},
            "output": {"title": "1 test failed", "summary": ""},
        },
    ]
    github.annotations[11] = [
        {
            "path": "tests/test_ledger.py",
            "start_line": 5,
            "annotation_level": "failure",
            "title": "test_line_2",
            "message": "AssertionError: assert 'line 2 changed' == 'line 2'",
        },
        {"path": ".github", "annotation_level": "warning", "message": "Node.js 20 is deprecated"},
    ]
    github.logs[11] = (
        "2026-10-24T16:21:00.0000000Z FAILED tests/test_ledger.py::test_line_2\n"
        "2026-10-24T16:22:00.0000000Z ##[error]Process completed with exit code 1."
    )


def _fix(find: str = "== 'line 2'\n") -> dict[str, Any]:
    return {
        "cause": "Le test lit encore la ligne 2 telle qu'elle était avant le changement.",
        "summary": "Le test attend la ligne 2 telle que le changement l'écrit.",
        "files": [
            {
                "path": "tests/test_ledger.py",
                "edits": [
                    {
                        "find": f"    assert lines()[1] {find}",
                        "replace": "    assert lines()[1] == 'line 2 changed'\n",
                    }
                ],
            }
        ],
    }


async def _applied_in_red(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID], github: GitHub
) -> uuid.UUID:
    source = await _github_source(acme["acme"], pull_requests=True)
    github.extra["app/ledger.py"] = LEDGER
    change_id = await _proposed(acme["acme"], source, "app/ledger.py", LEDGER, LEDGER_AFTER)
    _as(identity, acme, "admin")
    assert (await client.post(f"{API}/{change_id}/accept", json={})).status_code == 200
    _red(github)
    followed = (await client.post(f"{API}/{change_id}/follow")).json()["follow"]
    assert (followed["stage"], followed["checks"]["failed"]) == ("checks_failed", ["web"])
    return change_id


async def test_a_pull_request_in_red_is_repaired_on_its_branch_and_its_checks_run_again(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github: GitHub,
    leka_gemini: Callable[..., Script],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repairs: list[uuid.UUID] = []

    async def queue(workspace_id: uuid.UUID, change_id: uuid.UUID) -> bool:
        repairs.append(change_id)
        return True

    monkeypatch.setattr(code_changes_api, "queue_repair", queue)
    change_id = await _applied_in_red(client, identity, acme, github)
    repair = f"{API}/{change_id}/repair"

    # A member may not; who may approve asks it — a worker does it.
    _as(identity, acme, "member")
    assert (await client.post(repair)).status_code == 403
    _as(identity, acme, "admin")
    asked = await client.post(repair)
    assert asked.status_code == 202, asked.text
    [running] = asked.json()["repairs"]
    assert (running["state"], running["failed"]) == ("running", ["web"])
    assert repairs == [change_id]
    # Asked twice while it runs: one.
    assert (await client.post(repair)).json()["error"]["details"][0]["message"] == "repairing"

    # The model's first fix copies a line that is not there: asked again,
    # told why — its second lands.
    script = leka_gemini(gemini(json.dumps(_fix("== 'line two'\n"))), gemini(json.dumps(_fix())))
    pushed = len(github.writes())
    assert await repair_change(acme["acme"], change_id) == {
        "state": "pushed",
        "commit": "fix-commit",
    }
    assert len(script.asked) == 2
    material = json.loads(script.asked[0]["contents"][-1]["parts"][0]["text"])
    # What failed, as GitHub said it — its log fetched without the token —
    # and the files at the pull request's head, its own and those named.
    [failed] = material["failed"]
    assert failed["check"] == "web"
    assert [a["path"] for a in failed["annotations"]] == ["tests/test_ledger.py"]
    assert "FAILED tests/test_ledger.py::test_line_2" in failed["log"]
    assert material["files"] == {
        "app/ledger.py": LEDGER_AFTER,
        "tests/test_ledger.py": TEST_LEDGER,
    }
    assert "+line 2 changed" in material["change"]["diff"]
    again = json.dumps(script.asked[1])
    assert "tests/test_ledger.py: an edit" in again

    # One commit on its branch, on top of its head, never forced.
    writes = github.writes()[pushed:]
    tree = next(body for path, body in writes if path.endswith("/git/trees"))
    assert tree == {
        "base_tree": "head-tree",
        "tree": [
            {
                "path": "tests/test_ledger.py",
                "mode": "100644",
                "type": "blob",
                "content": TEST_LEDGER_FIXED,
            }
        ],
    }
    commit = next(body for path, body in writes if path.endswith("/git/commits"))
    assert commit is not None and commit["parents"] == ["new-commit"]
    assert commit["message"].startswith("Le test attend la ligne 2")
    read = (await client.get(f"{API}/{change_id}")).json()
    [ref] = [(path, body) for path, body in writes if "/git/refs/heads/" in path]
    assert ref == (
        f"/repos/{REPO}/git/refs/heads/{read['branch']}",
        {"sha": "fix-commit", "force": False},
    )
    assert not [path for path, _ in writes if path.endswith(("/merge", "/pulls"))]

    # Said: what failed, why, what it fixed, by which model; its checks run
    # again; the change holds what its pull request holds — so undoing it
    # undoes the repair too.
    [done] = read["repairs"]
    assert (done["state"], done["commit"], done["model"]) == (
        "pushed",
        "fix-commit",
        "gemini-3.8-flash",
    )
    assert done["cause"].startswith("Le test lit encore la ligne 2")
    [fixed] = done["files"]
    assert (
        fixed["path"] == "tests/test_ledger.py"
        and "+    assert lines()[1] == 'line 2 changed'" in fixed["diff"]
    )
    assert read["follow"]["stage"] == "checks"
    assert [f["path"] for f in read["files"]] == ["app/ledger.py", "tests/test_ledger.py"]
    assert read["files"][1]["why"].startswith("réparation : ")
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            kept = await session.get(CodeChange, change_id)
            assert kept is not None and kept.commit_sha == "fix-commit"
            assert kept.files[1]["content"] == TEST_LEDGER_FIXED


async def test_a_repair_says_why_it_wrote_nothing_and_what_it_may_not_do(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    github: GitHub,
    leka_gemini: Callable[..., Script],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def queue(workspace_id: uuid.UUID, change_id: uuid.UUID) -> bool:
        return True

    monkeypatch.setattr(code_changes_api, "queue_repair", queue)
    change_id = await _applied_in_red(client, identity, acme, github)
    repair = f"{API}/{change_id}/repair"

    # The cause is not in the code: said, nothing written.
    assert (await client.post(repair)).status_code == 202
    outside = {"cause": "Le runner n'a pas démarré : rien à corriger dans le code.", "files": []}
    leka_gemini(gemini(json.dumps(outside)))
    pushed = len(github.writes())
    assert (await repair_change(acme["acme"], change_id))["state"] == "outside"
    assert github.writes()[pushed:] == []
    said = (await client.get(f"{API}/{change_id}")).json()["repairs"][-1]
    assert (said["state"], said["cause"]) == ("outside", outside["cause"])

    # Its branch moved meanwhile: said, never forced.
    assert (await client.post(repair)).status_code == 202
    github.branch_moved = True
    leka_gemini(gemini(json.dumps(_fix())))
    assert (await repair_change(acme["acme"], change_id))["state"] == "failed"
    said = (await client.get(f"{API}/{change_id}")).json()["repairs"][-1]
    assert (said["state"], said["error"]) == ("failed", "moved")
    github.branch_moved = False

    # Closed in red by a person: reopened, then repaired.
    github.pull["state"] = "closed"
    assert (await client.post(repair)).status_code == 202
    leka_gemini(gemini(json.dumps(_fix())))
    assert (await repair_change(acme["acme"], change_id))["state"] == "pushed"
    assert ("/repos/acme/payments/pulls/7", {"state": "open"}) in github.writes()
    said = (await client.get(f"{API}/{change_id}")).json()["repairs"][-1]
    assert said["reopened"] is True

    # Nothing in red any more: said, nothing asked of a model.
    github.check_runs = [{"id": 12, "name": "web", "status": "completed", "conclusion": "success"}]
    assert (await client.post(repair)).status_code == 202
    assert (await repair_change(acme["acme"], change_id))["state"] == "unneeded"

    # Merged: nothing left to repair on its branch.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            kept = await session.get(CodeChange, change_id)
            assert kept is not None
            kept.follow = {
                **(kept.follow or {}),
                "stage": "merged",
                "merged_at": "2026-10-24T18:00:00Z",
            }
            await session.commit()
    merged = await client.post(repair)
    assert (merged.status_code, merged.json()["error"]["details"][0]["message"]) == (409, "merged")
